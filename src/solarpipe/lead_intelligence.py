"""Solar lead qualification, capacity estimation, and CRM webhook dispatch engine."""

import re
import hmac
import hashlib
import json
from enum import Enum
from typing import Optional, Tuple, Dict, Any, List
from pydantic import BaseModel, Field, field_validator


class InquiryTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class SolarInquiry(BaseModel):
    inquiry_id: str = Field(..., min_length=1)
    customer_name: str = Field(..., min_length=1)
    customer_email: str = Field(...)
    property_type: str = Field(default="residential")
    monthly_bill_nzd: float = Field(..., gt=0)
    roof_area_m2: float = Field(..., gt=0)
    battery_interested: bool = Field(default=False)
    notes: Optional[str] = None

    @field_validator("customer_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not re.match(pattern, v):
            raise ValueError(f"Invalid email address: {v}")
        return v.strip().lower()


class QualifiedLead(BaseModel):
    inquiry_id: str
    tier: InquiryTier
    score: float
    estimated_kw_capacity: float
    recommendations: str
    customer_email: str
    property_type: str
    monthly_bill_nzd: float


class WebhookDeliveryResult(BaseModel):
    delivered: bool
    attempts: int
    routed_to_dlq: bool
    status_code: Optional[int] = None
    error_message: Optional[str] = None


def qualify_lead(inquiry: SolarInquiry) -> QualifiedLead:
    """Evaluate solar inquiry metrics to score viability and tier classification."""
    # Estimated kW capacity: roughly 6.5 m^2 per kW of modern PV array
    estimated_kw = round(inquiry.roof_area_m2 / 6.5, 2)

    # Bill score (up to 40 pts)
    if inquiry.monthly_bill_nzd >= 400.0:
        bill_score = 40.0
    elif inquiry.monthly_bill_nzd >= 250.0:
        bill_score = 30.0
    elif inquiry.monthly_bill_nzd >= 150.0:
        bill_score = 20.0
    else:
        bill_score = 10.0

    # Roof score (up to 35 pts)
    if inquiry.roof_area_m2 >= 100.0:
        roof_score = 35.0
    elif inquiry.roof_area_m2 >= 50.0:
        roof_score = 28.0
    elif inquiry.roof_area_m2 >= 25.0:
        roof_score = 18.0
    else:
        roof_score = 8.0

    # Battery interest (up to 15 pts)
    battery_score = 15.0 if inquiry.battery_interested else 5.0

    # Property type multiplier/bonus (up to 10 pts)
    if inquiry.property_type.lower() in ("commercial", "agricultural", "industrial"):
        type_score = 10.0
    else:
        type_score = 7.0

    total_score = min(100.0, bill_score + roof_score + battery_score + type_score)

    if total_score >= 80.0:
        tier = InquiryTier.TIER_A
        rec_parts = ["High solar yield potential"]
        if inquiry.battery_interested:
            rec_parts.append("battery storage recommended for peak shaving and resilience")
        else:
            rec_parts.append("consider battery retrofit for maximum self-consumption")
    elif total_score >= 60.0:
        tier = InquiryTier.TIER_B
        rec_parts = ["Moderate-to-high solar yield potential; standard grid-tied inverter suitable"]
        if inquiry.battery_interested:
            rec_parts.append("battery storage recommended")
    else:
        tier = InquiryTier.TIER_C
        rec_parts = ["Low baseline consumption or constrained roof space; micro-inverter topology advised"]

    recommendations = "; ".join(rec_parts)

    return QualifiedLead(
        inquiry_id=inquiry.inquiry_id,
        tier=tier,
        score=round(total_score, 1),
        estimated_kw_capacity=estimated_kw,
        recommendations=recommendations,
        customer_email=str(inquiry.customer_email),
        property_type=inquiry.property_type,
        monthly_bill_nzd=inquiry.monthly_bill_nzd
    )


def generate_crm_webhook_payload(qual: QualifiedLead, secret: str) -> Tuple[Dict[str, Any], str]:
    """Generate canonical webhook JSON payload and HMAC-SHA256 signature."""
    payload = {
        "event": "lead.qualified",
        "inquiry_id": qual.inquiry_id,
        "tier": qual.tier.value if hasattr(qual.tier, "value") else str(qual.tier),
        "score": qual.score,
        "estimated_kw_capacity": qual.estimated_kw_capacity,
        "customer_email": qual.customer_email,
        "idempotency_key": f"lead.qualified:{qual.inquiry_id}:{int(qual.score)}"
    }

    canonical_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()
    return payload, sig


def verify_webhook_signature(payload: Dict[str, Any], signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature of webhook payload against shared secret."""
    try:
        canonical_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        expected_sig = hmac.new(secret.encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_sig, signature)
    except Exception:
        return False


class MockCRMDispatcher:
    """Simulates reliable event delivery to enterprise CRM endpoints with retries and dead-letter queue."""

    def __init__(self, fail_until_attempt: int = 0):
        self.fail_until_attempt = fail_until_attempt
        self.current_attempt = 0
        self.dead_letter_queue: List[Dict[str, Any]] = []

    def deliver_with_retry(
        self,
        payload: Dict[str, Any],
        signature: str,
        max_retries: int = 3
    ) -> WebhookDeliveryResult:
        """Attempt to deliver payload with retry logic. Route to DLQ on exhaustion."""
        for attempt in range(1, max_retries + 1):
            self.current_attempt += 1
            if self.current_attempt >= self.fail_until_attempt:
                return WebhookDeliveryResult(
                    delivered=True,
                    attempts=attempt,
                    routed_to_dlq=False,
                    status_code=200
                )

        # Retries exhausted -> route to DLQ
        self.dead_letter_queue.append({
            "payload": payload,
            "signature": signature,
            "attempts": max_retries,
            "reason": "Max retries exceeded"
        })
        return WebhookDeliveryResult(
            delivered=False,
            attempts=max_retries,
            routed_to_dlq=True,
            status_code=500,
            error_message="CRM endpoint unavailable after max retries"
        )
