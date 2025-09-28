# LLM Drone Controller - Testing Guide

## Current Test Environment

### Active Simulation
- **World**: `search_rescue_enhanced.sdf` (suburban environment with people)
- **Drone Available**: 1 x500 quadcopter on port 14540
- **GPS Reference**: 47.3977°N, 8.5456°E (Zurich, Switzerland)
- **MAVLink Status**: Connected and ready for commands

### World Environment Details

#### Search Targets (People)
- **rescue_target_1**: Standing person at (26, 4) meters from origin
- **rescue_target_2**: Standing person at (-24, -10) meters from origin

#### Key Landmarks
- **Central Plaza**: (0, 0) - Clear takeoff/landing area (12x12m)
- **Operations Center**: (22, 0) - Large building for reference
- **Suburban Houses**: Grid pattern from -18 to +18 on X/Y axes
- **Trees**: Perimeter at ±18m positions

#### Safe Flying Zones
- **Central Area**: ±15m from origin (clear of major obstacles)
- **Altitude Range**: 5-50m (safe above buildings, below airspace limits)
- **No-Fly Zones**: Directly over houses (collision risk)

## Testing Framework

### Prerequisites

1. **Verify Simulation Status**:
   ```bash
   # Check if PX4 is running
   ps aux | grep px4

   # Check MAVLink connections
   netstat -an | grep 14540
   ```

2. **Verify Environment Setup**:
   ```bash
   cd /home/cobe-liu/Developing/llm-drone-controller
   source venv/bin/activate  # If using virtual environment
   python -c "from src.utils.config import get_config; print('Config loaded successfully')"
   ```

### Test Categories

## 1. Basic Connection Tests

### Test 1.1: Drone Connection
```python
# File: test_connection.py
import asyncio
from src.drone_manager import DroneManager
from src.utils.config import get_config

async def test_connection():
    config = get_config()
    drone = DroneManager(1, "udp://:14540", config)

    print("Attempting to connect to drone...")
    connected = await drone.connect()

    if connected:
        print("✅ Connection successful!")
        telemetry = await drone.get_telemetry()
        print(f"📍 Position: {telemetry['position']}")
        print(f"🔋 Battery: {telemetry['battery']['percent']}%")
        print(f"🛰️ GPS Satellites: {telemetry['gps']['satellites']}")
    else:
        print("❌ Connection failed!")

    await drone.disconnect()

# Run: python -c "import asyncio; from test_connection import test_connection; asyncio.run(test_connection())"
```

**Expected Results**:
- Connection establishes within 5 seconds
- GPS coordinates near 47.3977°N, 8.5456°E
- Battery at 100%
- 10+ GPS satellites

### Test 1.2: Health Check
```python
# File: test_health.py
import asyncio
from src.drone_manager import DroneManager
from src.utils.config import get_config

async def test_health():
    config = get_config()
    drone = DroneManager(1, "udp://:14540", config)
    await drone.connect()

    print("Waiting for global position fix...")
    health_ok = await drone.wait_for_global_position()

    if health_ok:
        print("✅ Drone ready for flight!")
    else:
        print("❌ Health check failed!")

    await drone.disconnect()

# Run: python -c "import asyncio; from test_health import test_health; asyncio.run(test_health())"
```

## 2. Basic Flight Tests

### Test 2.1: Safe Takeoff and Landing
```python
# File: test_takeoff.py
import asyncio
from src.drone_manager import DroneManager
from src.utils.config import get_config

async def test_takeoff_landing():
    config = get_config()
    drone = DroneManager(1, "udp://:14540", config)
    await drone.connect()

    print("🚀 Starting takeoff test...")

    # Takeoff to safe altitude
    success = await drone.arm_and_takeoff(15.0)  # 15m altitude
    if success:
        print("✅ Takeoff successful!")

        # Wait a moment
        await asyncio.sleep(5)

        # Land
        landing_success = await drone.land()
        if landing_success:
            print("✅ Landing successful!")
        else:
            print("❌ Landing failed!")
    else:
        print("❌ Takeoff failed!")

    await drone.disconnect()

# Run: python -c "import asyncio; from test_takeoff import test_takeoff_landing; asyncio.run(test_takeoff_landing())"
```

**Expected Results**:
- Drone arms within 2 seconds
- Smooth takeoff to 15m altitude
- Stable hover for 5 seconds
- Controlled landing at origin

### Test 2.2: Simple Navigation
```python
# File: test_navigation.py
import asyncio
from src.drone_manager import DroneManager
from src.utils.config import get_config
from src.utils.validators import validate_gps_coordinate

async def test_navigation():
    config = get_config()
    drone = DroneManager(1, "udp://:14540", config)
    await drone.connect()

    print("🧭 Testing navigation...")

    # Takeoff
    await drone.arm_and_takeoff(20.0)

    # Navigate to safe position near first target
    target_coord = validate_gps_coordinate(
        47.397993,  # Slightly north of origin
        8.546163,   # Near longitude center
        20.0        # 20m altitude
    )

    print(f"📍 Flying to: {target_coord.latitude}, {target_coord.longitude}")
    nav_success = await drone.goto_location(target_coord, speed=5.0)

    if nav_success:
        print("✅ Navigation successful!")
        await asyncio.sleep(5)  # Hover for observation
    else:
        print("❌ Navigation failed!")

    # Return and land
    await drone.land()
    await drone.disconnect()

# Run: python -c "import asyncio; from test_navigation import test_navigation; asyncio.run(test_navigation())"
```

## 3. Mission Planning Tests

### Test 3.1: GPT-5 Mission Generation
```python
# File: test_gpt5_planning.py
import asyncio
from src.gpt5_agent import GPT5MissionPlanner, MissionContextBuilder

async def test_mission_planning():
    print("🤖 Testing GPT-5 mission planning...")

    # Create mission context for our world
    context = MissionContextBuilder.create_search_context(
        scenario="Search for two missing persons in suburban area with houses and trees",
        center_lat=47.397971,
        center_lon=8.546164,
        radius_m=50,  # Small radius for testing
        num_drones=1,
        weather="Clear skies",
        wind_speed=2.0
    )

    # Generate mission
    planner = GPT5MissionPlanner()

    # Note: This requires valid OpenAI API key in .env
    try:
        mission = await planner.generate_search_mission(context)

        print("✅ Mission generated successfully!")
        print(f"📋 Strategy: {mission.strategy_summary}")
        print(f"🎯 Success Probability: {mission.success_probability}")
        print(f"⏱️ Estimated Duration: {mission.estimated_duration} minutes")
        print(f"🛩️ Waypoints for drone 1: {len(mission.drone_missions[0])}")

        # Print first few waypoints
        for i, wp in enumerate(mission.drone_missions[0][:3]):
            print(f"  Waypoint {i+1}: ({wp.coordinate.latitude:.6f}, {wp.coordinate.longitude:.6f}) at {wp.coordinate.altitude}m")

    except Exception as e:
        print(f"❌ Mission planning failed: {e}")
        print("Note: Ensure OPENAI_API_KEY is set in .env file")

# Run: python -c "import asyncio; from test_gpt5_planning import test_mission_planning; asyncio.run(test_mission_planning())"
```

### Test 3.2: Mission Validation
```python
# File: test_mission_validation.py
from src.utils.validators import Waypoint, validate_gps_coordinate, MissionValidation

def test_mission_validation():
    print("✅ Testing mission validation...")

    # Create test waypoints for our world
    good_waypoints = [
        Waypoint(
            coordinate=validate_gps_coordinate(47.397971, 8.546164, 20.0),
            speed=5.0,
            action="search"
        ),
        Waypoint(
            coordinate=validate_gps_coordinate(47.397990, 8.546180, 20.0),
            speed=5.0,
            action="search"
        )
    ]

    # Test valid mission
    valid, errors = MissionValidation.validate_waypoint_sequence(good_waypoints)
    print(f"Good waypoints validation: {'✅ PASS' if valid else '❌ FAIL'}")
    if errors:
        print(f"Errors: {errors}")

    # Test invalid waypoints (too close together)
    bad_waypoints = [
        Waypoint(
            coordinate=validate_gps_coordinate(47.397971, 8.546164, 20.0),
            speed=5.0,
            action="search"
        ),
        Waypoint(
            coordinate=validate_gps_coordinate(47.397971, 8.546164, 20.0),  # Same location!
            speed=5.0,
            action="search"
        )
    ]

    valid, errors = MissionValidation.validate_waypoint_sequence(bad_waypoints)
    print(f"Bad waypoints validation: {'❌ FAIL (expected)' if not valid else '⚠️ UNEXPECTED PASS'}")
    if errors:
        print(f"Expected errors: {errors}")

# Run: python test_mission_validation.py
```

## 4. Integration Tests

### Test 4.1: End-to-End Mission Execution
```python
# File: test_e2e_mission.py
import asyncio
from src.drone_manager import DroneManager
from src.gpt5_agent import GPT5MissionPlanner, MissionContextBuilder
from src.utils.config import get_config

async def test_end_to_end():
    print("🎯 End-to-end mission test...")

    config = get_config()
    drone = DroneManager(1, "udp://:14540", config)

    # Connect to drone
    await drone.connect()

    # Create simple mission context
    context = MissionContextBuilder.create_search_context(
        scenario="Quick test flight to verify rescue target locations",
        center_lat=47.397971,
        center_lon=8.546164,
        radius_m=30,  # Small radius for quick test
        num_drones=1
    )

    # Manual waypoints for testing (without GPT-5 dependency)
    from src.utils.validators import Waypoint, validate_gps_coordinate

    test_waypoints = [
        # Takeoff point (origin)
        Waypoint(
            coordinate=validate_gps_coordinate(47.397971, 8.546164, 15.0),
            speed=3.0,
            action="search",
            loiter_time=2.0
        ),
        # Near rescue_target_1 (26, 4 in local coordinates)
        Waypoint(
            coordinate=validate_gps_coordinate(47.397993, 8.546200, 15.0),
            speed=3.0,
            action="search",
            loiter_time=3.0
        ),
        # Return to center
        Waypoint(
            coordinate=validate_gps_coordinate(47.397971, 8.546164, 15.0),
            speed=3.0,
            action="search",
            loiter_time=2.0
        )
    ]

    try:
        # Takeoff
        print("🚀 Taking off...")
        await drone.arm_and_takeoff(15.0)

        # Upload mission
        print("📤 Uploading mission...")
        mission_success = await drone.upload_mission(test_waypoints)

        if mission_success:
            print("✅ Mission uploaded successfully!")

            # Start mission
            print("▶️ Starting mission...")
            start_success = await drone.start_mission()

            if start_success:
                print("✅ Mission started!")

                # Monitor progress
                for i in range(30):  # Monitor for 30 seconds
                    telemetry = await drone.get_telemetry()
                    print(f"📍 Position: {telemetry['position']['lat']:.6f}, {telemetry['position']['lon']:.6f}")
                    print(f"🎯 Mission active: {telemetry.get('mission_active', 'Unknown')}")

                    await asyncio.sleep(2)

                    # Check if landed (mission complete)
                    if not telemetry['in_air']:
                        print("✅ Mission completed - drone landed!")
                        break
            else:
                print("❌ Failed to start mission")
        else:
            print("❌ Failed to upload mission")

    except Exception as e:
        print(f"❌ Test failed: {e}")

    finally:
        # Ensure safe landing
        if drone.status.in_air:
            print("🛬 Emergency landing...")
            await drone.land()

        await drone.disconnect()
        print("🔌 Disconnected from drone")

# Run: python -c "import asyncio; from test_e2e_mission import test_end_to_end; asyncio.run(test_end_to_end())"
```

## 5. Good vs Bad Commands Reference

### ✅ Good Commands (Safe in Current World)

#### Safe GPS Coordinates
```python
# Origin area (central plaza)
lat=47.397971, lon=8.546164, alt=15-30m

# Near rescue targets (but not directly over)
lat=47.397990, lon=8.546180, alt=15-25m  # Near target 1
lat=47.397950, lon=8.546140, alt=15-25m  # Near target 2

# Safe survey points (avoiding houses)
lat=47.397980, lon=8.546164, alt=20m     # North of center
lat=47.397960, lon=8.546164, alt=20m     # South of center
```

#### Safe Flight Parameters
```python
# Altitudes
alt=15-30m     # Above houses, below 50m limit
alt=35-45m     # Higher altitude for overview

# Speeds
speed=3-8m/s   # Conservative speeds for precision
speed=10m/s    # Maximum safe speed

# Actions
action="search"    # Standard search pattern
action="hover"     # Stationary observation
action="photo"     # Photo capture at waypoint
```

#### Safe Mission Patterns
```python
# Grid search (small area)
radius_m=25-50     # Manageable area size
waypoint_count=4-8 # Reasonable complexity

# Altitude layers
low_alt=15m        # Building clearance
medium_alt=25m     # Standard search altitude
high_alt=35m       # Overview altitude
```

### ❌ Bad Commands (Dangerous/Invalid)

#### Dangerous GPS Coordinates
```python
# Outside world boundaries
lat=47.398500, lon=8.547000  # Too far from origin
lat=47.397000, lon=8.545000  # Too far south/west

# Directly over buildings (collision risk)
lat=47.397990, lon=8.546320  # Over eastern houses
lat=47.397950, lon=8.546000  # Over western houses
```

#### Dangerous Flight Parameters
```python
# Unsafe altitudes
alt=5m             # Too low (collision with buildings)
alt=60m            # Above safety limit
alt=0m             # Ground level

# Unsafe speeds
speed=20m/s        # Too fast for suburban area
speed=0.5m/s       # Too slow (inefficient)

# Invalid actions
action="attack"    # Not supported
action="land_here" # Unsafe landing zones
```

#### Dangerous Mission Patterns
```python
# Too large area
radius_m=200       # Exceeds world boundaries
radius_m=500       # Way too large

# Too complex
waypoint_count=50  # Excessive complexity
waypoint_count=100 # System overload risk

# Conflicting waypoints
same_coordinates   # Multiple waypoints at exact same spot
rapid_altitude_changes  # 5m to 50m to 5m quickly
```

## 6. Troubleshooting Guide

### Common Issues

#### Connection Problems
```bash
# Issue: "Connection timeout"
# Solution: Check PX4 is running
ps aux | grep px4
# Restart PX4 if needed

# Issue: "Port already in use"
# Solution: Check for existing connections
netstat -an | grep 14540
lsof -i :14540
```

#### Flight Issues
```bash
# Issue: "Preflight checks failed"
# Solution: Wait for GPS fix
# GPS should show 8+ satellites

# Issue: "Takeoff failed"
# Solution: Check armed status and GPS health
# Ensure drone is in correct flight mode
```

#### Mission Issues
```python
# Issue: "Mission validation failed"
# Solution: Check waypoint spacing and altitudes
# Ensure coordinates are within world bounds

# Issue: "GPT-5 API error"
# Solution: Verify API key in .env file
# Check internet connection and API quota
```

### Performance Monitoring

#### Real-time Telemetry Check
```python
# Monitor drone status
telemetry = await drone.get_telemetry()
print(f"Battery: {telemetry['battery']['percent']}%")
print(f"GPS Sats: {telemetry['gps']['satellites']}")
print(f"Altitude: {telemetry['position']['altitude']}m")
```

#### System Resource Check
```bash
# CPU usage
top -p $(pgrep px4)

# Memory usage
ps -o pid,vsz,rss,comm -p $(pgrep px4)

# Network connections
netstat -an | grep -E "1454[0-2]"
```

## 7. Test Execution Order

### Recommended Testing Sequence

1. **Basic Tests** (10 minutes)
   - Connection test
   - Health check
   - Telemetry verification

2. **Flight Tests** (15 minutes)
   - Safe takeoff/landing
   - Simple navigation
   - Return-to-launch

3. **Mission Tests** (20 minutes)
   - Manual waypoint missions
   - GPT-5 planning (if API available)
   - Mission validation

4. **Integration Tests** (30 minutes)
   - End-to-end mission execution
   - Multi-waypoint navigation
   - Emergency procedures

### Success Criteria

- ✅ All connections establish within 5 seconds
- ✅ GPS lock with 8+ satellites
- ✅ Successful takeoff to 15m altitude
- ✅ Accurate navigation to target coordinates
- ✅ Mission waypoints executed in sequence
- ✅ Safe landing at origin
- ✅ No system errors or exceptions

This testing framework provides comprehensive validation of the LLM Drone Controller system integration with PX4 and MAVLink, ensuring safe and reliable operation in the search_rescue_enhanced simulation environment.