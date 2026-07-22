"""End-to-end schedule discovery, raw capture, normalization, and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from collections.abc import Callable
from typing import Any, Iterable

from .config import CrawlerConfig
from .db import Database
from .errors import SchemaError
from .parsers.kbo import parse_boxscore, parse_player_daily, parse_roster
from .parsers.naver import NaverGame, parse_relay, parse_schedule_games
from .quality import QualityIssue, has_errors, validate_game_records
from .raw_store import RawStore
from .repository import (
    record_quality_issues,
    replace_boxscore_data,
    replace_player_daily_data,
    replace_relay_data,
    replace_roster_data,
    set_ingestion_status,
    upsert_schedule_game,
)
from .sources.kbo import KBOSource
from .sources.naver import NaverSource


@dataclass(slots=True)
class CrawlSummary:
    discovered: int = 0
    fetched: int = 0
    validated: int = 0
    quarantined: int = 0
    skipped: int = 0
    failed: int = 0
    roster_records: int = 0
    player_daily_records: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "discovered": self.discovered,
            "fetched": self.fetched,
            "validated": self.validated,
            "quarantined": self.quarantined,
            "skipped": self.skipped,
            "failed": self.failed,
            "roster_records": self.roster_records,
            "player_daily_records": self.player_daily_records,
        }


class Crawler:
    """Coordinates adapters while keeping fetches injectable for tests."""

    def __init__(
        self,
        config: CrawlerConfig,
        *,
        database: Database | None = None,
        naver: NaverSource | None = None,
        kbo: KBOSource | None = None,
    ) -> None:
        self.config = config
        self.database = database or Database(
            config.database_path,
            busy_timeout_ms=config.sqlite_busy_timeout_ms,
        )
        self.raw_store = RawStore(config.raw_dir)
        self.naver = naver or NaverSource()
        self.kbo = kbo or KBOSource()

    def initialize(self) -> None:
        self.config.ensure_directories()
        self.database.initialize()

    def discover_date(
        self,
        game_date: date,
        *,
        crawl_run_id: int | None = None,
    ) -> tuple[str, ...]:
        payload = self.naver.fetch_schedule(game_date)
        artifact = self.raw_store.save_json(
            source="naver",
            season=game_date.year,
            game_id=f"schedule-{game_date.isoformat()}",
            endpoint="/schedule/games",
            parameters={
                "fromDate": game_date.isoformat(),
                "toDate": game_date.isoformat(),
            },
            payload=payload,
        )
        self.database.record_source_request(
            crawl_run_id=crawl_run_id,
            source="naver",
            endpoint="/schedule/games",
            parameters={
                "fromDate": game_date.isoformat(),
                "toDate": game_date.isoformat(),
            },
            artifact=artifact,
        )
        schedule = parse_schedule_games(payload)
        with self.database.transaction() as connection:
            for game in schedule.games:
                upsert_schedule_game(
                    connection,
                    game,
                    season=_season(game, game_date.year),
                    series_type=_series_type(game),
                )
        return tuple(game.game_id for game in schedule.games)

    def discover_range(
        self,
        start_date: date,
        end_date: date,
        *,
        crawl_run_id: int | None = None,
    ) -> tuple[str, ...]:
        if end_date < start_date:
            raise ValueError("end_date must not be before start_date")
        game_ids: list[str] = []
        current = start_date
        while current <= end_date:
            game_ids.extend(self.discover_date(current, crawl_run_id=crawl_run_id))
            current += timedelta(days=1)
        return tuple(dict.fromkeys(game_ids))

    def fetch_game(
        self,
        game_id: str,
        *,
        crawl_run_id: int | None = None,
        validate_kbo: bool = True,
        max_inning: int = 18,
    ) -> tuple[int, int, list[QualityIssue]]:
        season = self._game_season(game_id)
        total_pitches = 0
        total_pas = 0
        empty_extra_innings = 0

        for inning in range(1, max_inning + 1):
            payload = self.naver.fetch_relay(game_id, inning)
            artifact = self.raw_store.save_json(
                source="naver",
                season=season,
                game_id=game_id,
                endpoint=f"/schedule/games/{game_id}/relay",
                parameters={"inning": inning},
                payload=payload,
            )
            request_id = self.database.record_source_request(
                crawl_run_id=crawl_run_id,
                source="naver",
                endpoint=f"/schedule/games/{game_id}/relay",
                parameters={"inning": inning},
                artifact=artifact,
            )
            parsed = parse_relay(payload, game_id=game_id, requested_inning=inning)
            with self.database.game_transaction(game_id) as connection:
                if inning == 1:
                    set_ingestion_status(connection, game_id, "raw")
                pa_count, pitch_count, _ = replace_relay_data(
                    connection,
                    parsed,
                    source_request_id=request_id,
                )
                set_ingestion_status(connection, game_id, "parsed")
            total_pas += pa_count
            total_pitches += pitch_count

            if inning >= 9:
                if parsed.relays:
                    empty_extra_innings = 0
                else:
                    empty_extra_innings += 1
                if inning >= 10 and empty_extra_innings:
                    break

        issues = self.validate_game(game_id, crawl_run_id=crawl_run_id)
        if validate_kbo:
            issues.extend(
                self._capture_kbo_validation(
                    game_id,
                    season=season,
                    crawl_run_id=crawl_run_id,
                )
            )
            if issues:
                with self.database.transaction() as connection:
                    record_quality_issues(
                        connection,
                        issues=issues,
                        game_id=game_id,
                        crawl_run_id=crawl_run_id,
                        source="combined",
                    )
                    set_ingestion_status(
                        connection,
                        game_id,
                        "quarantined" if has_errors(issues) else "validated",
                    )
        return total_pas, total_pitches, issues

    def validate_game(
        self,
        game_id: str,
        *,
        crawl_run_id: int | None = None,
    ) -> list[QualityIssue]:
        with self.database.session() as connection:
            pitches = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT pitch_id, plate_appearance_id, batter_id, pitcher_id,
                           pitch_num, seqno, plate_height
                    FROM pitches
                    WHERE game_id = ?
                    ORDER BY COALESCE(seqno, 2147483647), pitch_id
                    """,
                    (game_id,),
                )
            ]
            plate_appearances = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT plate_appearance_id
                    FROM plate_appearances
                    WHERE game_id = ?
                    """,
                    (game_id,),
                )
            ]
        issues = validate_game_records(
            game_id=game_id,
            pitches=pitches,
            plate_appearances=plate_appearances,
        )
        if not pitches:
            issues.append(
                QualityIssue(
                    severity="error",
                    code="no_pitches",
                    message="No pitch records were parsed for a non-cancelled game",
                    entity_id=game_id,
                )
            )
        with self.database.transaction() as connection:
            record_quality_issues(
                connection,
                issues=issues,
                game_id=game_id,
                crawl_run_id=crawl_run_id,
            )
            set_ingestion_status(
                connection,
                game_id,
                "quarantined" if has_errors(issues) else "validated",
            )
        return issues

    def fetch_roster_snapshot(
        self,
        roster_date: date,
        *,
        crawl_run_id: int | None = None,
        team_id: str | None = None,
        all_teams: bool = True,
    ) -> int:
        html = self.kbo.fetch_roster(
            roster_date,
            team_id=team_id,
            all_teams=all_teams,
        )
        endpoint = "RegisterAll.aspx" if all_teams else "Register.aspx"
        artifact = self.raw_store.save_html(
            source="kbo",
            season=roster_date.year,
            game_id=f"roster-{roster_date.isoformat()}",
            endpoint=endpoint,
            parameters={"date": roster_date.isoformat(), "teamId": team_id},
            html=html,
        )
        request_id = self.database.record_source_request(
            crawl_run_id=crawl_run_id,
            source="kbo",
            endpoint=endpoint,
            parameters={"date": roster_date.isoformat(), "teamId": team_id},
            artifact=artifact,
        )
        records = parse_roster(html, roster_date=roster_date)
        with self.database.transaction() as connection:
            return replace_roster_data(
                connection,
                roster_date=roster_date.isoformat(),
                records=records,
                source_request_id=request_id,
            )

    def fetch_player_daily(
        self,
        player_id: str,
        *,
        season: int,
        roles: Iterable[str] = ("hitter", "pitcher"),
        crawl_run_id: int | None = None,
    ) -> int:
        total = 0
        for role in roles:
            html = self.kbo.fetch_player_daily(
                player_id,
                role=role,
                season_id=season,
            )
            endpoint = f"player-daily-{role}"
            artifact = self.raw_store.save_html(
                source="kbo",
                season=season,
                game_id=f"player-{player_id}",
                endpoint=endpoint,
                parameters={"playerId": player_id, "seasonId": season},
                html=html,
            )
            request_id = self.database.record_source_request(
                crawl_run_id=crawl_run_id,
                source="kbo",
                endpoint=endpoint,
                parameters={"playerId": player_id, "seasonId": season},
                artifact=artifact,
            )
            records = parse_player_daily(
                html,
                player_id=player_id,
                role=role,
                season=season,
            )
            with self.database.transaction() as connection:
                total += replace_player_daily_data(
                    connection,
                    records=records,
                    source_request_id=request_id,
                )
        return total

    def run_dates(
        self,
        dates: Iterable[date],
        *,
        validate_kbo: bool = True,
        finished_only: bool = True,
        skip_validated: bool = False,
        include_roster: bool = False,
        run_type: str = "sync",
        progress: Callable[[str], None] | None = None,
    ) -> CrawlSummary:
        date_values = tuple(dict.fromkeys(dates))
        run_id = self.database.start_crawl_run(
            run_type,
            arguments={
                "dates": [value.isoformat() for value in date_values],
                "validate_kbo": validate_kbo,
                "finished_only": finished_only,
                "skip_validated": skip_validated,
                "include_roster": include_roster,
            },
        )
        summary = CrawlSummary()
        failures: list[str] = []
        try:
            for date_index, game_date in enumerate(date_values, start=1):
                if progress:
                    progress(
                        f"[{date_index}/{len(date_values)}] "
                        f"{game_date.isoformat()} 일정 확인"
                    )
                if include_roster:
                    try:
                        count = self.fetch_roster_snapshot(
                            game_date,
                            crawl_run_id=run_id,
                        )
                        summary.roster_records += count
                        if progress:
                            progress(
                                f"  1군 등록 현황 {count}건 적재"
                            )
                    except Exception as exc:
                        summary.failed += 1
                        failures.append(f"{game_date}: roster: {exc}")
                        if progress:
                            progress(f"  1군 등록 현황 실패: {exc}")
                try:
                    game_ids = self.discover_date(game_date, crawl_run_id=run_id)
                    summary.discovered += len(game_ids)
                except Exception as exc:
                    summary.failed += 1
                    failures.append(f"{game_date}: discovery: {exc}")
                    continue
                for game_id in game_ids:
                    if skip_validated and self._is_validated(game_id):
                        summary.skipped += 1
                        if progress:
                            progress(f"  {game_id}: 이미 검증됨, 건너뜀")
                        continue
                    if finished_only and not self._ready_for_postgame(game_id):
                        summary.skipped += 1
                        if progress:
                            progress(f"  {game_id}: 종료 전/취소 경기, 건너뜀")
                        continue
                    try:
                        if progress:
                            progress(f"  {game_id}: 중계·PTS 수집")
                        _, _, issues = self.fetch_game(
                            game_id,
                            crawl_run_id=run_id,
                            validate_kbo=validate_kbo,
                        )
                        summary.fetched += 1
                        if has_errors(issues):
                            summary.quarantined += 1
                        else:
                            summary.validated += 1
                        if progress:
                            state = "격리" if has_errors(issues) else "검증 완료"
                            progress(f"  {game_id}: {state}, 이슈 {len(issues)}건")
                    except Exception as exc:
                        summary.failed += 1
                        failures.append(f"{game_id}: {exc}")
                        if progress:
                            progress(f"  {game_id}: 실패: {exc}")
            status = "succeeded" if not failures else "partial"
            self.database.finish_crawl_run(
                run_id,
                status=status,
                summary={**summary.as_dict(), "failures": failures},
            )
            return summary
        except BaseException as exc:
            self.database.finish_crawl_run(
                run_id,
                status="failed",
                summary=summary.as_dict(),
                error_text=str(exc),
            )
            raise

    def fetch_period_player_daily(
        self,
        start_date: date,
        end_date: date,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[int, list[str]]:
        """Collect each observed player's season page once per role/season."""

        with self.database.session() as connection:
            targets = list(
                connection.execute(
                    """
                    SELECT DISTINCT player_id, season, role
                    FROM (
                        SELECT p.batter_id AS player_id, g.season, 'hitter' AS role
                        FROM pitches AS p
                        JOIN games AS g ON g.game_id = p.game_id
                        WHERE g.game_date BETWEEN ? AND ? AND p.batter_id IS NOT NULL
                        UNION
                        SELECT p.pitcher_id AS player_id, g.season, 'pitcher' AS role
                        FROM pitches AS p
                        JOIN games AS g ON g.game_id = p.game_id
                        WHERE g.game_date BETWEEN ? AND ? AND p.pitcher_id IS NOT NULL
                    )
                    ORDER BY season, player_id, role
                    """,
                    (
                        start_date.isoformat(),
                        end_date.isoformat(),
                        start_date.isoformat(),
                        end_date.isoformat(),
                    ),
                )
            )
        total = 0
        failures: list[str] = []
        for index, row in enumerate(targets, start=1):
            player_id = str(row["player_id"])
            season = int(row["season"])
            role = str(row["role"])
            if progress:
                progress(
                    f"[선수 {index}/{len(targets)}] "
                    f"{season} {player_id} {role}"
                )
            try:
                total += self.fetch_player_daily(
                    player_id,
                    season=season,
                    roles=(role,),
                )
            except Exception as exc:
                failures.append(f"{season}:{player_id}:{role}: {exc}")
                if progress:
                    progress(f"  선수 일별 기록 실패: {exc}")
        return total, failures

    def _capture_kbo_validation(
        self,
        game_id: str,
        *,
        season: int,
        crawl_run_id: int | None,
    ) -> list[QualityIssue]:
        """Persist official responses; parser-level comparisons are additive."""

        issues: list[QualityIssue] = []
        for endpoint, fetch in (
            ("scoreboard", self.kbo.fetch_scoreboard),
            ("boxscore", self.kbo.fetch_boxscore),
        ):
            try:
                payload = fetch(game_id, season_id=season)
                artifact = self.raw_store.save_json(
                    source="kbo",
                    season=season,
                    game_id=game_id,
                    endpoint=endpoint,
                    parameters={"gameId": game_id, "seasonId": season},
                    payload=payload,
                )
                request_id = self.database.record_source_request(
                    crawl_run_id=crawl_run_id,
                    source="kbo",
                    endpoint=endpoint,
                    method="POST",
                    parameters={"gameId": game_id, "seasonId": season},
                    artifact=artifact,
                )
                if endpoint == "boxscore":
                    parsed = parse_boxscore(payload)
                    with self.database.game_transaction(game_id) as connection:
                        replace_boxscore_data(
                            connection,
                            game_id=game_id,
                            boxscore=parsed,
                            source_request_id=request_id,
                        )
            except Exception as exc:
                self.database.record_source_request(
                    crawl_run_id=crawl_run_id,
                    source="kbo",
                    endpoint=endpoint,
                    method="POST",
                    parameters={"gameId": game_id, "seasonId": season},
                    error_text=str(exc),
                )
                issues.append(
                    QualityIssue(
                        severity="error" if isinstance(exc, SchemaError) else "warning",
                        code=(
                            f"kbo_{endpoint}_schema"
                            if isinstance(exc, SchemaError)
                            else f"kbo_{endpoint}_unavailable"
                        ),
                        message=str(exc),
                        entity_id=game_id,
                    )
                )
        issues.extend(self._compare_official_runs(game_id))
        return issues

    def _compare_official_runs(self, game_id: str) -> list[QualityIssue]:
        with self.database.session() as connection:
            game = connection.execute(
                """
                SELECT away_team_id, home_team_id, away_score, home_score
                FROM games WHERE game_id = ?
                """,
                (game_id,),
            ).fetchone()
            totals = {
                row["team_id"]: row["runs"]
                for row in connection.execute(
                    """
                    SELECT team_id, SUM(runs) AS runs
                    FROM batting_boxscores
                    WHERE game_id = ? AND runs IS NOT NULL
                    GROUP BY team_id
                    """,
                    (game_id,),
                )
            }
        if game is None:
            return []
        issues: list[QualityIssue] = []
        for side in ("away", "home"):
            team_id = game[f"{side}_team_id"]
            schedule_score = game[f"{side}_score"]
            official_runs = totals.get(team_id)
            if (
                team_id is not None
                and schedule_score is not None
                and official_runs is not None
                and int(schedule_score) != int(official_runs)
            ):
                issues.append(
                    QualityIssue(
                        severity="error",
                        code="boxscore_run_mismatch",
                        message=(
                            f"{side} score is {schedule_score}, but official "
                            f"batting runs sum to {official_runs}"
                        ),
                        entity_id=game_id,
                        context={
                            "side": side,
                            "team_id": team_id,
                            "schedule_score": schedule_score,
                            "official_runs": official_runs,
                        },
                    )
                )
        return issues

    def _game_season(self, game_id: str) -> int:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT season FROM games WHERE game_id = ?",
                (game_id,),
            ).fetchone()
        if row is None:
            raise LookupError(
                f"game {game_id} is not in the discovered schedule; discover its date first"
            )
        return int(row["season"])

    def _ready_for_postgame(self, game_id: str) -> bool:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT status, is_cancelled FROM games WHERE game_id = ?",
                (game_id,),
            ).fetchone()
        if row is None or row["is_cancelled"]:
            return False
        status = str(row["status"]).lower()
        ready_tokens = ("result", "end", "final", "종료", "경기종료")
        return any(token in status for token in ready_tokens)

    def _is_validated(self, game_id: str) -> bool:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT ingestion_status FROM games WHERE game_id = ?",
                (game_id,),
            ).fetchone()
        return bool(row and row["ingestion_status"] == "validated")


def _season(game: NaverGame, fallback: int) -> int:
    for value in (
        game.raw.get("seasonYear"),
        game.raw.get("season"),
        game.game_id[-4:] if len(game.game_id) >= 4 else None,
    ):
        try:
            year = int(value)
        except (TypeError, ValueError):
            continue
        if 1982 <= year <= 2100:
            return year
    return fallback


def _series_type(game: NaverGame) -> str:
    text = " ".join(
        str(game.raw.get(key, ""))
        for key in (
            "tournamentPhase",
            "gameType",
            "seriesName",
            "groupName",
            "statusInfo",
        )
    ).lower()
    if any(token in text for token in ("preseason", "exhibition", "시범")):
        return "preseason"
    if any(
        token in text
        for token in (
            "postseason",
            "wildcard",
            "준플레이오프",
            "플레이오프",
            "한국시리즈",
        )
    ):
        return "postseason"
    return "regular"
