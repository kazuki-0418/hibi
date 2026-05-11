from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def state_root(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "state"
    root.mkdir()
    yield root


@pytest.fixture
def repo_root(tmp_path: Path) -> Iterator[Path]:
    """Isolated repo_root so kill-switch checks don't see real `.claude/STOP`."""
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    yield root


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
