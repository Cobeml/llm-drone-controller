"""Manual telemetry and navigation test against a running PX4 SITL instance.

This script connects to the first drone, confirms telemetry at the launch position,
then performs a short hop to a nearby GPS coordinate before landing.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

# Ensure repository root is on the Python path when invoked as a script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.drone_manager import DroneManager
from src.utils.config import get_config
from src.utils.validators import validate_gps_coordinate


async def print_telemetry(drone: DroneManager, label: str) -> None:
    """Log a snapshot of telemetry to stdout."""
    telemetry = await drone.get_telemetry()
    position = telemetry["position"]
    battery = telemetry["battery"]
    gps = telemetry["gps"]

    print(f"\n[{label}] Telemetry snapshot for drone {telemetry['drone_id']}")
    print(f"  Connected: {telemetry['connected']} | Armed: {telemetry['armed']} | In air: {telemetry['in_air']}")
    print(
        "  Position: lat={latitude}, lon={longitude}, alt={altitude}".format(
            latitude=position["latitude"],
            longitude=position["longitude"],
            altitude=position["altitude"],
        )
    )
    print(
        "  Battery: {percent:.1%} ({voltage:.2f} V)".format(
            percent=battery["percent"],
            voltage=battery["voltage"],
        )
    )
    print(f"  GPS satellites: {gps['satellites']} | Flight mode: {telemetry['flight_mode']}")
    print(f"  Heading: {telemetry['heading']:.2f} | Ground speed: {telemetry['ground_speed']:.2f} m/s")
    print(f"  Last update: {telemetry['last_update']}")


async def fly_to_coordinate(drone: DroneManager, lat_offset: float, lon_offset: float, altitude: Optional[float] = None) -> bool:
    """Command the drone to fly to a coordinate offset from the configured search center."""
    config = drone.config
    current_abs_alt = (drone.status.position.altitude if drone.status.position else None)
    target_altitude = altitude or current_abs_alt or config.drone.default_altitude
    target_coordinate = validate_gps_coordinate(
        config.search.center_lat + lat_offset,
        config.search.center_lon + lon_offset,
        target_altitude,
    )

    print(
        "Commanding drone to target lat={:.6f}, lon={:.6f}, alt={}m".format(
            target_coordinate.latitude,
            target_coordinate.longitude,
            target_coordinate.altitude,
        )
    )

    return await drone.goto_location(target_coordinate, speed=5.0)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    config = get_config()
    connection_string = config.drone.connection_strings[0]
    drone = DroneManager(drone_id=1, connection_string=connection_string, config=config)

    print(f"Connecting to drone on {connection_string}...")
    if not await drone.connect():
        print("Failed to connect to drone. Aborting test.")
        return

    try:
        # Allow telemetry loop to populate initial values.
        await asyncio.sleep(3)
        await print_telemetry(drone, label="Pre-flight")

        if not drone.status.in_air:
            target_altitude = 15.0
            print(f"Drone not airborne; performing arm and takeoff to {target_altitude}m.")
            takeoff_success = await drone.arm_and_takeoff(target_altitude)
            if not takeoff_success:
                print("Takeoff failed; see logs for details.")
                return

        # Give the drone time to climb and stabilize before navigation.
        await asyncio.sleep(8)
        await print_telemetry(drone, label="Post-takeoff")

        # Fly to a nearby coordinate (~10m north-east).
        hop_success = await fly_to_coordinate(drone, lat_offset=0.00009, lon_offset=0.00009, altitude=20.0)
        if not hop_success:
            print("Goto command failed; see logs for details.")
            return

        print("Hold position for observation...")
        await asyncio.sleep(15)
        await print_telemetry(drone, label="On-target")

        if drone.status.position:
            origin = validate_gps_coordinate(
                config.search.center_lat,
                config.search.center_lon,
                drone.status.position.altitude,
            )
            distance = origin.distance_to(drone.status.position)
            print(f"  Distance from launch center: {distance:.2f} m")

        print("Initiating landing sequence...")
        await drone.land()
        await asyncio.sleep(3)
        await print_telemetry(drone, label="Post-landing")

    finally:
        await drone.disconnect()
        await asyncio.sleep(1)
        print("Telemetry test complete. Drone disconnected.")


if __name__ == "__main__":
    asyncio.run(main())
