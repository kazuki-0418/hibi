# architecture

Hibi の現行アーキテクチャを記述する一次情報。
将来構想や提案はここに置かない（`docs/` または GitHub Issue）。

## Diagrams

| ファイル | 内容 | 更新トリガー |
| --------- | ------ | ------------ |
| `diagrams/pipeline-flow.mmd` | 3-stage batch + click loop | Stage 構成・順序・依存が変わったとき |
| `diagrams/data-model.mmd` | articles / clicks / sources の関係 | スキーマ変更（migrations 追加時） |
| `diagrams/click-tracking-flow.mmd` | Gmail → HMAC検証 → clicks 記録 | クリック署名方式・bot filter ロジック変更時 |

## Skills

`skills/hibi-domain.md` がドメイン事実の固定文書。実装・レビュー・spec すべての作業で参照する。

## Update Rules

- 実装変更で挙動・スキーマ・フローが変わった場合、同じ PR でダイアグラムを更新する
- ダイアグラムを「理想形」に書き換えない。現行コードと整合させる
- 計画中機能はダイアグラムに含めない。`hibi-domain.md` の Known Not-Implemented Areas に記述する
