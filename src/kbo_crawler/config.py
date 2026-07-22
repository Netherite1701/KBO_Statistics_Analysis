"""Configuration for the KBO crawler.

Only filesystem and SQLite settings live here.  Network/source-specific
configuration belongs to the corresponding source adapter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero, got {parsed}")
    return parsed


@dataclass(frozen=True, slots=True)
class CrawlerConfig:
    """Resolved storage configuration.

    Relative paths supplied through environment variables are resolved from
    ``project_root`` so cron jobs do not depend on their working directory.
    """

    project_root: Path
    data_dir: Path
    database_path: Path
    raw_dir: Path
    sqlite_busy_timeout_ms: int = 5_000

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        project_root: Path | None = None,
    ) -> "CrawlerConfig":
        env = os.environ if environ is None else environ
        root = (project_root or PROJECT_ROOT).resolve()

        data_dir = _resolve_path(env.get("KBO_DATA_DIR", "data"), root)
        database_path = _resolve_path(
            env.get("KBO_DATABASE_PATH", str(data_dir / "kbo.sqlite")), root
        )
        raw_dir = _resolve_path(
            env.get("KBO_RAW_DIR", str(data_dir / "raw")), root
        )
        busy_timeout = _positive_int(
            env.get("KBO_SQLITE_BUSY_TIMEOUT_MS", "5000"),
            "KBO_SQLITE_BUSY_TIMEOUT_MS",
        )

        return cls(
            project_root=root,
            data_dir=data_dir,
            database_path=database_path,
            raw_dir=raw_dir,
            sqlite_busy_timeout_ms=busy_timeout,
        )

    def ensure_directories(self) -> None:
        """Create writable storage directories.

        This is intentionally explicit rather than a side effect of loading
        configuration.
        """

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def load_config(
    environ: Mapping[str, str] | None = None,
    *,
    project_root: Path | None = None,
) -> CrawlerConfig:
    """Load crawler configuration from environment variables."""

    return CrawlerConfig.from_env(environ, project_root=project_root)
