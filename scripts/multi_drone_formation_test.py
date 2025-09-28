"""Multi-drone formation takeoff/landing test using MultiDroneManager.

Usage:
    python scripts/multi_drone_formation_test.py

Prerequisites:
- PX4 SITL instances bound to the ports defined in config (defaults 14540-14542).
- Each drone should be idle on the pad before running.
"""

import asyncio
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.drone_manager import MultiDroneManager
from src.utils.config import get_config


async def print_fleet_telemetry(manager: MultiDroneManager, label: str) -> None:
    telemetry = await manager.get_all_telemetry()
    print(f"\n[{label}] Fleet telemetry ({len(telemetry)} drones)")
    for data in telemetry:
        position = data["position"]
        print(
            "  Drone {id}: connected={connected} in_air={in_air} armed={armed} alt={alt:.1f} lat={lat:.6f} lon={lon:.6f}".format(
                id=data["drone_id"],
                connected=data["connected"],
                in_air=data["in_air"],
                armed=data["armed"],
                alt=position["altitude"] or 0.0,
                lat=position["latitude"] or 0.0,
                lon=position["longitude"] or 0.0,
            )
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = get_config()
    manager = MultiDroneManager(config)

    print("Connecting to configured drones...")
    successful, total = await manager.connect_all()
    print(f"Connected {successful}/{total} drones")
    if successful == 0:
        print("❌ No drones connected; aborting test")
        return

    try:
        await asyncio.sleep(3)
        await print_fleet_telemetry(manager, label="Pre-flight")

        target_altitude = 18.0
        print(f"Launching formation to {target_altitude}m with 8m spacing...")
        formation_ok = await manager.takeoff_formation(altitude=target_altitude, spacing=8.0)
        print(f"Formation takeoff success: {formation_ok}")

        await asyncio.sleep(15)
        await print_fleet_telemetry(manager, label="Mid-flight")

        print("Commanding coordinated landing...")
        landing_ok = await manager.land_all()
        print(f"Landing success: {landing_ok}")

        await asyncio.sleep(8)
        await print_fleet_telemetry(manager, label="Post-landing")

    finally:
        await manager.disconnect_all()
        await asyncio.sleep(2)
        print("All drones disconnected")


if __name__ == "__main__":
    asyncio.run(main())
