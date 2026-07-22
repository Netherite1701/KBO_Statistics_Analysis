from __future__ import annotations

import json
import unittest
from typing import Any

from kbo_crawler.errors import SchemaError, SourceError
from kbo_crawler.sources.kbo import (
    BOXSCORE_URL,
    KBOBusinessError,
    KBOContentTypeError,
    KBOHTMLResponseError,
    KBOSource,
)
from kbo_crawler.sources.statiz import StatizDisabledError, StatizSource


class FakeResponse:
    def __init__(
        self,
        value: Any,
        *,
        content_type: str = "application/json; charset=utf-8",
        text: str | None = None,
    ) -> None:
        self.value = value
        self.headers = {"Content-Type": content_type}
        self.text = json.dumps(value) if text is None else text

    def json(self) -> Any:
        return self.value


class FakeHttp:
    def __init__(
        self,
        responses: list[FakeResponse] | None = None,
        *,
        text: str = "<html>ok</html>",
    ) -> None:
        self.responses = list(responses or [])
        self.text = text
        self.requests: list[dict[str, Any]] = []
        self.text_requests: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)

    def get_text(self, url: str, **kwargs: Any) -> str:
        self.text_requests.append({"url": url, **kwargs})
        return self.text


class KBOSourceTests(unittest.TestCase):
    def test_bootstraps_then_fetches_boxscore_with_derived_season(self) -> None:
        http = FakeHttp(
            [
                FakeResponse({}, content_type="text/html", text="<html>game center</html>"),
                FakeResponse({"code": "100", "arrHitter": []}),
            ]
        )
        source = KBOSource(http=http)  # type: ignore[arg-type]

        result = source.fetch_boxscore("20260506HHHT02026")

        self.assertEqual("100", result["code"])
        self.assertEqual("GET", http.requests[0]["method"])
        self.assertEqual("POST", http.requests[1]["method"])
        self.assertEqual(BOXSCORE_URL, http.requests[1]["url"])
        self.assertEqual("2026", http.requests[1]["data"]["seasonId"])
        self.assertIn("Referer", http.requests[1]["headers"])

    def test_asmx_html_has_explicit_error_without_fallback(self) -> None:
        http = FakeHttp(
            [
                FakeResponse({}, content_type="text/html", text="<html>game center</html>"),
                FakeResponse({}, content_type="text/html", text="<!DOCTYPE html><h1>Error</h1>"),
            ]
        )
        source = KBOSource(http=http)  # type: ignore[arg-type]

        with self.assertRaises(KBOHTMLResponseError):
            source.fetch_boxscore("20260506HHHT02026")

    def test_html_uses_injected_fallback_without_selenium_import(self) -> None:
        http = FakeHttp(
            [
                FakeResponse({}, content_type="text/html", text="<html>game center</html>"),
                FakeResponse({}, content_type="text/html", text="<html>blocked</html>"),
            ]
        )
        calls: list[tuple[str, str]] = []

        def fallback(url: str, *, method: str, data: Any = None) -> dict[str, Any]:
            calls.append((url, method))
            return {"code": "100", "arrHitter": []}

        result = KBOSource(
            http=http, browser_fallback=fallback  # type: ignore[arg-type]
        ).fetch_boxscore("20260506HHHT02026")

        self.assertEqual("100", result["code"])
        self.assertEqual([(BOXSCORE_URL, "POST")], calls)

    def test_rejects_non_json_content_type(self) -> None:
        http = FakeHttp(
            [
                FakeResponse({}, content_type="text/html", text="<html>game center</html>"),
                FakeResponse({"code": "100"}, content_type="application/octet-stream"),
            ]
        )
        with self.assertRaises(KBOContentTypeError):
            KBOSource(http=http).fetch_boxscore("20260506HHHT02026")  # type: ignore[arg-type]

    def test_rejects_kbo_business_error(self) -> None:
        http = FakeHttp(
            [
                FakeResponse({}, content_type="text/html", text="<html>game center</html>"),
                FakeResponse({"code": "500", "message": "bad game"}),
            ]
        )
        with self.assertRaises(KBOBusinessError):
            KBOSource(http=http).fetch_boxscore("20260506HHHT02026")  # type: ignore[arg-type]

    def test_rejects_json_object_without_kbo_response_code(self) -> None:
        http = FakeHttp(
            [
                FakeResponse({}, content_type="text/html", text="<html>game center</html>"),
                FakeResponse({"arrHitter": []}),
            ]
        )
        with self.assertRaisesRegex(SchemaError, "response code"):
            KBOSource(http=http).fetch_boxscore("20260506HHHT02026")  # type: ignore[arg-type]

    def test_statiz_is_opt_in(self) -> None:
        with self.assertRaises(StatizDisabledError):
            StatizSource(http=FakeHttp()).fetch_player("16261")  # type: ignore[arg-type]

    def test_statiz_enabled_supports_validation_views(self) -> None:
        http = FakeHttp()
        source = StatizSource(enabled=True, http=http)  # type: ignore[arg-type]

        source.fetch_playlog("16261")

        self.assertEqual("playlog", http.text_requests[0]["params"]["m"])
        self.assertEqual("16261", http.text_requests[0]["params"]["p_no"])

    def test_player_daily_never_silently_accepts_wrong_season(self) -> None:
        html = '<select><option selected="selected" value="2026">2026</option></select>'
        source = KBOSource(http=FakeHttp(text=html))  # type: ignore[arg-type]

        with self.assertRaisesRegex(SourceError, "ignored the requested season"):
            source.fetch_player_daily("67893", season_id=2025)

    def test_player_daily_can_delegate_aspnet_selection_to_browser(self) -> None:
        initial = '<select><option selected="selected" value="2026">2026</option></select>'

        def fallback(url: str, *, method: str, data: Any = None) -> str:
            return '<select><option selected="selected" value="2025">2025</option></select>'

        source = KBOSource(
            http=FakeHttp(text=initial),  # type: ignore[arg-type]
            browser_fallback=fallback,
        )

        html = source.fetch_player_daily("67893", season_id=2025)

        self.assertIn('value="2025"', html)


if __name__ == "__main__":
    unittest.main()
