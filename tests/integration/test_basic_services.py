"""Basic integration tests for core services."""

import pytest


def test_basic_services_integration(
    dispatcher,
) -> None:
    """Test basic services integration without database operations."""

    # === Проверяем, что все сервисы созданы ===
    try:
        user_service = dispatcher["user_role_service"]
        order_service = dispatcher["order_service"]
        payment_service = dispatcher["payment_service"]
        interaction_service = dispatcher["interaction_service"]
        complaint_service = dispatcher["complaint_service"]
        offer_dispatch_service = dispatcher["offer_dispatch_service"]
        offer_response_service = dispatcher["offer_response_service"]
        instagram_service = dispatcher["instagram_verification_service"]
        blogger_reg_service = dispatcher["blogger_registration_service"]
        advertiser_reg_service = dispatcher["advertiser_registration_service"]
    except KeyError as e:
        pytest.fail(f"Service not found in dispatcher: {e}")

    # === Проверяем, что сервисы не None ===
    assert user_service is not None
    assert order_service is not None
    assert payment_service is not None
    assert interaction_service is not None
    assert complaint_service is not None
    assert offer_dispatch_service is not None
    assert offer_response_service is not None
    assert instagram_service is not None
    assert blogger_reg_service is not None
    assert advertiser_reg_service is not None

    # === Проверяем, что сервисы имеют базовые методы ===
    assert hasattr(user_service, "set_user")
    assert hasattr(user_service, "update_status")

    assert hasattr(order_service, "create_order")

    assert hasattr(payment_service, "confirm_telegram_payment")

    assert hasattr(interaction_service, "record_blogger_feedback")
    assert hasattr(interaction_service, "record_advertiser_feedback")

    assert hasattr(complaint_service, "create_complaint")

    print("✅ Basic services integration test passed!")
