from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from .models import AnomalyEvent, Reading


class AnomalyDetector:
    def __init__(
        self,
        thermal_threshold_c: Decimal = Decimal("65.0"),
        peak_sun_min_irradiance: Decimal = Decimal("400.0"),
        drift_tolerance: Decimal = Decimal("0.25"),
    ) -> None:
        self.thermal_threshold_c = thermal_threshold_c
        self.peak_sun_min_irradiance = peak_sun_min_irradiance
        self.drift_tolerance = drift_tolerance

    def _make_id(self, site_id: str, inverter_id: str, kind: str, at: datetime) -> str:
        raw = f"{site_id}:{inverter_id}:{kind}:{at.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def check_thermal_throttling(self, reading: Reading) -> AnomalyEvent | None:
        if reading.temperature_c >= self.thermal_threshold_c:
            # If inverter is hot and producing significantly below DC input capacity
            if reading.dc_kw > Decimal("1.0") and reading.ac_kw < (reading.dc_kw * Decimal("0.80")):
                return AnomalyEvent(
                    anomaly_id=self._make_id(reading.site_id, reading.inverter_id, "thermal_throttle", reading.at),
                    site_id=reading.site_id,
                    inverter_id=reading.inverter_id,
                    at=reading.at,
                    severity="WARNING",
                    kind="thermal_throttling",
                    message=(
                        f"Inverter {reading.inverter_id} temperature {reading.temperature_c}°C exceeds threshold "
                        f"{self.thermal_threshold_c}°C with reduced conversion efficiency."
                    ),
                    metric_value=reading.temperature_c,
                    threshold_value=self.thermal_threshold_c,
                )
        return None

    def check_zero_generation_under_sun(self, reading: Reading) -> AnomalyEvent | None:
        if reading.irradiance >= self.peak_sun_min_irradiance and reading.ac_kw <= Decimal("0.05"):
            return AnomalyEvent(
                anomaly_id=self._make_id(reading.site_id, reading.inverter_id, "zero_gen_peak_sun", reading.at),
                site_id=reading.site_id,
                inverter_id=reading.inverter_id,
                at=reading.at,
                severity="CRITICAL",
                kind="zero_gen_peak_sun",
                message=(
                    f"Inverter {reading.inverter_id} generating zero power ({reading.ac_kw} kW) "
                    f"under high solar irradiance ({reading.irradiance} W/m²)."
                ),
                metric_value=reading.ac_kw,
                threshold_value=self.peak_sun_min_irradiance,
            )
        return None

    def check_peer_inverter_drift(self, readings: Sequence[Reading]) -> list[AnomalyEvent]:
        # Group by (site_id, at)
        by_slot: dict[tuple[str, datetime], list[Reading]] = defaultdict(list)
        for r in readings:
            by_slot[(r.site_id, r.at)].append(r)

        anomalies: list[AnomalyEvent] = []
        for (site_id, at), slot_readings in by_slot.items():
            if len(slot_readings) < 2:
                continue

            # Calculate conversion ratio for each inverter with valid DC input
            ratios: list[tuple[Reading, Decimal]] = []
            for r in slot_readings:
                if r.dc_kw > Decimal("0.5"):
                    ratio = r.ac_kw / r.dc_kw
                    ratios.append((r, ratio))

            if len(ratios) < 2:
                continue

            sorted_ratios = sorted([ratio for _, ratio in ratios])
            median_ratio = sorted_ratios[len(sorted_ratios) // 2]
            if median_ratio <= Decimal("0.10"):
                continue

            for r, ratio in ratios:
                ratio_deficit = (median_ratio - ratio) / median_ratio
                if ratio_deficit >= self.drift_tolerance:
                    severity = "CRITICAL" if ratio_deficit >= Decimal("0.50") else "WARNING"
                    anomalies.append(
                        AnomalyEvent(
                            anomaly_id=self._make_id(site_id, r.inverter_id, "peer_drift", at),
                            site_id=site_id,
                            inverter_id=r.inverter_id,
                            at=at,
                            severity=severity,
                            kind="peer_efficiency_drift",
                            message=(
                                f"Inverter {r.inverter_id} conversion ratio {ratio:.3f} is "
                                f"{ratio_deficit * 100:.1f}% below site median {median_ratio:.3f}."
                            ),
                            metric_value=ratio,
                            threshold_value=median_ratio * (Decimal("1") - self.drift_tolerance),
                        )
                    )
        return anomalies

    def scan_telemetry(self, readings: Sequence[Reading]) -> list[AnomalyEvent]:
        events: list[AnomalyEvent] = []
        for r in readings:
            thermal = self.check_thermal_throttling(r)
            if thermal:
                events.append(thermal)

            zero_gen = self.check_zero_generation_under_sun(r)
            if zero_gen:
                events.append(zero_gen)

        peer_drifts = self.check_peer_inverter_drift(readings)
        events.extend(peer_drifts)

        return sorted(events, key=lambda e: (e.at, e.site_id, e.inverter_id))
