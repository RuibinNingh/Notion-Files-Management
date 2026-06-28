import time

from batch_rename import BatchRemoveSuffixTask
from download import Download
from migrate import MigrationTask
from notion import Notion
from page_size_update import PageSizeUpdateTask
from upload import TokenBucketRateLimiter, Upload
from url_security import UnsafeUrlError, assert_safe_remote_url


def test_url_security_rejects_local_and_credentials():
    for url in ("http://127.0.0.1/x", "http://localhost/x", "file:///etc/passwd", "https://u:p@example.com/x"):
        try:
            assert_safe_remote_url(url)
        except UnsafeUrlError:
            pass
        else:
            raise AssertionError(f"unsafe URL accepted: {url}")


def test_download_rejects_unsafe_url_without_network():
    dl = Download(max_workers=1, debug=False)
    try:
        r = dl.download("http://127.0.0.1:1/a", "/tmp/unused", 1)
        assert r["msg"] == "Unsafe URL rejected"
        st = dl.get_status("http://127.0.0.1:1/a")
        assert st["status"] == "error"
        assert "unsafe_url" in st["error"]
    finally:
        dl.shutdown(wait=False)


def test_notion_extracts_download_items_and_avoids_private_size_probe():
    notion = Notion("token")
    block = {
        "id": "b1",
        "type": "file",
        "file": {
            "type": "external",
            "external": {"url": "http://127.0.0.1/private"},
            "caption": [{"plain_text": "caption.bin"}],
        },
    }
    items = notion.get_download_url_no_recurse([block])
    assert items[0]["real_name"] == "caption.bin"
    assert items[0]["url"] == "http://127.0.0.1/private"
    assert notion._get_remote_file_size("http://127.0.0.1/private") == 0


def test_page_size_probe_rejects_private_url():
    assert PageSizeUpdateTask._probe_file_size("http://127.0.0.1/private", max_retries=0) == 0.0


def test_upload_helpers_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(Upload, "get_max_upload_bytes", lambda self: 50 * 1024 * 1024)
    up = Upload("token", max_workers=0, debug=False)
    try:
        f = tmp_path / "archive.7z"
        f.write_bytes(b"abc")
        mime, upload_name = up.get_mime_type(str(f))
        assert mime == "text/plain"
        assert upload_name == "archive.7z.txt"
        assert up._detect_notion_block_type("movie.mp4") == "video"
        assert up.upload_file(str(f), "page")["msg"] == "任务已入队"
        assert up.upload_file(str(tmp_path / "missing"), "page")["msg"] == "文件不存在"
    finally:
        up.shutdown(wait=False)


def test_token_bucket_rate_limiter_consumes_tokens():
    limiter = TokenBucketRateLimiter(rate=1000, burst=1)
    start = time.monotonic()
    limiter.acquire()
    limiter.acquire()
    assert time.monotonic() - start < 0.2


def test_migration_property_cleanup():
    task = MigrationTask(Notion("token"), "src", "tgt", {"Tags": "NewTags", "Formula": "F"}, 1)
    task._src_prop_types = {"Tags": "multi_select", "Formula": "formula"}
    task._tgt_prop_types = {"NewTags": "multi_select", "F": "rich_text"}
    props = {
        "Tags": {
            "type": "multi_select",
            "multi_select": [{"id": "1", "name": "A", "color": "red", "description": "x"}],
        },
        "Formula": {"type": "formula", "formula": {"string": "x"}},
    }
    out = task._convert_properties(props)
    assert out == {"NewTags": {"type": "multi_select", "multi_select": [{"name": "A"}]}}


def test_batch_rename_title_helpers():
    assert BatchRemoveSuffixTask._find_title_prop({"Name": "title", "Other": "rich_text"}) == "Name"
    page = {"properties": {"Name": {"title": [{"plain_text": "Hello copy"}]}}}
    assert BatchRemoveSuffixTask._extract_title(page, "Name") == "Hello copy"
