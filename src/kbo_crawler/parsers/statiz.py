"""Validation-only parser for STATIZ player aggregate pages."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from bs4 import BeautifulSoup, Tag

from kbo_crawler.errors import SchemaError
from kbo_crawler.parsers.kbo import normalize_missing

ADVANCED_METRICS = frozenset(
    {
        "WAR",
        "WAR/144",
        "WAA",
        "RAR",
        "wRC+",
        "wOBA",
        "OPS",
        "ISO",
        "BABIP",
        "BB%",
        "K%",
        "FIP",
        "WHIP",
        "ERA+",
        "WPA",
    }
)
_PLAYER_NO_RE = re.compile(r"(?:p_no)=([A-Za-z0-9_-]+)", re.I)


def parse_statiz_metrics(
    html: str,
    *,
    player_no: str | int | None = None,
) -> dict[str, Any]:
    """Parse labeled STATIZ tables and percentile cards.

    The complete table row is retained for traceability while
    ``advanced_metrics`` offers the small validation surface used by this
    project.  No STATIZ value is treated as a primary-source fact.
    """

    if not isinstance(html, str) or not html.strip():
        raise SchemaError("STATIZ HTML is empty")
    soup = BeautifulSoup(html, "html.parser")
    resolved_player = str(player_no) if player_no is not None else _player_no(soup)
    tables: list[dict[str, Any]] = []

    for table_index, table in enumerate(soup.select("table")):
        columns = _headers(table)
        if not columns:
            continue
        group = _table_group(table) or f"table_{table_index + 1}"
        for row_index, row in enumerate(table.select("tbody tr")):
            values = [
                normalize_missing(cell.get_text(" ", strip=True))
                for cell in row.find_all(["td", "th"], recursive=False)
            ]
            if not values or "조회된 데이터가 없습니다" in str(values[0] or ""):
                continue
            metrics = _zip(columns, values)
            is_total = "total" in (row.get("class") or []) or any(
                str(value or "").strip() in {"합계", "통산", "계"} for value in values[:2]
            )
            tables.append(
                {
                    "external_player_id": resolved_player,
                    "metric_group": group,
                    "row_index": row_index,
                    "is_total": is_total,
                    "metrics": metrics,
                    "advanced_metrics": {
                        key: value
                        for key, value in metrics.items()
                        if _metric_key(key) in ADVANCED_METRICS
                    },
                }
            )

    percentiles = _percentiles(soup)
    if not tables and not percentiles:
        raise SchemaError("STATIZ page contains no supported metrics")
    return {
        "external_player_id": resolved_player,
        "tables": tables,
        "percentiles": percentiles,
    }


def parse_advanced_metrics(
    html: str,
    *,
    player_no: str | int | None = None,
) -> list[dict[str, Any]]:
    """Return only rows/cards containing an advanced validation metric."""

    parsed = parse_statiz_metrics(html, player_no=player_no)
    result = [
        {
            "external_player_id": row["external_player_id"],
            "metric_group": row["metric_group"],
            "is_total": row["is_total"],
            "metrics": row["advanced_metrics"],
        }
        for row in parsed["tables"]
        if row["advanced_metrics"]
    ]
    if parsed["percentiles"]:
        result.append(
            {
                "external_player_id": parsed["external_player_id"],
                "metric_group": "percentiles",
                "is_total": False,
                "metrics": parsed["percentiles"],
            }
        )
    return result


def _headers(table: Tag) -> list[str]:
    header_rows = table.select("thead tr")
    if not header_rows:
        return []
    # The final/only header row with cells is sufficient for current STATIZ
    # pages; when the second rowspan row is empty use the first one.
    candidate: list[Tag] = []
    for row in header_rows:
        cells = row.find_all("th", recursive=False)
        if len(cells) > len(candidate):
            candidate = cells
    return _unique([cell.get_text(" ", strip=True) or "column" for cell in candidate])


def _table_group(table: Tag) -> str | None:
    box = table.find_parent(class_="sh_box")
    if box:
        heading = box.select_one(".box_head")
        if heading:
            return str(normalize_missing(heading.get_text(" ", strip=True)))
    heading = table.find_previous(["h2", "h3", "h4", "h5", "h6"])
    return str(normalize_missing(heading.get_text(" ", strip=True))) if heading else None


def _zip(columns: list[str], values: list[Any]) -> dict[str, Any]:
    result = {
        column: normalize_missing(values[index]) if index < len(values) else None
        for index, column in enumerate(columns)
    }
    if len(values) > len(columns):
        result["_extra"] = [normalize_missing(value) for value in values[len(columns) :]]
    return result


def _unique(values: Iterable[str]) -> list[str]:
    counts: dict[str, int] = {}
    result: list[str] = []
    for raw in values:
        value = str(normalize_missing(raw) or "column")
        counts[value] = counts.get(value, 0) + 1
        result.append(value if counts[value] == 1 else f"{value}_{counts[value]}")
    return result


def _metric_key(value: str) -> str:
    return value.strip().replace("％", "%")


def _percentiles(soup: BeautifulSoup) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in soup.select(".rang_info"):
        parent = item.parent
        if not isinstance(parent, Tag):
            continue
        label = parent.find("span", recursive=False)
        rank = item.find("span")
        if label is None or rank is None:
            continue
        metric = str(normalize_missing(label.get_text(" ", strip=True)) or "").rstrip("%")
        tooltip = str(rank.get("tooltip", ""))
        match = re.search(r"([^:]+):\s*([-+]?\d+(?:\.\d+)?)", tooltip)
        result[metric] = {
            "percentile": normalize_missing(rank.get_text(" ", strip=True)),
            "rank": normalize_missing(match.group(1)) if match else None,
            "value": normalize_missing(match.group(2)) if match else None,
        }
    return result


def _player_no(soup: BeautifulSoup) -> str | None:
    canonical = soup.select_one("link[rel='canonical']")
    if canonical:
        match = _PLAYER_NO_RE.search(canonical.get("href", ""))
        if match:
            return match.group(1)
    for link in soup.find_all("a", href=True):
        match = _PLAYER_NO_RE.search(link["href"])
        if match:
            return match.group(1)
    return None


__all__ = [
    "ADVANCED_METRICS",
    "parse_advanced_metrics",
    "parse_statiz_metrics",
]
