"""Automated takeoff and landing validation against PX4 SITL.

Usage:
    python scripts/takeoff_landing_test.py
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
        target_altitude = 15.0
        print(f"Arming and taking off to {target_altitude}m...")
        if not await drone.arm_and_takeoff(target_altitude):
            print("❌ Takeoff failed")
            return

        # Dwell in the air for telemetry confirmation.
        await asyncio.sleep(5)
        telemetry = await drone.get_telemetry()
        print(
            "  Altitude: {altitude:.2f} m (should be near {target_altitude} m)".format(
                altitude=telemetry["position"]["altitude"],
                target_altitude=target_altitude,
            )
        )

        print("Commanding landing...")
        if await drone.land():
            await asyncio.sleep(5)
            telemetry = await drone.get_telemetry()
            print(f"✅ Landing complete, in_air={telemetry['in_air']}")
        else:
            print("❌ Landing command failed")
    finally:
        await drone.disconnect()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
