# solar-telemetry-pipeline

[![ci](https://github.com/itsoumya-d/solar-telemetry-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/itsoumya-d/solar-telemetry-pipeline/actions/workflows/ci.yml)

A small, tested reference for solar-farm telemetry and billing reconciliation:

- Normalize inverter readings from solar-site field names.
- Validate timestamps, power, energy, irradiance, temperature, site capacity and
  registered inverters.
- Idempotent ingestion keyed by site, inverter and timestamp.
- Performance analysis: actual vs expected kWh, performance ratio, missing
  intervals, underperforming intervals and stale inverters.
- Billing reconciliation against metered kWh with a configurable tolerance.
- Dead-letter queue and audit entries for rejected or accepted readings.
- FastAPI endpoints and a pytest suite.

This is a **reference implementation**, not a claim of production solar-farm,
SCADA or energy-market experience. Live inverter, weather, market-pricing and
billing connectors are out of scope; the ingestion, validation, performance and
reconciliation core is tested.

## Run

```bash
uv venv --python 3.12
source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn solarpipe.api:app --reload
```

## License

MIT
