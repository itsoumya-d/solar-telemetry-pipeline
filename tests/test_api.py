from fastapi.testclient import TestClient

from solarpipe.api import create_app


def test_api_site_ingest_analysis_and_reconcile():
    client = TestClient(create_app())
    site = client.post("/sites", json={"site_id": "SOLAR-1", "capacity_kw": "100", "inverter_ids": ["INV-1"]})
    assert site.status_code == 200

    ingest = client.post(
        "/ingest",
        json={
            "records": [
                {
                    "site_id": "SOLAR-1",
                    "inverter_id": "INV-1",
                    "timestamp": "2026-11-01T10:00:00Z",
                    "ac_kw": "50",
                    "energy_kwh": "4",
                    "irradiance": "800",
                    "temperature_c": "30",
                }
            ]
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["created"] == 1

    analysis = client.get("/sites/SOLAR-1/analysis/2026-11-01")
    assert analysis.status_code == 200
    assert analysis.json()["readings"] == 1

    reconcile = client.post(
        "/reconcile",
        json={"site_id": "SOLAR-1", "period_start": "2026-11-01", "period_end": "2026-11-01", "billed_kwh": "10"},
    )
    assert reconcile.status_code == 200
    assert reconcile.json()["discrepancies"][0]["kind"] == "billing_mismatch"


def test_api_rejects_bad_site():
    client = TestClient(create_app())
    response = client.get("/sites/UNKNOWN/analysis/2026-11-01")
    assert response.status_code == 404
