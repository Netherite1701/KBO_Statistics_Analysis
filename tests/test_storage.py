from __future__ import annotations

import gzip
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kbo_crawler.config import CrawlerConfig
from kbo_crawler.db import Database, load_migrations
from kbo_crawler.raw_store import RawStore


class ConfigTests(unittest.TestCase):
    def test_paths_are_resolved_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = CrawlerConfig.from_env(
                {
                    "KBO_DATA_DIR": "var/data",
                    "KBO_DATABASE_PATH": "var/db.sqlite",
                    "KBO_RAW_DIR": "var/raw",
                    "KBO_SQLITE_BUSY_TIMEOUT_MS": "7500",
                },
                project_root=root,
            )

            self.assertEqual(config.data_dir, (root / "var/data").resolve())
            self.assertEqual(config.database_path, (root / "var/db.sqlite").resolve())
            self.assertEqual(config.raw_dir, (root / "var/raw").resolve())
            self.assertEqual(config.sqlite_busy_timeout_ms, 7_500)


class RawStoreTests(unittest.TestCase):
    def test_json_is_canonical_immutable_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(temporary)
            first = store.save_json(
                source="naver",
                season=2026,
                game_id="20260506HHHT02026",
                endpoint="relay/1",
                parameters={"inning": 1, "gameId": "20260506HHHT02026"},
                payload={"선수": "홍길동", "values": [1, 2]},
            )
            repeated = store.save_json(
                source="naver",
                season=2026,
                game_id="20260506HHHT02026",
                endpoint="relay/1",
                parameters={"gameId": "20260506HHHT02026", "inning": 1},
                payload={"values": [1, 2], "선수": "홍길동"},
            )
            corrected = store.save_json(
                source="naver",
                season=2026,
                game_id="20260506HHHT02026",
                endpoint="relay/1",
                parameters={"inning": 1, "gameId": "20260506HHHT02026"},
                payload={"선수": "홍길동", "values": [1, 3]},
            )

            self.assertEqual(first.relative_path, repeated.relative_path)
            self.assertNotEqual(first.relative_path, corrected.relative_path)
            self.assertEqual(
                json.loads(store.read(first).decode("utf-8")),
                {"선수": "홍길동", "values": [1, 2]},
            )
            self.assertTrue(store.verify(first))
            with gzip.open(store.resolve(first), "rb") as stream:
                self.assertEqual(stream.read(), store.read(first))

    def test_raw_json_bytes_are_preserved_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(temporary)
            original = b'{  "source-order": 1, "next": 2 }\r\n'
            artifact = store.save_json(
                source="naver",
                season=2026,
                game_id="game-1",
                endpoint="relay",
                parameters={},
                payload=original,
            )

            self.assertEqual(store.read(artifact), original)
            self.assertTrue(store.verify(artifact))

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(temporary)
            with self.assertRaises(ValueError):
                store.resolve("../outside.json.gz")


class DatabaseTests(unittest.TestCase):
    def test_migrations_pragmas_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "kbo.sqlite", busy_timeout_ms=7_000)
            database.initialize()
            database.initialize()

            with database.session() as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertTrue(
                    {
                        "games",
                        "plate_appearances",
                        "pitches",
                        "source_requests",
                        "data_quality_issues",
                    }.issubset(tables)
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_keys").fetchone()[0], 1
                )
                self.assertEqual(
                    connection.execute("PRAGMA journal_mode").fetchone()[0], "wal"
                )
                self.assertEqual(
                    connection.execute("PRAGMA busy_timeout").fetchone()[0], 7_000
                )
                count = connection.execute(
                    "SELECT count(*) FROM schema_migrations"
                ).fetchone()[0]
                self.assertEqual(count, len(load_migrations()))

    def test_game_transaction_rolls_back_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "kbo.sqlite")
            database.initialize()

            with self.assertRaisesRegex(RuntimeError, "parser failed"):
                with database.game_transaction("game-1") as connection:
                    connection.execute(
                        """
                        INSERT INTO games (
                            game_id, season, series_type, game_date, status
                        ) VALUES ('game-1', 2026, 'regular', '2026-05-06', 'final')
                        """
                    )
                    raise RuntimeError("parser failed")

            with database.session() as connection:
                self.assertIsNone(
                    connection.execute(
                        "SELECT game_id FROM games WHERE game_id = 'game-1'"
                    ).fetchone()
                )

    def test_foreign_keys_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "kbo.sqlite")
            database.initialize()

            with self.assertRaises(sqlite3.IntegrityError):
                with database.transaction() as connection:
                    connection.execute(
                        """
                        INSERT INTO plate_appearances (
                            plate_appearance_id, game_id, relay_no, inning, half
                        ) VALUES ('missing-1', 'missing', 1, 1, 'top')
                        """
                    )

    def test_run_and_request_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = Database(root / "kbo.sqlite")
            database.initialize()
            store = RawStore(root / "raw")
            artifact = store.save_html(
                source="kbo",
                season=2026,
                game_id="game-1",
                endpoint="boxscore",
                parameters={"gameId": "game-1"},
                html="<html>ok</html>",
            )

            run_id = database.start_crawl_run("fetch-game", arguments={"game": "game-1"})
            request_id = database.record_source_request(
                crawl_run_id=run_id,
                source="kbo",
                endpoint="boxscore",
                status_code=200,
                elapsed_ms=10,
                artifact=artifact,
            )
            database.finish_crawl_run(run_id, status="succeeded", summary={"games": 1})

            with database.session() as connection:
                request = connection.execute(
                    "SELECT * FROM source_requests WHERE source_request_id = ?",
                    (request_id,),
                ).fetchone()
                run = connection.execute(
                    "SELECT * FROM crawl_runs WHERE crawl_run_id = ?", (run_id,)
                ).fetchone()
                self.assertEqual(request["sha256"], artifact.sha256)
                self.assertEqual(request["raw_path"], artifact.relative_path)
                self.assertEqual(request["game_id"], "game-1")
                self.assertEqual(request["season"], "2026")
                self.assertEqual(run["status"], "succeeded")

    def test_quality_issue_keeps_entity_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "kbo.sqlite")
            database.initialize()
            with database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO games (
                        game_id, season, series_type, game_date, status
                    ) VALUES ('game-1', 2026, 'regular', '2026-05-06', 'final')
                    """
                )

            issue_id = database.record_data_quality_issue(
                game_id="game-1",
                source="naver",
                entity_type="plate_appearance",
                entity_id="game-1:17",
                severity="error",
                issue_code="mixed_batter_pa",
                message="multiple batters",
                context={"batters": ["1", "2"]},
            )

            with database.session() as connection:
                issue = connection.execute(
                    """
                    SELECT * FROM data_quality_issues
                    WHERE data_quality_issue_id = ?
                    """,
                    (issue_id,),
                ).fetchone()
                self.assertEqual(issue["entity_type"], "plate_appearance")
                self.assertEqual(issue["entity_id"], "game-1:17")


if __name__ == "__main__":
    unittest.main()
