from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from solarpipe.mapping import normalize_reading
from solarpipe.models import SiteConfig
from solarpipe.pipeline import SolarPipeline


def raw(**overrides):
    data = {
        "site": "SOLAR-1",
        "inverter": "INV-1",
        "timestamp": "2026-11-01T10:00:00Z",
        "ac_power_kw": "48.5",
        "dc_kw": "50.0",
        "energy_kwh": "4.04",
        "irradiance_wm2": "800",
        "temperature_c": "32",
        "status": "online",
    }
    data.update(overrides)
    return data


def pipeline_with_site():
    pipeline = SolarPipeline()
    pipeline.register_site(SiteConfig("SOLAR-1", Decimal("100"), ("INV-1", "INV-2"), 5))
    return pipeline


def test_normalize_aliases():
    reading = normalize_reading(raw())
    assert reading.site_id == "SOLAR-1"
    assert reading.inverter_id == "INV-1"
    assert reading.at == datetime(2026, 11, 1, 10, tzinfo=timezone.utc)
    assert reading.ac_kw == Decimal("48.500")
    assert reading.irradiance == Decimal("800.000")


def test_rejects_negative_and_impossible_values():
    with pytest.raises(ValueError, match="below minimum"):
        normalize_reading(raw(ac_power_kw="-1"))
    assert "irradiance exceeds" in pipeline_with_site().ingest([raw(irradiance_wm2="2000")]).dead_letters[0].errors[0]
    assert "exceeds site capacity" in pipeline_with_site().ingest([raw(ac_power_kw="150")]).dead_letters[0].errors[0]
    assert "not registered" in pipeline_with_site().ingest([raw(inverter="INV-9")]).dead_letters[0].errors[0]


def test_ingest_is_idempotent():
    pipeline = pipeline_with_site()
    first = pipeline.ingest([raw()])
    assert first.created == 1
    same = pipeline.ingest([raw()])
    assert same.unchanged == 1
    changed = pipeline.ingest([raw(ac_power_kw="49.0")])
    assert changed.rejected == 1
    assert "duplicate reading" in changed.dead_letters[0].errors[0]


def test_analyze_reports_actual_expected_and_gaps():
    pipeline = pipeline_with_site()
    records = [raw(timestamp=f"2026-11-01T10:0{i}:00Z", energy_kwh="4.0") for i in range(3)]
    pipeline.ingest(records)
    result = pipeline.analyze("SOLAR-1", date(2026, 11, 1))
    assert result.readings == 3
    assert result.actual_kwh == Decimal("12.000")
    assert result.expected_kwh > 0
    assert result.gap_count == 0
    assert result.stale_inverters == ("INV-2",)


def test_analyze_detects_underperformance():
    pipeline = pipeline_with_site()
    pipeline.ingest([raw(ac_power_kw="10", irradiance_wm2="900", energy_kwh="1")])
    result = pipeline.analyze("SOLAR-1", date(2026, 11, 1))
    assert result.underperforming_intervals == 1


def test_analyze_returns_empty_for_no_data():
    result = pipeline_with_site().analyze("SOLAR-1", date(2026, 11, 2))
    assert result.readings == 0
    assert result.actual_kwh == Decimal("0")


def test_reconcile_billing_matches_and_flags_mismatch():
    pipeline = pipeline_with_site()
    pipeline.ingest([raw(energy_kwh="100")])
    assert pipeline.reconcile_billing("SOLAR-1", date(2026, 11, 1), date(2026, 11, 1), "100.5") == []
    mismatch = pipeline.reconcile_billing("SOLAR-1", date(2026, 11, 1), date(2026, 11, 1), "120")
    assert mismatch[0].kind == "billing_mismatch"
    missing = pipeline.reconcile_billing("SOLAR-1", date(2026, 11, 2), date(2026, 11, 2), "10")
    assert missing[0].kind == "missing_telemetry"


def test_unregistered_site_analysis_raises():
    with pytest.raises(ValueError, match="not registered"):
        SolarPipeline().analyze("UNKNOWN", date(2026, 11, 1))
