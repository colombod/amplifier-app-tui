"""Amplifier TUI CLI entry point.

Usage:
    amplifier-tui                          # Launch with default settings
    amplifier-tui init                     # Initialize configuration
    amplifier-tui run                      # Run with explicit settings
    amplifier-tui run --attach localhost:4096  # Attach to running server
    amplifier-tui run --mock               # Demo mode with mock data
"""

from __future__ import annotations

import os
from pathlib import Path

import click


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(version="0.1.0")
def main(ctx: click.Context) -> None:
    """Amplifier TUI - Terminal interface for AI agents.

    Run without arguments to start with default/configured settings.
    Use 'init' to configure, 'run' for explicit options.
    """
    if ctx.invoked_subcommand is None:
        # Default: run with configured settings
        _run_with_config()


# =============================================================================
# Init Command
# =============================================================================


@main.command("init")
@click.option("--bundle", "-b", default=None, help="Default bundle to use")
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["subprocess", "attach"]),
    default=None,
    help="Connection mode",
)
@click.option("--server-url", default=None, help="Server URL for attach mode")
@click.option("--runtime-command", default=None, help="Command to launch runtime")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing configuration")
@click.option("--yes", "-y", is_flag=True, help="Accept defaults without prompting")
def init_config(
    bundle: str | None,
    mode: str | None,
    server_url: str | None,
    runtime_command: str | None,
    force: bool,
    yes: bool,
) -> None:
    """Initialize the Amplifier TUI configuration.

    Creates configuration directory and settings file with connection preferences.

    Examples:

        # Interactive setup
        amplifier-tui init

        # Non-interactive with defaults
        amplifier-tui init --yes

        # Configure for attach mode
        amplifier-tui init --mode attach --server-url http://localhost:4096
    """
    import yaml

    config_dir = Path.home() / ".amplifier-tui"
    settings_file = config_dir / "settings.yaml"

    # Check if already initialized
    if settings_file.exists() and not force:
        click.echo(f"Configuration already exists at {settings_file}")
        click.echo("Use --force to overwrite existing configuration.")
        if not yes and not click.confirm("Continue anyway?"):
            return

    # Create config directory
    config_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"Configuration directory: {config_dir}")

    # Detect available providers (check environment)
    provider_checks = [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("azure-openai", "AZURE_OPENAI_API_KEY"),
        ("google", "GOOGLE_API_KEY"),
    ]

    available_providers = []
    for name, env_var in provider_checks:
        if os.getenv(env_var):
            available_providers.append(name)
            click.echo(f"  Found provider: {name} ({env_var} is set)")

    if not available_providers:
        click.echo("\n⚠️  No provider API keys found in environment.")
        click.echo("The runtime will need configured providers to work.")

    # Select connection mode
    selected_mode = mode
    if not selected_mode:
        if yes:
            selected_mode = "subprocess"
        else:
            selected_mode = click.prompt(
                "Connection mode",
                default="subprocess",
                type=click.Choice(["subprocess", "attach"]),
            )

    # Select bundle
    selected_bundle = bundle
    if not selected_bundle:
        if yes:
            selected_bundle = "foundation"
        else:
            selected_bundle = click.prompt("Default bundle", default="foundation")

    # Mode-specific configuration
    selected_server_url = server_url
    selected_runtime_command = runtime_command

    if selected_mode == "attach":
        if not selected_server_url:
            if yes:
                selected_server_url = "http://localhost:4096"
            else:
                selected_server_url = click.prompt("Server URL", default="http://localhost:4096")
    else:
        if not selected_runtime_command:
            if yes:
                selected_runtime_command = "amplifier-runtime"
            else:
                selected_runtime_command = click.prompt(
                    "Runtime command", default="amplifier-runtime"
                )

    # Create settings
    settings: dict = {
        "version": "1.0",
        "connection": {
            "mode": selected_mode,
        },
        "session": {
            "bundle": selected_bundle,
        },
    }

    if selected_mode == "attach":
        settings["connection"]["server_url"] = selected_server_url
    else:
        settings["connection"]["runtime_command"] = selected_runtime_command

    # Write settings file
    with open(settings_file, "w") as f:
        yaml.dump(settings, f, default_flow_style=False, sort_keys=False)

    click.echo(f"\n✓ Configuration saved to {settings_file}")
    click.echo(f"  Connection mode:  {selected_mode}")
    click.echo(f"  Default bundle:   {selected_bundle}")
    if selected_mode == "attach":
        click.echo(f"  Server URL:       {selected_server_url}")
    else:
        click.echo(f"  Runtime command:  {selected_runtime_command}")

    click.echo("\nTo start the TUI:")
    click.echo("  amplifier-tui           # Use configured settings")
    click.echo("  amplifier-tui run       # Same as above")
    click.echo("  amplifier-tui run --mock  # Demo mode without runtime")


# =============================================================================
# Run Command
# =============================================================================


@main.command("run")
@click.option(
    "--attach",
    "attach_url",
    default=None,
    help="Attach to running server (e.g., http://localhost:4096)",
)
@click.option(
    "--runtime-command",
    default=None,
    help="Command to launch runtime (default: amplifier-runtime)",
)
@click.option(
    "--working-dir",
    default=None,
    help="Working directory for runtime subprocess",
)
@click.option(
    "--bundle",
    "-b",
    default=None,
    help="Bundle to use (overrides config)",
)
@click.option(
    "--mock",
    is_flag=True,
    help="Run in demo mode with mock data (no runtime needed)",
)
def run_command(
    attach_url: str | None,
    runtime_command: str | None,
    working_dir: str | None,
    bundle: str | None,
    mock: bool,
) -> None:
    """Run the Amplifier TUI.

    By default, uses configured settings from 'amplifier-tui init'.
    Command-line options override configuration.

    Examples:

        # Use configured settings
        amplifier-tui run

        # Attach to running server
        amplifier-tui run --attach http://localhost:4096

        # Demo mode (no runtime needed)
        amplifier-tui run --mock
    """
    if mock:
        _run_mock()
    else:
        _run_with_options(attach_url, runtime_command, working_dir, bundle)


# =============================================================================
# Config Command
# =============================================================================


@main.command("config")
@click.option("--show", is_flag=True, help="Show current configuration")
def config_command(show: bool) -> None:
    """View or manage TUI configuration."""
    import yaml

    settings_file = Path.home() / ".amplifier-tui" / "settings.yaml"

    if not settings_file.exists():
        click.echo("No configuration found. Run 'amplifier-tui init' to create one.")
        return

    with open(settings_file) as f:
        settings = yaml.safe_load(f)

    click.echo(f"Configuration file: {settings_file}\n")
    click.echo(yaml.dump(settings, default_flow_style=False, sort_keys=False))


# =============================================================================
# Helper Functions
# =============================================================================


def _load_config() -> dict | None:
    """Load configuration from settings file."""
    import yaml

    settings_file = Path.home() / ".amplifier-tui" / "settings.yaml"
    if settings_file.exists():
        with open(settings_file) as f:
            return yaml.safe_load(f)
    return None


def _run_with_config() -> None:
    """Run TUI with configured settings."""
    config = _load_config()

    if config is None:
        # No config, use defaults
        _run_with_options(None, None, None, None)
        return

    connection = config.get("connection", {})
    session = config.get("session", {})

    mode = connection.get("mode", "subprocess")

    if mode == "attach":
        attach_url = connection.get("server_url", "http://localhost:4096")
        _run_with_options(attach_url, None, None, session.get("bundle"))
    else:
        runtime_cmd = connection.get("runtime_command", "amplifier-runtime")
        _run_with_options(None, runtime_cmd, None, session.get("bundle"))


def _run_with_options(
    attach_url: str | None,
    runtime_command: str | None,
    working_dir: str | None,
    bundle: str | None,
) -> None:
    """Run TUI with explicit options."""
    from .app import run

    run(
        attach_url=attach_url,
        runtime_command=[runtime_command] if runtime_command else None,
        working_directory=working_dir,
        bundle=bundle,
    )


def _run_mock() -> None:
    """Run TUI in mock/demo mode without real runtime."""
    import asyncio

    from .app import AmplifierTUI

    app = AmplifierTUI()

    async def demo_sequence():
        """Simulate a demo interaction."""
        await asyncio.sleep(1)

        # Simulate connection
        app.set_connected(True, "mock")
        app.set_session("mock-session-12345")
        app.add_system_message("Connected to mock runtime (demo mode)")

        await asyncio.sleep(0.5)

        # Simulate user message
        app.add_user_message("Hello! Can you help me with a code review?")

        await asyncio.sleep(0.5)

        # Simulate agent response
        app.start_response()
        app.set_agent_state("thinking")
        app.add_thinking("Analyzing the request...")

        await asyncio.sleep(1)
        app.end_thinking()

        app.set_agent_state("generating")
        for chunk in [
            "Of course! ",
            "I'd be happy to help ",
            "with a code review. ",
            "Please share the code ",
            "you'd like me to review.",
        ]:
            app.append_content(chunk)
            await asyncio.sleep(0.2)

        app.end_response()

        await asyncio.sleep(0.5)

        # Simulate tool call
        app.add_user_message("Review the file src/main.py")
        app.start_response()

        tool_id = app.add_tool_call(
            "read_file",
            {"path": "src/main.py"},
            status="pending",
        )

        await asyncio.sleep(1)

        app.update_tool_call(
            tool_id,
            "def main():\n    print('Hello, World!')\n\nif __name__ == '__main__':\n    main()",
            "success",
        )

        app.append_content(
            "\n\nI've reviewed `src/main.py`. It's a simple Python script that:\n"
            "1. Defines a `main()` function that prints 'Hello, World!'\n"
            "2. Uses the standard `if __name__ == '__main__'` guard\n\n"
            "The code looks clean! Would you like me to suggest any improvements?"
        )

        app.end_response()

        # Simulate todos
        app.update_todos(
            [
                {
                    "content": "Review src/main.py",
                    "status": "completed",
                    "activeForm": "Reviewing code",
                },
                {
                    "content": "Suggest improvements",
                    "status": "in_progress",
                    "activeForm": "Suggesting improvements",
                },
                {
                    "content": "Apply changes",
                    "status": "pending",
                    "activeForm": "Applying changes",
                },
            ]
        )

    async def run_with_demo():
        # Start demo sequence in background
        demo_task = asyncio.create_task(demo_sequence())
        try:
            await app.run_async()
        finally:
            demo_task.cancel()
            try:
                await demo_task
            except asyncio.CancelledError:
                pass

    asyncio.run(run_with_demo())


if __name__ == "__main__":
    main()
