"""Pure authority rules over declared synthetic facts; no SQL acceptance.

Rows below model immutable table facts only. No engine, connection, session
binding, provider fact or bank mapping is created by these tests.
"""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.physical_proof_ports import (
    PhysicalProofIdentity,
    PhysicalProofOwner,
)

ACTOR, REQUEST, EXECUTION, OUTCOME, COMMAND = (UUID(int=i) for i in range(1, 6))


class Clock:
    def now(self):
        return datetime(2026, 10, 24, tzinfo=timezone.utc)


def repository(source="synthetic:source", account="synthetic:account"):
    from ugc_bot.infrastructure.db.repositories.physical_proofs import (
        SqlAlchemyPhysicalProofRepository,
    )

    return SqlAlchemyPhysicalProofRepository(source, account, Clock())


def identity(**changes):
    return PhysicalProofIdentity(
        **dict(
            source="synthetic:source",
            account="synthetic:account",
            direction="outgoing",
            reference="synthetic:reference",
        )
        | changes
    )


def owner(**changes):
    return PhysicalProofOwner(
        **dict(
            producer="payout",
            intent_id=EXECUTION,
            observation_id=OUTCOME,
            command_id=COMMAND,
        )
        | changes
    )


def history():
    # Synthetic immutable paid-but-unapplied P01 rows. Unsupported economics
    # deliberately remain physical ownership; recipient is no namespace input.
    return dict(
        outcomes=[
            dict(
                outcome_id=OUTCOME,
                execution_id=EXECUTION,
                request_id=REQUEST,
                actor_id=ACTOR,
                status="paid",
                bank_account="synthetic:account",
                bank_reference="synthetic:reference",
                applied=False,
                amount_minor=-1,
                currency="USD",
                review_reason="emergency_stop",
            )
        ],
        settlements=[],
        intents=[
            dict(
                execution_id=EXECUTION,
                request_id=REQUEST,
                bank_account="different-expected-account",
            )
        ],
        commands=[
            dict(
                command_id=COMMAND,
                actor_id=ACTOR,
                action="RecordPayoutResult",
                result=dict(
                    request_id=str(REQUEST),
                    version=3,
                    state="unknown",
                    execution_id=str(UUID(int=66)),
                ),
            )
        ],
        events=[
            dict(
                event_id=UUID(int=6),
                request_id=REQUEST,
                version=3,
                actor_id=ACTOR,
                action="bank_result",
                details=dict(outcome_id=str(OUTCOME)),
            )
        ],
    )


def test_bounded_failure_text_cannot_leak_proof_data():
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofConflict,
        PhysicalProofUnavailable,
    )

    for error, code in (
        (PhysicalProofUnavailable, "physical_proof_unavailable"),
        (PhysicalProofConflict, "physical_proof_owner_conflict"),
    ):
        assert str(error()) == code and error().args == (code,)
        with pytest.raises(TypeError):
            error("private-account")


def test_configured_resolution_trims_without_inventing_a_namespace():
    repo = repository(" synthetic:source ", " synthetic:account ")
    assert (
        repo.resolve_manual_identity(
            " synthetic:account ", " synthetic:reference ", direction="outgoing"
        )
        == identity()
    )
    assert repo.resolve_manual_identity(
        "synthetic:account", "synthetic:reference", direction="incoming"
    ) == identity(direction="incoming")


@pytest.mark.parametrize(
    "source,account,label,reference,direction",
    [
        ("", "synthetic:account", "synthetic:account", "r", "outgoing"),
        ("x" * 257, "synthetic:account", "synthetic:account", "r", "outgoing"),
        ("synthetic:source", "", "", "r", "outgoing"),
        ("synthetic:source", "x" * 257, "x" * 257, "r", "outgoing"),
        ("synthetic:source", "synthetic:account", "unknown", "r", "outgoing"),
        (
            "synthetic:source",
            "synthetic:account",
            "synthetic:account",
            " ",
            "outgoing",
        ),
        (
            "synthetic:source",
            "synthetic:account",
            "synthetic:account",
            "x" * 4001,
            "outgoing",
        ),
        (
            "synthetic:source",
            "synthetic:account",
            "synthetic:account",
            "r",
            "sideways",
        ),
    ],
)
def test_unrecognized_identity_is_unavailable(
    source, account, label, reference, direction
):
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )

    with pytest.raises(
        PhysicalProofUnavailable, match="^physical_proof_unavailable$"
    ):
        repository(source, account).resolve_manual_identity(
            label, reference, direction=direction
        )


def test_full_identity_key_is_unambiguous_and_hashes_exact_accepted_encoding():
    import hashlib

    from ugc_bot.infrastructure.db.repositories.physical_proofs import _key_hash

    a = identity(source="a:b", account="c", reference="雪:r")
    b = identity(source="a", account="b:c", reference="雪:r")
    assert a.key != b.key and _key_hash(a) != _key_hash(b)
    assert _key_hash(a) == hashlib.sha256(a.key.encode("utf-8")).hexdigest()
    assert _key_hash(identity()) != _key_hash(identity(direction="incoming"))


def test_unapplied_history_uses_actual_execution_account_and_command():
    facts = history()
    assert repository()._historical_owners(identity(), **facts) == (owner(),)
    facts["outcomes"][0]["applied"] = True
    facts["settlements"] = [
        dict(
            outcome_id=OUTCOME,
            execution_id=EXECUTION,
            request_id=REQUEST,
            bank_account="synthetic:account",
            bank_reference="synthetic:reference",
        )
    ]
    assert repository()._historical_owners(identity(), **facts) == (owner(),)


def test_direct_outcome_receipt_retains_real_command_without_false_event():
    facts = history()
    facts["events"] = []
    facts["commands"][0]["result"] = dict(
        request_id=str(REQUEST),
        version=None,
        state="unavailable",
        outcome_id=str(OUTCOME),
        applied=False,
    )
    assert repository()._historical_owners(identity(), **facts) == (owner(),)


@pytest.mark.parametrize("kind", ["commands", "events", "intents"])
def test_missing_historical_linkage_never_means_unused(kind):
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )

    facts = history()
    facts[kind] = []
    with pytest.raises(PhysicalProofUnavailable):
        repository()._historical_owners(identity(), **facts)


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("commands", "action", "ReviewPayout"),
        ("commands", "actor_id", UUID(int=99)),
        ("events", "action", "approve"),
        ("events", "actor_id", UUID(int=99)),
        ("events", "request_id", UUID(int=99)),
        ("intents", "request_id", UUID(int=99)),
        ("outcomes", "bank_account", "unknown-account"),
        ("outcomes", "execution_id", UUID(int=99)),
    ],
)
def test_invalid_historical_scope_is_unavailable(kind, field, value):
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )

    facts = history()
    facts[kind][0][field] = value
    with pytest.raises(PhysicalProofUnavailable):
        repository()._historical_owners(identity(), **facts)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "3"),
        ("version", True),
        ("request_id", REQUEST),
        ("request_id", str(UUID(int=99))),
    ],
)
def test_receipt_json_types_and_scope_are_exact(field, value):
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )

    facts = history()
    facts["commands"][0]["result"][field] = value
    with pytest.raises(PhysicalProofUnavailable):
        repository()._historical_owners(identity(), **facts)


@pytest.mark.parametrize("kind", ["commands", "events"])
def test_ambiguous_historical_attribution_never_fabricates_an_owner(kind):
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )

    facts = history()
    other = deepcopy(facts[kind][0])
    other["command_id" if kind == "commands" else "event_id"] = UUID(int=99)
    facts[kind].append(other)
    with pytest.raises(PhysicalProofUnavailable):
        repository()._historical_owners(identity(), **facts)


def test_nonpaid_history_is_not_a_paid_proof_but_orphan_settlement_blocks():
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )

    facts = history()
    facts["outcomes"][0]["status"] = "unknown"
    assert repository()._historical_owners(identity(), **facts) == ()
    facts["settlements"] = [
        dict(
            outcome_id=UUID(int=88),
            request_id=REQUEST,
            execution_id=EXECUTION,
            bank_account="synthetic:account",
            bank_reference="synthetic:reference",
        )
    ]
    with pytest.raises(PhysicalProofUnavailable):
        repository()._historical_owners(identity(), **facts)
    assert (
        repository()._historical_owners(
            identity(direction="incoming"), **history()
        )
        == ()
    )


def test_original_owner_replays_by_intent_and_conflicts_never_reassign():
    from ugc_bot.application.physical_proof_ports import PhysicalProofConflict
    from ugc_bot.infrastructure.db.repositories.physical_proofs import (
        _existing_owner,
        _merge_owners,
    )

    original = owner()
    repeat = owner(observation_id=UUID(int=77), command_id=UUID(int=78))
    assert _existing_owner((original,), repeat) is original
    assert _existing_owner((), repeat) is None
    assert _merge_owners((original,), (repeat,)) == (original,)
    for foreign in (owner(producer="refund"), owner(intent_id=UUID(int=99))):
        with pytest.raises(PhysicalProofConflict):
            _existing_owner((original,), foreign)
        with pytest.raises(PhysicalProofConflict):
            _existing_owner((foreign,), original)
        with pytest.raises(PhysicalProofConflict):
            _existing_owner((original, foreign), original)


def test_claim_hash_hit_validates_full_identity_and_actual_owner_ids():
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )
    from ugc_bot.infrastructure.db.repositories.physical_proofs import (
        _claim_row_owner,
        _key_hash,
    )

    row = dict(
        claim_id=UUID(int=6),
        source="synthetic:source",
        account="synthetic:account",
        direction="outgoing",
        reference="synthetic:reference",
        key_hash=_key_hash(identity()),
        producer="payout",
        intent_id=EXECUTION,
        observation_id=OUTCOME,
        command_id=COMMAND,
    )
    assert _claim_row_owner(identity(), row) == owner()
    for change in (
        dict(reference="different"),
        dict(claim_id=UUID(int=0)),
        dict(command_id=UUID(int=0)),
        dict(key_hash="0" * 64),
        dict(producer="unknown"),
    ):
        with pytest.raises(PhysicalProofUnavailable):
            _claim_row_owner(identity(), row | change)


@pytest.mark.asyncio
async def test_unconnected_or_inactive_sessions_cannot_claim_or_inspect_sql():
    from sqlalchemy.ext.asyncio import AsyncSession

    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )

    repo = repository()
    async with AsyncSession() as unbound:
        for session in (None, object(), unbound):
            with pytest.raises(PhysicalProofUnavailable):
                await repo.lock(identity(), session=session)
            with pytest.raises(PhysicalProofUnavailable):
                await repo.owners(identity(), session=session)
            with pytest.raises(PhysicalProofUnavailable):
                await repo.claim(identity(), owner(), session=session)
        async with unbound.begin():
            with pytest.raises(PhysicalProofUnavailable):
                await repo.claim(identity(), owner(), session=unbound)


def test_multiple_historical_executions_remain_conflicting_owners():
    from ugc_bot.application.physical_proof_ports import PhysicalProofConflict
    from ugc_bot.infrastructure.db.repositories.physical_proofs import (
        _existing_owner,
    )

    facts = history()
    second = deepcopy(history())
    second["outcomes"][0].update(
        outcome_id=UUID(int=17),
        execution_id=UUID(int=16),
        request_id=UUID(int=18),
        recipient_id=UUID(int=99),
    )
    second["intents"][0].update(
        execution_id=UUID(int=16), request_id=UUID(int=18)
    )
    second["commands"][0].update(
        command_id=UUID(int=19),
        result=dict(request_id=str(UUID(int=18)), version=3),
    )
    second["events"][0].update(
        event_id=UUID(int=20),
        request_id=UUID(int=18),
        details=dict(outcome_id=str(UUID(int=17))),
    )
    for kind in facts:
        facts[kind].extend(second[kind])
    actual = repository()._historical_owners(identity(), **facts)
    assert actual == (
        owner(),
        owner(
            intent_id=UUID(int=16),
            observation_id=UUID(int=17),
            command_id=UUID(int=19),
        ),
    )
    with pytest.raises(PhysicalProofConflict):
        _existing_owner(actual, owner())


def test_same_execution_observations_collapse_to_actual_deterministic_ids():
    facts = history()
    second = deepcopy(history())
    second["outcomes"][0]["outcome_id"] = UUID(int=17)
    second["commands"][0].update(
        command_id=UUID(int=19), result=dict(request_id=str(REQUEST), version=4)
    )
    second["events"][0].update(
        event_id=UUID(int=20),
        version=4,
        details=dict(outcome_id=str(UUID(int=17))),
    )
    for kind in ("outcomes", "commands", "events"):
        facts[kind].extend(second[kind])
    assert repository()._historical_owners(identity(), **facts) == (owner(),)


def test_other_action_receipt_reusing_a_view_version_is_not_attribution():
    facts = history()
    other = deepcopy(facts["commands"][0])
    other.update(command_id=UUID(int=77), action="escalate")
    facts["commands"].append(other)
    assert repository()._historical_owners(identity(), **facts) == (owner(),)


def test_direct_other_outcome_does_not_borrow_an_ordinary_event_version():
    facts = history()
    observed = deepcopy(facts["outcomes"][0])
    observed["outcome_id"] = UUID(int=77)
    facts["outcomes"].append(observed)
    direct = deepcopy(facts["commands"][0])
    direct.update(
        command_id=UUID(int=78),
        result=dict(
            request_id=str(REQUEST),
            version=3,
            state="unavailable",
            outcome_id=str(UUID(int=77)),
            applied=False,
        ),
    )
    facts["commands"].append(direct)
    assert repository()._historical_owners(identity(), **facts) == (owner(),)


@pytest.mark.parametrize("result", [None, [], "not-an-object", 3])
def test_nonobject_historical_receipt_is_unavailable(result):
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )

    facts = history()
    facts["commands"][0]["result"] = result
    with pytest.raises(PhysicalProofUnavailable):
        repository()._historical_owners(identity(), **facts)


def test_different_reference_settlement_does_not_own_this_key():
    facts = history()
    facts["settlements"].append(dict(bank_reference="different-reference"))
    assert repository()._historical_owners(identity(), **facts) == (owner(),)
