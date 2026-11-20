"""
Synthetic legacy facts, never a production dump
or copied profile payload.

Six INSERT proof triggers are bypassed only while
constructing historical
fixtures: their original items/contacts no longer
exist in the approved case.
All FK/CHECK constraints stay enabled, and proof
triggers are restored before
the utility is invoked. The utility must handle
its own guards independently.

"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text

from scripts.residual_purge import (
    AUDIT_ID,
    BUSINESS_ORDER,
    INSERT_GUARDS,
    TARGET_ORDERS,
    TARGET_USERS,
    load_plan,
)
from scripts.residual_purge_catalog import quote, rows
from ugc_bot.infrastructure.db.identity_history_schema import (
    BINDING_HASH,
    PROFILE_HASH,
)


def put(db, table, **payload):
    columns = ",".join(quote(c) for c in payload)
    db.execute(
        text(
            f"""INSERT INTO {quote(table)} ({columns}) SELECT {columns}
FROM jsonb_populate_record(NULL::{quote(table)},CAST(:doc
AS jsonb))"""
        ),
        {"doc": json.dumps(payload, default=str)},
    )


def _order(db, order, owner, *, deleted=False):
    put(
        db,
        "orders",
        order_id=order,
        advertiser_id=owner,
        product_link="https://example.test/synthetic",
        offer_text="synthetic fixture",
        price="100.00",
        bloggers_needed=10,
        status="deleted" if deleted else "closed",
        dispatch_stopped=deleted,
    )


def _campaigns(db, now, admin):
    creator, owner = TARGET_USERS[:2]
    for actor, key, action in [
        (admin, "policy", "publish"),
        (admin, "grant", "grant"),
        (admin, "revoke", "revoke"),
        (creator, "consent", "consent"),
        (creator, "unsubscribe", "unsubscribe"),
    ]:
        put(
            db,
            "campaign_foundation_commands",
            actor_id=actor,
            operation_key=key,
            action=action,
            payload_hash="a" * 64,
            recorded_at=now,
            result={},
        )
    put(
        db,
        "campaign_policy_events",
        version=1,
        publication_version=1,
        terms_version="synthetic",
        terms_hash="b" * 64,
        default_locale="ru",
        terms={},
        limits={},
        enabled=True,
        reason="synthetic",
        actor_id=admin,
        operation_key="policy",
        recorded_at=now,
    )
    for version in (1, 2):
        put(
            db,
            "campaign_publisher_events",
            owner_id=owner,
            version=version,
            active=version == 1,
            policy_version=1,
            reason="synthetic",
            actor_id=admin,
            operation_key="grant" if version == 1 else "revoke",
            recorded_at=now,
        )
        put(
            db,
            "campaign_consent_events",
            creator_id=creator,
            version=version,
            owner_id=owner,
            canonical_identity="synthetic_test_identity",
            binding_created_at=now,
            policy_version=1,
            terms_version="synthetic",
            terms_hash="b" * 64,
            active=version == 1,
            actor_id=creator,
            operation_key="consent" if version == 1 else "unsubscribe",
            recorded_at=now,
        )
    campaign = uuid4()
    for version in (1, 2):
        put(
            db,
            "campaign_draft_commands",
            actor_id=owner,
            operation_key=f"draft-{version}",
            payload_hash="c" * 64,
            recorded_at=now,
            result={},
        )
        if version == 1:
            put(
                db,
                "campaign_drafts",
                campaign_id=campaign,
                owner_id=owner,
                operation_key="draft-1",
                created_at=now,
            )
        put(
            db,
            "campaign_draft_revisions",
            campaign_id=campaign,
            version=version,
            owner_id=owner,
            operation_key=f"draft-{version}",
            policy_version=1,
            terms_hash="b" * 64,
            grant_version=1,
            recorded_at=now,
            content={},
            segment={},
            revision_digest=str(version) * 64,
        )


def _intake(db, now, recipients):
    requests = [uuid4(), uuid4()]
    lead = uuid4()
    for order, request in zip(TARGET_ORDERS, requests, strict=True):
        put(
            db,
            "order_intake_receipts",
            request_id=request,
            order_id=order,
            client_id=TARGET_USERS[0],
            operation_key=str(request),
            payload_hash="d" * 64,
            requested_at=now,
            result={"request_id": str(request), "order_id": order},
        )
        put(
            db,
            "order_notice_events",
            order_id=order,
            event_kind="created",
            created_at=now,
            expanded=True,
        )
        for index in range(3):
            put(
                db,
                "order_notice_deliveries",
                job_id=uuid4(),
                order_id=order,
                event_kind="created",
                recipient=f"synthetic-{index}",
                state="sent",
                attempt=1,
            )
    order = TARGET_ORDERS[1]
    put(
        db,
        "accompaniment_leads",
        lead_id=lead,
        request_id=requests[1],
        order_id=order,
        client_id=TARGET_USERS[0],
        requested_at=now,
        contact_reference="synthetic contact",
        selected_ordinals=[1],
        state="requested_unpaid",
    )
    put(
        db,
        "accompaniment_lead_outbox",
        lead_id=lead,
        order_id=order,
        created_at=now,
        expanded_at=now,
    )
    for recipient in recipients:
        job, attempt = uuid4(), uuid4()
        put(
            db,
            "accompaniment_lead_deliveries",
            job_id=job,
            lead_id=lead,
            order_id=order,
            recipient_id=recipient,
            state="accepted",
            attempt_count=1,
            current_attempt_id=attempt,
        )
        put(
            db,
            "accompaniment_lead_attempts",
            attempt_id=attempt,
            job_id=job,
            lead_id=lead,
            order_id=order,
            recipient_id=recipient,
            number=1,
            lease_token=uuid4(),
            prepared_at=now,
            lease_until=now + timedelta(minutes=1),
            channel="telegram",
            address="synthetic",
            address_kind="chat_id",
            text="synthetic",
        )
        put(
            db,
            "accompaniment_lead_outcomes",
            outcome_id=uuid4(),
            attempt_id=attempt,
            job_id=job,
            lead_id=lead,
            order_id=order,
            kind="result",
            status="accepted",
            recorded_at=now,
            provider_reference="synthetic",
            applied=True,
        )


def _checkout(db, now):
    order, attempt = TARGET_ORDERS[0], uuid4()
    put(
        db,
        "financial_checkouts",
        order_id=order,
        client_id=TARGET_USERS[0],
        account="synthetic",
        state="failed",
        attempt_id=attempt,
        version=1,
    )
    put(
        db,
        "checkout_requests",
        request_id=uuid4(),
        client_id=TARGET_USERS[0],
        operation_key="checkout",
        order_id=order,
        payload_hash="e" * 64,
        attempt_id=attempt,
        created_at=now,
    )
    put(
        db,
        "checkout_link_attempts",
        attempt_id=attempt,
        order_id=order,
        created_at=now,
        prepared={"order_id": order},
    )
    put(
        db,
        "checkout_link_results",
        result_id=uuid4(),
        attempt_id=attempt,
        observed_at=now,
        outcome="failed",
    )


def _history(db, now, partner, working_creator):
    for user, count in zip(TARGET_USERS, (6, 5, 4), strict=True):
        for index in range(count):
            source = (
                "canonical_profile_cutover"
                if user == TARGET_USERS[0] and index == 0
                else "instagram_webhook"
            )
            put(
                db,
                "creator_identity_observations",
                creator_user_id=user,
                instagram_user_id="synthetic-" + user,
                active=index % 2 == 0,
                observed_at=now + timedelta(seconds=index),
                source=source,
                business_key=f"synthetic-profile-{user}-{index}",
            )
    put(
        db,
        "creator_identity_observations",
        creator_user_id=working_creator,
        instagram_user_id="synthetic-working",
        active=True,
        observed_at=now,
        source="canonical_profile_cutover",
        business_key="synthetic-working-profile",
    )
    for index in range(2):
        put(
            db,
            "creator_direct_binding_observations",
            referrer_user_id=TARGET_USERS[1],
            referred_user_id=TARGET_USERS[0],
            active=index == 0,
            created_at=now,
            registered_at=now,
            observed_at=now + timedelta(seconds=index),
            source="direct_binding_observed",
            business_key=f"synthetic-binding-{index}",
        )
    put(
        db,
        "creator_direct_binding_observations",
        referrer_user_id=partner,
        referred_user_id=working_creator,
        active=True,
        created_at=now,
        registered_at=now,
        observed_at=now,
        source="direct_binding_cutover",
        business_key="synthetic-working-binding",
    )
    put(
        db,
        "instagram_profile_observations",
        observation_id=uuid4(),
        user_id=TARGET_USERS[2],
        meta_id="synthetic-latest",
        id_kind="legacy_meta_id",
        identity_context="synthetic",
        old_handle="synthetic_old",
        new_handle="synthetic_new",
        outcome="verified",
        observed_at=now,
    )
    db.execute(
        text(
            """ALTER TABLE creator_identity_coverage DISABLE TRIGGER
creator_coverage_immutable"""
        )
    )
    db.execute(
        text(
            f"""
UPDATE creator_identity_coverage SET covered_from=:now,
profile_seed_count=2,binding_seed_count=1,profile_seed_hash=(SELECT
{PROFILE_HASH} FROM creator_identity_observations
WHERE
source='canonical_profile_cutover'),binding_seed_hash=(SELECT
{BINDING_HASH} FROM creator_direct_binding_observations
WHERE source='direct_binding_cutover')
"""
        ),
        {"now": now},
    )
    db.execute(
        text(
            "ALTER TABLE creator_identity_coverage "
            "ENABLE TRIGGER creator_coverage_immutable"
        )
    )


def add_working_snapshot(db, seed, *, at=None):
    snapshot = uuid4()
    put(
        db,
        "rate_snapshots",
        id=snapshot,
        recipient_id=seed["partner"],
        referred_user_id=seed["creator"],
        paid_item_id=seed["item"],
        order_id=BUSINESS_ORDER,
        payment_id=seed["payment"],
        currency="RUB",
        side="client",
        effective_at=at or seed["now"],
        registered_at=seed["now"],
        age_rule="first_year",
        verified_count=1,
        rate_bps=1000,
        policy_version=seed["policy"],
        payload_hash="f" * 64,
    )
    return snapshot


def _working_money(db, now, partner, creator):
    policy = "synthetic-residual-policy"
    put(
        db,
        "financial_policy_versions",
        version=policy,
        approved_by=partner,
        approved_at=now - timedelta(days=1),
        effective_from=now - timedelta(days=1),
        refund_window_seconds=3600,
        rules={},
    )
    item, payment = uuid4(), uuid4()
    put(
        db,
        "order_items",
        paid_item_id=item,
        order_id=BUSINESS_ORDER,
        ordinal=1,
        currency="RUB",
        selection_minor=50000,
        accompaniment_minor=0,
        policy_version=policy,
        selection_due_at=now + timedelta(days=1),
        quote_key="synthetic",
        quote_payload={},
    )
    put(
        db,
        "payments",
        payment_id=payment,
        order_id=BUSINESS_ORDER,
        provider="synthetic",
        status="paid",
        amount="500.00",
        currency="RUB",
        external_id=str(payment),
        captured_minor=50000,
        financial_version=policy,
    )
    seed = dict(
        partner=partner,
        creator=creator,
        now=now,
        item=item,
        payment=payment,
        policy=policy,
    )
    snapshot = add_working_snapshot(db, seed)
    obligation, movement = uuid4(), uuid4()
    put(
        db,
        "financial_obligations",
        id=obligation,
        business_key=str(obligation),
        kind="client_referral",
        recipient_id=partner,
        paid_item_id=item,
        order_id=BUSINESS_ORDER,
        currency="RUB",
        base_minor=50000,
        amount_minor=5000,
        snapshot_id=snapshot,
        policy_version=policy,
        recorded_at=now,
        payload_hash="a" * 64,
    )
    put(
        db,
        "financial_movements",
        id=movement,
        obligation_id=obligation,
        operation_key=str(movement),
        event_id="synthetic",
        movement_type="issuance",
        amount_minor=5000,
        currency="RUB",
        effective_at=now,
        recorded_at=now,
        actor_id=partner,
        actor_kind="user",
        reason="synthetic",
        bucket_to="pending",
        payload_hash="b" * 64,
    )
    return seed


def seed_residuals(engine):
    plan = load_plan()
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    admin, creator = (plan["protected_accounts"][i]["user_id"] for i in (0, 3))
    targets = {}
    with engine.begin() as db:
        before = {
            r["table"]: {
                x["fingerprint"]
                for x in rows(
                    db,
                    f"""
SELECT md5(to_jsonb(t)::text) AS fingerprint FROM
{quote(r["table"])}
t
""",
                )
            }
            for r in plan["delete_tables"]
        }
        for user in TARGET_USERS:
            put(
                db,
                "users",
                user_id=user,
                messenger_type="telegram",
                username="synthetic archived",
                status="deleted",
            )
        for user in plan["protected_accounts"]:
            put(
                db,
                "users",
                user_id=user["user_id"],
                messenger_type="telegram",
                username="synthetic preserved",
                status=user["status"],
                telegram=user["telegram"],
                telegram_id="synthetic-" + user["user_id"],
                admin=user["admin"],
            )
        for order in TARGET_ORDERS:
            _order(db, order, TARGET_USERS[0], deleted=True)
        _order(db, BUSINESS_ORDER, admin)
        for table, trigger in sorted(INSERT_GUARDS):
            db.execute(
                text(
                    f"ALTER TABLE {quote(table)} "
                    f"DISABLE TRIGGER {quote(trigger)}"
                )
            )
        _campaigns(db, now, admin)
        recipients = [r["user_id"] for r in plan["protected_accounts"][:3]]
        _intake(db, now, recipients)
        _checkout(db, now)
        for table, trigger in sorted(INSERT_GUARDS):
            db.execute(
                text(
                    f"ALTER TABLE {quote(table)} "
                    f"ENABLE TRIGGER {quote(trigger)}"
                )
            )
        _history(db, now, admin, creator)
        put(
            db,
            "audit_log",
            id=AUDIT_ID,
            entity_type="order",
            entity_id=BUSINESS_ORDER,
            action="update",
            old_values={"advertiser_id": TARGET_USERS[0]},
            new_values={
                "advertiser_id": admin,
                "reason": "synthetic owner correction",
            },
            changed_by=admin,
            changed_at=now,
        )
        # Keep the global publish receipt outside the approved test scope.
        for target in plan["delete_tables"]:
            table = target["table"]
            found = rows(
                db,
                f"""
SELECT md5(to_jsonb(t)::text) AS fingerprint FROM {quote(table)}
t""",
            )
            hashes = {r["fingerprint"] for r in found} - before[table]
            if table == "users":
                hashes = {
                    r["fingerprint"]
                    for r in rows(
                        db,
                        """
SELECT md5(to_jsonb(t)::text) AS fingerprint FROM users
t WHERE user_id=ANY(CAST(:ids AS uuid[]))""",
                        {"ids": list(TARGET_USERS)},
                    )
                }
            elif table == "orders":
                hashes = {
                    r["fingerprint"]
                    for r in rows(
                        db,
                        """
SELECT md5(to_jsonb(t)::text) AS fingerprint FROM orders
t WHERE order_id=ANY(CAST(:ids AS uuid[]))""",
                        {"ids": list(TARGET_ORDERS)},
                    )
                }
            elif table == "campaign_foundation_commands":
                hashes -= {
                    r["fingerprint"]
                    for r in rows(
                        db,
                        """
SELECT md5(to_jsonb(t)::text) AS fingerprint FROM
campaign_foundation_commands
t WHERE operation_key='policy'
""",
                    )
                }
            elif table == "creator_identity_observations":
                hashes = {
                    r["fingerprint"]
                    for r in rows(
                        db,
                        """
SELECT md5(to_jsonb(t)::text) AS fingerprint FROM
creator_identity_observations
t WHERE creator_user_id=ANY(CAST(:ids AS uuid[]))
""",
                        {"ids": list(TARGET_USERS)},
                    )
                }
            elif table == "creator_direct_binding_observations":
                hashes = {
                    r["fingerprint"]
                    for r in rows(
                        db,
                        """
SELECT md5(to_jsonb(t)::text) AS fingerprint FROM
creator_direct_binding_observations
t WHERE referred_user_id=ANY(CAST(:ids AS uuid[]))
""",
                        {"ids": list(TARGET_USERS)},
                    )
                }
            assert len(hashes) == target["rows"], (table, len(hashes))
            target["row_fingerprints"] = sorted(hashes)
            targets[table] = hashes
        coverage = rows(
            db,
            """SELECT *,md5(to_jsonb(c)::text) AS row_fingerprint FROM
creator_identity_coverage c""",
        )[0]
        plan["coverage_update"]["before"] = {
            key: coverage[key] for key in plan["coverage_update"]["before"]
        }
        plan["coverage_update"].update(
            after_profile_seed_count=1,
            after_profile_seed_hash=db.scalar(
                text(
                    f"""SELECT {PROFILE_HASH} FROM creator_identity_observations
WHERE source='canonical_profile_cutover' AND creator_user_id=CAST(:id
AS uuid)"""
                ),
                {"id": creator},
            ),
        )
        audit_hash = db.scalar(
            text(
                """
SELECT md5(to_jsonb(t)::text) FROM audit_log t WHERE id=CAST(:id
AS uuid)"""
            ),
            {"id": AUDIT_ID},
        )
        plan["audit_redaction"]["before_row_fingerprint"] = audit_hash
        money = _working_money(db, now, admin, creator)
    return dict(engine=engine, plan=plan, targets=targets, money=money, now=now)


def database_digest(engine, *, exclude_operations=False):
    result = {}
    with engine.connect() as db:
        for row in rows(
            db,
            """SELECT table_name FROM information_schema.tables WHERE
table_schema=current_schema() AND table_type='BASE TABLE'
ORDER BY table_name""",
        ):
            table = row["table_name"]
            where = (
                "WHERE entity_type<>'test_residual_cleanup'"
                if exclude_operations and table == "audit_log"
                else ""
            )
            documents = db.scalars(
                text(
                    f"""SELECT to_jsonb(t)::text FROM {quote(table)} t {where}
ORDER BY to_jsonb(t)::text"""
                )
            ).all()
            result[table] = hashlib.sha256(
                "\n".join(documents).encode()
            ).hexdigest()
    return result
