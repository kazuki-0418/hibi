# idea_mining

Hibi の 5 AI workflow (Collector / Extractor / Spotter / Ideator / Critic) のうち、
個人固有の制約と過去 KILL 例 (profile) を必要とする下流 AI が共通で使う基盤。

本ディレクトリでは現状以下のみ提供する:

- `profile_loader.py` — Vault の `profile/*.md` を 1 つの prompt block 文字列に
  整形して返す。
- `prompts/_profile_block.py` — `profile_loader.load()` を呼ぶ薄い helper。
  下流 prompt の先頭にそのまま貼り付ける用途。

実際の prompt 組み込み (#138 Ideator / #139 Critic) は本ディレクトリ範囲外。

## profile の置き場所

profile は Hibi リポジトリには入れず、別 Vault (Obsidian-workspace) で管理する。
固定パスは次のとおり:

```
${OBSIDIAN_VAULT_ROOT}/10_projects/hibi/idea-mining/profile/
├── user-constraints.md     # 必須条件 / 避けるパターン / ペルソナ
└── negative-examples.md    # 過去に KILL したアイデアと理由
```

`profile_loader.load()` は上記 2 ファイルを Markdown 全文のまま結合して返す。
front-matter 解析やセクション抽出は行わない。

## 環境変数

| 変数 | 役割 | 例 |
|---|---|---|
| `OBSIDIAN_VAULT_ROOT` | Vault clone のルート (`10_projects/` を含むディレクトリ) | `/Users/kazuki/Obsidian-workspace` |
| `HIBI_VAULT_OPTIONAL` | `1` のときに限り loader が空文字列を返す (テスト用 escape) | `1` |

### Vault clone path の設定方法

1. Obsidian-workspace リポを任意のパスに clone する:

   ```bash
   git clone git@github.com:kazuki-0418/Obsidan-workspace.git ~/Obsidian-workspace
   ```

2. `.env` (ローカル) または GitHub Secrets (Actions) に `OBSIDIAN_VAULT_ROOT` を
   追加する:

   ```env
   OBSIDIAN_VAULT_ROOT=/Users/kazuki/Obsidian-workspace
   ```

3. profile ファイル本体 (`profile/user-constraints.md` 等) は Vault 側 PR で
   別途用意する。Hibi 側 (本リポ) には profile 本体をコピーしない。

## Fails-closed セマンティクス

下流 prompt は profile なしで走らせない方針なので、loader は次の場合に
`RuntimeError` を送出する:

- `OBSIDIAN_VAULT_ROOT` が未設定
- 必須 2 ファイル (`user-constraints.md` / `negative-examples.md`) のいずれかが
  見つからない

CI やローカルで Vault を mount せずに idea_mining コードをテストしたい場合は
`HIBI_VAULT_OPTIONAL=1` を set すると loader は空文字列を返す。**本番 (cron /
pipeline) では絶対に set しない**。
