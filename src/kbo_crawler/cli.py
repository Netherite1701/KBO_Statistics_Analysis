"""Command-line entry point for repeatable post-game collection."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from .config import load_config
from .db import Database
from .errors import CrawlerError
from .export import export_pitches
from .pipeline import Crawler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kbo-crawl")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="initialize or migrate storage")

    sync = subparsers.add_parser("sync", help="collect recently completed games")
    sync.add_argument("--date", type=_date, help="anchor date (default: yesterday)")
    sync.add_argument("--lookback", type=_positive_int, default=3)
    sync.add_argument("--no-kbo", action="store_true", help="skip official KBO validation")
    sync.add_argument(
        "--include-live",
        action="store_true",
        help="attempt games even when the schedule does not say they are final",
    )

    backfill = subparsers.add_parser(
        "backfill",
        help="discover and collect a historical calendar range",
    )
    backfill.add_argument("--start-year", type=int, default=2021)
    backfill.add_argument("--end-year", type=int, default=date.today().year)
    backfill.add_argument("--from-date", type=_date)
    backfill.add_argument("--to-date", type=_date)
    backfill.add_argument("--no-kbo", action="store_true")
    backfill.add_argument("--include-live", action="store_true")

    period = subparsers.add_parser(
        "period",
        help="resumable wrapper that crawls every date in an explicit range",
    )
    period.add_argument("--from-date", type=_date, required=True)
    period.add_argument("--to-date", type=_date, required=True)
    period.add_argument("--no-kbo", action="store_true")
    period.add_argument("--include-live", action="store_true")
    period.add_argument(
        "--refresh",
        action="store_true",
        help="recrawl games already marked validated",
    )
    period.add_argument(
        "--with-rosters",
        action="store_true",
        help="also request the KBO first-team roster for every calendar date",
    )
    period.add_argument(
        "--with-player-daily",
        action="store_true",
        help="after games, collect season daily pages for every observed player",
    )

    fetch = subparsers.add_parser("fetch-game", help="collect one discovered game")
    fetch.add_argument("game_id")
    fetch.add_argument(
        "--date",
        type=_date,
        help="discover this date first if the game is not yet in SQLite",
    )
    fetch.add_argument("--no-kbo", action="store_true")

    validate = subparsers.add_parser("validate", help="rerun local quality checks")
    validate.add_argument("--game-id")

    roster = subparsers.add_parser("roster", help="collect a dated first-team roster")
    roster.add_argument("date", type=_date)
    roster.add_argument("--team-id")
    roster.add_argument(
        "--per-team",
        action="store_true",
        help="use the detailed per-team page instead of the all-team snapshot",
    )

    daily = subparsers.add_parser(
        "player-daily",
        help="collect official daily game logs for one player",
    )
    daily.add_argument("player_id")
    daily.add_argument("--season", type=int, required=True)
    daily.add_argument(
        "--role",
        choices=("hitter", "pitcher", "both"),
        default="both",
    )

    export = subparsers.add_parser("export", help="export normalized pitches to CSV")
    export.add_argument("output", type=Path)
    selector = export.add_mutually_exclusive_group()
    selector.add_argument("--game-id")
    selector.add_argument("--season", type=int)

    subparsers.add_parser("coverage", help="show schedule and ingestion coverage")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    config = load_config()
    crawler = Crawler(config)
    crawler.initialize()

    try:
        if arguments.command == "init":
            print(config.database_path)
            return 0
        if arguments.command == "sync":
            anchor = arguments.date or (date.today() - timedelta(days=1))
            dates = [
                anchor - timedelta(days=offset)
                for offset in range(arguments.lookback - 1, -1, -1)
            ]
            summary = crawler.run_dates(
                dates,
                validate_kbo=not arguments.no_kbo,
                finished_only=not arguments.include_live,
                run_type="sync",
                progress=_progress,
            )
            print(json.dumps(summary.as_dict(), ensure_ascii=False))
            return 1 if summary.failed else 0
        if arguments.command == "backfill":
            start, end = _backfill_range(arguments)
            dates = _dates(start, end)
            summary = crawler.run_dates(
                dates,
                validate_kbo=not arguments.no_kbo,
                finished_only=not arguments.include_live,
                skip_validated=True,
                run_type="backfill",
                progress=_progress,
            )
            print(json.dumps(summary.as_dict(), ensure_ascii=False))
            return 1 if summary.failed else 0
        if arguments.command == "period":
            if arguments.to_date < arguments.from_date:
                raise ValueError("--to-date must not be before --from-date")
            summary = crawler.run_dates(
                _dates(arguments.from_date, arguments.to_date),
                validate_kbo=not arguments.no_kbo,
                finished_only=not arguments.include_live,
                skip_validated=not arguments.refresh,
                include_roster=arguments.with_rosters,
                run_type="period",
                progress=_progress,
            )
            player_failures: list[str] = []
            if arguments.with_player_daily:
                records, player_failures = crawler.fetch_period_player_daily(
                    arguments.from_date,
                    arguments.to_date,
                    progress=_progress,
                )
                summary.player_daily_records = records
                summary.failed += len(player_failures)
            output = summary.as_dict()
            if player_failures:
                output["player_daily_failures"] = player_failures
            print(json.dumps(output, ensure_ascii=False))
            return 1 if summary.failed else 0
        if arguments.command == "fetch-game":
            if arguments.date is not None:
                crawler.discover_date(arguments.date)
            pa_count, pitch_count, issues = crawler.fetch_game(
                arguments.game_id,
                validate_kbo=not arguments.no_kbo,
            )
            print(
                json.dumps(
                    {
                        "game_id": arguments.game_id,
                        "plate_appearances": pa_count,
                        "pitches": pitch_count,
                        "issues": len(issues),
                    },
                    ensure_ascii=False,
                )
            )
            return 1 if any(issue.severity == "error" for issue in issues) else 0
        if arguments.command == "validate":
            game_ids = (
                [arguments.game_id]
                if arguments.game_id
                else _stored_game_ids(crawler.database)
            )
            result = {
                game_id: [
                    {
                        "severity": issue.severity,
                        "code": issue.code,
                        "message": issue.message,
                    }
                    for issue in crawler.validate_game(game_id)
                ]
                for game_id in game_ids
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if any(
                issue["severity"] == "error"
                for issues in result.values()
                for issue in issues
            ) else 0
        if arguments.command == "roster":
            count = crawler.fetch_roster_snapshot(
                arguments.date,
                team_id=arguments.team_id,
                all_teams=not arguments.per_team,
            )
            print(
                json.dumps(
                    {"date": arguments.date.isoformat(), "roster_records": count},
                    ensure_ascii=False,
                )
            )
            return 0
        if arguments.command == "player-daily":
            roles = (
                ("hitter", "pitcher")
                if arguments.role == "both"
                else (arguments.role,)
            )
            count = crawler.fetch_player_daily(
                arguments.player_id,
                season=arguments.season,
                roles=roles,
            )
            print(
                json.dumps(
                    {
                        "player_id": arguments.player_id,
                        "season": arguments.season,
                        "records": count,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if arguments.command == "export":
            with crawler.database.session() as connection:
                count = export_pitches(
                    connection,
                    arguments.output,
                    game_id=arguments.game_id,
                    season=arguments.season,
                )
            print(json.dumps({"rows": count, "output": str(arguments.output)}))
            return 0
        if arguments.command == "coverage":
            print(json.dumps(_coverage(crawler.database), ensure_ascii=False, indent=2))
            return 0
    except (CrawlerError, ValueError, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


def _backfill_range(arguments: argparse.Namespace) -> tuple[date, date]:
    if (arguments.from_date is None) != (arguments.to_date is None):
        raise ValueError("--from-date and --to-date must be used together")
    if arguments.from_date is not None:
        if arguments.to_date < arguments.from_date:
            raise ValueError("--to-date must not be before --from-date")
        return arguments.from_date, arguments.to_date
    if arguments.start_year < 1982 or arguments.end_year < arguments.start_year:
        raise ValueError("invalid KBO season year range")
    return date(arguments.start_year, 1, 1), date(arguments.end_year, 12, 31)


def _dates(start: date, end: date) -> list[date]:
    return [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    ]


def _stored_game_ids(database: Database) -> list[str]:
    with database.session() as connection:
        return [
            str(row["game_id"])
            for row in connection.execute(
                "SELECT game_id FROM games ORDER BY game_date, game_id"
            )
        ]


def _coverage(database: Database) -> dict[str, object]:
    with database.session() as connection:
        by_status = {
            str(row["ingestion_status"]): int(row["count"])
            for row in connection.execute(
                """
                SELECT ingestion_status, COUNT(*) AS count
                FROM games
                GROUP BY ingestion_status
                ORDER BY ingestion_status
                """
            )
        }
        by_season = [
            {
                "season": int(row["season"]),
                "series_type": str(row["series_type"]),
                "games": int(row["games"]),
                "validated": int(row["validated"]),
                "quarantined": int(row["quarantined"]),
            }
            for row in connection.execute(
                """
                SELECT
                    season,
                    series_type,
                    COUNT(*) AS games,
                    SUM(ingestion_status = 'validated') AS validated,
                    SUM(ingestion_status = 'quarantined') AS quarantined
                FROM games
                GROUP BY season, series_type
                ORDER BY season, series_type
                """
            )
        ]
        requests = int(
            connection.execute("SELECT COUNT(*) FROM source_requests").fetchone()[0]
        )
    return {
        "database": str(database.path),
        "games_by_status": by_status,
        "seasons": by_season,
        "source_requests": requests,
    }


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
