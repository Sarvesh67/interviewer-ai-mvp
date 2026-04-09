#!/usr/bin/env python3
"""
One-time migration script: import existing JSON files into PostgreSQL.

Usage:
    # Dry-run (default) — shows what would be imported, writes nothing:
    python db/migrate_from_files.py

    # Actually write to the database:
    python db/migrate_from_files.py --apply

    # Specify a custom user email for all imported interviews
    # (since the old JSON files don't store the authenticated user):
    python db/migrate_from_files.py --apply --user-email you@example.com

The script reads:
    interview_store/interview_*.json       — interview metadata + questions
    interview_store/*_api.json             — newer format (if any)
    interview_store/*_answers.json         — agent-persisted answers (if any)
    uploads/*_report.json                  — generated reports
    uploads/*_report.txt                   — formatted text reports
"""
import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from db.models import Base, User, Interview, Report

logging.basicConfig(level=logging.INFO, format="%(levelname)-5s  %(message)s")
logger = logging.getLogger("migrate")

INTERVIEW_STORE = ROOT / "interview_store"
UPLOADS = ROOT / "uploads"

# Matches both formats:
#   interview_d8ccce0084b5.json        (old — full interview dump)
#   interview_d8ccce0084b5_api.json    (newer — API-persisted subset)
INTERVIEW_FILE_RE = re.compile(r"^(interview_[a-f0-9]{12})(?:_api)?\.json$")


def _discover_interviews() -> dict[str, dict]:
    """
    Scan interview_store/ and uploads/ to build a map of
    interview_id → {interview_path, answers_path, report_json_path, report_txt_path}.
    """
    discovered: dict[str, dict] = {}

    if INTERVIEW_STORE.is_dir():
        for f in sorted(INTERVIEW_STORE.iterdir()):
            m = INTERVIEW_FILE_RE.match(f.name)
            if m:
                iid = m.group(1)
                discovered.setdefault(iid, {})["interview_path"] = f

            if f.name.endswith("_answers.json"):
                iid = f.name.replace("_answers.json", "")
                discovered.setdefault(iid, {})["answers_path"] = f

    if UPLOADS.is_dir():
        for f in sorted(UPLOADS.iterdir()):
            if f.name.endswith("_report.json"):
                iid = f.name.replace("_report.json", "")
                discovered.setdefault(iid, {})["report_json_path"] = f
            elif f.name.endswith("_report.txt"):
                iid = f.name.replace("_report.txt", "")
                discovered.setdefault(iid, {})["report_txt_path"] = f

    return discovered


def _parse_interview_file(path: Path) -> dict:
    """Parse an interview JSON file (old or new format) into a normalised dict."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # New _api.json format has top-level keys: domain_knowledge, questions, candidate_info, ...
    # Old format has: job_description.domain_knowledge, questions, candidate_info, ...
    if "job_description" in raw:
        # Old format — domain_knowledge is nested inside job_description
        jd = raw["job_description"]
        domain_knowledge = jd.get("domain_knowledge", {})
        job_title = jd.get("title", "")
    else:
        # New _api.json format
        domain_knowledge = raw.get("domain_knowledge", {})
        job_title = raw.get("job_title", "")

    candidate_info = raw.get("candidate_info", {})

    return {
        "domain_knowledge": domain_knowledge,
        "questions": raw.get("questions", []),
        "candidate_info": candidate_info,
        "avatar_id": raw.get("avatar_id"),
        "job_title": job_title or candidate_info.get("position", "Unknown"),
        "candidate_name": candidate_info.get("name", "Unknown"),
        "candidate_email": candidate_info.get("email", "").lower(),
        "user_email": raw.get("user_email"),  # only present in _api.json
        "status": raw.get("status", "completed"),
        "created_at": raw.get("created_at"),
    }


async def migrate(*, apply: bool, user_email: str | None):
    discovered = _discover_interviews()

    if not discovered:
        logger.info("No interview files found in %s — nothing to migrate.", INTERVIEW_STORE)
        return

    logger.info("Discovered %d interview(s) to migrate.", len(discovered))

    if not apply:
        for iid, paths in discovered.items():
            parts = []
            if "interview_path" in paths:
                parts.append("interview")
            if "answers_path" in paths:
                parts.append("answers")
            if "report_json_path" in paths:
                parts.append("report")
            logger.info("  %s  [%s]", iid, ", ".join(parts))
        logger.info("")
        logger.info("Dry-run complete.  Re-run with --apply to write to the database.")
        return

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        # Collect unique user emails across all interviews
        user_cache: dict[str, User] = {}
        imported = 0
        skipped = 0

        for iid, paths in discovered.items():
            # Check if already imported
            existing = await db.execute(select(Interview).where(Interview.id == iid))
            if existing.scalar_one_or_none() is not None:
                logger.info("  SKIP  %s  (already in database)", iid)
                skipped += 1
                continue

            # Parse interview data
            interview_path = paths.get("interview_path")
            if not interview_path:
                logger.warning("  SKIP  %s  (no interview JSON found)", iid)
                skipped += 1
                continue

            data = _parse_interview_file(interview_path)

            # Determine the owner email — always lowercase to match the DB index
            email = (data["user_email"] or user_email or data["candidate_email"] or "migrated@localhost").lower()

            # Get or create user
            if email not in user_cache:
                result = await db.execute(select(User).where(User.email == email))
                user = result.scalar_one_or_none()
                if user is None:
                    user = User(email=email, name=email.split("@")[0])
                    db.add(user)
                    await db.flush()
                    logger.info("  USER  Created user %s", email)
                user_cache[email] = user
            user = user_cache[email]

            # Parse answers (if any)
            answers = None
            answers_path = paths.get("answers_path")
            if answers_path and answers_path.exists():
                try:
                    answers_raw = json.loads(answers_path.read_text())
                    answers = answers_raw.get("answers", [])
                except Exception as e:
                    logger.warning("  WARN  Failed to parse answers for %s: %s", iid, e)

            # Determine created_at
            created_at = None
            if data["created_at"]:
                try:
                    created_at = datetime.fromisoformat(data["created_at"])
                except (ValueError, TypeError):
                    pass
            if created_at is None:
                # Fall back to file modification time
                stat = interview_path.stat()
                created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            # Create interview row
            interview = Interview(
                id=iid,
                user_id=user.id,
                job_title=data["job_title"],
                candidate_name=data["candidate_name"],
                candidate_email=data["candidate_email"],
                domain_knowledge=data["domain_knowledge"],
                questions=data["questions"],
                candidate_info=data["candidate_info"],
                avatar_id=data["avatar_id"],
                status=data["status"],
                answers=answers,
                created_at=created_at,
            )
            db.add(interview)
            await db.flush()

            # Import report (if any)
            report_json_path = paths.get("report_json_path")
            report_txt_path = paths.get("report_txt_path")
            if report_json_path and report_json_path.exists():
                try:
                    report_data = json.loads(report_json_path.read_text())
                    report_text = None
                    if report_txt_path and report_txt_path.exists():
                        report_text = report_txt_path.read_text()

                    report = Report(
                        interview_id=iid,
                        report_data=report_data,
                        report_text=report_text,
                        overall_score=report_data.get("overall_score"),
                        recommendation=report_data.get("recommendation"),
                    )
                    db.add(report)
                    logger.info("  OK    %s  (interview + report)", iid)
                except Exception as e:
                    logger.warning("  WARN  Report parse failed for %s: %s", iid, e)
                    logger.info("  OK    %s  (interview only)", iid)
            else:
                logger.info("  OK    %s  (interview only, no report)", iid)

            imported += 1

        await db.commit()

    await engine.dispose()
    logger.info("")
    logger.info("Migration complete: %d imported, %d skipped.", imported, skipped)


def main():
    parser = argparse.ArgumentParser(
        description="Migrate existing JSON interview data into PostgreSQL."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write to the database (default is dry-run).",
    )
    parser.add_argument(
        "--user-email",
        type=str,
        default=None,
        help="Owner email for imported interviews (used when the JSON file has no user_email field).",
    )
    args = parser.parse_args()
    asyncio.run(migrate(apply=args.apply, user_email=args.user_email))


if __name__ == "__main__":
    main()
