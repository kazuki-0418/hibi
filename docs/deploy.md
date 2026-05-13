# Homelab deploy

Personal AI Newspaper's FastAPI service is shipped as a private GHCR image and
fronted by a Cloudflare Tunnel. The homelab never opens inbound ports: the
outbound `cloudflared` daemon terminates the tunnel at Cloudflare's edge, and
Cloudflare proxies traffic to the local `fastapi` container over the internal
Docker network.

```
Internet
  │ HTTPS
Cloudflare Edge (TLS + WAF)
  │ Argo Tunnel (outbound, encrypted)
cloudflared container
  │ docker network "internal"
fastapi container :8000  (no host port binding)
```

## Prerequisites

- A Cloudflare account with the target domain onboarded as a zone.
- Docker + `docker compose` on the homelab host.
- A GitHub PAT with `read:packages` scope, if the GHCR image is private.

## 1. Create the Cloudflare Tunnel

1. In Cloudflare's **Zero Trust** dashboard: **Networks → Tunnels → Create tunnel**.
2. Connector type: **Cloudflared**. Tunnel name: `personal-newspaper`.
3. On the **Install connector** step, copy the generated token — this is the
   `TUNNEL_TOKEN` value used below. Do not click through the install command;
   `docker compose` brings up `cloudflared` with the token instead.
4. **Public Hostnames** tab → **Add a public hostname**:
   - Subdomain: `newspaper`
   - Domain: your Cloudflare-managed domain
   - Type: `HTTP`
   - URL: `fastapi:8000`  (Docker service DNS, not `localhost`)
5. Save. Cloudflare creates the DNS record automatically; no registrar work
   needed.

## 2. Log in to GHCR (one-time, if image is private)

```bash
echo "$GITHUB_PAT" | docker login ghcr.io -u <github-username> --password-stdin
```

Store the PAT somewhere the host user can re-read on rotation (e.g. a pass
entry) — the credential helper caches it in `~/.docker/config.json`.

## 3. Populate `secrets.env`

Clone the repo (or just copy `docker-compose.yml` and `secrets.env.example`):

```bash
git clone https://github.com/kazuki-0418/Personal-Daily-News.git
cd Personal-Daily-News
cp secrets.env.example secrets.env
chmod 600 secrets.env
$EDITOR secrets.env   # paste TUNNEL_TOKEN from step 1
```

`secrets.env` is `.gitignore`d — never commit it.

## 4. Bring the stack up

```bash
docker compose pull
docker compose up -d
docker compose ps
```

Expected result:

| container                           | PORTS  |
| ----------------------------------- | ------ |
| `hibi-fastapi`                      | *(empty — no host bind)* |
| `hibi-cloudflared`                  | *(empty)* |

## 5. Verify

```bash
# From the homelab, via docker network:
docker compose exec cloudflared wget -qO- http://fastapi:8000/health

# From anywhere on the internet, via the tunnel:
curl https://newspaper.<your-domain>/health
# → {"status":"ok","version":"0.1.0"}
```

Sanity check: stop `cloudflared` and confirm the public URL goes 5xx while
the `fastapi` container stays healthy — the service is reachable only via the
tunnel.

```bash
docker compose stop cloudflared
curl -I https://newspaper.<your-domain>/health   # 5xx expected
docker compose start cloudflared
```

## 6. Router / firewall

Leave inbound 80/443 **closed** on the home router. `cloudflared` establishes
outbound connections to Cloudflare on 443 only. No port forwarding required.

## Upgrades

```bash
docker compose pull     # pulls :latest from GHCR
docker compose up -d    # recreates containers whose image digest changed
```

## Troubleshooting

- `cloudflared` keeps restarting → `docker compose logs cloudflared`. Most
  often a stale / revoked `TUNNEL_TOKEN`; re-generate in Zero Trust and
  update `secrets.env`.
- Public URL returns 502 → the hostname route points at `fastapi:8000` but
  the container isn't healthy yet. `docker compose ps` should show `fastapi`
  as `healthy` before Cloudflare serves traffic.
- `docker pull` from GHCR 403s → PAT missing `read:packages` or the package
  visibility hasn't been flipped to allow the account. Re-run `docker login`.

## Access policies (future)

Cloudflare Access is not enabled yet. Click-tracking endpoints (`/r/*`, once
they land) stay public because they're hit from email clients. Management or
admin endpoints added later should be gated by a Zero Trust Access
application (email allowlist). Track under the relevant follow-up issue
before shipping any admin surface.
