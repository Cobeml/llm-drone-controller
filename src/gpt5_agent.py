"""GPT-5 powered mission planning agent for LLM Drone Controller."""

import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from .utils.config import Config, get_config
from .utils.validators import (
    GPSCoordinate, Waypoint, SearchArea, MissionValidation,
    OpenAIPromptValidation, validate_gps_coordinate
)


@dataclass
class MissionContext:
    """Context information for mission planning."""

    scenario_description: str
    search_area: SearchArea
    num_drones: int
    drone_capabilities: List[Dict[str, Any]]
    environmental_conditions: Dict[str, Any]
    time_constraints: Optional[Dict[str, Any]] = None
    priority_areas: Optional[List[Dict[str, Any]]] = None
    known_obstacles: Optional[List[Dict[str, Any]]] = None


@dataclass
class GeneratedMission:
    """Generated mission plan from GPT-5."""

    strategy_summary: str
    reasoning: str
    drone_missions: List[List[Waypoint]]
    coordination_notes: str
    contingency_plans: str
    estimated_duration: float
    risk_assessment: str
    success_probability: float
    generated_at: datetime


class GPT5MissionPlanner:
    """GPT-5 powered mission planning agent."""

    def __init__(self, config: Optional[Config] = None):
        """Initialize GPT-5 mission planner."""
        self.config = config or get_config()
        self.client = AsyncOpenAI(api_key=self.config.openai.api_key)
        self.logger = logging.getLogger("gpt5_mission_planner")

        # GPT-5 specific settings
        self.model = self.config.openai.model_variant
        self.verbosity = self.config.openai.verbosity
        self.reasoning_effort = self.config.openai.reasoning_effort
        self.enable_thinking = self.config.openai.enable_thinking

    async def generate_search_mission(self, context: MissionContext) -> GeneratedMission:
        """Generate a comprehensive search mission using GPT-5."""
        try:
            start_time = time.time()
            self.logger.info(f"Generating mission for {context.num_drones} drones using GPT-5")

            # Validate and sanitize input
            valid_prompt, errors = OpenAIPromptValidation.validate_mission_prompt(
                context.scenario_description
            )
            if not valid_prompt:
                raise ValueError(f"Invalid prompt: {errors}")

            # Create the detailed prompt for GPT-5
            prompt = self._create_mission_prompt(context)

            # Generate mission using GPT-5 with advanced parameters
            response = await self._call_gpt5(prompt)

            # Parse and validate the response
            mission_data = self._parse_mission_response(response)

            # Convert to waypoints and validate
            drone_missions = self._convert_to_waypoints(mission_data["drone_missions"])

            # Validate mission feasibility
            validation_success, validation_errors = MissionValidation.validate_multi_drone_mission(
                drone_missions
            )
            if not validation_success:
                self.logger.warning(f"Mission validation warnings: {validation_errors}")

            # Create the generated mission object
            mission = GeneratedMission(
                strategy_summary=mission_data["strategy_summary"],
                reasoning=mission_data["reasoning"],
                drone_missions=drone_missions,
                coordination_notes=mission_data["coordination_notes"],
                contingency_plans=mission_data["contingency_plans"],
                estimated_duration=mission_data.get("estimated_duration_minutes", 15.0),
                risk_assessment=mission_data.get("risk_assessment", "Medium risk"),
                success_probability=mission_data.get("success_probability", 0.8),
                generated_at=datetime.now()
            )

            generation_time = time.time() - start_time
            self.logger.info(f"Mission generated in {generation_time:.2f}s with {len(drone_missions)} drone plans")

            return mission

        except Exception as e:
            self.logger.error(f"Failed to generate mission: {e}")
            return self._get_fallback_mission(context)

    def _create_mission_prompt(self, context: MissionContext) -> str:
        """Create a detailed prompt for GPT-5 mission planning."""
        return f"""You are an expert search and rescue mission planner for autonomous drone operations. You have access to the latest drone technology and search patterns.

MISSION SCENARIO:
{context.scenario_description}

OPERATIONAL PARAMETERS:
- Available Drones: {context.num_drones}
- Search Area: Center at {context.search_area.center.latitude:.6f}, {context.search_area.center.longitude:.6f}
- Search Radius: {context.search_area.radius_m} meters
- Altitude Range: {context.search_area.min_altitude}m to {context.search_area.max_altitude}m

DRONE CAPABILITIES:
{json.dumps(context.drone_capabilities, indent=2) if context.drone_capabilities else "Standard multi-rotor capabilities"}

ENVIRONMENTAL CONDITIONS:
{json.dumps(context.environmental_conditions, indent=2)}

ADDITIONAL CONSTRAINTS:
- Time Constraints: {context.time_constraints or "Standard 15-minute mission"}
- Priority Areas: {context.priority_areas or "No specific priority areas"}
- Known Obstacles: {context.known_obstacles or "Standard suburban environment with houses"}

INSTRUCTIONS:
Generate a comprehensive search strategy that maximizes coverage efficiency while ensuring drone safety. Consider:

1. **Optimal Search Patterns**: Choose between grid, spiral, random, or custom patterns based on scenario
2. **Drone Coordination**: Minimize overlap while ensuring complete coverage
3. **Risk Mitigation**: Account for obstacles, weather, and safety margins
4. **Adaptive Strategy**: Plan for dynamic replanning based on findings
5. **Communication Protocol**: Ensure drones can coordinate effectively

Return your response in this exact JSON format:
{{
    "strategy_summary": "Brief 2-3 sentence overview of the search strategy",
    "reasoning": "Detailed explanation of why this approach is optimal for the given scenario",
    "drone_missions": [
        {{
            "drone_id": 1,
            "mission_type": "grid_search|spiral|zigzag|custom",
            "priority": "high|medium|low",
            "waypoints": [
                {{
                    "latitude": 47.397971,
                    "longitude": 8.546164,
                    "altitude": 25.0,
                    "speed": 8.0,
                    "action": "search",
                    "loiter_time": 2.0,
                    "photo_interval": 1.0,
                    "gimbal_pitch": -45.0,
                    "gimbal_yaw": 0.0
                }}
            ],
            "special_instructions": "Specific guidance for this drone's mission",
            "estimated_duration_minutes": 12.0
        }}
    ],
    "coordination_notes": "How drones should coordinate and communicate during the mission",
    "contingency_plans": "What to do if targets are found, drones fail, or conditions change",
    "estimated_duration_minutes": 15.0,
    "risk_assessment": "Assessment of mission risks and mitigation strategies",
    "success_probability": 0.85
}}

IMPORTANT:
- Ensure waypoints are within the specified search area
- Maintain safe separation between drones (minimum 20m)
- Use realistic speeds (5-15 m/s) and altitudes (15-50m)
- Include contingency plans for emergency situations
- Optimize for both speed and thoroughness"""

    async def _call_gpt5(self, prompt: str) -> ChatCompletion:
        """Call GPT-5 API with advanced parameters."""
        try:
            # GPT-5 specific parameters for September 2025
            messages = [
                {
                    "role": "system",
                    "content": "You are an expert autonomous drone mission planner with extensive experience in search and rescue operations. Always respond with valid JSON that exactly matches the requested format."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]

            # Advanced GPT-5 parameters
            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.config.openai.max_tokens,
                "temperature": self.config.openai.temperature,
                "response_format": {"type": "json_object"},
                "timeout": self.config.mission.planning_timeout
            }

            # Add GPT-5 specific parameters
            if hasattr(self.config.openai, 'verbosity'):
                kwargs["verbosity"] = self.verbosity

            if hasattr(self.config.openai, 'reasoning_effort'):
                kwargs["reasoning_effort"] = self.reasoning_effort

            if self.enable_thinking:
                kwargs["thinking"] = True

            self.logger.debug(f"Calling GPT-5 with model: {self.model}, verbosity: {self.verbosity}")

            response = await self.client.chat.completions.create(**kwargs)

            return response

        except Exception as e:
            self.logger.error(f"GPT-5 API call failed: {e}")
            raise

    def _parse_mission_response(self, response: ChatCompletion) -> Dict[str, Any]:
        """Parse GPT-5 response and validate structure."""
        try:
            content = response.choices[0].message.content
            mission_data = json.loads(content)

            # Validate required fields
            required_fields = [
                "strategy_summary", "reasoning", "drone_missions",
                "coordination_notes", "contingency_plans"
            ]

            for field in required_fields:
                if field not in mission_data:
                    raise ValueError(f"Missing required field: {field}")

            # Validate drone missions structure
            if not isinstance(mission_data["drone_missions"], list):
                raise ValueError("drone_missions must be a list")

            for i, mission in enumerate(mission_data["drone_missions"]):
                if not isinstance(mission.get("waypoints"), list):
                    raise ValueError(f"Drone {i+1} waypoints must be a list")

                if len(mission["waypoints"]) == 0:
                    raise ValueError(f"Drone {i+1} must have at least one waypoint")

            return mission_data

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse GPT-5 JSON response: {e}")
            raise ValueError(f"Invalid JSON response from GPT-5: {e}")

        except Exception as e:
            self.logger.error(f"Failed to validate mission response: {e}")
            raise

    def _convert_to_waypoints(self, drone_missions: List[Dict[str, Any]]) -> List[List[Waypoint]]:
        """Convert raw waypoint data to validated Waypoint objects."""
        converted_missions = []

        for mission in drone_missions:
            waypoints = []
            for wp_data in mission["waypoints"]:
                try:
                    # Create GPS coordinate
                    coordinate = validate_gps_coordinate(
                        wp_data["latitude"],
                        wp_data["longitude"],
                        wp_data.get("altitude", 20.0)
                    )

                    # Create waypoint
                    waypoint = Waypoint(
                        coordinate=coordinate,
                        speed=wp_data.get("speed", 5.0),
                        action=wp_data.get("action", "search"),
                        loiter_time=wp_data.get("loiter_time", 0.0),
                        photo_interval=wp_data.get("photo_interval", 0.0),
                        gimbal_pitch=wp_data.get("gimbal_pitch", 0.0),
                        gimbal_yaw=wp_data.get("gimbal_yaw", 0.0)
                    )

                    waypoints.append(waypoint)

                except Exception as e:
                    self.logger.warning(f"Invalid waypoint data: {wp_data}, error: {e}")
                    continue

            if waypoints:
                converted_missions.append(waypoints)

        return converted_missions

    def _get_fallback_mission(self, context: MissionContext) -> GeneratedMission:
        """Generate a fallback mission when GPT-5 fails."""
        self.logger.warning("Using fallback mission generation")

        # Simple grid search pattern
        missions = []
        center = context.search_area.center
        radius_deg = context.search_area.radius_m / 111000  # Rough meters to degrees

        for i in range(context.num_drones):
            waypoints = []
            offset = (i - context.num_drones/2) * radius_deg / context.num_drones

            # Create simple north-south search pattern
            waypoints.extend([
                Waypoint(
                    coordinate=validate_gps_coordinate(
                        center.latitude + offset,
                        center.longitude - radius_deg/2,
                        25.0
                    ),
                    speed=5.0,
                    action="search"
                ),
                Waypoint(
                    coordinate=validate_gps_coordinate(
                        center.latitude + offset,
                        center.longitude + radius_deg/2,
                        25.0
                    ),
                    speed=5.0,
                    action="search"
                )
            ])

            missions.append(waypoints)

        return GeneratedMission(
            strategy_summary="Fallback parallel search pattern due to AI planning failure",
            reasoning="Using simple grid search as emergency fallback",
            drone_missions=missions,
            coordination_notes="Maintain 100m separation between drones",
            contingency_plans="Return to launch if any issues occur",
            estimated_duration=10.0,
            risk_assessment="Low risk emergency pattern",
            success_probability=0.6,
            generated_at=datetime.now()
        )

    async def refine_mission(self,
                           original_mission: GeneratedMission,
                           feedback: str,
                           telemetry_data: Optional[List[Dict[str, Any]]] = None) -> GeneratedMission:
        """Refine an existing mission based on feedback or real-time data."""
        try:
            self.logger.info("Refining mission based on feedback")

            # Create refinement prompt
            prompt = f"""You are refining an existing drone search mission based on new information.

ORIGINAL MISSION SUMMARY:
{original_mission.strategy_summary}

ORIGINAL REASONING:
{original_mission.reasoning}

NEW FEEDBACK/INFORMATION:
{feedback}

CURRENT TELEMETRY (if available):
{json.dumps(telemetry_data, indent=2) if telemetry_data else "No current telemetry"}

INSTRUCTIONS:
Modify the original mission to account for the new information. Consider:
1. Adjusting search patterns based on findings
2. Reallocating drones to different areas
3. Changing priorities based on new intel
4. Updating safety considerations

Provide the updated mission in the same JSON format as the original, but optimized for the new situation."""

            response = await self._call_gpt5(prompt)
            mission_data = self._parse_mission_response(response)
            drone_missions = self._convert_to_waypoints(mission_data["drone_missions"])

            return GeneratedMission(
                strategy_summary=mission_data["strategy_summary"],
                reasoning=mission_data["reasoning"],
                drone_missions=drone_missions,
                coordination_notes=mission_data["coordination_notes"],
                contingency_plans=mission_data["contingency_plans"],
                estimated_duration=mission_data.get("estimated_duration_minutes", 15.0),
                risk_assessment=mission_data.get("risk_assessment", "Medium risk"),
                success_probability=mission_data.get("success_probability", 0.8),
                generated_at=datetime.now()
            )

        except Exception as e:
            self.logger.error(f"Failed to refine mission: {e}")
            # Return original mission if refinement fails
            return original_mission

    async def analyze_mission_progress(self,
                                     mission: GeneratedMission,
                                     telemetry_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze mission progress and provide recommendations."""
        try:
            self.logger.info("Analyzing mission progress with GPT-5")

            prompt = f"""Analyze the progress of an ongoing drone search mission.

MISSION PLAN:
Strategy: {mission.strategy_summary}
Estimated Duration: {mission.estimated_duration} minutes
Success Probability: {mission.success_probability}

CURRENT TELEMETRY:
{json.dumps(telemetry_data, indent=2)}

ANALYSIS REQUIRED:
1. Progress assessment (percentage complete)
2. Performance vs. expectations
3. Potential issues or concerns
4. Recommendations for optimization
5. Whether mission goals are on track

Provide analysis in this JSON format:
{{
    "progress_percentage": 75.0,
    "performance_assessment": "Mission performing above/below/as expected",
    "identified_issues": ["List of any issues or concerns"],
    "recommendations": ["List of actionable recommendations"],
    "mission_status": "on_track|needs_adjustment|critical_issues",
    "estimated_completion_time": 12.5,
    "success_probability_update": 0.85
}}"""

            response = await self._call_gpt5(prompt)
            analysis = json.loads(response.choices[0].message.content)

            return analysis

        except Exception as e:
            self.logger.error(f"Failed to analyze mission progress: {e}")
            return {
                "progress_percentage": 50.0,
                "performance_assessment": "Unable to assess due to analysis error",
                "identified_issues": [f"Analysis system error: {str(e)}"],
                "recommendations": ["Continue with original mission plan"],
                "mission_status": "unknown",
                "estimated_completion_time": mission.estimated_duration,
                "success_probability_update": mission.success_probability
            }

    def validate_api_connection(self) -> bool:
        """Validate OpenAI API connection and credentials."""
        try:
            # Simple validation call
            test_response = asyncio.run(
                self.client.chat.completions.create(
                    model="gpt-3.5-turbo",  # Use a basic model for testing
                    messages=[{"role": "user", "content": "Test connection"}],
                    max_tokens=10
                )
            )
            return True

        except Exception as e:
            self.logger.error(f"API validation failed: {e}")
            return False


class MissionContextBuilder:
    """Helper class to build mission context from various inputs."""

    @staticmethod
    def create_search_context(
        scenario: str,
        center_lat: float,
        center_lon: float,
        radius_m: float,
        num_drones: int,
        **kwargs
    ) -> MissionContext:
        """Create a mission context for search operations."""

        search_area = SearchArea(
            center=validate_gps_coordinate(center_lat, center_lon),
            radius_m=radius_m,
            min_altitude=kwargs.get("min_altitude", 15.0),
            max_altitude=kwargs.get("max_altitude", 50.0)
        )

        # Default drone capabilities
        drone_capabilities = [
            {
                "drone_id": i + 1,
                "max_speed": 15.0,
                "max_altitude": 120.0,
                "battery_life": 25.0,
                "camera_capabilities": "4K video, thermal imaging",
                "payload_capacity": 0.5
            }
            for i in range(num_drones)
        ]

        # Default environmental conditions
        environmental_conditions = {
            "weather": kwargs.get("weather", "Clear skies"),
            "wind_speed": kwargs.get("wind_speed", 5.0),
            "visibility": kwargs.get("visibility", "Excellent"),
            "temperature": kwargs.get("temperature", 20.0),
            "time_of_day": kwargs.get("time_of_day", "Daytime")
        }

        return MissionContext(
            scenario_description=scenario,
            search_area=search_area,
            num_drones=num_drones,
            drone_capabilities=drone_capabilities,
            environmental_conditions=environmental_conditions,
            time_constraints=kwargs.get("time_constraints"),
            priority_areas=kwargs.get("priority_areas"),
            known_obstacles=kwargs.get("known_obstacles")
        )