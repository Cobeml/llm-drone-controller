"""Input validation utilities for LLM Drone Controller."""

import math
import re
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel, validator, Field
from geopy.distance import geodesic


class GPSCoordinate(BaseModel):
    """GPS coordinate validation."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude: Optional[float] = Field(default=None, ge=0)

    def distance_to(self, other: "GPSCoordinate") -> float:
        """Calculate distance to another coordinate in meters."""
        return geodesic(
            (self.latitude, self.longitude),
            (other.latitude, other.longitude)
        ).meters

    def bearing_to(self, other: "GPSCoordinate") -> float:
        """Calculate bearing to another coordinate in degrees."""
        lat1, lon1 = math.radians(self.latitude), math.radians(self.longitude)
        lat2, lon2 = math.radians(other.latitude), math.radians(other.longitude)

        dlon = lon2 - lon1

        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)

        bearing = math.atan2(y, x)
        return (math.degrees(bearing) + 360) % 360


class Waypoint(BaseModel):
    """Waypoint validation."""

    coordinate: GPSCoordinate
    speed: float = Field(default=5.0, ge=0.1, le=20.0)
    action: str = Field(default="search")
    loiter_time: float = Field(default=0.0, ge=0)
    photo_interval: float = Field(default=0.0, ge=0)
    gimbal_pitch: float = Field(default=0.0, ge=-90, le=90)
    gimbal_yaw: float = Field(default=0.0, ge=-180, le=180)

    @validator("action")
    def validate_action(cls, v):
        valid_actions = ["search", "hover", "photo", "land", "takeoff", "rtl"]
        if v not in valid_actions:
            raise ValueError(f"action must be one of {valid_actions}")
        return v

    def to_mavsdk_dict(self) -> Dict[str, Any]:
        """Convert to MAVSDK mission item format."""
        return {
            "lat": self.coordinate.latitude,
            "lon": self.coordinate.longitude,
            "alt": self.coordinate.altitude or 20.0,
            "speed": self.speed,
            "action": self.action,
            "loiter_time": self.loiter_time,
            "photo_interval": self.photo_interval,
            "gimbal_pitch": self.gimbal_pitch,
            "gimbal_yaw": self.gimbal_yaw,
        }


class SearchArea(BaseModel):
    """Search area validation."""

    center: GPSCoordinate
    radius_m: float = Field(..., ge=10, le=5000)
    min_altitude: float = Field(default=10.0, ge=5)
    max_altitude: float = Field(default=100.0, le=500)

    @validator("max_altitude")
    def validate_altitudes(cls, v, values):
        if "min_altitude" in values and v <= values["min_altitude"]:
            raise ValueError("max_altitude must be greater than min_altitude")
        return v

    def contains_point(self, point: GPSCoordinate) -> bool:
        """Check if a point is within the search area."""
        distance = self.center.distance_to(point)
        return distance <= self.radius_m


class DroneCapabilities(BaseModel):
    """Drone capabilities validation."""

    max_speed: float = Field(default=15.0, ge=1, le=30)
    max_altitude: float = Field(default=120.0, ge=10, le=500)
    max_range: float = Field(default=1000.0, ge=100, le=10000)
    battery_capacity: float = Field(default=100.0, ge=0, le=100)
    payload_weight: float = Field(default=0.0, ge=0)

    def can_reach_point(self, current: GPSCoordinate, target: GPSCoordinate) -> bool:
        """Check if drone can reach target from current position."""
        distance = current.distance_to(target)
        return distance <= self.max_range


class MissionValidation:
    """Mission validation utilities."""

    @staticmethod
    def validate_waypoint_sequence(waypoints: List[Waypoint]) -> Tuple[bool, List[str]]:
        """Validate a sequence of waypoints."""
        errors = []

        if not waypoints:
            errors.append("Mission must contain at least one waypoint")
            return False, errors

        if len(waypoints) > 50:
            errors.append("Mission cannot exceed 50 waypoints")

        # Check waypoint spacing
        for i in range(1, len(waypoints)):
            distance = waypoints[i-1].coordinate.distance_to(waypoints[i].coordinate)
            if distance < 1.0:
                errors.append(f"Waypoints {i-1} and {i} are too close (<1m)")
            elif distance > 1000.0:
                errors.append(f"Waypoints {i-1} and {i} are too far apart (>1km)")

        # Check altitude consistency
        altitudes = [wp.coordinate.altitude for wp in waypoints if wp.coordinate.altitude]
        if altitudes:
            min_alt, max_alt = min(altitudes), max(altitudes)
            if max_alt - min_alt > 50:
                errors.append("Altitude variation exceeds 50m between waypoints")

        return len(errors) == 0, errors

    @staticmethod
    def validate_search_pattern(waypoints: List[Waypoint], search_area: SearchArea) -> Tuple[bool, List[str]]:
        """Validate waypoints form a valid search pattern."""
        errors = []

        # Check all waypoints are within search area
        for i, wp in enumerate(waypoints):
            if not search_area.contains_point(wp.coordinate):
                errors.append(f"Waypoint {i} is outside search area")

        # Check pattern coverage (basic grid detection)
        if len(waypoints) < 4:
            errors.append("Search pattern should have at least 4 waypoints for adequate coverage")

        return len(errors) == 0, errors

    @staticmethod
    def validate_multi_drone_mission(missions: List[List[Waypoint]]) -> Tuple[bool, List[str]]:
        """Validate missions for multiple drones."""
        errors = []

        if not missions:
            errors.append("No missions provided")
            return False, errors

        # Check for waypoint conflicts (too close in space and time)
        for i, mission1 in enumerate(missions):
            for j, mission2 in enumerate(missions[i+1:], i+1):
                conflicts = MissionValidation._detect_waypoint_conflicts(mission1, mission2)
                if conflicts:
                    errors.extend([f"Drone {i} and {j}: {conflict}" for conflict in conflicts])

        return len(errors) == 0, errors

    @staticmethod
    def _detect_waypoint_conflicts(mission1: List[Waypoint], mission2: List[Waypoint]) -> List[str]:
        """Detect potential conflicts between two missions."""
        conflicts = []
        min_separation = 10.0  # Minimum separation in meters

        # Simple temporal conflict detection
        for i, wp1 in enumerate(mission1):
            for j, wp2 in enumerate(mission2):
                distance = wp1.coordinate.distance_to(wp2.coordinate)
                time_diff = abs(i - j)  # Simplified time estimation

                if distance < min_separation and time_diff < 2:
                    conflicts.append(f"Waypoints too close: {distance:.1f}m separation")

        return conflicts


class TelemetryValidation:
    """Telemetry data validation."""

    @staticmethod
    def validate_position_data(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate position telemetry data."""
        errors = []
        required_fields = ["latitude", "longitude", "altitude", "heading"]

        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")

        try:
            if "latitude" in data:
                lat = float(data["latitude"])
                if not -90 <= lat <= 90:
                    errors.append(f"Invalid latitude: {lat}")

            if "longitude" in data:
                lon = float(data["longitude"])
                if not -180 <= lon <= 180:
                    errors.append(f"Invalid longitude: {lon}")

            if "altitude" in data:
                alt = float(data["altitude"])
                if not -1000 <= alt <= 10000:
                    errors.append(f"Invalid altitude: {alt}")

            if "heading" in data:
                heading = float(data["heading"])
                if not 0 <= heading <= 360:
                    errors.append(f"Invalid heading: {heading}")

        except (ValueError, TypeError) as e:
            errors.append(f"Data type error: {e}")

        return len(errors) == 0, errors

    @staticmethod
    def validate_battery_data(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate battery telemetry data."""
        errors = []

        try:
            if "voltage" in data:
                voltage = float(data["voltage"])
                if not 0 <= voltage <= 30:
                    errors.append(f"Invalid voltage: {voltage}V")

            if "remaining_percent" in data:
                percent = float(data["remaining_percent"])
                if not 0 <= percent <= 100:
                    errors.append(f"Invalid battery percentage: {percent}%")

        except (ValueError, TypeError) as e:
            errors.append(f"Battery data type error: {e}")

        return len(errors) == 0, errors


class OpenAIPromptValidation:
    """OpenAI prompt validation."""

    @staticmethod
    def validate_mission_prompt(prompt: str) -> Tuple[bool, List[str]]:
        """Validate mission planning prompt."""
        errors = []

        if not prompt or not prompt.strip():
            errors.append("Prompt cannot be empty")
            return False, errors

        if len(prompt) < 10:
            errors.append("Prompt too short (minimum 10 characters)")

        if len(prompt) > 4000:
            errors.append("Prompt too long (maximum 4000 characters)")

        # Check for potentially harmful content
        harmful_patterns = [
            r"attack",
            r"weapon",
            r"bomb",
            r"explosive",
            r"military\s+target",
        ]

        for pattern in harmful_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                errors.append(f"Prompt contains potentially harmful content: {pattern}")

        return len(errors) == 0, errors

    @staticmethod
    def sanitize_prompt(prompt: str) -> str:
        """Sanitize prompt for safe usage."""
        # Remove potentially harmful content
        sanitized = re.sub(r"[^\w\s\.,;:!?\-()[\]{}\"']", "", prompt)

        # Limit length
        if len(sanitized) > 4000:
            sanitized = sanitized[:4000] + "..."

        return sanitized.strip()


def validate_gps_coordinate(lat: float, lon: float, alt: Optional[float] = None) -> GPSCoordinate:
    """Create and validate a GPS coordinate."""
    return GPSCoordinate(latitude=lat, longitude=lon, altitude=alt)


def validate_search_area_input(center_lat: float, center_lon: float, radius_m: float) -> SearchArea:
    """Create and validate a search area."""
    center = validate_gps_coordinate(center_lat, center_lon)
    return SearchArea(center=center, radius_m=radius_m)


if __name__ == "__main__":
    # Test validation functions
    print("Testing GPS coordinate validation...")
    coord = validate_gps_coordinate(47.3977, 8.5456, 20.0)
    print(f" Valid coordinate: {coord}")

    print("\nTesting search area validation...")
    area = validate_search_area_input(47.3977, 8.5456, 200.0)
    print(f" Valid search area: {area}")

    print("\nTesting waypoint validation...")
    wp = Waypoint(coordinate=coord, speed=5.0, action="search")
    print(f" Valid waypoint: {wp}")

    print("\nAll validation tests passed!")