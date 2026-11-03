#!/usr/bin/env python3
"""単体テスト: 松山市ごみカレンダー生成コード (scripts/pipeline.py, scripts/bundle.py)

対象はPDF解析を除く純粋ロジック:
  decode_day / cats / nth_of / is_last_wd / infer / build_ics / verify /
  detect_headers / marker_key / build_bundle_ics
加えて、保存済みグリッド (grids/*.json) と公開ICSの照合 (ローカルに
grids/ がある場合のみ実行し、無ければスキップする)。

実行: python3 -m unittest discover -s tests -v   (標準ライブラリのみで動く)
"""
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pipeline as P
import bundle as B

FY = P.FY_DAYS  # 2026-04-01 .. 2027-03-31 (365日)


def days_where(pred):
    return {d for d in FY if pred(d)}


class TestDecodeDay(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(P.decode_day("7"), 7)
        self.assertEqual(P.decode_day("15"), 15)
        self.assertEqual(P.decode_day("31"), 31)

    def test_doubled_glyphs(self):
        # PDFで二重描画された数字は1文字に解釈する (現行仕様の明示)
        self.assertEqual(P.decode_day("11"), 1)
        self.assertEqual(P.decode_day("33"), 3)
        self.assertEqual(P.decode_day("1100"), 10)
        self.assertEqual(P.decode_day("1122"), 12)


class TestCats(unittest.TestCase):
    def test_each_keyword(self):
        self.assertEqual(P.cats("可燃ごみ"), {"可燃ごみ"})
        self.assertEqual(P.cats("プラ"), {"プラスチック製容器包装"})
        self.assertEqual(P.cats("ペットボトル"), {"ペットボトル"})
        self.assertEqual(P.cats("紙類"), {"紙類"})
        self.assertEqual(P.cats("金物"), {"金物・ガラス類"})
        self.assertEqual(P.cats("埋立"), {"埋立ごみ"})
        self.assertEqual(P.cats("水銀"), {"水銀ごみ"})

    def test_partial_keywords_do_not_match(self):
        self.assertEqual(P.cats("紙"), set())      # 「類」が必要
        self.assertEqual(P.cats("埋"), set())      # 「立」が必要
        self.assertEqual(P.cats("水"), set())      # 「銀」が必要
        self.assertEqual(P.cats(""), set())
        self.assertEqual(P.cats("収集休止"), set())

    def test_combination(self):
        self.assertEqual(P.cats("可燃・プラ"),
                         {"可燃ごみ", "プラスチック製容器包装"})


class TestDateHelpers(unittest.TestCase):
    def test_nth_of(self):
        self.assertEqual(P.nth_of(date(2026, 4, 1)), 1)
        self.assertEqual(P.nth_of(date(2026, 4, 7)), 1)
        self.assertEqual(P.nth_of(date(2026, 4, 8)), 2)
        self.assertEqual(P.nth_of(date(2026, 4, 29)), 5)

    def test_is_last_wd(self):
        self.assertTrue(P.is_last_wd(date(2026, 5, 31)))   # 翌週は6月
        self.assertFalse(P.is_last_wd(date(2026, 5, 24)))  # 翌週も5月
        self.assertTrue(P.is_last_wd(date(2027, 2, 28)))   # 翌週は3月


class TestInfer(unittest.TestCase):
    def test_weekly_single(self):
        S = days_where(lambda d: d.weekday() == 0)
        mode, pl, missing, extra = P.infer(S)
        self.assertEqual(mode, "weekly")
        self.assertEqual(pl["weekdays"], [0])
        self.assertEqual(missing, set())
        self.assertEqual(extra, set())

    def test_weekly_two_weekdays(self):
        S = days_where(lambda d: d.weekday() in (0, 3))
        mode, pl, missing, extra = P.infer(S)
        self.assertEqual(mode, "weekly")
        self.assertEqual(pl["weekdays"], [0, 3])
        self.assertEqual(missing, set())

    def test_weekly_with_holidays_becomes_exdates(self):
        S = days_where(lambda d: d.weekday() == 0)
        dropped = {sorted(S)[10], sorted(S)[30]}
        mode, pl, missing, extra = P.infer(S - dropped)
        self.assertEqual(mode, "weekly")
        self.assertEqual(missing, dropped)
        self.assertEqual(extra, set())

    def test_monthly_nth(self):
        S = days_where(lambda d: d.weekday() == 1 and P.nth_of(d) in (2, 4))
        mode, pl, missing, extra = P.infer(S)
        self.assertEqual(mode, "monthly")
        self.assertEqual(pl["weekday"], 1)
        self.assertEqual(pl["nth"], [2, 4])
        self.assertEqual(missing, set())
        self.assertEqual(extra, set())

    def test_monthly_last_weekday_roundtrips(self):
        # 最終金曜の集合は、推定ルール+EXDATEで過不足なく再現できること
        S = days_where(lambda d: d.weekday() == 4 and P.is_last_wd(d))
        mode, pl, missing, extra = P.infer(S)
        self.assertEqual(mode, "monthly")
        self.assertEqual((pl["expected"] - missing) | extra, S)

    def test_biweekly(self):
        anchor = date(2026, 4, 1)  # FY初日 (水曜)
        S = days_where(lambda d: (d - anchor).days % 14 == 0)
        self.assertTrue(all(d.weekday() == 2 for d in S))
        mode, pl, missing, extra = P.infer(S)
        self.assertEqual(mode, "biweekly")
        self.assertEqual(pl["weekday"], 2)
        self.assertEqual(missing, set())
        self.assertEqual(extra, set())

    def test_singles_few_dates(self):
        S = {date(2026, 5, 3), date(2026, 11, 20), date(2027, 2, 14)}
        mode, pl, missing, extra = P.infer(S)
        self.assertEqual(mode, "singles")

    def test_singles_scattered(self):
        S = {date(2026, 4, 5), date(2026, 5, 11), date(2026, 6, 17),
             date(2026, 7, 23), date(2026, 9, 2), date(2026, 10, 9),
             date(2026, 11, 18), date(2026, 12, 24), date(2027, 1, 15),
             date(2027, 3, 8)}
        mode, pl, missing, extra = P.infer(S)
        self.assertEqual(mode, "singles")


def sample_grid():
    grid = {d: set() for d in FY}
    burn = days_where(lambda d: d.weekday() in (0, 3))
    dropped = date(2026, 12, 31)  # 木曜
    assert dropped in burn
    for d in burn - {dropped}:
        grid[d].add("可燃ごみ")
    for d in days_where(lambda d: d.weekday() == 4 and P.nth_of(d) in (2, 4)):
        grid[d].add("プラスチック製容器包装")
    anchor = date(2026, 4, 1)
    for d in days_where(lambda d: (d - anchor).days % 14 == 0):
        grid[d].add("ペットボトル")
    for d in (date(2026, 5, 20), date(2026, 8, 19), date(2026, 11, 18),
              date(2027, 2, 17)):
        grid[d].add("水銀ごみ")
    return grid, dropped


class TestBuildIcs(unittest.TestCase):
    def setUp(self):
        self.grid, self.dropped = sample_grid()
        self.ics, self.rules = P.build_ics("testslug", "テスト地区", self.grid)

    def test_structure(self):
        self.assertTrue(self.ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(self.ics.endswith("END:VCALENDAR\r\n"))
        self.assertIn("X-WR-CALNAME:松山市テスト地区ごみカレンダー（令和8年度）", self.ics)
        self.assertIn("TRANSP:TRANSPARENT", self.ics)

    def test_weekly_rrule_and_exdate(self):
        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=MO,TH;UNTIL=20270331", self.ics)
        self.assertIn("DTSTART;VALUE=DATE:20260402", self.ics)  # 年度最初の該当曜日 (4/2=木曜)
        self.assertIn(f"EXDATE;VALUE=DATE:{self.dropped:%Y%m%d}", self.ics)

    def test_monthly_rrule(self):
        self.assertIn("RRULE:FREQ=MONTHLY;BYDAY=2FR,4FR;UNTIL=20270331", self.ics)

    def test_biweekly_rrule(self):
        self.assertIn("RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=WE;UNTIL=20270331", self.ics)

    def test_roundtrip_verify(self):
        self.assertEqual(P.verify(self.ics, self.grid), [])

    def test_verify_detects_mismatch(self):
        broken = {d: set(cs) for d, cs in self.grid.items()}
        target = sorted(days_where(lambda d: d.weekday() == 0))[5]
        broken[target] = set()
        mism = P.verify(self.ics, broken)
        self.assertTrue(any(m["date"] == target.isoformat() for m in mism))


class TestDetectHeaders(unittest.TestCase):
    def _words(self, rows):
        words = []
        for r, months in enumerate(rows):
            for c, mo in enumerate(months):
                words.append({"text": str(mo), "size": 30,
                              "top": r * 100, "x0": c * 240})
        return words

    def test_valid_layout(self):
        out = P.detect_headers(self._words([[4, 5, 6, 7], [8, 9, 10, 11], [12, 1, 2, 3]]))
        self.assertIsNotNone(out)
        self.assertEqual(len(out), 12)
        self.assertEqual([(y, m) for _, _, y, m in out],
                         [(2026, m) for m in range(4, 13)] + [(2027, m) for m in range(1, 4)])

    def test_wrong_month_returns_none(self):
        self.assertIsNone(P.detect_headers(
            self._words([[4, 5, 6, 9], [8, 9, 10, 11], [12, 1, 2, 3]])))

    def test_wrong_row_count_returns_none(self):
        self.assertIsNone(P.detect_headers(self._words([[4, 5, 6, 7], [8, 9, 10, 11]])))


class TestBundle(unittest.TestCase):
    def test_marker_key(self):
        bundles = {"第1木": ["缶類"], "第3金": ["紙類"]}
        self.assertEqual(B.marker_key("第1木", bundles), "第1木")
        self.assertEqual(B.marker_key("第1木曜", bundles), "第1木")
        self.assertIsNone(B.marker_key("可燃ごみ", bundles))
        self.assertIsNone(B.marker_key("", bundles))

    def test_norm_mapping(self):
        self.assertEqual(B.NORM["埋立"], "埋立ごみ")
        self.assertEqual(B.NORM["水銀"], "水銀ごみ")
        self.assertEqual(B.NORM["粗大"], "粗大ごみ")
        self.assertEqual(B.NORM["可燃"], "可燃ごみ")
        self.assertEqual(B.NORM.get("缶類", "缶類"), "缶類")  # 変換対象外はそのまま

    def test_build_bundle_ics_expands_markers(self):
        d1, d2 = date(2026, 4, 2), date(2026, 5, 7)
        grid_raw = {d: set() for d in FY}
        grid_raw[d1] = {"BUNDLE:第1木", "可燃ごみ"}
        grid_raw[d2] = {"BUNDLE:第1木"}
        bundles = {"第1木": ["缶類", "紙類"]}
        ics, expanded = B.build_bundle_ics("island", "島地区", grid_raw, bundles)
        self.assertEqual(expanded[d1], {"缶類", "紙類", "可燃ごみ"})
        self.assertEqual(expanded[d2], {"缶類", "紙類"})
        self.assertEqual(ics.count("SUMMARY:缶類"), 2)
        self.assertEqual(P.verify(ics, expanded), [])


GRIDS_DIR = Path(__file__).resolve().parent.parent / "grids"
ICS_DIR = Path(__file__).resolve().parent.parent / "ics"


@unittest.skipUnless(GRIDS_DIR.exists(), "grids/ はローカル作業用 (リポジトリには無い)")
class TestStoredData(unittest.TestCase):
    def test_all_published_ics_match_stored_grids(self):
        files = sorted(GRIDS_DIR.glob("*.json"))
        self.assertEqual(len(files), 43)
        for gf in files:
            raw = json.loads(gf.read_text(encoding="utf-8"))
            grid = {date.fromisoformat(k): set(v) for k, v in raw.items()}
            self.assertEqual(len(grid), 365, gf.name)
            ics_text = (ICS_DIR / (gf.stem + ".ics")).read_text(encoding="utf-8")
            self.assertEqual(P.verify(ics_text, grid), [], gf.name)


if __name__ == "__main__":
    unittest.main()
