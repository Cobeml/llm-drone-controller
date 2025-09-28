#!/usr/bin/env python3
"""
Demo script to showcase the CLI chat interface for LLM Drone Controller.

This demonstrates how to use the chat interface for drone control.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

def main():
    console = Console()

    # Welcome message
    welcome_text = Text.from_markup("""
[bold blue]🚁 LLM Drone Controller - CLI Chat Interface Demo[/bold blue]

[green]✅ Interactive chat interface for drone control[/green]
[green]✅ GPT-5 powered mission planning with robust fallback[/green]
[green]✅ Real-time telemetry and status monitoring[/green]
[green]✅ Conversational mission refinement[/green]

[yellow]📖 How to use:[/yellow]

1. Start the chat interface:
   [cyan]python main.py chat[/cyan]

2. Chat with the AI to plan missions:
   [italic]"Search the residential area for missing hikers"[/italic]
   [italic]"Find lost children in the town center"[/italic]
   [italic]"Survey the area for thermal anomalies"[/italic]

3. Use commands for advanced features:
   [cyan]/help[/cyan]      - Show all available commands
   [cyan]/status[/cyan]    - Check drone status and position
   [cyan]/telemetry[/cyan] - Live telemetry display
   [cyan]/emergency[/cyan] - Emergency land all drones
   [cyan]/history[/cyan]   - View conversation history

[yellow]🔧 Prerequisites:[/yellow]
• PX4 simulation running: [cyan]PX4_GZ_WORLD=search_rescue_enhanced make px4_sitl gz_x500[/cyan]
• OpenAI API key configured in [cyan].env.local[/cyan]
• All dependencies installed: [cyan]pip install -r requirements.txt[/cyan]

[yellow]🎯 Features:[/yellow]
• Natural language mission requests
• Interactive mission refinement
• Real-time drone monitoring
• Beautiful terminal interface with Rich
• Robust fallback when GPT-5 is unavailable
• Mission preview and waypoint display
• Emergency controls and safety features
""")

    console.print(Panel(welcome_text, title="[bold]Demo Guide[/bold]", border_style="blue"))

    console.print("\n[bold green]Ready to start chatting with your drones! 🚁✨[/bold green]")
    console.print("Run: [cyan]python main.py chat[/cyan] to begin")

if __name__ == "__main__":
    main()