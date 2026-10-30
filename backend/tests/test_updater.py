"""Automatic updates: version checks, picking the right file, checksum verification, installing."""
import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient

from mtrini import updater

SETUP = b"pretend installer bytes"
APPIMG = b"pretend appimage bytes"


def fake_github(version="9.9.9", setup=SETUP, sha=None):
    sha = sha or hashlib.sha256(setup).hexdigest()
    linux_sha = f"{hashlib.sha256(APPIMG).hexdigest()}  MtriniWorkspace-{version}-x86_64.AppImage\n"
    assets = [
        {"name": f"MtriniWorkspace-Setup-{version}.exe", "url": "https://api.github.test/a/1"},
        {"name": f"MtriniWorkspace-Setup-{version}.exe.sha256", "url": "https://api.github.test/a/2"},
        {"name": f"MtriniWorkspace-{version}-x86_64.AppImage", "url": "https://api.github.test/a/3"},
        {"name": f"MtriniWorkspace-{version}-linux.sha256", "url": "https://api.github.test/a/4"},
    ]
    files = {"/a/1": setup, "/a/2": f"{sha} *MtriniWorkspace-Setup-{version}.exe\n".encode(),
             "/a/3": APPIMG, "/a/4": linux_sha.encode()}

    def handler(req: httpx.Request):
        if req.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json={"tag_name": f"v{version}", "body": "notes", "html_url": "https://x/r", "assets": assets})
        assert req.headers["accept"] == "application/octet-stream"  # downloads go through the API host
        return httpx.Response(200, content=files[req.url.path])
    return handler


@pytest.fixture()
def gh(monkeypatch, tmp_path):
    def use(handler, kind="windows"):
        monkeypatch.setattr(updater, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
        monkeypatch.setattr(updater, "install_kind", lambda: kind)
        monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
        updater._state.clear()
        updater._state.update({"status": "idle", "current": updater.__version__})
    return use


def test_versions():
    assert updater.newer("0.8.10", "0.8.2") and updater.newer("1.0.0", "0.9.9")
    assert not updater.newer("0.8.1", "0.8.1") and not updater.newer("0.8.0", "0.8.1")
    assert updater.parse_version("v0.9") == (0, 9, 0)


def test_downloads_and_verifies_the_windows_installer(gh):
    gh(fake_github())
    st = updater.check()
    assert st["status"] == "ready" and st["latest"] == "9.9.9"
    assert open(st["file"], "rb").read() == SETUP and st["sha256"] == hashlib.sha256(SETUP).hexdigest()


def test_rejects_a_download_that_does_not_match_its_checksum(gh):
    gh(fake_github(sha="0" * 64))
    st = updater.check()
    assert st["status"] == "error" and "checksum" in st["error"]
    assert not st.get("file")


def test_appimage_uses_the_combined_linux_checksum_file(gh):
    gh(fake_github(), kind="appimage")
    assert updater.check()["status"] == "ready"


def test_deb_and_source_installs_only_report(gh):
    gh(fake_github(), kind="linux-manual")
    assert updater.check()["status"] == "available"
    gh(fake_github(), kind="source")
    assert updater.check()["status"] == "available"


def test_up_to_date(gh):
    gh(fake_github(version=updater.__version__))
    assert updater.check()["status"] == "uptodate"


def test_windows_install_runs_the_installer_silently(gh, monkeypatch):
    gh(fake_github())
    updater.check()
    spawned = []
    monkeypatch.setattr(updater, "_spawn_detached", spawned.append)
    assert updater.apply(relaunch=True)
    args = spawned[0]
    assert args[0].endswith("MtriniWorkspace-Setup-9.9.9.exe") and "/VERYSILENT" in args and "/RELAUNCH" in args
    updater._state["status"] = "ready"
    updater.apply(relaunch=False)
    assert "/RELAUNCH" not in spawned[1]  # closing the app: install, don't reopen


def test_appimage_install_replaces_the_file(gh, monkeypatch, tmp_path):
    gh(fake_github(), kind="appimage")
    updater.check()
    app = tmp_path / "Mtrini.AppImage"
    app.write_bytes(b"old")
    monkeypatch.setenv("APPIMAGE", str(app))
    assert updater.apply(relaunch=False)
    assert app.read_bytes() == APPIMG


def test_nothing_to_apply_without_a_ready_update(gh):
    gh(fake_github())
    assert updater.apply(relaunch=True) is False


def test_api_and_setting(gh, monkeypatch, tmp_path):
    gh(fake_github())
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    from mtrini.main import app

    c = TestClient(app)
    assert c.get("/api/update").json()["auto"] is True
    assert c.post("/api/update/settings", json={"auto": False}).json()["auto"] is False
    assert c.post("/api/update/check").json()["status"] == "available"  # auto off: tell, don't download
    assert c.post("/api/update/restart").status_code == 409
