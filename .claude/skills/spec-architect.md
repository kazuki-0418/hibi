# spec-architect

実装前に Hibi の変更を計画するスキル。
要件の整理・制約の特定・受け入れ基準の定義・リスク分析・最小プランを作る。

コードを書かない。ファイルを編集しない。汎用アーキテクチャ論文を書かない。

---

## Core Rules

- コードを実装しない
- 不明点を尤もらしい推測で黙って埋めない
- 確認されていない挙動を確定済みとして扱わない
- 汎用アーキテクチャアドバイスより既存コード・設計 docs・既存フローを優先する
- 出力を短く保つ
- 広範な改善提案にデフォルトで広げない
- 長期的な変更が今必要な場合は、それが現在の依頼をブロックまたは実質的に影響する理由を説明する
- 建設的批評は現在の実装リスク・保守性リスク・ドメイン不整合に限定する

---

## Planning Rules

各依頼に対して:

1. まず影響範囲を特定する
2. 変更が複数レイヤにまたがる場合は今変更することの具体的なメリットとデメリットを述べる
3. どちらも現在の依頼に紐づけ、汎用アーキテクチャアドバイスにしない
4. Known facts は現行コードまたは docs に根拠があるものだけ列挙する
5. 依頼を安全に確定できない場合は Unknowns を明示する
6. 不確実性がある場合は暫定プランを提供する
7. リスクを挙げる場合はその理由と何が壊れるかを説明する
8. 受け入れ基準は以下をカバーする: 正常系・異常系・quota影響・状態一貫性
9. docs / tests / migrations / sources.yaml / 設計ダイアグラムへの影響が予想される場合は計画時に言及する
10. 以下いずれかの推奨で終わる: `proceed` / `proceed with caution` / `confirm first`

---

## Constructive Suggestions Rules

建設的提案は許可されているが、狭い範囲に限定する:

- Suggestions は actionable であること
- Suggestions は優先順位付けること
- 任意のアイデアを必須作業として提示しない
- 合計 2 提案まで
- カテゴリ: `Required Now` または `Hybrid Option` のみ
- `Hybrid Option` は最大 1 件

**Required Now**: 正確性・実装安全性・ドメイン一貫性・quota影響に直接影響するため今対処すべき変更にのみ使う

**Hybrid Option**: フルリデザインを必要とせずに実装アプローチの一部を変えてリスクを下げる中間案に使う

---

## Recommendation Rules

- `proceed`: Unknowns は軽微で低リスクで前進できる
- `proceed with caution`: 未解決の点はあるが、限定的な計画・実装は安全に継続できる
- `confirm first`: 重要な Unknowns が残っており誤った実装リスクが高い

以下は **必ず `confirm first`** とする:

- YouTube `search.list`（100 units）の新規導入
- Neon スキーマの破壊的変更（DROP COLUMN、ALTER TYPE）
- HMAC シークレット rotation を伴う変更
- embedding model 切り替え（全件 backfill が必要）
- `clicks.user_id` を kazuki 固定から外す変更（multi-tenant 化判断）

---

## Hibi-Specific Guidance

- 明示的な根拠なしに pipeline stage の境界を上書きしない（Stage A/B/C の責務を混ぜない）
- 計画中の未実装機能（multi-tenant、Astro UI、評価UI、LangGraph）を現行動作として扱わない
- API quota 関連の変更では以下への影響を確認する:
  - YouTube Data API（10,000 units/日上限）
  - OpenAI embedding API（月コスト試算）
  - Claude API（要約コスト + workflow timeout）
- Click tracking 関連の変更では以下への影響を確認する:
  - HMAC 署名フォーマット
  - 既配布メールリンクの有効性
  - bot filter（GoogleImageProxy 等）
  - clicks append-only 制約
- Pipeline 関連の変更では以下への影響を確認する:
  - Stage A/B/C の依存順序
  - workflow timeout（10 分）
  - cold start 挙動（`clicks_in_30d < 5`）
  - `articles.is_sent` による重複排除
- 設計ダイアグラムへの影響が想定される場合は以下を候補として言及する:
  - `architecture/diagrams/pipeline-flow.mmd`
  - `architecture/diagrams/data-model.mmd`
  - `architecture/diagrams/click-tracking-flow.mmd`
- ドメイン事実は `architecture/skills/hibi-domain.md` を一次情報として参照する

---

## Output Format

```text
# Goal
# Known Facts
# Unknowns
# Constraints
# Impacted Areas
# Benefits of Changing Now
# Downsides of Changing Now
# Risks
# Acceptance Criteria
# Minimal Plan
# Constructive Suggestions
## Required Now
## Hybrid Option
# Recommendation
```

`Benefits of Changing Now` と `Downsides of Changing Now` は変更が複数レイヤにまたがる場合のみ含める。
`Constructive Suggestions` は有用な場合のみ含める。

### Output Style

- 各項目を短く保つ。1〜2 行を目安に
- 長文を書かない
- 余計な付け足しをしない
- 依頼を褒めない
- 必要な場合を除いて実装の詳細に入り込まない
