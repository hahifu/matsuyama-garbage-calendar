#!/usr/bin/env python3
"""島しょ部型 (第n曜日まとめ日) 地区のICS化

本土型と違い、セルには品目名でなく「第1木」等のまとめ日マーカーが入る。
凡例 (タイトル帯の「第n曜ごみ」見出しと、その右の品目リスト) を座標で読み取り、
マーカーの日付に凡例の品目を展開してICS化する。検証は本土型と同じく
標準ライブラリで全365日展開し、展開済みグリッドと照合する。
"""
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import (ROOT, FY_DAYS, parse_grid, infer, cats, download, district_map)

CAT_KEYS = ["缶類", "金物・ガラス類", "埋立", "水銀", "粗大", "ペットボトル",
            "プラスチック製容器包装", "紙類", "びん類", "可燃"]
NORM = {"埋立": "埋立ごみ", "水銀": "水銀ごみ", "粗大": "粗大ごみ", "可燃": "可燃ごみ"}


def parse_legend(path):
    import pdfplumber
    pdf = pdfplumber.open(path)
    words = pdf.pages[0].extract_words(extra_attrs=["size"])
    headers = [w for w in words if w["top"] < 112 and 14 <= w["size"] <= 20
               and re.fullmatch(r"第\d[月火水木金土日]曜ごみ", w["text"])]
    bundles = {}
    for h in headers:
        marker = h["text"][:3]  # 第1木曜ごみ -> 第1木 (セルのマーカー表記)
        items = [w for w in words
                 if h["x0"] + 80 <= w["x0"] <= h["x0"] + 340
                 and h["top"] - 8 <= w["top"] <= h["top"] + 26
                 and 8 <= w["size"] <= 11.5
                 and any(k in w["text"] for k in CAT_KEYS)]
        text = "".join(w["text"] for w in sorted(items, key=lambda w: (round(w["top"] / 10), w["x0"])))
        found = []
        for k in CAT_KEYS:
            if k in text:
                found.append(NORM.get(k, k))
        bundles[marker] = found
    return bundles


def marker_key(txt, bundles):
    for m in bundles:
        if txt.startswith(m):
            return m
    return None


def build_bundle_ics(slug, title, grid_raw, bundles):
    """grid_raw: date -> raw pseudo set (from cats + markers); markers expanded here"""
    expanded = {}
    for d, cs in grid_raw.items():
        out = set()
        for c in cs:
            if c.startswith("BUNDLE:"):
                out |= set(bundles[c[7:]])
            else:
                out.add(c)
        expanded[d] = out
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             f"PRODID:-//hahifu//matsuyama-garbage-{slug}//JA",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:松山市{title}ごみカレンダー（令和8年度）",
             "X-WR-TIMEZONE:Asia/Tokyo"]
    all_cats = sorted({c for cs in expanded.values() for c in cs})
    for ci, cat in enumerate(all_cats):
        S = {d for d, cs in expanded.items() if cat in cs}
        if not S:
            continue
        desc = f"松山市{title}のごみ収集日（令和8年度公式カレンダーより）"
        for i, d in enumerate(sorted(S)):
            lines += ["BEGIN:VEVENT", f"UID:{slug}-b{ci}-{i}@matsuyama-garbage",
                      f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                      f"SUMMARY:{cat}", f"DESCRIPTION:{desc}", "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n", expanded


def main():
    dmap = district_map()
    results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    targets = [s for s, r in results.items()
               if r.get("status") == "failed" and "unmapped" in str(r.get("reason", ""))]
    print("bundle targets:", targets)
    for slug in targets:
        rec = results[slug]
        fname = rec["pdf"]
        path = ROOT / "pdfs" / fname
        bundles = parse_legend(path)
        # re-parse grid keeping raw markers: monkeypatch cats via pipeline internals
        grid, title, halts, unmapped = parse_grid_marked(path, bundles)
        rec["bundles"] = bundles
        rec["halts"] = halts
        # 空虚な合格を防ぐ: マーカーが実際にセルに現れ、未対応ラベルが残っていないこと
        marker_hits = {m: 0 for m in bundles}
        for cs in grid.values():
            for c in cs:
                if c.startswith("BUNDLE:"):
                    marker_hits[c[7:]] = marker_hits.get(c[7:], 0) + 1
        rec["marker_hits"] = marker_hits
        if (not bundles or any(not v for v in bundles.values())
                or any(n < 10 for n in marker_hits.values()) or unmapped):
            rec["status"] = "failed"
            rec["reason"] = (f"legend/marker check failed: bundles={bundles} "
                             f"hits={marker_hits} unmapped={unmapped[:3]}")
            print(f"[failed] {slug} {rec['reason']}", flush=True)
            results[slug] = rec
            (ROOT / "results.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
            continue
        ics_text, expanded = build_bundle_ics(slug, title or slug, grid, bundles)
        from pipeline import verify
        mism = verify(ics_text, expanded)
        rec["mismatch_count"] = len(mism)
        rec["mismatches"] = mism[:10]
        if mism:
            rec["status"] = "failed"
            rec["reason"] = f"bundle verify: {len(mism)} mismatches"
            print(f"[failed] {slug} verify {len(mism)} mismatches {mism[:3]}", flush=True)
        else:
            (ROOT / "ics" / f"{slug}.ics").write_text(ics_text, encoding="utf-8", newline="")
            (ROOT / "grids" / f"{slug}.json").write_text(
                json.dumps({d.isoformat(): sorted(cs) for d, cs in sorted(expanded.items())},
                           ensure_ascii=False, indent=1), encoding="utf-8")
            rec["status"] = "ok"
            rec["reason"] = ""
            print(f"[ok] {slug} bundles={bundles}", flush=True)
        results[slug] = rec
        (ROOT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    print(f"DONE ok={ok} total={len(results)}")


def parse_grid_marked(path, bundles):
    """pipeline.parse_grid と同じ転記だが、セル文字列をそのまま保持して
    マーカーを BUNDLE:<marker> として返す"""
    import pdfplumber
    import pipeline as P
    pdf = pdfplumber.open(path)
    page = pdf.pages[0]
    words = page.extract_words(extra_attrs=["size"])
    headers = P.detect_headers(words) or P.FIXED_HEADERS
    title_words = [w for w in words if w["size"] >= 26 and w["top"] < 110 and w["x0"] < 700
                   and not re.fullmatch(r"\d{1,2}", w["text"])]
    title = "".join(w["text"] for w in sorted(title_words, key=lambda w: w["x0"]))
    grid, halts, unmapped = {}, [], []
    for hx, hy, yr, mo in headers:
        x0, x1, y0, y1 = hx - 22, hx + 218, hy + 30, hy + 238
        ws = [w for w in words if x0 <= w["x0"] < x1 and y0 <= w["top"] < y1]
        days, seen = [], set()
        for w in ws:
            if abs(w["size"] - 20) < 1 and re.fullmatch(r"\d+", w["text"]):
                try:
                    dv = P.decode_day(w["text"]); days.append((dv, w)); seen.add(dv)
                except Exception:
                    pass
        for w in ws:
            if abs(w["size"] - 10) < 1.5 and re.fullmatch(r"\d+", w["text"]):
                try:
                    dv = P.decode_day(w["text"])
                    if dv not in seen and 1 <= dv <= 31:
                        days.append((dv, w)); seen.add(dv)
                except Exception:
                    pass
        labels = [w for w in ws if 4 <= w["size"] <= 11.5 and not re.fullmatch(r"\d+", w["text"])]
        per = {dv: [] for dv, _ in days}
        for w in labels:
            cand = []
            for dv, a in days:
                dt = w["top"] - a["top"]
                dx = abs(w["x0"] - (a["x0"] - 2))
                if 6 <= dt <= 34 and dx < 17:
                    cand.append((dx, dv, w))
            if cand:
                cand.sort(key=lambda t: t[0])
                per[cand[0][1]].append(w)
        for dv, lw in per.items():
            txt = "".join(w["text"] for w in sorted(lw, key=lambda w: w["x0"]))
            dd = date(yr, mo, dv)
            if "休止" in txt:
                halts.append(dd.isoformat())
                grid[dd] = set()
                continue
            cs = cats(txt)
            mk = marker_key(txt, bundles) if txt else None
            if mk:
                cs = set(cs) | {f"BUNDLE:{mk}"}
            elif txt and not cs:
                unmapped.append(txt)
            grid[dd] = cs
    return grid, title, halts, unmapped


if __name__ == "__main__":
    main()
