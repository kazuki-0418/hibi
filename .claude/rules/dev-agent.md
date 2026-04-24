# Dev Agent Rules

実装タスク時に適用するルール。
対象: `**/*.py`, `migrations/*.sql`, `sources.yaml`, `.github/workflows/*.yml`

## Rules

- 変更前に既存コード・既存パターン・関連 docs（`architecture/diagrams/*.mmd`、`architecture/skills/hibi-domain.md`）を確認する
- 変更は現在の依頼に必要な範囲へ限定し、unrelated refactor をしない
- 既存のレイヤ責務を崩さない（fetcher / db / pipeline / delivery / click endpoint）
- 型ヒント必須。`Any` / `# type: ignore` で逃げない
- psycopg 3.x のみ。psycopg2 / SQLAlchemy / Alembic を導入しない
- async / 並行処理を導入しない（YAGNI 判断済み）
- 挙動を変える場合は、関連する tests / migrations / sources.yaml / docs の更新要否を確認する
- Hibi 固有の domain rules は `architecture/skills/hibi-domain.md` を優先して守る
- migration は新規ファイル追加のみ。既存 migration を編集しない
- 破壊的スキーマ変更（DROP / ALTER COLUMN）は別 PR + 運用窓
- secrets を yaml / コード / コミットメッセージに含めない（`.env` 管理）
- 作業完了時は status を明示する: `Pytest Passed` / `Pytest Failed` / `Pytest Not Run`、`Dry-run Passed` / `Dry-run Failed` / `Dry-run Not Run`、`Migration Applied` / `Migration Pending` / `Migration N/A`
