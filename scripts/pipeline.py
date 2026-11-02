#!/usr/bin/env python3
"""松山市 地区別ごみカレンダー (令和8年度) 全地区ICS化パイプライン

手順 (地区ごと):
  1. 市公式PDFを座標解析で全365日転記する
  2. 種別ごとに収集パターン (毎週/第n週/隔週) を推定し、例外は EXDATE・単発で表す
  3. ICSを生成し、標準ライブラリ (icalendar+dateutil) で全365日展開して転記と照合する
  4. 不一致0の地区だけを ics/ に出す。不一致があれば理由つきで results.json に残す

使い方: python3 pipeline.py [--only slug,slug] [--no-download]
"""
import argparse
import calendar as calmod
import json
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import os
ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www.city.matsuyama.ehime.jp/kurashi/gomi/dashikata/gomicalender/"
INDEX_URL = os.environ.get("GARBAGE_INDEX_URL", BASE + "r8gomicaletikubetu.html")
INDEX_HTML = ROOT / "index_cache.html"
FY_START = date.fromisoformat(os.environ.get("GARBAGE_FY_START", "2026-04-01"))
FY_END = date.fromisoformat(os.environ.get("GARBAGE_FY_END", "2027-03-31"))
UNTIL_STR = FY_END.strftime("%Y%m%d")
FY_DAYS = []
_d = FY_START
while _d <= FY_END:
    FY_DAYS.append(_d)
    _d += timedelta(days=1)

CATEGORIES = ["可燃ごみ", "プラスチック製容器包装", "ペットボトル", "紙類",
              "金物・ガラス類", "埋立ごみ", "水銀ごみ"]
WD2 = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]



def save_results(results, prev=None):
    if prev:
        for k, v in prev.items():
            results.setdefault(k, v)
    tmp = ROOT / "results.json.tmp"
    tmp.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ROOT / "results.json")

def district_map():
    try:
        req = urllib.request.Request(INDEX_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            INDEX_HTML.write_bytes(r.read())
    except Exception:
        if not INDEX_HTML.exists():
            legacy = ROOT.parent / "garbage-shimizu" / "districts.html"
            INDEX_HTML.write_bytes(legacy.read_bytes())
    html = INDEX_HTML.read_text(encoding="utf-8")
    out = {}
    for rel, name in re.findall(r'href="([^"]+\.pdf)"[^>]*>([^<]*地区)', html):
        out.setdefault(rel.split("/")[-1], []).append(name.replace("地区", ""))
    return out  # {pdf filename: [district short names]}


def download(fname, force=False):
    dest = ROOT / "pdfs" / fname
    if dest.exists() and dest.stat().st_size > 100000 and not force:
        return dest
    req = urllib.request.Request(BASE + "r8gomicaletikubetu.files/" + fname,
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())
    return dest


def decode_day(text):
    if len(text) % 2 == 0 and all(text[i] == text[i + 1] for i in range(0, len(text), 2)):
        return int(text[0::2])
    return int(text)


def cats(txt):
    out = set()
    if "可燃" in txt: out.add("可燃ごみ")
    if "プラ" in txt: out.add("プラスチック製容器包装")
    if "ペット" in txt: out.add("ペットボトル")
    if "紙" in txt and "類" in txt: out.add("紙類")
    if "金" in txt: out.add("金物・ガラス類")
    if "埋" in txt and "立" in txt: out.add("埋立ごみ")
    if "水" in txt and "銀" in txt: out.add("水銀ごみ")
    return out


def _fixed_headers():
    sy = FY_START.year
    pos = [(48, 124), (276, 124), (514, 124), (752, 124), (37, 363), (276, 363),
           (505, 363), (744, 363), (28, 603), (287, 603), (514, 603), (752, 603)]
    months = [(sy, m) for m in range(4, 13)] + [(sy + 1, m) for m in range(1, 4)]
    return [(x, y, yr, mo) for (x, y), (yr, mo) in zip(pos, months)]


FIXED_HEADERS = _fixed_headers()


def detect_headers(words):
    nums = [w for w in words if w["size"] > 26 and re.fullmatch(r"\d{1,2}", w["text"])]
    rows = {}
    for w in nums:
        rows.setdefault(round(w["top"] / 100), []).append(w)
    if len(rows) != 3:
        return None
    sy = FY_START.year
    order = [(sy, m) for m in range(4, 13)] + [(sy + 1, m) for m in range(1, 4)]
    out = []
    for i, key in enumerate(sorted(rows)):
        ws = sorted(rows[key], key=lambda w: w["x0"])
        if len(ws) != 4:
            return None
        for w in ws:
            yr, mo = order[len(out)]
            if int(w["text"]) != mo:
                return None
            out.append((w["x0"], w["top"], yr, mo))
    return out


def parse_grid(path):
    import pdfplumber
    pdf = pdfplumber.open(path)
    page = pdf.pages[0]
    words = page.extract_words(extra_attrs=["size"])
    headers = detect_headers(words) or FIXED_HEADERS
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
                    dv = decode_day(w["text"]); days.append((dv, w)); seen.add(dv)
                except Exception:
                    pass
        for w in ws:
            if abs(w["size"] - 10) < 1.5 and re.fullmatch(r"\d+", w["text"]):
                try:
                    dv = decode_day(w["text"])
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
            else:
                cs = cats(txt)
                if txt and not cs:
                    unmapped.append(txt)
                grid[dd] = cs
    return grid, title, halts, unmapped


def nth_of(d):
    return (d.day - 1) // 7 + 1


def is_last_wd(d):
    return (d + timedelta(days=7)).month != d.month


def infer(S):
    """set[date] -> (mode, payload, missing, extra)
    mode: weekly | monthly | biweekly | singles"""
    S = set(S)
    cands = []
    # weekly
    W = {d.weekday() for d in S}
    exp = {d for d in FY_DAYS if d.weekday() in W}
    cands.append((len(exp ^ S), 0, "weekly", {"weekdays": sorted(W), "expected": exp}))
    # monthly nth (single weekday)
    if len({d.weekday() for d in S}) == 1:
        w = next(iter({d.weekday() for d in S}))
        N = {nth_of(d) for d in S}
        exp = {d for d in FY_DAYS if d.weekday() == w and nth_of(d) in N}
        cands.append((len(exp ^ S), 1, "monthly", {"weekday": w, "nth": sorted(N), "expected": exp, "neg": False}))
        if all(is_last_wd(d) for d in S if nth_of(d) == 5):
            N2 = {-1 if n == 5 else n for n in N}
            exp2 = {d for d in FY_DAYS if d.weekday() == w and
                    ((nth_of(d) in N2) or (-1 in N2 and is_last_wd(d)))}
            cands.append((len(exp2 ^ S), 1, "monthly", {"weekday": w, "nth": sorted(N2), "expected": exp2, "neg": True}))
        # biweekly, both phases
        for phase in (0, 1):
            anchor = min(S)
            base = anchor - timedelta(days=7 * phase)
            exp = {d for d in FY_DAYS if d.weekday() == w and ((d - base).days % 14 == 0) and d >= FY_START}
            cands.append((len(exp ^ S), 2, "biweekly", {"weekday": w, "expected": exp}))
    cands.sort(key=lambda t: (t[0], t[1]))
    score, _, mode, pl = cands[0]
    exp = pl["expected"]
    if len(S) <= 6 or score > max(4, 0.15 * len(S)):
        return "singles", {}, set(), set()
    return mode, pl, exp - S, S - exp


def build_ics(slug, title, grid):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             f"PRODID:-//hahifu//matsuyama-garbage-{slug}//JA",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:松山市{title}ごみカレンダー（令和8年度）",
             "X-WR-TIMEZONE:Asia/Tokyo"]
    rules_summary = {}
    for ci, cat in enumerate(CATEGORIES):
        S = {d for d, cs in grid.items() if cat in cs}
        if not S:
            continue
        mode, pl, missing, extra = infer(S)
        rules_summary[cat] = {"mode": mode, "count": len(S),
                              "exdates": sorted(x.isoformat() for x in missing),
                              "extras": sorted(x.isoformat() for x in extra)}
        uid = f"{slug}-{ci}"
        desc = f"松山市{title}のごみ収集日（令和8年度公式カレンダーより）"
        if mode == "singles":
            for i, d in enumerate(sorted(S)):
                lines += ["BEGIN:VEVENT", f"UID:{uid}-{i}@matsuyama-garbage",
                          f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                          f"SUMMARY:{cat}", f"DESCRIPTION:{desc}", "TRANSP:TRANSPARENT", "END:VEVENT"]
            continue
        start = min(pl["expected"])
        if mode == "weekly":
            rrule = "FREQ=WEEKLY;BYDAY=" + ",".join(WD2[w] for w in pl["weekdays"]) + ";UNTIL=" + UNTIL_STR
        elif mode == "monthly":
            parts = []
            for n in pl["nth"]:
                parts.append(f"{n}{WD2[pl['weekday']]}" if n > 0 else f"-1{WD2[pl['weekday']]}")
            rrule = "FREQ=MONTHLY;BYDAY=" + ",".join(parts) + ";UNTIL=" + UNTIL_STR
        else:
            rrule = f"FREQ=WEEKLY;INTERVAL=2;BYDAY={WD2[pl['weekday']]};UNTIL={UNTIL_STR}"
        ev = ["BEGIN:VEVENT", f"UID:{uid}@matsuyama-garbage",
              f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{start + timedelta(days=1):%Y%m%d}",
              f"RRULE:{rrule}"]
        for x in sorted(missing):
            ev.append(f"EXDATE;VALUE=DATE:{x:%Y%m%d}")
        ev += [f"SUMMARY:{cat}", f"DESCRIPTION:{desc}", "TRANSP:TRANSPARENT", "END:VEVENT"]
        lines += ev
        for i, d in enumerate(sorted(extra)):
            lines += ["BEGIN:VEVENT", f"UID:{uid}-x{i}@matsuyama-garbage",
                      f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                      f"SUMMARY:{cat}", f"DESCRIPTION:{desc}", "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n", rules_summary


def verify(ics_text, grid):
    from icalendar import Calendar
    from dateutil.rrule import rrulestr
    from datetime import datetime
    cal = Calendar.from_ical(ics_text.encode("utf-8"))
    got = {}
    for comp in cal.walk("VEVENT"):
        dt = comp.decoded("DTSTART")
        exs = set()
        if comp.get("EXDATE"):
            ex = comp.decoded("EXDATE")
            for grp in (ex if isinstance(ex, list) else [ex]):
                for x in (grp.dts if hasattr(grp, "dts") else [grp]):
                    exs.add(x.dt)
        dates = set()
        if comp.get("RRULE"):
            rule = rrulestr(comp.get("RRULE").to_ical().decode(), dtstart=dt)
            for d in rule:
                dd = d.date() if isinstance(d, datetime) else d
                if dd not in exs:
                    dates.add(dd)
        else:
            dates.add(dt)
        for dd in dates:
            got.setdefault(dd, set()).add(str(comp.get("SUMMARY")))
    mism = []
    for d in FY_DAYS:
        if grid.get(d, set()) != got.get(d, set()):
            mism.append({"date": d.isoformat(), "grid": sorted(grid.get(d, set())),
                         "ics": sorted(got.get(d, set()))})
    return mism


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()
    dmap = district_map()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    results = {}
    prev = {}
    rpath = ROOT / "results.json"
    if rpath.exists():
        prev = json.loads(rpath.read_text(encoding="utf-8"))
    for fname, districts in sorted(dmap.items()):
        slug = re.sub(r"^2026", "", fname[:-4])
        if only and slug not in only:
            if slug in prev:
                results[slug] = prev[slug]
            continue
        rec = {"slug": slug, "pdf": fname, "districts": districts}
        try:
            if not args.no_download:
                download(fname)
            grid, title, halts, unmapped = parse_grid(ROOT / "pdfs" / fname)
            rec["title"] = title
            rec["halts"] = halts
            if unmapped:
                from collections import Counter
                rec["status"] = "failed"
                rec["reason"] = "unmapped cell labels: " + str(Counter(unmapped).most_common(5))
                results[slug] = rec
                print(f"[failed] {slug} ({'/'.join(districts)}) {rec['reason']}", flush=True)
                save_results(results, prev)
                continue
            missing_days = [d.isoformat() for d in FY_DAYS if d not in grid]
            rec["grid_days"] = len(grid)
            rec["missing_days"] = missing_days
            (ROOT / "grids" / f"{slug}.json").write_text(
                json.dumps({d.isoformat(): sorted(cs) for d, cs in sorted(grid.items())},
                           ensure_ascii=False, indent=1), encoding="utf-8")
            if missing_days:
                rec["status"] = "failed"
                rec["reason"] = f"grid incomplete: {len(missing_days)} days missing"
            else:
                ics_text, rules = build_ics(slug, title or "・".join(districts) + "地区", grid)
                rec["rules"] = rules
                mism = verify(ics_text, grid)
                rec["mismatches"] = mism[:10]
                rec["mismatch_count"] = len(mism)
                if mism:
                    rec["status"] = "failed"
                    rec["reason"] = f"{len(mism)} day mismatches"
                else:
                    (ROOT / "ics" / f"{slug}.ics").write_text(ics_text, encoding="utf-8", newline="")
                    rec["status"] = "ok"
        except Exception as e:
            rec["status"] = "error"
            rec["reason"] = f"{type(e).__name__}: {e}"
        results[slug] = rec
        print(f"[{rec['status']}] {slug} ({'/'.join(districts)}) {rec.get('reason', '')}", flush=True)
        save_results(results, prev)
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    print(f"DONE ok={ok} total={len(results)}")


if __name__ == "__main__":
    main()
