# CF Companion

<p align="center">
    <strong>Automatic Cloudflare DNS for your Docker containers.</strong><br>
    Deploy a container with Traefik labels — DNS just happens. No more manual CNAME records.
</p>

<p align="center">
    <a href="https://github.com/smashingtags/cf-companion/actions">
        <img src="https://img.shields.io/github/actions/workflow/status/smashingtags/cf-companion/build.yml?label=Build&logo=github" alt="Build">
    </a>
    <a href="https://hub.docker.com/r/smashingtags/cf-companion">
        <img src="https://img.shields.io/docker/pulls/smashingtags/cf-companion?label=Docker%20Pulls&logo=docker" alt="Docker Pulls">
    </a>
    <a href="https://github.com/smashingtags/cf-companion/pkgs/container/cf-companion">
        <img src="https://img.shields.io/badge/GHCR-Available-blue?logo=github" alt="GHCR">
    </a>
    <a href="https://github.com/smashingtags/cf-companion/blob/main/LICENSE">
        <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT License">
    </a>
</p>

<p align="center">
    <a href="https://discord.gg/Pc7mXX786x">
        <img src="https://img.shields.io/discord/1334411584927301682?label=Discord&logo=discord&color=5865F2" alt="Discord">
    </a>
    <a href="https://ko-fi.com/homelabarr">
        <img src="https://img.shields.io/badge/Ko--fi-Support-FF5E5B?logo=kofi&logoColor=white" alt="Ko-fi">
    </a>
    <a href="https://imogenlabs.ai">
        <img src="https://img.shields.io/badge/Imogen_Labs-AI-8B5CF6?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJ3aGl0ZSI+PHBhdGggZD0iTTEyIDJMMiA3bDEwIDUgMTAtNXoiLz48L3N2Zz4=&logoColor=white" alt="Imogen Labs">
    </a>
    <a href="https://homelabarr.com">
        <img src="https://img.shields.io/badge/HomelabARR-Website-FF8C1A?logo=firefox&logoColor=white" alt="HomelabARR">
    </a>
    <a href="https://twitter.com/Imogen_Labs">
        <img src="https://img.shields.io/badge/𝕏-@Imogen__Labs-000000?logo=x&logoColor=white" alt="X/Twitter">
    </a>
    <a href="https://www.reddit.com/r/homelabarr/">
        <img src="https://img.shields.io/badge/Reddit-r/homelabarr-FF4500?logo=reddit&logoColor=white" alt="Reddit">
    </a>
</p>

---

## The Problem

You deploy a new container behind Traefik. It needs a DNS record. So you:

1. Open Cloudflare dashboard
2. Navigate to DNS
3. Create a CNAME record
4. Set the target
5. Toggle proxy
6. Save

**Every. Single. Time.**

Some people have been doing this manually for years. Some have had broken auto-DNS for even longer.

## The Solution

CF Companion watches Docker events. When a container starts with a Traefik `Host()` rule, it automatically creates the Cloudflare DNS record. When you deploy 40 containers, you get 40 DNS records. Zero manual work.

```
Container starts → Traefik label detected → Cloudflare CNAME created → Done
```

## Quick Start

### Docker Compose (recommended)

```yaml
services:
  cf-companion:
    image: smashingtags/cf-companion:latest
    container_name: cf-companion
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    group_add:
      - ${DOCKER_GID:-999}  # Run: echo "DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)" >> .env
    environment:
      - CF_TOKEN=your-cloudflare-api-token
      - TARGET_DOMAIN=your-server.example.com
      - DOMAIN1=example.com
      - DOMAIN1_ZONE_ID=your-zone-id
      - DOMAIN1_PROXIED=TRUE
      - TRAEFIK_VERSION=2
    networks:
      - proxy

networks:
  proxy:
    external: true
```

```bash
docker compose up -d
```

That's it. Every container with a Traefik `Host()` label now gets automatic DNS.

### Docker Run

```bash
docker run -d \
  --name cf-companion \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --group-add $(stat -c '%g' /var/run/docker.sock) \
  -e CF_TOKEN=your-cloudflare-api-token \
  -e TARGET_DOMAIN=your-server.example.com \
  -e DOMAIN1=example.com \
  -e DOMAIN1_ZONE_ID=your-zone-id \
  -e DOMAIN1_PROXIED=TRUE \
  -e TRAEFIK_VERSION=2 \
  --network proxy \
  smashingtags/cf-companion:latest
```

> **Note:** The `--group-add` flag is required because the container runs as a non-root user. Without it, you'll get a `PermissionError(13, 'Permission denied')` when the container tries to access the Docker socket.

### Available Images

| Registry | Image |
|----------|-------|
| Docker Hub | `smashingtags/cf-companion:latest` |
| GHCR | `ghcr.io/smashingtags/cf-companion:latest` |

Multi-arch: `linux/amd64` and `linux/arm64`.

## How It Works

1. **Startup scan** — discovers all running containers with Traefik routing labels
2. **Event watch** — listens to Docker events for new container starts
3. **Label extraction** — parses `Host()` rules from Traefik v1 or v2 labels
4. **DNS sync** — creates or updates CNAME records in Cloudflare via API
5. **Idempotent** — existing records are left alone, only missing ones are created

Supports:
- Traefik v1 and v2 label formats
- Multiple domains (DOMAIN1, DOMAIN2, DOMAIN3...)
- Docker Swarm service discovery
- Traefik API polling (alternative to Docker socket)
- Excluded subdomains
- Dry run mode
- Proxied and unproxied records

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CF_TOKEN` | *required* | Cloudflare API token (DNS edit permission) |
| `CF_EMAIL` | | Cloudflare email (for global API key auth) |
| `TARGET_DOMAIN` | *required* | CNAME target (where records point) |
| `DOMAIN1` | *required* | First domain to manage |
| `DOMAIN1_ZONE_ID` | *required* | Cloudflare Zone ID for DOMAIN1 |
| `DOMAIN1_PROXIED` | `FALSE` | Enable Cloudflare proxy (orange cloud) |
| `DOMAIN1_TTL` | `1` | TTL (1 = auto) |
| `DOMAIN1_EXCLUDED_SUB_DOMAINS` | | Comma-separated subdomains to skip |
| `DOMAIN2`, `DOMAIN3`, ... | | Additional domains (same pattern) |
| `TRAEFIK_VERSION` | `2` | Traefik version (1 or 2) |
| `DRY_RUN` | `FALSE` | Log actions without making changes |
| `REFRESH_ENTRIES` | `FALSE` | Update records even if target matches |
| `RC_TYPE` | `CNAME` | DNS record type |
| `DEFAULT_TTL` | `1` | Default TTL for all domains |
| `DOCKER_SWARM_MODE` | `FALSE` | Enable Swarm service discovery |
| `ENABLE_TRAEFIK_POLL` | `FALSE` | Poll Traefik API instead of Docker events |
| `TRAEFIK_POLL_URL` | | Traefik API URL (e.g., `http://traefik:8080`) |
| `TRAEFIK_POLL_SECONDS` | `60` | Polling interval |
| `LOG_LEVEL` | `INFO` | DEBUG, VERBOSE, or INFO |
| `LOG_TYPE` | `BOTH` | CONSOLE, FILE, or BOTH |

## Getting a Cloudflare API Token

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. **Create Token** > Use the **Edit zone DNS** template
3. Zone Resources: **Include** > **Specific zone** > select your domain
4. Copy the token

## Getting Your Zone ID

Your Zone ID is on the right sidebar of your domain's **Overview** page in Cloudflare.

## Multiple Domains

```yaml
environment:
  - DOMAIN1=example.com
  - DOMAIN1_ZONE_ID=abc123
  - DOMAIN1_PROXIED=TRUE
  - DOMAIN2=otherdomain.com
  - DOMAIN2_ZONE_ID=def456
  - DOMAIN2_PROXIED=FALSE
```

## What Changed From Upstream

This is a modernized fork of [tiredofit/docker-traefik-cloudflare-companion](https://github.com/tiredofit/docker-traefik-cloudflare-companion). We rewrote the packaging:

| | Upstream | CF Companion |
|---|---|---|
| Base image | Proprietary `tiredofit/alpine` (~200MB) | `python:3.12-alpine` (~50MB) |
| Init system | Custom s6-overlay with shell wrappers | Direct Python entrypoint |
| Registry | Docker Hub only | Docker Hub + GHCR |
| Architectures | amd64 only | amd64 + arm64 |
| CI/CD | Custom | GitHub Actions |
| Maintenance | Last updated April 2025 | Actively maintained |

The core Python logic is the same proven code — we just stripped out the unnecessary complexity around it.

## Part of the Ecosystem

CF Companion is built by [Imogen Labs](https://imogenlabs.ai) and pairs perfectly with:

- **[HomelabARR CE](https://github.com/smashingtags/homelabarr-ce)** — GUI Docker container management (157 apps)
- **[HomelabARR](https://homelabarr.com)** — The homelab platform

Deploy containers from the HomelabARR dashboard, CF Companion handles the DNS. Fully automatic.

## Troubleshooting

### `PermissionError(13, 'Permission denied')` on startup

The container runs as a non-root user and needs access to the Docker socket. Add `group_add` with your host's Docker socket GID:

```yaml
services:
  cf-companion:
    group_add:
      - ${DOCKER_GID:-999}
```

Then set the variable:

```bash
echo "DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)" >> .env
```

*Thanks to [@cyb3rgh05t](https://github.com/cyb3rgh05t) for reporting this issue.*

### `Unable to authenticate request` (Error 10001)

The new Cloudflare SDK requires `CF_TOKEN` (scoped API token), **not** the legacy `CF_EMAIL` + `CF_API_KEY` combo. If you're migrating from the upstream image or DockServer:

```yaml
# ❌ Old (won't work)
- CLOUDFLARE_EMAIL=you@example.com
- CLOUDFLARE_API_KEY=your-global-key

# ✅ New
- CF_TOKEN=your-scoped-api-token
```

Create a scoped token with **Edit zone DNS** permission — see [Getting a Cloudflare API Token](#getting-a-cloudflare-api-token) above.

> **Note:** Global API key auth (`CF_EMAIL` + `CF_API_KEY`) is still supported but `CF_TOKEN` is recommended. If using global keys, make sure the env var names are `CF_EMAIL` and `CF_API_KEY` (not `CLOUDFLARE_EMAIL` / `CLOUDFLARE_API_KEY`).

*Thanks to [@cyb3rgh05t](https://github.com/cyb3rgh05t) for reporting this issue.*

### Container starts but no DNS records are created

1. Check `LOG_LEVEL=DEBUG` to see what labels are being detected
2. Verify your containers have Traefik `Host()` labels
3. Confirm `DOMAIN1` matches the domain in your Host rules
4. Make sure your API token has **Edit** permission on DNS for the zone

### Records created with wrong target

Set `TARGET_DOMAIN` to your server's public hostname or IP. All CNAME records will point here.

## Contributors

<a href="https://github.com/smashingtags"><img src="https://avatars.githubusercontent.com/u/5765990?v=4" width="50" height="50" style="border-radius:50%" alt="smashingtags"></a>
<a href="https://github.com/cyb3rgh05t"><img src="https://avatars.githubusercontent.com/u/5200101?v=4" width="50" height="50" style="border-radius:50%" alt="cyb3rgh05t"></a>

## Community

- [Discord](https://discord.gg/Pc7mXX786x) — Get help, share your setup
- [Reddit](https://www.reddit.com/r/homelabarr/) — r/homelabarr
- [X/Twitter](https://twitter.com/Imogen_Labs) — @Imogen_Labs
- [Ko-fi](https://ko-fi.com/homelabarr) — Support the project

## License

MIT. Original project by [Dave Conroy / tiredofit](https://github.com/tiredofit).
