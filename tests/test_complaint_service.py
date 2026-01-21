"""Tests for complaint service."""

from uuid import UUID

import pytest

from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.domain.enums import ComplaintStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryComplaintRepository


def test_create_complaint() -> None:
    """Create a new complaint."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    complaint = service.create_complaint(
        reporter_id=UUID("00000000-0000-0000-0000-000000000901"),
        reported_id=UUID("00000000-0000-0000-0000-000000000902"),
        order_id=UUID("00000000-0000-0000-0000-000000000903"),
        reason="Мошенничество",
    )

    assert complaint.status == ComplaintStatus.PENDING
    assert complaint.reason == "Мошенничество"
    assert repo.get_by_id(complaint.complaint_id) is not None


def test_create_complaint_duplicate() -> None:
    """Prevent duplicate complaints for same order."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    reporter_id = UUID("00000000-0000-0000-0000-000000000911")
    order_id = UUID("00000000-0000-0000-0000-000000000912")

    service.create_complaint(
        reporter_id=reporter_id,
        reported_id=UUID("00000000-0000-0000-0000-000000000913"),
        order_id=order_id,
        reason="Мошенничество",
    )

    with pytest.raises(ValueError, match="уже подали жалобу"):
        service.create_complaint(
            reporter_id=reporter_id,
            reported_id=UUID("00000000-0000-0000-0000-000000000914"),
            order_id=order_id,
            reason="Другое",
        )


def test_get_by_id() -> None:
    """Get complaint by ID."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    complaint = service.create_complaint(
        reporter_id=UUID("00000000-0000-0000-0000-000000000921"),
        reported_id=UUID("00000000-0000-0000-0000-000000000922"),
        order_id=UUID("00000000-0000-0000-0000-000000000923"),
        reason="Мошенничество",
    )

    found = service.get_by_id(complaint.complaint_id)
    assert found is not None
    assert found.complaint_id == complaint.complaint_id


def test_get_by_id_not_found() -> None:
    """Return None for non-existent complaint."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    found = service.get_by_id(UUID("00000000-0000-0000-0000-000000000999"))
    assert found is None


def test_list_by_order() -> None:
    """List complaints for a specific order."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    order_id = UUID("00000000-0000-0000-0000-000000000931")
    service.create_complaint(
        reporter_id=UUID("00000000-0000-0000-0000-000000000932"),
        reported_id=UUID("00000000-0000-0000-0000-000000000933"),
        order_id=order_id,
        reason="Мошенничество",
    )
    service.create_complaint(
        reporter_id=UUID("00000000-0000-0000-0000-000000000934"),
        reported_id=UUID("00000000-0000-0000-0000-000000000935"),
        order_id=order_id,
        reason="Другое",
    )

    complaints = service.list_by_order(order_id)
    assert len(list(complaints)) == 2


def test_list_by_reporter() -> None:
    """List complaints filed by a specific user."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    reporter_id = UUID("00000000-0000-0000-0000-000000000941")
    service.create_complaint(
        reporter_id=reporter_id,
        reported_id=UUID("00000000-0000-0000-0000-000000000942"),
        order_id=UUID("00000000-0000-0000-0000-000000000943"),
        reason="Мошенничество",
    )
    service.create_complaint(
        reporter_id=reporter_id,
        reported_id=UUID("00000000-0000-0000-0000-000000000944"),
        order_id=UUID("00000000-0000-0000-0000-000000000945"),
        reason="Другое",
    )

    complaints = service.list_by_reporter(reporter_id)
    assert len(list(complaints)) == 2


def test_list_by_status() -> None:
    """List complaints by status."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    complaint1 = service.create_complaint(
        reporter_id=UUID("00000000-0000-0000-0000-000000000951"),
        reported_id=UUID("00000000-0000-0000-0000-000000000952"),
        order_id=UUID("00000000-0000-0000-0000-000000000953"),
        reason="Мошенничество",
    )
    complaint2 = service.create_complaint(
        reporter_id=UUID("00000000-0000-0000-0000-000000000954"),
        reported_id=UUID("00000000-0000-0000-0000-000000000955"),
        order_id=UUID("00000000-0000-0000-0000-000000000956"),
        reason="Другое",
    )

    # Dismiss one complaint
    service.dismiss_complaint(complaint1.complaint_id)

    pending = service.list_by_status(ComplaintStatus.PENDING)
    dismissed = service.list_by_status(ComplaintStatus.DISMISSED)

    assert len(list(pending)) == 1
    assert len(list(dismissed)) == 1
    assert list(pending)[0].complaint_id == complaint2.complaint_id
    assert list(dismissed)[0].complaint_id == complaint1.complaint_id


def test_dismiss_complaint() -> None:
    """Dismiss a complaint without taking action."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    complaint = service.create_complaint(
        reporter_id=UUID("00000000-0000-0000-0000-000000000961"),
        reported_id=UUID("00000000-0000-0000-0000-000000000962"),
        order_id=UUID("00000000-0000-0000-0000-000000000963"),
        reason="Мошенничество",
    )

    dismissed = service.dismiss_complaint(complaint.complaint_id)

    assert dismissed.status == ComplaintStatus.DISMISSED
    assert dismissed.reviewed_at is not None
    assert dismissed.complaint_id == complaint.complaint_id
    assert dismissed.reason == complaint.reason


def test_dismiss_complaint_not_found() -> None:
    """Raise error when dismissing non-existent complaint."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    with pytest.raises(ValueError, match="not found"):
        service.dismiss_complaint(UUID("00000000-0000-0000-0000-000000000999"))


def test_resolve_complaint_with_action() -> None:
    """Resolve complaint by taking action."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    complaint = service.create_complaint(
        reporter_id=UUID("00000000-0000-0000-0000-000000000971"),
        reported_id=UUID("00000000-0000-0000-0000-000000000972"),
        order_id=UUID("00000000-0000-0000-0000-000000000973"),
        reason="Мошенничество",
    )

    resolved = service.resolve_complaint_with_action(complaint.complaint_id)

    assert resolved.status == ComplaintStatus.ACTION_TAKEN
    assert resolved.reviewed_at is not None
    assert resolved.complaint_id == complaint.complaint_id
    assert resolved.reason == complaint.reason


def test_resolve_complaint_with_action_not_found() -> None:
    """Raise error when resolving non-existent complaint."""

    repo = InMemoryComplaintRepository()
    service = ComplaintService(complaint_repo=repo)

    with pytest.raises(ValueError, match="not found"):
        service.resolve_complaint_with_action(
            UUID("00000000-0000-0000-0000-000000000999")
        )
