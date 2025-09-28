"""
Telemetry Monitor for LLM Drone Controller

Real-time monitoring and data aggregation for drone telemetry data
with health monitoring, alerts, and data persistence.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

from mavsdk import System
from mavsdk.telemetry import (
    Position, Battery, FlightMode, Health, RcStatus,
    EulerAngle, VelocityNed, GpsInfo, LandedState
)

from .utils.config import Config
from .utils.validators import TelemetryValidation


class HealthStatus(Enum):
    """Overall health status"""
    EXCELLENT = "excellent"
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class TelemetryAlert:
    """Telemetry alert message"""
    timestamp: datetime
    drone_id: str
    level: AlertLevel
    source: str
    message: str
    resolved: bool = False
    resolution_time: Optional[datetime] = None


@dataclass
class DroneHealthMetrics:
    """Comprehensive health metrics for a drone"""
    drone_id: str
    timestamp: datetime
    overall_status: HealthStatus

    # Position and navigation
    position: Optional[Position] = None
    gps_info: Optional[GpsInfo] = None
    attitude: Optional[EulerAngle] = None
    velocity: Optional[VelocityNed] = None

    # System health
    battery: Optional[Battery] = None
    health: Optional[Health] = None
    flight_mode: Optional[FlightMode] = None
    is_armed: bool = False
    landed_state: Optional[LandedState] = None

    # Communication
    rc_status: Optional[RcStatus] = None

    # Derived metrics
    altitude_agl_m: float = 0.0
    speed_ms: float = 0.0
    distance_to_home_m: float = 0.0
    flight_time_s: float = 0.0
    estimated_remaining_time_s: Optional[float] = None

    # Health indicators
    gps_satellite_count: int = 0
    battery_percentage: float = 0.0
    battery_voltage_v: float = 0.0
    connection_quality: float = 100.0


class TelemetryMonitor:
    """Monitor telemetry for a single drone"""

    def __init__(self, drone: System, drone_id: str, config: Config):
        self.drone = drone
        self.drone_id = drone_id
        self.config = config
        self.logger = logging.getLogger(f"TelemetryMonitor.{drone_id}")

        self.latest_metrics: Optional[DroneHealthMetrics] = None
        self.alerts: List[TelemetryAlert] = []
        self.data_callbacks: List[Callable[[DroneHealthMetrics], None]] = []
        self.alert_callbacks: List[Callable[[TelemetryAlert], None]] = []

        self._monitoring_task: Optional[asyncio.Task] = None
        self._cancel_event = asyncio.Event()

        # Monitoring parameters
        self.update_interval_s = config.telemetry.update_interval_s
        self.alert_retention_hours = config.telemetry.alert_retention_hours
        self.health_check_interval_s = 5.0

        # Health thresholds
        self.battery_warning_pct = config.drone.battery_warning_threshold
        self.battery_critical_pct = config.drone.battery_critical_threshold
        self.gps_min_satellites = config.drone.min_gps_satellites
        self.max_altitude_m = config.search.max_altitude_m

        # State tracking
        self.arm_time: Optional[datetime] = None
        self.takeoff_position: Optional[Position] = None
        self.last_position: Optional[Position] = None
        self.last_health_check = datetime.now()

    async def start_monitoring(self) -> bool:
        """Start telemetry monitoring"""
        try:
            self.logger.info(f"Starting telemetry monitoring for {self.drone_id}")

            # Reset state
            self._cancel_event.clear()
            self.arm_time = None
            self.takeoff_position = None

            # Start monitoring task
            self._monitoring_task = asyncio.create_task(self._monitor_telemetry())

            return True

        except Exception as e:
            self.logger.error(f"Failed to start telemetry monitoring: {e}")
            return False

    async def stop_monitoring(self):
        """Stop telemetry monitoring"""
        try:
            self.logger.info(f"Stopping telemetry monitoring for {self.drone_id}")

            # Cancel monitoring
            if self._monitoring_task:
                self._cancel_event.set()
                await asyncio.wait_for(self._monitoring_task, timeout=5.0)

        except asyncio.TimeoutError:
            self.logger.warning("Telemetry monitoring stop timeout")
            if self._monitoring_task:
                self._monitoring_task.cancel()
        except Exception as e:
            self.logger.error(f"Error stopping telemetry monitoring: {e}")

    async def _monitor_telemetry(self):
        """Main telemetry monitoring loop"""
        try:
            # Set up telemetry subscriptions
            position_task = asyncio.create_task(self._monitor_position())
            battery_task = asyncio.create_task(self._monitor_battery())
            health_task = asyncio.create_task(self._monitor_health())
            flight_mode_task = asyncio.create_task(self._monitor_flight_mode())
            armed_task = asyncio.create_task(self._monitor_armed_state())
            gps_task = asyncio.create_task(self._monitor_gps())
            attitude_task = asyncio.create_task(self._monitor_attitude())
            velocity_task = asyncio.create_task(self._monitor_velocity())

            # Wait for cancellation
            await self._cancel_event.wait()

            # Cancel all tasks
            tasks = [position_task, battery_task, health_task, flight_mode_task,
                    armed_task, gps_task, attitude_task, velocity_task]

            for task in tasks:
                task.cancel()

            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            self.logger.error(f"Telemetry monitoring error: {e}")

    async def _monitor_position(self):
        """Monitor position telemetry"""
        try:
            async for position in self.drone.telemetry.position():
                if self._cancel_event.is_set():
                    break

                self.last_position = position
                await self._update_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Position monitoring error: {e}")

    async def _monitor_battery(self):
        """Monitor battery telemetry"""
        try:
            async for battery in self.drone.telemetry.battery():
                if self._cancel_event.is_set():
                    break

                # Check battery alerts
                await self._check_battery_health(battery)
                await self._update_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Battery monitoring error: {e}")

    async def _monitor_health(self):
        """Monitor system health"""
        try:
            async for health in self.drone.telemetry.health():
                if self._cancel_event.is_set():
                    break

                await self._check_system_health(health)
                await self._update_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Health monitoring error: {e}")

    async def _monitor_flight_mode(self):
        """Monitor flight mode changes"""
        try:
            async for flight_mode in self.drone.telemetry.flight_mode():
                if self._cancel_event.is_set():
                    break

                self.logger.info(f"Flight mode changed to: {flight_mode}")
                await self._update_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Flight mode monitoring error: {e}")

    async def _monitor_armed_state(self):
        """Monitor armed state changes"""
        try:
            async for is_armed in self.drone.telemetry.armed():
                if self._cancel_event.is_set():
                    break

                if is_armed and self.arm_time is None:
                    self.arm_time = datetime.now()
                    self.logger.info(f"Drone {self.drone_id} armed")
                elif not is_armed and self.arm_time is not None:
                    self.arm_time = None
                    self.logger.info(f"Drone {self.drone_id} disarmed")

                await self._update_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Armed state monitoring error: {e}")

    async def _monitor_gps(self):
        """Monitor GPS information"""
        try:
            async for gps_info in self.drone.telemetry.gps_info():
                if self._cancel_event.is_set():
                    break

                await self._check_gps_health(gps_info)
                await self._update_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"GPS monitoring error: {e}")

    async def _monitor_attitude(self):
        """Monitor attitude telemetry"""
        try:
            async for attitude in self.drone.telemetry.attitude_euler():
                if self._cancel_event.is_set():
                    break

                await self._update_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Attitude monitoring error: {e}")

    async def _monitor_velocity(self):
        """Monitor velocity telemetry"""
        try:
            async for velocity in self.drone.telemetry.velocity_ned():
                if self._cancel_event.is_set():
                    break

                await self._update_metrics()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Velocity monitoring error: {e}")

    async def _update_metrics(self):
        """Update comprehensive health metrics"""
        try:
            # Collect current telemetry
            current_metrics = DroneHealthMetrics(
                drone_id=self.drone_id,
                timestamp=datetime.now(),
                overall_status=HealthStatus.UNKNOWN
            )

            # Get latest telemetry data (this is simplified - in reality we'd cache the latest values)
            # For now, we'll use placeholder logic

            # Calculate derived metrics
            if self.last_position:
                current_metrics.altitude_agl_m = self.last_position.relative_altitude_m

                # Calculate distance to home if we have takeoff position
                if self.takeoff_position:
                    current_metrics.distance_to_home_m = self._calculate_distance(
                        self.last_position, self.takeoff_position
                    )

            # Calculate flight time
            if self.arm_time:
                current_metrics.flight_time_s = (datetime.now() - self.arm_time).total_seconds()

            # Determine overall health status
            current_metrics.overall_status = self._assess_overall_health(current_metrics)

            # Update latest metrics
            self.latest_metrics = current_metrics

            # Notify callbacks
            self._notify_data_callbacks(current_metrics)

        except Exception as e:
            self.logger.error(f"Error updating metrics: {e}")

    async def _check_battery_health(self, battery: Battery):
        """Check battery health and generate alerts"""
        try:
            battery_pct = battery.remaining_percent * 100

            if battery_pct <= self.battery_critical_pct:
                await self._create_alert(
                    AlertLevel.CRITICAL,
                    "battery",
                    f"Critical battery level: {battery_pct:.1f}%"
                )
            elif battery_pct <= self.battery_warning_pct:
                await self._create_alert(
                    AlertLevel.WARNING,
                    "battery",
                    f"Low battery level: {battery_pct:.1f}%"
                )

        except Exception as e:
            self.logger.error(f"Error checking battery health: {e}")

    async def _check_gps_health(self, gps_info: GpsInfo):
        """Check GPS health and generate alerts"""
        try:
            if gps_info.num_satellites < self.gps_min_satellites:
                await self._create_alert(
                    AlertLevel.WARNING,
                    "gps",
                    f"Low GPS satellite count: {gps_info.num_satellites}"
                )

        except Exception as e:
            self.logger.error(f"Error checking GPS health: {e}")

    async def _check_system_health(self, health: Health):
        """Check system health and generate alerts"""
        try:
            if not health.is_global_position_ok:
                await self._create_alert(
                    AlertLevel.WARNING,
                    "navigation",
                    "Global position not available"
                )

            if not health.is_home_position_ok:
                await self._create_alert(
                    AlertLevel.WARNING,
                    "navigation",
                    "Home position not set"
                )

        except Exception as e:
            self.logger.error(f"Error checking system health: {e}")

    def _assess_overall_health(self, metrics: DroneHealthMetrics) -> HealthStatus:
        """Assess overall health status based on all metrics"""
        # Check for critical conditions
        critical_alerts = [alert for alert in self.alerts
                          if alert.level == AlertLevel.CRITICAL and not alert.resolved]
        if critical_alerts:
            return HealthStatus.CRITICAL

        # Check for warnings
        warning_alerts = [alert for alert in self.alerts
                         if alert.level == AlertLevel.WARNING and not alert.resolved]
        if warning_alerts:
            return HealthStatus.WARNING

        # If we have good position and battery data
        if metrics.battery_percentage > self.battery_warning_pct and metrics.gps_satellite_count >= self.gps_min_satellites:
            return HealthStatus.EXCELLENT
        else:
            return HealthStatus.GOOD

    async def _create_alert(self, level: AlertLevel, source: str, message: str):
        """Create and store a new alert"""
        alert = TelemetryAlert(
            timestamp=datetime.now(),
            drone_id=self.drone_id,
            level=level,
            source=source,
            message=message
        )

        self.alerts.append(alert)
        self.logger.log(
            logging.CRITICAL if level == AlertLevel.CRITICAL else logging.WARNING,
            f"Alert: {message}"
        )

        # Notify alert callbacks
        self._notify_alert_callbacks(alert)

        # Clean up old alerts
        await self._cleanup_old_alerts()

    async def _cleanup_old_alerts(self):
        """Remove old resolved alerts"""
        cutoff_time = datetime.now() - timedelta(hours=self.alert_retention_hours)
        self.alerts = [alert for alert in self.alerts
                      if alert.timestamp > cutoff_time or not alert.resolved]

    def _calculate_distance(self, pos1: Position, pos2: Position) -> float:
        """Calculate distance between two positions in meters"""
        # Simple haversine distance calculation
        import math

        lat1, lon1 = math.radians(pos1.latitude_deg), math.radians(pos1.longitude_deg)
        lat2, lon2 = math.radians(pos2.latitude_deg), math.radians(pos2.longitude_deg)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))

        # Earth radius in meters
        r = 6371000

        return c * r

    def add_data_callback(self, callback: Callable[[DroneHealthMetrics], None]):
        """Add callback for telemetry data updates"""
        self.data_callbacks.append(callback)

    def add_alert_callback(self, callback: Callable[[TelemetryAlert], None]):
        """Add callback for alert notifications"""
        self.alert_callbacks.append(callback)

    def _notify_data_callbacks(self, metrics: DroneHealthMetrics):
        """Notify all data callbacks"""
        for callback in self.data_callbacks:
            try:
                callback(metrics)
            except Exception as e:
                self.logger.error(f"Error in data callback: {e}")

    def _notify_alert_callbacks(self, alert: TelemetryAlert):
        """Notify all alert callbacks"""
        for callback in self.alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                self.logger.error(f"Error in alert callback: {e}")

    def get_latest_metrics(self) -> Optional[DroneHealthMetrics]:
        """Get the latest health metrics"""
        return self.latest_metrics

    def get_active_alerts(self) -> List[TelemetryAlert]:
        """Get all unresolved alerts"""
        return [alert for alert in self.alerts if not alert.resolved]

    def resolve_alert(self, alert_index: int) -> bool:
        """Mark an alert as resolved"""
        try:
            if 0 <= alert_index < len(self.alerts):
                self.alerts[alert_index].resolved = True
                self.alerts[alert_index].resolution_time = datetime.now()
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error resolving alert: {e}")
            return False


class MultiDroneTelemetryAggregator:
    """Aggregate telemetry from multiple drones"""

    def __init__(self, monitors: Dict[str, TelemetryMonitor]):
        self.monitors = monitors
        self.logger = logging.getLogger("TelemetryAggregator")

        self.aggregated_data: Dict[str, DroneHealthMetrics] = {}
        self.all_alerts: List[TelemetryAlert] = []

        # Set up callbacks
        for monitor in self.monitors.values():
            monitor.add_data_callback(self._on_drone_data_update)
            monitor.add_alert_callback(self._on_drone_alert)

    def _on_drone_data_update(self, metrics: DroneHealthMetrics):
        """Handle data update from a drone"""
        self.aggregated_data[metrics.drone_id] = metrics

    def _on_drone_alert(self, alert: TelemetryAlert):
        """Handle alert from a drone"""
        self.all_alerts.append(alert)

    def get_fleet_summary(self) -> Dict[str, Any]:
        """Get summary of entire drone fleet"""
        summary = {
            "total_drones": len(self.monitors),
            "active_drones": 0,
            "healthy_drones": 0,
            "warning_drones": 0,
            "critical_drones": 0,
            "total_alerts": len([a for a in self.all_alerts if not a.resolved]),
            "critical_alerts": len([a for a in self.all_alerts
                                  if a.level == AlertLevel.CRITICAL and not a.resolved]),
            "average_battery": 0.0,
            "total_flight_time": 0.0
        }

        if self.aggregated_data:
            battery_sum = 0
            flight_time_sum = 0

            for metrics in self.aggregated_data.values():
                summary["active_drones"] += 1
                battery_sum += metrics.battery_percentage
                flight_time_sum += metrics.flight_time_s

                if metrics.overall_status == HealthStatus.EXCELLENT:
                    summary["healthy_drones"] += 1
                elif metrics.overall_status == HealthStatus.WARNING:
                    summary["warning_drones"] += 1
                elif metrics.overall_status == HealthStatus.CRITICAL:
                    summary["critical_drones"] += 1

            summary["average_battery"] = battery_sum / len(self.aggregated_data)
            summary["total_flight_time"] = flight_time_sum

        return summary

    def get_drone_metrics(self, drone_id: str) -> Optional[DroneHealthMetrics]:
        """Get metrics for a specific drone"""
        return self.aggregated_data.get(drone_id)

    def get_all_alerts(self, resolved: bool = False) -> List[TelemetryAlert]:
        """Get all alerts, optionally including resolved ones"""
        if resolved:
            return self.all_alerts
        else:
            return [alert for alert in self.all_alerts if not alert.resolved]

    def get_critical_alerts(self) -> List[TelemetryAlert]:
        """Get all critical unresolved alerts"""
        return [alert for alert in self.all_alerts
                if alert.level == AlertLevel.CRITICAL and not alert.resolved]

    async def start_all_monitoring(self) -> bool:
        """Start monitoring for all drones"""
        try:
            results = []
            for monitor in self.monitors.values():
                result = await monitor.start_monitoring()
                results.append(result)

            return all(results)

        except Exception as e:
            self.logger.error(f"Error starting all monitoring: {e}")
            return False

    async def stop_all_monitoring(self):
        """Stop monitoring for all drones"""
        try:
            tasks = []
            for monitor in self.monitors.values():
                tasks.append(monitor.stop_monitoring())

            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            self.logger.error(f"Error stopping all monitoring: {e}")