# ロールバック手順 — 松山市 地区別ごみカレンダーICS

## GitHub公開を取り消す場合
対象: リポジトリ hahifu/matsuyama-garbage-calendar（public）
手順:
1. GitHubのリポジトリ設定（Settings → General → Danger Zone）からリポジトリを削除する。
   または、ファイルだけを消す場合は削除コミットをpushする。
2. Googleカレンダー側は、各アカウントで該当カレンダーの購読を解除すれば表示が消える
   （購読は読み取り専用コピーなので、解除しても他に影響はない）。

## ローカル成果物をなかったことにする場合
対象: ~/workspace/touch-display/garbage-matsuyama/ 一式
手順:
1. フォルダごと削除する。
2. キオスク側の清水ICS（~/workspace/touch-display/kiosk/garbage.ics）は別成果物なので
   個別に判断する。消す場合はPi側の garbage.ics / garbage.json も消すとゴミ表示だけが
   消え、時計・天気・カレンダー表示には影響しない。

## 年度途中で公式カレンダーが改訂された場合
- 改訂版PDFで再生成し、TEST_RECORD.md の検証をすべて通してから同じパスへ差し替える
  （購読URLは変わらない）。差し替え前の版はGitの履歴に残るので、戻す場合は
  該当コミットへ revert する。
