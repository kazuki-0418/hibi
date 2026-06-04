# Obsidian vault in GitHub Actions (KAZ-206)

Daily news goal-conditioning (`KAZ-202` / `KAZ-204`) reads growth-subject notes from a
**separate private vault repo**, not from the Hibi git tree.

## Vault repository

- GitHub: `kazuki-0418/Obsidan-workspace` (historical repo name spelling)
- Local clone path is arbitrary; Actions uses `${{ github.workspace }}/obsidian-vault`

## Sparse checkout (privacy)

`daily-news.yml` checks out only:

```text
10_projects/monogatari/
10_projects/roamlore/
30_raw/hibi/          # capture + novelty inbox writes (ephemeral on the runner)
```

Other vault paths (personal notes, unrelated projects) are **not** fetched in CI.

## Required GitHub secret

| Secret | Purpose |
|--------|---------|
| `OBSIDIAN_VAULT_PAT` | Fine-grained PAT (or classic PAT) with **read** access to `Obsidan-workspace` |

Create under **Settings → Secrets and variables → Actions → New repository secret**.

Fine-grained PAT example:

- Repository access: `Obsidan-workspace` only
- Permissions: Contents → Read-only

Do **not** set `HIBI_GOALS_OPTIONAL=1` on the production daily-news job. That flag is
for unit tests only and forces empty goal context.

## Workflow env

After checkout, the pipeline sets:

```text
OBSIDIAN_VAULT_ROOT=${{ github.workspace }}/obsidian-vault
```

## Verify after checkout

`scripts/verify_vault_goal_paths.py` runs in Actions and logs which conditioning files
exist. Missing files are OK when a project is not set up yet, but goal context stays
empty for that slug.

## Local development

```bash
git clone git@github.com:kazuki-0418/Obsidan-workspace.git ~/Obsidian-workspace
export OBSIDIAN_VAULT_ROOT=~/Obsidian-workspace
python scripts/verify_vault_goal_paths.py
python daily_news.py
```

## Capture / inbox writes in CI

`daily_news.py` may write under `30_raw/hibi/capture/` and `30_raw/hibi/inbox/` on the
runner. Those files are **not** pushed back to the vault repo automatically (v0). Persist
captures locally or via a future vault commit workflow.

Centroid cache (`.hibi/goal_centroid_cache.json`) is also ephemeral in CI unless
`HIBI_GOAL_CACHE_DIR` is pointed at durable storage.
