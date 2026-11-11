"""nflverse-data release files, local or over HTTPS."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = "https://github.com/nflverse/nflverse-data/releases/download"

RELEASE = {
    "teams": "teams",
    "players": "players",
    "games": "schedules",
    "player_week_stats": "stats_player",
}


class LoadError(Exception):
    """A dataset failed validation, download, or write. The message is stored on load_runs."""


class SourceFileNotFound(LoadError):
    def __init__(self, url: str):
        super().__init__(f"source file not found: {url}")
        self.url = url


class DownloadError(LoadError):
    pass


def file_name(dataset: str, season: int | None) -> str:
    if dataset == "teams":
        return "teams_colors_logos.parquet"
    if dataset == "players":
        return "players.parquet"
    if dataset == "games":
        return "games.parquet"
    if dataset == "player_week_stats":
        if season is None:
            raise LoadError("player_week_stats requires a season")
        return f"stats_player_week_{season}.parquet"
    raise LoadError(f"unknown dataset: {dataset}")


def release_url(dataset: str, season: int | None) -> str:
    return f"{BASE}/{RELEASE[dataset]}/{file_name(dataset, season)}"


def _parse_retrieved(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class DirSource:
    """Read a mirror laid out like the GitHub release assets.

    ``retrieval.json`` is the original upstream retrieval instant. File mtime
    is not retrieval evidence and does not renew a receipt.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def url(self, dataset: str, season: int | None) -> str:
        return release_url(dataset, season)

    def fetch_parquet(self, dataset: str, season: int | None) -> bytes:
        path = self.root / RELEASE[dataset] / file_name(dataset, season)
        if not path.is_file():
            raise SourceFileNotFound(self.url(dataset, season))
        return path.read_bytes()

    def retrieved_at(self, dataset: str, season: int | None = None) -> datetime | None:
        del season
        path = self.root / RELEASE[dataset] / "retrieval.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return _parse_retrieved(payload.get("retrieved_at"))

    def fetch_version(self, dataset: str) -> str | None:
        path = self.root / RELEASE[dataset] / "timestamp.json"
        if not path.is_file():
            return None
        payload = json.loads(path.read_text())
        value = payload.get("last_updated")
        return None if value is None else str(value)


class HttpSource:
    """Download release assets. A 404 is not retried; other failures are retried 3 times."""

    def __init__(self, client: httpx.Client | None = None, sleeper=time.sleep, retries: int = 3):
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=60.0,
            follow_redirects=True,
            headers={"User-Agent": "seam-finder-loader"},
        )
        self.sleeper = sleeper
        self.retries = retries
        self._retrieved: dict[tuple[str, int | None], datetime] = {}

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def url(self, dataset: str, season: int | None) -> str:
        return release_url(dataset, season)

    def fetch_parquet(self, dataset: str, season: int | None) -> bytes:
        body = self._get(self.url(dataset, season))
        self._retrieved[(dataset, season)] = datetime.now(UTC)
        return body

    def retrieved_at(self, dataset: str, season: int | None = None) -> datetime | None:
        return self._retrieved.get((dataset, season))

    def fetch_version(self, dataset: str) -> str | None:
        url = f"{BASE}/{RELEASE[dataset]}/timestamp.json"
        try:
            payload = self._get(url)
        except (SourceFileNotFound, DownloadError):
            return None
        value = json.loads(payload).get("last_updated")
        return None if value is None else str(value)

    def _get(self, url: str) -> bytes:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.get(url)
            except Exception as exc:  # noqa: BLE001 - network errors are retried
                last = exc
            else:
                if response.status_code == 404:
                    raise SourceFileNotFound(url)
                if response.status_code >= 400:
                    last = DownloadError(f"HTTP {response.status_code} for {url}")
                else:
                    return response.content
            if attempt == self.retries:
                break
            self.sleeper(2**attempt)
        raise DownloadError(f"download failed after {self.retries} retries: {last}")
