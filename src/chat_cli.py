"""Interactive CLI chat interface for LLM Drone Controller."""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional, Dict, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.layout import Layout
from rich.live import Live
from rich import box

from .gpt5_agent import GPT5MissionPlanner, MissionContextBuilder, GeneratedMission
from .utils.config import get_config


class DroneControllerChatCLI:
    """Interactive CLI chat interface for drone control."""

    def __init__(self, controller):
        """Initialize chat CLI with drone controller."""
        self.controller = controller
        self.config = get_config()
        self.console = Console()
        self.mission_planner = GPT5MissionPlanner(self.config)
        self.logger = logging.getLogger("chat_cli")

        # State tracking
        self.running = False
        self.current_mission = None
        self.chat_history = []

        # Commands
        self.commands = {
            "/help": self._show_help,
            "/status": self._show_status,
            "/mission": self._plan_mission,
            "/execute": self._execute_mission,
            "/emergency": self._emergency_land,
            "/telemetry": self._show_telemetry,
            "/history": self._show_history,
            "/clear": self._clear_screen,
            "/quit": self._quit
        }

    async def start(self):
        """Start the interactive chat interface."""
        self.running = True

        # Setup signal handling
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Welcome message
        self._show_welcome()

        # Chat loop
        await self._chat_loop()

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.console.print("\n[yellow]📡 Received shutdown signal...[/yellow]")
        self.running = False

    def _show_welcome(self):
        """Display welcome message and status."""
        self.console.clear()

        welcome_panel = Panel.fit(
            "[bold blue]🚁 LLM Drone Controller - Chat Interface[/bold blue]\n\n"
            "[green]✅ Connected to GPT-5 Mission Planner[/green]\n"
            f"[green]✅ Connected to {len(self.controller.connected_drones)} drone(s)[/green]\n\n"
            "[dim]Type a mission description or use commands (type /help for help)[/dim]",
            title="[bold]Drone Control Chat[/bold]",
            border_style="blue"
        )

        self.console.print(welcome_panel)
        self.console.print()

    async def _chat_loop(self):
        """Main chat interaction loop."""
        while self.running:
            try:
                # Get user input
                user_input = Prompt.ask(
                    "[bold cyan]>[/bold cyan]",
                    default=""
                ).strip()

                if not user_input:
                    continue

                # Add to history
                self._add_to_history("user", user_input)

                # Process input
                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                else:
                    await self._handle_mission_request(user_input)

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Use /quit to exit properly[/yellow]")
            except Exception as e:
                self.console.print(f"[red]❌ Error: {e}[/red]")
                self.logger.error(f"Chat loop error: {e}")

    async def _handle_command(self, command_text: str):
        """Handle CLI commands."""
        parts = command_text.split(" ", 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command in self.commands:
            await self.commands[command](args)
        else:
            self.console.print(f"[red]❌ Unknown command: {command}[/red]")
            self.console.print("[dim]Type /help for available commands[/dim]")

    async def _handle_mission_request(self, description: str):
        """Handle natural language mission requests."""
        self.console.print(f"[blue]🤖 GPT-5 Agent:[/blue] Analyzing mission request: [italic]{description}[/italic]")

        # Show available drones
        num_drones = len(self.controller.connected_drones)
        self.console.print(f"[green]📊 Available drones: {num_drones}[/green]")

        # Show loading spinner
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True
        ) as progress:
            task = progress.add_task("Generating mission plan...", total=None)

            try:
                # Create mission context
                context = MissionContextBuilder.create_search_context(
                    scenario=description,
                    center_lat=self.config.search.center_lat,
                    center_lon=self.config.search.center_lon,
                    radius_m=self.config.search.radius_m,
                    num_drones=min(num_drones, 3),
                    weather="Clear skies",
                    wind_speed=5.0,
                    time_of_day="Daytime"
                )

                progress.update(task, description="Calling GPT-5 mission planner...")

                # Generate mission
                mission = await self.mission_planner.generate_search_mission(context)
                self.current_mission = mission

                progress.update(task, description="Mission generated!")

            except Exception as e:
                self.console.print(f"[red]❌ Mission generation failed: {e}[/red]")
                self.console.print("[yellow]💡 The system will use fallback mission generation[/yellow]")
                return

        # Display mission details
        self._display_mission(mission)
        self._add_to_history("assistant", f"Generated mission: {mission.strategy_summary}")

        # Interactive mission options
        await self._mission_interaction_menu()

    def _display_mission(self, mission: GeneratedMission):
        """Display mission details in a formatted way."""
        # Mission overview
        overview_table = Table(title="Mission Overview", box=box.ROUNDED)
        overview_table.add_column("Property", style="cyan")
        overview_table.add_column("Value", style="white")

        overview_table.add_row("Strategy", mission.strategy_summary)
        overview_table.add_row("Duration", f"{mission.estimated_duration:.1f} minutes")
        overview_table.add_row("Success Probability", f"{mission.success_probability:.0%}")
        overview_table.add_row("Risk Assessment", mission.risk_assessment)
        overview_table.add_row("Generated", mission.generated_at.strftime("%H:%M:%S"))

        self.console.print(overview_table)

        # Drone assignments
        if mission.drone_missions:
            drone_table = Table(title="Drone Assignments", box=box.ROUNDED)
            drone_table.add_column("Drone", style="green")
            drone_table.add_column("Waypoints", style="yellow")
            drone_table.add_column("First Location", style="blue")

            for i, waypoints in enumerate(mission.drone_missions, 1):
                if waypoints:
                    first_wp = waypoints[0]
                    location = f"{first_wp.coordinate.latitude:.6f}, {first_wp.coordinate.longitude:.6f}"
                    altitude = f"{first_wp.coordinate.altitude:.1f}m"
                    drone_table.add_row(
                        f"Drone {i}",
                        str(len(waypoints)),
                        f"{location} @ {altitude}"
                    )

            self.console.print(drone_table)

        # Additional details
        details_panel = Panel(
            f"[bold]Reasoning:[/bold]\n{mission.reasoning}\n\n"
            f"[bold]Coordination:[/bold]\n{mission.coordination_notes}\n\n"
            f"[bold]Contingency:[/bold]\n{mission.contingency_plans}",
            title="Mission Details",
            border_style="green"
        )
        self.console.print(details_panel)

    async def _mission_interaction_menu(self):
        """Interactive menu for mission options."""
        while True:
            self.console.print("\n[bold cyan]Mission Options:[/bold cyan]")
            self.console.print("1. 🚀 Execute mission")
            self.console.print("2. 📝 Modify mission request")
            self.console.print("3. 📊 Preview waypoints")
            self.console.print("4. ❌ Cancel mission")

            choice = Prompt.ask("Choose an option", choices=["1", "2", "3", "4"], default="1")

            if choice == "1":
                await self._execute_current_mission()
                break
            elif choice == "2":
                feedback = Prompt.ask("What modifications would you like?")
                await self._refine_mission(feedback)
            elif choice == "3":
                self._show_detailed_waypoints()
            elif choice == "4":
                self.console.print("[yellow]Mission cancelled[/yellow]")
                self.current_mission = None
                break

    async def _refine_mission(self, feedback: str):
        """Refine the current mission based on user feedback."""
        if not self.current_mission:
            self.console.print("[red]❌ No mission to refine[/red]")
            return

        self.console.print("[blue]🔄 Refining mission based on your feedback...[/blue]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True
        ) as progress:
            task = progress.add_task("Refining mission...", total=None)

            try:
                refined_mission = await self.mission_planner.refine_mission(
                    self.current_mission,
                    feedback
                )
                self.current_mission = refined_mission

                progress.update(task, description="Mission refined!")

            except Exception as e:
                self.console.print(f"[red]❌ Mission refinement failed: {e}[/red]")
                return

        self.console.print("[green]✨ Mission refined successfully![/green]")
        self._display_mission(self.current_mission)
        self._add_to_history("assistant", f"Refined mission: {feedback}")

    def _show_detailed_waypoints(self):
        """Show detailed waypoint information."""
        if not self.current_mission or not self.current_mission.drone_missions:
            self.console.print("[red]❌ No mission waypoints to display[/red]")
            return

        for i, waypoints in enumerate(self.current_mission.drone_missions, 1):
            waypoint_table = Table(title=f"Drone {i} Waypoints", box=box.ROUNDED)
            waypoint_table.add_column("#", style="cyan")
            waypoint_table.add_column("Latitude", style="green")
            waypoint_table.add_column("Longitude", style="green")
            waypoint_table.add_column("Altitude", style="yellow")
            waypoint_table.add_column("Action", style="blue")
            waypoint_table.add_column("Speed", style="magenta")

            for j, wp in enumerate(waypoints, 1):
                waypoint_table.add_row(
                    str(j),
                    f"{wp.coordinate.latitude:.6f}",
                    f"{wp.coordinate.longitude:.6f}",
                    f"{wp.coordinate.altitude:.1f}m",
                    wp.action,
                    f"{wp.speed:.1f} m/s"
                )

            self.console.print(waypoint_table)

    async def _execute_current_mission(self):
        """Execute the current mission."""
        if not self.current_mission:
            self.console.print("[red]❌ No mission to execute[/red]")
            return

        self.console.print("[green]🚀 Starting mission execution...[/green]")

        try:
            # Upload missions to drones
            for i, waypoints in enumerate(self.current_mission.drone_missions):
                if i >= len(self.controller.connected_drones):
                    break

                drone_id = self.controller.connected_drones[i]
                executor = self.controller.executors.get(drone_id)

                if executor:
                    success = await executor.upload_mission(waypoints, f"chat_mission_{drone_id}")
                    if success:
                        self.console.print(f"[green]✅ Mission uploaded to {drone_id}[/green]")
                    else:
                        self.console.print(f"[red]❌ Failed to upload mission to {drone_id}[/red]")

            self.console.print("[yellow]📡 Missions uploaded. Use /status to monitor progress[/yellow]")
            self._add_to_history("system", "Mission execution started")

        except Exception as e:
            self.console.print(f"[red]❌ Mission execution failed: {e}[/red]")

    async def _show_help(self, args: str = ""):
        """Show available commands."""
        help_table = Table(title="Available Commands", box=box.ROUNDED)
        help_table.add_column("Command", style="cyan")
        help_table.add_column("Description", style="white")

        help_table.add_row("/help", "Show this help message")
        help_table.add_row("/status", "Show drone status and mission progress")
        help_table.add_row("/mission <description>", "Plan a mission with specific description")
        help_table.add_row("/execute", "Execute the current mission")
        help_table.add_row("/emergency", "Emergency land all drones")
        help_table.add_row("/telemetry", "Show detailed telemetry data")
        help_table.add_row("/history", "Show conversation history")
        help_table.add_row("/clear", "Clear the screen")
        help_table.add_row("/quit", "Exit the chat interface")

        self.console.print(help_table)

        self.console.print("\n[dim]You can also type natural language mission requests directly![/dim]")

    async def _show_status(self, args: str = ""):
        """Show current drone status."""
        if not self.controller.telemetry_aggregator:
            self.console.print("[red]❌ Telemetry not available[/red]")
            return

        try:
            summary = await self.controller.get_telemetry_summary()

            status_table = Table(title="Fleet Status", box=box.ROUNDED)
            status_table.add_column("Drone", style="green")
            status_table.add_column("Status", style="yellow")
            status_table.add_column("Position", style="blue")
            status_table.add_column("Altitude", style="cyan")

            for drone_id in self.controller.connected_drones:
                monitor = self.controller.monitors.get(drone_id)
                if monitor:
                    telemetry = monitor.get_latest_telemetry()
                    if telemetry:
                        status = "🟢 In Air" if telemetry.get("in_air") else "🔴 Landed"
                        pos = telemetry.get("position", {})
                        lat = pos.get("latitude", 0)
                        lon = pos.get("longitude", 0)
                        alt = pos.get("altitude", 0)

                        status_table.add_row(
                            drone_id,
                            status,
                            f"{lat:.6f}, {lon:.6f}",
                            f"{alt:.1f}m"
                        )
                    else:
                        status_table.add_row(drone_id, "🟡 No Data", "Unknown", "Unknown")

            self.console.print(status_table)

        except Exception as e:
            self.console.print(f"[red]❌ Failed to get status: {e}[/red]")

    async def _plan_mission(self, args: str):
        """Plan a mission with specific description."""
        if not args.strip():
            description = Prompt.ask("Enter mission description")
        else:
            description = args

        await self._handle_mission_request(description)

    async def _execute_mission(self, args: str = ""):
        """Execute the current mission."""
        await self._execute_current_mission()

    async def _emergency_land(self, args: str = ""):
        """Emergency land all drones."""
        if Confirm.ask("[bold red]⚠️ Emergency land all drones?[/bold red]"):
            self.console.print("[red]🚨 EMERGENCY LANDING INITIATED[/red]")

            try:
                success = await self.controller.emergency_land_all()
                if success:
                    self.console.print("[green]✅ Emergency landing command sent[/green]")
                else:
                    self.console.print("[red]❌ Emergency landing failed[/red]")

                self._add_to_history("system", "Emergency landing initiated")

            except Exception as e:
                self.console.print(f"[red]❌ Emergency landing error: {e}[/red]")

    async def _show_telemetry(self, args: str = ""):
        """Show detailed telemetry data with real-time updates."""
        self.console.print("[blue]📊 Real-time Telemetry Display[/blue]")
        self.console.print("[dim]Press Ctrl+C to stop monitoring[/dim]\n")

        try:
            while True:
                # Create telemetry layout
                layout = Layout()
                layout.split_column(
                    Layout(name="header", size=3),
                    Layout(name="main", ratio=1),
                    Layout(name="footer", size=2)
                )

                # Header
                header_text = Text(f"Live Telemetry - {datetime.now().strftime('%H:%M:%S')}", style="bold blue")
                layout["header"].update(Panel(header_text, title="Status"))

                # Main telemetry data
                telemetry_table = await self._create_telemetry_table()
                layout["main"].update(telemetry_table)

                # Footer
                footer_text = Text("Press Ctrl+C to return to chat", style="dim")
                layout["footer"].update(Panel(footer_text))

                # Display for 2 seconds, then update
                self.console.clear()
                self.console.print(layout)
                await asyncio.sleep(2)

        except KeyboardInterrupt:
            self.console.clear()
            self.console.print("[yellow]📊 Telemetry monitoring stopped[/yellow]")

    async def _create_telemetry_table(self):
        """Create detailed telemetry table."""
        telemetry_table = Table(title="Drone Fleet Telemetry", box=box.ROUNDED)
        telemetry_table.add_column("Drone ID", style="green")
        telemetry_table.add_column("Status", style="yellow")
        telemetry_table.add_column("Latitude", style="blue")
        telemetry_table.add_column("Longitude", style="blue")
        telemetry_table.add_column("Altitude", style="cyan")
        telemetry_table.add_column("Battery", style="magenta")
        telemetry_table.add_column("Speed", style="white")

        for drone_id in self.controller.connected_drones:
            monitor = self.controller.monitors.get(drone_id)
            if monitor:
                telemetry = monitor.get_latest_telemetry()
                if telemetry:
                    # Status indicators
                    armed_status = "🟢 ARMED" if telemetry.get("armed") else "🔴 DISARMED"
                    flight_status = "✈️ FLYING" if telemetry.get("in_air") else "🛬 LANDED"
                    status = f"{armed_status} | {flight_status}"

                    # Position data
                    pos = telemetry.get("position", {})
                    lat = pos.get("latitude", 0.0)
                    lon = pos.get("longitude", 0.0)
                    alt = pos.get("altitude", 0.0)

                    # Battery and speed
                    battery = telemetry.get("battery", {}).get("percentage", 0.0)
                    battery_str = f"{battery:.1f}%"
                    if battery < 25:
                        battery_str = f"[red]{battery_str}[/red]"
                    elif battery < 50:
                        battery_str = f"[yellow]{battery_str}[/yellow]"

                    velocity = telemetry.get("velocity", {})
                    speed = (velocity.get("north", 0)**2 + velocity.get("east", 0)**2)**0.5

                    telemetry_table.add_row(
                        drone_id,
                        status,
                        f"{lat:.6f}",
                        f"{lon:.6f}",
                        f"{alt:.1f}m",
                        battery_str,
                        f"{speed:.1f} m/s"
                    )
                else:
                    telemetry_table.add_row(
                        drone_id,
                        "❌ NO DATA",
                        "Unknown",
                        "Unknown",
                        "Unknown",
                        "Unknown",
                        "Unknown"
                    )

        return Panel(telemetry_table, title="Live Telemetry")

    async def _show_history(self, args: str = ""):
        """Show conversation history."""
        if not self.chat_history:
            self.console.print("[yellow]No conversation history yet[/yellow]")
            return

        history_panel = Panel(
            "\n".join([
                f"[{'cyan' if entry['type'] == 'user' else 'green' if entry['type'] == 'assistant' else 'yellow'}]"
                f"{entry['type'].capitalize()}: {entry['message']}[/]"
                for entry in self.chat_history[-10:]  # Show last 10 entries
            ]),
            title="Recent Conversation History",
            border_style="white"
        )
        self.console.print(history_panel)

    async def _clear_screen(self, args: str = ""):
        """Clear the screen."""
        self.console.clear()
        self._show_welcome()

    async def _quit(self, args: str = ""):
        """Exit the chat interface."""
        self.console.print("[yellow]👋 Goodbye![/yellow]")
        self.running = False

    def _add_to_history(self, entry_type: str, message: str):
        """Add entry to chat history."""
        self.chat_history.append({
            "type": entry_type,
            "message": message,
            "timestamp": datetime.now()
        })

        # Keep only last 50 entries
        if len(self.chat_history) > 50:
            self.chat_history = self.chat_history[-50:]


async def start_chat_interface(controller):
    """Start the chat interface with the given controller."""
    chat_cli = DroneControllerChatCLI(controller)
    await chat_cli.start()