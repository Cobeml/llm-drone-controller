"""Navigation test that validates goto command to a nearby waypoint.

Usage:
    python scripts/simple_navigation_test.py
"""

import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.drone_manager import DroneManager
from src.utils.config import get_config
from src.utils.validators import validate_gps_coordinate


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
        await asyncio.sleep(2)
        if not drone.status.in_air:
            climb_altitude = 20.0
            print(f"Taking off to {climb_altitude}m...")
            if not await drone.arm_and_takeoff(climb_altitude):
                print("❌ Takeoff failed")
                return

            await asyncio.sleep(8)

        start_telemetry = await drone.get_telemetry()
        print(
            "  Start position lat={lat:.6f}, lon={lon:.6f}, alt={alt:.1f}".format(
                lat=start_telemetry["position"]["latitude"],
                lon=start_telemetry["position"]["longitude"],
                alt=start_telemetry["position"]["altitude"],
            )
        )

        offset = 0.00012  # ≈ 13 meters at Zurich latitude
        target = validate_gps_coordinate(
            config.search.center_lat + offset,
            config.search.center_lon + offset,
            (drone.status.position.altitude if drone.status.position else None)
            or config.drone.default_altitude,
        )

        print(
            "Commanding goto lat={:.6f}, lon={:.6f}, alt={:.1f}".format(
                target.latitude,
                target.longitude,
                target.altitude or 0.0,
            )
        )
        if not await drone.goto_location(target, speed=5.0):
            print("❌ Goto command failed")
            return

        await asyncio.sleep(15)
        current = await drone.get_telemetry()
        print(
            "  Current position lat={lat:.6f}, lon={lon:.6f}, alt={alt:.1f}".format(
                lat=current["position"]["latitude"],
                lon=current["position"]["longitude"],
                alt=current["position"]["altitude"],
            )
        )
        if drone.status.position:
            origin = validate_gps_coordinate(
                config.search.center_lat,
                config.search.center_lon,
                drone.status.position.altitude,
            )
            distance = origin.distance_to(drone.status.position)
            print(f"  Distance from launch center: {distance:.2f} m")
            print(f"  Raw target altitude command: {target.altitude:.1f} m")

        print("Commanding landing...")
        await drone.land()
        await asyncio.sleep(5)
        final = await drone.get_telemetry()
        print(f"✅ Landed, in_air={final['in_air']}, armed={final['armed']}")
    finally:
        await drone.disconnect()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
