#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Drone Controller - Main Application Entry Point

Coordinates GPT-5 powered mission planning with multi-drone execution
for search and rescue operations in realistic simulation environments.
"""

import asyncio
import logging
import signal
import sys
from typing import Dict, List, Optional
from datetime import datetime

import click
from rich.console import Console

from src.utils.config import Config
from src.drone_manager import MultiDroneManager, DroneManager
from src.gpt5_agent import GPT5MissionPlanner, MissionContextBuilder
from src.mission_executor import MissionExecutor, MultiMissionCoordinator
from src.telemetry_monitor import TelemetryMonitor, MultiDroneTelemetryAggregator
from src.utils.validators import Waypoint, GPSCoordinate
from src.chat_cli import start_chat_interface


class LLMDroneController:
    """Main controller class orchestrating all components"""

    def __init__(self):
        self.config = Config()
        self.logger = self._setup_logging()

        # Core components
        self.drone_manager: Optional[MultiDroneManager] = None
        self.mission_planner: Optional[GPT5MissionPlanner] = None
        self.mission_coordinator: Optional[MultiMissionCoordinator] = None
        self.telemetry_aggregator: Optional[MultiDroneTelemetryAggregator] = None

        # Component dictionaries
        self.executors: Dict[str, MissionExecutor] = {}
        self.monitors: Dict[str, TelemetryMonitor] = {}

        # State
        self.running = False
        self.connected_drones: List[str] = []

    def _setup_logging(self) -> logging.Logger:
        """Configure logging for the application"""
        logging.basicConfig(
            level=getattr(logging, self.config.logging.level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(
                    self.config.logging.log_file_path,
                    mode='a'
                )
            ]
        )
        return logging.getLogger("LLMDroneController")

    async def initialize(self) -> bool:
        """Initialize all system components"""
        try:
            self.logger.info("Initializing LLM Drone Controller...")

            # Initialize mission planner
            self.mission_planner = GPT5MissionPlanner(self.config)

            # Test OpenAI connection
            if not await self._test_openai_connection():
                self.logger.error("OpenAI connection test failed - continuing without GPT-5")
                # Continue without GPT-5 for basic testing

            # Initialize drone manager
            self.drone_manager = MultiDroneManager(self.config)

            # Connect to available drones
            connected_count = await self._connect_drones()
            if connected_count == 0:
                self.logger.error("No drones connected - cannot proceed")
                return False

            self.logger.info(f"Connected to {connected_count} drones: {self.connected_drones}")

            # Initialize mission executors and telemetry monitors
            await self._initialize_executors_and_monitors()

            # Initialize coordinators
            self.mission_coordinator = MultiMissionCoordinator(self.executors)
            self.telemetry_aggregator = MultiDroneTelemetryAggregator(self.monitors)

            # Start telemetry monitoring
            await self.telemetry_aggregator.start_all_monitoring()

            self.logger.info("LLM Drone Controller initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize controller: {e}")
            return False

    async def _test_openai_connection(self) -> bool:
        """Test OpenAI API connection"""
        try:
            if not self.mission_planner:
                return False

            # Simple test call
            test_context = MissionContextBuilder.create_search_context(
                scenario="Test connection",
                center_lat=47.397971,
                center_lon=8.546164,
                radius_m=50,
                num_drones=1
            )

            # This should be a quick test, not a full mission generation
            response = await self.mission_planner.client.chat.completions.create(
                model="gpt-3.5-turbo",  # Use cheaper model for test
                messages=[{"role": "user", "content": "Say 'connection test successful'"}],
                max_tokens=10
            )

            return "successful" in response.choices[0].message.content.lower()

        except Exception as e:
            self.logger.warning(f"OpenAI connection test failed: {e}")
            return False

    async def _connect_drones(self) -> int:
        """Connect to all configured drones"""
        try:
            connected = await self.drone_manager.connect_all()
            self.connected_drones = list(connected.keys())
            return len(connected)

        except Exception as e:
            self.logger.error(f"Error connecting to drones: {e}")
            return 0

    async def _initialize_executors_and_monitors(self):
        """Initialize mission executors and telemetry monitors for connected drones"""
        for drone_id in self.connected_drones:
            drone_instance = self.drone_manager.get_drone(drone_id)
            if drone_instance:
                # Create mission executor
                executor = MissionExecutor(
                    drone_instance.drone,
                    drone_id,
                    self.config
                )
                self.executors[drone_id] = executor

                # Create telemetry monitor
                monitor = TelemetryMonitor(
                    drone_instance.drone,
                    drone_id,
                    self.config
                )
                self.monitors[drone_id] = monitor

    async def run_simple_test(self) -> bool:
        """Run a simple test mission to verify system integration"""
        try:
            self.logger.info("Running simple integration test...")

            if not self.connected_drones:
                self.logger.error("No drones available for testing")
                return False

            # Use first connected drone for test
            test_drone_id = self.connected_drones[0]

            # Create simple test waypoints around the search_rescue_enhanced world
            # Center coordinates from the world file: 47.397971N, 8.546164E
            test_waypoints = [
                Waypoint(
                    latitude=47.397971,
                    longitude=8.546164,
                    altitude=20.0,  # 20m altitude
                    speed_ms=5.0,
                    action="takeoff",
                    loiter_time_s=3.0
                ),
                Waypoint(
                    latitude=47.398000,  # Slight north
                    longitude=8.546164,
                    altitude=20.0,
                    speed_ms=3.0,
                    action="waypoint",
                    loiter_time_s=5.0
                ),
                Waypoint(
                    latitude=47.397971,  # Return to center
                    longitude=8.546200,  # Slight east
                    altitude=20.0,
                    speed_ms=3.0,
                    action="waypoint",
                    loiter_time_s=5.0
                ),
                Waypoint(
                    latitude=47.397971,  # Return to start
                    longitude=8.546164,
                    altitude=5.0,   # Lower altitude for landing approach
                    speed_ms=2.0,
                    action="land",
                    loiter_time_s=0.0
                )
            ]

            # Get executor for test drone
            executor = self.executors.get(test_drone_id)
            if not executor:
                self.logger.error(f"No executor found for drone {test_drone_id}")
                return False

            # Upload test mission
            self.logger.info(f"Uploading test mission to drone {test_drone_id}")
            upload_success = await executor.upload_mission(test_waypoints, "integration_test")

            if not upload_success:
                self.logger.error("Failed to upload test mission")
                return False

            self.logger.info("Test mission uploaded successfully")

            # For safety, we won't automatically start the mission
            # This allows the user to manually start it from QGroundControl or other interface
            self.logger.info("Test mission ready - use QGroundControl or call start_test_mission() to execute")

            return True

        except Exception as e:
            self.logger.error(f"Simple test failed: {e}")
            return False

    async def start_test_mission(self) -> bool:
        """Start the uploaded test mission"""
        try:
            if not self.connected_drones:
                return False

            test_drone_id = self.connected_drones[0]
            executor = self.executors.get(test_drone_id)

            if not executor:
                return False

            self.logger.info(f"Starting test mission on drone {test_drone_id}")
            success = await executor.start_mission()

            if success:
                self.logger.info("Test mission started successfully")
            else:
                self.logger.error("Failed to start test mission")

            return success

        except Exception as e:
            self.logger.error(f"Error starting test mission: {e}")
            return False

    async def generate_gpt5_mission(self, scenario: str, num_drones: int = 1) -> bool:
        """Generate and upload a mission using GPT-5"""
        try:
            if not self.mission_planner:
                self.logger.error("Mission planner not available")
                return False

            if num_drones > len(self.connected_drones):
                self.logger.error(f"Requested {num_drones} drones but only {len(self.connected_drones)} connected")
                return False

            self.logger.info(f"Generating GPT-5 mission for scenario: {scenario}")

            # Create mission context for search_rescue_enhanced world
            context = MissionContextBuilder.create_search_context(
                scenario=scenario,
                center_lat=47.397971,  # Search rescue world center
                center_lon=8.546164,
                radius_m=self.config.search.search_radius_m,
                num_drones=num_drones
            )

            # Generate mission with GPT-5
            mission = await self.mission_planner.generate_search_mission(context)

            if not mission or not mission.drone_missions:
                self.logger.error("GPT-5 failed to generate valid mission")
                return False

            self.logger.info(f"GPT-5 generated mission with {len(mission.drone_missions)} drone assignments")

            # Upload missions to drones
            for i, (drone_id, waypoints) in enumerate(mission.drone_missions.items()):
                if i >= len(self.connected_drones):
                    break

                actual_drone_id = self.connected_drones[i]
                executor = self.executors.get(actual_drone_id)

                if executor:
                    await executor.upload_mission(waypoints, f"gpt5_mission_{actual_drone_id}")
                    self.logger.info(f"Uploaded GPT-5 mission to {actual_drone_id}")

            return True

        except Exception as e:
            self.logger.error(f"Error generating GPT-5 mission: {e}")
            return False

    async def get_telemetry_summary(self) -> Dict:
        """Get current telemetry summary for all drones"""
        if self.telemetry_aggregator:
            return self.telemetry_aggregator.get_fleet_summary()
        return {"error": "Telemetry aggregator not available"}

    async def emergency_land_all(self) -> bool:
        """Emergency land all connected drones"""
        try:
            self.logger.warning("Emergency landing all drones")

            tasks = []
            for executor in self.executors.values():
                tasks.append(executor.emergency_land())

            results = await asyncio.gather(*tasks, return_exceptions=True)

            success_count = sum(1 for result in results if result is True)
            self.logger.info(f"Emergency landing initiated for {success_count}/{len(results)} drones")

            return success_count > 0

        except Exception as e:
            self.logger.error(f"Error during emergency landing: {e}")
            return False

    async def shutdown(self):
        """Graceful shutdown of all components"""
        try:
            self.logger.info("Shutting down LLM Drone Controller...")
            self.running = False

            # Stop telemetry monitoring
            if self.telemetry_aggregator:
                await self.telemetry_aggregator.stop_all_monitoring()

            # Clean up executors
            for executor in self.executors.values():
                await executor.cleanup()

            # Disconnect drones
            if self.drone_manager:
                await self.drone_manager.disconnect_all()

            self.logger.info("Shutdown complete")

        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")

    def run(self):
        """Main run method for the application"""
        try:
            # Set up signal handlers
            def signal_handler(signum, frame):
                self.logger.info(f"Received signal {signum}, shutting down...")
                self.running = False

            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

            # Run the async main loop
            asyncio.run(self._main_loop())

        except KeyboardInterrupt:
            self.logger.info("Interrupted by user")
        except Exception as e:
            self.logger.error(f"Fatal error in main loop: {e}")
            sys.exit(1)

    async def _main_loop(self):
        """Main async event loop"""
        try:
            # Initialize system
            if not await self.initialize():
                self.logger.error("Failed to initialize - exiting")
                return

            self.running = True

            # Run simple integration test
            await self.run_simple_test()

            self.logger.info("LLM Drone Controller is running...")
            self.logger.info("Available commands:")
            self.logger.info("  - Ctrl+C: Shutdown")
            self.logger.info("  - Check QGroundControl for drone status")
            self.logger.info("  - Test mission uploaded and ready for execution")

            # Keep running until shutdown
            while self.running:
                await asyncio.sleep(1.0)

                # Print periodic status
                if hasattr(self, '_last_status_time'):
                    if (datetime.now() - self._last_status_time).total_seconds() > 30:
                        await self._print_status()
                        self._last_status_time = datetime.now()
                else:
                    self._last_status_time = datetime.now()

        except Exception as e:
            self.logger.error(f"Error in main loop: {e}")
        finally:
            await self.shutdown()

    async def _print_status(self):
        """Print periodic status information"""
        try:
            summary = await self.get_telemetry_summary()
            self.logger.info(f"Status: {summary.get('active_drones', 0)} active drones, "
                           f"{summary.get('total_alerts', 0)} alerts")
        except Exception as e:
            self.logger.debug(f"Error printing status: {e}")


# Interactive testing functions for development
async def test_basic_connection():
    """Test basic drone connection without full initialization"""
    print("Testing basic drone connection...")
    config = Config()
    drone_manager = MultiDroneManager(config)

    try:
        successful, total = await drone_manager.connect_all()
        print(f"Connected to {successful}/{total} drones")

        # Get connected drones
        connected_drones = drone_manager.get_connected_drones()
        if connected_drones:
            first_drone = connected_drones[0]
            print(f"Testing telemetry for {first_drone.drone_id}...")

            # Get a few telemetry readings
            count = 0
            async for position in first_drone.drone.telemetry.position():
                print(f"Position: {position.latitude_deg:.6f}, {position.longitude_deg:.6f}, {position.relative_altitude_m:.1f}m")
                count += 1
                if count >= 3:
                    break

        await drone_manager.disconnect_all()
        return successful > 0

    except Exception as e:
        print(f"Connection test failed: {e}")
        return False


@click.group()
@click.option('--debug', is_flag=True, help='Enable debug logging')
def cli(debug):
    """LLM Drone Controller - GPT-5 powered autonomous drone missions."""
    if debug:
        logging.basicConfig(level=logging.DEBUG)


@cli.command()
def test():
    """Run basic connection test."""
    console = Console()
    console.print("[blue]🔧 Running basic connection test...[/blue]")
    result = asyncio.run(test_basic_connection())
    if result:
        console.print("[green]✅ Connection test passed[/green]")
    else:
        console.print("[red]❌ Connection test failed[/red]")
    sys.exit(0 if result else 1)


@cli.command()
def run():
    """Run the main drone controller application."""
    controller = LLMDroneController()
    controller.run()


@cli.command()
def chat():
    """Start interactive chat interface for drone control."""
    async def chat_main():
        console = Console()
        console.print("[blue]🚁 Initializing LLM Drone Controller...[/blue]")

        try:
            controller = LLMDroneController()

            # Initialize controller
            if not await controller.initialize():
                console.print("[red]❌ Failed to initialize controller[/red]")
                return 1

            # Start chat interface
            await start_chat_interface(controller)

            # Cleanup
            await controller.shutdown()
            return 0

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user[/yellow]")
            return 0
        except Exception as e:
            console.print(f"[red]❌ Fatal error: {e}[/red]")
            return 1

    result = asyncio.run(chat_main())
    sys.exit(result)


if __name__ == "__main__":
    cli()