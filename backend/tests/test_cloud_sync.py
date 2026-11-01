"""Cloud sync (uploads, conflicts, deletes), Full access, and tasks the phone queues for this PC."""
import json
import uuid

import httpx
import pytest

from mtrini import account, cloud_sync, remote, threads
from mtrini import remote_crypto as rc

PHONE = "ph1"
PC = "pc1"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    from mtrini.config import user_dir

    (user_dir() / "account.json").write_text(json.dumps({"deviceId": PC}))
    for f in ("remote.json", "sync.json", "workspaces.json"):
        (user_dir() / f).unlink(missing_ok=True)
    monkeypatch.setattr(threads, "_known", None)
    monkeypatch.setattr(account, "_token", lambda: "tok")
    return tmp_path


def pair(full=False, allow_auto=False):
    """A phone paired with this PC; returns the key the phone shares with it."""
    data = remote.load()
    phone_key = rc.new_private_key()
    data["paired"][PHONE] = {"name": "Pixel", "pub": rc.public_str(phone_key), "paired_at": 1, "allow_auto": allow_auto, "full": full}
    remote._save(data)
    return rc.shared_key(phone_key, remote.pc_public(), remote.pc_public(), rc.public_str(phone_key))


def sealed_task(key, ws, prompt="add a test", mode="ask", tid="t1", task=None):
    body = {"kind": "task", "task": task or uuid.uuid4().hex, "thread_id": tid, "workspace": str(ws), "prompt": prompt, "mode": mode}
    return {"id": uuid.uuid4().hex[:16], "from_device": PHONE, "thread_id": tid, "workspace": str(ws),
            "prompt": json.dumps(rc.seal(key, PHONE, PC, body))}


class FakeCloud:
    """Just enough of cloud/src/sync.js: sessions with revs and conflicts, plus the task queue."""

    def __init__(self):
        self.threads, self.rev, self.tasks, self.updates = {}, 0, [], []

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.startswith("/sync/threads/"):
            tid = path.rsplit("/", 1)[1]
            cur = self.threads.get(tid)
            if req.method == "PUT":
                b = json.loads(req.content)
                if cur and "base_rev" in b and b["base_rev"] != cur["rev"]:
                    return httpx.Response(409, json={"rev": cur["rev"], "thread": cur["thread"]})
                self.rev += 1
                self.threads[tid] = {"rev": self.rev, "thread": b["thread"], "workspace": b["workspace"]}
                return httpx.Response(200, json={"ok": True, "rev": self.rev})
            if req.method == "DELETE":
                self.threads.pop(tid, None)
                return httpx.Response(200, json={"ok": True})
        if path == "/sync/tasks":
            return httpx.Response(200, json={"tasks": [t for t in self.tasks if t.get("status", "queued") == "queued"]})
        if path.startswith("/sync/tasks/"):
            tid = path.rsplit("/", 1)[1]
            self.updates.append((tid, json.loads(req.content)))
            for t in self.tasks:
                if t["id"] == tid:
                    t["status"] = json.loads(req.content)["status"]
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)


@pytest.fixture()
def cloud(monkeypatch, home):
    fake = FakeCloud()
    monkeypatch.setattr(cloud_sync, "_client", lambda: httpx.Client(base_url="https://cloud.test", transport=httpx.MockTransport(fake.handler)))
    return fake


def project(tmp_path, name="shop"):
    ws = tmp_path / name
    ws.mkdir()
    return ws


# ---------------------------------------------------------------- the cloud copy

def test_cloud_copy_drops_images_and_trims_long_fields():
    big = "x" * (cloud_sync.MAX_FIELD + 50)
    t = {"id": "a", "messages": [{"role": "user", "content": "hi", "images": [{"mime": "image/png", "data": "AAAA"}]},
                                 {"role": "tool", "tool": "read_file", "output": {"text": big}}]}
    out = cloud_sync.cloud_copy(t)
    assert out["messages"][0]["images"] == [] and out["messages"][0]["imagesOmitted"] == 1
    assert len(out["messages"][1]["output"]["text"]) < len(big) and "trimmed" in out["messages"][1]["output"]["text"]
    assert t["messages"][0]["images"]  # the local copy is untouched


def test_merge_keeps_local_and_adds_cloud_only_messages_in_order():
    local = {"messages": [{"role": "user", "content": "a", "ts": 1}, {"role": "assistant", "content": "b", "ts": 3}]}
    cloud = {"messages": [{"role": "user", "content": "a", "ts": 1}, {"role": "user", "content": "from phone", "ts": 2}]}
    assert [m["content"] for m in cloud_sync.merge(local, cloud)["messages"]] == ["a", "from phone", "b"]
    assert cloud_sync.merge(local, {"messages": local["messages"][:1]}) is local


# ---------------------------------------------------------------- sync passes

def test_sessions_upload_once_then_only_when_changed_and_deletes_follow(tmp_path, cloud):
    ws = project(tmp_path)
    t = threads.create_thread(ws, "Fix login")
    threads.append_message(ws, t["id"], "user", "hello")
    cloud_sync.sync_once()
    assert cloud.threads[t["id"]]["thread"]["messages"][0]["content"] == "hello"
    assert cloud.threads[t["id"]]["workspace"] == str(ws.resolve())
    rev = cloud.rev
    cloud_sync.sync_once()
    assert cloud.rev == rev  # nothing changed, nothing sent
    threads.delete_thread(ws, t["id"])
    cloud_sync.sync_once()
    assert t["id"] not in cloud.threads and cloud_sync.load()["threads"] == {}


def test_a_conflict_folds_in_the_cloud_messages_and_saves_again(tmp_path, cloud):
    ws = project(tmp_path)
    t = threads.create_thread(ws, "T")
    threads.append_message(ws, t["id"], "user", "one")
    cloud_sync.sync_once()
    cur = cloud.threads[t["id"]]
    cloud.rev += 1  # another device saved a message meanwhile
    cloud.threads[t["id"]] = {**cur, "rev": cloud.rev, "thread": {**cur["thread"], "messages": cur["thread"]["messages"] + [
        {"role": "user", "content": "from elsewhere", "ts": 10 ** 10}]}}
    threads.append_message(ws, t["id"], "assistant", "two")
    cloud_sync.sync_once()
    local = [m["content"] for m in threads.get_thread(ws, t["id"])["messages"]]
    assert local == ["one", "two", "from elsewhere"]
    assert [m["content"] for m in cloud.threads[t["id"]]["thread"]["messages"]] == local


def test_sync_off_sends_nothing(tmp_path, cloud):
    ws = project(tmp_path)
    threads.create_thread(ws, "T")
    data = cloud_sync.load()
    data["enabled"] = False
    cloud_sync._save(data)
    cloud_sync.sync_once()
    assert cloud.threads == {}


# ---------------------------------------------------------------- Full access

def test_full_access_allows_everything_but_remote_access_and_sign_out():
    full = {"full": True}
    assert remote.policy("POST", "/api/providers/configure", {"provider": "openai"}, full, [])[0]
    assert remote.policy("GET", "/api/threads?workspace=C:/anything", None, full, [])[0]
    ok, _, body = remote.policy("POST", "/api/agent", {"workspace": "C:/x", "permissionMode": "auto"}, full, [])
    assert ok and body["permissionMode"] == "auto"
    for path in ("/api/remote/settings", "/api/remote/devices/ph1/full", "/api/account/logout"):
        assert not remote.policy("POST", path, {}, full, [])[0]
    assert not remote.policy("POST", "/api/providers/configure", {}, {}, [])[0]  # without Full access: still refused


def test_full_access_phones_see_every_project_with_sessions(tmp_path, home):
    a, b = project(tmp_path, "a"), project(tmp_path, "b")
    threads.create_thread(a, "x")
    threads.create_thread(b, "y")
    remote.share_project(str(a), True)
    assert [p["name"] for p in remote.shared({})["projects"]] == ["a"]
    assert sorted(p["name"] for p in remote.shared({"full": True})["projects"]) == ["a", "b"]


# ---------------------------------------------------------------- queued tasks

def test_a_task_runs_only_when_sealed_by_a_paired_phone(tmp_path, home):
    ws = project(tmp_path)
    remote.share_project(str(ws), True)
    key = pair()
    job = remote.open_task(sealed_task(key, ws, mode="auto"))
    assert job["prompt"] == "add a test" and job["mode"] == "ask"  # Auto isn't allowed for this phone
    with pytest.raises(PermissionError, match="isn't sealed"):
        remote.open_task({**sealed_task(key, ws), "prompt": json.dumps({"v": 1, "iv": "AAAA", "c": "AAAA"})})
    with pytest.raises(PermissionError, match="isn't sealed"):  # sealed with some other key
        remote.open_task(sealed_task(rc.shared_key(rc.new_private_key(), remote.pc_public(), remote.pc_public(), remote.pc_public()), ws))
    with pytest.raises(PermissionError, match="isn't paired"):
        remote.open_task({**sealed_task(key, ws), "from_device": "stranger"})
    other = project(tmp_path, "other")
    with pytest.raises(PermissionError, match="isn't shared"):
        remote.open_task(sealed_task(key, other))
    with pytest.raises(PermissionError, match="doesn't match"):  # the cloud swapped the project
        remote.open_task({**sealed_task(key, ws), "workspace": str(other)})


def test_a_task_never_runs_twice_even_if_resent_under_a_new_id(tmp_path, home):
    ws = project(tmp_path)
    remote.share_project(str(ws), True)
    key = pair(allow_auto=True)
    t = sealed_task(key, ws, mode="auto", task="same")
    assert remote.open_task(t)["mode"] == "auto"
    with pytest.raises(PermissionError, match="already ran"):
        remote.open_task({**t, "id": "resent"})


def test_queued_tasks_run_through_the_local_agent_and_report_back(tmp_path, cloud, monkeypatch):
    ws = project(tmp_path)
    remote.share_project(str(ws), True)
    data = remote.load()
    data["enabled"] = True
    remote._save(data)
    key = pair()
    cloud.tasks = [sealed_task(key, ws, prompt="write the readme", tid="new1"), {**sealed_task(key, ws), "from_device": "stranger"}]
    seen = []

    def agent(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        threads.append_message(ws, "new1", "user", "write the readme")
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=b'data: {"type": "assistant_delta", "delta": "ok"}\n\ndata: {"type": "done"}\n\n')

    real = httpx.Client
    monkeypatch.setattr(cloud_sync.httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(agent)}) if "cloud" not in str(kw.get("base_url")) else real(**kw))
    cloud_sync.sync_once()
    assert seen[0]["message"] == "write the readme" and seen[0]["threadId"] == "new1" and seen[0]["permissionMode"] == "ask"
    assert threads.get_thread(ws, "new1")["title"] == "write the readme"
    statuses = [(tid, u["status"]) for tid, u in cloud.updates]
    assert statuses[:2] == [(cloud.tasks[0]["id"], "running"), (cloud.tasks[0]["id"], "done")]
    assert (cloud.tasks[1]["id"], "failed") in statuses
    assert "new1" in cloud.threads  # the result goes to the cloud right away


def test_queued_tasks_wait_while_remote_access_is_off(tmp_path, cloud):
    ws = project(tmp_path)
    cloud.tasks = [sealed_task(pair(), ws)]
    cloud_sync.sync_once()
    assert cloud.updates == []
