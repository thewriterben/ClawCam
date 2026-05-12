# Contributing to ClawCam

ClawCam is being rebuilt as a transparent, testable wildlife monitoring platform. Contributions should improve the working system or clarify roadmap status.

## Contribution Principles

| Principle | Meaning |
|---|---|
| Be honest about status | Do not mark features as working unless they are implemented and testable. |
| Prefer vertical slices | Small end-to-end functionality is more valuable than large untested scaffolds. |
| Preserve field reliability | Deterministic capture, storage, and sleep behavior must not depend on LLM availability. |
| Add tests | Schemas, gateway behavior, and adapters should include tests. |
| Document hardware | New board support requires wiring, build configuration, and capture test notes. |

## Development Setup

```bash
cd gateway
python -m pip install fastapi uvicorn pydantic pytest jsonschema httpx
PYTHONPATH=gateway pytest -q ../tests/schemas ../tests/gateway
```

## Pull Request Checklist

| Check | Required |
|---|---|
| Status docs updated when feature maturity changes | Yes |
| Tests added or updated | Yes |
| No secrets committed | Yes |
| Hardware claims backed by tested board notes | Yes |
| Large binaries avoided unless explicitly approved | Yes |
