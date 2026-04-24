# Test Agent Rules

テスト追加・更新時に適用するルール。
対象: `tests/**/*.py`, `conftest.py`

## Rules

- まず既存テストを確認し、必要なら更新する。毎回新規作成を前提にしない
- 変更した挙動に対して、必要な範囲で正常系・異常系・境界条件を検証する
- style より behavior, contract, quota impact, state consistency を優先して確認する
- Hibi では HMAC 署名検証, pipeline stage boundary, articles.is_sent 整合性, click append-only 制約に注意する
- 外部 API（YouTube / Claude / OpenAI / Gmail / Neon）はモックする。実呼び出しテストを増やさない
- planned-but-unwired features（multi-tenant, Astro UI, 評価UI）は現行仕様としてテストしない
- モックは最小限にし、既存 fixture（`conftest.py`）に合わせる
- 型ヒント必須。`Any` / `# type: ignore` で逃げない
- DB テストは pytest-postgres または in-memory mock。本番 Neon を test target にしない
- cold start 挙動（`clicks_in_30d < 5`）は ranking 変更時に必ず検証する
- 挙動が変わる場合は、関連テストの更新有無を明示する
