"""Configuration management for LLM Drone Controller."""

import os
from pathlib import Path
from typing import Optional, List
from pydantic import BaseSettings, Field, validator
from dotenv import load_dotenv


class OpenAIConfig(BaseSettings):
    """OpenAI GPT-5 configuration."""

    api_key: str = Field(..., env="OPENAI_API_KEY")
    model: str = Field(default="gpt-5", env="OPENAI_MODEL")
    model_variant: str = Field(default="gpt-5-mini", env="OPENAI_MODEL_VARIANT")
    verbosity: str = Field(default="medium", env="OPENAI_VERBOSITY")
    reasoning_effort: str = Field(default="medium", env="OPENAI_REASONING_EFFORT")
    max_tokens: int = Field(default=8192, env="OPENAI_MAX_TOKENS")
    temperature: float = Field(default=0.7, env="OPENAI_TEMPERATURE")
    enable_thinking: bool = Field(default=True, env="OPENAI_ENABLE_THINKING")

    @validator("verbosity")
    def validate_verbosity(cls, v):
        if v not in ["low", "medium", "high"]:
            raise ValueError("verbosity must be 'low', 'medium', or 'high'")
        return v

    @validator("reasoning_effort")
    def validate_reasoning_effort(cls, v):
        if v not in ["minimal", "low", "medium", "high"]:
            raise ValueError("reasoning_effort must be 'minimal', 'low', 'medium', or 'high'")
        return v


class DroneConfig(BaseSettings):
    """Drone configuration."""

    count: int = Field(default=3, env="DRONE_COUNT")
    base_port: int = Field(default=14540, env="DRONE_BASE_PORT")
    timeout_seconds: int = Field(default=30, env="DRONE_TIMEOUT_SECONDS")
    default_altitude: float = Field(default=20.0, env="PX4_DEFAULT_ALTITUDE")
    safety_radius: float = Field(default=100.0, env="PX4_SAFETY_RADIUS")

    @validator("count")
    def validate_count(cls, v):
        if v < 1 or v > 10:
            raise ValueError("drone count must be between 1 and 10")
        return v

    @property
    def ports(self) -> List[int]:
        """Get list of drone ports."""
        return [self.base_port + i for i in range(self.count)]

    @property
    def connection_strings(self) -> List[str]:
        """Get connection strings for all drones."""
        return [f"udp://:{port}" for port in self.ports]


class SearchConfig(BaseSettings):
    """Search area configuration."""

    center_lat: float = Field(default=47.397971057728974, env="DEFAULT_SEARCH_CENTER_LAT")
    center_lon: float = Field(default=8.546163739800146, env="DEFAULT_SEARCH_CENTER_LON")
    radius_m: float = Field(default=200.0, env="DEFAULT_SEARCH_RADIUS_M")

    @validator("center_lat")
    def validate_latitude(cls, v):
        if v < -90 or v > 90:
            raise ValueError("latitude must be between -90 and 90")
        return v

    @validator("center_lon")
    def validate_longitude(cls, v):
        if v < -180 or v > 180:
            raise ValueError("longitude must be between -180 and 180")
        return v


class WebConfig(BaseSettings):
    """Web interface configuration."""

    host: str = Field(default="0.0.0.0", env="WEB_HOST")
    port: int = Field(default=8080, env="WEB_PORT")
    websocket_port: int = Field(default=8765, env="WEBSOCKET_PORT")
    debug: bool = Field(default=False, env="WEB_DEBUG")


class TelemetryConfig(BaseSettings):
    """Telemetry configuration."""

    update_rate_hz: float = Field(default=1.0, env="TELEMETRY_UPDATE_RATE_HZ")
    log_enabled: bool = Field(default=True, env="TELEMETRY_LOG_ENABLED")
    log_path: str = Field(default="./logs", env="TELEMETRY_LOG_PATH")


class MissionConfig(BaseSettings):
    """Mission configuration."""

    planning_timeout: int = Field(default=30, env="MISSION_PLANNING_TIMEOUT")
    execution_timeout: int = Field(default=300, env="MISSION_EXECUTION_TIMEOUT")
    waypoint_tolerance_m: float = Field(default=2.0, env="WAYPOINT_TOLERANCE_M")


class SafetyConfig(BaseSettings):
    """Safety and emergency configuration."""

    emergency_land_enabled: bool = Field(default=True, env="EMERGENCY_LAND_ENABLED")
    low_battery_threshold: int = Field(default=25, env="LOW_BATTERY_THRESHOLD")
    max_flight_time_minutes: int = Field(default=15, env="MAX_FLIGHT_TIME_MINUTES")

    @validator("low_battery_threshold")
    def validate_battery_threshold(cls, v):
        if v < 0 or v > 100:
            raise ValueError("battery threshold must be between 0 and 100")
        return v


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: str = Field(default="INFO", env="LOG_LEVEL")
    file_enabled: bool = Field(default=True, env="LOG_FILE_ENABLED")
    file_path: str = Field(default="./logs/drone_controller.log", env="LOG_FILE_PATH")

    @validator("level")
    def validate_level(cls, v):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log level must be one of {valid_levels}")
        return v.upper()


class DevelopmentConfig(BaseSettings):
    """Development settings."""

    debug_mode: bool = Field(default=False, env="DEBUG_MODE")
    simulation_speed_factor: float = Field(default=1.0, env="SIMULATION_SPEED_FACTOR")
    enable_mock_drones: bool = Field(default=False, env="ENABLE_MOCK_DRONES")


class Config(BaseSettings):
    """Main configuration class."""

    # Sub-configurations
    openai: OpenAIConfig = OpenAIConfig()
    drone: DroneConfig = DroneConfig()
    search: SearchConfig = SearchConfig()
    web: WebConfig = WebConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    mission: MissionConfig = MissionConfig()
    safety: SafetyConfig = SafetyConfig()
    logging: LoggingConfig = LoggingConfig()
    development: DevelopmentConfig = DevelopmentConfig()

    # Global settings
    simulation_world: str = Field(default="search_rescue_enhanced", env="SIMULATION_WORLD")
    px4_sitl_path: str = Field(default="/home/cobe-liu/Developing/PX4-Autopilot", env="PX4_SITL_PATH")

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def __init__(self, **data):
        """Initialize configuration with environment loading."""
        # Load .env file from current directory or project root
        env_path = Path(".env")
        if not env_path.exists():
            # Try parent directories
            for parent in Path.cwd().parents:
                env_path = parent / ".env"
                if env_path.exists():
                    break

        if env_path.exists():
            load_dotenv(env_path)

        # Initialize sub-configs
        super().__init__(**data)

    def validate_all(self) -> bool:
        """Validate all configuration sections."""
        try:
            # Validate OpenAI API key is present
            if not self.openai.api_key or self.openai.api_key == "your_openai_api_key_here":
                raise ValueError("OpenAI API key not configured")

            # Validate PX4 path exists
            if not Path(self.px4_sitl_path).exists():
                raise ValueError(f"PX4 SITL path does not exist: {self.px4_sitl_path}")

            return True
        except Exception as e:
            print(f"Configuration validation failed: {e}")
            return False

    def create_directories(self):
        """Create necessary directories."""
        dirs_to_create = [
            self.telemetry.log_path,
            Path(self.logging.file_path).parent,
        ]

        for dir_path in dirs_to_create:
            Path(dir_path).mkdir(parents=True, exist_ok=True)


def get_config() -> Config:
    """Get configuration instance."""
    return Config()


def validate_config() -> bool:
    """Validate configuration and return True if valid."""
    config = get_config()
    return config.validate_all()


if __name__ == "__main__":
    # Test configuration loading
    config = get_config()
    print("Configuration loaded successfully!")
    print(f"OpenAI Model: {config.openai.model}")
    print(f"Drone Count: {config.drone.count}")
    print(f"Drone Ports: {config.drone.ports}")

    if config.validate_all():
        print(" Configuration validation passed")
    else:
        print("L Configuration validation failed")