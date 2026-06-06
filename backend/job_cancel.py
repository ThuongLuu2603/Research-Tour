"""Hủy job hợp tác (cooperative cancel) cho scrape/sync chạy nền.

Endpoint /cancel ghi job_id vào sổ này; vòng lặp merge + recompute kiểm tra giữa các lô
và ném JobCancelled để dừng SỚM (giải phóng khóa + ngừng tốn RU) thay vì chỉ đánh dấu DB.
"""
from __future__ import annotations

import threading

_cancelled: set[int] = set()
_lock = threading.Lock()


class JobCancelled(Exception):
    """Job bị người dùng yêu cầu dừng."""


def request_cancel(job_id: int | None) -> None:
    if job_id is None:
        return
    with _lock:
        _cancelled.add(int(job_id))


def is_cancel_requested(job_id: int | None) -> bool:
    if job_id is None:
        return False
    with _lock:
        return int(job_id) in _cancelled


def clear_cancel(job_id: int | None) -> None:
    if job_id is None:
        return
    with _lock:
        _cancelled.discard(int(job_id))


def make_cancel_check(job_id: int | None):
    """Trả về hàm cancel_check() dùng để kiểm tra trong vòng lặp."""
    return lambda: is_cancel_requested(job_id)


def raise_if_cancelled(cancel_check) -> None:
    if cancel_check is not None and cancel_check():
        raise JobCancelled("Đã dừng theo yêu cầu")
