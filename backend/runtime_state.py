"""Trạng thái runtime process (DB bootstrap, v.v.)."""
from __future__ import annotations

import threading

_db_ready = threading.Event()


def set_db_ready() -> None:
    _db_ready.set()


def wait_db_ready(timeout: float = 300.0) -> bool:
    return _db_ready.wait(timeout=timeout)


def is_db_ready() -> bool:
    return _db_ready.is_set()
