from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from solarpipe import SiteConfig, SolarPipeline
from solarpipe.api import create_app


def test_site_registration_negative_capacity_rejected():
    pipeline = SolarPipeline()
    app = create_app(pipeline)
    client = TestClient(app)

    # Negative capacity should fail validation
    resp = client.post("/sites", json={
        "site_id": "site-invalid",
        "capacity_kw": "-10.0",
        "inverter_ids": ["inv-1"],
        "interval_minutes": 5
    })
    assert resp.status_code == 422


def test_site_registration_zero_capacity_rejected():
    pipeline = SolarPipeline()
    app = create_app(pipeline)
    client = TestClient(app)

    resp = client.post("/sites", json={
        "site_id": "site-zero",
        "capacity_kw": "0.0",
        "inverter_ids": ["inv-1"],
        "interval_minutes": 5
    })
    assert resp.status_code == 422


def test_analysis_nonexistent_site_returns_404():
    pipeline = SolarPipeline()
    app = create_app(pipeline)
    client = TestClient(app)

    resp = client.get("/sites/non-existent-site-id/analysis/2026-11-20")
    assert resp.status_code == 404
    assert "not registered" in resp.json()["detail"].lower()


def test_ingest_corrupted_records_routed_to_dead_letters():
    pipeline = SolarPipeline()
    pipeline.register_site(
        SiteConfig(
            site_id="site-test-corrupt",
            capacity_kw=Decimal("50.0"),
            inverter_ids=("inv-1",),
            interval_minutes=5,
        )
    )
    app = create_app(pipeline)
    client = TestClient(app)

    # Missing mandatory timestamp or malformed energy values
    payload = {
        "records": [
            {"site_id": "site-test-corrupt", "inverter_id": "inv-1"},  # missing timestamp
            {"site_id": "site-test-corrupt", "inverter_id": "inv-1", "timestamp": "invalid-time", "energy_kwh": "abc"},
        ]
    }
    resp = client.post("/ingest", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["rejected"] > 0
    assert len(data["dead_letters"]) > 0
