from __future__ import annotations

import unittest

from kbo_crawler.parsers.statiz import parse_advanced_metrics, parse_statiz_metrics


class StatizParserTests(unittest.TestCase):
    HTML = """
    <html><head><link rel="canonical"
      href="https://www.statiz.co.kr/player/?m=playerinfo&amp;p_no=16261"></head>
    <body>
      <div class="item"><span>WAR%</span><div class="rang_info">
        <span tooltip="3위: 1.79">99</span></div></div>
      <div class="sh_box"><div class="box_head">주요기록</div>
        <table><thead><tr><th>Year</th><th>WAR</th><th>FIP</th><th>BABIP</th></tr></thead>
        <tbody>
          <tr><td>2026</td><td>1.79</td><td>3.43</td><td>-</td></tr>
          <tr class="total"><th>통산</th><th>5.39</th><th>3.04</th><th>0.252</th></tr>
        </tbody></table>
      </div>
    </body></html>
    """

    def test_parses_labeled_tables_and_percentiles(self) -> None:
        parsed = parse_statiz_metrics(self.HTML)

        self.assertEqual("16261", parsed["external_player_id"])
        self.assertEqual("주요기록", parsed["tables"][0]["metric_group"])
        self.assertIsNone(parsed["tables"][0]["metrics"]["BABIP"])
        self.assertTrue(parsed["tables"][1]["is_total"])
        self.assertEqual("1.79", parsed["percentiles"]["WAR"]["value"])

    def test_advanced_view_excludes_identity_columns(self) -> None:
        rows = parse_advanced_metrics(self.HTML)

        self.assertEqual(
            {"WAR": "1.79", "FIP": "3.43", "BABIP": None},
            rows[0]["metrics"],
        )
        self.assertNotIn("Year", rows[0]["metrics"])


if __name__ == "__main__":
    unittest.main()
