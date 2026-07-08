"""Arq worker (Phase 1): async fact extraction after each chat exchange.

Run: uv run arq core.worker.WorkerSettings
Uses the cheap-tier model to distill durable facts from the latest exchange into
persistent memory. Failures are logged, never fatal — chat must not depend on it.
"""

import json
import logging
import uuid

from arq import cron
from arq.connections import RedisSettings

from core import secrets
from core.config import settings
from core.db import SessionFactory
from core.inference.fireworks import FireworksClient, FireworksError
from core.memory import MemoryStore
from core.reporter import generate_report

logger = logging.getLogger("jardo.worker")

_EXTRACTION_PROMPT = """\
You extract DURABLE facts and PREFERENCES about the OWNER from what the owner
said. Return STRICT JSON: {"facts": ["..."]}.

Include only stable, reusable facts about the OWNER — especially:
- how they like to work (tools, languages, frameworks, workflow, coding style),
- their ongoing projects or goals,
- standing constraints, requirements, or biography they state.

NEVER include (these are the common mistakes):
- anything about the assistant, "Jardo", or this app itself,
- one-off or transient details (a single command, a file edited today, "removed X"),
- conversation mechanics or the current task's step-by-step,
- secrets or credentials,
- anything you are inferring rather than something the owner actually stated.

Prefer general preferences ("prefers pnpm", "wants tests before committing") over
specific events. If there are no durable owner facts, return {"facts": []}."""


async def extract_facts(ctx: dict, conversation_id: str) -> int:
    api_key = secrets.read_secret(secrets.FIREWORKS_API_KEY)
    if not api_key:
        logger.warning("extract_facts skipped: no API key in Keychain")
        return 0

    async with SessionFactory() as session:
        store = MemoryStore(session)
        owner = await store.get_owner()
        if owner is None:
            return 0
        exchange = await store.recent_messages(uuid.UUID(conversation_id), 4)
        # Only the OWNER's words describe the owner — the assistant's self-talk
        # (e.g. "I'm Jardo, chief of staff…") must never become a "fact".
        owner_said = [m.content for m in exchange if m.role == "user"]
        if not owner_said:
            return 0
        transcript = "\n".join(f"owner: {c}" for c in owner_said)

        client = FireworksClient(api_key, settings.fireworks_base_url)
        try:
            result = await client.chat(
                settings.extraction_model,
                [
                    {"role": "system", "content": _EXTRACTION_PROMPT},
                    {"role": "user", "content": transcript},
                ],
                max_tokens=512,
                temperature=0.0,
            )
            facts = json.loads(result.content).get("facts", [])
        except (FireworksError, json.JSONDecodeError) as exc:
            logger.warning("extract_facts failed (non-fatal): %s", exc)
            return 0

        stored = 0
        for fact in facts:
            if isinstance(fact, str) and fact.strip():
                if await store.add_fact(owner.id, fact.strip(), source="worker"):
                    stored += 1
        if stored:
            await store.audit("worker", "memory.facts_extracted", {"count": stored})
        await session.commit()
        return stored


async def _owner_honorific() -> str:
    async with SessionFactory() as session:
        owner = await MemoryStore(session).get_owner()
        return owner.pronoun_style if owner else "sir"


async def build_report(ctx: dict, period: str) -> str:
    """Cron-driven report generation (spec §4.4)."""
    honorific = await _owner_honorific()
    async with SessionFactory() as session:
        report = await generate_report(session, period, honorific=honorific)
        await MemoryStore(session).audit("reporter", "report.generated",
                                         {"period": period, "report_id": str(report.id)})
        await session.commit()
        logger.info("generated %s report %s", period, report.id)
        return str(report.id)


async def hourly_report(ctx: dict) -> str:
    return await build_report(ctx, "hourly")


async def daily_report(ctx: dict) -> str:
    return await build_report(ctx, "daily")


async def weekly_report(ctx: dict) -> str:
    return await build_report(ctx, "weekly")


class WorkerSettings:
    functions = [extract_facts, build_report]
    # Report cadence (spec §4.4). Times are UTC.
    cron_jobs = [
        cron(hourly_report, minute=0),
        cron(daily_report, hour=7, minute=5),          # morning summary
        cron(weekly_report, weekday="mon", hour=7, minute=10),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
