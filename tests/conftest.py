from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "claude-fusion-drive"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


@pytest.fixture
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    drive_home = tmp_path / "claude-fusion-drive-home"
    engine_home = drive_home / "engine"
    monkeypatch.setenv("CLAUDE_FUSION_DRIVE_HOME", str(drive_home))
    monkeypatch.setenv("RELENTLESS_INCEPTION_HOME", str(engine_home))
    return drive_home

