"""Configuration management for LLM Drone Controller."""

import os
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv


class OpenAIConfig(BaseSettings):
    """OpenAI GPT-5 configuration."""

    api_key: str = Field(default="test_key", env="OPENAI_API_KEY")
    model: str = Field(default="gpt-5", env="OPENAI_MODEL")
    model_variant: str = Field(default="gpt-5-mini", env="OPENAI_MODEL_VARIANT")
    verbosity: str = Field(default="medium", env="OPENAI_VERBOSITY")
    reasoning_effort: str = Field(default="medium", env="OPENAI_REASONING_EFFORT")
    max_tokens: int = Field(default=8192, env="OPENAI_MAX_TOKENS")
    temperature: float = Field(default=0.7, env="OPENAI_TEMPERATURE")
    enable_thinking: bool = Field(default=True, env="OPENAI_ENABLE_THINKING")

    def __init__(self, **data):
        """Initialize with environment loading."""
        # Load .env files BEFORE calling super().__init__()
        env_files = [".env.local", ".env"]
        for env_file in env_files:
            env_path = Path(env_file)
            if not env_path.exists():
                # Try parent directories
                for parent in Path.cwd().parents:
                    env_path = parent / env_file
                    if env_path.exists():
                        break
            if env_path.exists():
                load_dotenv(env_path)
                break
        super().__init__(**data)

    class Config:
        """Pydantic configuration."""
        env_file = [".env.local", ".env"]
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"

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
    base_port: int = Field(default=14541, env="DRONE_BASE_PORT")
    timeout_seconds: int = Field(default=30, env="DRONE_TIMEOUT_SECONDS")
    default_altitude: float = Field(default=20.0, env="PX4_DEFAULT_ALTITUDE")
    safety_radius: float = Field(default=100.0, env="PX4_SAFETY_RADIUS")
    waypoint_radius_m: float = Field(default=2.0, env="DRONE_WAYPOINT_RADIUS_M")
    max_flight_time_s: int = Field(default=900, env="DRONE_MAX_FLIGHT_TIME_S")
    battery_warning_threshold: float = Field(default=30.0, env="DRONE_BATTERY_WARNING_THRESHOLD")
    battery_critical_threshold: float = Field(default=15.0, env="DRONE_BATTERY_CRITICAL_THRESHOLD")
    min_gps_satellites: int = Field(default=8, env="DRONE_MIN_GPS_SATELLITES")

    @validator("count")
    def validate_count(cls, v):
        if v < 1 or v > 10:
            raise ValueError("drone count must be between 1 and 10")
        return v

    @validator("waypoint_radius_m")
    def validate_waypoint_radius(cls, v):
        if v <= 0:
            raise ValueError("waypoint radius must be positive")
        return v

    @validator("max_flight_time_s")
    def validate_max_flight_time(cls, v):
        if v <= 0:
            raise ValueError("max flight time must be positive")
        return v

    @validator("battery_warning_threshold")
    def validate_battery_warning(cls, v):
        if v <= 0 or v > 100:
            raise ValueError("battery warning threshold must be between 0 and 100")
        return v

    @validator("battery_critical_threshold")
    def validate_battery_critical(cls, v, values):
        if v <= 0 or v > 100:
            raise ValueError("battery critical threshold must be between 0 and 100")
        warning = values.get("battery_warning_threshold", 30.0)
        if v >= warning:
            raise ValueError("battery critical threshold must be less than warning threshold")
        return v

    @validator("min_gps_satellites")
    def validate_min_gps(cls, v):
        if v < 0:
            raise ValueError("minimum GPS satellites cannot be negative")
        return v

    @property
    def ports(self) -> List[int]:
        """Get list of drone ports."""
        return [self.base_port + i for i in range(self.count)]

    @property
    def connection_strings(self) -> List[str]:
        """Get connection strings for all drones."""
        return [f"udpin://0.0.0.0:{port}" for port in self.ports]


class SearchConfig(BaseSettings):
    """Search area configuration."""

    center_lat: float = Field(default=47.397971057728974, env="DEFAULT_SEARCH_CENTER_LAT")
    center_lon: float = Field(default=8.546163739800146, env="DEFAULT_SEARCH_CENTER_LON")
    radius_m: float = Field(default=200.0, env="DEFAULT_SEARCH_RADIUS_M")
    max_altitude_m: float = Field(default=120.0, env="DEFAULT_SEARCH_MAX_ALTITUDE_M")

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

    @validator("max_altitude_m")
    def validate_max_altitude(cls, v):
        if v <= 0:
            raise ValueError("max altitude must be positive")
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
    update_interval_s: Optional[float] = Field(default=None, env="TELEMETRY_UPDATE_INTERVAL_S")
    alert_retention_hours: float = Field(default=2.0, env="TELEMETRY_ALERT_RETENTION_HOURS")
    log_enabled: bool = Field(default=True, env="TELEMETRY_LOG_ENABLED")
    log_path: str = Field(default="./logs", env="TELEMETRY_LOG_PATH")

    @validator("update_rate_hz")
    def validate_update_rate(cls, v):
        if v <= 0:
            raise ValueError("telemetry update rate must be positive")
        return v

    @validator("alert_retention_hours")
    def validate_alert_retention(cls, v):
        if v <= 0:
            raise ValueError("alert retention must be positive")
        return v

    @validator("update_interval_s", always=True)
    def set_update_interval(cls, v, values):
        if v is not None:
            if v <= 0:
                raise ValueError("telemetry update interval must be positive")
            return v

        rate = values.get("update_rate_hz", 1.0)
        return 1.0 / rate if rate > 0 else 1.0


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

    # Global settings
    simulation_world: str = Field(default="search_rescue_enhanced", env="SIMULATION_WORLD")
    px4_sitl_path: str = Field(default="/home/cobe-liu/Developing/PX4-Autopilot", env="PX4_SITL_PATH")

    class Config:
        """Pydantic configuration."""
        env_file = [".env.local", ".env"]  # Try .env.local first, then .env
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables

    def __init__(self, **data):
        """Initialize configuration with environment loading."""
        # Load .env files from current directory or project root
        # Try .env.local first, then .env
        env_files_to_try = [".env.local", ".env"]

        for env_file in env_files_to_try:
            env_path = Path(env_file)
            if not env_path.exists():
                # Try parent directories
                for parent in Path.cwd().parents:
                    env_path = parent / env_file
                    if env_path.exists():
                        break

            if env_path.exists():
                load_dotenv(env_path)
                break  # Use the first env file found

        # Initialize parent class first
        super().__init__(**data)

        # Cache sub-configs to avoid re-instantiation
        self._openai_config = None
        self._drone_config = None
        self._search_config = None
        self._web_config = None
        self._telemetry_config = None
        self._mission_config = None
        self._safety_config = None
        self._logging_config = None
        self._development_config = None

    @property
    def openai(self) -> OpenAIConfig:
        """Get OpenAI configuration."""
        if self._openai_config is None:
            # Pass environment variables explicitly
            import os
            self._openai_config = OpenAIConfig(
                api_key=os.getenv("OPENAI_API_KEY", "test_key"),
                model=os.getenv("OPENAI_MODEL", "gpt-5"),
                model_variant=os.getenv("OPENAI_MODEL_VARIANT", "gpt-5-mini"),
                verbosity=os.getenv("OPENAI_VERBOSITY", "medium"),
                reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "medium"),
                max_tokens=int(os.getenv("OPENAI_MAX_TOKENS", "8192")),
                temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
                enable_thinking=os.getenv("OPENAI_ENABLE_THINKING", "true").lower() == "true"
            )
        return self._openai_config

    @property
    def drone(self) -> DroneConfig:
        """Get drone configuration."""
        if self._drone_config is None:
            self._drone_config = DroneConfig()
        return self._drone_config

    @property
    def search(self) -> SearchConfig:
        """Get search configuration."""
        if self._search_config is None:
            self._search_config = SearchConfig()
        return self._search_config

    @property
    def web(self) -> WebConfig:
        """Get web configuration."""
        if self._web_config is None:
            self._web_config = WebConfig()
        return self._web_config

    @property
    def telemetry(self) -> TelemetryConfig:
        """Get telemetry configuration."""
        if self._telemetry_config is None:
            self._telemetry_config = TelemetryConfig()
        return self._telemetry_config

    @property
    def mission(self) -> MissionConfig:
        """Get mission configuration."""
        if self._mission_config is None:
            # Pass environment variables explicitly
            import os
            self._mission_config = MissionConfig(
                planning_timeout=int(os.getenv("MISSION_PLANNING_TIMEOUT", "30")),
                execution_timeout=int(os.getenv("MISSION_EXECUTION_TIMEOUT", "300")),
                waypoint_tolerance_m=float(os.getenv("WAYPOINT_TOLERANCE_M", "2.0"))
            )
        return self._mission_config

    @property
    def safety(self) -> SafetyConfig:
        """Get safety configuration."""
        if self._safety_config is None:
            self._safety_config = SafetyConfig()
        return self._safety_config

    @property
    def logging(self) -> LoggingConfig:
        """Get logging configuration."""
        if self._logging_config is None:
            self._logging_config = LoggingConfig()
        return self._logging_config

    @property
    def development(self) -> DevelopmentConfig:
        """Get development configuration."""
        if self._development_config is None:
            self._development_config = DevelopmentConfig()
        return self._development_config

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
