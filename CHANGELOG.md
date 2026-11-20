# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-11-20

### Added
- Automated service smoke test (`scripts/smoke.sh`) running against live API in CI.
- Type checking with mypy and linting with ruff in CI pipeline.
- Production package build artifact verification step (`python -m build`).
- Dependency vulnerability auditing via `pip-audit`.
- Secret scanning via Gitleaks action.
- Operational runbook (`docs/runbook.md`) documenting health checks, SLOs, and rollback procedures.
- Dependabot configuration for automated dependency updates.
- Failure mode test suite (`tests/test_failure_modes.py`) covering negative capacity, malformed inputs, and 404 responses.
- Load testing verification with p95 latency target SLO < 45ms.

## [0.1.0] - 2026-11-20

### Added
- Core telemetry ingestion, validation, and deduplication engine.
- Sliding-window anomaly detection for thermal throttling and inverter drift.
- End-of-period billing reconciliation with configurable tolerance.
- FastAPI REST endpoints for registration, ingestion, and analysis.
