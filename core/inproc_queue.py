"""In-process task queue — the embedded (SQLite) build's replacement for Redis/Arq.

The server setup runs an out-of-process Arq worker against Redis. The
self-contained desktop app can't require services, so here jobs run inside the
core process: `enqueue_job` fires the function as a background asyncio task, and a
lightweight scheduler drives the report crons. Same call sites, no Redis.

Failures are logged, never propagated — background work must not break the request
that scheduled it (mirrors the Arq worker's non-fatal contract).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

logger = logging.getLogger("jardo.inproc")

# Job name -> coroutine function (ctx, *args). Matches WorkerSettings.functions.
JobFn = Callable[..., Awaitable[object]]


class InProcessQueue:
    """A drop-in stand-in for an Arq pool's `enqueue_job` / `ping` / `aclose`."""

    def __init__(self, functions: dict[str, JobFn]) -> None:
        self._functions = functions
        self._tasks: set[asyncio.Task] = set()
        self._scheduler: asyncio.Task | None = None

    async def ping(self) -> bool:
        return True

    async def enqueue_job(self, name: str, *args: object) -> None:
        fn = self._functions.get(name)
        if fn is None:
            logger.warning("enqueue_job: unknown job %r (ignored)", name)
            return
        self._spawn(fn, *args)

    def _spawn(self, fn: JobFn, *args: object) -> None:
        async def _run() -> None:
            try:
                await fn({}, *args)
            except Exception as exc:  # noqa: BLE001 — background work is non-fatal
                logger.warning("in-process job %s failed (non-fatal): %s",
                               getattr(fn, "__name__", fn), exc)

        task = asyncio.create_task(_run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def start_scheduler(self, crons: list[tuple[JobFn, Callable[[datetime], bool]]]) -> None:
        """Run report crons in-process. Each entry is (fn, should_fire(now_utc))."""
        self._scheduler = asyncio.create_task(self._schedule_loop(crons))

    async def _schedule_loop(
        self, crons: list[tuple[JobFn, Callable[[datetime], bool]]]
    ) -> None:
        # Minute-granularity: check once a minute, fire each cron at most once per
        # matching minute (guarded by the last-fired timestamp).
        last_fired: dict[int, str] = {}
        try:
            while True:
                now = datetime.now(timezone.utc)
                stamp = now.strftime("%Y-%m-%dT%H:%M")
                for i, (fn, should_fire) in enumerate(crons):
                    if should_fire(now) and last_fired.get(i) != stamp:
                        last_fired[i] = stamp
                        self._spawn(fn)
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass

    async def aclose(self) -> None:
        if self._scheduler is not None:
            self._scheduler.cancel()
        for task in list(self._tasks):
            task.cancel()
