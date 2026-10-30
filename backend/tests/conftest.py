import pytest


@pytest.fixture(autouse=True)
def _isolated_user_dir(tmp_path, monkeypatch):
    """Keep tests out of the real ~/.mtrini (provider settings, fallback secrets, install id),
    and away from the live free-model relay unless a test sets MTRINI_FREE_URL itself."""
    monkeypatch.setenv("MTRINI_HOME", str(tmp_path / "_home"))
    monkeypatch.delenv("MTRINI_FREE_URL", raising=False)
    monkeypatch.setattr("mtrini.providers.free.FREE_RELAY_URL", "")
