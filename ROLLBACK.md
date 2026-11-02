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

## 四半期自動更新を止める場合
対象: cron ジョブ「garbage-calendar-quarterly-update」と Deploy Key「Muse quarterly updater」
手順:
1. cron ジョブを削除（または無効化）する。以後の自動実行は止まる。
2. GitHub のリポジトリ Settings → Deploy keys で「Muse quarterly updater」を削除する。
   これで VM からこのリポジトリへ push できなくなる。
3. VM 側の鍵ファイル publish/garbage_calendar_deploy_key（秘密鍵・公開鍵）を削除する。
4. ローカルの作業コピー publish/live-repo は削除してよい（リポジトリ本体には影響しない）。
