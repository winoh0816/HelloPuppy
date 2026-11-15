from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_media_dir(tmp_path, monkeypatch):
    """Photos saved during a test go to a temporary folder, never to backend/data/media."""
    monkeypatch.setenv("HELLOPUPPY_MEDIA_DIR", str(tmp_path / "media"))
