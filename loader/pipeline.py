"""One capture execution: gate, migrate, full refresh, proof, then capture.

The coordination lock is held from before migration until the attempt ends.
This module does not dispatch a workflow.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

from loader.coordination import (
    COORDINATION_WAIT_S,
    PIPELINE_DEADLINE_S,
    CoordinationError,
    RefreshStopped,
    coordination,
    ensure_pipeline_ownership,
)
from loader.dk_lobby import (
    SEASON_MAX,
    SEASON_MIN,
    WEEK_MAX,
    WEEK_MIN,
    CaptureFailure,
    Crash,
    capture_schedule_enabled,
    normalize_trigger,
    run_capture,
)
from loader.migrate import migrate_production
from loader.run import current_season, run_load
from loader.salary_private import DATASET, PUBLIC_SOURCE_URL, Source
from loader.schedule_proof import ProofBinding, verify_schedule
from loader.url import normalize_database_url

ET = ZoneInfo("America/New_York")
_DIGITS = set("0123456789")


@dataclass
class PipelineResult:
    ok: bool
    reason: str
    trace: tuple[str, ...]
    persisted: bool = False
    capture: object | None = None


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _digits(value: str | None) -> bool:
    return bool(value) and all(char in _DIGITS for char in value)


def validate_request(
    *,
    trigger: str,
    season: str | None,
    week: str | None,
    draft_group_id: str | None,
    selection: str | None,
) -> tuple[dict | None, str | None]:
    """Reject a bad manual request before any migration or refresh write."""
    try:
        trigger_name = normalize_trigger(trigger)
    except CaptureFailure:
        return None, "invalid_trigger"
    draft = _blank(draft_group_id)
    chosen = _blank(selection)
    if trigger_name == "schedule":
        if draft is not None or (chosen is not None and chosen != "sunday-afternoon"):
            return None, "invalid_selector"
        return {
            "trigger": trigger_name,
            "season": None,
            "week": None,
            "draft_group_id": None,
            "selection": "sunday-afternoon",
            "automatic": True,
        }, None
    season_text = _blank(season)
    week_text = _blank(week)
    if not _digits(season_text):
        return None, "invalid_season"
    if not _digits(week_text):
        return None, "invalid_week"
    season_number = int(season_text)
    week_number = int(week_text)
    if season_number < SEASON_MIN or season_number > SEASON_MAX:
        return None, "season_out_of_range"
    if week_number < WEEK_MIN or week_number > WEEK_MAX:
        return None, "week_out_of_range"
    if draft and chosen:
        return None, "invalid_selector"
    if draft is None and chosen != "sunday-afternoon":
        return None, "invalid_selector"
    if draft is not None and not _digits(draft):
        return None, "invalid_draft_group"
    if draft is not None and int(draft) <= 0:
        return None, "invalid_draft_group"
    return {
        "trigger": trigger_name,
        "season": season_number,
        "week": week_number,
        "draft_group_id": draft,
        "selection": None if draft else "sunday-afternoon",
        "automatic": False,
    }, None


def _pipeline_metadata(stage: str, run_group, games_ids, scope: str) -> dict:
    return {
        "pipeline_stage": stage,
        "pipeline_refresh_run_group": None if run_group is None else str(run_group),
        "pipeline_games_load_run_ids": [int(item) for item in games_ids],
        "pipeline_timing_scope": scope,
    }


def _duration_ms(clock, started_mono: float) -> int | None:
    elapsed = int((float(clock.mono()) - started_mono) * 1000)
    if elapsed < 0:
        return None
    return elapsed


def _record_failure(
    engine,
    *,
    clock,
    started_wall: datetime,
    started_mono: float,
    trigger: str,
    reason: str,
    stage: str,
    run_group,
    games_ids,
    season: int | None,
) -> bool:
    """Write one private failure when the tables exist. Never claim success."""
    try:
        conn = engine.connect()
    except Exception:  # noqa: BLE001 - a refused connection is not an audit row
        return False
    try:
        present = conn.execute(
            text("SELECT to_regclass('salary_private.salary_observations')")
        ).scalar()
        conn.commit()
        if present is None:
            return False
        finished = clock.wall()
        duration = _duration_ms(clock, started_mono)
        metadata = _pipeline_metadata(stage, run_group, games_ids, "pipeline")
        metadata["parser_version"] = "f005.1"
        group = uuid4()
        with conn.begin():
            run_id = conn.execute(
                text(
                    """
                    INSERT INTO load_runs (
                        run_group, dataset, season, status, trigger, started_at,
                        finished_at, source_url, notes, error, rows_read,
                        rows_upserted, rows_deleted, rows_skipped
                    ) VALUES (
                        :run_group, :dataset, :season, 'failed', :trigger, :started_at,
                        :finished_at, :source_url, :notes, :error, 0, 0, 0, 0
                    )
                    RETURNING id
                    """
                ),
                {
                    "run_group": group,
                    "dataset": DATASET,
                    "season": season,
                    "trigger": trigger,
                    "started_at": started_wall,
                    "finished_at": finished,
                    "source_url": PUBLIC_SOURCE_URL,
                    "notes": f"reason={reason};rows=0;snapshots=0",
                    "error": reason,
                },
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO salary_private.salary_observations (
                        observation_id, load_run_id, source, requested_at, started_at,
                        finished_at, duration_ms, observed_at, source_url, metadata,
                        status, reason_code, loaded_at
                    ) VALUES (
                        :observation_id, :load_run_id, :source, :requested_at, :started_at,
                        :finished_at, :duration_ms, :observed_at, :source_url,
                        CAST(:metadata AS jsonb), 'failed', :reason_code, :loaded_at
                    )
                    """
                ),
                {
                    "observation_id": uuid4(),
                    "load_run_id": int(run_id),
                    "source": Source.DK_LOBBY.value,
                    "requested_at": started_wall,
                    "started_at": started_wall,
                    "finished_at": finished,
                    "duration_ms": duration,
                    "observed_at": started_wall,
                    "source_url": PUBLIC_SOURCE_URL,
                    "metadata": json.dumps(metadata),
                    "reason_code": reason,
                    "loaded_at": finished,
                },
            )
        return True
    except Exception:  # noqa: BLE001 - do not claim an audit row when the write fails
        return False
    finally:
        conn.close()


def run_pipeline(
    *,
    database_url: str,
    trigger: str,
    season: str | None = None,
    week: str | None = None,
    draft_group_id: str | None = None,
    selection: str | None = None,
    gate: str | None = None,
    data_dir=None,
    source=None,
    transport=None,
    clock=None,
    sleeper=None,
    engine=None,
    wait_seconds: float = COORDINATION_WAIT_S,
    deadline_s: float = PIPELINE_DEADLINE_S,
    checkpoint=None,
    failpoint: str | None = None,
    before_terminal=None,
) -> PipelineResult:
    from loader.dk_lobby import system_clock

    clock = clock or system_clock()
    trace = ["gate"]
    if not capture_schedule_enabled(gate):
        return PipelineResult(False, "capture_disabled", tuple(trace), False)
    trace.append("validation")
    request, problem = validate_request(
        trigger=trigger,
        season=season,
        week=week,
        draft_group_id=draft_group_id,
        selection=selection,
    )
    if problem is not None:
        return PipelineResult(False, problem, tuple(trace), False)
    started_wall = clock.wall()
    started_mono = float(clock.mono())
    deadline_mono = started_mono + float(deadline_s)
    own_engine = engine is None
    if engine is None:
        try:
            engine = create_engine(
                normalize_database_url(database_url),
                pool_pre_ping=True,
                connect_args={"connect_timeout": 5},
            )
        except Exception:  # noqa: BLE001 - the URL must not be printed
            return PipelineResult(False, "database_unreachable", tuple(trace), False)
    run_group = None
    games_ids: list[int] = []
    try:
        with coordination(
            engine,
            wait_seconds=wait_seconds,
            clock=clock,
            deadline_mono=deadline_mono,
            started_mono=started_mono,
        ):
            trace.append("migration")
            try:
                ensure_pipeline_ownership()
                migrate_production(database_url, os.environ.get("SALARY_PRIVATE_MIGRATION"))
            except CoordinationError:
                raise
            except Exception:  # noqa: BLE001 - migration errors stay a reason code
                persisted = _record_failure(
                    engine,
                    clock=clock,
                    started_wall=started_wall,
                    started_mono=started_mono,
                    trigger=request["trigger"],
                    reason="migrate_failed",
                    stage="migration",
                    run_group=None,
                    games_ids=[],
                    season=request["season"],
                )
                return PipelineResult(False, "migrate_failed", tuple(trace), persisted)
            trace.append("refresh")
            if request["automatic"]:
                moment = started_wall.astimezone(ET).date()
                seasons = [current_season(moment)]
            else:
                seasons = [request["season"]]
            loaded: dict = {}

            def _checkpoint():
                ensure_pipeline_ownership()
                if checkpoint is not None:
                    checkpoint()

            try:
                ok = run_load(
                    database_url=database_url,
                    seasons=seasons,
                    trigger=request["trigger"],
                    data_dir=data_dir,
                    source=source,
                    checkpoint=_checkpoint,
                    out=loaded,
                )
            except RefreshStopped as exc:
                persisted = _record_failure(
                    engine,
                    clock=clock,
                    started_wall=started_wall,
                    started_mono=started_mono,
                    trigger=request["trigger"],
                    reason=exc.reason,
                    stage="refresh",
                    run_group=loaded.get("run_group"),
                    games_ids=loaded.get("games_load_run_ids") or [],
                    season=request["season"],
                )
                return PipelineResult(False, exc.reason, tuple(trace), persisted)
            run_group = loaded.get("run_group")
            games_ids = [int(item) for item in loaded.get("games_load_run_ids") or []]
            if not ok:
                persisted = _record_failure(
                    engine,
                    clock=clock,
                    started_wall=started_wall,
                    started_mono=started_mono,
                    trigger=request["trigger"],
                    reason="refresh_failed",
                    stage="refresh",
                    run_group=run_group,
                    games_ids=games_ids,
                    season=request["season"],
                )
                return PipelineResult(False, "refresh_failed", tuple(trace), persisted)
            trace.append("proof")
            ensure_pipeline_ownership()
            binding = ProofBinding(str(run_group), tuple(games_ids))
            try:
                proof = engine.connect()
            except Exception:  # noqa: BLE001 - the URL must not be printed
                return PipelineResult(False, "database_unreachable", tuple(trace), False)
            try:
                verdict = verify_schedule(proof, clock.wall(), binding=binding)
            finally:
                proof.close()
            if verdict.evidence == "schedule_evidence_missing":
                persisted = _record_failure(
                    engine,
                    clock=clock,
                    started_wall=started_wall,
                    started_mono=started_mono,
                    trigger=request["trigger"],
                    reason="schedule_evidence_missing",
                    stage="proof",
                    run_group=run_group,
                    games_ids=games_ids,
                    season=request["season"],
                )
                return PipelineResult(
                    False, "schedule_evidence_missing", tuple(trace), persisted
                )
            trace.append("capture")
            ensure_pipeline_ownership()
            capture = run_capture(
                engine,
                season=request["season"],
                week=request["week"],
                trigger=request["trigger"],
                selection=request["selection"],
                draft_group_id=request["draft_group_id"],
                transport=transport,
                clock=clock,
                sleeper=sleeper,
                failpoint=failpoint,
                before_terminal=before_terminal,
                proof_binding=binding,
                pipeline_meta=_pipeline_metadata("capture", run_group, games_ids, "capture"),
            )
            return PipelineResult(
                bool(capture.exit_ok),
                capture.reason,
                tuple(trace),
                bool(capture.persisted),
                capture,
            )
    except Crash:
        raise
    except CoordinationError as exc:
        stage = trace[-1] if trace else "terminal"
        persisted = False
        if exc.reason != "pipeline_busy":
            persisted = _record_failure(
                engine,
                clock=clock,
                started_wall=started_wall,
                started_mono=started_mono,
                trigger=request["trigger"],
                reason=exc.reason,
                stage=stage if stage in {"migration", "refresh", "proof", "capture"} else "terminal",
                run_group=run_group,
                games_ids=games_ids,
                season=request["season"],
            )
        return PipelineResult(False, exc.reason, tuple(trace), persisted)
    finally:
        if own_engine and engine is not None:
            engine.dispose()


def _report(result: PipelineResult) -> None:
    if result.reason == "capture_disabled":
        return
    if not result.persisted and result.reason == "database_unreachable":
        print("database_unreachable", file=sys.stderr)
        return
    if result.capture is not None:
        from loader.dk_lobby import _report as report_capture

        report_capture(result.capture)
        return
    print(f"pipeline stage={result.trace[-1]} result={result.reason}", flush=True)
    if not result.ok:
        print(result.reason, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loader.pipeline")
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
    database_url = os.environ.get("DATABASE_URL")
    if not database_url and capture_schedule_enabled(os.environ.get("DK_LOBBY_CAPTURE_ENABLED")):
        # Validation can still fail before this, but a missing URL is not a write.
        request, problem = validate_request(
            trigger=args.trigger,
            season=args.season,
            week=args.week,
            draft_group_id=args.draft_group_id,
            selection=args.selection,
        )
        if problem is not None:
            print(problem, file=sys.stderr)
            return 1
        if request is None:
            return 1
        print("database_unreachable", file=sys.stderr)
        return 1
    try:
        result = run_pipeline(
            database_url=database_url or "",
            trigger=args.trigger,
            season=args.season,
            week=args.week,
            draft_group_id=args.draft_group_id,
            selection=args.selection,
            gate=os.environ.get("DK_LOBBY_CAPTURE_ENABLED"),
        )
    except Crash:
        return 1
    except Exception:  # noqa: BLE001 - never print SQL or the database URL
        print("capture_failed", file=sys.stderr)
        return 1
    _report(result)
    if result.reason == "capture_disabled":
        return 1
    if not result.persisted and result.reason == "database_unreachable":
        return 1
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
