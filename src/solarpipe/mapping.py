from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import Reading

ALIASES = {
    "site_id": ("site_id", "site", "plant_id", "farm_id"),
    "inverter_id": ("inverter_id", "inverter", "device_id", "asset_id"),
    "at": ("timestamp", "at", "time", "reading_time", "datetime"),
    "ac_kw": ("ac_kw", "ac_power_kw", "power_kw", "kw"),
    "dc_kw": ("dc_kw", "dc_power_kw", "dc_kw"),
    "energy_kwh": ("energy_kwh", "kwh", "interval_kwh", "generation_kwh"),
    "irradiance": ("irradiance", "irradiance_wm2", "poa_wm2", "gti"),
    "temperature_c": ("temperature_c", "temperature", "temp_c", "module_temp_c"),
    "status": ("status", "state", "operating_status"),
}


def _pick(raw: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in raw and raw[name] not in (None, ""):
            return raw[name]
    return None


def _decimal(value: Any, field: str, *, minimum: Decimal | None = None) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"{field} below minimum: {value!r}")
    return number.quantize(Decimal("0.001"))


def _timestamp(value: Any) -> datetime:
    if value in (None, ""):
        raise ValueError("timestamp is required")
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def normalize_reading(raw: dict[str, Any]) -> Reading:
    site_id = str(_pick(raw, ALIASES["site_id"]) or "").strip()
    inverter_id = str(_pick(raw, ALIASES["inverter_id"]) or "").strip()
    if not site_id:
        raise ValueError("site_id is required")
    if not inverter_id:
        raise ValueError("inverter_id is required")
    return Reading(
        site_id=site_id,
        inverter_id=inverter_id,
        at=_timestamp(_pick(raw, ALIASES["at"])),
        ac_kw=_decimal(_pick(raw, ALIASES["ac_kw"]), "ac_kw", minimum=Decimal(0)),
        dc_kw=_decimal(_pick(raw, ALIASES["dc_kw"]), "dc_kw", minimum=Decimal(0)),
        energy_kwh=_decimal(_pick(raw, ALIASES["energy_kwh"]), "energy_kwh", minimum=Decimal(0)),
        irradiance=_decimal(_pick(raw, ALIASES["irradiance"]), "irradiance", minimum=Decimal(0)),
        temperature_c=_decimal(_pick(raw, ALIASES["temperature_c"]), "temperature_c"),
        status=str(_pick(raw, ALIASES["status"]) or "online").strip().lower(),
    )
