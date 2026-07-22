"""Pure parsers for official KBO JSON and HTML responses."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from kbo_crawler.errors import SchemaError

_MISSING = {"", "-", "—", "–", "N/A", "n/a", "null", "None"}
_PLAYER_ID_RE = re.compile(r"(?:playerId|p_id)=([A-Za-z0-9_-]+)", re.I)
_GAME_ID_RE = re.compile(r"(?:gameId|game_id|g_id)=([A-Za-z0-9_-]+)", re.I)
_MONTH_RE = re.compile(r"(\d{1,2})월")
_DAY_RE = re.compile(r"(\d{1,2})[.\-/](\d{1,2})")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

_BOX_COLUMN_MAP = {
    "선수명": "player_name",
    "선수": "player_name",
    "player": "player_name",
    "타순": "lineup_seq",
    "순": "appearance_seq",
    "pa": "plate_appearances",
    "타석": "plate_appearances",
    "ab": "at_bats",
    "타수": "at_bats",
    "r": "runs",
    "득점": "runs",
    "h": "hits",
    "안타": "hits",
    "2b": "doubles",
    "2루타": "doubles",
    "3b": "triples",
    "3루타": "triples",
    "hr": "home_runs",
    "홈런": "home_runs",
    "rbi": "rbi",
    "타점": "rbi",
    "bb": "walks",
    "볼넷": "walks",
    "ibb": "intentional_walks",
    "고의4구": "intentional_walks",
    "hbp": "hit_by_pitch",
    "사구": "hit_by_pitch",
    "so": "strikeouts",
    "삼진": "strikeouts",
    "sh": "sacrifice_hits",
    "희생번트": "sacrifice_hits",
    "sf": "sacrifice_flies",
    "희생플라이": "sacrifice_flies",
    "sb": "stolen_bases",
    "도루": "stolen_bases",
    "cs": "caught_stealing",
    "도루실패": "caught_stealing",
    "ip": "innings_pitched",
    "이닝": "innings_pitched",
    "tbf": "batters_faced",
    "타자": "batters_faced",
    "np": "pitches",
    "투구수": "pitches",
    "er": "earned_runs",
    "자책": "earned_runs",
    "결과": "result",
}


def normalize_missing(value: Any) -> Any:
    """Convert source missing markers to ``None`` without guessing numeric types."""

    if value is None:
        return None
    if isinstance(value, str):
        cleaned = " ".join(value.replace("\xa0", " ").split())
        return None if cleaned in _MISSING else cleaned
    return value


def parse_schedule(html: str) -> list[dict[str, Any]]:
    """Parse either the KBO game-centre carousel or schedule result table."""

    soup = _html(html, "KBO schedule")
    games: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in soup.select("[g_id], [game_id], [data-game-id]"):
        game_id = (
            item.get("g_id") or item.get("game_id") or item.get("data-game-id")
        )
        if not game_id or game_id in seen:
            continue
        seen.add(str(game_id))
        games.append(
            {
                "external_game_id": str(game_id),
                "season": _int_or_none(item.get("season")),
                "series_id": normalize_missing(item.get("sr_id")),
                "league_id": normalize_missing(item.get("le_id")),
                "game_date": _date_from_compact(item.get("g_dt")),
                "status": normalize_missing(
                    _text(item.select_one(".staus, .status")) or item.get("game_sc")
                ),
                "away_team_id": normalize_missing(item.get("away_id")),
                "home_team_id": normalize_missing(item.get("home_id")),
                "away_team_name": normalize_missing(item.get("away_nm")),
                "home_team_name": normalize_missing(item.get("home_nm")),
                "ballpark": normalize_missing(item.get("s_nm")),
                "doubleheader_game": _doubleheader_number(item),
            }
        )

    if games:
        return games

    # Monthly Schedule.aspx uses ordinary table rows.  Attribute names have
    # changed over time, so retain every visible field and extract IDs from
    # links/data attributes rather than constructing them.
    for row in soup.select("table tbody tr"):
        game_id = _find_game_id(row)
        cells = [normalize_missing(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
        if not game_id or game_id in seen:
            continue
        seen.add(game_id)
        games.append(
            {
                "external_game_id": game_id,
                "game_date": _find_date(cells),
                "values": cells,
                "status": _find_status(cells),
            }
        )
    return games


def parse_boxscore(payload: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Normalize the nested KBO box-score table envelope.

    KBO sometimes JSON-encodes team groups, individual tables, or rows a
    second time.  This parser handles all three without silently dropping a
    malformed group.
    """

    if not isinstance(payload, Mapping):
        raise SchemaError("KBO boxscore root must be an object")
    if "arrHitter" not in payload and "arrPitcher" not in payload:
        raise SchemaError("KBO boxscore has no recognized team arrays")
    batting = _parse_box_groups(payload.get("arrHitter", []), category="batting")
    pitching = _parse_box_groups(payload.get("arrPitcher", []), category="pitching")
    return {"batting": batting, "pitching": pitching}


def parse_player_daily(
    html: str,
    *,
    player_id: str | int | None = None,
    role: str = "hitter",
    season: int | None = None,
) -> list[dict[str, Any]]:
    """Parse game rows and month totals from a KBO player daily page."""

    role_key = role.lower()
    if role_key not in {"hitter", "pitcher"}:
        raise ValueError("role must be 'hitter' or 'pitcher'")
    soup = _html(html, "KBO player daily")
    resolved_season = season or _selected_year(soup)
    if resolved_season is None:
        raise SchemaError("KBO daily page does not expose a selected season")
    resolved_player = str(player_id) if player_id is not None else _player_id_from_soup(soup)

    records: list[dict[str, Any]] = []
    for table in soup.select("table.tbl, .tbl-type02 table"):
        header_cells = table.select("thead tr:first-child th")
        if len(header_cells) < 2:
            continue
        first_header = normalize_missing(header_cells[0].get_text(" ", strip=True))
        month_match = _MONTH_RE.search(str(first_header or ""))
        if not month_match:
            continue
        month = int(month_match.group(1))
        columns = ["date", *[_column_name(cell.get_text(" ", strip=True)) for cell in header_cells[1:]]]

        for row in table.select("tbody tr"):
            values = _row_values(row)
            if len(values) < 2:
                continue
            day_match = _DAY_RE.search(str(values[0] or ""))
            if not day_match:
                continue
            record_date = date(
                resolved_season, int(day_match.group(1)), int(day_match.group(2))
            ).isoformat()
            records.append(
                _daily_record(
                    columns,
                    values,
                    record_date=record_date,
                    player_id=resolved_player,
                    role=role_key,
                    month=month,
                    is_month_total=False,
                )
            )

        for row in table.select("tfoot tr"):
            values = _row_values(row, expand_colspan=True)
            # KBO total rows commonly use colspan=2; metrics align with the
            # columns after opponent, so normalize the leading cells.
            if len(values) == len(columns) - 1:
                values.insert(1, None)
            elif len(values) > len(columns):
                values = [values[0], *values[-(len(columns) - 1) :]]
            records.append(
                _daily_record(
                    columns,
                    values,
                    record_date=f"{resolved_season:04d}-{month:02d}",
                    player_id=resolved_player,
                    role=role_key,
                    month=month,
                    is_month_total=True,
                )
            )
    if not records:
        raise SchemaError("KBO daily page contains no supported daily tables")
    return records


def parse_roster(
    html: str,
    *,
    roster_date: date | str | None = None,
) -> list[dict[str, Any]]:
    """Parse registered players and same-day registration/removal tables."""

    soup = _html(html, "KBO roster")
    resolved_date = _roster_date(soup, roster_date)
    records: list[dict[str, Any]] = []
    for table in soup.select("table"):
        header_cells = table.select("thead th")
        if not header_cells:
            first_row = table.find("tr")
            header_cells = first_row.find_all("th", recursive=False) if first_row else []
        columns = [_column_name(cell.get_text(" ", strip=True)) for cell in header_cells]
        if len(columns) < 2:
            continue

        context = _table_context(table)
        team_name = _team_from_context(context)
        transaction_type = _transaction_from_context(context)
        for row in table.select("tbody tr"):
            if columns[0] == "구단":
                expanded = _all_team_roster_rows(
                    row, columns, roster_date=resolved_date
                )
                records.extend(expanded)
                continue
            values = _row_values(row)
            if len(values) < 2 or "없습니다" in " ".join(str(v or "") for v in values):
                continue
            cells = row.find_all(["td", "th"], recursive=False)
            player_id = _player_id_from_cells(cells)
            mapped = _zip_columns(columns, values)
            player_name = _first_present(
                mapped, "선수명", "선수", "player_name", "감독", "코치", "투수", "포수", "내야수", "외야수"
            )
            position = normalize_missing(mapped.get("포지션"))
            if position is None and len(columns) > 1 and columns[1] in {
                "감독",
                "코치",
                "투수",
                "포수",
                "내야수",
                "외야수",
            }:
                position = columns[1]
            records.append(
                {
                    "roster_date": resolved_date,
                    "team_name": team_name,
                    "external_player_id": player_id,
                    "player_name": normalize_missing(player_name),
                    "number": _first_present(mapped, "등번호", "번호"),
                    "position": position,
                    "bats_throws": _first_present(mapped, "투타유형", "투타"),
                    "birth_date": _first_present(mapped, "생년월일"),
                    "body": _first_present(mapped, "체격"),
                    "roster_status": "removed" if transaction_type == "말소" else "registered",
                    "transaction_type": transaction_type,
                    "values": values,
                }
            )
    if not records:
        raise SchemaError("KBO roster page contains no supported player rows")
    return records


def _all_team_roster_rows(
    row: Tag,
    columns: list[str],
    *,
    roster_date: str | None,
) -> list[dict[str, Any]]:
    """Expand RegisterAll.aspx cells, each of which contains many players."""

    cells = row.find_all(["td", "th"], recursive=False)
    if len(cells) < 2:
        return []
    team_name = normalize_missing(cells[0].get_text(" ", strip=True))
    result: list[dict[str, Any]] = []
    for index, cell in enumerate(cells[1:], start=1):
        if index >= len(columns):
            break
        position = re.sub(r"\s*\(\d+\)\s*$", "", columns[index]).strip()
        entries = cell.select("li") or cell.find_all("a", href=True)
        for entry in entries:
            text = str(normalize_missing(entry.get_text(" ", strip=True)) or "")
            match = re.match(r"(.+?)\s*\((\d+)\)\s*$", text)
            player_name = match.group(1).strip() if match else text
            number = match.group(2) if match else None
            link = entry if entry.name == "a" else entry.find("a", href=True)
            player_id = None
            if link:
                id_match = _PLAYER_ID_RE.search(link.get("href", ""))
                if id_match:
                    player_id = id_match.group(1)
            if player_name:
                result.append(
                    {
                        "roster_date": roster_date,
                        "team_name": team_name,
                        "external_player_id": player_id,
                        "player_name": player_name,
                        "number": number,
                        "position": position,
                        "bats_throws": None,
                        "birth_date": None,
                        "body": None,
                        "roster_status": "registered",
                        "transaction_type": None,
                        "values": [text],
                    }
                )
    return result


def _parse_box_groups(value: Any, *, category: str) -> list[dict[str, Any]]:
    groups = _json_value(value, f"arr{category.title()}")
    if groups in (None, []):
        return []
    if not isinstance(groups, list):
        raise SchemaError(f"KBO {category} groups must be a list")
    result: list[dict[str, Any]] = []
    for team_index, raw_group in enumerate(groups):
        group = _json_value(raw_group, f"{category} team {team_index}")
        if not isinstance(group, Mapping):
            raise SchemaError(f"KBO {category} team {team_index} must be an object")
        team_id = _first_present(group, "teamId", "team_id", "t_id")
        team_name = _first_present(group, "teamName", "team_name", "t_nm")
        table_items = [
            (name, raw_table)
            for name, raw_table in group.items()
            if str(name).lower().startswith("table")
        ]
        for table_name, raw_table in sorted(table_items, key=lambda item: str(item[0])):
            table = _json_value(raw_table, f"{category} {table_name}")
            if not isinstance(table, Mapping):
                raise SchemaError(f"KBO {category} {table_name} must be an object")
            columns = _api_columns(table)
            rows = _json_value(table.get("rows", []), f"{category} {table_name}.rows")
            if not isinstance(rows, list):
                raise SchemaError(f"KBO {category} {table_name}.rows must be a list")
            for row_index, raw_row in enumerate(rows):
                row = _json_value(raw_row, f"{category} {table_name} row")
                if not isinstance(row, Mapping):
                    raise SchemaError(f"KBO {category} row must be an object")
                raw_cells = _json_value(row.get("row", []), f"{category} row cells")
                if not isinstance(raw_cells, list):
                    raise SchemaError(f"KBO {category} row cells must be a list")
                cells = [_api_cell(cell) for cell in raw_cells]
                values = [normalize_missing(cell["text"]) for cell in cells]
                source_record = _zip_columns(columns, values)
                normalized = {
                    _box_column_name(key): value for key, value in source_record.items()
                }
                player_id = _api_player_id(cells)
                player_name = normalized.get("player_name")
                is_total = _is_total(values, row)
                result.append(
                    {
                        "category": category,
                        "team_side": "away" if team_index == 0 else "home",
                        "team_index": team_index,
                        "team_id": normalize_missing(team_id),
                        "team_name": normalize_missing(team_name),
                        "table_name": str(table_name),
                        "row_index": row_index,
                        "external_player_id": player_id,
                        "player_name": player_name,
                        "is_total": is_total,
                        "metrics": normalized,
                        "source_columns": columns,
                        "source_values": values,
                    }
                )
    return result


def _api_columns(table: Mapping[str, Any]) -> list[str]:
    for key in ("columns", "headers", "header", "cols"):
        raw = _json_value(table.get(key), f"table.{key}")
        if isinstance(raw, list):
            columns = []
            for value in raw:
                if isinstance(value, Mapping):
                    value = _first_present(value, "Text", "text", "Name", "name")
                columns.append(str(normalize_missing(value) or f"column_{len(columns) + 1}"))
            return _unique_columns(columns)
    return []


def _api_cell(value: Any) -> dict[str, Any]:
    value = _json_value(value, "boxscore cell")
    if isinstance(value, Mapping):
        text = _first_present(value, "Text", "text", "Value", "value")
        return {"text": text, "raw": dict(value)}
    return {"text": value, "raw": {}}


def _api_player_id(cells: Iterable[Mapping[str, Any]]) -> str | None:
    for cell in cells:
        raw = cell.get("raw")
        if not isinstance(raw, Mapping):
            continue
        direct = _first_present(raw, "PlayerId", "playerId", "p_id", "Id", "id")
        if direct is not None and str(direct).strip():
            return str(direct).strip()
        for value in raw.values():
            match = _PLAYER_ID_RE.search(str(value))
            if match:
                return match.group(1)
    return None


def _json_value(value: Any, context: str) -> Any:
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise SchemaError(f"{context} contains invalid nested JSON") from exc
    return value


def _daily_record(
    columns: list[str],
    values: list[Any],
    *,
    record_date: str,
    player_id: str | None,
    role: str,
    month: int,
    is_month_total: bool,
) -> dict[str, Any]:
    metrics = _zip_columns(columns, values)
    metrics.pop("date", None)
    return {
        "record_date": record_date,
        "external_player_id": player_id,
        "record_type": role,
        "month": month,
        "is_month_total": is_month_total,
        "metrics": metrics,
    }


def _html(html: str, context: str) -> BeautifulSoup:
    if not isinstance(html, str) or not html.strip():
        raise SchemaError(f"{context} HTML is empty")
    return BeautifulSoup(html, "html.parser")


def _row_values(row: Tag, *, expand_colspan: bool = False) -> list[Any]:
    values: list[Any] = []
    for cell in row.find_all(["td", "th"], recursive=False):
        value = normalize_missing(cell.get_text(" ", strip=True))
        values.append(value)
        if expand_colspan:
            try:
                span = int(cell.get("colspan", 1))
            except (TypeError, ValueError):
                span = 1
            values.extend([None] * (max(1, span) - 1))
    return values


def _zip_columns(columns: list[str], values: list[Any]) -> dict[str, Any]:
    if not columns:
        columns = [f"column_{index + 1}" for index in range(len(values))]
    result = {
        str(column): normalize_missing(values[index]) if index < len(values) else None
        for index, column in enumerate(columns)
    }
    if len(values) > len(columns):
        result["_extra"] = [normalize_missing(value) for value in values[len(columns) :]]
    return result


def _unique_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for raw in columns:
        name = str(normalize_missing(raw) or "column")
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result


def _column_name(value: str) -> str:
    value = str(normalize_missing(value) or "column")
    return _BOX_COLUMN_MAP.get(value.lower(), value)


def _box_column_name(value: str) -> str:
    return _BOX_COLUMN_MAP.get(str(value).strip().lower(), str(value).strip())


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and normalize_missing(mapping[key]) is not None:
            return normalize_missing(mapping[key])
    return None


def _is_total(values: list[Any], row: Mapping[str, Any]) -> bool:
    classes = str(_first_present(row, "Class", "class", "CssClass") or "").lower()
    return "total" in classes or any(
        str(value or "").strip() in {"합계", "계", "통산"} for value in values[:3]
    )


def _text(tag: Tag | None) -> str | None:
    return tag.get_text(" ", strip=True) if tag else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _date_from_compact(value: Any) -> str | None:
    text = str(value or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return normalize_missing(value)


def _doubleheader_number(item: Tag) -> int | None:
    text = _text(item.select_one(".dh")) or ""
    match = re.search(r"DH\s*(\d+)", text, re.I)
    if match:
        return int(match.group(1))
    game_id = str(item.get("g_id") or "")
    if game_id and game_id[-1:] in {"1", "2"}:
        return int(game_id[-1])
    return None


def _find_game_id(row: Tag) -> str | None:
    for key in ("g_id", "game_id", "data-game-id"):
        if row.get(key):
            return str(row.get(key))
    for link in row.find_all("a", href=True):
        match = _GAME_ID_RE.search(link["href"])
        if match:
            return match.group(1)
    return None


def _find_date(values: list[Any]) -> str | None:
    for value in values:
        match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", str(value or ""))
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return None


def _find_status(values: list[Any]) -> str | None:
    statuses = ("경기종료", "취소", "서스펜디드", "예정", "진행중")
    for value in values:
        for status in statuses:
            if status in str(value or ""):
                return status
    return None


def _selected_year(soup: BeautifulSoup) -> int | None:
    selected = soup.select_one("select[id*='ddlYear'] option[selected]")
    if selected and str(selected.get("value", "")).isdigit():
        return int(selected["value"])
    heading = soup.find(string=_YEAR_RE)
    if heading:
        match = _YEAR_RE.search(str(heading))
        if match:
            return int(match.group(1))
    return None


def _player_id_from_soup(soup: BeautifulSoup) -> str | None:
    for tag in soup.find_all(["form", "a"], href=True):
        match = _PLAYER_ID_RE.search(tag.get("href", ""))
        if match:
            return match.group(1)
    form = soup.find("form", action=True)
    if form:
        match = _PLAYER_ID_RE.search(form.get("action", ""))
        if match:
            return match.group(1)
    canonical = soup.select_one("link[rel='canonical']")
    if canonical:
        query = parse_qs(urlparse(canonical.get("href", "")).query)
        if query.get("playerId"):
            return query["playerId"][0]
    return None


def _table_context(table: Tag) -> list[str]:
    context: list[str] = []
    current: Tag | None = table
    for _ in range(5):
        if current is None:
            break
        heading = current.find_previous(["h3", "h4", "h5", "h6"])
        if heading is None:
            break
        text = heading.get_text(" ", strip=True)
        if text and text not in context:
            context.append(text)
        current = heading
    return context


def _team_from_context(context: list[str]) -> str | None:
    for value in context:
        if "선수등록" in value or "등/말소" in value:
            return normalize_missing(
                re.sub(r"(선수\s*등록\s*명단|선수등록명단|등/말소\s*현황).*$", "", value).strip()
            )
    return None


def _transaction_from_context(context: list[str]) -> str | None:
    for value in context:
        stripped = value.strip()
        if stripped == "말소" or stripped.startswith("말소 "):
            return "말소"
        if stripped == "등록" or stripped.startswith("등록 "):
            return "등록"
    return None


def _player_id_from_cells(cells: Iterable[Tag]) -> str | None:
    for cell in cells:
        link = cell.find("a", href=True)
        if link:
            match = _PLAYER_ID_RE.search(link["href"])
            if match:
                return match.group(1)
    return None


def _roster_date(soup: BeautifulSoup, supplied: date | str | None) -> str | None:
    if supplied is not None:
        return supplied.isoformat() if isinstance(supplied, date) else str(supplied)
    for item in soup.select("input[value]"):
        value = str(item.get("value", ""))
        match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", value)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    text = soup.get_text(" ", strip=True)
    match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return None


__all__ = [
    "normalize_missing",
    "parse_boxscore",
    "parse_player_daily",
    "parse_roster",
    "parse_schedule",
]
