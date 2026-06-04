"""Database-level locks for long jobs that write shared tables."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text

from config import settings

logger = logging.getLogger(__name__)

TOURS_WRITE_LOCK = (874260, 1)


def _is_postgres() -> bool:
    return settings.database_url.startswith("postgresql")


@contextmanager
def advisory_lock(db, key: tuple[int, int], owner: str) -> Iterator[bool]:
    """Try to take a Postgres session-level advisory lock for the current DB session."""
    if not _is_postgres():
        yield True
        return

    got = False
    try:
        got = bool(
            db.execute(
                text("select pg_try_advisory_lock(:k1, :k2)"),
                {"k1": int(key[0]), "k2": int(key[1])},
            ).scalar()
        )
        if not got:
            logger.warning("DB advisory lock busy: owner=%s key=%s", owner, key)
            yield False
            return
        yield True
    finally:
        if got:
            try:
                db.execute(
                    text("select pg_advisory_unlock(:k1, :k2)"),
                    {"k1": int(key[0]), "k2": int(key[1])},
                )
            except Exception as e:
                logger.warning("DB advisory unlock failed owner=%s key=%s: %s", owner, key, e)


@contextmanager
def tours_write_lock(db, owner: str) -> Iterator[bool]:
    with advisory_lock(db, TOURS_WRITE_LOCK, owner) as locked:
        yield locked
