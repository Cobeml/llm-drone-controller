"""
Mission Executor for LLM Drone Controller

Handles waypoint execution, mission monitoring, and progress tracking
for autonomous drone operations with PX4/MAVLink integration.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan
from mavsdk.action import ActionError
from mavsdk.mission import MissionError
from mavsdk.telemetry import Position, FlightMode

from .utils.config import Config
from .utils.validators import Waypoint, MissionValidation


class MissionState(Enum):
    """Mission execution states"""
    IDLE = "idle"
    UPLOADING = "uploading"
    STARTING = "starting"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class WaypointStatus(Enum):
    """Individual waypoint status"""
    PENDING = "pending"
    APPROACHING = "approaching"
    REACHED = "reached"
    SKIPPED = "skipped"


@dataclass
class WaypointProgress:
    """Track progress of individual waypoints"""
    waypoint: Waypoint
    status: WaypointStatus = WaypointStatus.PENDING
    reached_time: Optional[datetime] = None
    distance_to_target: float = 0.0
    eta_seconds: Optional[float] = None


@dataclass
class MissionProgress:
    """Track overall mission progress"""
    mission_id: str
    drone_id: str
    state: MissionState = MissionState.IDLE
    current_waypoint_index: int = 0
    waypoints: List[WaypointProgress] = field(default_factory=list)
    start_time: Optional[datetime] = None
    completion_time: Optional[datetime] = None
    total_distance_m: float = 0.0
    distance_completed_m: float = 0.0
    estimated_duration_s: Optional[float] = None
    actual_duration_s: Optional[float] = None
    error_message: Optional[str] = None

    @property
    def progress_percentage(self) -> float:
        """Calculate completion percentage"""
        if not self.waypoints:
            return 0.0

        completed = sum(1 for wp in self.waypoints
                       if wp.status == WaypointStatus.REACHED)
        return (completed / len(self.waypoints)) * 100.0

    @property
    def is_active(self) -> bool:
        """Check if mission is actively executing"""
        return self.state in [
            MissionState.UPLOADING,
            MissionState.STARTING,
            MissionState.EXECUTING,
            MissionState.PAUSED
        ]


class MissionExecutor:
    """Execute and monitor drone missions"""

    def __init__(self, drone: System, drone_id: str, config: Config):
        self.drone = drone
        self.drone_id = drone_id
        self.config = config
        self.logger = logging.getLogger(f"MissionExecutor.{drone_id}")

        self.current_mission: Optional[MissionProgress] = None
        self.progress_callbacks: List[Callable[[MissionProgress], None]] = []
        self.waypoint_callbacks: List[Callable[[WaypointProgress], None]] = []

        self._monitoring_task: Optional[asyncio.Task] = None
        self._cancel_event = asyncio.Event()

        # Mission execution parameters
        self.waypoint_radius_m = config.drone.waypoint_radius_m
        self.max_mission_duration_s = config.drone.max_flight_time_s
        self.position_check_interval_s = 1.0

    async def upload_mission(self, waypoints: List[Waypoint], mission_id: str = None) -> bool:
        """Upload mission to drone"""
        try:
            if mission_id is None:
                mission_id = f"mission_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            self.logger.info(f"Uploading mission {mission_id} with {len(waypoints)} waypoints")

            # Validate mission
            validation_result = MissionValidation.validate_mission_sequence(waypoints)
            if not validation_result.is_valid:
                raise ValueError(f"Mission validation failed: {validation_result.errors}")

            # Convert to MAVSDK mission items
            mission_items = []
            for i, waypoint in enumerate(waypoints):
                mission_item = MissionItem(
                    latitude_deg=waypoint.latitude,
                    longitude_deg=waypoint.longitude,
                    relative_altitude_m=waypoint.altitude,
                    speed_m_s=waypoint.speed_ms,
                    is_fly_through=(waypoint.action == "flythrough"),
                    gimbal_pitch_deg=float('nan'),
                    gimbal_yaw_deg=float('nan'),
                    camera_action=MissionItem.CameraAction.NONE,
                    loiter_time_s=waypoint.loiter_time_s,
                    acceptance_radius_m=self.waypoint_radius_m,
                    yaw_deg=float('nan'),
                    camera_photo_interval_s=float('nan'),
                    camera_photo_distance_m=float('nan')
                )
                mission_items.append(mission_item)

            # Create mission plan
            mission_plan = MissionPlan(mission_items)

            # Initialize mission progress
            self.current_mission = MissionProgress(
                mission_id=mission_id,
                drone_id=self.drone_id,
                state=MissionState.UPLOADING,
                waypoints=[WaypointProgress(wp) for wp in waypoints]
            )

            # Upload to drone
            await self.drone.mission.upload_mission(mission_plan)

            self.current_mission.state = MissionState.IDLE
            self.logger.info(f"Mission {mission_id} uploaded successfully")
            self._notify_progress()

            return True

        except Exception as e:
            self.logger.error(f"Failed to upload mission: {e}")
            if self.current_mission:
                self.current_mission.state = MissionState.FAILED
                self.current_mission.error_message = str(e)
                self._notify_progress()
            return False

    async def start_mission(self) -> bool:
        """Start executing the uploaded mission"""
        try:
            if not self.current_mission:
                raise ValueError("No mission uploaded")

            if self.current_mission.state != MissionState.IDLE:
                raise ValueError(f"Mission not ready to start: {self.current_mission.state}")

            self.logger.info(f"Starting mission {self.current_mission.mission_id}")

            # Update state
            self.current_mission.state = MissionState.STARTING
            self.current_mission.start_time = datetime.now()
            self._notify_progress()

            # Start mission on drone
            await self.drone.mission.start_mission()

            # Start monitoring
            self._cancel_event.clear()
            self._monitoring_task = asyncio.create_task(self._monitor_mission())

            self.current_mission.state = MissionState.EXECUTING
            self.logger.info(f"Mission {self.current_mission.mission_id} started")
            self._notify_progress()

            return True

        except Exception as e:
            self.logger.error(f"Failed to start mission: {e}")
            if self.current_mission:
                self.current_mission.state = MissionState.FAILED
                self.current_mission.error_message = str(e)
                self._notify_progress()
            return False

    async def pause_mission(self) -> bool:
        """Pause the current mission"""
        try:
            if not self.current_mission or self.current_mission.state != MissionState.EXECUTING:
                return False

            self.logger.info("Pausing mission")
            await self.drone.mission.pause_mission()

            self.current_mission.state = MissionState.PAUSED
            self._notify_progress()

            return True

        except Exception as e:
            self.logger.error(f"Failed to pause mission: {e}")
            return False

    async def resume_mission(self) -> bool:
        """Resume a paused mission"""
        try:
            if not self.current_mission or self.current_mission.state != MissionState.PAUSED:
                return False

            self.logger.info("Resuming mission")
            await self.drone.mission.start_mission()

            self.current_mission.state = MissionState.EXECUTING
            self._notify_progress()

            return True

        except Exception as e:
            self.logger.error(f"Failed to resume mission: {e}")
            return False

    async def abort_mission(self) -> bool:
        """Abort the current mission and return to launch"""
        try:
            if not self.current_mission or not self.current_mission.is_active:
                return False

            self.logger.warning("Aborting mission")

            # Cancel monitoring
            if self._monitoring_task:
                self._cancel_event.set()
                await self._monitoring_task

            # Clear mission and return to launch
            await self.drone.mission.clear_mission()
            await self.drone.action.return_to_launch()

            self.current_mission.state = MissionState.ABORTED
            self.current_mission.completion_time = datetime.now()
            if self.current_mission.start_time:
                self.current_mission.actual_duration_s = (
                    self.current_mission.completion_time - self.current_mission.start_time
                ).total_seconds()

            self._notify_progress()
            self.logger.info("Mission aborted successfully")

            return True

        except Exception as e:
            self.logger.error(f"Failed to abort mission: {e}")
            return False

    async def emergency_land(self) -> bool:
        """Emergency landing procedure"""
        try:
            self.logger.warning("Initiating emergency landing")

            # Cancel monitoring
            if self._monitoring_task:
                self._cancel_event.set()
                await self._monitoring_task

            # Emergency land
            await self.drone.action.land()

            if self.current_mission:
                self.current_mission.state = MissionState.ABORTED
                self.current_mission.error_message = "Emergency landing initiated"
                self.current_mission.completion_time = datetime.now()
                if self.current_mission.start_time:
                    self.current_mission.actual_duration_s = (
                        self.current_mission.completion_time - self.current_mission.start_time
                    ).total_seconds()
                self._notify_progress()

            self.logger.info("Emergency landing initiated")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initiate emergency landing: {e}")
            return False

    async def _monitor_mission(self):
        """Monitor mission progress and update waypoint status"""
        try:
            self.logger.info("Starting mission monitoring")

            while not self._cancel_event.is_set():
                try:
                    # Check mission completion
                    async for mission_progress in self.drone.mission.mission_progress():
                        if self._cancel_event.is_set():
                            break

                        self.current_mission.current_waypoint_index = mission_progress.current

                        # Update waypoint status
                        self._update_waypoint_status(mission_progress.current)

                        # Check if mission completed
                        if mission_progress.current >= len(self.current_mission.waypoints):
                            await self._complete_mission()
                            return

                        self._notify_progress()

                        # Timeout check
                        if self._check_mission_timeout():
                            self.logger.warning("Mission timeout reached")
                            await self.abort_mission()
                            return

                        await asyncio.sleep(self.position_check_interval_s)

                except Exception as e:
                    self.logger.error(f"Error in mission monitoring: {e}")
                    await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            self.logger.info("Mission monitoring cancelled")
        except Exception as e:
            self.logger.error(f"Mission monitoring failed: {e}")
            if self.current_mission:
                self.current_mission.state = MissionState.FAILED
                self.current_mission.error_message = str(e)
                self._notify_progress()

    def _update_waypoint_status(self, current_index: int):
        """Update status of waypoints based on current progress"""
        if not self.current_mission or current_index >= len(self.current_mission.waypoints):
            return

        # Mark previous waypoints as reached
        for i in range(min(current_index, len(self.current_mission.waypoints))):
            if self.current_mission.waypoints[i].status == WaypointStatus.PENDING:
                self.current_mission.waypoints[i].status = WaypointStatus.REACHED
                self.current_mission.waypoints[i].reached_time = datetime.now()
                self._notify_waypoint(self.current_mission.waypoints[i])

        # Mark current waypoint as approaching
        if current_index < len(self.current_mission.waypoints):
            if self.current_mission.waypoints[current_index].status == WaypointStatus.PENDING:
                self.current_mission.waypoints[current_index].status = WaypointStatus.APPROACHING
                self._notify_waypoint(self.current_mission.waypoints[current_index])

    async def _complete_mission(self):
        """Handle mission completion"""
        self.logger.info(f"Mission {self.current_mission.mission_id} completed successfully")

        # Mark all waypoints as reached
        for waypoint in self.current_mission.waypoints:
            if waypoint.status != WaypointStatus.REACHED:
                waypoint.status = WaypointStatus.REACHED
                waypoint.reached_time = datetime.now()

        self.current_mission.state = MissionState.COMPLETED
        self.current_mission.completion_time = datetime.now()
        if self.current_mission.start_time:
            self.current_mission.actual_duration_s = (
                self.current_mission.completion_time - self.current_mission.start_time
            ).total_seconds()

        self._notify_progress()

    def _check_mission_timeout(self) -> bool:
        """Check if mission has exceeded maximum duration"""
        if not self.current_mission or not self.current_mission.start_time:
            return False

        elapsed = (datetime.now() - self.current_mission.start_time).total_seconds()
        return elapsed > self.max_mission_duration_s

    def add_progress_callback(self, callback: Callable[[MissionProgress], None]):
        """Add callback for mission progress updates"""
        self.progress_callbacks.append(callback)

    def add_waypoint_callback(self, callback: Callable[[WaypointProgress], None]):
        """Add callback for waypoint status updates"""
        self.waypoint_callbacks.append(callback)

    def _notify_progress(self):
        """Notify all progress callbacks"""
        if self.current_mission:
            for callback in self.progress_callbacks:
                try:
                    callback(self.current_mission)
                except Exception as e:
                    self.logger.error(f"Error in progress callback: {e}")

    def _notify_waypoint(self, waypoint: WaypointProgress):
        """Notify all waypoint callbacks"""
        for callback in self.waypoint_callbacks:
            try:
                callback(waypoint)
            except Exception as e:
                self.logger.error(f"Error in waypoint callback: {e}")

    def get_mission_status(self) -> Optional[MissionProgress]:
        """Get current mission status"""
        return self.current_mission

    def is_mission_active(self) -> bool:
        """Check if a mission is currently active"""
        return self.current_mission is not None and self.current_mission.is_active

    async def cleanup(self):
        """Cleanup resources and stop monitoring"""
        if self._monitoring_task:
            self._cancel_event.set()
            try:
                await asyncio.wait_for(self._monitoring_task, timeout=5.0)
            except asyncio.TimeoutError:
                self.logger.warning("Mission monitoring cleanup timeout")
                self._monitoring_task.cancel()


class MultiMissionCoordinator:
    """Coordinate missions across multiple drones"""

    def __init__(self, executors: Dict[str, MissionExecutor]):
        self.executors = executors
        self.logger = logging.getLogger("MultiMissionCoordinator")
        self.coordinated_missions: Dict[str, List[str]] = {}  # mission_group_id -> drone_ids

    async def start_coordinated_mission(self, mission_group_id: str,
                                      drone_missions: Dict[str, List[Waypoint]],
                                      delay_between_starts_s: float = 2.0) -> bool:
        """Start synchronized missions across multiple drones"""
        try:
            self.logger.info(f"Starting coordinated mission {mission_group_id}")

            # Upload missions to all drones
            upload_tasks = []
            for drone_id, waypoints in drone_missions.items():
                if drone_id not in self.executors:
                    raise ValueError(f"No executor found for drone {drone_id}")

                task = self.executors[drone_id].upload_mission(
                    waypoints, f"{mission_group_id}_{drone_id}"
                )
                upload_tasks.append(task)

            upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)

            # Check upload results
            failed_uploads = [result for result in upload_results if not result or isinstance(result, Exception)]
            if failed_uploads:
                self.logger.error(f"Failed to upload missions: {failed_uploads}")
                return False

            # Start missions with staggered timing
            start_tasks = []
            for i, drone_id in enumerate(drone_missions.keys()):
                async def start_with_delay(executor, delay):
                    if delay > 0:
                        await asyncio.sleep(delay)
                    return await executor.start_mission()

                delay = i * delay_between_starts_s
                task = start_with_delay(self.executors[drone_id], delay)
                start_tasks.append(task)

            start_results = await asyncio.gather(*start_tasks, return_exceptions=True)

            # Check start results
            failed_starts = [result for result in start_results if not result or isinstance(result, Exception)]
            if failed_starts:
                self.logger.error(f"Failed to start missions: {failed_starts}")
                return False

            self.coordinated_missions[mission_group_id] = list(drone_missions.keys())
            self.logger.info(f"Coordinated mission {mission_group_id} started successfully")

            return True

        except Exception as e:
            self.logger.error(f"Failed to start coordinated mission: {e}")
            return False

    async def abort_coordinated_mission(self, mission_group_id: str) -> bool:
        """Abort all missions in a coordinated group"""
        if mission_group_id not in self.coordinated_missions:
            return False

        try:
            self.logger.warning(f"Aborting coordinated mission {mission_group_id}")

            abort_tasks = []
            for drone_id in self.coordinated_missions[mission_group_id]:
                if drone_id in self.executors:
                    abort_tasks.append(self.executors[drone_id].abort_mission())

            await asyncio.gather(*abort_tasks, return_exceptions=True)

            del self.coordinated_missions[mission_group_id]
            return True

        except Exception as e:
            self.logger.error(f"Failed to abort coordinated mission: {e}")
            return False

    def get_coordinated_status(self, mission_group_id: str) -> Dict[str, Optional[MissionProgress]]:
        """Get status of all drones in a coordinated mission"""
        if mission_group_id not in self.coordinated_missions:
            return {}

        status = {}
        for drone_id in self.coordinated_missions[mission_group_id]:
            if drone_id in self.executors:
                status[drone_id] = self.executors[drone_id].get_mission_status()

        return status