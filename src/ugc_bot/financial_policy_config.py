"""Preview or explicitly publish environment-backed immutable refund rules."""

import argparse
import asyncio
import json
from datetime import datetime
from uuid import UUID

from ugc_bot.application.services.financial_policy_publication import (
    FinancialPolicyDraft,
    FinancialPolicyPublicationService,
)
from ugc_bot.config import AppConfig, load_config
from ugc_bot.domain.financial import utc


async def _publish(config: AppConfig, draft: FinancialPolicyDraft, actor: UUID):
    # Preview never constructs a container, engine, connection or transaction.
    from ugc_bot.container import Container
    from ugc_bot.infrastructure.clock import SystemClock
    from ugc_bot.infrastructure.db.repositories.financial_policy import (
        SqlAlchemyFinancialPolicyRepository,
    )

    container = Container(config)
    try:
        transactions = container.transaction_manager
        if transactions is None:
            raise ValueError("policy_database_required")
        return await FinancialPolicyPublicationService(
            SqlAlchemyFinancialPolicyRepository(), transactions, SystemClock()
        ).publish(draft, actor_id=actor)
    finally:
        await container.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--approved-by", required=True, type=UUID)
    parser.add_argument("--effective-from", required=True)
    parser.add_argument("--terms-reference", required=True)
    parser.add_argument(
        "--allowed-client", required=True, action="append", type=UUID
    )
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config()
        draft = FinancialPolicyDraft.from_environment(
            config.financial,
            version=args.version,
            effective_from=utc(datetime.fromisoformat(args.effective_from)),
            allowed_clients=frozenset(args.allowed_client),
            terms_reference=args.terms_reference,
        )
    except ValueError:
        parser.error("invalid_refund_policy_configuration")
    result = draft.to_document() | {"published": False}
    if args.publish:
        try:
            policy = asyncio.run(_publish(config, draft, args.approved_by))
        except PermissionError:
            parser.error("active_admin_required")
        except ValueError:
            parser.error("policy_publication_rejected")
        result.update(
            published=True,
            approved_by=str(args.approved_by),
            approved_at=policy.approved_at.isoformat(),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
