"""SQLite connection, migrations, and atomic game-write helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterator, Mapping

from .raw_store import RawArtifact


class MigrationError(RuntimeError):
    """Raised when a migration cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    name: str
    sql: str
    checksum: str


class Database:
    """Own connections to the crawler's single SQLite database."""

    def __init__(
        self,
        path: str | Path,
        *,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be greater than zero")
        self.path = Path(path).resolve()
        self.busy_timeout_ms = busy_timeout_ms

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms:d}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create or upgrade the database to the latest bundled schema."""

        with self.session() as connection:
            self._ensure_migration_table(connection)
            applied = {
                row["version"]: row
                for row in connection.execute(
                    "SELECT version, name, checksum FROM schema_migrations"
                )
            }
            for migration in load_migrations():
                previous = applied.get(migration.version)
                if previous is not None:
                    if (
                        previous["name"] != migration.name
                        or previous["checksum"] != migration.checksum
                    ):
                        raise MigrationError(
                            f"migration {migration.version} changed after application"
                        )
                    continue
                self._apply_migration(connection, migration)

    @contextmanager
    def transaction(
        self,
        *,
        immediate: bool = True,
    ) -> Iterator[sqlite3.Connection]:
        """Run arbitrary writes atomically on a fresh connection."""

        with self.session() as connection:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def game_transaction(self, game_id: str) -> Iterator[sqlite3.Connection]:
        """Provide one all-or-nothing transaction for a game's parsed rows."""

        if not game_id.strip():
            raise ValueError("game_id must not be empty")
        with self.transaction(immediate=True) as connection:
            yield connection

    def start_crawl_run(
        self,
        run_type: str,
        *,
        arguments: Mapping[str, Any] | None = None,
    ) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO crawl_runs (run_type, status, arguments_json)
                VALUES (?, 'running', ?)
                """,
                (run_type, _json(arguments or {})),
            )
            return int(cursor.lastrowid)

    def finish_crawl_run(
        self,
        run_id: int,
        *,
        status: str,
        summary: Mapping[str, Any] | None = None,
        error_text: str | None = None,
    ) -> None:
        if status not in {"succeeded", "failed", "partial"}:
            raise ValueError("status must be succeeded, failed, or partial")
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE crawl_runs
                SET status = ?, finished_at = ?, summary_json = ?, error_text = ?
                WHERE crawl_run_id = ? AND status = 'running'
                """,
                (status, _utc_now(), _json(summary or {}), error_text, run_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"running crawl run {run_id} was not found")

    def record_source_request(
        self,
        *,
        crawl_run_id: int | None,
        source: str,
        endpoint: str,
        method: str = "GET",
        parameters: Mapping[str, Any] | None = None,
        status_code: int | None = None,
        elapsed_ms: int | None = None,
        attempt: int = 1,
        artifact: RawArtifact | None = None,
        error_text: str | None = None,
    ) -> int:
        """Register request provenance and an optional stored raw response."""

        if artifact is not None:
            if artifact.source != source:
                raise ValueError("artifact source does not match request source")
            if artifact.endpoint != endpoint:
                raise ValueError("artifact endpoint does not match request endpoint")
        state = "failed" if error_text else "succeeded"
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO source_requests (
                    crawl_run_id, source, season, game_id, endpoint, method, parameters_json,
                    status_code, response_content_type, raw_path, sha256,
                    response_size_bytes, compressed_size_bytes, elapsed_ms,
                    attempt, state, error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    crawl_run_id,
                    source,
                    artifact.season if artifact else None,
                    artifact.game_id if artifact else None,
                    endpoint,
                    method.upper(),
                    artifact.parameters_json if artifact else _json(parameters or {}),
                    status_code,
                    artifact.content_type if artifact else None,
                    artifact.relative_path if artifact else None,
                    artifact.sha256 if artifact else None,
                    artifact.size_bytes if artifact else None,
                    artifact.compressed_size_bytes if artifact else None,
                    elapsed_ms,
                    attempt,
                    state,
                    error_text,
                ),
            )
            return int(cursor.lastrowid)

    def record_data_quality_issue(
        self,
        *,
        severity: str,
        issue_code: str,
        message: str,
        crawl_run_id: int | None = None,
        game_id: str | None = None,
        source: str | None = None,
        entity_type: str = "game",
        entity_id: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> int:
        """Persist a validation issue without coupling to a validator class."""

        if severity not in {"info", "warning", "error"}:
            raise ValueError("severity must be info, warning, or error")
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO data_quality_issues (
                    crawl_run_id, game_id, source, entity_type, entity_id,
                    severity, issue_code, message, context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    crawl_run_id,
                    game_id,
                    source,
                    entity_type,
                    entity_id,
                    severity,
                    issue_code,
                    message,
                    _json(context or {}),
                ),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def _ensure_migration_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )

    @staticmethod
    def _apply_migration(
        connection: sqlite3.Connection,
        migration: Migration,
    ) -> None:
        # sqlite3.executescript commits any open transaction, so transaction
        # control is included in the script itself.
        values = tuple(
            value.replace("'", "''")
            for value in (migration.version, migration.name, migration.checksum)
        )
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql}\n"
            "INSERT INTO schema_migrations (version, name, checksum) "
            f"VALUES ('{values[0]}', '{values[1]}', '{values[2]}');\n"
            "COMMIT;\n"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            raise MigrationError(
                f"failed to apply migration {migration.version} ({migration.name})"
            ) from exc


def load_migrations() -> tuple[Migration, ...]:
    migration_root = files("kbo_crawler").joinpath("migrations")
    migrations: list[Migration] = []
    for resource in sorted(
        (
            child
            for child in migration_root.iterdir()
            if child.name.endswith(".sql")
        ),
        key=lambda child: child.name,
    ):
        stem = resource.name[:-4]
        version, separator, name = stem.partition("_")
        if not separator or not version.isdigit() or not name:
            raise MigrationError(
                f"invalid migration filename {resource.name!r}; "
                "expected NNN_name.sql"
            )
        sql = resource.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=version,
                name=name,
                sql=sql,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )

    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise MigrationError("migration versions must be unique")
    return tuple(migrations)


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
