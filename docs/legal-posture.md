# Hibi 法的ポジショニング

Hibi の現在の法的状態と、進行中の Perplexity 訴訟 (2025-08 提訴、東京地裁係属中) の含意を整理する。判決まで 1-2 年の見込みで、その間は **商用化判断を保留** する。再開条件と再開シグナルもここに固定する。

将来の AI セッション (Manager / `/triage-issue` / 個別 dev エージェント) がこのファイルを読んで「auth・multi-tenant 化・本文取得拡張・新規メディア追加」を提案する前に、ここでの判断を尊重できるよう書いてある。Markdown 1 ファイルが SSoT。

最終更新: 2026-05-14

---

## 1. Hibi の現状 (2026-05 時点)

- **1 人運用** (kazuki 単独購読者)。`RECIPIENT_EMAIL` 単一固定で配信。
- `articles.user_id` / `clicks.user_id` は kazuki 固定 UUID (`'00000000-0000-0000-0000-000000000001'`)。
- multi-tenant / signup / login の路線は **撤回済** (rollback PR #130、2026-05-14)。Better Auth 関連コードと `hibi-domain.md` の multi-tenant 文言を main から削除した。
- migration 007 (Better Auth 4 テーブル) は Neon に残存。additive で害なし、`hibi-domain.md` の「破壊的変更は別 PR + 運用窓」ルールに従い別途判断する。
- 商用化 / OSS 配布 / 第三者購読受付は **全部保留**。

## 2. Perplexity 訴訟の概要

- 提訴: 2025 年 8 月、東京地方裁判所
- 原告: 読売新聞 / 朝日新聞 / 日本経済新聞(主要 3 紙)
- 被告: Perplexity AI, Inc.
- 請求額合計: 約 66 億円(損害賠償)
- 主な争点:
  1. **robots.txt 無視** で公開ページを大量取得
  2. **記事本文をサーバに複製・保存** (著作権法 21 条複製権 / 27 条翻訳権 / 23 条公衆送信権)
  3. **paywall 突破** によるアクセス
  4. **媒体名を冠した不正確情報の配信** (不正競争防止法 2 条 1 項 21 号 — 信用毀損)

栗原潔弁護士の解説(末尾の一次ソース参照)によれば、被告の典型反論である「私的使用例外 (著作 30 条)」「情報解析例外 (著作 30 条の 4)」は **robots.txt 無視で大幅に弱まる** と評価されている。

## 3. Hibi のどこに該当するか

| 訴訟の争点 | Hibi での該当箇所 | 影響度 |
|---|---|---|
| robots.txt 無視 | `fetchers/rss.py` の `trafilatura.fetch_url()` は robots.txt を **見ていない** (README の「robots.txt 尊重」は誤記、後述) | 🔴 直撃 |
| 記事本文のサーバ複製・保存 | `trafilatura.extract()` で本文取得 + `articles.summary` として Neon に保存 | 🔴 直撃 |
| paywall 突破 | フィードに paywall 記事 URL が混入した場合、追加判定なく fetch する | 🟡 潜在 (現状の sources.yaml では未確認だが、構造上ガードがない) |
| 媒体名を冠した不正確情報 | `articles.source_name` をメール本文 / archive にそのまま表示、AI の summary は hallucination リスクあり | 🔴 直撃 |

### README の誤記について

`README.md` のフロー説明に「trafilatura（本文抽出 + robots.txt 尊重）」と記載があるが、現行 `fetchers/rss.py` は robots.txt を見ていない。本ドキュメント作成時点では「**判決を待ってから対応**」方針のため README の表現はこの doc とセットで読む。文言修正は商用化判断再開時にまとめて行う(README で「尊重」と書いて実装してない方が問題が大きいので、必要なら短期で README 側を「robots.txt は現状未尊重(#124 関連で保留中)」に直す選択肢もある)。

## 4. 防衛 PR の位置づけ

epic #124 で 5 件の防衛 issue を起こした(2026-05-14、Hibi 着手前)。直後に状況整理が進み、**個別実装は全て deferred** とした。

| issue | テーマ | 判断 |
|---|---|---|
| #125 | `trafilatura` を robots.txt 尊重モードに変更 + User-Agent 明示 | **保留** (Manager triage で `robots.txt 取得失敗時の fallback` が judgment call として未決のまま停止。判決後に再判断) |
| #126 | paywall 記事 URL の自動検出と除外 | **保留** (paywall detection の精度トレードオフが未検証) |
| #127 | `/copyright` ページ (出典ポリシー + 削除依頼窓口) | **保留** (公開ページ追加は商用化判断と紐づくため) |
| #128 | 本文未取得 / 不確実時の AI 要約抑止 | **保留** (現状 1 人運用なので影響対象が kazuki 自身のみ) |
| #129 | **本ドキュメント** | ← これ |

#124 と #125-#128 は **2026-05-14 に close**。実装着手は本ドキュメントが固まり、商用化判断が再開された時点で **新規 issue として再起票** する。

## 5. 商用化判断の保留条件

以下 **すべて満たすまで** Hibi を kazuki 単独の private newspaper にとどめる:

1. Perplexity 一審判決が出る(判決方向で robots.txt 尊重・本文複製の合法性レンジが見えるまで読めない)
2. もしくは Perplexity が 3 紙と和解(和解条件で許容範囲が見える)
3. 主要メディアとのライセンス契約あるいは API 経由配信パスを少なくとも 1 つ確保(Yahoo News API / Smartnews 等の公式パス)
4. 法務レビュー(社外弁護士)を最低 1 回通す体制

保留期間中の挙動:
- 配信先 = `RECIPIENT_EMAIL` 単一固定。新規 subscriber 受付しない。
- 公開 web archive (`hibi-news.com`) は読み取り専用、signup 動線なし。
- OSS 配布 (#74) / VS Code 拡張 (#77) / CLI (#76) / MCP (#75) は **設計検討のみ**。公開配布しない。

## 5.5 idea-mining は別パイプライン (保留対象外)

`idea_mining/` (Apple iTunes RSS 等の製品レビュー / ideation ソース) は newspaper 配信パイプライン (`daily_news.py` / `fetchers/rss.py` / `articles`) の外側に存在し、§5 の「新規メディアソース追加」保留対象には該当しない。

判断根拠:
- ニュース記事ではなく Apple 公式 RSS API + UGC (アプリレビュー)、§2 の 4 争点 (robots.txt / 本文複製 / paywall / 信用毀損) いずれにも該当しない
- メール配信 / archive 公開なし、`voices` テーブルに private で保管
- 将来 idea-mining 用に news サイト RSS を追加する場合は本除外対象外、§5 に従って判決後再判断

## 6. 再開シグナル

以下のうち **どれかが起きたら本ドキュメントを再開し、#124 相当の防衛 issue を再起票** する候補とする:

- Perplexity 一審判決(原告勝訴・敗訴いずれでも、判決理由が公開された時点で再評価)
- Perplexity と 3 紙のいずれかが和解(条件公開)
- 同種の海外判例 (Stack Overflow / Reddit / Google Search Generative Experience 訴訟) で robots.txt 尊重義務が明示される
- 日本の文化庁が著作権法 30 条の 4 のガイドラインを改訂(RAG / scraping への適用範囲を限定する方向)
- kazuki がメディア / 出版社と業務上の繋がりを持ち、Hibi の存在を伏せられない状況になる

再開時にやること:
1. このドキュメントの「現状」「該当箇所」「ソース」を最新化
2. 防衛 issue 群 (旧 #125 / #126 / #127 / #128 相当) を新規起票
3. 商用化判断保留条件 (§5) と再開シグナル (§6) を新条件で書き直す

## 7. 一次ソース

- **西村あさひ法律事務所ニュースレター** — 訴訟の論点整理(法律事務所視点)
  <https://www.nishimura.com/ja/knowledge/newsletters/intellectual_property_robotics_artificial_intelligence_251211>
- **栗原潔弁護士の解説** — 30 条の 4 と robots.txt の関係
  <https://news.yahoo.co.jp/expert/articles/342242c21eb5ea6f535bed02940d82a1e10106d8>
- **日経記事** — 提訴の事実関係
  <https://www.nikkei.com/article/DGXZQOUD302I50Q5A730C2000000/>
- **Nieman Lab (英語)** — 海外向けの解説
  <https://www.niemanlab.org/2025/08/japans-largest-newspaper-yomiuri-shimbun-sues-perplexity-for-copyright-violations/>

## 8. 関連 (Hibi 内)

- 撤回 PR #130 — auth / multi-tenant 路線の rollback
- closed epic #124 — 元の防衛 epic
- closed epic #109 / #111 — auth / multi-tenant 配信(本ドキュメントの方針整理を経て撤回)
- `architecture/skills/hibi-domain.md` — 「1 人運用」前提に戻した(PR #130 で同時 revert)
