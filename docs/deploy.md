# Homelab deploy

Hibi's FastAPI service is shipped as a private GHCR image and fronted by a
Cloudflare Tunnel. **Main-branch pushes auto-deploy to the homelab** via a
self-hosted GitHub Actions runner — no manual `docker compose pull` needed in
the normal path.

```
Internet
  │ HTTPS
Cloudflare Edge (TLS + WAF)
  │ Argo Tunnel (outbound, encrypted)
cloudflared container
  │ docker network "internal"
nginx → hibi-api :8000  (no host port binding)
```

## Auto-deploy pipeline

Triggered by `push` to `main` that touches `service/**` or a deploy-related
workflow file. The orchestrator runs:

```
push to main (service/** changed)
  │
orchestrator.yml (ubuntu-latest)
  ├─ build-and-push.yml   →  ghcr.io/<owner>/hibi-api:sha-<long-sha>
  └─ deploy.yml (self-hosted runner on homelab)
        ├─ /opt/ops/.env.deploy ← HIBI_API_TAG=sha-<long-sha>
        ├─ cd /opt/ops && make deploy-hibi
        └─ curl https://api.hibi-news.com/health (retry up to 5×)
```

Concurrency group `hibi-prod-${ref}` cancels in-flight runs when a newer
commit lands so deploys never interleave.

`sha-*` tagging pins each deploy to its exact build (the same image identity
flows into `HIBI_RELEASE` for Sentry via the image's env). `:latest` is still
pushed for ad-hoc operations but is not what production normally runs.

## One-time prerequisites

These are recorded for reference; they have already been done for this repo.

### Cloudflare Tunnel

1. Cloudflare **Zero Trust → Networks → Tunnels → Create tunnel**.
2. Connector type: **Cloudflared**. Reuse the existing homelab tunnel.
3. **Public Hostnames** → **Add a public hostname**:
   - Subdomain: `api`, Domain: `hibi-news.com`
   - Type: `HTTP`, URL: `nginx:80` (nginx fronts hibi-api over the internal
     Docker network and adds the `X-Forwarded-*` headers FastAPI needs).

### Self-hosted runner on homelab

1. https://github.com/<owner>/hibi/settings/actions/runners → **New
   self-hosted runner** (Linux x64).
2. On the homelab box:
   ```bash
   mkdir -p ~/actions-runner-hibi && cd ~/actions-runner-hibi
   curl -o actions-runner.tar.gz -L <URL from GitHub install page>
   tar xzf actions-runner.tar.gz
   ./config.sh --url https://github.com/<owner>/hibi \
               --token <one-shot token from the install page> \
               --name homelab-hibi \
               --labels self-hosted,hibi \
               --unattended
   sudo ./svc.sh install
   sudo ./svc.sh start
   ```
3. Runner appears as `Idle` (green) on the Actions runners page. The deploy
   workflow targets `runs-on: [self-hosted, hibi]` so it never lands on the
   monogatari runner.

### `/opt/ops/` on homelab

The compose stack and Makefile live under `/opt/ops/` and are shared with
monogatari. Required pieces specific to hibi:

- `compose.yml` (or `docker-compose.yml`) declares `hibi-api` with
  `image: ghcr.io/<owner>/hibi-api:${HIBI_API_TAG:-latest}` and a Python-based
  healthcheck (slim images do not ship `wget`).
- `nginx/conf.d/hibi.conf` proxies `api.hibi-news.com` → `hibi-api:8000`
  with `X-Forwarded-*` and `proxy_redirect off` (the click route 302s to
  external URLs).
- `env/hibi/api.env` carries `CLICK_SIGNING_SECRET`, `DATABASE_URL`,
  `PUBLIC_BASE_URL`, `IP_SALT`, `SENTRY_DSN`, `HIBI_RELEASE`, `HIBI_ENV`,
  etc. `chmod 600` and keep out of git.
- `Makefile` has `deploy-hibi` (`pull-hibi` → `up-hibi` → `clean-images`).

## Manual override (rollback / red button)

```bash
ssh homelab
cd /opt/ops

# Point at a known-good SHA (any tag the registry has).
sed -i '/^HIBI_API_TAG=/d' .env.deploy
echo "HIBI_API_TAG=sha-<known-good-long-sha>" >> .env.deploy
make deploy-hibi
```

`/opt/ops/.env.deploy` is the single source of truth for which image is
running; the workflow only edits its own `HIBI_API_TAG=` line and leaves
sibling lines (`FRONT_TAG`, `BACK_TAG`, etc.) untouched.

## Verifying a deploy

```bash
# From any client:
curl https://api.hibi-news.com/health
# → {"status":"ok","version":"0.1.0"}

# On homelab:
docker compose ps hibi-api          # expect Up ... (healthy)
docker compose logs --tail=50 hibi-api
```

## Troubleshooting

- `deploy.yml` fails at "Verify /health": container started but
  `api.hibi-news.com` 5xx → check `nginx` logs first (`docker compose logs
  nginx`), then `cloudflared`. If nginx is healthy and hibi-api is healthy,
  Cloudflare's tunnel routing may have been edited.
- `make deploy-hibi` fails on the self-hosted runner: the runner user needs
  rights to read `/opt/ops/.env.deploy` and to run `docker compose`. Confirm
  with `sudo ./svc.sh status` and a manual `make pull-hibi` as the runner
  user.
- `docker pull` from GHCR 403s → the runner user needs a PAT with
  `read:packages` cached in `~/.docker/config.json`. `docker login ghcr.io`
  once on the host.

## Future work

Cloudflare Access is not enabled yet. Click-tracking endpoints (`/r/*`) stay
public because they're hit from email clients. Any admin surface added later
should be gated by a Zero Trust Access application — track under a separate
issue.
