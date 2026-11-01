"""Skill library and Import from GitHub (GitHub is faked with httpx.MockTransport)."""
import httpx
import pytest
from fastapi.testclient import TestClient

from mtrini.project import MAX_SKILL_CHARS, library, skill_import, valid_skill_name

REVIEW = "---\nname: Pro Review\ndescription: Review code like a senior engineer\n---\n\n1. Read the diff.\n2. Report bugs.\n"
NOTES = "# Meeting notes\n\nTurn a transcript into action items.\n"
HUGE = "---\nname: huge\ndescription: too big\n---\n\n" + "x" * (MAX_SKILL_CHARS + 10)


def fake_github(files=None, status=200):
    files = files or {"skills/pro-review/SKILL.md": REVIEW, "skills/meeting-notes/SKILL.md": NOTES,
                      "skills/huge/SKILL.md": HUGE, "skills/pro-review/run.sh": "rm -rf /", "README.md": "hi"}

    def handler(req: httpx.Request):
        p = req.url.path
        if status != 200:
            return httpx.Response(status)
        if p == "/repos/acme/skills":
            return httpx.Response(200, json={"default_branch": "main"})
        if p.startswith("/repos/acme/skills/git/trees/"):
            return httpx.Response(200, json={"tree": [{"path": k, "type": "blob"} for k in files]})
        if p.startswith("/repos/acme/skills/contents/"):
            path = p.split("/contents/", 1)[1]
            assert path.endswith("SKILL.md"), "only SKILL.md files are ever downloaded"
            assert req.headers["accept"] == "application/vnd.github.raw"
            return httpx.Response(200, text=files[path])
        return httpx.Response(404)
    return handler


@pytest.fixture()
def gh(monkeypatch, tmp_path):
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))

    def use(handler):
        monkeypatch.setattr(skill_import, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return use


def test_parse_url_forms():
    s = skill_import.parse_url("acme/skills")
    assert (s.owner, s.repo, s.ref, s.path, s.is_file) == ("acme", "skills", None, "", False)
    s = skill_import.parse_url("https://github.com/acme/skills/tree/dev/skills/pro-review/")
    assert (s.ref, s.path, s.is_file) == ("dev", "skills/pro-review", False)
    s = skill_import.parse_url("github.com/acme/skills/blob/main/skills/x/SKILL.md")
    assert s.is_file and s.path == "skills/x/SKILL.md"
    with pytest.raises(ValueError):
        skill_import.parse_url("https://example.com/acme/skills")


def test_slug():
    assert skill_import.slug("Pro Review!") == "pro-review"
    assert skill_import.slug("--A__B--") == "a-b"


def test_library_entries_are_valid():
    names = [s["name"] for s in library.library()]
    assert len(names) >= 25 and len(set(names)) == len(names)
    for s in library.library():
        assert valid_skill_name(s["name"]) and s["category"] in library.CATEGORIES
        assert s["description"] and 0 < len(s["content"]) <= MAX_SKILL_CHARS


def test_library_api(gh, tmp_path):
    from mtrini.main import app

    c = TestClient(app)
    lib = c.get("/api/skills/library").json()
    assert not any(s["installed"] for s in lib["skills"])
    assert c.post("/api/skills/library", json={"names": ["debug", "dockerize", "nope"]}).json()["added"] == ["debug", "dockerize"]
    lib = c.get("/api/skills/library").json()
    assert {s["name"] for s in lib["skills"] if s["installed"]} == {"debug", "dockerize"}
    assert (tmp_path / ".mtrini" / "skills" / "debug" / "SKILL.md").exists()


def test_preview_lists_skills_and_downloads_only_skill_files(gh, tmp_path):
    gh(fake_github())
    found = skill_import.preview(tmp_path, "acme/skills")
    by = {s["name"]: s for s in found["skills"]}
    assert set(by) == {"pro-review", "meeting-notes", "huge"}
    assert by["pro-review"]["description"] == "Review code like a senior engineer"
    assert by["meeting-notes"]["description"] == "Meeting notes"  # no front matter: first line
    assert by["huge"]["ok"] is False and "Longer" in by["huge"]["reason"]
    assert not (tmp_path / ".mtrini").exists()  # preview writes nothing


def test_install_picked_skills_keeps_existing(gh, tmp_path):
    gh(fake_github())
    out = skill_import.install(tmp_path, "https://github.com/acme/skills", ["pro-review", "huge"])
    assert out["added"] == ["pro-review"] and out["skipped"] == [{"name": "huge", "reason": f"Longer than {MAX_SKILL_CHARS:,} characters"}]
    text = (tmp_path / ".mtrini" / "skills" / "pro-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "Report bugs." in text and "Imported from github.com/acme/skills" in text
    again = skill_import.install(tmp_path, "acme/skills", ["pro-review"])
    assert again["added"] == [] and again["skipped"][0]["reason"] == "Already installed"
    assert skill_import.install(tmp_path, "acme/skills", ["pro-review"], overwrite=True)["added"] == ["pro-review"]


def test_folder_link_limits_the_search(gh, tmp_path):
    gh(fake_github())
    found = skill_import.preview(tmp_path, "https://github.com/acme/skills/tree/main/skills/meeting-notes")
    assert [s["name"] for s in found["skills"]] == ["meeting-notes"]


def test_errors_are_readable(gh, tmp_path):
    from mtrini.main import app

    gh(fake_github(status=404))
    r = TestClient(app).post("/api/skills/import/preview", json={"url": "acme/skills"})
    assert r.status_code == 400 and "public" in r.json()["detail"]
    gh(fake_github(files={"README.md": "no skills"}))
    with pytest.raises(ValueError, match="No SKILL.md"):
        skill_import.preview(tmp_path, "acme/skills")
