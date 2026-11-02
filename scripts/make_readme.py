#!/usr/bin/env python3
"""Generate the repository README.md from results.json.
Usage: make_readme.py <results.json> <label_ja> <label_en> <period> <index_url> <out.md>"""
import json, sys

results_path, label_ja, label_en, period, index_url, out_path = sys.argv[1:7]
r = json.load(open(results_path))
base = "https://raw.githubusercontent.com/hahifu/matsuyama-garbage-calendar/main/ics/"
rows = []
for slug, rec in sorted(r.items(), key=lambda kv: kv[1]["districts"][0]):
    rows.append(f"| {'・'.join(rec['districts'])} | {base}{slug}.ics |")
readme = f"""# 松山市 地区別ごみカレンダー iCal（{label_ja} / {label_en}）

松山市公式「地区別ごみカレンダー（{label_ja}）」の全地区分を、Googleカレンダー等で
購読できる iCalendar (.ics) 形式に変換したものです。

- 対応範囲: **全58地区 / 43カレンダー**（複数地区で1枚の共通カレンダーは1ファイル）
- 期間: {period}
- 出典: 松山市公式ホームページ「地区別ごみカレンダー（{label_ja}）」
  {index_url}
- 検証: 全カレンダーとも、公式PDFの全365日とICSの展開結果を照合し **不一致0件**
  （詳細は `TEST_RECORD.md`）
- 更新: 四半期ごとに公式カレンダーと自動で照合し、差分があればこのリポジトリを
  更新します。年度が替わると新年度版に差し替わります（購読URLは変わりません）。

## Googleカレンダーへの追加方法

1. 下の表から自分の地区のURLをコピーする
2. Googleカレンダー（PC版）を開き、「他のカレンダー」の「+」→「URLで追加」を選ぶ
3. URLを貼って「カレンダーを追加」を押す

読み取り専用の購読カレンダーとして追加され、自動で同期されます
（Google側の同期間隔は12〜24時間程度。年度内は内容が変わらないため実用上の問題はありません）。

## 地区別 購読URL

| 地区 | URL |
|---|---|
""" + "\n".join(rows) + """

## 形式の違いについて

- 本土側の地区: 繰り返し規則（毎週／第n週／隔週）＋休止日の除外（EXDATE）で表現。
- 島しょ部の一部（10カレンダー）: 公式カレンダーが「第n曜日まとめ日」方式のため、
  まとめ日の品目を日付ごとに展開した予定にしています。島しょ部では粗大ごみも
  まとめ日に収集されます。
- 粗大ごみ（本土側）は申込制で決まった日がないため、含めていません。

## 生成方法

`scripts/pipeline.py`（本土型）と `scripts/bundle.py`（島しょ部型）が、
公式PDFの転記→ICS生成→全365日照合を一括で行います。再現手順は `PROMPT.md`、
戻し方は `ROLLBACK.md` を参照してください。

## 注意

- 本データは公式カレンダーの転記です。最終的な確認は市の公式カレンダーを正としてください。
- 年度が替わったら、新年度のPDFで再生成が必要です。
"""
open(out_path, "w", encoding="utf-8").write(readme)
print("README written:", out_path)
