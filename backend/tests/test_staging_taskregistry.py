import anyio
import zipfile
from pathlib import Path

from app import staging
from app.config import LOG_DIR
from app.taskregistry import TaskRegistry


def test_staging_cache_path_blocks_traversal():
    d = Path(staging.new_task_dir("download"))
    (d / "a.txt").write_text("a", "utf-8")
    assert staging.cache_item_path(d.name) == d.resolve()

    try:
        staging.cache_item_path("../config.json")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("traversal was not blocked")


def test_zip_dir_uses_relative_archive_names():
    d = Path(staging.new_task_dir("download"))
    (d / "sub").mkdir()
    (d / "sub" / "a.txt").write_text("a", "utf-8")
    (d / staging.CACHE_META_NAME).write_text("{}", "utf-8")

    zp = staging.zip_dir(str(d))
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
    assert names == ["sub/a.txt"]
    assert all(not n.startswith("/") and ".." not in Path(n).parts for n in names)


def test_log_tail_and_zip_skip_invalid_names():
    p = LOG_DIR / "tail.log"
    p.write_text("\n".join(str(i) for i in range(10)), "utf-8")

    content, truncated, size = staging.read_log_tail("tail.log", max_lines=3)
    assert content == "7\n8\n9"
    assert truncated is True
    assert size > 0

    zp = staging.zip_logs(["tail.log", "../secret"])
    with zipfile.ZipFile(zp) as z:
        assert z.namelist() == ["tail.log"]


def test_taskregistry_poll_done_and_subscribe():
    async def scenario():
        reg = TaskRegistry()
        calls = {"n": 0}

        def poll():
            calls["n"] += 1
            return {"done": calls["n"] >= 1, "status": "done", "value": calls["n"]}

        h = reg.create("unit", poll_fn=poll)
        q = await reg.subscribe(h.task_id)
        first = await q.get()
        assert first["event"] == "progress"

        done = None
        with anyio.fail_after(2):
            while True:
                msg = await q.get()
                if msg["event"] == "done":
                    done = msg
                    break
        assert done["data"]["status"] == "done"
        assert reg.detail(h.task_id)["terminal"] is True

    anyio.run(scenario)


def test_taskregistry_cancel_active_cache_refs():
    async def scenario():
        reg = TaskRegistry()
        h = reg.create("unit", cache_refs=["/tmp/cache"], meta={"dir": "/tmp/dir"})
        assert reg.active_cache_refs() == {"/tmp/cache", "/tmp/dir"}
        assert await reg.cancel(h.task_id) is True
        assert reg.active_cache_refs() == set()

    anyio.run(scenario)
