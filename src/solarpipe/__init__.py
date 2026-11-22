"""Solar telemetry, billing reconciliation, and lead intelligence reference implementation."""

from .anomaly import AnomalyDetector
from .models import AnomalyEvent, Reading, SiteConfig
from .pipeline import SolarPipeline
from .lead_intelligence import (
    InquiryTier,
    SolarInquiry,
    QualifiedLead,
    WebhookDeliveryResult,
    qualify_lead,
    generate_crm_webhook_payload,
    verify_webhook_signature,
    MockCRMDispatcher,
)

__all__ = [
    "AnomalyDetector",
    "AnomalyEvent",
    "Reading",
    "SiteConfig",
    "SolarPipeline",
    "InquiryTier",
    "SolarInquiry",
    "QualifiedLead",
    "WebhookDeliveryResult",
    "qualify_lead",
    "generate_crm_webhook_payload",
    "verify_webhook_signature",
    "MockCRMDispatcher",
]
