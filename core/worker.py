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
You extract durable personal facts from a conversation exchange.
Return STRICT JSON: {"facts": ["..."]}. Include only stable, useful facts about
the owner (preferences, projects, constraints, biography). If none, return
{"facts": []}. Never include secrets, credentials, or one-off task details."""


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
        exchange = await store.recent_messages(uuid.UUID(conversation_id), 2)
        transcript = "\n".join(f"{m.role}: {m.content}" for m in exchange)

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
