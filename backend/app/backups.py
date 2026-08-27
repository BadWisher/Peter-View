"""Ежедневные резервные копии каталога data/ (стайл-гайды, задания, репозиторий, статистика).

Снимок — это tar.gz всего data/ (кроме самого каталога бэкапов) в BACKUP_DIR.
Храним последние BACKUP_KEEP штук, старые удаляем. Каталог BACKUP_DIR обычно
монтируется на хост (bind-mount), чтобы копии переживали потерю тома.
"""

from __future__ import annotations

import logging
import os
import tarfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/app/backups"))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "7"))
_PREFIX = "peterview-"
_SUFFIX = ".tar.gz"


def _snapshots() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    items = [p for p in BACKUP_DIR.glob(f"{_PREFIX}*{_SUFFIX}") if p.is_file()]
    items.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return items


def _rotate() -> None:
    for old in _snapshots()[BACKUP_KEEP:]:
        old.unlink(missing_ok=True)


def make_snapshot() -> Path | None:
    """Создаёт снимок data/. Возвращает путь к архиву (или None, если данных нет)."""
    if not DATA_DIR.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"{_PREFIX}{stamp}{_SUFFIX}"
    backup_resolved = BACKUP_DIR.resolve()
    data_resolved = DATA_DIR.resolve()

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # если каталог бэкапов вложен в data/, не утаскиваем его в снимок
        rel = Path(info.name).relative_to("data")
        full = (data_resolved / rel).resolve()
        if full == backup_resolved or backup_resolved in full.parents:
            return None
        return info

    try:
        with tarfile.open(target, "w:gz") as tar:
            tar.add(DATA_DIR, arcname="data", filter=_filter)
        # В data/ лежат настройки с ключами и история проверок: читать архив
        # должен только владелец.
        os.chmod(target, 0o600)
    except OSError as e:
        logger.warning("Не удалось создать бэкап: %s", e)
        target.unlink(missing_ok=True)
        return None
    _rotate()
    logger.info("Бэкап создан: %s", target.name)
    return target


def last_snapshot() -> dict | None:
    items = _snapshots()
    if not items:
        return None
    latest = items[0]
    st = latest.stat()
    return {"name": latest.name, "size": st.st_size, "created_at": st.st_mtime,
            "count": len(items)}


def needs_snapshot_today() -> bool:
    """True, если за сегодня (по mtime последнего) снимка ещё не было."""
    last = last_snapshot()
    if last is None:
        return True
    return (time.time() - last["created_at"]) >= 12 * 3600
