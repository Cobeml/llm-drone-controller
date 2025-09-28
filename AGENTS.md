# Repository Guidelines

## Project Structure & Module Organization
- `main.py` orchestrates multi-drone missions, hooking planner, executor, and telemetry layers.
- `src/` hosts mission logic: `gpt5_agent.py` (planning prompts and parsing), `mission_executor.py` for task queueing, `drone_manager.py` bridging MAVSDK, `telemetry_monitor.py` for health checks, plus `utils/` for config loaders and validation.
- `config/` holds YAML defaults and mission presets; copy templates before editing and keep secrets in a local `.env`.
- `tests/` mirrors `src/` modules with pytest suites; add new `test_<feature>.py` files next to the module under test.
- Simulation assets live in `world/`; FastAPI UI components live in `web/` (keep heavy binaries out of Git).

## Build, Test, and Development Commands
- `python -m venv venv && source venv/bin/activate` creates an isolated environment.
- `pip install -r requirements.txt` pulls runtime, tooling, and test dependencies.
- `python main.py` launches the controller against PX4/Gazebo; ensure the simulator is publishing on UDP 14540.
- `pytest` runs unit and integration tests; `pytest --cov=src` adds coverage reporting.
- `uvicorn src.web_interface:app --reload --port 8080` serves the control panel for local UI checks.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation, descriptive docstrings, and type hints on public APIs; favor dataclasses for structured payloads.
- Run `black src tests` and `isort src tests` before committing to keep imports and spacing consistent.
- Lint with `flake8` and type-check with `mypy src`; resolve warnings instead of ignoring them.
- Use snake_case for functions and variables, CamelCase for classes, and prefix async coroutines with verbs (`start_telemetry_loop`).

## Testing Guidelines
- Use `pytest` with `pytest-asyncio`; decorate async tests with `@pytest.mark.asyncio`.
- Share fixtures via `tests/conftest.py`, especially for PX4 endpoints or temporary config overrides.
- Maintain ≥80% coverage and add regression tests when touching mission parsing, telemetry validation, or config serializers.
- Before hardware-in-loop runs, confirm the sim with `netstat -an | grep 14540` and review `TESTING_GUIDE.md`.

## Commit & Pull Request Guidelines
- Write short, imperative commit subjects (e.g., `Add MAVSDK reconnection watchdog`), adding behavioral details in the body when needed.
- Scope each PR to one topic; provide a summary, `pytest` output or sim logs, and call out config or schema changes.
- Link issues, request reviewers familiar with MAVSDK or GPT planning, and attach UI captures or telemetry snippets when operator flows change.
