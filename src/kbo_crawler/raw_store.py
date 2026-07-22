"""Immutable gzip storage for raw source responses."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
_EXTENSIONS = {
    "application/json": "json",
    "text/json": "json",
    "text/html": "html",
    "application/xhtml+xml": "html",
}


@dataclass(frozen=True, slots=True)
class RawArtifact:
    """Metadata required to register a raw response in ``source_requests``."""

    source: str
    season: str
    game_id: str
    endpoint: str
    parameters_json: str
    relative_path: str
    sha256: str
    size_bytes: int
    compressed_size_bytes: int
    content_type: str


class RawStore:
    """Store raw responses without mutating previously saved payloads."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def save_json(
        self,
        *,
        source: str,
        season: int | str,
        game_id: str,
        endpoint: str,
        parameters: Mapping[str, Any] | None,
        payload: Any,
    ) -> RawArtifact:
        if isinstance(payload, bytes):
            content = payload
        elif isinstance(payload, str):
            content = payload.encode("utf-8")
        else:
            content = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        return self.save_bytes(
            source=source,
            season=season,
            game_id=game_id,
            endpoint=endpoint,
            parameters=parameters,
            content=content,
            content_type="application/json",
        )

    def save_html(
        self,
        *,
        source: str,
        season: int | str,
        game_id: str,
        endpoint: str,
        parameters: Mapping[str, Any] | None,
        html: str | bytes,
        encoding: str = "utf-8",
    ) -> RawArtifact:
        content = html.encode(encoding) if isinstance(html, str) else html
        return self.save_bytes(
            source=source,
            season=season,
            game_id=game_id,
            endpoint=endpoint,
            parameters=parameters,
            content=content,
            content_type="text/html",
        )

    def save_bytes(
        self,
        *,
        source: str,
        season: int | str,
        game_id: str,
        endpoint: str,
        parameters: Mapping[str, Any] | None,
        content: bytes,
        content_type: str,
    ) -> RawArtifact:
        """Save a response and return stable metadata.

        Both request parameters and payload hashes are part of the filename.
        A corrected upstream response therefore creates a new artifact instead
        of overwriting the response used by an earlier crawl.
        """

        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")

        safe_source = _component(source, "source")
        safe_season = _component(str(season), "season")
        safe_game_id = _component(game_id or "_global", "game_id")
        safe_endpoint = _component(endpoint, "endpoint")
        parameters_json = _canonical_parameters(parameters)
        params_hash = hashlib.sha256(parameters_json.encode("utf-8")).hexdigest()
        payload_hash = hashlib.sha256(content).hexdigest()
        extension = _EXTENSIONS.get(content_type.lower(), "bin")
        filename = (
            f"{safe_endpoint}-{params_hash[:12]}-{payload_hash[:12]}"
            f".{extension}.gz"
        )

        target_dir = self.root / safe_source / safe_season / safe_game_id
        target = target_dir / filename
        target_dir.mkdir(parents=True, exist_ok=True)

        if target.exists():
            compressed_size = target.stat().st_size
        else:
            compressed_size = self._write_atomic(target, content)

        relative_path = PurePosixPath(target.relative_to(self.root)).as_posix()
        return RawArtifact(
            source=source,
            season=str(season),
            game_id=game_id,
            endpoint=endpoint,
            parameters_json=parameters_json,
            relative_path=relative_path,
            sha256=payload_hash,
            size_bytes=len(content),
            compressed_size_bytes=compressed_size,
            content_type=content_type,
        )

    def resolve(self, artifact: RawArtifact | str) -> Path:
        """Resolve a stored relative path and reject traversal outside root."""

        relative = artifact.relative_path if isinstance(artifact, RawArtifact) else artifact
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("raw artifact path escapes the raw store") from exc
        return candidate

    def read(self, artifact: RawArtifact | str) -> bytes:
        with gzip.open(self.resolve(artifact), "rb") as stream:
            return stream.read()

    def verify(self, artifact: RawArtifact) -> bool:
        """Check a stored response against its database payload checksum."""

        digest = hashlib.sha256(self.read(artifact)).hexdigest()
        return digest == artifact.sha256

    @staticmethod
    def _write_atomic(target: Path, content: bytes) -> int:
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(file_descriptor, "wb") as raw_stream:
                # mtime=0 makes the same raw payload byte-for-byte reproducible.
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    fileobj=raw_stream,
                    mtime=0,
                ) as compressed_stream:
                    compressed_stream.write(content)
                raw_stream.flush()
                os.fsync(raw_stream.fileno())
            try:
                os.replace(temporary_name, target)
            except FileExistsError:
                os.unlink(temporary_name)
            return target.stat().st_size
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def _component(value: str, field: str) -> str:
    cleaned = _SAFE_COMPONENT.sub("_", value.strip()).strip("._")
    if not cleaned:
        raise ValueError(f"{field} must contain at least one safe character")
    return cleaned[:120]


def _canonical_parameters(parameters: Mapping[str, Any] | None) -> str:
    return json.dumps(
        dict(parameters or {}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
