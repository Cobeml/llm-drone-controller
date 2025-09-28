"""Mission upload and execution smoke test for a single drone.

Usage:
    python scripts/mission_upload_test.py

Expectations:
- Drone arms, uploads a square search pattern, executes, then lands.
- Mission progress logs should advance through all waypoints without errors.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.drone_manager import DroneManager
from src.utils.config import get_config
from src.utils.validators import Waypoint, validate_gps_coordinate


def _build_square_pattern(center_lat: float, center_lon: float, altitude: float) -> List[Waypoint]:
    """Create a simple square mission around the launch site."""
    offset = 0.00008  # ≈ 9 m at Zurich latitude
    coords = [
        validate_gps_coordinate(center_lat + offset, center_lon, altitude),
        validate_gps_coordinate(center_lat + offset, center_lon + offset, altitude),
        validate_gps_coordinate(center_lat - offset, center_lon + offset, altitude),
        validate_gps_coordinate(center_lat - offset, center_lon, altitude),
    ]

    waypoints = [
        Waypoint(coordinate=coords[0], speed=4.0, action="takeoff", loiter_time=2.0),
        Waypoint(coordinate=coords[1], speed=4.0, action="search", loiter_time=2.0),
        Waypoint(coordinate=coords[2], speed=4.0, action="search", loiter_time=2.0),
        Waypoint(coordinate=coords[3], speed=4.0, action="search", loiter_time=2.0),
    ]
    return waypoints


async def monitor_mission_progress(drone: DroneManager, expected_waypoints: int, timeout: float = 180.0) -> None:
    """Subscribe to mission progress updates and log them until completion."""
    start_time = asyncio.get_event_loop().time()
    async for progress in drone.drone.mission.mission_progress():
        print(
            f"Mission progress: current={progress.current} / total={progress.total}, "
            f"finished={progress.current >= progress.total - 1}"
        )
        if progress.current >= progress.total - 1 or progress.current + 1 >= expected_waypoints:
            print("✅ Mission reported complete")
            break
        if asyncio.get_event_loop().time() - start_time > timeout:
            print("⚠️ Mission monitoring timed out")
            break


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = get_config()
    connection_string = config.drone.connection_strings[0]
    drone = DroneManager(drone_id=1, connection_string=connection_string, config=config)

    print(f"Connecting to drone on {connection_string}...")
    if not await drone.connect():
        print("❌ Connection failed")
        return

    try:
        await asyncio.sleep(3)
        if not await drone.wait_for_global_position():
            print("❌ Global position fix not acquired")
            return

        mission_altitude = 20.0
        waypoints = _build_square_pattern(
            center_lat=config.search.center_lat,
            center_lon=config.search.center_lon,
            altitude=mission_altitude,
        )
        print(f"Uploading mission with {len(waypoints)} waypoints...")
        if not await drone.upload_mission(waypoints):
            print("❌ Mission upload failed")
            return

        # Check if drone needs to takeoff first
        telemetry = await drone.get_telemetry()
        if not telemetry["in_air"]:
            print(f"Drone on ground, taking off to {mission_altitude}m...")
            if not await drone.arm_and_takeoff(mission_altitude):
                print("❌ Takeoff failed")
                return
        else:
            print(f"Drone already airborne at {telemetry['position']['altitude']:.1f}m")
        
        print("Starting mission...")
        if not await drone.start_mission():
            print("❌ Mission start failed")
            return

        await monitor_mission_progress(drone, expected_waypoints=len(waypoints))

        print("Waiting for drone to land...")
        await asyncio.sleep(10)
        await drone.land()
        await asyncio.sleep(5)
        telemetry = await drone.get_telemetry()
        print(
            "Post-mission telemetry: in_air={in_air}, armed={armed}, "
            "altitude={alt:.1f}".format(
                in_air=telemetry["in_air"],
                armed=telemetry["armed"],
                alt=telemetry["position"]["altitude"],
            )
        )

    finally:
        await drone.disconnect()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
