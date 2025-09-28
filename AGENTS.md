# Repository Guidelines

## Project Structure & Module Organization
- `main.py` orchestrates multi-drone missions and ties the planner, executor, and telemetry layers together.
- `src/` hosts core modules: `gpt5_agent.py` for mission planning, `drone_manager.py` for MAVSDK control, `mission_executor.py`, `telemetry_monitor.py`, and the `utils/` package for config, validation, and shared helpers.
- `config/` stores YAML templates for drone defaults and mission presets; update these before flights instead of hard-coding values.
- `tests/` contains pytest suites covering the GPT-5 planner and drone manager; mirror this layout for new features.
- `world/` and `web/` reserve assets for Gazebo scenarios and the FastAPI UI respectively; keep large binaries out of Git.

## Build, Test, and Development Commands
- `python -m venv venv && source venv/bin/activate` to isolate dependencies.
- `pip install -r requirements.txt` installs runtime, testing, and tooling packages.
- `python main.py` starts the controller against a running PX4/Gazebo stack.
- `pytest` executes the existing unit/integration tests; `pytest --cov=src` reports coverage.
- `uvicorn src.web_interface:app --reload --port 8080` serves the FastAPI control panel once endpoints are ready.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation, descriptive docstrings, and pervasive type hints; reuse dataclasses for structured payloads.
- Format before committing: `black src tests` and `isort src tests` keep imports and spacing consistent.
- Enforce linting and types with `flake8` and `mypy src`; resolve warnings rather than suppressing them.
- Use snake_case for functions and module-level helpers, CamelCase for classes, and prefix async tasks with verbs (`start_telemetry_loop`).

## Testing Guidelines
- Use pytest + `pytest-asyncio`; mark coroutine tests with `@pytest.mark.asyncio` and favor fixtures for PX4 endpoints.
- Keep coverage above 80%; add regression tests when touching mission parsing, telemetry validation, or config loaders.
- Confirm the PX4 sim is active (`netstat -an | grep 14540`) before running hardware-in-loop suites described in `TESTING_GUIDE.md`.
- Name new files `test_<feature>.py` and group shared fixtures under `tests/conftest.py` if they grow beyond a single module.

## Commit & Pull Request Guidelines
- Write short, imperative commits (see `git log`: `codex oneshot GPT-5 agent control for integration`); describe behavioral impact in the body when needed.
- One topic per PR; include a summary, validation evidence (`pytest` output or sim logs), and note config migrations or deployment steps.
- Link issues, tag reviewers familiar with MAVSDK or GPT-5 changes, and attach UI screenshots or telemetry snippets when altering operator-facing flows.
