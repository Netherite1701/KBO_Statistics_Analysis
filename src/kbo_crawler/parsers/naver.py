"""Lossless typed parsing for Naver KBO schedule and relay responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ..errors import SchemaError

JsonObject = dict[str, Any]
Number = int | float
Scalar = str | Number | bool

# Both codes are observed for a completed batting result.  In particular,
# hits/home runs can be type 23 and must not be filtered out by a type-13-only
# crawler.
PLATE_APPEARANCE_RESULT_TYPES = frozenset({13, 23})


@dataclass(frozen=True, slots=True)
class NaverGame:
    game_id: str
    category_id: str | None
    game_date: str | None
    game_date_time: str | None
    home_team_code: str | None
    home_team_name: str | None
    home_team_score: Number | None
    away_team_code: str | None
    away_team_name: str | None
    away_team_score: Number | None
    winner: str | None
    status_code: str | None
    status_info: str | None
    cancelled: bool
    suspended: bool
    reversed_home_away: bool | None
    raw: JsonObject


@dataclass(frozen=True, slots=True)
class NaverSchedule:
    games: tuple[NaverGame, ...]
    game_total_count: int
    raw_result: JsonObject


@dataclass(frozen=True, slots=True)
class NaverSeason:
    season_year: int | None
    season: str | None
    season_id: str | None
    category_id: str | None
    start_date: str | None
    end_date: str | None
    recent_schedule_date: str | None
    recent_tournament_phase: str | None
    months: tuple[JsonObject, ...]
    post_seasons: tuple[JsonObject, ...]
    raw_result: JsonObject


@dataclass(frozen=True, slots=True)
class NaverEvent:
    game_id: str
    relay_no: int | None
    inning: int | None
    home_or_away: str | None
    seqno: int | None
    event_type: int | None
    text: str | None
    pitch_id: str | None
    pitch_num: int | None
    pitch_result: str | None
    stuff: str | None
    speed: Scalar | None
    batter_code: str | None
    pitcher_code: str | None
    current_game_state: JsonObject
    is_plate_appearance_result: bool
    raw: JsonObject


@dataclass(frozen=True, slots=True)
class NaverPitch:
    game_id: str
    relay_no: int | None
    inning: int | None
    home_or_away: str | None
    seqno: int | None
    pitch_id: str | None
    pitch_num: int | None
    pitch_result: str | None
    text: str | None
    stuff: str | None
    speed: Scalar | None
    batter_code: str | None
    pitcher_code: str | None
    current_game_state: JsonObject
    ballcount: int | None
    cross_plate_x: Number | None
    cross_plate_y: Number | None
    top_sz: Number | None
    bottom_sz: Number | None
    stance: str | None
    x0: Number | None
    y0: Number | None
    z0: Number | None
    vx0: Number | None
    vy0: Number | None
    vz0: Number | None
    ax: Number | None
    ay: Number | None
    az: Number | None
    has_tracking: bool
    raw_text_option: JsonObject | None
    raw_pts_option: JsonObject | None


@dataclass(frozen=True, slots=True)
class NaverRelay:
    game_id: str
    relay_no: int | None
    inning: int | None
    home_or_away: str | None
    title: str | None
    status_code: Scalar | None
    events: tuple[NaverEvent, ...]
    pitches: tuple[NaverPitch, ...]
    result_events: tuple[NaverEvent, ...]
    metric_option: JsonObject
    raw: JsonObject


@dataclass(frozen=True, slots=True)
class NaverRelayResult:
    game_id: str
    requested_inning: int | None
    relays: tuple[NaverRelay, ...]
    pitches: tuple[NaverPitch, ...]
    events: tuple[NaverEvent, ...]
    result_events: tuple[NaverEvent, ...]
    current_game_state: JsonObject
    raw_text_relay_data: JsonObject
    raw_result: JsonObject


def parse_schedule_games(payload: Mapping[str, Any]) -> NaverSchedule:
    """Parse a ``/schedule/games`` response without deriving game IDs."""

    result = _result(payload, "schedule/games")
    raw_games = _object_list(result.get("games", []), "result.games")
    games: list[NaverGame] = []
    for index, raw_game in enumerate(raw_games):
        game_id = _required_text(raw_game.get("gameId"), f"result.games[{index}].gameId")
        games.append(
            NaverGame(
                game_id=game_id,
                category_id=_text(raw_game.get("categoryId")),
                game_date=_text(raw_game.get("gameDate")),
                game_date_time=_text(raw_game.get("gameDateTime")),
                home_team_code=_text(raw_game.get("homeTeamCode")),
                home_team_name=_text(raw_game.get("homeTeamName")),
                home_team_score=_number(raw_game.get("homeTeamScore")),
                away_team_code=_text(raw_game.get("awayTeamCode")),
                away_team_name=_text(raw_game.get("awayTeamName")),
                away_team_score=_number(raw_game.get("awayTeamScore")),
                winner=_text(raw_game.get("winner")),
                status_code=_text(raw_game.get("statusCode")),
                status_info=_text(raw_game.get("statusInfo")),
                cancelled=bool(raw_game.get("cancel", False)),
                suspended=bool(raw_game.get("suspended", False)),
                reversed_home_away=_optional_bool(raw_game.get("reversedHomeAway")),
                raw=deepcopy(raw_game),
            )
        )
    total = _integer(result.get("gameTotalCount"))
    return NaverSchedule(
        games=tuple(games),
        game_total_count=len(games) if total is None else total,
        raw_result=deepcopy(result),
    )


def parse_season(payload: Mapping[str, Any]) -> NaverSeason:
    """Parse a ``/schedule/season`` response."""

    result = _result(payload, "schedule/season")
    months = _object_list(result.get("months", []), "result.months")
    post_seasons = _object_list(result.get("postSeasons", []), "result.postSeasons")
    return NaverSeason(
        season_year=_integer(result.get("seasonYear")),
        season=_text(result.get("season")),
        season_id=_text(result.get("seasonId")),
        category_id=_text(result.get("categoryId")),
        start_date=_text(result.get("startDate")),
        end_date=_text(result.get("endDate")),
        recent_schedule_date=_text(result.get("recentScheduleDate")),
        recent_tournament_phase=_text(result.get("recentTournamentPhase")),
        months=tuple(deepcopy(months)),
        post_seasons=tuple(deepcopy(post_seasons)),
        raw_result=deepcopy(result),
    )


def parse_seasons(payload: Mapping[str, Any]) -> NaverSeason:
    """Compatibility alias for :func:`parse_season`."""

    return parse_season(payload)


def parse_relay(
    payload: Mapping[str, Any],
    *,
    game_id: str | None = None,
    requested_inning: int | None = None,
) -> NaverRelayResult:
    """Parse one relay response and outer-join pitch text with PTS tracking.

    A record is emitted for a text pitch even when tracking is absent.  An
    unmatched PTS object is emitted as well, ensuring the parser never changes
    the observed pitch count merely because one half of the response is absent.
    """

    result = _result(payload, "games/{gameId}/relay")
    relay_data_value = result.get("textRelayData")
    if not isinstance(relay_data_value, Mapping):
        raise SchemaError("Naver relay result.textRelayData must be an object")
    relay_data = dict(relay_data_value)
    source_game_id = _text(relay_data.get("gameId"))
    resolved_game_id = str(game_id or source_game_id or "").strip()
    if not resolved_game_id:
        raise SchemaError("Naver relay is missing gameId")
    if game_id and source_game_id and game_id != source_game_id:
        raise SchemaError(
            f"Naver relay gameId mismatch: requested {game_id}, received {source_game_id}"
        )

    raw_relays = _object_list(relay_data.get("textRelays", []), "textRelayData.textRelays")
    relays = [_parse_single_relay(resolved_game_id, relay) for relay in raw_relays]
    # The endpoint commonly returns newest plate appearances first.  relay.no
    # is the source chronology key; never reconstruct order from pitchNum.
    relays.sort(key=lambda relay: _optional_int_sort_key(relay.relay_no))

    events = tuple(event for relay in relays for event in relay.events)
    pitches = tuple(pitch for relay in relays for pitch in relay.pitches)
    result_events = tuple(event for relay in relays for event in relay.result_events)
    current_state = _json_object(relay_data.get("currentGameState"))
    inferred_inning = _integer(relay_data.get("inn"))
    return NaverRelayResult(
        game_id=resolved_game_id,
        requested_inning=requested_inning if requested_inning is not None else inferred_inning,
        relays=tuple(relays),
        pitches=pitches,
        events=events,
        result_events=result_events,
        current_game_state=current_state,
        raw_text_relay_data=deepcopy(relay_data),
        raw_result=deepcopy(result),
    )


def _parse_single_relay(game_id: str, raw_relay: JsonObject) -> NaverRelay:
    relay_no = _integer(raw_relay.get("no"))
    inning = _integer(raw_relay.get("inn"))
    home_or_away = _text(raw_relay.get("homeOrAway"))
    raw_options = _object_list(raw_relay.get("textOptions", []), "relay.textOptions")
    raw_pts_options = _object_list(raw_relay.get("ptsOptions", []), "relay.ptsOptions")

    events = tuple(
        _parse_event(game_id, relay_no, inning, home_or_away, option)
        for option in raw_options
    )
    result_events = tuple(event for event in events if event.is_plate_appearance_result)
    pitches = _join_pitches(
        game_id,
        relay_no,
        inning,
        home_or_away,
        raw_options,
        raw_pts_options,
    )
    return NaverRelay(
        game_id=game_id,
        relay_no=relay_no,
        inning=inning,
        home_or_away=home_or_away,
        title=_text(raw_relay.get("title")),
        status_code=_scalar(raw_relay.get("statusCode")),
        events=events,
        pitches=pitches,
        result_events=result_events,
        metric_option=_json_object(raw_relay.get("metricOption")),
        raw=deepcopy(raw_relay),
    )


def _parse_event(
    game_id: str,
    relay_no: int | None,
    inning: int | None,
    home_or_away: str | None,
    option: JsonObject,
) -> NaverEvent:
    state = _json_object(option.get("currentGameState"))
    event_type = _integer(option.get("type"))
    return NaverEvent(
        game_id=game_id,
        relay_no=relay_no,
        inning=inning,
        home_or_away=home_or_away,
        seqno=_integer(option.get("seqno")),
        event_type=event_type,
        text=_text(option.get("text")),
        pitch_id=_pitch_id(option.get("ptsPitchId")),
        pitch_num=_integer(option.get("pitchNum")),
        pitch_result=_text(option.get("pitchResult")),
        stuff=_text(option.get("stuff")),
        speed=_scalar(option.get("speed")),
        batter_code=_player_code(state.get("batter")),
        pitcher_code=_player_code(state.get("pitcher")),
        current_game_state=state,
        is_plate_appearance_result=event_type in PLATE_APPEARANCE_RESULT_TYPES,
        raw=deepcopy(option),
    )


def _join_pitches(
    game_id: str,
    relay_no: int | None,
    inning: int | None,
    home_or_away: str | None,
    options: list[JsonObject],
    pts_options: list[JsonObject],
) -> tuple[NaverPitch, ...]:
    pts_by_id: dict[str, list[JsonObject]] = {}
    for pts in pts_options:
        pitch_id = _pitch_id(pts.get("pitchId"))
        if pitch_id:
            pts_by_id.setdefault(pitch_id, []).append(pts)

    joined: list[NaverPitch] = []
    used_pts_ids: set[int] = set()
    for option in options:
        if not _is_pitch_option(option):
            continue
        pitch_id = _pitch_id(option.get("ptsPitchId"))
        pts: JsonObject | None = None
        if pitch_id:
            matches = pts_by_id.get(pitch_id, [])
            pts = next((candidate for candidate in matches if id(candidate) not in used_pts_ids), None)
        if pts is not None:
            used_pts_ids.add(id(pts))
        joined.append(
            _make_pitch(
                game_id,
                relay_no,
                inning,
                home_or_away,
                option=option,
                pts=pts,
            )
        )

    for pts in pts_options:
        if id(pts) in used_pts_ids:
            continue
        joined.append(
            _make_pitch(
                game_id,
                relay_no,
                inning,
                home_or_away,
                option=None,
                pts=pts,
            )
        )

    joined.sort(key=_pitch_sort_key)
    return tuple(joined)


def _make_pitch(
    game_id: str,
    relay_no: int | None,
    inning: int | None,
    home_or_away: str | None,
    *,
    option: JsonObject | None,
    pts: JsonObject | None,
) -> NaverPitch:
    option = option or {}
    pts = pts or {}
    state = _json_object(option.get("currentGameState"))
    return NaverPitch(
        game_id=game_id,
        relay_no=relay_no,
        inning=inning if inning is not None else _integer(pts.get("inn")),
        home_or_away=home_or_away,
        seqno=_integer(option.get("seqno")),
        pitch_id=_pitch_id(option.get("ptsPitchId")) or _pitch_id(pts.get("pitchId")),
        pitch_num=_integer(option.get("pitchNum")),
        pitch_result=_text(option.get("pitchResult")),
        text=_text(option.get("text")),
        stuff=_text(option.get("stuff")),
        speed=_scalar(option.get("speed")),
        batter_code=_player_code(state.get("batter")),
        pitcher_code=_player_code(state.get("pitcher")),
        current_game_state=state,
        ballcount=_integer(pts.get("ballcount")),
        cross_plate_x=_number(pts.get("crossPlateX")),
        cross_plate_y=_number(pts.get("crossPlateY")),
        top_sz=_number(pts.get("topSz")),
        bottom_sz=_number(pts.get("bottomSz")),
        stance=_text(pts.get("stance")),
        x0=_number(pts.get("x0")),
        y0=_number(pts.get("y0")),
        z0=_number(pts.get("z0")),
        vx0=_number(pts.get("vx0")),
        vy0=_number(pts.get("vy0")),
        vz0=_number(pts.get("vz0")),
        ax=_number(pts.get("ax")),
        ay=_number(pts.get("ay")),
        az=_number(pts.get("az")),
        has_tracking=bool(pts),
        raw_text_option=deepcopy(option) if option else None,
        raw_pts_option=deepcopy(pts) if pts else None,
    )


def _is_pitch_option(option: Mapping[str, Any]) -> bool:
    return any(
        option.get(field) is not None
        for field in ("pitchNum", "ptsPitchId", "pitchResult")
    )


def _pitch_sort_key(pitch: NaverPitch) -> tuple[int, int, int]:
    # seqno is the authoritative event stream order.  ballcount is a useful
    # fallback for PTS-only rows, and pitchNum is retained rather than rebuilt.
    if pitch.seqno is not None:
        return (0, pitch.seqno, 0)
    if pitch.ballcount is not None:
        return (1, pitch.ballcount, 0)
    return (2, pitch.pitch_num or 0, 0)


def _result(payload: Mapping[str, Any], endpoint: str) -> JsonObject:
    if not isinstance(payload, Mapping):
        raise SchemaError(f"Naver {endpoint} payload must be an object")
    if payload.get("success") is False:
        message = payload.get("message") or payload.get("code") or "unknown error"
        raise SchemaError(f"Naver {endpoint} reported failure: {message}")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise SchemaError(f"Naver {endpoint} result must be an object")
    return dict(result)


def _object_list(value: Any, field: str) -> list[JsonObject]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise SchemaError(f"Naver {field} must be a list")
    result: list[JsonObject] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise SchemaError(f"Naver {field}[{index}] must be an object")
        result.append(dict(item))
    return result


def _json_object(value: Any) -> JsonObject:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _required_text(value: Any, field: str) -> str:
    normalized = _text(value)
    if not normalized:
        raise SchemaError(f"Naver {field} must be a non-empty string")
    return normalized


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _player_code(value: Any) -> str | None:
    if value in (None, "", "0", 0):
        return None
    return str(value)


def _pitch_id(value: Any) -> str | None:
    """Normalize Naver's non-ID sentinels while retaining them in raw JSON."""

    normalized = _text(value)
    if normalized is None or normalized.strip() in {"", "-1", "0"}:
        return None
    return normalized


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> Number | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _scalar(value: Any) -> Scalar | None:
    return value if isinstance(value, (str, int, float, bool)) else None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_int_sort_key(value: int | None) -> tuple[int, int]:
    return (1, 0) if value is None else (0, value)
