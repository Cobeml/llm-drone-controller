"""Quick connection test for PX4 SITL using DroneManager.

Usage:
    python scripts/check_connection.py
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
        # Allow telemetry task to populate once
        await asyncio.sleep(2)
        telemetry = await drone.get_telemetry()
        print("✅ Connection successful")
        print(
            "  Position lat={latitude}, lon={longitude}, alt={altitude}".format(
                **telemetry["position"]
            )
        )
        print(f"  Battery: {telemetry['battery']['percent']:.1%} ({telemetry['battery']['voltage']:.2f} V)")
        print(f"  GPS satellites: {telemetry['gps']['satellites']}")
    finally:
        await drone.disconnect()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
