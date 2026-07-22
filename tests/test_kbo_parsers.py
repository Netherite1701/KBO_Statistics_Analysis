from __future__ import annotations

import json
import unittest

from kbo_crawler.parsers.kbo import (
    normalize_missing,
    parse_boxscore,
    parse_player_daily,
    parse_roster,
    parse_schedule,
)


class KBOParserTests(unittest.TestCase):
    def test_missing_dash_is_none(self) -> None:
        self.assertIsNone(normalize_missing("-"))
        self.assertIsNone(normalize_missing(" — "))
        self.assertEqual("0", normalize_missing("0"))

    def test_boxscore_parses_nested_json_and_total_rows(self) -> None:
        table = {
            "headers": [{"Text": "선수명"}, {"Text": "AB"}, {"Text": "H"}],
            "rows": [
                {
                    "row": [
                        {
                            "Text": "홍길동",
                            "Href": "/Player/Detail?playerId=12345",
                        },
                        {"Text": "4"},
                        {"Text": "-"},
                    ]
                },
                {
                    "Class": "total",
                    "row": [{"Text": "합계"}, {"Text": "4"}, {"Text": "1"}],
                },
            ],
        }
        payload = {
            "code": "100",
            "arrHitter": [
                json.dumps({"teamId": "HT", "teamName": "KIA", "table1": json.dumps(table)})
            ],
            "arrPitcher": [],
        }

        result = parse_boxscore(payload)

        self.assertEqual(2, len(result["batting"]))
        first = result["batting"][0]
        self.assertEqual("away", first["team_side"])
        self.assertEqual("12345", first["external_player_id"])
        self.assertEqual("4", first["metrics"]["at_bats"])
        self.assertIsNone(first["metrics"]["hits"])
        self.assertTrue(result["batting"][1]["is_total"])

    def test_cancelled_game_may_have_empty_boxscore_arrays(self) -> None:
        self.assertEqual(
            {"batting": [], "pitching": []},
            parse_boxscore({"code": "100", "arrHitter": [], "arrPitcher": []}),
        )

    def test_schedule_keeps_official_game_id_and_doubleheader(self) -> None:
        html = """
        <ul><li class="game-cont end" g_id="20240421WOOB2"
          g_dt="20240421" season="2024" sr_id="0" le_id="1"
          away_id="WO" home_id="OB" away_nm="키움" home_nm="두산"
          s_nm="잠실"><p class="staus">경기종료</p><p class="dh">(DH2)</p></li></ul>
        """

        games = parse_schedule(html)

        self.assertEqual("20240421WOOB2", games[0]["external_game_id"])
        self.assertEqual("2024-04-21", games[0]["game_date"])
        self.assertEqual(2, games[0]["doubleheader_game"])

    def test_daily_rows_and_month_total_are_distinct(self) -> None:
        html = """
        <html><body>
          <select id="x_ddlYear"><option selected value="2025">2025</option></select>
          <table class="tbl">
            <thead><tr><th>3월</th><th>상대</th><th>AB</th><th>H</th></tr></thead>
            <tfoot><tr><th colspan="2">합계</th><th>4</th><th>-</th></tr></tfoot>
            <tbody><tr><td>03.22</td><td>두산</td><td>4</td><td>1</td></tr></tbody>
          </table>
        </body></html>
        """

        records = parse_player_daily(html, player_id="67893")

        self.assertEqual("2025-03-22", records[0]["record_date"])
        self.assertFalse(records[0]["is_month_total"])
        self.assertEqual("2025-03", records[1]["record_date"])
        self.assertTrue(records[1]["is_month_total"])
        self.assertIsNone(records[1]["metrics"]["hits"])

    def test_roster_distinguishes_registered_and_removed(self) -> None:
        html = """
        <html><body>
          <input value="2026.07.19(일)">
          <h4>KIA 타이거즈 선수등록명단</h4>
          <table><thead><tr><th>등번호</th><th>투수</th><th>투타유형</th></tr></thead>
            <tbody><tr><td>54</td><td><a href="/Player/Detail?playerId=54321">김투수</a></td><td>우투우타</td></tr></tbody>
          </table>
          <h4>KIA 타이거즈 등/말소 현황</h4><h5>말소</h5>
          <table><thead><tr><th>등번호</th><th>선수명</th><th>포지션</th></tr></thead>
            <tbody><tr><td>7</td><td><a href="/Player/Detail?playerId=77777">이타자</a></td><td>내야수</td></tr></tbody>
          </table>
        </body></html>
        """

        records = parse_roster(html)

        self.assertEqual("2026-07-19", records[0]["roster_date"])
        self.assertEqual("54321", records[0]["external_player_id"])
        self.assertEqual("투수", records[0]["position"])
        self.assertEqual("removed", records[1]["roster_status"])
        self.assertEqual("말소", records[1]["transaction_type"])

    def test_all_team_roster_expands_players_inside_position_cells(self) -> None:
        html = """
        <html><body><table><thead><tr>
          <th>구단</th><th>감독(1)</th><th>투수(2)</th>
        </tr></thead><tbody><tr><td>삼성</td>
          <td><ul><li><a href="/Player/Detail?playerId=100">박감독(70)</a></li></ul></td>
          <td><ul>
            <li><a href="/Player/Detail?playerId=101">원투수(18)</a></li>
            <li><a href="/Player/Detail?playerId=102">이투수(57)</a></li>
          </ul></td>
        </tr></tbody></table></body></html>
        """

        records = parse_roster(html, roster_date="2026-07-19")

        self.assertEqual(3, len(records))
        self.assertEqual("삼성", records[2]["team_name"])
        self.assertEqual("투수", records[2]["position"])
        self.assertEqual("57", records[2]["number"])
        self.assertEqual("102", records[2]["external_player_id"])


if __name__ == "__main__":
    unittest.main()
