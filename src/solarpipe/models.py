from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class SiteConfig:
    site_id: str
    capacity_kw: Decimal
    inverter_ids: tuple[str, ...] = ()
    interval_minutes: int = 5


@dataclass(frozen=True)
class Reading:
    site_id: str
    inverter_id: str
    at: datetime
    ac_kw: Decimal
    dc_kw: Decimal
    energy_kwh: Decimal
    irradiance: Decimal
    temperature_c: Decimal
    status: str

    def fingerprint(self) -> str:
        payload = {
            "ac_kw": str(self.ac_kw),
            "dc_kw": str(self.dc_kw),
            "energy_kwh": str(self.energy_kwh),
            "irradiance": str(self.irradiance),
            "temperature_c": str(self.temperature_c),
            "status": self.status,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class AuditEntry:
    at: datetime
    action: str
    reference: str
    detail: str


@dataclass
class DeadLetter:
    letter_id: str
    reference: str
    payload: dict[str, Any]
    errors: list[str]


@dataclass
class IngestSummary:
    received: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    dead_letters: list[DeadLetter] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)


@dataclass(frozen=True)
class SiteAnalysis:
    site_id: str
    day: date
    readings: int
    actual_kwh: Decimal
    expected_kwh: Decimal
    performance_ratio: Decimal
    gap_count: int
    underperforming_intervals: int
    stale_inverters: tuple[str, ...]


@dataclass(frozen=True)
class AnomalyEvent:
    anomaly_id: str
    site_id: str
    inverter_id: str
    at: datetime
    severity: str
    kind: str
    message: str
    metric_value: Decimal
    threshold_value: Decimal


@dataclass(frozen=True)
class BillingDiscrepancy:
    kind: str
    site_id: str
    detail: str
    actual_kwh: str = ""
    billed_kwh: str = ""
