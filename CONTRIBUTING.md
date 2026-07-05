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

Install the gateway package editable with dev extras — exactly what CI does
(`.github/workflows`), so your environment can't drift from the gate:

```bash
python -m pip install -e "gateway/[dev,mqtt]"
```

Run the full gated suite from the **repo root** — `pytest.ini` supplies the
test paths and puts `gateway/` and `brain/oh-ben-claw-adapter/` on the import
path, so no environment variables are needed:

```bash
pytest
```

Equivalent CI-style invocation from `gateway/` (uses the `testpaths` in
`gateway/pyproject.toml`, the same five suites), as shown in the README:

```bash
cd gateway && PYTHONPATH=$PWD:$PWD/../brain/oh-ben-claw-adapter pytest
```

All runtime deps (including `python-multipart`, required at app-construction
time, and `croniter` for the scheduler) come from the package metadata in
`gateway/pyproject.toml` — never hand-install a dep list. The adapter path
makes `tests/gateway/test_tool_catalog_ssot.py` run instead of skipping.
Optional model runtimes are extras: `pip install -e "gateway/[vision]"`
(MegaDetector), `[ocr]`, `[faces]`, `[audio]`, `[cloud]`.

## Pull Request Checklist

| Check | Required |
|---|---|
| Status docs updated when feature maturity changes | Yes |
| Tests added or updated | Yes |
| No secrets committed | Yes |
| Hardware claims backed by tested board notes | Yes |
| Large binaries avoided unless explicitly approved | Yes |

## Pre-commit hooks

This repo ships a `.pre-commit-config.yaml` that mirrors CI: Ruff lint plus
LF-line-ending and whitespace fixers (paired with `.gitattributes` to keep the
tree LF-only). Enable it once after cloning:

```
pip install pre-commit
pre-commit install
```

Run against the whole tree at any time with `pre-commit run --all-files`.
