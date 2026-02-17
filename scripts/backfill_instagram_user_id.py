#!/usr/bin/env python3
"""Backfill instagram_user_id for verified bloggers.

For profiles that have instagram_url but no instagram_user_id (e.g. verified
before the field existed). Requires a mapping username -> instagram_user_id
(e.g. from webhook logs). Without --mapping only lists profiles and can
write a template CSV for manual fill.
"""

import argparse
import asyncio
import csv
import sys
from pathlib import Path

from sqlalchemy import or_, select

from ugc_bot.config import load_config
from ugc_bot.container import repository_factory
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.enums import AudienceGender, BloggerGender, WorkFormat
from ugc_bot.infrastructure.db.models import BloggerProfileModel
from ugc_bot.infrastructure.db.session import create_session_factory


def extract_username_from_instagram_url(instagram_url: str) -> str | None:
    """Extract username from instagram_url (instagram.com/user or @user)."""
    url = (instagram_url or "").lower().strip()
    if not url:
        return None
    if "instagram.com/" in url:
        parts = url.split("instagram.com/")
        if len(parts) > 1:
            return parts[-1].split("/")[0].split("?")[0].strip()
        return None
    return url.replace("@", "").strip()


def load_username_to_id_mapping(path: Path) -> dict[str, str]:
    """Load mapping username -> instagram_user_id from CSV.

    CSV must have header. Columns: username, instagram_user_id.
    Username is normalized to lowercase for lookup.
    """
    mapping: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return mapping
        header = [h.strip().lower() for h in header]
        username_col = "username" in header
        id_col = (
            "instagram_user_id" in header or "instagram user id" in header
        )
        if not username_col or not id_col:
            idx_username = 0
            idx_id = 1
        else:
            idx_username = header.index("username")
            idx_id = (
                header.index("instagram_user_id")
                if "instagram_user_id" in header
                else header.index("instagram user id")
            )
        for row in reader:
            if len(row) <= max(idx_username, idx_id):
                continue
            username = (row[idx_username] or "").strip().lower()
            ig_id = (row[idx_id] or "").strip()
            if username and ig_id:
                mapping[username] = ig_id
    return mapping


def _model_to_blogger_profile(
    model: BloggerProfileModel, instagram_user_id: str
) -> BloggerProfile:
    """Build BloggerProfile from ORM model with given instagram_user_id."""
    ag = model.audience_gender
    wf = model.work_format
    if isinstance(ag, str):
        ag = AudienceGender(ag)
    if isinstance(wf, str):
        wf = WorkFormat(wf)
    bg = getattr(model, "blogger_gender", None)
    if bg is not None and isinstance(bg, str):
        bg = BloggerGender(bg)
    return BloggerProfile(
        user_id=model.user_id,
        instagram_url=model.instagram_url,
        confirmed=model.confirmed,
        city=model.city,
        topics=model.topics,
        audience_gender=ag,
        audience_age_min=model.audience_age_min,
        audience_age_max=model.audience_age_max,
        audience_geo=model.audience_geo,
        price=float(model.price),
        barter=model.barter,
        work_format=wf,
        updated_at=model.updated_at,
        wanted_to_change_terms_count=getattr(
            model, "wanted_to_change_terms_count", 0
        ),
        blogger_gender=bg,
        instagram_user_id=instagram_user_id,
        instagram_followers_count=getattr(
            model, "instagram_followers_count", None
        ),
        instagram_media_count=getattr(model, "instagram_media_count", None),
        instagram_follows_count=getattr(
            model, "instagram_follows_count", None
        ),
        instagram_biography=getattr(model, "instagram_biography", None),
        instagram_username=getattr(model, "instagram_username", None),
        instagram_stats_fetched_at=getattr(
            model, "instagram_stats_fetched_at", None
        ),
    )


async def run(
    dry_run: bool,
    mapping_path: Path | None,
    output_csv: Path | None,
) -> int:
    """Find verified bloggers without instagram_user_id; optionally backfill."""
    config = load_config()
    if not config.db.database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    repos = repository_factory.build_repos(session_factory)
    blogger_repo = repos["blogger_repo"]

    username_to_id = (
        load_username_to_id_mapping(mapping_path) if mapping_path else {}
    )

    async with session_factory() as session:
        stmt = select(BloggerProfileModel).where(
            BloggerProfileModel.confirmed.is_(True),
            or_(
                BloggerProfileModel.instagram_user_id.is_(None),
                BloggerProfileModel.instagram_user_id == "",
            ),
            BloggerProfileModel.instagram_url.isnot(None),
            BloggerProfileModel.instagram_url != "",
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

    if not rows:
        print("No verified bloggers without instagram_user_id found.")
        return 0

    candidates = [
        (m, extract_username_from_instagram_url(m.instagram_url))
        for m in rows
    ]

    if output_csv and not mapping_path:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                ["user_id", "instagram_url", "username", "instagram_user_id"]
            )
            for model, username in candidates:
                w.writerow([
                    str(model.user_id),
                    model.instagram_url,
                    username or "",
                    "",
                ])
        print(
            f"Wrote {len(candidates)} rows to {output_csv}. "
            f"Fill instagram_user_id and run with --mapping {output_csv}"
        )
        return 0

    updated = 0
    for model, username in candidates:
        ig_id = (
            username_to_id.get(username.lower())
            if username and username_to_id
            else None
        )

        if ig_id and not dry_run:
            profile = _model_to_blogger_profile(model, ig_id)
            async with session_factory() as session:
                await blogger_repo.save(profile, session=session)
                await session.commit()
            updated += 1
            print(
                f"Updated user_id={model.user_id} username={username} "
                f"-> instagram_user_id={ig_id}"
            )
        else:
            if dry_run or not username_to_id:
                u = model.user_id
                url = model.instagram_url
                un = username or "(none)"
                print(f"user_id={u} instagram_url={url} username={un}")
            if dry_run and ig_id:
                updated += 1

    print(
        f"Verified bloggers without instagram_user_id: {len(candidates)}. "
        f"Updated: {updated} (dry_run={dry_run})"
    )
    if dry_run and updated > 0:
        print(
            "Run without --dry-run and with --mapping <file> to apply."
        )
    return 0


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Backfill instagram_user_id for verified bloggers that have "
            "instagram_url but no instagram_user_id. Requires a CSV mapping "
            "username -> instagram_user_id (e.g. from webhook logs)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List only, or with --mapping show what would be updated.",
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        metavar="FILE",
        help=(
            "CSV with columns: username, instagram_user_id. "
            "Used to set instagram_user_id."
        ),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        metavar="FILE",
        help=(
            "Write template CSV: user_id, instagram_url, username, "
            "empty instagram_user_id for manual fill."
        ),
    )
    args = parser.parse_args()
    return asyncio.run(
        run(
            dry_run=args.dry_run,
            mapping_path=args.mapping,
            output_csv=args.output_csv,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
