"""Data-quality checks shared by batch ingestion and explicit validation."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    code: str
    message: str
    entity_type: str = "game"
    entity_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


def _value(item: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(item, dict) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return default


def validate_game_records(
    *,
    game_id: str,
    pitches: Iterable[Any],
    plate_appearances: Iterable[Any],
) -> list[QualityIssue]:
    """Validate identity, ownership, and sequence invariants for one game."""

    pitch_rows = list(pitches)
    pa_rows = list(plate_appearances)
    issues: list[QualityIssue] = []

    pitch_ids = [
        str(_value(row, "pitch_id", "pitchId", default="") or "")
        for row in pitch_rows
    ]
    duplicate_ids = [
        pitch_id
        for pitch_id, count in Counter(pitch_ids).items()
        if pitch_id and count > 1
    ]
    if duplicate_ids:
        issues.append(
            QualityIssue(
                severity="error",
                code="duplicate_pitch_id",
                message=f"{len(duplicate_ids)} duplicate pitch identifiers",
                entity_id=game_id,
                context={"pitch_ids": duplicate_ids[:20]},
            )
        )

    missing_pitch_ids = sum(not pitch_id for pitch_id in pitch_ids)
    if missing_pitch_ids:
        issues.append(
            QualityIssue(
                severity="error",
                code="missing_pitch_id",
                message=f"{missing_pitch_ids} pitches have no identifier",
                entity_id=game_id,
            )
        )

    synthetic_pitch_ids = [
        pitch_id for pitch_id in pitch_ids if pitch_id.startswith("synthetic:")
    ]
    if synthetic_pitch_ids:
        issues.append(
            QualityIssue(
                severity="warning",
                code="missing_source_pitch_id",
                message=(
                    f"{len(synthetic_pitch_ids)} pitches use stable synthetic IDs "
                    "because the source supplied no usable pitch ID"
                ),
                entity_id=game_id,
                context={"pitch_ids": synthetic_pitch_ids[:20]},
            )
        )

    text_pitch_rows = [
        row
        for row in pitch_rows
        if _value(row, "seqno", "sequence_number") is not None
    ]
    tracking_only_rows = [
        row
        for row in pitch_rows
        if _value(row, "seqno", "sequence_number") is None
    ]
    missing_batter = sum(
        not _value(row, "batter_id", "batter_code", "batterCode")
        for row in text_pitch_rows
    )
    missing_pitcher = sum(
        not _value(row, "pitcher_id", "pitcher_code", "pitcherCode")
        for row in text_pitch_rows
    )
    for code, count in (
        ("missing_batter_id", missing_batter),
        ("missing_pitcher_id", missing_pitcher),
    ):
        if count:
            issues.append(
                QualityIssue(
                    severity="error",
                    code=code,
                    message=f"{count} pitches are missing a player identifier",
                    entity_id=game_id,
                )
            )

    unmatched_tracking = sum(
        not _value(row, "batter_id", "batter_code", "batterCode")
        or not _value(row, "pitcher_id", "pitcher_code", "pitcherCode")
        for row in tracking_only_rows
    )
    if unmatched_tracking:
        issues.append(
            QualityIssue(
                severity="warning",
                code="unmatched_pts_pitch",
                message=(
                    f"{unmatched_tracking} tracking records have no matching "
                    "text event/player context"
                ),
                entity_id=game_id,
            )
        )

    implausible_heights = [
        {
            "pitch_id": _value(row, "pitch_id", "pitchId"),
            "plate_height": height,
        }
        for row in pitch_rows
        if (height := _value(row, "plate_height", "plateHeight")) is not None
        and (float(height) < 0.0 or float(height) > 6.0)
    ]
    if implausible_heights:
        issues.append(
            QualityIssue(
                severity="warning",
                code="implausible_plate_height",
                message=(
                    f"{len(implausible_heights)} reconstructed crossings are "
                    "outside 0-6 ft; retain them as source-fit outliers"
                ),
                entity_id=game_id,
                context={"pitches": implausible_heights[:20]},
            )
        )

    pa_ids = {
        str(_value(row, "plate_appearance_id", "pa_id", default="") or "")
        for row in pa_rows
    }
    pitch_groups: dict[str, list[Any]] = defaultdict(list)
    for row in pitch_rows:
        pa_id = str(
            _value(row, "plate_appearance_id", "pa_id", default="") or ""
        )
        pitch_groups[pa_id].append(row)

    orphan_pa_ids = sorted(pa_id for pa_id in pitch_groups if pa_id not in pa_ids)
    if orphan_pa_ids:
        issues.append(
            QualityIssue(
                severity="error",
                code="orphan_pitch_pa",
                message=f"{len(orphan_pa_ids)} pitch groups have no plate appearance",
                entity_id=game_id,
                context={"plate_appearance_ids": orphan_pa_ids[:20]},
            )
        )

    for pa_id, rows in pitch_groups.items():
        batters = {
            str(
                _value(row, "batter_id", "batter_code", "batterCode", default="")
                or ""
            )
            for row in rows
        }
        pitchers = {
            str(
                _value(
                    row,
                    "pitcher_id",
                    "pitcher_code",
                    "pitcherCode",
                    default="",
                )
                or ""
            )
            for row in rows
        }
        if len(batters - {""}) > 1:
            issues.append(
                QualityIssue(
                    severity="error",
                    code="mixed_batter_pa",
                    message="A plate appearance contains multiple batters",
                    entity_type="plate_appearance",
                    entity_id=pa_id,
                )
            )
        if len(pitchers - {""}) > 1:
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="pitcher_changed_inside_pa",
                    message="A plate appearance contains multiple pitchers",
                    entity_type="plate_appearance",
                    entity_id=pa_id,
                )
            )

        sequence = [
            _value(row, "pitch_number", "pitch_num", "pitchNum") for row in rows
        ]
        numeric = [int(value) for value in sequence if value is not None]
        if numeric and numeric != sorted(numeric):
            issues.append(
                QualityIssue(
                    severity="error",
                    code="non_monotonic_pitch_sequence",
                    message="Pitch numbers are not in source order",
                    entity_type="plate_appearance",
                    entity_id=pa_id,
                    context={"pitch_numbers": numeric},
                )
            )

    return issues


def has_errors(issues: Iterable[QualityIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)
