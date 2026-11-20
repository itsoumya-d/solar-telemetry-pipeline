from datetime import date, datetime, timezone
from decimal import Decimal

from solarpipe import AnomalyDetector, Reading, SiteConfig, SolarPipeline


def test_thermal_throttling_detection():
    detector = AnomalyDetector(thermal_threshold_c=Decimal("65.0"))
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)

    normal_reading = Reading(
        site_id="site-1",
        inverter_id="inv-1",
        at=now,
        ac_kw=Decimal("4.5"),
        dc_kw=Decimal("4.8"),
        energy_kwh=Decimal("12.0"),
        irradiance=Decimal("800.0"),
        temperature_c=Decimal("45.0"),
        status="ok",
    )
    assert detector.check_thermal_throttling(normal_reading) is None

    throttled_reading = Reading(
        site_id="site-1",
        inverter_id="inv-2",
        at=now,
        ac_kw=Decimal("2.5"),
        dc_kw=Decimal("5.0"),
        energy_kwh=Decimal("10.0"),
        irradiance=Decimal("850.0"),
        temperature_c=Decimal("72.5"),
        status="warning",
    )
    event = detector.check_thermal_throttling(throttled_reading)
    assert event is not None
    assert event.severity == "WARNING"
    assert event.kind == "thermal_throttling"
    assert event.metric_value == Decimal("72.5")
    assert "72.5°C" in event.message


def test_zero_generation_under_peak_sun():
    detector = AnomalyDetector(peak_sun_min_irradiance=Decimal("500.0"))
    now = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)

    tripped_reading = Reading(
        site_id="site-1",
        inverter_id="inv-3",
        at=now,
        ac_kw=Decimal("0.0"),
        dc_kw=Decimal("0.0"),
        energy_kwh=Decimal("5.0"),
        irradiance=Decimal("920.0"),
        temperature_c=Decimal("38.0"),
        status="fault",
    )
    event = detector.check_zero_generation_under_sun(tripped_reading)
    assert event is not None
    assert event.severity == "CRITICAL"
    assert event.kind == "zero_gen_peak_sun"
    assert "generating zero power" in event.message


def test_peer_inverter_drift_detection():
    detector = AnomalyDetector(drift_tolerance=Decimal("0.25"))
    now = datetime(2026, 11, 20, 11, 30, tzinfo=timezone.utc)

    # 3 inverters at same site: inv-1 and inv-2 healthy (~0.95 ratio), inv-3 degraded (0.50 ratio)
    readings = [
        Reading(
            site_id="site-grid-1",
            inverter_id="inv-A",
            at=now,
            ac_kw=Decimal("9.5"),
            dc_kw=Decimal("10.0"),
            energy_kwh=Decimal("20.0"),
            irradiance=Decimal("750.0"),
            temperature_c=Decimal("42.0"),
            status="ok",
        ),
        Reading(
            site_id="site-grid-1",
            inverter_id="inv-B",
            at=now,
            ac_kw=Decimal("9.4"),
            dc_kw=Decimal("10.0"),
            energy_kwh=Decimal("19.8"),
            irradiance=Decimal("750.0"),
            temperature_c=Decimal("41.5"),
            status="ok",
        ),
        Reading(
            site_id="site-grid-1",
            inverter_id="inv-C",
            at=now,
            ac_kw=Decimal("5.0"),
            dc_kw=Decimal("10.0"),
            energy_kwh=Decimal("12.0"),
            irradiance=Decimal("750.0"),
            temperature_c=Decimal("55.0"),
            status="ok",
        ),
    ]

    drifts = detector.check_peer_inverter_drift(readings)
    assert len(drifts) == 1
    assert drifts[0].inverter_id == "inv-C"
    assert drifts[0].kind == "peer_efficiency_drift"
    assert drifts[0].severity == "WARNING"


def test_pipeline_anomaly_integration():
    pipeline = SolarPipeline()
    pipeline.register_site(
        SiteConfig(
            site_id="site-nz-1",
            capacity_kw=Decimal("20.0"),
            inverter_ids=("inv-1", "inv-2"),
            interval_minutes=5,
        )
    )

    now = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
    raw_telemetry = [
        {
            "site_id": "site-nz-1",
            "inverter_id": "inv-1",
            "timestamp": now.isoformat(),
            "ac_kw": "0.0",
            "dc_kw": "0.0",
            "energy_kwh": "10.0",
            "irradiance": "650.0",
            "temperature_c": "30.0",
            "status": "fault",
        },
        {
            "site_id": "site-nz-1",
            "inverter_id": "inv-2",
            "timestamp": now.isoformat(),
            "ac_kw": "8.0",
            "dc_kw": "8.5",
            "energy_kwh": "25.0",
            "irradiance": "650.0",
            "temperature_c": "40.0",
            "status": "ok",
        },
    ]

    summary = pipeline.ingest(raw_telemetry)
    assert summary.created == 2

    anomalies = pipeline.detect_anomalies(site_id="site-nz-1", day=date(2026, 11, 20))
    assert len(anomalies) >= 1
    kinds = [a.kind for a in anomalies]
    assert "zero_gen_peak_sun" in kinds

    # Verify audit trail records anomalies
    audit_actions = [entry.action for entry in pipeline.audit]
    assert "anomaly_critical" in audit_actions


def test_dead_letter_replay_and_recovery():
    pipeline = SolarPipeline()
    pipeline.register_site(
        SiteConfig(
            site_id="site-nz-2",
            capacity_kw=Decimal("15.0"),
            inverter_ids=("inv-1",),
            interval_minutes=5,
        )
    )

    # Ingest bad record (missing required inverter_id)
    bad_record = {
        "site_id": "site-nz-2",
        "timestamp": "2026-11-20T10:00:00+00:00",
        "ac_kw": "5.0",
        "energy_kwh": "10.0",
    }
    summary = pipeline.ingest([bad_record])
    assert summary.rejected == 1
    assert len(pipeline.dead_letters) == 1

    # Fix and replay
    fixed_record = dict(bad_record)
    fixed_record["inverter_id"] = "inv-1"

    replay_summary = pipeline.replay_dead_letters([fixed_record])
    assert replay_summary.created == 1
    assert replay_summary.rejected == 0
