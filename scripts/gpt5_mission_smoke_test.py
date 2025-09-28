"""Smoke test for GPT-5 mission planning integration.

Usage:
    # Offline mock (default)
    python scripts/gpt5_mission_smoke_test.py

    # Real API call (requires OPENAI_API_KEY)
    MOCK_GPT5=0 python scripts/gpt5_mission_smoke_test.py

Outputs:
- Strategy summary and reasoning snippet
- Number of waypoints generated per drone
- Example of the first waypoint for each mission
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.gpt5_agent import GPT5MissionPlanner, MissionContextBuilder
from src.utils.config import get_config


def _mock_chat_completion() -> SimpleNamespace:
    """Build a fake OpenAI chat completion response."""
    mission_payload = {
        "strategy_summary": "Grid north-east sweep with thermal confirmation passes.",
        "reasoning": "Two drones split the sector. Primary drone handles dense housing, secondary inspects river corridor.",
        "drone_missions": [
            {
                "drone_id": 1,
                "mission_type": "grid_search",
                "priority": "high",
                "waypoints": [
                    {
                        "latitude": 47.39805,
                        "longitude": 8.54620,
                        "altitude": 25.0,
                        "speed": 5.0,
                        "action": "search"
                    },
                    {
                        "latitude": 47.39795,
                        "longitude": 8.54600,
                        "altitude": 25.0,
                        "speed": 5.0,
                        "action": "search"
                    }
                ]
            },
            {
                "drone_id": 2,
                "mission_type": "zigzag",
                "priority": "medium",
                "waypoints": [
                    {
                        "latitude": 47.39790,
                        "longitude": 8.54630,
                        "altitude": 30.0,
                        "speed": 4.0,
                        "action": "search"
                    },
                    {
                        "latitude": 47.39810,
                        "longitude": 8.54640,
                        "altitude": 30.0,
                        "speed": 4.0,
                        "action": "search"
                    }
                ]
            }
        ],
        "coordination_notes": "Broadcast position every 3s; avoid overlapping altitude bands.",
        "contingency_plans": "If thermal anomaly detected, loiter and alert command.",
        "estimated_duration_minutes": 18,
        "risk_assessment": "Low",
        "success_probability": 0.86
    }

    content = json.dumps(mission_payload)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


async def main() -> None:
    config = get_config()
    planner = GPT5MissionPlanner(config)

    use_mock = os.getenv("MOCK_GPT5", "1") != "0"
    if use_mock:
        print("MOCK_GPT5 enabled: using synthetic mission payload")

        async def _fake_call(prompt: str):  # type: ignore
            return _mock_chat_completion()

        planner._call_gpt5 = _fake_call  # type: ignore[attr-defined]
    else:
        print("MOCK_GPT5 disabled: real OpenAI API call will be made")

    context = MissionContextBuilder.create_search_context(
        scenario="Search residential district for missing hikers",
        center_lat=config.search.center_lat,
        center_lon=config.search.center_lon,
        radius_m=200.0,
        num_drones=2,
        weather="Clear",
        wind_speed=4.0,
        time_of_day="Late afternoon",
    )

    mission = await planner.generate_search_mission(context)

    print("\nMission summary")
    print(f"Strategy: {mission.strategy_summary}")
    print(f"Reasoning: {mission.reasoning[:120]}...")
    print(f"Coordination notes: {mission.coordination_notes}")
    print(f"Contingency plans: {mission.contingency_plans}")
    print(f"Estimated duration: {mission.estimated_duration:.1f} minutes")
    print(f"Success probability: {mission.success_probability:.2f}")

    for idx, drone_mission in enumerate(mission.drone_missions, start=1):
        print(
            "  Drone {idx}: {count} waypoints".format(
                idx=idx,
                count=len(drone_mission)
            )
        )
        if drone_mission:
            first_wp = drone_mission[0]
            coord = first_wp.coordinate
            print(
                "    First waypoint -> lat={lat:.6f}, lon={lon:.6f}, alt={alt:.1f}, action={action}".format(
                    lat=coord.latitude,
                    lon=coord.longitude,
                    alt=coord.altitude or 0.0,
                    action=first_wp.action,
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
