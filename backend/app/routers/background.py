from __future__ import annotations

import asyncio
import logging

from .. import backups, features
from ..llm import repo_store
from ..llm import watch_run

logger = logging.getLogger(__name__)




async def start_repo_auto_archive():
    if not features.enabled("documents"):
        return

    async def loop():
        while True:
            try:
                await asyncio.to_thread(repo_store.auto_archive_stale)
            except Exception as e:  # noqa: BLE001
                logger.warning("Авто-архив не выполнен: %s", e)
            await asyncio.sleep(6 * 3600)

    asyncio.create_task(loop())





async def start_daily_backup():
    """Раз в сутки делает снимок data/ (если за сегодня ещё не было)."""
    async def loop():
        while True:
            try:
                if await asyncio.to_thread(backups.needs_snapshot_today):
                    await asyncio.to_thread(backups.make_snapshot)
            except Exception as e:  # noqa: BLE001
                logger.warning("Бэкап не выполнен: %s", e)
            await asyncio.sleep(6 * 3600)

    asyncio.create_task(loop())







async def start_watch_daily():
    if not features.enabled("watch"):
        return

    async def loop():
        await asyncio.sleep(20)
        while True:
            try:
                await watch_run.run_daily_if_due()
            except Exception as e:  # noqa: BLE001
                logger.warning("Мониторинг не выполнен: %s", e)
            await asyncio.sleep(30 * 60)

    asyncio.create_task(loop())
