import httpx
import pytest

from loader.source import DownloadError, HttpSource, SourceFileNotFound


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_retries_three_times_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 4:
            return httpx.Response(503)
        return httpx.Response(200, content=b"parquet")

    sleeps = []
    source = HttpSource(client=_client(handler), sleeper=sleeps.append, retries=3)
    assert source._get("https://example.com/file.parquet") == b"parquet"
    assert calls["n"] == 4
    assert sleeps == [1, 2, 4]


def test_download_404_is_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    sleeps = []
    source = HttpSource(client=_client(handler), sleeper=sleeps.append, retries=3)
    with pytest.raises(SourceFileNotFound, match="source file not found"):
        source._get("https://example.com/missing.parquet")
    assert calls["n"] == 1
    assert sleeps == []


def test_download_failure_after_three_retries():
    def handler(request):
        raise httpx.ConnectError("down")

    sleeps = []
    source = HttpSource(client=_client(handler), sleeper=sleeps.append, retries=3)
    with pytest.raises(DownloadError, match="3 retries"):
        source._get("https://example.com/file.parquet")
    assert sleeps == [1, 2, 4]
