"""Locks must not block forever, and a recycled pid must not look alive.

Both were reported by the 2026-08-01 field evaluation: a wedged provider CLI
could hold a lock for its full 1800s subprocess timeout with nothing to point
at, and a crashed worker whose pid was reused was never reclaimed.
"""

from __future__ import annotations

import json
import multiprocessing
import time
from pathlib import Path

import pytest

from claude_fusion_drive import jobs
from claude_fusion_drive.errors import LockTimeout
from claude_fusion_drive.util import exclusive_lock


def _hold_lock(path: str, hold_seconds: float, ready) -> None:
    with exclusive_lock(Path(path)):
        ready.set()
        time.sleep(hold_seconds)


def test_lock_is_acquired_and_released_normally(tmp_path: Path) -> None:
    lock = tmp_path / "run.lock"
    with exclusive_lock(lock):
        pass
    with exclusive_lock(lock):
        pass


def test_lock_records_its_holder_while_held(tmp_path: Path) -> None:
    lock = tmp_path / "run.lock"
    with exclusive_lock(lock):
        record = json.loads(lock.read_text(encoding="utf-8"))
    assert record["pid"] > 0
    assert record["acquired_at"]


def test_lock_times_out_instead_of_blocking_forever(tmp_path: Path) -> None:
    lock = tmp_path / "contended.lock"
    ready = multiprocessing.Event()
    holder = multiprocessing.Process(target=_hold_lock, args=(str(lock), 5.0, ready))
    holder.start()
    try:
        assert ready.wait(timeout=10), "holder process never acquired the lock"
        started = time.monotonic()
        with pytest.raises(LockTimeout) as caught:
            with exclusive_lock(lock, timeout=0.5):
                pass
        elapsed = time.monotonic() - started
    finally:
        holder.terminate()
        holder.join(timeout=10)

    assert elapsed < 4, "the waiter blocked past its deadline"
    # The message has to name a holder, or a stall is undiagnosable.
    assert "pid" in str(caught.value)


def test_pid_liveness_rejects_a_recycled_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setattr(jobs, "_process_started_at", lambda _pid: "Sat Aug  2 09:00:00 2026")
    # Our own pid is certainly alive, but it did not start when the manifest says.
    assert jobs._pid_is_alive(os.getpid(), "Fri Aug  1 09:00:00 2026") is False
    assert jobs._pid_is_alive(os.getpid(), "Sat Aug  2 09:00:00 2026") is True


def test_pid_liveness_falls_back_when_the_probe_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setattr(jobs, "_process_started_at", lambda _pid: None)
    assert jobs._pid_is_alive(os.getpid(), "Fri Aug  1 09:00:00 2026") is True


def test_process_start_probe_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args, **_kwargs):
        raise RuntimeError("no subprocess here")

    monkeypatch.setattr(jobs.subprocess, "run", explode)
    assert jobs._process_started_at(1) is None
