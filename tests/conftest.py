"""Ensures tests never touch a real data/ dir on disk -- state is
constructed in-memory in every test above (AccountState(...), GateState(...)
passed explicitly), but this guards against any future test that forgets
and calls .load()/.save() without an explicit path.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_hermes_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path / "data"))
