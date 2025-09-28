"""Multi-drone management using MAVSDK for LLM Drone Controller."""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan
from mavsdk.offboard import PositionNedYaw, VelocityNedYaw
from mavsdk.action import ActionError
from mavsdk.mission import MissionError

from .utils.config import Config, get_config
from .utils.validators import GPSCoordinate, Waypoint, DroneCapabilities, TelemetryValidation


@dataclass
class DroneStatus:
    """Drone status information."""

    id: int
    connected: bool = False
    armed: bool = False
    in_air: bool = False
    battery_percent: float = 0.0
    battery_voltage: float = 0.0
    position: Optional[GPSCoordinate] = None
    altitude: float = 0.0
    heading: float = 0.0
    ground_speed: float = 0.0
    gps_satellites: int = 0
    flight_mode: str = "UNKNOWN"
    mission_active: bool = False
    mission_progress: int = 0
    last_update: Optional[datetime] = None


class DroneManager:
    """Individual drone management class."""

    def __init__(self, drone_id: int, connection_string: str, config: Config):
        """Initialize drone manager."""
        self.drone_id = drone_id
        self.connection_string = connection_string
        self.config = config
        self.drone = System()
        self.status = DroneStatus(id=drone_id)
        self.capabilities = DroneCapabilities()

        # State tracking
        self._telemetry_task: Optional[asyncio.Task] = None
        self._mission_items: List[MissionItem] = []
        self._emergency_mode = False

        # Setup logging
        self.logger = logging.getLogger(f"drone_{drone_id}")

    async def connect(self) -> bool:
        """Connect to the drone."""
        try:
            self.logger.info(f"Connecting to drone {self.drone_id} at {self.connection_string}")
            await self.drone.connect(system_address=self.connection_string)

            # Wait for connection with timeout
            connection_timeout = self.config.drone.timeout_seconds
            start_time = datetime.now()

            async for state in self.drone.core.connection_state():
                if state.is_connected:
                    self.status.connected = True
                    self.logger.info(f"Drone {self.drone_id} connected successfully")

                    # Start telemetry monitoring
                    await self._start_telemetry_monitoring()
                    return True

                if (datetime.now() - start_time).total_seconds() > connection_timeout:
                    break

            self.logger.error(f"Connection timeout for drone {self.drone_id}")
            return False

        except Exception as e:
            self.logger.error(f"Failed to connect drone {self.drone_id}: {e}")
            return False

    async def _start_telemetry_monitoring(self):
        """Start background telemetry monitoring."""
        if self._telemetry_task and not self._telemetry_task.done():
            return

        self._telemetry_task = asyncio.create_task(self._telemetry_loop())

    async def _telemetry_loop(self):
        """Background telemetry monitoring loop."""
        try:
            while self.status.connected:
                await self._update_telemetry()
                await asyncio.sleep(1.0 / self.config.telemetry.update_rate_hz)
        except asyncio.CancelledError:
            self.logger.info(f"Telemetry monitoring stopped for drone {self.drone_id}")
        except Exception as e:
            self.logger.error(f"Telemetry loop error for drone {self.drone_id}: {e}")

    async def _update_telemetry(self):
        """Update drone telemetry data."""
        try:
            # Get position
            position = await self.drone.telemetry.position().__anext__()
            self.status.position = GPSCoordinate(
                latitude=position.latitude_deg,
                longitude=position.longitude_deg,
                altitude=position.absolute_altitude_m
            )
            self.status.altitude = position.relative_altitude_m

            # Get battery
            battery = await self.drone.telemetry.battery().__anext__()
            self.status.battery_percent = battery.remaining_percent
            self.status.battery_voltage = battery.voltage_v

            # Get GPS info
            gps = await self.drone.telemetry.gps_info().__anext__()
            self.status.gps_satellites = gps.num_satellites

            # Get flight mode
            flight_mode = await self.drone.telemetry.flight_mode().__anext__()
            self.status.flight_mode = str(flight_mode)

            # Get armed state
            armed = await self.drone.telemetry.armed().__anext__()
            self.status.armed = armed

            # Get in-air state
            in_air = await self.drone.telemetry.in_air().__anext__()
            self.status.in_air = in_air

            # Get heading and ground speed
            attitude = await self.drone.telemetry.attitude_euler().__anext__()
            self.status.heading = attitude.yaw_deg

            velocity = await self.drone.telemetry.velocity_ned().__anext__()
            self.status.ground_speed = math.sqrt(velocity.north_m_s**2 + velocity.east_m_s**2)

            self.status.last_update = datetime.now()

            # Check for emergency conditions
            await self._check_emergency_conditions()

        except Exception as e:
            self.logger.warning(f"Telemetry update failed for drone {self.drone_id}: {e}")

    async def _check_emergency_conditions(self):
        """Check for emergency conditions and take action."""
        if not self.config.safety.emergency_land_enabled:
            return

        # Low battery check
        if (self.status.battery_percent < self.config.safety.low_battery_threshold and
            self.status.in_air and not self._emergency_mode):

            self.logger.warning(f"Drone {self.drone_id}: Low battery ({self.status.battery_percent}%), initiating emergency landing")
            await self.emergency_land()

        # GPS loss check
        if self.status.gps_satellites < 6 and self.status.in_air and not self._emergency_mode:
            self.logger.warning(f"Drone {self.drone_id}: Poor GPS signal ({self.status.gps_satellites} satellites), initiating emergency landing")
            await self.emergency_land()

    async def wait_for_global_position(self) -> bool:
        """Wait for drone to have global position fix."""
        try:
            timeout = self.config.drone.timeout_seconds
            start_time = datetime.now()

            async for health in self.drone.telemetry.health():
                if health.is_global_position_ok and health.is_home_position_ok:
                    self.logger.info(f"Drone {self.drone_id}: Global position fix acquired")
                    return True

                if (datetime.now() - start_time).total_seconds() > timeout:
                    break

            self.logger.error(f"Drone {self.drone_id}: Timeout waiting for global position")
            return False

        except Exception as e:
            self.logger.error(f"Error waiting for global position on drone {self.drone_id}: {e}")
            return False

    async def arm_and_takeoff(self, altitude: Optional[float] = None) -> bool:
        """Arm drone and takeoff to specified altitude."""
        try:
            if not self.status.connected:
                self.logger.error(f"Drone {self.drone_id}: Cannot takeoff - not connected")
                return False

            # Use default altitude if not specified
            target_altitude = altitude or self.config.drone.default_altitude

            self.logger.info(f"Drone {self.drone_id}: Arming and taking off to {target_altitude}m")

            # Wait for global position
            if not await self.wait_for_global_position():
                return False

            # Arm the drone
            await self.drone.action.arm()
            self.logger.info(f"Drone {self.drone_id}: Armed")

            # Set takeoff altitude
            await self.drone.action.set_takeoff_altitude(target_altitude)

            # Takeoff
            await self.drone.action.takeoff()
            self.logger.info(f"Drone {self.drone_id}: Takeoff initiated")

            # Wait for takeoff to complete
            await self._wait_for_altitude(target_altitude, tolerance=2.0)

            return True

        except ActionError as e:
            self.logger.error(f"Drone {self.drone_id}: Takeoff failed - {e}")
            return False
        except Exception as e:
            self.logger.error(f"Drone {self.drone_id}: Unexpected error during takeoff - {e}")
            return False

    async def _wait_for_altitude(self, target_altitude: float, tolerance: float = 2.0):
        """Wait for drone to reach target altitude."""
        timeout = 60  # 60 seconds timeout
        start_time = datetime.now()

        while (datetime.now() - start_time).total_seconds() < timeout:
            if abs(self.status.altitude - target_altitude) <= tolerance:
                self.logger.info(f"Drone {self.drone_id}: Reached target altitude {target_altitude}m")
                return True
            await asyncio.sleep(1)

        self.logger.warning(f"Drone {self.drone_id}: Timeout waiting for altitude {target_altitude}m")

    async def land(self) -> bool:
        """Land the drone."""
        try:
            if not self.status.in_air:
                self.logger.info(f"Drone {self.drone_id}: Already on ground")
                return True

            self.logger.info(f"Drone {self.drone_id}: Landing")
            await self.drone.action.land()

            # Wait for landing
            timeout = 60
            start_time = datetime.now()

            while (datetime.now() - start_time).total_seconds() < timeout:
                if not self.status.in_air:
                    self.logger.info(f"Drone {self.drone_id}: Landed successfully")
                    return True
                await asyncio.sleep(1)

            self.logger.warning(f"Drone {self.drone_id}: Landing timeout")
            return False

        except Exception as e:
            self.logger.error(f"Drone {self.drone_id}: Landing failed - {e}")
            return False

    async def emergency_land(self) -> bool:
        """Perform emergency landing."""
        try:
            self._emergency_mode = True
            self.logger.warning(f"Drone {self.drone_id}: EMERGENCY LANDING initiated")

            # Cancel any active mission
            await self.drone.mission.pause_mission()

            # Emergency land
            await self.drone.action.land()

            return True

        except Exception as e:
            self.logger.error(f"Drone {self.drone_id}: Emergency landing failed - {e}")
            return False

    async def return_to_launch(self) -> bool:
        """Return drone to launch position."""
        try:
            self.logger.info(f"Drone {self.drone_id}: Returning to launch")
            await self.drone.action.return_to_launch()
            return True

        except Exception as e:
            self.logger.error(f"Drone {self.drone_id}: RTL failed - {e}")
            return False

    async def upload_mission(self, waypoints: List[Waypoint]) -> bool:
        """Upload mission waypoints to drone."""
        try:
            if not waypoints:
                self.logger.error(f"Drone {self.drone_id}: No waypoints provided")
                return False

            self.logger.info(f"Drone {self.drone_id}: Uploading mission with {len(waypoints)} waypoints")

            # Convert waypoints to MAVSDK mission items
            mission_items = []
            for i, wp in enumerate(waypoints):
                wp_dict = wp.to_mavsdk_dict()

                mission_item = MissionItem(
                    wp_dict["lat"],
                    wp_dict["lon"],
                    wp_dict["alt"],
                    wp_dict["speed"],
                    is_fly_through=True,
                    gimbal_pitch_deg=wp_dict["gimbal_pitch"],
                    gimbal_yaw_deg=wp_dict["gimbal_yaw"],
                    camera_action=MissionItem.CameraAction.NONE,
                    loiter_time_s=wp_dict["loiter_time"],
                    camera_photo_interval_s=wp_dict["photo_interval"]
                )
                mission_items.append(mission_item)

            # Create mission plan
            mission_plan = MissionPlan(mission_items)

            # Upload mission
            await self.drone.mission.upload_mission(mission_plan)
            self._mission_items = mission_items

            self.logger.info(f"Drone {self.drone_id}: Mission uploaded successfully")
            return True

        except MissionError as e:
            self.logger.error(f"Drone {self.drone_id}: Mission upload failed - {e}")
            return False
        except Exception as e:
            self.logger.error(f"Drone {self.drone_id}: Unexpected error during mission upload - {e}")
            return False

    async def start_mission(self) -> bool:
        """Start the uploaded mission."""
        try:
            if not self._mission_items:
                self.logger.error(f"Drone {self.drone_id}: No mission uploaded")
                return False

            self.logger.info(f"Drone {self.drone_id}: Starting mission")
            await self.drone.mission.start_mission()
            self.status.mission_active = True

            return True

        except Exception as e:
            self.logger.error(f"Drone {self.drone_id}: Failed to start mission - {e}")
            return False

    async def pause_mission(self) -> bool:
        """Pause the current mission."""
        try:
            await self.drone.mission.pause_mission()
            self.status.mission_active = False
            self.logger.info(f"Drone {self.drone_id}: Mission paused")
            return True

        except Exception as e:
            self.logger.error(f"Drone {self.drone_id}: Failed to pause mission - {e}")
            return False

    async def goto_location(self, coordinate: GPSCoordinate, speed: float = 5.0) -> bool:
        """Go to specific GPS coordinates."""
        try:
            self.logger.info(f"Drone {self.drone_id}: Going to {coordinate.latitude}, {coordinate.longitude}")

            await self.drone.action.goto_location(
                coordinate.latitude,
                coordinate.longitude,
                coordinate.altitude or self.status.altitude,
                speed
            )
            return True

        except Exception as e:
            self.logger.error(f"Drone {self.drone_id}: Failed to go to location - {e}")
            return False

    async def get_telemetry(self) -> Dict[str, Any]:
        """Get current telemetry data."""
        return {
            "drone_id": self.drone_id,
            "connected": self.status.connected,
            "armed": self.status.armed,
            "in_air": self.status.in_air,
            "position": {
                "latitude": self.status.position.latitude if self.status.position else None,
                "longitude": self.status.position.longitude if self.status.position else None,
                "altitude": self.status.altitude,
            },
            "battery": {
                "percent": self.status.battery_percent,
                "voltage": self.status.battery_voltage,
            },
            "gps": {
                "satellites": self.status.gps_satellites,
            },
            "flight_mode": self.status.flight_mode,
            "heading": self.status.heading,
            "ground_speed": self.status.ground_speed,
            "mission_active": self.status.mission_active,
            "last_update": self.status.last_update.isoformat() if self.status.last_update else None,
        }

    async def disconnect(self):
        """Disconnect from drone."""
        try:
            # Cancel telemetry monitoring
            if self._telemetry_task and not self._telemetry_task.done():
                self._telemetry_task.cancel()

            # Land if in air
            if self.status.in_air:
                await self.land()

            self.status.connected = False
            self.logger.info(f"Drone {self.drone_id}: Disconnected")

        except Exception as e:
            self.logger.error(f"Drone {self.drone_id}: Error during disconnect - {e}")


class MultiDroneManager:
    """Manager for multiple drones."""

    def __init__(self, config: Optional[Config] = None):
        """Initialize multi-drone manager."""
        self.config = config or get_config()
        self.drones: List[DroneManager] = []
        self.logger = logging.getLogger("multi_drone_manager")

        # Create drone managers
        for i in range(self.config.drone.count):
            drone_id = i + 1
            connection_string = self.config.drone.connection_strings[i]
            drone_manager = DroneManager(drone_id, connection_string, self.config)
            self.drones.append(drone_manager)

    async def connect_all(self) -> Tuple[int, int]:
        """Connect to all drones. Returns (successful, total) counts."""
        self.logger.info(f"Connecting to {len(self.drones)} drones...")

        # Connect all drones in parallel
        tasks = [drone.connect() for drone in self.drones]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful = sum(1 for result in results if result is True)
        total = len(self.drones)

        self.logger.info(f"Connected to {successful}/{total} drones")
        return successful, total

    async def takeoff_formation(self, altitude: Optional[float] = None, spacing: float = 10.0) -> bool:
        """Takeoff all drones in formation with spacing."""
        try:
            target_altitude = altitude or self.config.drone.default_altitude
            self.logger.info(f"Taking off {len(self.drones)} drones in formation at {target_altitude}m")

            # Stagger takeoffs to avoid conflicts
            tasks = []
            for i, drone in enumerate(self.drones):
                delay = i * 3.0  # 3 second delay between takeoffs
                task = self._delayed_takeoff(drone, target_altitude, delay)
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            successful = sum(1 for result in results if result is True)

            self.logger.info(f"Formation takeoff: {successful}/{len(self.drones)} drones successful")
            return successful == len(self.drones)

        except Exception as e:
            self.logger.error(f"Formation takeoff failed: {e}")
            return False

    async def _delayed_takeoff(self, drone: DroneManager, altitude: float, delay: float) -> bool:
        """Takeoff with delay."""
        await asyncio.sleep(delay)
        return await drone.arm_and_takeoff(altitude)

    async def land_all(self) -> bool:
        """Land all drones."""
        self.logger.info("Landing all drones...")

        tasks = [drone.land() for drone in self.drones if drone.status.in_air]
        if not tasks:
            self.logger.info("No drones in air to land")
            return True

        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful = sum(1 for result in results if result is True)

        self.logger.info(f"Landing: {successful}/{len(tasks)} drones successful")
        return successful == len(tasks)

    async def emergency_land_all(self) -> bool:
        """Emergency land all drones."""
        self.logger.warning("EMERGENCY LANDING ALL DRONES")

        tasks = [drone.emergency_land() for drone in self.drones if drone.status.in_air]
        await asyncio.gather(*tasks, return_exceptions=True)

        return True

    async def get_all_telemetry(self) -> List[Dict[str, Any]]:
        """Get telemetry from all connected drones."""
        tasks = [drone.get_telemetry() for drone in self.drones if drone.status.connected]
        if not tasks:
            return []

        telemetry_data = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_data = [data for data in telemetry_data if isinstance(data, dict)]
        return valid_data

    async def upload_missions(self, missions: List[List[Waypoint]]) -> bool:
        """Upload missions to multiple drones."""
        if len(missions) != len(self.drones):
            self.logger.error(f"Mission count ({len(missions)}) doesn't match drone count ({len(self.drones)})")
            return False

        self.logger.info(f"Uploading missions to {len(self.drones)} drones")

        tasks = []
        for drone, mission in zip(self.drones, missions):
            if drone.status.connected:
                tasks.append(drone.upload_mission(mission))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful = sum(1 for result in results if result is True)

        self.logger.info(f"Mission upload: {successful}/{len(tasks)} drones successful")
        return successful == len(tasks)

    async def start_all_missions(self) -> bool:
        """Start missions on all drones."""
        self.logger.info("Starting missions on all drones")

        tasks = [drone.start_mission() for drone in self.drones if drone.status.connected]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful = sum(1 for result in results if result is True)

        self.logger.info(f"Mission start: {successful}/{len(tasks)} drones successful")
        return successful == len(tasks)

    async def disconnect_all(self):
        """Disconnect from all drones."""
        self.logger.info("Disconnecting from all drones...")

        tasks = [drone.disconnect() for drone in self.drones]
        await asyncio.gather(*tasks, return_exceptions=True)

        self.logger.info("All drones disconnected")

    def get_connected_drones(self) -> List[DroneManager]:
        """Get list of connected drones."""
        return [drone for drone in self.drones if drone.status.connected]

    def get_armed_drones(self) -> List[DroneManager]:
        """Get list of armed drones."""
        return [drone for drone in self.drones if drone.status.armed]

    def get_flying_drones(self) -> List[DroneManager]:
        """Get list of flying drones."""
        return [drone for drone in self.drones if drone.status.in_air]