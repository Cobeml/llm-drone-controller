"""Plan and execute a GPT-generated mission across connected drones."""

import asyncio
import logging
import sys
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.drone_manager import MultiDroneManager, DroneManager
from src.gpt5_agent import GPT5MissionPlanner, MissionContextBuilder
from src.utils.config import get_config
from src.utils.validators import Waypoint


async def monitor_progress(drone: DroneManager, expected_waypoints: int) -> None:
    """Log MAVSDK mission progress updates until completion."""
    async for progress in drone.drone.mission.mission_progress():
        print(
            f"Drone {drone.drone_id} mission progress: current={progress.current} "
            f"/ total={progress.total}"
        )
        if progress.current + 1 >= expected_waypoints:
            print(f"✅ Drone {drone.drone_id} mission reported complete")
            break


async def execute_mission() -> None:
    logging.basicConfig(level=logging.INFO)
    config = get_config()

    planner = GPT5MissionPlanner(config)
    manager = MultiDroneManager(config)

    # Build mission context limited to available drones.
    requested_drones = len(manager.drones)
    context = MissionContextBuilder.create_search_context(
        scenario="Search residential district for missing hikers",
        center_lat=config.search.center_lat,
        center_lon=config.search.center_lon,
        radius_m=config.search.radius_m,
        num_drones=requested_drones,
        weather="Clear",
        wind_speed=4.0,
        time_of_day="Daytime",
    )

    print("Generating mission plan via GPT...")
    mission = await planner.generate_search_mission(context)

    if not mission.drone_missions:
        print("No missions returned; aborting.")
        return

    print("Connecting to drones...")
    successful, total = await manager.connect_all()
    if successful == 0:
        print("❌ Failed to connect to any drones")
        return

    connected_drones = manager.get_connected_drones()
    print(f"Connected {len(connected_drones)} drones")

    # Pair available drones with GPT missions.
    assignments = list(zip(connected_drones, mission.drone_missions))
    if not assignments:
        print("No available drone/mission pairs; aborting.")
        return

    try:
        # Ensure vehicles are ready before mission upload.
        for drone, _ in assignments:
            await drone.wait_for_global_position()
            try:
                await drone.drone.mission.clear_mission()
            except Exception:
                pass

        await asyncio.sleep(2)

        # Upload missions and prepare for execution with retries to bypass BUSY states.
        for drone, waypoints in assignments:
            assert isinstance(waypoints, List) and waypoints, "Mission waypoints missing"
            print(f"Uploading mission to drone {drone.drone_id} ({len(waypoints)} waypoints)...")

            attempt = 0
            while attempt < 3:
                if await drone.upload_mission(waypoints):
                    break
                attempt += 1
                print(f"Drone {drone.drone_id}: upload busy, retrying ({attempt})...")
                await asyncio.sleep(2)
            else:
                raise RuntimeError(f"Mission upload failed for drone {drone.drone_id}")

        # Arm and take off each drone before starting missions.
        for drone, waypoints in assignments:
            takeoff_alt = waypoints[0].coordinate.altitude or config.drone.default_altitude
            if not drone.status.in_air:
                print(f"Drone {drone.drone_id}: takeoff to {takeoff_alt:.1f}m")
                if not await drone.arm_and_takeoff(takeoff_alt):
                    raise RuntimeError(f"Takeoff failed for drone {drone.drone_id}")

        # Start missions.
        for drone, _ in assignments:
            print(f"Starting mission on drone {drone.drone_id}...")
            if not await drone.start_mission():
                raise RuntimeError(f"Mission start failed for drone {drone.drone_id}")

        # Monitor mission progress concurrently.
        await asyncio.gather(
            *(monitor_progress(drone, len(waypoints)) for drone, waypoints in assignments)
        )

        # Land all participating drones.
        print("Landing assigned drones...")
        await asyncio.gather(*(drone.land() for drone, _ in assignments))
        await asyncio.sleep(3)

    finally:
        await manager.disconnect_all()
        await asyncio.sleep(1)
        print("All drones disconnected")


if __name__ == "__main__":
    asyncio.run(execute_mission())
