# ClawCam

**ClawCam** is a robust wildlife monitoring platform that combines resilient camera-trap hardware, a local field gateway, and an edge AI operations layer.

## Current Progress
> **Current Status**: In progress; [view roadmap](docs/ROADMAP.md) and [detailed status](docs/STATUS.md).

## Getting Started
### Requirements:
1. Python installed with FastAPI.
2. SQLite3 for database; Python scripts assume SQLite persistence.

### Steps to Launch Gateway:
```bash
cd gateway
python -m clawcam_gateway.main
```

### Workflows:
- **Simulator**: Generate event payloads without node hardware:
   ```bash
   python -m clawcam_gateway.simulator.cli
   ```

For full guidance, refer to:
- [Roadmap](docs/ROADMAP.md)
- [Status](docs/STATUS.md)