from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .models import SiteConfig
from .pipeline import SolarPipeline


class SiteIn(BaseModel):
    site_id: str
    capacity_kw: str
    inverter_ids: list[str] = Field(default_factory=list)
    interval_minutes: int = 5


class IngestIn(BaseModel):
    records: list[dict[str, Any]]


class ReconcileIn(BaseModel):
    site_id: str
    period_start: date
    period_end: date
    billed_kwh: str


def _summary(summary) -> dict[str, Any]:
    return {
        "received": summary.received,
        "created": summary.created,
        "updated": summary.updated,
        "unchanged": summary.unchanged,
        "rejected": summary.rejected,
        "dead_letters": [letter.__dict__ for letter in summary.dead_letters],
        "audit": [entry.__dict__ | {"at": entry.at.isoformat()} for entry in summary.audit],
    }


def create_app(pipeline: SolarPipeline | None = None) -> FastAPI:
    state = pipeline or SolarPipeline()
    app = FastAPI(title="Solar telemetry pipeline", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/sites")
    def register_site(payload: SiteIn) -> dict[str, str]:
        try:
            state.register_site(
                SiteConfig(
                    site_id=payload.site_id,
                    capacity_kw=Decimal(payload.capacity_kw),
                    inverter_ids=tuple(payload.inverter_ids),
                    interval_minutes=payload.interval_minutes,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"site_id": payload.site_id, "status": "registered"}

    @app.post("/ingest")
    def ingest(payload: IngestIn) -> dict[str, Any]:
        return _summary(state.ingest(payload.records))

    @app.get("/sites/{site_id}/analysis/{day}")
    def analysis(site_id: str, day: date) -> dict[str, Any]:
        try:
            result = state.analyze(site_id, day)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "site_id": result.site_id,
            "day": result.day.isoformat(),
            "readings": result.readings,
            "actual_kwh": str(result.actual_kwh),
            "expected_kwh": str(result.expected_kwh),
            "performance_ratio": str(result.performance_ratio),
            "gap_count": result.gap_count,
            "underperforming_intervals": result.underperforming_intervals,
            "stale_inverters": list(result.stale_inverters),
        }

    @app.post("/reconcile")
    def reconcile(payload: ReconcileIn) -> dict[str, Any]:
        return {
            "discrepancies": [
                item.__dict__
                for item in state.reconcile_billing(
                    payload.site_id, payload.period_start, payload.period_end, payload.billed_kwh
                )
            ]
        }

    return app


app = create_app()
