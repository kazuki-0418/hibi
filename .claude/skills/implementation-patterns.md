# implementation-patterns

Hibi の実装タスクの作業手順スキル。

実装・テスト・契約・設計 docs を整合させるために使う。
汎用知識文書として使わない。広範なアーキテクチャ変更を提案するために使わない。

既存コード・既存 docs・既存パターンを先に確認してから新しいものを提案する。

## 禁止

- 存在しない要件を補完しない
- 汎用ニュースリーダーの挙動をここに当てはめない
- unrelated refactor をしない
- cleanup や "while here" 改善でスコープを広げない
- 計画中機能を現行動作として記述しない
- コードの変更だけで作業完了とせず、影響する tests / migrations / docs / yaml も更新する

---

## Standard Workflow

実装タスクはこの順序で実行する:

1. 関連する既存コード（`fetchers/` / `db.py` / `daily_news.py`）を読む
2. 関連する設計 docs（`architecture/diagrams/*.mmd` と `architecture/skills/hibi-domain.md`）を読む
3. 影響範囲を特定する（fetcher / DB / pipeline / delivery / click endpoint のどこに及ぶか）
4. 最小限の実装変更を行う
5. 関連テスト（`tests/`）を更新する
6. 影響する migrations / sources.yaml / 環境変数を更新する
7. 挙動・フロー・スキーマ・制約が変わった場合は関連設計 docs を更新する
8. クロスレイヤの整合性を確認する（fetcher → DB → pipeline → delivery）
9. `uv run pytest` が通ることを確認する
10. dry-run（`python -m daily_news --dry-run`）が通ることを確認する
11. 固定の出力フォーマットで短いサマリーを返す

整合作業を省略しない。pytest が通ってもコードの変更だけでは完了ではない。

---

## Definition of Done

以下をすべて満たしたときのみ完了:

- 実装が更新されている
- 関連テストが更新されている
- 影響する migrations / sources.yaml / 環境変数が更新されている
- 挙動・フロー・スキーマ・制約が変わった場合は関連設計 docs が更新されている
- 変更後の挙動が fetcher・DB・pipeline・delivery で一貫している
- `uv run pytest` が通っている
- dry-run が通っている。または status が明示されている
- 残存する不明点が明示されている

以下の場合は完了ではない:

- コードしか変更されていない
- テストが旧挙動のまま
- 設計 docs / ダイアグラムが旧挙動のまま
- migrations を追加したが既存 Neon DB に適用していない（手動適用の status 明示が必要）
- 挙動が変わったが影響確認をしていない
- pytest / dry-run の status が不明

---

## Handling Unknowns

正しい変更が既存コード・設計 docs・確立されたパターンから判断できない場合:

- 変更を拡大しない
- 問題を unknown としてマークする
- 事実と仮定を分離する
- 実装スコープを最小に保つ
- 新しいルールやフローを黙って作らない

この区別を使う:

- **Facts**: 現行コードまたは現行 docs に根拠がある
- **Assumptions**: 確認されていない
- **Planned**: 将来の意図はあるが現行では有効ではない

不確実性がある場合は、大きく投機的な変更より小さく正確な変更を選ぶ。

---

## Updating Tests

実装が挙動を変えた場合は、同じタスクでテストを更新する。

- pytest fixture（`conftest.py`）と既存パターンに合わせる
- 変更後の挙動に必要な範囲でテストを更新する
- 無関係なカバレッジ作業に広げない
- 古い期待値を残さない
- 外部 API（YouTube / Claude / OpenAI / Gmail / Neon）はモックする。実呼び出しテストを増やさない
- DB 関連は `pytest-postgres` または in-memory mock。本番 Neon を test target にしない

影響する可能性のあるテスト範囲:

- `tests/fetchers/`: ソース取得ロジック
- `tests/test_db.py`: psycopg 3.x DB 操作
- `tests/test_pipeline.py`: 3-stage pipeline 統合
- `tests/test_click_endpoint.py`: HMAC 検証 / bot filter

---

## Updating Migrations and Schema

スキーマ変更時:

- `migrations/NNN_<description>.sql` を番号順に追加する
- 既存 migration ファイルを編集しない（新規追加のみ）
- 破壊的変更（DROP COLUMN / ALTER TYPE）は別 PR + 運用窓で実行
- 同じ PR に DDL と backfill DML を混ぜない
- `db.py` の関数シグネチャと型ヒントを更新する
- pgvector カラム変更時は次元数を確認する（現行 1536）
- migration 適用は手動（Neon SQL Editor）。PR description に適用 status を明示

---

## Updating Source Configuration

ソース変更時:

- `sources.yaml` を編集する。コードコメントアウトで無効化しない
- YouTube チャンネル追加時は `scripts/verify_channels.py` で実在検証
- LLM に `channel_id` を生成させない。名前と URL のみ LLM、ID は API 検証
- `enabled: false` で論理削除。yaml から削除すると履歴が失われる
- カテゴリは既存値を優先。新規カテゴリ追加は ranking 影響を試算する

---

## Updating Design Docs

実装が挙動・フロー・スキーマ・制約を変えた場合は、同じタスクで関連設計 docs を更新する。

優先 docs:

- `architecture/diagrams/pipeline-flow.mmd`
- `architecture/diagrams/data-model.mmd`
- `architecture/diagrams/click-tracking-flow.mmd`
- `architecture/skills/hibi-domain.md`

- 変更に影響する docs だけを更新する
- docs を現行の実際の挙動と整合させる
- docs を理想的な将来アーキテクチャに書き直さない
- 実装されていない挙動を実装済みとして記述しない
- ダイアグラムの変更は小さく事実に基づいて行う

---

## Domain-Specific Checks

### API quota and cost

YouTube / OpenAI / Claude API の呼び出し数増加を伴う変更:

- YouTube `playlistItems.list` の呼び出し数を quota 試算（10,000 units/日上限）
- `search.list`（100 units）を新規導入する変更は明示承認が必要
- embedding 対象記事数の増減を月コストで試算（text-embedding-3-small は $0.02/1M tokens）
- summarize 対象本数の変更は workflow timeout（10 分）影響を確認

### Click tracking and signing

クリックトラッキング関連の変更:

- HMAC 署名フォーマット変更は既配布メールのリンクを無効化する
- HMAC シークレット rotation には運用窓が必要
- bot filter（GoogleImageProxy 等）の通過判定を確認
- `clicks.user_id` を kazuki 固定から外す変更は multi-tenant 化判断が必要

### Pipeline state

3-stage pipeline の変更:

- Stage A の取得本数変更は YouTube quota に影響
- Stage B の14日窓 / `is_sent` フィルタ変更は重複判定に影響
- Stage B のランキング変更は cold start 挙動（`clicks_in_30d < 5`）を確認
- 各 Stage の timeout 試算を更新（現行は Stage C が支配的）

### Embedding consistency

- embedding model 切り替えは全件 backfill が必要
- 次元数を変える変更は pgvector カラム ALTER + backfill + index 再作成
- embedding 失敗時は `sim = 0` で fails-open。ranking を停止しない設計を崩さない

### Schema and persistence

migrations 追加時:

- 既存 Neon DB に対する破壊的変更は手動承認 + 運用窓
- backfill が必要な場合は別 PR に分ける
- `articles.is_sent` を変更する logic は重複送信防止の唯一の真実であることを保つ
- `clicks` は append-only。論理削除カラムを足さない

### Delivery

- Gmail OAuth refresh_token は Production consent screen が前提
- メール本文の URL はすべて HMAC 署名付きトラッキング URL に置換されているか確認
- bounce / unsubscribe / Privacy Policy 関連は multi-tenant 化前は不要

---

## Build and Test Verification

確認は必須。

- `uv run pytest` が通るかどうかを作業完了前に確認する
- `python -m daily_news --dry-run` が通るかどうかを確認する（DB 書き込み・メール送信なし）
- migration を追加した場合は Neon SQL Editor で適用済みか明示する
- status が不明な場合は安全と仮定しない

以下のステータスのいずれかだけを使う:

- `Pytest Passed` / `Pytest Failed` / `Pytest Not Run`
- `Dry-run Passed` / `Dry-run Failed` / `Dry-run Not Run`
- `Migration Applied` / `Migration Pending` / `Migration N/A`

---

## Python-Specific Conventions

- 型ヒント必須（`articles: list[Article]`、`def fetch(channel: str) -> list[VideoMetadata]`）
- `Any` / `# type: ignore` で逃げない
- psycopg 3.x のみ使用。psycopg2 / SQLAlchemy / Alembic を持ち込まない
- 生 SQL を `db.py` に書く。ORM レイヤを足さない
- async / 並行処理を導入しない（YAGNI 判断済み、現行 N=5 の要約は直列で workflow timeout 内に収まる）
- 環境変数は `.env` + `os.getenv()` で読む。secrets ライブラリは追加しない
- yaml 読み込みは `PyYAML`。`ruamel.yaml` 等に切り替えない
- requirements は `uv` 管理。`pip install` を直接実行しない

---

## Fixed Output Format

実装作業後はこのフォーマットを使う:

### Affected Areas

### Changes Made

### Tests Updated

### Migrations / Schema Updated

### sources.yaml Updated

### Docs Updated

### Pytest Status

### Dry-run Status

### Migration Apply Status

### Remaining Unknowns
