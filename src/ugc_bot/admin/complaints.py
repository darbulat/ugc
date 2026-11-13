"""Complaint list queries and the audited admin close operation."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from ugc_bot.domain.enums import AuditAction, ComplaintStatus
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    ComplaintModel,
    OrderModel,
    UserModel,
)

OPEN_COMPLAINT_STATUSES = (ComplaintStatus.PENDING, ComplaintStatus.REVIEWED)
COMPLAINT_STATUS_LABELS = {
    ComplaintStatus.PENDING: "На рассмотрении",
    ComplaintStatus.REVIEWED: "Просмотрена",
    ComplaintStatus.DISMISSED: "Закрыта без мер",
    ComplaintStatus.ACTION_TAKEN: "Приняты меры",
}


def complaint_context(ids: list[UUID]):
    reporter = aliased(UserModel)
    reported = aliased(UserModel)
    return (
        select(
            ComplaintModel.complaint_id,
            func.coalesce(
                func.nullif(reporter.username, ""), reporter.telegram
            ).label("reporter"),
            func.coalesce(
                func.nullif(reported.username, ""), reported.telegram
            ).label("reported"),
            OrderModel.offer_text,
        )
        .join(reporter, reporter.user_id == ComplaintModel.reporter_id)
        .join(reported, reported.user_id == ComplaintModel.reported_id)
        .join(OrderModel, OrderModel.order_id == ComplaintModel.order_id)
        .where(ComplaintModel.complaint_id.in_(ids))
    )


def search_complaints(term: str):
    term = term.strip()
    try:
        identifier = UUID(term)
    except ValueError:
        identifier = None
    if identifier is not None:
        return or_(
            ComplaintModel.complaint_id == identifier,
            ComplaintModel.order_id == identifier,
            ComplaintModel.reporter_id == identifier,
            ComplaintModel.reported_id == identifier,
        )
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return or_(
        ComplaintModel.reason.ilike(pattern, escape="\\"),
        select(UserModel.user_id)
        .where(
            UserModel.user_id.in_(
                (ComplaintModel.reporter_id, ComplaintModel.reported_id)
            ),
            or_(
                UserModel.username.ilike(pattern, escape="\\"),
                UserModel.telegram.ilike(pattern, escape="\\"),
            ),
        )
        .exists(),
        select(OrderModel.order_id)
        .where(
            OrderModel.order_id == ComplaintModel.order_id,
            OrderModel.offer_text.ilike(pattern, escape="\\"),
        )
        .exists(),
    )


def dismiss_open_complaint(session: Session, complaint_id: UUID) -> bool:
    complaint = session.get(ComplaintModel, complaint_id, with_for_update=True)
    if complaint is None or complaint.status not in OPEN_COMPLAINT_STATUSES:
        return False
    now = datetime.now(timezone.utc)
    session.add(
        AuditLogModel(
            entity_type="complaint",
            entity_id=complaint_id,
            action=AuditAction.UPDATE,
            old_values={"status": complaint.status.value},
            new_values={"status": ComplaintStatus.DISMISSED.value},
            changed_at=now,
        )
    )
    complaint.status = ComplaintStatus.DISMISSED
    complaint.reviewed_at = now
    complaint.updated_at = now
    return True
