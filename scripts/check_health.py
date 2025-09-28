"""Global position / health readiness test for PX4 SITL.

Usage:
    python scripts/check_health.py
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
        print("Waiting for global position fix...")
        health_ok = await drone.wait_for_global_position()
        if health_ok:
            print("✅ Drone reports global position and home position ready")
        else:
            print("❌ Timed out waiting for global position")
    finally:
        await drone.disconnect()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
