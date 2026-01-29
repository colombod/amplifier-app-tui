# Amplifier TUI

Terminal User Interface for Amplifier Runtime, built with [Textual](https://textual.textualize.io/) + [Rich](https://rich.readthedocs.io/).

## Features

- **Transport Agnostic**: Connect via subprocess (launch runtime) or HTTP (attach to server)
- **Event-Driven**: Real-time streaming of runtime events
- **Rich Interface**: Full TUI with layouts, busy indicators, and interactive controls

## Installation

```bash
# From source
pip install -e .

# With dev dependencies
pip install -e ".[dev]"
```

## Usage

```bash
# Launch runtime as subprocess (default)
amplifier-tui

# Attach to existing server
amplifier-tui --attach --server http://localhost:4096

# Custom runtime command
amplifier-tui --command "python -m amplifier_runtime"
```

## Architecture

```
amplifier-app-tui/
├── src/amplifier_app_tui/
│   ├── core/           # Transport-agnostic core
│   │   ├── runtime_manager.py  # Manages runtime connection
│   │   └── event_bridge.py     # Routes events to UI
│   ├── ui/             # Textual UI components
│   │   └── app.py      # Main application
│   ├── widgets/        # Custom Textual widgets
│   └── cli.py          # CLI entry point
└── tests/
```

### Connection Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `subprocess` | Launch runtime as child process | Local development, single-user |
| `attach` | Connect to HTTP server | Shared server, remote runtime |
| `mock` | Mock transport for testing | Unit tests, development |

### SDK Integration

The TUI uses the `amplifier-app-runtime` SDK with the transport abstraction:

```python
from amplifier_app_runtime.sdk import (
    TransportAmplifierClient,
    create_subprocess_client,
    create_attach_client,
)

# Subprocess mode
async with create_subprocess_client() as client:
    sessions = await client.session.list()

# Attach mode
async with create_attach_client("http://localhost:4096") as client:
    async for event in client.session.prompt(session_id, parts):
        print(event)
```

## Development

```bash
# Run tests
pytest

# Type checking
pyright src/

# Linting
ruff check src/
```

## License

MIT
