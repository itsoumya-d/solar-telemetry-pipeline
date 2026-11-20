from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from .anomaly import AnomalyDetector
from .mapping import normalize_reading
from .models import (
    AnomalyEvent,
    AuditEntry,
    BillingDiscrepancy,
    DeadLetter,
    IngestSummary,
    Reading,
    SiteAnalysis,
    SiteConfig,
)


class SolarPipeline:
    def __init__(self) -> None:
        self.sites: dict[str, SiteConfig] = {}
        self.readings: dict[tuple[str, str, datetime], Reading] = {}
        self.dead_letters: list[DeadLetter] = []
        self.audit: list[AuditEntry] = []

    def register_site(self, config: SiteConfig) -> None:
        if config.capacity_kw <= 0:
            raise ValueError("capacity_kw must be positive")
        if config.interval_minutes <= 0:
            raise ValueError("interval_minutes must be positive")
        self.sites[config.site_id] = config
        self._record("site_registered", config.site_id, f"capacity_kw={config.capacity_kw}")

    def _record(self, action: str, reference: str, detail: str) -> None:
        self.audit.append(AuditEntry(datetime.now(UTC), action, reference, detail))

    def ingest(self, records: list[dict[str, Any]]) -> IngestSummary:
        summary = IngestSummary(received=len(records))
        for raw in records:
            reference = str(raw.get("site_id") or raw.get("site") or "") + "/" + str(
                raw.get("inverter_id") or raw.get("inverter") or ""
            )
            try:
                reading = normalize_reading(raw)
                self._validate(reading)
                key = (reading.site_id, reading.inverter_id, reading.at)
                existing = self.readings.get(key)
                if existing is None:
                    self.readings[key] = reading
                    summary.created += 1
                    action = "created"
                elif existing.fingerprint() != reading.fingerprint():
                    raise ValueError("duplicate reading with different values")
                else:
                    summary.unchanged += 1
                    action = "unchanged"
                self._record(action, f"{reading.site_id}/{reading.inverter_id}", reading.at.isoformat())
            except ValueError as exc:
                summary.rejected += 1
                letter = DeadLetter(uuid.uuid4().hex[:12], reference, dict(raw), [str(exc)])
                self.dead_letters.append(letter)
                summary.dead_letters.append(letter)
                self._record("rejected", reference, str(exc))
        summary.audit = list(self.audit)
        return summary

    def _validate(self, reading: Reading) -> None:
        if reading.irradiance > Decimal(1500):
            raise ValueError("irradiance exceeds physical maximum")
        if reading.temperature_c < Decimal(-50) or reading.temperature_c > Decimal(90):
            raise ValueError("temperature outside plausible range")
        config = self.sites.get(reading.site_id)
        if config and reading.ac_kw > config.capacity_kw * Decimal("1.2"):
            raise ValueError("ac_kw exceeds site capacity by more than 20%")
        if config and config.inverter_ids and reading.inverter_id not in config.inverter_ids:
            raise ValueError("inverter is not registered for this site")

    def analyze(self, site_id: str, day: date) -> SiteAnalysis:
        config = self.sites.get(site_id)
        if config is None:
            raise ValueError(f"site is not registered: {site_id}")
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)
        rows = sorted(
            (r for (s, _, at), r in self.readings.items() if s == site_id and start <= at < end),
            key=lambda r: r.at,
        )
        if not rows:
            return SiteAnalysis(site_id, day, 0, Decimal(0), Decimal(0), Decimal(0), 0, 0, ())

        actual = sum((r.energy_kwh for r in rows), Decimal(0))
        interval_hours = Decimal(config.interval_minutes) / Decimal(60)
        expected = Decimal(0)
        for r in rows:
            if r.irradiance > 0:
                expected += config.capacity_kw * (r.irradiance / Decimal(1000)) * interval_hours
            else:
                expected += config.capacity_kw * interval_hours
        ratio = (actual / expected).quantize(Decimal("0.001")) if expected > 0 else Decimal(0)

        expected_slots = int((rows[-1].at - rows[0].at).total_seconds() // (config.interval_minutes * 60)) + 1
        gap_count = max(0, expected_slots - len(rows))
        underperforming = sum(
            1
            for r in rows
            if r.irradiance >= Decimal(500)
            and r.ac_kw < config.capacity_kw * Decimal("0.5")
        )
        present = {r.inverter_id for r in rows}
        stale = tuple(sorted(set(config.inverter_ids) - present))
        return SiteAnalysis(
            site_id=site_id,
            day=day,
            readings=len(rows),
            actual_kwh=actual.quantize(Decimal("0.001")),
            expected_kwh=expected.quantize(Decimal("0.001")),
            performance_ratio=ratio,
            gap_count=gap_count,
            underperforming_intervals=underperforming,
            stale_inverters=stale,
        )

    def reconcile_billing(
        self,
        site_id: str,
        period_start: date,
        period_end: date,
        billed_kwh: Decimal | str,
    ) -> list[BillingDiscrepancy]:
        start = datetime.combine(period_start, time.min, tzinfo=UTC)
        end = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=UTC)
        rows = [r for (s, _, at), r in self.readings.items() if s == site_id and start <= at < end]
        if not rows:
            return [BillingDiscrepancy("missing_telemetry", site_id, "no readings in billing period", "0", str(billed_kwh))]
        actual = sum((r.energy_kwh for r in rows), Decimal(0))
        billed = Decimal(str(billed_kwh))
        tolerance = max(Decimal(1), abs(billed) * Decimal("0.02"))
        if abs(actual - billed) > tolerance:
            return [
                BillingDiscrepancy(
                    "billing_mismatch",
                    site_id,
                    f"telemetry differs by more than {tolerance} kWh",
                    str(actual.quantize(Decimal("0.001"))),
                    str(billed.quantize(Decimal("0.001"))),
                )
            ]
        return []

    def detect_anomalies(
        self,
        site_id: str | None = None,
        day: date | None = None,
        detector: AnomalyDetector | None = None,
    ) -> list[AnomalyEvent]:
        active_detector = detector or AnomalyDetector()
        readings = list(self.readings.values())
        if site_id is not None:
            readings = [r for r in readings if r.site_id == site_id]
        if day is not None:
            readings = [r for r in readings if r.at.date() == day]

        events = active_detector.scan_telemetry(readings)
        for ev in events:
            self._record(
                f"anomaly_{ev.severity.lower()}",
                f"{ev.site_id}/{ev.inverter_id}",
                f"kind={ev.kind} msg={ev.message}",
            )
        return events

    def replay_dead_letters(
        self,
        remapped_records: list[dict[str, Any]] | None = None,
    ) -> IngestSummary:
        records_to_process = remapped_records or [dict(dl.payload) for dl in self.dead_letters]
        summary = self.ingest(records_to_process)
        # Clear successfully recovered dead letters if full replay
        if remapped_records is None and summary.created > 0:
            failed_references = {dl.reference for dl in summary.dead_letters}
            self.dead_letters = [dl for dl in self.dead_letters if dl.reference in failed_references]
        return summary
