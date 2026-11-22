import pytest
from pydantic import ValidationError
from solarpipe.lead_intelligence import (
    SolarInquiry,
    InquiryTier,
    qualify_lead,
    generate_crm_webhook_payload,
    verify_webhook_signature,
    MockCRMDispatcher,
    WebhookDeliveryResult
)


def test_inquiry_validation_valid():
    inquiry = SolarInquiry(
        inquiry_id="inq-101",
        customer_name="Auckland Commercial Farm",
        customer_email="operations@farmnz.co.nz",
        property_type="commercial",
        monthly_bill_nzd=650.0,
        roof_area_m2=180.0,
        battery_interested=True,
        notes="Looking to reduce daytime peak grid demand and install backup storage."
    )
    assert inquiry.inquiry_id == "inq-101"
    assert inquiry.monthly_bill_nzd == 650.0
    assert inquiry.battery_interested is True


def test_inquiry_validation_rejects_invalid():
    with pytest.raises(ValidationError):
        SolarInquiry(
            inquiry_id="",
            customer_name="Test",
            customer_email="not-an-email",
            property_type="residential",
            monthly_bill_nzd=-50.0,
            roof_area_m2=0.0
        )


def test_lead_scoring_tier_a():
    inquiry = SolarInquiry(
        inquiry_id="inq-tier-a",
        customer_name="High Demand User",
        customer_email="client@domain.nz",
        property_type="residential",
        monthly_bill_nzd=420.0,
        roof_area_m2=65.0,
        battery_interested=True
    )
    result = qualify_lead(inquiry)
    assert result.tier == InquiryTier.TIER_A
    assert result.score >= 80.0
    assert result.estimated_kw_capacity >= 6.0
    assert "battery storage recommended" in result.recommendations.lower()


def test_lead_scoring_tier_c():
    inquiry = SolarInquiry(
        inquiry_id="inq-tier-c",
        customer_name="Low Demand Apartment",
        customer_email="flat@domain.nz",
        property_type="residential",
        monthly_bill_nzd=80.0,
        roof_area_m2=15.0,
        battery_interested=False
    )
    result = qualify_lead(inquiry)
    assert result.tier == InquiryTier.TIER_C
    assert result.score < 60.0
    assert result.estimated_kw_capacity < 3.0


def test_crm_webhook_payload_and_signature():
    inquiry = SolarInquiry(
        inquiry_id="inq-crm-99",
        customer_name="Waikato Dairy",
        customer_email="manager@waikatodairy.co.nz",
        property_type="agricultural",
        monthly_bill_nzd=850.0,
        roof_area_m2=220.0,
        battery_interested=True
    )
    qual = qualify_lead(inquiry)
    secret = "solar-crm-shared-secret-key-32b"
    payload, signature = generate_crm_webhook_payload(qual, secret=secret)

    assert payload["event"] == "lead.qualified"
    assert payload["inquiry_id"] == "inq-crm-99"
    assert payload["tier"] == "TIER_A"
    assert payload["idempotency_key"] == f"lead.qualified:inq-crm-99:{int(qual.score)}"
    assert verify_webhook_signature(payload, signature, secret=secret) is True
    assert verify_webhook_signature(payload, "invalid_sig", secret=secret) is False


def test_crm_dispatcher_retry_and_dead_letter():
    dispatcher = MockCRMDispatcher(fail_until_attempt=2)
    inquiry = SolarInquiry(
        inquiry_id="inq-retry-1",
        customer_name="Tauranga Orchard",
        customer_email="orchard@bayofplenty.nz",
        property_type="commercial",
        monthly_bill_nzd=350.0,
        roof_area_m2=80.0,
        battery_interested=False
    )
    qual = qualify_lead(inquiry)
    payload, sig = generate_crm_webhook_payload(qual, secret="test-secret")

    # Attempt delivery with retry
    result = dispatcher.deliver_with_retry(payload, sig, max_retries=3)
    assert isinstance(result, WebhookDeliveryResult)
    assert result.delivered is True
    assert result.attempts == 2
    assert result.routed_to_dlq is False

    # Simulate hard downstream failure -> DLQ
    failing_dispatcher = MockCRMDispatcher(fail_until_attempt=10)
    dlq_result = failing_dispatcher.deliver_with_retry(payload, sig, max_retries=2)
    assert isinstance(dlq_result, WebhookDeliveryResult)
    assert dlq_result.delivered is False
    assert dlq_result.attempts == 2
    assert dlq_result.routed_to_dlq is True
    assert len(failing_dispatcher.dead_letter_queue) == 1
