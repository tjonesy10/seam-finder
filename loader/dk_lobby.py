"""Bounded unauthenticated DraftKings Classic lobby capture.

The staged F004 loader is not used. Live calls stay on the allowlisted HTTPS
paths. Tests pass a transport; this module does not widen that list.
"""

import argparse
import csv
import io
import json
import os
import re
import socket
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import NoReturn
from urllib.parse import parse_qs, urljoin, urlparse
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpcore
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from loader.salary_private import (
    OBJECT_LIMIT,
    PARSER_VERSION,
    ArtifactKind,
    LedgerRow,
    ObservationStatus,
    ParseStatus,
    PoolKind,
    PrivateWriteError,
    RowStatus,
    Source,
    assert_actual_ceiling,
    canonical_sha256,
    find_snapshot,
    finish_load_run,
    finish_observation,
    insert_running_load_run,
    insert_running_observation,
    insert_snapshot,
    lock_capture,
    raise_private,
    reconcile,
    sha256_bytes,
    store_artifact,
    store_ledger,
    unlock_capture,
)
from loader.url import normalize_database_url

ET = ZoneInfo("America/New_York")
HTTP_BUDGET_S = 180
USER_AGENT = "seam-finder/0.1 (private DK Classic capture; github.com/tjonesy10/seam-finder)"
LOBBY_URL = "https://www.draftkings.com/lobby/getcontests?sport=NFL"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
CLASSIC_SLOTS = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "DST": 1}
REQUIRED_HEADERS = (
    "Position",
    "Name + ID",
    "Name",
    "ID",
    "Roster Position",
    "Salary",
    "Game Info",
    "TeamAbbrev",
)
SEASON_MIN = 1999
SEASON_MAX = 2100
WEEK_MIN = 1
WEEK_MAX = 18
_GAME_INFO = re.compile(
    r"^\s*([A-Za-z]{2,3})\s*@\s*([A-Za-z]{2,3})\s+"
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s+"
    r"(\d{1,2}):(\d{2})(AM|PM)\s+ET\s*$",
    re.IGNORECASE,
)
_REASON = re.compile(r"^[a-z0-9_]+$")


class Crash(Exception):
    """Test seam: the process stopped before the terminal write or audit."""


class CaptureFailure(Exception):
    def __init__(
        self,
        reason: str,
        *,
        private: str = "",
        body: bytes | None = None,
        truncated: bool = False,
        retry_after: str | None = None,
        guard_fields: dict | None = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.private = private[:300]
        self.body = body
        self.truncated = truncated
        self.retry_after = retry_after
        self.guard_fields = guard_fields


class SlateLabel(StrEnum):
    SUNDAY_MAIN = "sunday_main"
    EXPLICIT_GROUP = "explicit_group"


@dataclass
class Clock:
    wall: object
    mono: object


@dataclass(frozen=True)
class AttemptResult:
    exit_ok: bool
    persisted: bool
    reason: str
    status: str
    season: int | None
    week: int | None
    rows: int
    guard: str = ""


@dataclass(frozen=True)
class GameEvidence:
    away: str
    home: str
    kickoff_at: datetime
    game_id: str | None = None


@dataclass(frozen=True)
class RegGame:
    game_id: str
    season: int
    week: int
    gameday: date
    weekday: str
    kickoff_at: datetime
    away: str
    home: str


@dataclass(frozen=True)
class DraftableFact:
    draftable_id: int
    player_id: int
    salary: Decimal
    position: str
    team: str
    name: str


@dataclass(frozen=True)
class DraftablesEvidence:
    """Slot-expanded draftables. Salary rows come from the CSV, not this count."""

    by_id: dict[int, DraftableFact]
    slot_count: int
    player_count: int


@dataclass(frozen=True)
class DraftGroup:
    draft_group_id: int
    contest_type_id: int | None
    game_type_id: int | None
    games: tuple[GameEvidence, ...] | None
    draftables: DraftablesEvidence | None = None


@dataclass(frozen=True)
class RulesVerdict:
    verified: bool
    reason: str | None
    slots: tuple[str, ...] | None


@dataclass
class FetchBody:
    body: bytes
    media_type: str
    fetched_at: datetime


def system_clock() -> Clock:
    return Clock(wall=lambda: datetime.now(UTC), mono=time.monotonic)


def capture_schedule_enabled(flag: str | None) -> bool:
    """True only for the exact repository variable value that arms the workflow."""
    return flag == "true"


def next_wednesday_10_et(after: datetime) -> datetime:
    """Next Wednesday 10:00 America/New_York strictly after ``after``."""
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    cursor = after.astimezone(ET).date()
    for _ in range(14):
        if cursor.weekday() == 2:
            local_10 = datetime(cursor.year, cursor.month, cursor.day, 10, 0, tzinfo=ET)
            if local_10 > after:
                return local_10
        cursor += timedelta(days=1)
    raise RuntimeError("no wednesday")


def normalize_trigger(value: str) -> str:
    if value == "scheduled":
        return "schedule"
    if value in {"local", "manual", "schedule"}:
        return value
    raise CaptureFailure("invalid_trigger")


def public_note(reason: str, rows: int, snapshots: int) -> str:
    if _REASON.fullmatch(reason) is None:
        reason = "unspecified"
    return f"reason={reason};rows={rows};snapshots={snapshots}"


def allowlisted(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path
    if host == "www.draftkings.com" and path == "/lobby/getcontests":
        return parse_qs(parsed.query) == {"sport": ["NFL"]}
    if host == "www.draftkings.com" and path == "/lineup/getavailableplayerscsv":
        query = parse_qs(parsed.query)
        draft_ids = query.get("draftGroupId") or []
        return (
            set(query) == {"contestTypeId", "draftGroupId"}
            and query.get("contestTypeId") == ["21"]
            and _positive(draft_ids)
        )
    if host == "api.draftkings.com" and path.startswith("/draftgroups/v1/"):
        return _positive([path.removeprefix("/draftgroups/v1/")])
    prefix = "/lineups/v1/gametypes/"
    if host == "api.draftkings.com" and path.startswith(prefix) and path.endswith("/rules"):
        return _positive([path[len(prefix) : -len("/rules")]])
    return False


def _positive(values: list[str]) -> bool:
    return len(values) == 1 and values[0].isdigit() and int(values[0]) > 0


def group_url(draft_group_id: int) -> str:
    return f"https://api.draftkings.com/draftgroups/v1/{draft_group_id}"


def rules_url(game_type_id: int) -> str:
    return f"https://api.draftkings.com/lineups/v1/gametypes/{game_type_id}/rules"


def csv_url(draft_group_id: int) -> str:
    return (
        "https://www.draftkings.com/lineup/getavailableplayerscsv"
        f"?contestTypeId=21&draftGroupId={draft_group_id}"
    )


def _login(url: str) -> bool:
    path = urlparse(url).path.lower()
    return "login" in path or "signin" in path or "captcha" in path


class DeadlineBackend(httpcore.NetworkBackend):
    """Clamp every TCP, TLS, read, and write to the time still inside one deadline."""

    def __init__(self, deadline_fn, inner: httpcore.NetworkBackend | None = None):
        self._deadline_fn = deadline_fn
        self._inner = inner or httpcore.SyncBackend()

    def _allowed(self, timeout: float | None) -> float:
        left = self._deadline_fn() - time.monotonic()
        if left <= 0:
            raise CaptureFailure("http_budget_exhausted")
        if timeout is None:
            return left
        return min(float(timeout), left)

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        allowed = self._allowed(timeout)
        stream = self._inner.connect_tcp(
            host,
            port,
            timeout=allowed,
            local_address=local_address,
            socket_options=socket_options,
        )
        return _DeadlineStream(stream, self)

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        allowed = self._allowed(timeout)
        stream = self._inner.connect_unix_socket(path, timeout=allowed, socket_options=socket_options)
        return _DeadlineStream(stream, self)

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(self._allowed(seconds))


class _DeadlineStream(httpcore.NetworkStream):
    def __init__(self, inner: httpcore.NetworkStream, backend: DeadlineBackend):
        self._inner = inner
        self._backend = backend

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._inner.read(max_bytes, timeout=self._backend._allowed(timeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._inner.write(buffer, timeout=self._backend._allowed(timeout))

    def close(self) -> None:
        self._inner.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        allowed = self._backend._allowed(timeout)
        wrapped = self._inner.start_tls(
            ssl_context,
            server_hostname=server_hostname,
            timeout=allowed,
        )
        return _DeadlineStream(wrapped, self._backend)

    def get_extra_info(self, info: str):
        return self._inner.get_extra_info(info)


class BudgetHTTPTransport(httpx.BaseTransport):
    """Installed HTTP stack with a deadline checked before TCP, TLS, and every later read."""

    def __init__(self, deadline_fn, backend: httpcore.NetworkBackend | None = None):
        import ssl

        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=DeadlineBackend(deadline_fn, backend),
            retries=0,
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            resp = self._pool.handle_request(req)
        except (
            CaptureFailure,
            httpcore.TimeoutException,
            httpcore.NetworkError,
            httpcore.ProtocolError,
        ) as exc:
            _translate_httpcore(exc)
        return httpx.Response(
            status_code=resp.status,
            headers=resp.headers,
            stream=_IterableStream(resp.stream),
            extensions=resp.extensions,
        )

    def close(self) -> None:
        self._pool.close()


def _translate_httpcore(exc: BaseException) -> NoReturn:
    """Map one httpcore error onto the httpx error the client already handles.

    Header setup and a later body read use this same mapping. A deadline that is
    already spent stays ``http_budget_exhausted`` so it is not retried.
    """
    if isinstance(exc, CaptureFailure):
        raise exc
    if isinstance(exc, httpcore.ConnectTimeout):
        raise httpx.ConnectTimeout(str(exc)) from exc
    if isinstance(exc, httpcore.ReadTimeout):
        raise httpx.ReadTimeout(str(exc)) from exc
    if isinstance(exc, httpcore.WriteTimeout):
        raise httpx.WriteTimeout(str(exc)) from exc
    if isinstance(exc, httpcore.ConnectError):
        raise httpx.ConnectError(str(exc)) from exc
    if isinstance(exc, httpcore.ReadError):
        raise httpx.ReadError(str(exc)) from exc
    if isinstance(exc, httpcore.NetworkError):
        raise httpx.NetworkError(str(exc)) from exc
    if isinstance(exc, httpcore.ProtocolError):
        raise httpx.RemoteProtocolError(str(exc)) from exc
    raise exc


class _IterableStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self._chunks = chunks

    def __iter__(self):
        try:
            yield from self._chunks
        except (
            CaptureFailure,
            httpcore.TimeoutException,
            httpcore.NetworkError,
            httpcore.ProtocolError,
        ) as exc:
            _translate_httpcore(exc)

    def close(self) -> None:
        closer = getattr(self._chunks, "close", None)
        if closer is not None:
            closer()


class BoundedClient:
    """At most four logical GETs, one same-allowlist redirect, no cookie jar."""

    def __init__(self, transport, clock: Clock, sleeper):
        self.client = httpx.Client(
            transport=transport if transport is not None else BudgetHTTPTransport(self._deadline_value),
            follow_redirects=False,
            timeout=httpx.Timeout(10.0, read=30.0),
            trust_env=False,
        )
        self.clock = clock
        self.sleeper = sleeper
        self.started = clock.mono()
        self.logical = 0
        self.wire: list[tuple[str, int]] = []
        self.touched = False

    def close(self) -> None:
        timer = getattr(self, "_budget_timer", None)
        if timer is not None:
            timer.cancel()
        self.client.close()

    def _cancel_inflight(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001 - cancellation must not raise on the timer thread
            return

    def _deadline_value(self) -> float:
        """Absolute monotonic deadline shared by TCP, TLS, headers, and body."""
        if getattr(self, "_wall_deadline", None) is None:
            left = HTTP_BUDGET_S - self._elapsed()
            self._wall_deadline = time.monotonic() + max(left, 0.0)
        return self._wall_deadline

    def _arm_wall_deadline(self) -> float:
        if self._deadline_value() - time.monotonic() <= 0:
            raise CaptureFailure("http_budget_exhausted")
        return self._wall_deadline - time.monotonic()

    def _elapsed(self) -> float:
        return self.clock.mono() - self.started

    def get_json(self, url: str) -> FetchBody:
        return self._get(url, "application/json")

    def get_csv(self, url: str) -> FetchBody:
        return self._get(url, "text/csv")

    def _get(self, url: str, accept: str) -> FetchBody:
        if not allowlisted(url):
            raise CaptureFailure("http_redirect_rejected")
        if self.logical >= 4:
            raise CaptureFailure("http_request_limit")
        self.logical += 1
        last_reason = "http_timeout"
        last_body: bytes | None = None
        last_retry_after = None
        for attempt in range(3):
            if self._elapsed() > HTTP_BUDGET_S:
                raise CaptureFailure("http_budget_exhausted")
            if attempt:
                delay = 1 if attempt == 1 else 2
                if self._elapsed() + delay > HTTP_BUDGET_S:
                    raise CaptureFailure("http_budget_exhausted")
                self.sleeper(delay)
            response = None
            try:
                response = self._send(url, accept)
                return self._accepted(response, accept, redirected=False)
            except httpx.TimeoutException:
                last_reason = "http_timeout"
                continue
            except httpx.TransportError:
                last_reason = "http_server_error"
                continue
            except _Retry as retry:
                last_reason = retry.reason
                last_body = retry.body
                last_retry_after = retry.retry_after
                continue
            finally:
                if response is not None:
                    response.close()
        raise CaptureFailure(last_reason, body=last_body, retry_after=last_retry_after)

    def _over_budget(self) -> bool:
        return self._elapsed() > HTTP_BUDGET_S

    def _send(self, url: str, accept: str) -> httpx.Response:
        if self._elapsed() >= HTTP_BUDGET_S:
            raise CaptureFailure("http_budget_exhausted")
        self._arm_wall_deadline()
        self.client.cookies.clear()
        request = self.client.build_request(
            "GET",
            url,
            headers={"Accept": accept, "User-Agent": USER_AGENT},
        )
        try:
            response = send_for_budget(self.client, request, self._wall_deadline, self._cancel_inflight)
        except CaptureFailure:
            raise
        except Exception as exc:
            if time.monotonic() >= self._wall_deadline:
                raise CaptureFailure("http_budget_exhausted") from exc
            raise
        response._seam_wall_deadline = self._wall_deadline
        self.client.cookies.clear()
        self.touched = True
        self.wire.append((str(request.url), response.status_code))
        if "authorization" in {key.lower() for key in request.headers}:
            response.close()
            raise CaptureFailure("http_unexpected_status")
        return response

    def _accepted(self, response: httpx.Response, accept: str, redirected: bool) -> FetchBody:
        status = response.status_code
        deadline = self.started + HTTP_BUDGET_S
        if status in {301, 302, 303, 307, 308}:
            location = response.headers.get("location") or ""
            target = urljoin(str(response.request.url), location)
            body, truncated, _bytes_read = _read_capped(
                response, deadline=deadline, clock=self.clock
            )
            if redirected or self._over_budget():
                reason = "http_budget_exhausted" if self._over_budget() else "http_redirect_rejected"
                raise CaptureFailure(reason, body=None if truncated else body, truncated=truncated)
            if _login(target) or not allowlisted(target):
                reason = "http_login_redirect" if _login(target) else "http_redirect_rejected"
                raise CaptureFailure(reason, body=None if truncated else body, truncated=truncated)
            response.close()
            return self._accepted(self._send(target, accept), accept, redirected=True)
        body, truncated, bytes_read = _read_capped(
            response, deadline=deadline, clock=self.clock
        )
        if self._over_budget():
            raise CaptureFailure("http_budget_exhausted")
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            retry_after = retry_after.strip()[:80]
        media = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if _challenge(media, body):
            raise CaptureFailure("http_challenge", body=None if truncated else body, truncated=truncated)
        if truncated:
            raise CaptureFailure(
                "storage_guard_object",
                body=body[:OBJECT_LIMIT],
                truncated=True,
                retry_after=retry_after,
                guard_fields=_guard_fields(response, bytes_read),
            )
        if status in {401, 403}:
            raise CaptureFailure("http_denied", body=body, private=f"http_status={status}")
        if status == 429:
            raise CaptureFailure(
                "http_rate_limited",
                body=body,
                private="http_status=429",
                retry_after=retry_after,
            )
        if status >= 500:
            raise _Retry("http_server_error", body=body, retry_after=retry_after)
        if status != 200:
            raise CaptureFailure(
                "http_unexpected_status",
                body=body,
                private=f"http_status={status}",
            )
        if not _media_ok(media, accept):
            raise CaptureFailure("http_unexpected_media", body=body, private=f"media={media}")
        return FetchBody(body=body, media_type=media, fetched_at=self.clock.wall())


class _BudgetTimeout(httpx.ReadTimeout):
    """The body read was stopped because the capture budget ran out."""


class _Retry(Exception):
    def __init__(self, reason: str, body: bytes | None, retry_after: str | None):
        super().__init__(reason)
        self.reason = reason
        self.body = body
        self.retry_after = retry_after


def send_for_budget(client: httpx.Client, request: httpx.Request, wall_deadline: float, cancel) -> httpx.Response:
    """Connect, headers, and the later body share one wall deadline."""
    left = wall_deadline - time.monotonic()
    if left <= 0:
        raise CaptureFailure("http_budget_exhausted")
    request.extensions["timeout"] = {
        "connect": min(10.0, left),
        "read": min(30.0, left),
        "write": min(30.0, left),
        "pool": min(10.0, left),
    }
    timer = threading.Timer(left, cancel)
    timer.daemon = True
    timer.start()
    try:
        return client.send(request, stream=True)
    except (httpx.TransportError, OSError) as exc:
        if time.monotonic() >= wall_deadline - 0.05:
            raise CaptureFailure("http_budget_exhausted") from exc
        raise
    finally:
        timer.cancel()


def _response_socket(response: httpx.Response):
    """Socket published on the response extensions. Mock transports do not have one."""
    extensions = getattr(response, "extensions", None) or {}
    stream = extensions.get("network_stream")
    info = getattr(stream, "get_extra_info", None)
    if info is None:
        return None
    return info("socket")


def _next_bounded(chunks, response: httpx.Response, timeout_s: float):
    """Stop a blocking body read when the remaining budget is gone.

    The HTTP library copies its read timeout when the body starts. Closing the
    socket is the timeout that still applies to a later chunk.
    """
    sock = _response_socket(response)
    if sock is None:
        return next(chunks)
    cancelled = False

    def _cancel():
        nonlocal cancelled
        cancelled = True
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            try:
                sock.close()
            except OSError:
                pass

    timer = threading.Timer(max(timeout_s, 0.05), _cancel)
    timer.daemon = True
    timer.start()
    try:
        return next(chunks)
    except Exception as exc:
        if cancelled:
            raise _BudgetTimeout("remaining budget") from exc
        raise
    finally:
        timer.cancel()


def _read_capped(
    response: httpx.Response, *, deadline: float, clock: Clock
) -> tuple[bytes, bool, int]:
    """Stop at 5 MiB. Each chunk read waits at most the seconds left in the 180s budget.

    The third value is the decoded bytes pulled when reading stopped. A truncated
    read can be one chunk past the cap; that count is not the unread remainder.
    """
    limit = OBJECT_LIMIT
    buf = bytearray()
    chunks = None
    while True:
        left = deadline - clock.mono()
        wall_left = None
        wall_deadline = getattr(response, "_seam_wall_deadline", None)
        if wall_deadline is not None:
            wall_left = wall_deadline - time.monotonic()
            left = wall_left if left is None else min(left, wall_left)
        if left <= 0:
            raise CaptureFailure("http_budget_exhausted")
        read_timeout = min(30.0, left)
        if chunks is None:
            chunks = iter(response.iter_bytes())
        try:
            chunk = _next_bounded(chunks, response, read_timeout)
        except StopIteration:
            break
        except _BudgetTimeout:
            raise CaptureFailure("http_budget_exhausted") from None
        if not chunk:
            continue
        buf.extend(chunk)
        if len(buf) > limit:
            return bytes(buf[:limit]), True, len(buf)
    return bytes(buf), False, len(buf)


_ENDPOINT_PATH = re.compile(r"/[A-Za-z0-9_./-]*")


def _endpoint_path(response: httpx.Response) -> str:
    """Allowlisted path only. Query, fragment, and userinfo stay out of the log."""
    request = getattr(response, "request", None)
    url = getattr(request, "url", None)
    raw = str(getattr(url, "path", "") or "")
    path = raw.split("?", 1)[0].split("#", 1)[0]
    if path.startswith("/") and _ENDPOINT_PATH.fullmatch(path):
        return path
    return "unknown"


def _content_length(response: httpx.Response) -> int | None:
    raw = response.headers.get("content-length")
    if raw is None or not re.fullmatch(r"[0-9]+", raw.strip()):
        return None
    return int(raw.strip())


def _decoded_length(response: httpx.Response) -> int | None:
    """Decoded size only when the client already holds the whole body."""
    content = getattr(response, "_content", None)
    if isinstance(content, (bytes, bytearray)):
        return len(content)
    return None


def _guard_fields(response: httpx.Response, bytes_read: int) -> dict:
    fields: dict = {
        "path": _endpoint_path(response),
        "bytes_read": bytes_read,
        "cap": OBJECT_LIMIT,
    }
    content_length = _content_length(response)
    if content_length is not None:
        fields["content_length"] = content_length
    decoded = _decoded_length(response)
    if decoded is not None:
        fields["decoded_length"] = decoded
    return fields


def format_guard(fields: dict | None) -> str:
    """Public suffix. Path is a validated path; sizes are non-negative integers."""
    if not fields:
        return ""
    parts = []
    path = fields.get("path")
    if not isinstance(path, str) or not _ENDPOINT_PATH.fullmatch(path) or not path.startswith("/"):
        path = "unknown"
    parts.append(f"path={path}")
    for key in ("bytes_read", "cap", "content_length", "decoded_length"):
        value = fields.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            parts.append(f"{key}={value}")
    return " ".join(parts)


def _challenge(media: str, body: bytes) -> bool:
    if media in {"text/html", "application/xhtml+xml"}:
        return True
    sample = body[:2000].lower()
    if sample.startswith((b"<", b"<!doctype")):
        return True
    markers = (b"captcha", b"cf-challenge", b"challenge-platform")
    return any(marker in sample for marker in markers)


def _media_ok(media: str, accept: str) -> bool:
    if accept == "application/json":
        return media in {"application/json", "text/json"}
    if accept == "text/csv":
        return media in {"text/csv", "application/csv"}
    return False


def parse_iso(value: str) -> datetime | None:
    text_value = value.strip()
    if text_value.endswith("Z"):
        text_value = text_value[:-1] + "+00:00"
    if "." in text_value:
        left, right = text_value.split(".", 1)
        digits = []
        rest = ""
        for index, char in enumerate(right):
            if char.isdigit() and rest == "":
                digits.append(char)
            else:
                rest = right[index:]
                break
        frac = "".join(digits[:6])
        text_value = left + (("." + frac) if frac else "") + rest
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).replace(microsecond=0)


def _parse_game(item: object) -> GameEvidence:
    if not isinstance(item, dict):
        raise CaptureFailure("metadata_incomplete")
    away = item.get("AwayTeamAbbrev")
    home = item.get("HomeTeamAbbrev")
    start = item.get("StartDate")
    if not all(isinstance(value, str) and value.strip() for value in (away, home, start)):
        raise CaptureFailure("metadata_incomplete")
    kickoff = parse_iso(start)
    if kickoff is None:
        raise CaptureFailure("metadata_incomplete")
    return GameEvidence(away.strip().upper(), home.strip().upper(), kickoff)


def _parse_group(item: object) -> DraftGroup:
    if not isinstance(item, dict):
        raise CaptureFailure("metadata_incomplete")
    draft_id = item.get("DraftGroupId")
    contest = item.get("ContestTypeId")
    game_type = item.get("GameTypeId")
    if not isinstance(draft_id, int) or isinstance(draft_id, bool) or draft_id <= 0:
        raise CaptureFailure("metadata_incomplete")
    if not isinstance(contest, int) or isinstance(contest, bool):
        raise CaptureFailure("metadata_incomplete")
    parsed_type = None
    if game_type is not None:
        if not isinstance(game_type, int) or isinstance(game_type, bool) or game_type <= 0:
            raise CaptureFailure("metadata_incomplete")
        parsed_type = game_type
    games = None
    if "Games" in item:
        raw_games = item.get("Games")
        if not isinstance(raw_games, list):
            raise CaptureFailure("metadata_incomplete")
        games = tuple(_parse_game(game) for game in raw_games)
    return DraftGroup(draft_id, contest, parsed_type, games)


def parse_lobby(body: bytes) -> tuple[DraftGroup, ...]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureFailure("metadata_incomplete") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("DraftGroups"), list):
        raise CaptureFailure("metadata_incomplete")
    return tuple(_parse_group(item) for item in payload["DraftGroups"])


def _json_object(body: bytes) -> dict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureFailure("metadata_incomplete") from exc
    if not isinstance(payload, dict):
        raise CaptureFailure("metadata_incomplete")
    return payload


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _money(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return _decimal(str(value), 10, 2)
    if isinstance(value, float) and value.is_integer():
        return _decimal(str(int(value)), 10, 2)
    if isinstance(value, str):
        return _decimal(value, 10, 2)
    return None


def _team_abbr(team: object) -> str | None:
    if not isinstance(team, dict):
        return None
    abbr = team.get("abbreviation")
    if not isinstance(abbr, str) or not abbr.strip():
        return None
    return abbr.strip().upper()


def parse_draftables(body: bytes) -> DraftGroup:
    """Parse a real draftables document. Slot rows are not salary rows."""
    payload = _json_object(body)
    competitions = payload.get("competitions")
    rows = payload.get("draftables")
    if not isinstance(competitions, list) or not competitions:
        raise CaptureFailure("metadata_incomplete")
    if not isinstance(rows, list) or not rows:
        raise CaptureFailure("metadata_incomplete")
    games: list[GameEvidence] = []
    for item in competitions:
        if not isinstance(item, dict):
            raise CaptureFailure("metadata_incomplete")
        sport = item.get("sport")
        if sport is not None and sport != "NFL":
            raise CaptureFailure("metadata_incomplete")
        away = _team_abbr(item.get("awayTeam"))
        home = _team_abbr(item.get("homeTeam"))
        start = item.get("startTime")
        kickoff = parse_iso(start) if isinstance(start, str) else None
        if away is None or home is None or kickoff is None:
            raise CaptureFailure("metadata_incomplete")
        games.append(GameEvidence(away, home, kickoff))
    by_id: dict[int, DraftableFact] = {}
    by_player: dict[int, DraftableFact] = {}
    for item in rows:
        if not isinstance(item, dict):
            raise CaptureFailure("metadata_incomplete")
        draftable_id = _positive_int(item.get("draftableId"))
        player_id = _positive_int(item.get("playerId"))
        salary = _money(item.get("salary"))
        position = item.get("position")
        team = item.get("teamAbbreviation")
        name = item.get("displayName")
        if (
            draftable_id is None
            or player_id is None
            or salary is None
            or not isinstance(position, str)
            or not position.strip()
            or not isinstance(team, str)
            or not team.strip()
            or not isinstance(name, str)
            or not name.strip()
        ):
            raise CaptureFailure("metadata_incomplete")
        fact = DraftableFact(
            draftable_id,
            player_id,
            salary,
            position.strip().upper(),
            team.strip().upper(),
            name.strip(),
        )
        prior = by_id.get(draftable_id)
        if prior is not None and prior != fact:
            raise CaptureFailure("draftables_mismatch")
        by_id[draftable_id] = fact
        same_player = by_player.get(player_id)
        if same_player is not None and (
            same_player.salary != fact.salary
            or same_player.position != fact.position
            or same_player.team != fact.team
            or same_player.name != fact.name
        ):
            raise CaptureFailure("draftables_mismatch")
        by_player[player_id] = fact
    evidence = DraftablesEvidence(by_id, len(rows), len(by_player))
    return DraftGroup(0, None, None, tuple(games), evidence)


def reconcile_draftables(evidence: DraftablesEvidence, assessed: list[dict]) -> list[str]:
    """CSV is the salary authority. Draftables slot count must not replace it."""
    reasons: list[str] = []
    if len(assessed) != evidence.player_count:
        reasons.append("draftables_mismatch")
    if evidence.slot_count != evidence.player_count and len(assessed) == evidence.slot_count:
        reasons.append("draftables_mismatch")
    seen: set[int] = set()
    for row in assessed:
        token = str(row.get("dk_id") or "")
        fact = evidence.by_id.get(int(token)) if token.isdigit() else None
        if fact is None or fact.player_id in seen:
            reasons.append("draftables_mismatch")
            continue
        seen.add(fact.player_id)
        if (
            fact.salary != row.get("salary")
            or fact.position != str(row.get("position") or "").upper()
            or fact.team != str(row.get("team") or "").upper()
            or fact.name != str(row.get("name") or "").strip()
        ):
            reasons.append("draftables_mismatch")
    if not reasons:
        return []
    return ["draftables_mismatch"]


def parse_group_document(body: bytes) -> DraftGroup:
    payload = _json_object(body)
    if "draftables" in payload and "competitions" in payload:
        return parse_draftables(body)
    return _parse_group(payload)


def parse_rules(body: bytes) -> RulesVerdict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return RulesVerdict(False, "missing_rules", None)
    if not isinstance(payload, dict):
        return RulesVerdict(False, "missing_rules", None)
    slots = payload.get("rosterSlots")
    names: list[str] = []
    if not isinstance(slots, list) or not slots:
        return RulesVerdict(False, "missing_rules", None)
    for slot in slots:
        if isinstance(slot, str) and slot.strip():
            names.append(slot.strip().upper())
        elif isinstance(slot, dict) and isinstance(slot.get("name"), str) and slot["name"].strip():
            names.append(slot["name"].strip().upper())
        else:
            return RulesVerdict(False, "missing_rules", None)
    if any(name == "CPT" for name in names):
        return RulesVerdict(False, "captain_slot", None)
    cap = payload.get("salaryCap")
    if isinstance(cap, float) and cap.is_integer():
        cap = int(cap)
    if cap != 50000 or Counter(names) != Counter(CLASSIC_SLOTS):
        return RulesVerdict(False, "missing_rules", None)
    return RulesVerdict(True, None, tuple(names))


def _kickoff_from_row(token: str) -> GameEvidence | None:
    match = _GAME_INFO.fullmatch(token.strip())
    if match is None:
        return None
    away, home, month, day, year, hour, minute, ampm = match.groups()
    hour_i = int(hour)
    if ampm.upper() == "PM" and hour_i != 12:
        hour_i += 12
    if ampm.upper() == "AM" and hour_i == 12:
        hour_i = 0
    if hour_i > 23:
        return None
    try:
        local = datetime(int(year), int(month), int(day), hour_i, int(minute), tzinfo=ET)
    except ValueError:
        return None
    return GameEvidence(away.upper(), home.upper(), local.astimezone(UTC).replace(microsecond=0))


def _decimal(token: str, precision: int, scale: int) -> Decimal | None:
    text_value = token.strip().replace("$", "").replace(",", "")
    if text_value == "" or re.fullmatch(r"\d+(\.\d+)?", text_value) is None:
        return None
    try:
        number = Decimal(text_value)
    except InvalidOperation:
        return None
    quantized = number.quantize(Decimal(1).scaleb(-scale))
    if quantized != number:
        return None
    digits = abs(int(number))
    if len(str(digits)) > precision - scale:
        return None
    return number


@dataclass(frozen=True)
class ParsedCsv:
    headers: tuple[str, ...]
    rows: tuple[dict, ...]


def parse_csv_bytes(body: bytes) -> ParsedCsv:
    try:
        text_value = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CaptureFailure("parse_failure") from exc
    try:
        reader = csv.reader(io.StringIO(text_value, newline=""))
        header = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise CaptureFailure("parse_failure") from exc
    if not any(cell.strip() for cell in header):
        raise CaptureFailure("parse_failure")
    missing = [name for name in REQUIRED_HEADERS if name not in header]
    if missing:
        raise CaptureFailure("parse_failure")
    rows = []
    number = 0
    try:
        records = list(reader)
    except csv.Error as exc:
        raise CaptureFailure("parse_failure") from exc
    for cells in records:
        if not any(cell.strip() for cell in cells):
            continue
        number += 1
        pairs = []
        width = max(len(header), len(cells))
        for index in range(width):
            key = header[index] if index < len(header) else f"extra_{index + 1}"
            value = cells[index] if index < len(cells) else ""
            pairs.append((key, value))
        rows.append({"row_number": number, "raw_fields": tuple(pairs)})
    if not rows:
        raise CaptureFailure("parse_failure")
    return ParsedCsv(tuple(header), tuple(rows))


def _cell(raw_fields: tuple[tuple[str, str], ...], name: str) -> str:
    for key, value in raw_fields:
        if key == name:
            return value
    return ""


def assess_rows(parsed: ParsedCsv) -> tuple[list[dict], list[str]]:
    file_reasons: list[str] = []
    assessed = []
    seen: dict[str, int] = {}
    for row in parsed.rows:
        raw = row["raw_fields"]
        reasons: list[str] = []
        name = _cell(raw, "Name").strip()
        dk_id = _cell(raw, "ID").strip()
        roster = _cell(raw, "Roster Position").strip()
        team = _cell(raw, "TeamAbbrev").strip().upper()
        game_info = _cell(raw, "Game Info")
        salary_token = _cell(raw, "Salary")
        avg_token = _cell(raw, "AvgPointsPerGame")
        status = _cell(raw, "Status")
        if name == "" or dk_id == "":
            reasons.append("missing_name")
        if "CPT" in roster.upper():
            reasons.append("captain_slot")
        game = _kickoff_from_row(game_info)
        if game is None or team == "" or team not in {game.away, game.home}:
            reasons.append("missing_team_or_game")
        salary = _decimal(salary_token, 10, 2)
        if salary is None:
            reasons.append("invalid_salary")
        avg = None
        if avg_token.strip() != "":
            avg = _decimal(avg_token, 12, 4)
            if avg is None:
                reasons.append("invalid_avg")
        if dk_id:
            seen[dk_id] = seen.get(dk_id, 0) + 1
        assessed.append(
            {
                "row_number": row["row_number"],
                "raw_fields": raw,
                "dk_id": dk_id,
                "name": name,
                "position": _cell(raw, "Position").strip(),
                "roster": roster,
                "team": team,
                "game_info": game_info,
                "status_raw": status if "Status" in {key for key, _value in raw} else None,
                "salary": salary,
                "avg": avg,
                "game": game,
                "reasons": reasons,
            }
        )
    duplicates = {dk_id for dk_id, count in seen.items() if count > 1}
    if duplicates:
        file_reasons.append("duplicate_dk_id")
        for row in assessed:
            if row["dk_id"] in duplicates and "duplicate_dk_id" not in row["reasons"]:
                row["reasons"].append("duplicate_dk_id")
    games = { _game_tuple(row["game"]) for row in assessed if row["game"] is not None }
    games.discard(None)
    if len(games) <= 1:
        file_reasons.append("one_game")
    teams_games: dict[str, set] = {}
    for row in assessed:
        game = row["game"]
        if game is None or not row["team"]:
            continue
        teams_games.setdefault(row["team"], set()).add(_game_tuple(game))
    if any(len(found) > 1 for found in teams_games.values()):
        file_reasons.append("contradictory_rows")
    return assessed, file_reasons


def _game_tuple(game: GameEvidence | None):
    if game is None:
        return None
    return (game.away, game.home, game.kickoff_at)


def _priority(reasons: list[str]) -> str:
    order = (
        "parse_failure",
        "captain_slot",
        "one_game",
        "not_classic",
        "duplicate_dk_id",
        "invalid_salary",
        "invalid_avg",
        "missing_name",
        "missing_team_or_game",
        "contradictory_rows",
        "mismatched_metadata",
        "inexact_game_set",
        "wrong_season_week",
        "missing_rules",
        "draftables_mismatch",
        "ambiguous_slate",
        "slate_unavailable",
        "metadata_incomplete",
        "schedule_evidence_missing",
    )
    for reason in order:
        if reason in reasons:
            return reason
    return reasons[0] if reasons else "rejected"


def load_schedule(conn, now: datetime) -> tuple[str, tuple[RegGame, ...], dict]:
    """Return gap, verified, or missing. Completeness comes from the pinned authority."""
    from loader.schedule_proof import verify_schedule

    verdict = verify_schedule(conn, now)
    games = []
    for row in verdict.games:
        if row["gametime"] is None:
            continue
        kickoff = _gametime(date.fromisoformat(row["gameday"]), row["gametime"])
        if kickoff is None:
            return "schedule_evidence_missing", (), verdict.metadata
        if WEEKDAYS[kickoff.astimezone(ET).weekday()].lower() != str(row["weekday"]).strip().lower():
            return "schedule_evidence_missing", (), verdict.metadata
        games.append(
            RegGame(
                row["game_id"],
                int(row["season"]),
                int(row["week"]),
                date.fromisoformat(row["gameday"]),
                str(row["weekday"]),
                kickoff,
                row["away_team"],
                row["home_team"],
            )
        )
    return verdict.evidence, tuple(games), verdict.metadata


def _gametime(gameday: date, gametime: str) -> datetime | None:
    match = re.fullmatch(r"(\d{2}):(\d{2})", str(gametime).strip())
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    local = datetime(gameday.year, gameday.month, gameday.day, hour, minute, tzinfo=ET)
    return local.astimezone(UTC).replace(microsecond=0)


def _in_season(now: datetime, games: tuple[RegGame, ...]) -> bool:
    if not games:
        return False
    moment = now.astimezone(UTC)
    by_season: dict[int, list[datetime]] = {}
    for game in games:
        by_season.setdefault(game.season, []).append(game.kickoff_at)
    return any(min(times) <= moment <= max(times) for times in by_season.values())


def upcoming_sunday(now: datetime) -> date:
    local = now.astimezone(ET)
    return local.date() + timedelta(days=(6 - local.weekday()) % 7)


def sunday_afternoon(kickoff: datetime) -> bool:
    local = kickoff.astimezone(ET)
    if WEEKDAYS[local.weekday()] != "Sunday":
        return False
    minutes = local.hour * 60 + local.minute
    return 13 * 60 <= minutes <= 16 * 60 + 30


def expected_sunday_games(games: tuple[RegGame, ...], sunday: date) -> tuple[RegGame, ...]:
    return tuple(
        game
        for game in games
        if game.kickoff_at.astimezone(ET).date() == sunday and sunday_afternoon(game.kickoff_at)
    )


def week_of(games: tuple[RegGame, ...], sunday: date) -> tuple[int, int] | None:
    start = sunday - timedelta(days=3)
    end = sunday + timedelta(days=1)
    near = [game for game in games if start <= game.gameday <= end]
    pool = near or [
        game for game in games if game.kickoff_at.astimezone(ET).date() == sunday
    ]
    keys = {(game.season, game.week) for game in pool}
    if len(keys) != 1:
        return None
    return keys.pop()


def _keys(games) -> set[tuple[str, str, datetime]]:
    return {(game.away, game.home, game.kickoff_at) for game in games}


def _match_groups(groups: tuple[DraftGroup, ...], expected: set[tuple]) -> tuple[str, DraftGroup | None]:
    classic = [
        group
        for group in groups
        if group.contest_type_id == 21 and group.games is not None
    ]
    exact = [group for group in classic if _keys(group.games or ()) == expected]
    if len(exact) > 1:
        return "ambiguous_slate", None
    if len(exact) == 1:
        return "ok", exact[0]
    if any(_keys(group.games or ()) & expected for group in classic):
        return "inexact_game_set", None
    return "slate_unavailable", None


def _release(conn) -> None:
    if conn.in_transaction():
        conn.commit()


def _duration_ms(clock: Clock, started_mono: float) -> int:
    elapsed = clock.mono() - started_mono
    duration = int(elapsed * 1000)
    if duration < 0:
        raise CaptureFailure("clock_monotonic")
    return duration


def _terminal_metadata(client: BoundedClient | None, label: str | None, extra: dict) -> dict:
    requests = []
    if client is not None:
        for url, status in client.wire:
            parsed = urlparse(url)
            requests.append({"host": parsed.hostname, "path": parsed.path, "status": status})
    metadata = {
        "parser_version": PARSER_VERSION,
        "slate_label": label,
        "requests": requests,
        "truncated": False,
        "retained_artifact": True,
    }
    metadata.update(extra)
    return metadata


def run_capture(
    engine,
    *,
    season: int | None,
    week: int | None,
    trigger: str,
    selection: str | None,
    draft_group_id: str | None,
    transport=None,
    clock: Clock | None = None,
    sleeper=None,
    failpoint: str | None = None,
    before_terminal=None,
) -> AttemptResult:
    clock = clock or system_clock()
    sleeper = sleeper or time.sleep
    try:
        conn = engine.connect()
    except Exception:  # noqa: BLE001 - connection failure must not echo the URL
        return AttemptResult(False, False, "database_unreachable", "unreached", season, week, 0)
    try:
        try:
            conn.execute(text("SELECT 1"))
            conn.commit()
        except Exception:  # noqa: BLE001 - connection failure must not echo the URL
            return AttemptResult(False, False, "database_unreachable", "unreached", season, week, 0)
        lock_capture(conn)
        try:
            return _locked(
                conn,
                season=season,
                week=week,
                trigger=trigger,
                selection=selection,
                draft_group_id=draft_group_id,
                transport=transport,
                clock=clock,
                sleeper=sleeper,
                failpoint=failpoint,
                before_terminal=before_terminal,
            )
        finally:
            unlock_capture(conn)
    finally:
        conn.close()


def _locked(conn, **kwargs) -> AttemptResult:
    clock: Clock = kwargs["clock"]
    reconcile(conn, finished_at=clock.wall())
    opened = clock.wall()
    started_mono = clock.mono()
    evidence, games, schedule_meta = load_schedule(conn, opened)
    _release(conn)
    plan = _plan(
        evidence=evidence,
        games=games,
        now=opened,
        season=kwargs["season"],
        week=kwargs["week"],
        trigger=kwargs["trigger"],
        selection=kwargs["selection"],
        draft_group_id=kwargs["draft_group_id"],
    )
    run_id = insert_running_load_run(
        conn,
        run_group=uuid4(),
        season=plan["season"],
        trigger=kwargs["trigger"],
        started_at=opened,
    )
    observation_id = uuid4()
    insert_running_observation(
        conn,
        observation_id=observation_id,
        load_run_id=run_id,
        requested_at=opened,
        started_at=opened,
        observed_at=opened,
        loaded_at=opened,
    )
    state = _State(conn, clock, kwargs["sleeper"], kwargs["transport"], opened, started_mono)
    state.run_id = run_id
    state.observation_id = observation_id
    state.failpoint = kwargs["failpoint"]
    state.before_terminal = kwargs["before_terminal"]
    state.season = plan["season"]
    state.week = plan["week"]
    state.label = plan["label"]
    state.schedule_meta = schedule_meta
    try:
        if plan["stop"] is not None:
            raise CaptureFailure(plan["stop"])
        _capture_body(state, plan, games)
        return _finish_success(state)
    except Crash:
        raise
    except CaptureFailure as exc:
        return _finish_failure(state, exc)
    except PrivateWriteError as exc:
        return _finish_failure(state, CaptureFailure(exc.reason, private=exc.private))
    except IntegrityError as exc:
        failure = _integrity(exc)
        return _finish_failure(state, failure)
    except Exception:  # noqa: BLE001 - public output stays a reason code
        return _finish_failure(state, CaptureFailure("capture_failed"))


@dataclass
class _State:
    conn: object
    clock: Clock
    sleeper: object
    transport: object
    opened: datetime
    started_mono: float
    run_id: int = 0
    observation_id: UUID | None = None
    failpoint: str | None = None
    before_terminal: object = None
    season: int | None = None
    week: int | None = None
    label: str | None = None
    client: BoundedClient | None = None
    artifacts: list = None
    invocation_bytes: int = 0
    csv_sha: str | None = None
    csv_artifact: int | None = None
    fetched_at: datetime | None = None
    rows_read: int = 0
    rows_upserted: int = 0
    rows_skipped: int = 0
    snapshot_id: UUID | None = None
    headers: tuple[str, ...] = ()

    def __post_init__(self):
        self.artifacts = []


def _plan(*, evidence, games, now, season, week, trigger, selection, draft_group_id) -> dict:
    label = None
    stop = None
    derived_season = season
    derived_week = week
    mode = "explicit" if draft_group_id else "sunday"
    if selection and draft_group_id:
        stop = "invalid_selector"
    elif selection == "sunday-afternoon":
        label = SlateLabel.SUNDAY_MAIN.value
        mode = "sunday"
    elif draft_group_id:
        if not (draft_group_id.isdigit() and int(draft_group_id) > 0):
            stop = "invalid_draft_group"
        label = SlateLabel.EXPLICIT_GROUP.value
        mode = "explicit"
    else:
        stop = "invalid_selector"
    if stop is None and evidence == "gap":
        stop = "off_season"
    elif stop is None and evidence != "verified":
        stop = "schedule_evidence_missing"
    if stop is None and mode == "sunday":
        sunday = upcoming_sunday(now)
        expected = expected_sunday_games(games, sunday)
        identity = week_of(games, sunday)
        if identity is None:
            stop = "schedule_evidence_missing"
        else:
            derived_season, derived_week = identity
            if season is None and week is None:
                if trigger != "schedule":
                    stop = "season_week_required"
            elif (season, week) != identity:
                stop = "wrong_season_week"
            if stop is None and not expected:
                stop = "slate_unavailable"
    if stop is None and mode == "explicit":
        if season is None or week is None:
            stop = "season_week_required"
        else:
            derived_season, derived_week = season, week
    return {
        "stop": stop,
        "mode": mode,
        "season": derived_season,
        "week": derived_week,
        "label": label,
        "draft_group_id": int(draft_group_id) if draft_group_id and draft_group_id.isdigit() else None,
        "expected": expected_sunday_games(games, upcoming_sunday(now)) if evidence == "verified" else (),
    }


def _capture_body(state: _State, plan: dict, games: tuple[RegGame, ...]) -> None:
    state.client = BoundedClient(state.transport, state.clock, state.sleeper)
    try:
        if plan["mode"] == "sunday":
            group = _select_sunday(state, plan["expected"])
        else:
            group = _select_explicit(state, plan, games)
        verdict = _verify_rules(state, group)
        if not verdict.verified:
            raise CaptureFailure(verdict.reason or "missing_rules")
        fetched = state.client.get_csv(csv_url(group.draft_group_id))
        state.fetched_at = fetched.fetched_at
        ref = _keep(state, fetched.body, ArtifactKind.CSV, fetched.media_type or "text/csv")
        state.csv_sha = ref.sha256
        state.csv_artifact = ref.artifact_id
        parsed = parse_csv_bytes(fetched.body)
        state.headers = parsed.headers
        assessed, file_reasons = assess_rows(parsed)
        state.rows_read = len(assessed)
        _store_rows(state, assessed)
        reasons = list(file_reasons)
        for row in assessed:
            reasons.extend(row["reasons"])
        csv_keys = {_game_tuple(row["game"]) for row in assessed if row["game"] is not None}
        csv_keys.discard(None)
        if _keys(group.games or ()) != csv_keys:
            reasons.append("mismatched_metadata")
        if group.draftables is not None:
            reasons.extend(reconcile_draftables(group.draftables, assessed))
        if reasons:
            raise CaptureFailure(_priority(reasons))
        _publish(state, group, verdict, assessed, games)
    finally:
        if state.client is not None:
            state.client.close()


def _select_sunday(state: _State, expected: tuple[RegGame, ...]) -> DraftGroup:
    fetched = state.client.get_json(LOBBY_URL)
    state.fetched_at = fetched.fetched_at
    _keep(state, fetched.body, ArtifactKind.LOBBY_JSON, fetched.media_type or "application/json")
    groups = list(parse_lobby(fetched.body))
    incomplete = [group for group in groups if group.contest_type_id == 21 and group.games is None]
    if incomplete and len(incomplete) > 1:
        raise CaptureFailure("metadata_incomplete")
    if len(incomplete) == 1:
        groups = [_hydrate(state, group) if group.games is None else group for group in groups]
    reason, chosen = _match_groups(tuple(groups), _keys(expected))
    if chosen is None:
        raise CaptureFailure(reason)
    if chosen.game_type_id is None:
        chosen = _hydrate(state, chosen)
        reason, again = _match_groups((chosen,), _keys(expected))
        if again is None:
            raise CaptureFailure(reason)
        chosen = again
    if chosen.game_type_id is None or chosen.contest_type_id != 21:
        raise CaptureFailure("metadata_incomplete" if chosen.game_type_id is None else "not_classic")
    if _keys(chosen.games or ()) != _keys(expected):
        raise CaptureFailure("mismatched_metadata")
    return chosen


def _select_explicit(state: _State, plan: dict, games: tuple[RegGame, ...]) -> DraftGroup:
    fetched = state.client.get_json(group_url(plan["draft_group_id"]))
    state.fetched_at = fetched.fetched_at
    _keep(state, fetched.body, ArtifactKind.LOBBY_JSON, fetched.media_type or "application/json")
    group = parse_group_document(fetched.body)
    if group.games is None:
        raise CaptureFailure("metadata_incomplete")
    if group.draft_group_id != plan["draft_group_id"]:
        raise CaptureFailure("mismatched_metadata")
    if group.draftables is None and group.contest_type_id != 21:
        raise CaptureFailure("not_classic")
    if len(group.games) <= 1:
        raise CaptureFailure("one_game")
    week_games = [
        game for game in games if game.season == plan["season"] and game.week == plan["week"]
    ]
    if not _keys(group.games) <= _keys(week_games):
        raise CaptureFailure("wrong_season_week")
    if group.game_type_id is None:
        raise CaptureFailure("metadata_incomplete")
    return group


def _hydrate(state: _State, group: DraftGroup) -> DraftGroup:
    fetched = state.client.get_json(group_url(group.draft_group_id))
    _keep(state, fetched.body, ArtifactKind.LOBBY_JSON, fetched.media_type or "application/json")
    loaded = parse_group_document(fetched.body)
    if loaded.draft_group_id not in (0, group.draft_group_id):
        raise CaptureFailure("mismatched_metadata")
    return DraftGroup(
        group.draft_group_id,
        loaded.contest_type_id if loaded.contest_type_id is not None else group.contest_type_id,
        loaded.game_type_id or group.game_type_id,
        loaded.games if loaded.games is not None else group.games,
        loaded.draftables if loaded.draftables is not None else group.draftables,
    )


def _verify_rules(state: _State, group: DraftGroup) -> RulesVerdict:
    fetched = state.client.get_json(rules_url(group.game_type_id))
    ref = _keep(state, fetched.body, ArtifactKind.RULES_JSON, fetched.media_type or "application/json")
    verdict = parse_rules(fetched.body)
    state.rules_artifact = ref.artifact_id
    state.rules_sha = ref.sha256
    state.game_type_id = group.game_type_id
    state.rules = verdict
    return verdict


def _keep(state: _State, body: bytes, kind: ArtifactKind, media_type: str):
    state.invocation_bytes += len(body)
    ref = store_artifact(
        state.conn,
        body=body,
        kind=kind,
        media_type=media_type,
        stored_at=state.clock.wall(),
        invocation_bytes=state.invocation_bytes,
    )
    state.artifacts.append(ref.artifact_id)
    return ref


def _store_rows(state: _State, assessed: list[dict]) -> None:
    ledger = tuple(
        LedgerRow(
            row_number=row["row_number"],
            raw_fields=row["raw_fields"],
            parse_status=ParseStatus.REJECTED if row["reasons"] else ParseStatus.PARSED,
            reason_codes=tuple(row["reasons"]),
        )
        for row in assessed
    )
    state.rows_skipped = sum(1 for row in assessed if row["reasons"])
    store_ledger(
        state.conn,
        artifact_id=state.csv_artifact,
        rows=ledger,
        loaded_at=state.clock.wall(),
    )


def _publish(state: _State, group: DraftGroup, verdict: RulesVerdict, assessed, games) -> None:
    by_key = {_game_tuple_reg(game): game for game in games}
    game_rows = []
    for evidence in sorted(group.games or (), key=lambda item: (item.kickoff_at, item.away, item.home)):
        reg = by_key.get((evidence.away, evidence.home, evidence.kickoff_at))
        game_rows.append(
            {
                "away": evidence.away,
                "home": evidence.home,
                "kickoff_at": evidence.kickoff_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "game_id": None if reg is None else reg.game_id,
            }
        )
    rules_payload = {
        "rules_id": None,
        "roster_slots": list(verdict.slots or ()),
        "salary_cap": 50000,
        "evidence_artifact_id": state.rules_artifact,
    }
    identity = {
        "contest_type_id": 21,
        "draft_group_id": str(group.draft_group_id),
        "games": game_rows,
        "parser_version": PARSER_VERSION,
        "rules": {"roster_slots": list(verdict.slots or ()), "salary_cap": 50000},
        "rules_artifact_sha256": state.rules_sha,
        "game_type_id": state.game_type_id,
        "season": state.season,
        "season_type": "REG",
        "week": state.week,
    }
    metadata_sha = canonical_sha256(identity)
    existing = find_snapshot(
        state.conn,
        artifact_id=state.csv_artifact,
        source_snapshot_key=str(group.draft_group_id),
        metadata_sha256=metadata_sha,
    )
    _release(state.conn)
    now = state.clock.wall()
    snapshot_id = existing or uuid4()
    fields = {
        "snapshot_id": snapshot_id,
        "source": Source.DK_LOBBY.value,
        "artifact_id": state.csv_artifact,
        "parser_version": PARSER_VERSION,
        "metadata_sha256": metadata_sha,
        "source_snapshot_key": str(group.draft_group_id),
        "season": state.season,
        "season_type": "REG",
        "week": state.week,
        "draft_group_id": str(group.draft_group_id),
        "games": json.dumps(game_rows),
        "rules": json.dumps(rules_payload),
        "game_set_sha256": canonical_sha256(game_rows),
        "rules_sha256": canonical_sha256(rules_payload),
        "source_pool_kind": PoolKind.FULL_EXPORT.value,
        "metadata": json.dumps(
            {
                "headers": list(state.headers),
                "row_count": len(assessed),
                "raw_retained": True,
                "slate_label": state.label,
                "parser_version": PARSER_VERSION,
                "draftables_slot_count": None
                if group.draftables is None
                else group.draftables.slot_count,
                "draftables_player_count": None
                if group.draftables is None
                else group.draftables.player_count,
            }
        ),
        "created_at": now,
        "loaded_at": now,
    }
    salary_rows = []
    if existing is None:
        for row in assessed:
            salary_rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "row_number": row["row_number"],
                    "artifact_id": state.csv_artifact,
                    "parser_version": PARSER_VERSION,
                    "row_status": RowStatus.VALID.value,
                    "reason_codes": "[]",
                    "salary": row["salary"],
                    "dk_id": row["dk_id"],
                    "name_raw": row["name"],
                    "position_raw": row["position"],
                    "roster_position_raw": row["roster"],
                    "team_raw": row["team"],
                    "game_info_raw": row["game_info"],
                    "avg_points_per_game": row["avg"],
                    "status_raw": row["status_raw"],
                    "loaded_at": now,
                }
            )
    state.snapshot_id = snapshot_id
    state.rows_upserted = 0 if existing is not None else len(salary_rows)
    state._publish_fields = fields
    state._salary_rows = salary_rows
    state._reused = existing is not None


def _game_tuple_reg(game: RegGame):
    return (game.away, game.home, game.kickoff_at)


def _finish_success(state: _State) -> AttemptResult:
    _write_terminal(
        state,
        status=ObservationStatus.SUCCEEDED,
        reason="captured",
        snapshot_id=state.snapshot_id,
        publish=True,
    )
    _audit(state, "succeeded", "captured", state.rows_upserted, 1)
    return AttemptResult(
        True, True, "captured", "succeeded", state.season, state.week, state.rows_read
    )


def _finish_failure(state: _State, exc: CaptureFailure) -> AttemptResult:
    if exc.truncated:
        _note_truncated(state, exc)
    elif exc.body:
        try:
            _keep(state, exc.body, ArtifactKind.REJECTED_BODY, "application/octet-stream")
        except (PrivateWriteError, CaptureFailure) as keep_exc:
            exc = CaptureFailure(getattr(keep_exc, "reason", exc.reason), private=exc.private)
    status = ObservationStatus.SKIPPED if exc.reason == "off_season" else (
        ObservationStatus.REJECTED
        if exc.reason
        in {
            "invalid_salary",
            "invalid_avg",
            "missing_name",
            "missing_team_or_game",
            "contradictory_rows",
            "duplicate_dk_id",
            "captain_slot",
            "one_game",
            "not_classic",
            "mismatched_metadata",
            "inexact_game_set",
            "missing_rules",
            "parse_failure",
        }
        else ObservationStatus.FAILED
    )
    private = _bound_private(exc.private)
    if exc.retry_after and _REASON.fullmatch(str(exc.retry_after).replace(" ", "")):
        private = _bound_private(
            ((private + ";") if private else "") + "retry_after=" + str(exc.retry_after).strip()[:40]
        )
    guard_fields = exc.guard_fields
    exc = CaptureFailure(
        _public_reason(exc.reason),
        private=private or "",
        body=exc.body,
        truncated=exc.truncated,
        retry_after=None,
        guard_fields=guard_fields,
    )
    _write_terminal(
        state,
        status=status,
        reason=exc.reason,
        snapshot_id=None,
        publish=False,
        error_private=private or None,
    )
    public_status = "succeeded" if exc.reason == "off_season" else "failed"
    _audit(state, public_status, exc.reason, 0, 0)
    return AttemptResult(
        exc.reason == "off_season",
        True,
        exc.reason,
        public_status,
        state.season,
        state.week,
        state.rows_read,
        format_guard(exc.guard_fields) if exc.reason == "storage_guard_object" else "",
    )


def _note_truncated(state: _State, exc: CaptureFailure) -> None:
    prefix = exc.body or b""
    state.truncated_meta = {
        "truncated": True,
        "prefix_sha256": sha256_bytes(prefix),
        "prefix_bytes": len(prefix),
        "retained_artifact": False,
    }
    fields = exc.guard_fields or {}
    for key in ("path", "bytes_read", "cap", "content_length", "decoded_length"):
        if key in fields:
            state.truncated_meta[key] = fields[key]


def _write_terminal(
    state: _State,
    *,
    status: ObservationStatus,
    reason: str,
    snapshot_id: UUID | None,
    publish: bool,
    error_private: str | None = None,
) -> None:
    if state.failpoint == "before_terminal":
        raise Crash(state.failpoint)
    if state.before_terminal is not None:
        state.before_terminal()
    duration_ms = _duration_ms(state.clock, state.started_mono)
    finished_at = state.clock.wall()
    metadata = _terminal_metadata(
        state.client,
        state.label,
        {
            "draft_group_id": None
            if state.snapshot_id is None and not publish
            else getattr(state, "draft_group_seen", None),
            "auxiliary_artifact_ids": list(state.artifacts),
            "retry_after": None,
        },
    )
    if getattr(state, "truncated_meta", None):
        metadata.update(state.truncated_meta)
    if getattr(state, "schedule_meta", None):
        metadata.update(state.schedule_meta)
    try:
        with state.conn.begin():
            if state.failpoint == "constraint":
                state.failpoint = None
                state.conn.execute(
                    text(
                        """
                        INSERT INTO salary_private.salary_artifacts (
                            source, sha256, body, byte_count, media_type, artifact_kind,
                            stored_at, loaded_at
                        ) VALUES (
                            'dk_lobby', :sha, ''::bytea, 1, 'text/plain', 'csv',
                            :now, :now
                        )
                        """
                    ),
                    {"sha": "a" * 64, "now": finished_at},
                )
            if publish:
                if not state._reused:
                    insert_snapshot(
                        state.conn,
                        snapshot_id=state.snapshot_id,
                        fields=state._publish_fields,
                        salary_rows=state._salary_rows,
                    )
                if state.failpoint == "crash_during_publish":
                    raise Crash(state.failpoint)
            if state.failpoint == "crash_during_publish" and not publish:
                raise Crash(state.failpoint)
            finish_observation(
                state.conn,
                observation_id=state.observation_id,
                status=status,
                finished_at=finished_at,
                duration_ms=duration_ms,
                artifact_id=state.csv_artifact or (state.artifacts[-1] if state.artifacts else None),
                snapshot_id=snapshot_id,
                fetched_at=state.fetched_at,
                reason_code=reason,
                error_private=error_private,
                metadata=metadata,
            )
            if publish:
                assert_actual_ceiling(state.conn)
    except Crash:
        raise
    except IntegrityError as exc:
        raise_private(exc)
    if state.failpoint == "after_publish":
        raise Crash(state.failpoint)


def _audit(state: _State, status: str, reason: str, upserted: int, snapshots: int) -> None:
    finish_load_run(
        state.conn,
        state.run_id,
        status=status,
        finished_at=state.clock.wall(),
        notes=public_note(reason, state.rows_read, snapshots),
        error=None if status == "succeeded" else reason,
        rows_read=state.rows_read,
        rows_upserted=upserted,
        rows_skipped=state.rows_skipped,
        source_version=state.csv_sha,
    )


def _integrity(exc: IntegrityError) -> CaptureFailure:
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None) or "constraint_failure"
    return CaptureFailure("constraint_failure", private=str(sqlstate))


def reconcile_open_attempts(engine, *, clock: Clock | None = None) -> None:
    clock = clock or system_clock()
    conn = engine.connect()
    try:
        lock_capture(conn)
        try:
            reconcile(conn, finished_at=clock.wall())
        finally:
            unlock_capture(conn)
    finally:
        conn.close()


def _public_reason(reason: str | None) -> str:
    if reason and _REASON.fullmatch(reason):
        return reason
    return "capture_failed"


def _bound_private(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9=_;:.-]", "", value)[:120]
    return cleaned or None


def _report(result: AttemptResult) -> None:
    reason = _public_reason(result.reason)
    if not result.persisted and reason == "database_unreachable":
        print("database_unreachable", file=sys.stderr)
        return
    season = "-" if result.season is None else str(result.season)
    week = "-" if result.week is None else str(result.week)
    suffix = f" {result.guard}" if reason == "storage_guard_object" and result.guard else ""
    print(
        f"dk_lobby_salaries season={season} week={week} "
        f"status={result.status} reason={reason} rows={result.rows}{suffix}",
        flush=True,
    )
    if result.status == "failed":
        print(reason, file=sys.stderr)


def main(
    argv: list[str] | None = None,
    *,
    transport=None,
    clock: Clock | None = None,
    sleeper=None,
    failpoint: str | None = None,
    before_terminal=None,
    engine=None,
) -> int:
    parser = argparse.ArgumentParser(prog="loader.dk_lobby")
    parser.add_argument("--season", default=None)
    parser.add_argument("--week", default=None)
    parser.add_argument("--draft-group-id", default=None)
    parser.add_argument("--selection", default=None)
    parser.add_argument(
        "--trigger",
        choices=["local", "manual", "schedule", "scheduled"],
        default="local",
    )
    args = parser.parse_args(argv)
    try:
        trigger = normalize_trigger(args.trigger)
        season = None if args.season in (None, "") else int(str(args.season).strip())
        week = None if args.week in (None, "") else int(str(args.week).strip())
    except (CaptureFailure, ValueError):
        print("invalid_season_week", file=sys.stderr)
        return 1
    if season is not None and (season < SEASON_MIN or season > SEASON_MAX):
        print("season_out_of_range", file=sys.stderr)
        return 1
    if week is not None and (week < WEEK_MIN or week > WEEK_MAX):
        print("week_out_of_range", file=sys.stderr)
        return 1
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("database_unreachable", file=sys.stderr)
        return 1
    own_engine = engine is None
    if engine is None:
        engine = create_engine(
            normalize_database_url(database_url),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )
    try:
        result = run_capture(
            engine,
            season=season,
            week=week,
            trigger=trigger,
            selection=args.selection,
            draft_group_id=args.draft_group_id,
            transport=transport,
            clock=clock,
            sleeper=sleeper,
            failpoint=failpoint,
            before_terminal=before_terminal,
        )
    except Crash:
        return 1
    except Exception:  # noqa: BLE001 - never print SQL or bound parameters
        print("capture_failed", file=sys.stderr)
        return 1
    finally:
        if own_engine:
            engine.dispose()
    _report(result)
    if not result.persisted and result.reason == "database_unreachable":
        return 1
    return 0 if result.exit_ok else 1


if __name__ == "__main__":
    sys.exit(main())
