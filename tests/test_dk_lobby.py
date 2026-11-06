"""F005 acceptance tests. CSV and JSON bodies are synthetic, not captured salaries."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from loader.dk_lobby import (
    HTTP_BUDGET_S,
    assess_rows,
    capture_schedule_enabled,
    main,
    next_wednesday_10_et,
    parse_csv_bytes,
    parse_draftables,
    reconcile_draftables,
    reconcile_open_attempts,
)
from loader.dk_slate import TRIGGERS as SLATE_TRIGGERS
from loader.dk_slate import main as slate_main
from loader.grants import apply_readonly_grant
from loader.salary_private import (
    CUMULATIVE_LIMIT,
    DATABASE_LIMIT,
    INVOCATION_LIMIT,
    OBJECT_LIMIT,
    budget_block,
    cumulative_would_exceed,
    database_would_exceed,
    read_storage_sizes,
)

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "dk-lobby-capture.yml"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=ET)
CANARY_SALARY = "4242"
CANARY_NAME = "Synthetic Quarterback"
CLASSIC_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]


class MutableClock:
    def __init__(self, wall, mono=0.0):
        self.wall_now = wall
        self.mono_now = mono

    def wall(self):
        return self.wall_now

    def mono(self):
        return self.mono_now


class ScriptTransport(httpx.BaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def handle_request(self, request):
        self.calls.append(request)
        status, headers, body = self.handler(request)
        return httpx.Response(status, headers=headers, content=body, request=request)


def _et(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def _iso(moment):
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _info(away, home, moment):
    local = moment.astimezone(ET)
    hour = local.hour
    suffix = "AM"
    if hour >= 12:
        suffix = "PM"
        if hour > 12:
            hour -= 12
    if hour == 0:
        hour = 12
    return f"{away}@{home} {local.month}/{local.day}/{local.year} {hour:02d}:{local.minute:02d}{suffix} ET"


def _kickoffs():
    return {
        "book": _et(2026, 9, 13, 13, 0),
        "thu": _et(2026, 11, 5, 20, 20),
        "sat1": _et(2026, 11, 7, 13, 0),
        "sat2": _et(2026, 11, 7, 16, 0),
        "sun1": _et(2026, 11, 8, 13, 0),
        "sun2": _et(2026, 11, 8, 16, 25),
        "snf": _et(2026, 11, 8, 20, 20),
        "hol": _et(2026, 12, 26, 13, 0),
        "end": _et(2027, 1, 3, 13, 0),
    }


def _seed(engine, *, source_version="synthetic-schedule-v1"):
    kicks = _kickoffs()
    plan = [
        ("2026_01_NE_KC", 2026, 1, "NE", "KC", kicks["book"]),
        ("2026_10_DAL_PHI", 2026, 10, "DAL", "PHI", kicks["thu"]),
        ("2026_10_BUF_MIA", 2026, 10, "BUF", "MIA", kicks["sat1"]),
        ("2026_10_LAR_ARI", 2026, 10, "LAR", "ARI", kicks["sat2"]),
        ("2026_10_NYJ_NE", 2026, 10, "NYJ", "NE", kicks["sun1"]),
        ("2026_10_GB_CHI", 2026, 10, "GB", "CHI", kicks["sun2"]),
        ("2026_10_SEA_SF", 2026, 10, "SEA", "SF", kicks["snf"]),
        ("2026_16_CIN_PIT", 2026, 16, "CIN", "PIT", kicks["hol"]),
        ("2026_17_KC_DEN", 2026, 17, "KC", "DEN", kicks["end"]),
    ]
    teams = sorted({team for _gid, _s, _w, away, home, _when in plan for team in (away, home)})
    with engine.begin() as conn:
        for abbr in teams:
            conn.execute(
                text(
                    """
                    INSERT INTO teams (
                        team_abbr, team_name, team_nick, team_conf, team_division,
                        team_id, team_color, team_color2, loaded_at
                    ) VALUES (
                        :abbr, :abbr, :abbr, 'NFC', 'NFC East', :abbr, '#000000', '#111111', now()
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"abbr": abbr},
            )
        for game_id, season, week, away, home, moment in plan:
            local = moment.astimezone(ET)
            conn.execute(
                text(
                    """
                    INSERT INTO games (
                        game_id, season, game_type, season_type, week, gameday, weekday,
                        gametime, away_team, home_team, location, loaded_at
                    ) VALUES (
                        :game_id, :season, 'REG', 'REG', :week, :gameday, :weekday,
                        :gametime, :away, :home, 'Home', now()
                    )
                    """
                ),
                {
                    "game_id": game_id,
                    "season": season,
                    "week": week,
                    "gameday": local.date(),
                    "weekday": WEEKDAYS[local.weekday()],
                    "gametime": local.strftime("%H:%M"),
                    "away": away,
                    "home": home,
                },
            )
        conn.execute(
            text(
                """
                INSERT INTO load_runs (
                    run_group, dataset, season, status, trigger, started_at, finished_at,
                    source_url, source_version
                ) VALUES (
                    :run_group, 'games', 2026, 'succeeded', 'local', now(), now(),
                    'https://example.test/schedules', :source_version
                )
                """
            ),
            {"run_group": uuid4(), "source_version": source_version},
        )
        conn.execute(
            text(
                """
                INSERT INTO dk_classic_slate (
                    season, week, dk_id, name_raw, position_raw, roster_position_raw,
                    team_raw, salary, source_name, source_sha256, source_loaded_at, loaded_at
                ) VALUES (
                    2026, 10, 'f004-keep', 'Keep', 'QB', 'QB', 'NE', 1, 'synthetic.csv',
                    :sha, now(), now()
                )
                """
            ),
            {"sha": "ab" * 32},
        )


def _group(draft_id, games, contest=21, game_type=7):
    return {
        "DraftGroupId": draft_id,
        "ContestTypeId": contest,
        "GameTypeId": game_type,
        "Games": [
            {"AwayTeamAbbrev": away, "HomeTeamAbbrev": home, "StartDate": _iso(moment)}
            for away, home, moment in games
        ],
    }


def _rules(slots=None, cap=50000):
    return json.dumps({"salaryCap": cap, "rosterSlots": slots or CLASSIC_SLOTS}).encode()


def _sunday_games():
    kicks = _kickoffs()
    return [("NYJ", "NE", kicks["sun1"]), ("GB", "CHI", kicks["sun2"])]


def _saturday_games():
    kicks = _kickoffs()
    return [("BUF", "MIA", kicks["sat1"]), ("LAR", "ARI", kicks["sat2"])]


def _csv(rows):
    header = (
        "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,"
        "TeamAbbrev,AvgPointsPerGame,Status"
    )
    body = "\n".join([header, *rows]).encode()
    return b"\xef\xbb\xbf" + body


def _classic_rows(salary=CANARY_SALARY):
    kicks = _kickoffs()
    sun1 = _info("NYJ", "NE", kicks["sun1"])
    sun2 = _info("GB", "CHI", kicks["sun2"])
    return [
        f"QB,Synthetic Quarterback (900001),{CANARY_NAME},900001,QB,{salary},{sun1},NYJ,1.5,Active",
        f"WR,Synthetic Wideout (900002),Synthetic Wideout,900002,WR/FLEX,4343,{sun1},NE,,Active",
        f"RB,Synthetic Rusher (900003),Synthetic Rusher,900003,RB/FLEX,4444,{sun2},GB,2,Active",
        f"DST,Synthetic Defense (900004),Synthetic Defense,900004,DST,4545,{sun2},CHI,3,Active",
    ]


def _saturday_rows():
    kicks = _kickoffs()
    sat1 = _info("BUF", "MIA", kicks["sat1"])
    sat2 = _info("LAR", "ARI", kicks["sat2"])
    return [
        f"QB,Synthetic Saturday (900011),Synthetic Saturday,900011,QB,4100,{sat1},BUF,1,Active",
        f"RB,Synthetic Saturday Two (900012),Synthetic Saturday Two,900012,RB,4200,{sat2},LAR,1,Active",
    ]


def _json_response(payload, status=200):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return status, {"content-type": "application/json"}, body


def _csv_response(body, status=200):
    return status, {"content-type": "text/csv"}, body


def _happy_handler(box):
    sunday = _group(90001, _sunday_games())
    saturday = _group(90002, _saturday_games())

    def handler(request):
        path = request.url.path
        if path.endswith("/getcontests"):
            groups = box.get("groups", [sunday, saturday])
            return _json_response({"DraftGroups": groups})
        if "/rules" in path:
            return _json_response({"salaryCap": box.get("cap", 50000), "rosterSlots": box["slots"]})
        if path.endswith("/getavailableplayerscsv"):
            return _csv_response(box["csv"])
        if path.startswith("/draftgroups/v1/"):
            return _json_response(box["group"])
        return 404, {"content-type": "text/plain"}, b"missing"

    return handler


def _box(**overrides):
    box = {"slots": list(CLASSIC_SLOTS), "csv": _csv(_classic_rows()), "cap": 50000}
    box.update(overrides)
    return box


_SEQ = {"n": 0}


def _run(engine, transport, argv=None, clock=None, failpoint=None, before_terminal=None, sleeper=None):
    if clock is None:
        _SEQ["n"] += 1
        clock = MutableClock(NOW + timedelta(seconds=_SEQ["n"]))
    return main(
        argv
        or [
            "--season",
            "2026",
            "--week",
            "10",
            "--selection",
            "sunday-afternoon",
            "--trigger",
            "local",
        ],
        transport=transport,
        clock=clock,
        sleeper=sleeper or (lambda _seconds: None),
        failpoint=failpoint,
        before_terminal=before_terminal,
        engine=engine,
    )


def _rows(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()


def _scalar(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def test_at1_exact_bytes_and_f004_untouched(engine):
    _seed(engine)
    box = _box()
    transport = ScriptTransport(_happy_handler(box))
    assert _run(engine, transport) == 0
    artifact = _rows(
        engine,
        """
        SELECT body, sha256, byte_count, artifact_kind
        FROM salary_private.salary_artifacts
        WHERE artifact_kind = 'csv'
        """,
    )[0]
    assert bytes(artifact["body"]) == box["csv"]
    assert artifact["sha256"] == __import__("hashlib").sha256(box["csv"]).hexdigest()
    assert artifact["byte_count"] == len(box["csv"])
    ledger = _rows(
        engine,
        """
        SELECT row_number, raw_fields
        FROM salary_private.salary_source_rows
        ORDER BY row_number
        """,
    )
    assert [row["row_number"] for row in ledger] == [1, 2, 3, 4]
    assert ledger[0]["raw_fields"][-1] == ["Status", "Active"]
    assert any(pair[0] == "Name + ID" for pair in ledger[0]["raw_fields"])
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dk_lobby_salaries") == 4
    assert _scalar(engine, "SELECT count(*) FROM dk_classic_slate") == 1
    assert _scalar(engine, "SELECT dk_id FROM dk_classic_slate") == "f004-keep"
    assert _scalar(engine, "SELECT count(*) FROM dk_classic_salaries") == 0


def test_at2_sunday_set_excludes_saturday_and_explicit_is_not_main(engine):
    _seed(engine)
    transport = ScriptTransport(_happy_handler(_box()))
    assert _run(engine, transport) == 0
    snapshot = _rows(
        engine,
        "SELECT draft_group_id, metadata, games FROM salary_private.salary_snapshots",
    )[0]
    assert snapshot["draft_group_id"] == "90001"
    assert snapshot["metadata"]["slate_label"] == "sunday_main"
    stored = {(row["away"], row["home"]) for row in snapshot["games"]}
    assert stored == {("NYJ", "NE"), ("GB", "CHI")}
    explicit = ScriptTransport(
        _happy_handler(_box(group=_group(90002, _saturday_games()), csv=_csv(_saturday_rows())))
    )
    code = _run(
        engine,
        explicit,
        argv=[
            "--season",
            "2026",
            "--week",
            "10",
            "--draft-group-id",
            "90002",
            "--trigger",
            "local",
        ],
    )
    assert code == 0
    labels = _rows(
        engine,
        "SELECT draft_group_id, metadata->>'slate_label' AS label "
        "FROM salary_private.salary_snapshots ORDER BY draft_group_id",
    )
    assert {(row["draft_group_id"], row["label"]) for row in labels} == {
        ("90001", "sunday_main"),
        ("90002", "explicit_group"),
    }


def test_at3_fail_closed_reasons(engine):
    kicks = _kickoffs()
    sunday = _group(90001, _sunday_games())
    twin = _group(90003, _sunday_games())
    saturday = _group(90002, _saturday_games())
    inexact = _group(90004, _sunday_games() + [("SEA", "SF", kicks["snf"])])
    cases = {
        "ambiguous_slate": {"groups": [sunday, twin]},
        "slate_unavailable": {"groups": [saturday]},
        "inexact_game_set": {"groups": [inexact]},
        "missing_rules": {"groups": [sunday], "slots": ["FLEX"]},
        "captain_slot": {"groups": [sunday], "csv": _csv(
            [
                row.replace(",QB,", ",CPT,") if row.startswith("QB,") else row
                for row in _classic_rows()
            ]
        )},
        "one_game": {"groups": [sunday], "csv": _csv(_classic_rows()[:1])},
        "duplicate_dk_id": {"groups": [sunday], "csv": _csv(_classic_rows() + [_classic_rows()[0]])},
        "mismatched_metadata": {"groups": [sunday], "csv": _csv(_saturday_rows())},
    }
    _seed(engine)
    before = _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots")
    for reason, updates in cases.items():
        box = _box()
        box.update(updates)
        transport = ScriptTransport(_happy_handler(box))
        assert _run(engine, transport) == 1
        obs = _rows(
            engine,
            """
            SELECT reason_code FROM salary_private.salary_observations
            ORDER BY loaded_at DESC, observation_id DESC LIMIT 1
            """,
        )[0]
        assert obs["reason_code"] == reason
        assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == before


def test_at3_wrong_week_and_holiday_do_not_substitute(engine):
    _seed(engine)
    transport = ScriptTransport(_happy_handler(_box()))
    assert (
        _run(
            engine,
            transport,
            argv=["--season", "2026", "--week", "11", "--selection", "sunday-afternoon"],
        )
        == 1
    )
    assert _rows(engine, "SELECT reason_code FROM salary_private.salary_observations")[0][
        "reason_code"
    ] == "wrong_season_week"
    assert transport.calls == []
    holiday = MutableClock(_et(2026, 12, 23, 10, 0))
    holiday_transport = ScriptTransport(_happy_handler(_box()))
    assert (
        _run(
            engine,
            holiday_transport,
            argv=["--season", "2026", "--week", "16", "--selection", "sunday-afternoon"],
            clock=holiday,
        )
        == 1
    )
    assert holiday_transport.calls == []
    assert _rows(
        engine,
        "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at DESC",
    )[0]["reason_code"] == "slate_unavailable"


def test_at4_schedule_text_and_disabled_gate():
    text_value = WORKFLOW.read_text()
    assert "cron: '0 10 * * 3'" in text_value
    assert "timezone: 'America/New_York'" in text_value
    assert "vars.DK_LOBBY_CAPTURE_ENABLED == 'true'" in text_value
    assert "capture_schedule_enabled" in text_value
    assert text_value.index("capture_schedule_enabled") < text_value.index("python -m loader.migrate")
    assert 'DK_LOBBY_CAPTURE_ENABLED: "true"' not in text_value
    assert "cancel-in-progress: false" in text_value
    assert text_value.count("cron:") == 1
    assert "0 15 * * 3" not in text_value
    assert "0 14 * * 3" not in text_value
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        lowered = path.read_text().lower()
        assert "grok" not in lowered
        assert "bot" not in path.name
    winter = next_wednesday_10_et(datetime(2026, 1, 6, 15, 0, tzinfo=UTC))
    summer = next_wednesday_10_et(datetime(2026, 7, 7, 14, 0, tzinfo=UTC))
    assert winter == datetime(2026, 1, 7, 15, 0, tzinfo=UTC)
    assert summer == datetime(2026, 7, 8, 14, 0, tzinfo=UTC)
    assert winter.astimezone(ET).hour == 10 and winter.astimezone(ET).weekday() == 2
    assert summer.astimezone(ET).hour == 10 and summer.astimezone(ET).weekday() == 2
    assert capture_schedule_enabled(None) is False
    assert capture_schedule_enabled("false") is False
    assert capture_schedule_enabled("TRUE") is False
    assert capture_schedule_enabled("true") is True
    script = text_value.split("run: |\n", 1)[1]
    checked = subprocess.run(["bash", "-n"], input=script, text=True, check=False)
    assert checked.returncode == 0


def test_at5_off_season_stale_and_absent_group(engine):
    _seed(engine)
    off = ScriptTransport(_happy_handler(_box()))
    assert _run(engine, off, clock=MutableClock(_et(2026, 8, 1, 10, 0))) == 0
    assert off.calls == []
    obs = _rows(engine, "SELECT status, reason_code, duration_ms FROM salary_private.salary_observations")[0]
    assert (obs["status"], obs["reason_code"]) == ("skipped", "off_season")
    assert obs["duration_ms"] is not None
    with engine.begin() as conn:
        conn.execute(text("UPDATE load_runs SET source_version = NULL WHERE dataset = 'games'"))
    stale = ScriptTransport(_happy_handler(_box()))
    assert _run(engine, stale) == 1
    assert stale.calls == []
    assert _rows(
        engine,
        "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at DESC",
    )[0]["reason_code"] == "schedule_evidence_missing"
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE load_runs SET source_version = 'synthetic-schedule-v1' WHERE dataset = 'games'")
        )
    absent = ScriptTransport(_happy_handler(_box(groups=[_group(90002, _saturday_games())])))
    assert _run(engine, absent) == 1
    assert absent.calls
    assert _rows(
        engine,
        "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at DESC",
    )[0]["reason_code"] == "slate_unavailable"
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0
    text_value = WORKFLOW.read_text()
    assert "invalid_season" in text_value
    assert "invalid_week" in text_value
    assert "invalid_draft_group" in text_value
    assert "invalid_selector" in text_value


def test_at6_repeat_content_and_identity_revision(engine):
    _seed(engine)
    box = _box()
    first = ScriptTransport(_happy_handler(box))
    assert _run(engine, first) == 0
    original = _rows(
        engine,
        "SELECT snapshot_id, loaded_at FROM salary_private.dk_lobby_salaries ORDER BY row_number",
    )
    assert _run(engine, ScriptTransport(_happy_handler(box))) == 0
    changed = _box(csv=_csv(_classic_rows("4243")))
    assert _run(engine, ScriptTransport(_happy_handler(changed))) == 0
    assert _run(engine, ScriptTransport(_happy_handler(box))) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_observations") == 4
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 2
    again = _rows(
        engine,
        """
        SELECT snapshot_id, loaded_at FROM salary_private.dk_lobby_salaries
        WHERE snapshot_id = :snapshot_id ORDER BY row_number
        """,
        snapshot_id=original[0]["snapshot_id"],
    )
    assert [(row["loaded_at"], row["snapshot_id"]) for row in again] == [
        (row["loaded_at"], row["snapshot_id"]) for row in original
    ]
    reordered = _box(slots=["DST", "FLEX", "TE", "WR", "WR", "WR", "RB", "RB", "QB"])
    assert _run(engine, ScriptTransport(_happy_handler(reordered))) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 3
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_artifacts WHERE artifact_kind = 'csv'") == 2


def test_at7_failures_keep_the_previous_snapshot(engine):
    _seed(engine)
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 0
    before = _rows(engine, "SELECT snapshot_id, salary::text FROM salary_private.dk_lobby_salaries")
    bad = _box(csv=b"not,a,salary\n1,2,3\n")
    assert _run(engine, ScriptTransport(_happy_handler(bad))) == 1
    invalid = _box(csv=_csv(
        [
            row.replace(f",{CANARY_SALARY},", ",nope,") if CANARY_NAME in row else row
            for row in _classic_rows()
        ]
    ))
    assert _run(engine, ScriptTransport(_happy_handler(invalid))) == 1
    ledger = _rows(
        engine,
        """
        SELECT reason_codes, raw_fields FROM salary_private.salary_source_rows
        WHERE raw_fields::text LIKE '%nope%'
        """,
    )
    assert ledger and "invalid_salary" in ledger[0]["reason_codes"]
    assert _run(engine, ScriptTransport(_happy_handler(_box())), failpoint="constraint") == 1
    after = _rows(engine, "SELECT snapshot_id, salary::text FROM salary_private.dk_lobby_salaries")
    assert after == before
    reasons = [row["reason_code"] for row in _rows(
        engine, "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at"
    )]
    assert "parse_failure" in reasons
    assert "invalid_salary" in reasons
    assert "constraint_failure" in reasons
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 1


def test_at8_reconcile_does_not_double_ingest_or_promote_unrelated(engine):
    _seed(engine)
    assert _run(engine, ScriptTransport(_happy_handler(_box())), failpoint="after_publish") == 1
    snapshots = _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO load_runs (
                    run_group, dataset, season, status, trigger, started_at, source_url
                ) VALUES (
                    :run_group, 'teams', NULL, 'running', 'local', now(), 'https://example.test/teams'
                )
                """
            ),
            {"run_group": uuid4()},
        )
        other = conn.execute(
            text(
                """
                INSERT INTO load_runs (
                    run_group, dataset, season, status, trigger, started_at, source_url
                ) VALUES (
                    :run_group, 'dk_lobby_salaries', 2026, 'running', 'local', now(),
                    'https://www.draftkings.com/lobby/getcontests'
                ) RETURNING id
                """
            ),
            {"run_group": uuid4()},
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_observations (
                    observation_id, load_run_id, source, requested_at, started_at, observed_at,
                    source_url, metadata, status, loaded_at
                ) VALUES (
                    :observation_id, :load_run_id, 'dk_lobby', now(), now(), now(),
                    'https://www.draftkings.com/lobby/getcontests', '{}'::jsonb, 'running', now()
                )
                """
            ),
            {"observation_id": uuid4(), "load_run_id": other},
        )
    reconcile_open_attempts(engine)
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == snapshots
    statuses = _rows(
        engine,
        """
        SELECT dataset, status FROM load_runs
        WHERE dataset IN ('dk_lobby_salaries', 'teams')
        ORDER BY dataset, id
        """,
    )
    assert ("teams", "running") in {(row["dataset"], row["status"]) for row in statuses}
    lobby = [row["status"] for row in statuses if row["dataset"] == "dk_lobby_salaries"]
    assert "succeeded" in lobby
    assert lobby.count("succeeded") == 1
    unrelated = _rows(
        engine,
        "SELECT status, finished_at, duration_ms FROM salary_private.salary_observations WHERE load_run_id = :id",
        id=other,
    )[0]
    assert unrelated["status"] == "failed"
    assert unrelated["finished_at"] is None
    assert unrelated["duration_ms"] is None


def test_at9_denial_does_not_retry(engine):
    _seed(engine)
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 0
    before = _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots")

    def once(status, headers, body):
        def handler(_request):
            return status, headers, body
        return handler

    cases = [
        once(403, {"content-type": "text/plain"}, b"denied-synthetic"),
        once(429, {"content-type": "text/plain", "retry-after": "30"}, b"slow-synthetic"),
        once(302, {"location": "https://www.draftkings.com/login", "content-type": "text/plain"}, b"go"),
        once(200, {"content-type": "text/html"}, b"<html>captcha</html>"),
    ]
    expected = ["http_denied", "http_rate_limited", "http_login_redirect", "http_challenge"]
    for handler, reason in zip(cases, expected, strict=True):
        transport = ScriptTransport(handler)
        assert _run(engine, transport) == 1
        assert len(transport.calls) == 1
        obs = _rows(
            engine,
            "SELECT reason_code, error_private FROM salary_private.salary_observations ORDER BY loaded_at DESC",
        )[0]
        assert obs["reason_code"] == reason
    rate = _rows(
        engine,
        "SELECT error_private FROM salary_private.salary_observations WHERE reason_code = 'http_rate_limited'",
    )[0]
    assert "retry_after=30" in rate["error_private"]
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == before


def test_at10_retries_redirects_and_budget(engine):
    _seed(engine)
    state = {"n": 0}

    def flaky(request):
        if request.url.path.endswith("/getcontests"):
            state["n"] += 1
            if state["n"] < 3:
                return 500, {"content-type": "text/plain"}, b"later"
        return _happy_handler(_box())(request)

    delays = []

    def sleeper(seconds):
        delays.append(seconds)

    transport = ScriptTransport(flaky)
    assert _run(engine, transport, sleeper=sleeper) == 0
    assert delays == [1, 2]
    assert sum(1 for call in transport.calls if call.url.path.endswith("/getcontests")) == 3

    def always_timeout(_request):
        raise httpx.ReadTimeout("timed out")

    exhausted = ScriptTransport(always_timeout)
    assert _run(engine, exhausted, sleeper=lambda _seconds: None) == 1
    assert len(exhausted.calls) == 3
    assert _rows(
        engine,
        "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at DESC",
    )[0]["reason_code"] == "http_timeout"

    def redirect(request):
        if request.url.path.endswith("/getcontests") and len(redirects.calls) == 1:
            return 302, {"location": "https://evil.example/steal", "content-type": "text/plain"}, b"no"
        return _happy_handler(_box())(request)

    redirects = ScriptTransport(redirect)
    assert _run(engine, redirects) == 1
    assert len(redirects.calls) == 1
    assert _rows(
        engine,
        "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at DESC",
    )[0]["reason_code"] == "http_redirect_rejected"

    def cookies(request):
        if "cookie" in {key.lower() for key in request.headers}:
            raise AssertionError(request.headers)
        if len(cookie_transport.calls) == 1:
            return 200, {"content-type": "application/json", "set-cookie": "a=b"}, json.dumps(
                {"DraftGroups": [_group(90001, _sunday_games())]}
            ).encode()
        return _happy_handler(_box())(request)

    cookie_transport = ScriptTransport(cookies)
    assert _run(engine, cookie_transport) == 0
    assert "authorization" not in {key.lower() for call in cookie_transport.calls for key in call.headers}

    clock = MutableClock(NOW + timedelta(days=3), 0)

    def jump(_request):
        clock.mono_now = 181
        return 500, {"content-type": "text/plain"}, b"late"

    budget = ScriptTransport(jump)
    assert _run(engine, budget, clock=clock, sleeper=lambda _seconds: None) == 1
    assert len(budget.calls) == 1
    assert _rows(
        engine,
        "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at DESC",
    )[0]["reason_code"] == "http_budget_exhausted"


def test_at11_grants_hide_private_and_f004(engine, monkeypatch):
    web = "seam_web_f005"
    optimizer = "seam_opt_f005"
    monkeypatch.setenv("READONLY_ROLE", web)
    monkeypatch.setenv("OPTIMIZER_ROLE", optimizer)
    with engine.begin() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {optimizer}"))
        conn.execute(text(f"DROP ROLE IF EXISTS {web}"))
        conn.execute(text(f"CREATE ROLE {web}"))
        conn.execute(text(f"CREATE ROLE {optimizer}"))
        conn.execute(text(f"GRANT {web} TO CURRENT_USER"))
        conn.execute(text(f"GRANT {optimizer} TO CURRENT_USER"))
        apply_readonly_grant(conn)
        apply_readonly_grant(conn)
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {web}"))
            for table in (
                "teams",
                "players",
                "games",
                "player_week_stats",
                "load_runs",
                "dk_classic_salaries",
            ):
                conn.execute(text(f"SELECT count(*) FROM {table}"))
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT count(*) FROM dk_classic_slate"))
            conn.rollback()
            conn.execute(text(f"SET ROLE {web}"))
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT count(*) FROM salary_private.salary_artifacts"))
            conn.rollback()
            conn.execute(text("RESET ROLE"))
            conn.commit()
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {optimizer}"))
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT count(*) FROM salary_private.dk_lobby_salaries"))
            conn.rollback()
            conn.execute(text("RESET ROLE"))
            conn.commit()
        with engine.begin() as conn:
            conn.execute(
                text("CREATE VIEW salary_private.dk_salary_unified AS SELECT 1::int AS selection_id")
            )
            apply_readonly_grant(conn)
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {optimizer}"))
            assert conn.execute(text("SELECT selection_id FROM salary_private.dk_salary_unified")).scalar() == 1
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT count(*) FROM salary_private.salary_artifacts"))
            conn.rollback()
            conn.execute(text(f"SET ROLE {optimizer}"))
            with pytest.raises(DBAPIError):
                conn.execute(text("INSERT INTO salary_private.salary_artifacts (source) VALUES ('dk_lobby')"))
            conn.rollback()
            conn.execute(text(f"SET ROLE {web}"))
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT selection_id FROM salary_private.dk_salary_unified"))
            conn.rollback()
            conn.execute(text("RESET ROLE"))
            member = conn.execute(
                text(
                    """
                    SELECT 1 FROM pg_auth_members m
                    JOIN pg_roles parent ON parent.oid = m.roleid
                    JOIN pg_roles child ON child.oid = m.member
                    WHERE parent.rolname = :web AND child.rolname = :optimizer
                    """
                ),
                {"web": web, "optimizer": optimizer},
            ).first()
            assert member is None
            conn.commit()
        with engine.begin() as conn:
            conn.execute(text("GRANT SELECT ON dk_classic_slate TO seam_web_f005"))
            apply_readonly_grant(conn)
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {web}"))
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT count(*) FROM dk_classic_slate"))
            conn.rollback()
            conn.execute(text("RESET ROLE"))
            conn.commit()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP VIEW IF EXISTS salary_private.dk_salary_unified"))
            conn.execute(text(f"DROP OWNED BY {optimizer}"))
            conn.execute(text(f"DROP OWNED BY {web}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {optimizer}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {web}"))


def test_at12_storage_guards_and_concurrent_lock(engine):
    _seed(engine)
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 0
    before = _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots")
    huge = b"x" * (OBJECT_LIMIT + 1)

    def oversized(_request):
        return 200, {"content-type": "text/csv"}, huge

    assert _run(engine, ScriptTransport(oversized)) == 1
    obs = _rows(
        engine,
        """
        SELECT reason_code, metadata FROM salary_private.salary_observations
        ORDER BY loaded_at DESC
        """,
    )[0]
    assert obs["reason_code"] == "storage_guard_object"
    assert obs["metadata"]["truncated"] is True
    assert obs["metadata"]["retained_artifact"] is False
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == before
    with engine.connect() as conn:
        sizes = read_storage_sizes(conn)
        assert sizes.database_bytes > 0
        assert budget_block(conn, object_bytes=100, invocation_bytes=100) is None
        assert budget_block(conn, object_bytes=10, invocation_bytes=INVOCATION_LIMIT + 1).value.endswith(
            "invocation"
        )
        assert cumulative_would_exceed(conn, CUMULATIVE_LIMIT) is True
        assert database_would_exceed(conn, DATABASE_LIMIT) is True
        assert cumulative_would_exceed(conn, 100) is False
        conn.rollback()
    import threading

    errors = []

    def worker(label):
        try:
            body = f"synthetic-{label}".encode()
            from loader.salary_private import (
                ArtifactKind,
                lock_capture,
                store_artifact,
                unlock_capture,
            )

            with engine.connect() as conn:
                lock_capture(conn)
                try:
                    store_artifact(
                        conn,
                        body=body,
                        kind=ArtifactKind.MANIFEST,
                        media_type="text/plain",
                        stored_at=NOW,
                        invocation_bytes=len(body),
                    )
                finally:
                    unlock_capture(conn)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert _scalar(
        engine,
        "SELECT count(*) FROM salary_private.salary_artifacts WHERE artifact_kind = 'manifest'",
    ) == 2


def test_at13_public_output_has_no_raw_salary(engine, capsys, client):
    _seed(engine)
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 0
    denied = ScriptTransport(
        lambda _request: (403, {"content-type": "text/plain"}, b"denied-synthetic-body")
    )
    assert _run(engine, denied) == 1
    captured = capsys.readouterr()
    assert CANARY_SALARY not in captured.out
    assert CANARY_NAME not in captured.out
    assert "denied-synthetic-body" not in captured.out + captured.err
    notes = _rows(engine, "SELECT notes, error FROM load_runs WHERE dataset = 'dk_lobby_salaries'")
    for row in notes:
        blob = f"{row['notes']} {row['error']}"
        assert CANARY_SALARY not in blob
        assert CANARY_NAME not in blob
        assert "denied-synthetic" not in blob
    assert client.get("/api/dk-lobby").status_code == 404
    assert client.get("/dk-lobby.csv").status_code == 404
    binary = __import__("shutil").which("gitleaks")
    assert binary
    scan = subprocess.run(
        [binary, "detect", "--source", str(ROOT), "--redact", "--log-opts=--all", "--no-banner"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert scan.returncode == 0, scan.stdout + scan.stderr


def test_at14_f004_scheduled_trigger_remains(database_url, engine, tmp_path, capsys):
    assert "scheduled" in SLATE_TRIGGERS
    workflow = (ROOT / ".github" / "workflows" / "dk-classic-slate.yml").read_text()
    assert "--trigger" in workflow and "scheduled" in workflow
    assert "draftkings.com" not in workflow
    assert "draftkings.com" not in (ROOT / "loader" / "dk_slate.py").read_text()
    missing = tmp_path / "DKSalaries.csv"
    code = slate_main(
        ["--csv", str(missing), "--season", "2026", "--week", "10", "--trigger", "scheduled"]
    )
    assert code == 1
    assert _rows(engine, "SELECT trigger, status FROM load_runs WHERE dataset = 'dk_classic_slate'")[-1][
        "trigger"
    ] == "scheduled"
    capsys.readouterr()


def test_at15_and_at16_timing(engine):
    _seed(engine)
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 0
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 0
    assert _run(engine, ScriptTransport(_happy_handler(_box())), clock=MutableClock(_et(2026, 8, 1, 10, 0))) == 0
    assert _run(
        engine,
        ScriptTransport(lambda _request: (403, {"content-type": "text/plain"}, b"no")),
    ) == 1
    invalid = _box(csv=_csv(
        [row.replace(f",{CANARY_SALARY},", ",nope,") if CANARY_NAME in row else row for row in _classic_rows()]
    ))
    assert _run(engine, ScriptTransport(_happy_handler(invalid))) == 1
    observations = _rows(
        engine,
        """
        SELECT status, reason_code, started_at, finished_at, duration_ms, snapshot_id
        FROM salary_private.salary_observations
        """,
    )
    by_reason = {}
    for row in observations:
        by_reason.setdefault(row["reason_code"], []).append(row)
        assert row["started_at"] is not None
        assert row["finished_at"] is not None
        assert row["duration_ms"] is not None and row["duration_ms"] >= 0
    assert len(by_reason["captured"]) == 2
    assert by_reason["captured"][0]["snapshot_id"] == by_reason["captured"][1]["snapshot_id"]
    assert by_reason["off_season"][0]["snapshot_id"] is None
    assert by_reason["http_denied"][0]["snapshot_id"] is None
    assert by_reason["invalid_salary"][0]["snapshot_id"] is None
    public = _rows(engine, "SELECT notes, error FROM load_runs WHERE dataset = 'dk_lobby_salaries'")
    for row in public:
        assert CANARY_NAME not in f"{row['notes']} {row['error']}"
    clock = MutableClock(NOW + timedelta(days=1), 10.0)

    def jump():
        clock.wall_now = clock.wall_now + timedelta(hours=1)
        clock.mono_now = 10.05

    assert _run(
        engine,
        ScriptTransport(_happy_handler(_box(csv=_csv(_classic_rows("4248"))))),
        clock=clock,
        before_terminal=jump,
    ) == 0
    timed = _rows(
        engine,
        """
        SELECT started_at, finished_at, duration_ms
        FROM salary_private.salary_observations
        ORDER BY loaded_at DESC
        """,
    )[0]
    wall_ms = int((timed["finished_at"] - timed["started_at"]).total_seconds() * 1000)
    assert timed["duration_ms"] == 50
    assert wall_ms == 3_600_000
    assert timed["duration_ms"] != wall_ms
    assert _run(engine, ScriptTransport(_happy_handler(_box())), failpoint="before_terminal") == 1
    crashed = _rows(
        engine,
        """
        SELECT status, finished_at, duration_ms FROM salary_private.salary_observations
        WHERE status = 'running'
        """,
    )
    assert len(crashed) == 1
    assert crashed[0]["finished_at"] is None and crashed[0]["duration_ms"] is None
    reconcile_open_attempts(engine)
    recovered = _rows(
        engine,
        """
        SELECT status, finished_at, duration_ms, reason_code
        FROM salary_private.salary_observations
        WHERE reason_code = 'interrupted'
        """,
    )[0]
    assert recovered["status"] == "failed"
    assert recovered["finished_at"] is None
    assert recovered["duration_ms"] is None


def test_at16_unreachable_database_claims_nothing(engine):
    before = _scalar(engine, "SELECT count(*) FROM load_runs")
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://seam@127.0.0.1:1/none"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loader.dk_lobby",
            "--season",
            "2026",
            "--week",
            "10",
            "--selection",
            "sunday-afternoon",
            "--trigger",
            "local",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr.strip() == "database_unreachable"
    assert "postgresql://" not in result.stderr
    assert _scalar(engine, "SELECT count(*) FROM load_runs") == before


def _synthetic_draftables():
    kicks = _kickoffs()
    sun1 = kicks["sun1"].astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    sun2 = kicks["sun2"].astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    player = {
        "playerId": 501,
        "playerDkId": 9001,
        "displayName": "Synthetic Quarterback",
        "position": "QB",
        "teamAbbreviation": "NYJ",
        "salary": 4242,
    }
    other = {
        "playerId": 502,
        "playerDkId": 9002,
        "displayName": "Synthetic Rusher",
        "position": "RB",
        "teamAbbreviation": "GB",
        "salary": 4444,
    }
    return {
        "draftables": [
            {"draftableId": 900001, "rosterSlotId": 66, **player},
            {"draftableId": 900099, "rosterSlotId": 70, **player},
            {"draftableId": 900003, "rosterSlotId": 67, **other},
        ],
        "competitions": [
            {
                "competitionId": 1,
                "sport": "NFL",
                "name": "NYJ @ NE",
                "startTime": sun1,
                "awayTeam": {"abbreviation": "NYJ", "teamId": 1},
                "homeTeam": {"abbreviation": "NE", "teamId": 2},
            },
            {
                "competitionId": 2,
                "sport": "NFL",
                "name": "GB @ CHI",
                "startTime": sun2,
                "awayTeam": {"abbreviation": "GB", "teamId": 3},
                "homeTeam": {"abbreviation": "CHI", "teamId": 4},
            },
        ],
    }


def test_draftables_contract_uses_csv_players_not_slot_rows():
    document = _synthetic_draftables()
    parsed = parse_draftables(json.dumps(document).encode())
    assert parsed.draftables is not None
    assert parsed.draftables.slot_count == 3
    assert parsed.draftables.player_count == 2
    assert len(parsed.games) == 2
    salary_rows = [_classic_rows()[0], _classic_rows()[2]]
    assessed, file_reasons = assess_rows(parse_csv_bytes(_csv(salary_rows)))
    assert file_reasons == []
    assert reconcile_draftables(parsed.draftables, assessed) == []
    csv_games = {(row["game"].away, row["game"].home, row["game"].kickoff_at) for row in assessed}
    parsed_games = {(game.away, game.home, game.kickoff_at) for game in parsed.games}
    assert csv_games == parsed_games
    shifted = _csv(
        [row.replace(",4242,", ",4243,") if "900001" in row else row for row in salary_rows]
    )
    changed, _ignored = assess_rows(parse_csv_bytes(shifted))
    assert reconcile_draftables(parsed.draftables, changed) == ["draftables_mismatch"]


def test_production_migrate_stops_before_0004(database_url):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from loader.migrate import current_revision, migrate_production, upgrade_target

    assert upgrade_target(None, None) == "0003"
    assert upgrade_target("0002", "") == "0003"
    assert upgrade_target("0004", None) == "0004"
    assert upgrade_target("0003", "TRUE") == "0003"
    assert upgrade_target("0003", "true") == "head"
    for name in (
        "refresh.yml",
        "dk-classic-salaries.yml",
        "dk-classic-slate.yml",
        "dk-lobby-capture.yml",
    ):
        workflow = (ROOT / ".github" / "workflows" / name).read_text()
        assert "alembic upgrade head" not in workflow
        assert "python -m loader.migrate" in workflow
    admin = create_engine(database_url)
    name = "seam_f005_gate"
    previous = os.environ.get("DATABASE_URL")
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
            conn.execute(text(f"CREATE DATABASE {name}"))
        gated = make_url(database_url).set(database=name).render_as_string(hide_password=False)
        assert migrate_production(gated, None) == "0003"
        check = create_engine(gated)
        with check.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
            assert conn.execute(text("SELECT to_regclass('public.games')")).scalar() is not None
            assert (
                conn.execute(text("SELECT to_regclass('salary_private.salary_artifacts')")).scalar()
                is None
            )
        check.dispose()
        assert current_revision(gated) == "0003"
        assert migrate_production(gated, "true") == "head"
        check = create_engine(gated)
        with check.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0004"
            assert (
                conn.execute(text("SELECT to_regclass('salary_private.dk_lobby_salaries')")).scalar()
                is not None
            )
        check.dispose()
        assert migrate_production(gated, None) == "0004"
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        admin.dispose()


def test_hydrate_is_rechecked_and_explicit_id_must_match(engine):
    _seed(engine)
    lobby = _group(90001, _sunday_games())
    lobby.pop("GameTypeId")
    replacement = _group(90001, _saturday_games())

    def handler(request):
        if request.url.path.endswith("/getcontests"):
            return _json_response({"DraftGroups": [lobby]})
        if request.url.path.startswith("/draftgroups/v1/"):
            return _json_response(replacement)
        return _happy_handler(_box())(request)

    transport = ScriptTransport(handler)
    assert _run(engine, transport) == 1
    assert _rows(
        engine, "SELECT reason_code FROM salary_private.salary_observations"
    )[-1]["reason_code"] in {"mismatched_metadata", "slate_unavailable", "inexact_game_set"}
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0
    wrong = _group(111, _saturday_games())

    def explicit(request):
        if request.url.path.startswith("/draftgroups/v1/"):
            return _json_response(wrong)
        return _happy_handler(_box())(request)

    assert (
        _run(
            engine,
            ScriptTransport(explicit),
            argv=["--season", "2026", "--week", "10", "--draft-group-id", "90002"],
        )
        == 1
    )
    assert _rows(
        engine,
        "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at DESC",
    )[0]["reason_code"] == "mismatched_metadata"


def test_historical_hole_does_not_block_the_current_season(engine):
    _seed(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO games (
                    game_id, season, game_type, season_type, week, gameday, weekday,
                    gametime, away_team, home_team, location, loaded_at
                ) VALUES (
                    '2015_01_NE_KC', 2015, 'REG', 'REG', 1, DATE '2015-09-13', 'Sunday',
                    NULL, 'NE', 'KC', 'Home', now()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO load_runs (
                    run_group, dataset, season, status, trigger, started_at, finished_at,
                    source_url, source_version
                ) VALUES (
                    :run_group, 'games', 2015, 'succeeded', 'local', now(), NULL,
                    'https://example.test/old', NULL
                )
                """
            ),
            {"run_group": uuid4()},
        )
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 0


def test_redirect_stops_when_the_budget_is_spent(engine):
    _seed(engine)
    clock = MutableClock(NOW + timedelta(days=2), 0)

    def handler(request):
        if request.url.path.endswith("/getcontests"):
            clock.mono_now = HTTP_BUDGET_S + 1
            return (
                302,
                {"location": "https://www.draftkings.com/lobby/getcontests?sport=NFL"},
                b"",
            )
        return _happy_handler(_box())(request)

    transport = ScriptTransport(handler)
    assert _run(engine, transport, clock=clock) == 1
    assert len(transport.calls) == 1
    assert _rows(
        engine,
        "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at DESC",
    )[0]["reason_code"] == "http_budget_exhausted"


def test_challenge_on_5xx_is_not_retried(engine):
    _seed(engine)

    def handler(_request):
        return 500, {"content-type": "text/html"}, b"<html>captcha</html>"

    transport = ScriptTransport(handler)
    assert _run(engine, transport) == 1
    assert len(transport.calls) == 1
    assert _rows(
        engine,
        "SELECT reason_code FROM salary_private.salary_observations ORDER BY loaded_at DESC",
    )[0]["reason_code"] == "http_challenge"


def test_concurrent_actual_growth_rejects_one_writer(engine, monkeypatch):
    import threading

    import loader.salary_private as private

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("DELETE FROM salary_private.salary_artifacts WHERE source = 'control'"))
        conn.execute(text("VACUUM FULL salary_private.salary_artifacts"))
    with engine.connect() as conn:
        before = private.read_storage_sizes(conn).private_bytes
        conn.rollback()
    probe = b"p" * 500_000
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_artifacts (
                    source, sha256, body, byte_count, media_type, artifact_kind, stored_at, loaded_at
                ) VALUES (
                    'control', :sha, :body, :count, 'text/plain', 'manifest', now(), now()
                )
                """
            ),
            {"sha": __import__("hashlib").sha256(probe).hexdigest(), "body": probe, "count": len(probe)},
        )
        grown = private.read_storage_sizes(conn).private_bytes
    delta = grown - before
    assert delta > 0
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("DELETE FROM salary_private.salary_artifacts WHERE source = 'control'"))
        conn.execute(text("VACUUM FULL salary_private.salary_artifacts"))
    with engine.connect() as conn:
        base = private.read_storage_sizes(conn).private_bytes
        conn.rollback()
    monkeypatch.setattr(private, "AUDIT_HEADROOM", 0)
    monkeypatch.setattr(private, "DATABASE_LIMIT", 10**15)
    monkeypatch.setattr(private, "CUMULATIVE_LIMIT", base + delta + delta // 2)
    start = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt(label: bytes):
        body = label * 500_000
        digest = __import__("hashlib").sha256(body).hexdigest()
        with engine.connect() as conn:
            start.wait(timeout=5)
            try:
                with conn.begin():
                    conn.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"),
                        {"key": private.CAPTURE_LOCK},
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO salary_private.salary_artifacts (
                                source, sha256, body, byte_count, media_type,
                                artifact_kind, stored_at, loaded_at
                            ) VALUES (
                                'control', :sha, :body, :count, 'text/plain',
                                'manifest', now(), now()
                            )
                            """
                        ),
                        {"sha": digest, "body": body, "count": len(body)},
                    )
                    private.assert_actual_ceiling(conn)
                outcomes.append("ok")
            except private.PrivateWriteError:
                outcomes.append("rejected")

    threads = [threading.Thread(target=attempt, args=(label,)) for label in (b"a", b"b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["ok", "rejected"]
    with engine.connect() as conn:
        assert private.read_storage_sizes(conn).database_bytes <= private.DATABASE_LIMIT


def test_rules_hash_and_game_type_split_snapshots(engine):
    _seed(engine)
    first = _box()
    first["note"] = "alpha"
    second = _box()
    second["note"] = "beta"

    def rules_handler(box):
        base = _happy_handler(box)

        def handler(request):
            if "/rules" in request.url.path:
                payload = {
                    "salaryCap": 50000,
                    "rosterSlots": box["slots"],
                    "note": box["note"],
                    "gameTypeId": 7,
                }
                return _json_response(payload)
            return base(request)

        return handler

    assert _run(engine, ScriptTransport(rules_handler(first))) == 0
    assert _run(engine, ScriptTransport(rules_handler(second))) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 2


@pytest.mark.xfail(
    strict=True,
    reason="BLOCKED: no authoritative season-completeness evidence in the repo or merged SPEC/ADRs",
)
def test_deleted_interior_sunday_game_is_missing_evidence(engine):
    """Endpoints stay. One interior Sunday game is gone. That is not a smaller slate."""
    _seed(engine)
    kicks = _kickoffs()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO games (
                    game_id, season, game_type, season_type, week, gameday, weekday,
                    gametime, away_team, home_team, location, loaded_at
                ) VALUES (
                    '2026_10_PHI_DAL', 2026, 'REG', 'REG', 10, DATE '2026-11-08', 'Sunday',
                    '13:00', 'PHI', 'DAL', 'Home', now()
                )
                """
            )
        )
        conn.execute(text("DELETE FROM games WHERE game_id = '2026_10_GB_CHI'"))
    sun1 = _info("NYJ", "NE", kicks["sun1"])
    extra = _info("PHI", "DAL", kicks["sun1"])
    rows = [
        f"QB,Synthetic Quarterback (900001),{CANARY_NAME},900001,QB,{CANARY_SALARY},{sun1},NYJ,1.5,Active",
        f"RB,Synthetic Rusher (900003),Synthetic Rusher,900003,RB,4444,{extra},PHI,2,Active",
    ]
    reduced = [("NYJ", "NE", kicks["sun1"]), ("PHI", "DAL", kicks["sun1"])]
    box = _box(csv=_csv(rows), groups=[_group(90001, reduced)])
    assert _run(engine, ScriptTransport(_happy_handler(box))) == 1
    observed = _rows(
        engine, "SELECT status, reason_code FROM salary_private.salary_observations"
    )[0]
    assert observed["reason_code"] == "schedule_evidence_missing"
    assert observed["status"] != "skipped"
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0


@pytest.mark.xfail(
    strict=True,
    reason="BLOCKED: no authoritative season-completeness evidence in the repo or merged SPEC/ADRs",
)
def test_deleted_interior_week_is_missing_evidence(engine):
    _seed(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM games WHERE season = 2026 AND week = 16"))
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 1
    observed = _rows(
        engine, "SELECT status, reason_code FROM salary_private.salary_observations"
    )[0]
    assert observed["reason_code"] == "schedule_evidence_missing"
    assert observed["reason_code"] != "off_season"
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0


@pytest.mark.xfail(
    strict=True,
    reason="BLOCKED: no authoritative season-completeness evidence in the repo or merged SPEC/ADRs",
)
def test_incomplete_prior_season_in_april_is_not_off_season(engine):
    _seed(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO games (
                    game_id, season, game_type, season_type, week, gameday, weekday,
                    gametime, away_team, home_team, location, loaded_at
                ) VALUES (
                    '2026_18_BUF_MIA', 2026, 'REG', 'REG', 18, DATE '2027-01-10', 'Sunday',
                    '13:00', 'BUF', 'MIA', 'Home', now()
                )
                """
            )
        )
        conn.execute(text("DELETE FROM games WHERE season = 2026 AND week = 16"))
        conn.execute(
            text(
                """
                UPDATE load_runs
                SET finished_at = TIMESTAMPTZ '2027-04-15 14:00:00+00',
                    source_version = 'synthetic-schedule-v1'
                WHERE dataset = 'games' AND season = 2026
                """
            )
        )
    transport = ScriptTransport(_happy_handler(_box()))
    assert _run(engine, transport, clock=MutableClock(_et(2027, 4, 15, 10, 0))) == 1
    observed = _rows(
        engine, "SELECT status, reason_code FROM salary_private.salary_observations"
    )[0]
    assert observed["reason_code"] == "schedule_evidence_missing"
    assert observed["status"] != "skipped"
    assert transport.calls == []
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0


def test_stale_current_season_is_not_saved_by_fresh_history(engine):
    _seed(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE load_runs
                SET finished_at = now() - interval '200 days'
                WHERE dataset = 'games' AND season = 2026
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO games (
                    game_id, season, game_type, season_type, week, gameday, weekday,
                    gametime, away_team, home_team, location, loaded_at
                ) VALUES (
                    '2015_01_BUF_MIA', 2015, 'REG', 'REG', 1, DATE '2015-09-13', 'Sunday',
                    '13:00', 'BUF', 'MIA', 'Home', now()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO load_runs (
                    run_group, dataset, season, status, trigger, started_at, finished_at,
                    source_url, source_version
                ) VALUES (
                    :run_group, 'games', 2015, 'succeeded', 'local', now(), now(),
                    'https://example.test/2015', 'fresh-history'
                )
                """
            ),
            {"run_group": uuid4()},
        )
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 1
    assert _rows(
        engine, "SELECT reason_code, status FROM salary_private.salary_observations"
    )[0]["reason_code"] == "schedule_evidence_missing"


def test_truncated_schedule_is_not_off_season(engine):
    _seed(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM games WHERE season = 2026 AND week > 10"))
    assert (
        _run(engine, ScriptTransport(_happy_handler(_box())), clock=MutableClock(_et(2026, 12, 23, 10, 0)))
        == 1
    )
    reason = _rows(
        engine, "SELECT reason_code FROM salary_private.salary_observations"
    )[0]["reason_code"]
    assert reason == "schedule_evidence_missing"
    assert reason != "off_season"


def test_login_redirect_keeps_the_body(engine):
    _seed(engine)
    evidence = b"synthetic-login-body"

    def handler(_request):
        return 302, {"location": "https://www.draftkings.com/login", "content-type": "text/plain"}, evidence

    assert _run(engine, ScriptTransport(handler)) == 1
    bodies = [bytes(row["body"]) for row in _rows(engine, "SELECT body FROM salary_private.salary_artifacts")]
    assert evidence in bodies


def test_connect_with_one_second_left_stays_inside_budget():
    from loader.dk_lobby import LOBBY_URL, BoundedClient, CaptureFailure

    clock = MutableClock(NOW, 0)

    class StallConnect(httpx.BaseTransport):
        def handle_request(self, request):
            connect = request.extensions.get("timeout", {}).get("connect", 10.0)
            clock.mono_now += connect
            raise httpx.ConnectTimeout("stall")

    client = BoundedClient(StallConnect(), clock, lambda delay: setattr(clock, "mono_now", clock.mono_now + delay))
    clock.mono_now = HTTP_BUDGET_S - 1
    with pytest.raises(CaptureFailure):
        client.get_json(LOBBY_URL)
    assert clock.mono() - client.started <= HTTP_BUDGET_S


def test_body_read_with_one_second_left_stays_inside_budget():
    from loader.dk_lobby import LOBBY_URL, BoundedClient, CaptureFailure

    clock = MutableClock(NOW, 0)

    class StallRead(httpx.BaseTransport):
        def handle_request(self, request):
            class OneRead(httpx.SyncByteStream):
                def __iter__(self):
                    read_timeout = request.extensions.get("timeout", {}).get("read", 30.0)
                    clock.mono_now += read_timeout
                    raise httpx.ReadTimeout("stall")
                    yield b""

            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=OneRead(),
                request=request,
            )

    client = BoundedClient(StallRead(), clock, lambda delay: setattr(clock, "mono_now", clock.mono_now + delay))
    clock.mono_now = HTTP_BUDGET_S - 1
    with pytest.raises(CaptureFailure):
        client.get_json(LOBBY_URL)
    assert clock.mono() - client.started <= HTTP_BUDGET_S


def test_trickled_stream_stops_at_the_deadline():
    from loader.dk_lobby import CaptureFailure, _read_capped

    clock = MutableClock(NOW, 0)
    produced = {"n": 0}

    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(6):
                produced["n"] += 1
                clock.mono_now += 40
                yield b"abcdefghij"

    response = httpx.Response(200, stream=Slow())
    try:
        with pytest.raises(CaptureFailure) as caught:
            _read_capped(response, deadline=100, clock=clock)
    finally:
        response.close()
    assert caught.value.reason == "http_budget_exhausted"
    assert produced["n"] < 6


def test_body_read_timeout_is_retried(engine):
    _seed(engine)
    state = {"n": 0}

    class TimeoutOnce(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadTimeout("synthetic read timeout")
            yield b""

    def handler(request):
        if request.url.path.endswith("/getcontests"):
            state["n"] += 1
            if state["n"] < 3:
                return httpx.Response(200, stream=TimeoutOnce())
        status, headers, body = _happy_handler(_box())(request)
        return status, headers, body

    class Transport(httpx.BaseTransport):
        def __init__(self):
            self.calls = []

        def handle_request(self, request):
            self.calls.append(request)
            result = handler(request)
            if isinstance(result, httpx.Response):
                return result
            status, headers, body = result
            return httpx.Response(status, headers=headers, content=body, request=request)

    transport = Transport()
    assert _run(engine, transport) == 0
    assert state["n"] == 3


def test_sunday_hydrate_rejects_a_different_group_id(engine):
    _seed(engine)
    lobby = _group(90001, _sunday_games())
    lobby.pop("GameTypeId")
    replacement = _group(99999, _sunday_games())

    def handler(request):
        if request.url.path.endswith("/getcontests"):
            return _json_response({"DraftGroups": [lobby]})
        if request.url.path.startswith("/draftgroups/v1/"):
            return _json_response(replacement)
        return _happy_handler(_box())(request)

    assert _run(engine, ScriptTransport(handler)) == 1
    assert _rows(
        engine, "SELECT reason_code FROM salary_private.salary_observations"
    )[0]["reason_code"] == "mismatched_metadata"
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0


def test_capture_over_the_ceiling_records_failure(engine, monkeypatch):
    import loader.salary_private as private

    _seed(engine)
    monkeypatch.setattr(private, "CUMULATIVE_LIMIT", 0)
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 1
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0
    row = _rows(
        engine,
        """
        SELECT status, reason_code, finished_at, duration_ms
        FROM salary_private.salary_observations
        """,
    )[0]
    assert row["status"] == "failed"
    assert row["reason_code"] == "storage_guard_cumulative"
    assert row["finished_at"] is not None
    assert row["duration_ms"] is not None


def test_flag_off_migrate_leaves_grants_unchanged(database_url, engine, monkeypatch):
    from loader.migrate import migrate_production

    role = "seam_grant_probe"
    monkeypatch.delenv("SALARY_PRIVATE_MIGRATION", raising=False)
    with engine.begin() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        conn.execute(text(f"CREATE ROLE {role}"))
        conn.execute(text(f"GRANT SELECT ON dk_classic_slate TO {role}"))
        conn.execute(text(f"REVOKE ALL ON TABLE teams FROM {role}"))
    monkeypatch.setenv("READONLY_ROLE", role)

    def privileges():
        with engine.connect() as conn:
            slate = conn.execute(
                text("SELECT has_table_privilege(:role, 'public.dk_classic_slate', 'SELECT')"),
                {"role": role},
            ).scalar()
            teams = conn.execute(
                text("SELECT has_table_privilege(:role, 'public.teams', 'SELECT')"),
                {"role": role},
            ).scalar()
        return slate, teams

    before = privileges()
    try:
        migrate_production(database_url, None)
        assert privileges() == before
        assert before == (True, False)
    finally:
        monkeypatch.delenv("READONLY_ROLE", raising=False)
        with engine.begin() as conn:
            conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
            conn.execute(text(f"DROP OWNED BY {role}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {role}"))


def test_unexpected_database_error_stays_a_reason_code(engine, monkeypatch, capsys):
    _seed(engine)

    def explode(*_args, **_kwargs):
        raise RuntimeError("INSERT INTO salary_private VALUES (4242, 'Synthetic Quarterback')")

    monkeypatch.setattr("loader.dk_lobby.insert_running_load_run", explode)
    assert _run(engine, ScriptTransport(_happy_handler(_box()))) == 1
    captured = capsys.readouterr()
    assert "4242" not in captured.out + captured.err
    assert "Synthetic" not in captured.out + captured.err
    assert "capture_failed" in captured.err


def test_cli_help_and_scheduled_alias(engine):
    _seed(engine)
    result = subprocess.run(
        [sys.executable, "-m", "loader.dk_lobby", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--selection" in result.stdout
    assert "--draft-group-id" in result.stdout
    assert _run(
        engine,
        ScriptTransport(_happy_handler(_box())),
        argv=[
            "--season",
            "2026",
            "--week",
            "10",
            "--selection",
            "sunday-afternoon",
            "--trigger",
            "scheduled",
        ],
    ) == 0
    assert _rows(
        engine,
        "SELECT trigger FROM load_runs WHERE dataset = 'dk_lobby_salaries'",
    )[-1]["trigger"] == "schedule"
