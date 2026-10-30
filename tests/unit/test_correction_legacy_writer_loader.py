"""Portable old-writer isolation; synthetic facts, no SQL execution."""

import builtins
import json
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "tests/fixtures/corrections/pre_approval_binding"
PREFIX = "_ugc_archived_correction_"
CANONICAL = (
    "ugc_bot.application.correction_ports",
    "ugc_bot.application.services.correction_service",
    "ugc_bot.infrastructure.db.repositories.corrections",
)
ARCHIVES = (
    "correction_ports.py.source",
    "correction_service.py.source",
    "corrections_repository.py.source",
    "domain_corrections.py.source",
    "correction_schema.py.source",
)
DEPENDENCIES = tuple(
    json.loads((ARCHIVE / "manifest.json").read_text())[
        "unchanged_dependencies_sha256"
    ]
)


@pytest.fixture(autouse=True)
def no_engines(monkeypatch):
    import sqlalchemy
    import sqlalchemy.engine
    import sqlalchemy.engine.create
    import sqlalchemy.ext.asyncio
    import sqlalchemy.ext.asyncio.engine

    def deny(*args, **kwargs):
        raise AssertionError("The archive loader must not construct engines")

    for owner, name in (
        (sqlalchemy, "create_engine"),
        (sqlalchemy.engine, "create_engine"),
        (sqlalchemy.engine.create, "create_engine"),
        (sqlalchemy.ext.asyncio, "create_async_engine"),
        (sqlalchemy.ext.asyncio.engine, "create_async_engine"),
    ):
        monkeypatch.setattr(owner, name, deny)


def private_modules():
    return {key for key in sys.modules if key.startswith(PREFIX)}


def request(ports):
    return ports.RequestSelectionRefund(
        actor_id=UUID(int=1),
        operation_key="archived-request",
        reason="Declared synthetic loader check",
        order_id=UUID(int=2),
        paid_item_ids=(UUID(int=3),),
        expected_source_hash="a" * 64,
    )


def copy_archive(destination):
    destination.mkdir()
    for name in (*ARCHIVES, "manifest.json"):
        shutil.copyfile(ARCHIVE / name, destination / name)
    return destination


@pytest.mark.asyncio
async def test_archived_commands_dispatch_without_replacing_current_modules():
    from tests.helpers.correction_legacy_writer import (
        archived_correction_writer,
    )
    from ugc_bot.application import correction_ports as current_ports
    from ugc_bot.application.services import correction_service

    before = {key: sys.modules.get(key) for key in CANONICAL}
    private_before = private_modules()
    import_before = builtins.__import__
    with archived_correction_writer() as writer:
        old = request(writer.ports)
        current = request(current_ports)
        repository = writer.repository.SqlAlchemyCorrectionRepository()
        # This old SQL routing branch returns before accessing its DB argument.
        assert await repository._routing(old, object()) == (
            UUID(int=2),
            None,
            (UUID(int=3),),
        )
        assert writer.ports.correction_command_hash(old) == (
            current_ports.correction_command_hash(current)
        )
        with pytest.raises(ValueError, match="^correction_command_invalid$"):
            writer.ports.correction_command_hash(current)
        with pytest.raises(ValueError, match="^correction_command_invalid$"):
            current_ports.correction_command_hash(old)
        # A current command cannot accidentally take the old Request branch.
        with pytest.raises(AttributeError, match="case_id"):
            await repository._routing(current, object())
        assert writer.service.RequestSelectionRefund is type(old)
        assert writer.service.CorrectionService is not (
            correction_service.CorrectionService
        )
        assert writer.repository.CorrectionScope is writer.ports.CorrectionScope
        assert asdict(old)["actor_id"] == UUID(int=1)
        assert writer.ports.CorrectionPrincipal is (
            current_ports.CorrectionPrincipal
        )
        assert len(private_modules() - private_before) == 4
        assert {key: sys.modules.get(key) for key in CANONICAL} == before
        assert builtins.__import__ is import_before
    assert private_modules() == private_before
    assert {key: sys.modules.get(key) for key in CANONICAL} == before
    assert builtins.__import__ is import_before


def test_nested_contexts_keep_independent_command_types_and_cleanup():
    from tests.helpers.correction_legacy_writer import (
        archived_correction_writer,
    )

    before = private_modules()
    with archived_correction_writer() as first:
        first_names = private_modules() - before
        with archived_correction_writer() as second:
            assert len(private_modules() - before) == 8
            assert first.ports.RequestSelectionRefund is not (
                second.ports.RequestSelectionRefund
            )
            with pytest.raises(ValueError, match="correction_command_invalid"):
                first.ports.correction_command_hash(request(second.ports))
        assert private_modules() - before == first_names
        assert first.ports.correction_command_hash(request(first.ports))
    assert private_modules() == before


@pytest.mark.asyncio
async def test_actual_archived_service_keeps_historical_early_intent_refusal():
    from tests.helpers.correction_legacy_writer import (
        archived_correction_writer,
    )

    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    actor, client, order, case, paid, payment, capture, invoice, intent = (
        UUID(int=i) for i in range(1, 10)
    )
    with archived_correction_writer() as writer:
        ports = writer.ports
        CapturedSelectionComponent = writer.domain.CapturedSelectionComponent
        CorrectionState = writer.domain.CorrectionState
        SelectionRefundBundle = writer.domain.SelectionRefundBundle
        bundle = SelectionRefundBundle(
            components=(
                CapturedSelectionComponent(
                    allocation_key="synthetic:selection",
                    payment_id=payment,
                    paid_item_id=paid,
                    gross_minor=50000,
                    currency="RUB",
                    selection_due_at=now - timedelta(days=1),
                    due_evidence_hash="a" * 64,
                ),
            )
        )
        scope = ports.CorrectionScope(
            actor_id=actor,
            prospective_user_ids=(actor, client),
            wallet_user_ids=(),
            order_id=order,
            client_id=client,
            case_id=case,
            source_hash="a" * 64,
            intent_id=invoice,
            capture_id=capture,
            payment_id=payment,
            captured_at=now - timedelta(days=2),
            quote_key="synthetic:quote",
            terms_reference="synthetic:terms",
            bundle=bundle,
            selected_paid_item_ids=(paid,),
        )
        facts = ports.CorrectionFacts(
            records=tuple(
                ports.CorrectionFact.from_values(kind, row)
                for kind, row in (
                    (
                        "cases",
                        dict(case_id=case, order_id=order, client_id=client),
                    ),
                    (
                        "requests",
                        dict(
                            request_id=UUID(int=10),
                            case_id=case,
                            order_id=order,
                            client_id=client,
                            paid_item_ids=[str(paid)],
                            source_hash="a" * 64,
                            bundle=[asdict(bundle.components[0])],
                        ),
                    ),
                    (
                        "intents",
                        dict(intent_id=intent, request_id=None),
                    ),
                )
            )
        )
        command = ports.ReviewSelectionRefund(
            actor_id=actor,
            operation_key="synthetic:review",
            reason="Declared synthetic archive discriminator",
            case_id=case,
            expected_version=2,
            expected_source_hash="a" * 64,
            decision="approve",
            evidence_reference="synthetic:evidence",
            evidence_hash="b" * 64,
        )
        service = writer.service.CorrectionService(
            object(), object(), SimpleNamespace(now=lambda: now)
        )
        with pytest.raises(
            ValueError, match="^correction_early_intent_binding_unavailable$"
        ):
            await service._review(
                command,
                dict(
                    scope=scope,
                    facts=facts,
                    state=CorrectionState(
                        case_id=case, version=2, source_hash="a" * 64
                    ),
                    consistent=True,
                    now=now,
                ),
            )
        with pytest.raises(ValueError, match="^correction_fact_invalid$"):
            ports.CorrectionFact.from_values("approvals", {})


@pytest.mark.parametrize("archive_name", ARCHIVES)
def test_changed_archived_source_is_refused_before_loading(
    tmp_path, archive_name
):
    from tests.helpers.correction_legacy_writer import (
        archived_correction_writer,
    )

    archive = copy_archive(tmp_path / "archive")
    changed = archive / archive_name
    changed.write_bytes(
        changed.read_bytes() + b"\nraise RuntimeError('tampered')\n"
    )
    before = private_modules()
    with (
        pytest.raises(ValueError, match="archived_correction_integrity"),
        archived_correction_writer(archive_dir=archive),
    ):
        pytest.fail("Tampered archived source executed")
    assert private_modules() == before


def test_changed_manifest_cannot_repin_changed_source(tmp_path):
    from tests.helpers.correction_legacy_writer import (
        archived_correction_writer,
    )

    archive = copy_archive(tmp_path / "archive")
    manifest = archive / "manifest.json"
    payload = json.loads(manifest.read_text())
    payload["source_files"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload))
    before = private_modules()
    with (
        pytest.raises(ValueError, match="archived_correction_integrity"),
        archived_correction_writer(archive_dir=archive),
    ):
        pytest.fail("Changed manifest trusted")
    assert private_modules() == before


@pytest.mark.parametrize("dependency", DEPENDENCIES)
def test_changed_pinned_dependency_is_refused(tmp_path, dependency):
    from tests.helpers.correction_legacy_writer import (
        archived_correction_writer,
    )

    for relative in DEPENDENCIES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    changed = tmp_path / dependency
    changed.write_bytes(changed.read_bytes() + b"\n# incompatible change\n")
    before = private_modules()
    with (
        pytest.raises(ValueError, match="archived_correction_integrity"),
        archived_correction_writer(repository_root=tmp_path),
    ):
        pytest.fail("Changed pinned dependency trusted")
    assert private_modules() == before


@pytest.mark.parametrize(
    "failed_import",
    ("ugc_bot.application.physical_proof_ports", "sqlalchemy"),
)
def test_import_failure_removes_already_registered_private_modules(
    monkeypatch, failed_import
):
    from tests.helpers import correction_legacy_writer as loader

    before = private_modules()
    canonical_before = {key: sys.modules.get(key) for key in CANONICAL}
    import_before = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == failed_import:
            raise ImportError("Declared dependency-import failure")
        return import_before(name, *args, **kwargs)

    # Replace this loader's forwarding boundary, never Python's import system.
    monkeypatch.setattr(loader, "_IMPORT", unavailable)
    with (
        pytest.raises(ImportError, match="Declared dependency-import failure"),
        loader.archived_correction_writer(),
    ):
        pytest.fail("Unavailable dependency ignored")
    assert private_modules() == before
    assert {key: sys.modules.get(key) for key in CANONICAL} == canonical_before
    assert builtins.__import__ is import_before


def test_caller_failure_also_releases_private_module_registrations():
    from tests.helpers.correction_legacy_writer import (
        archived_correction_writer,
    )

    before = private_modules()
    with (
        pytest.raises(RuntimeError, match="Declared caller failure"),
        archived_correction_writer(),
    ):
        assert len(private_modules() - before) == 4
        raise RuntimeError("Declared caller failure")
    assert private_modules() == before
