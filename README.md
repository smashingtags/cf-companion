# cf-companion

Auto-create Cloudflare DNS records when Docker containers with Traefik labels start. By [Imogen Labs](https://agents.imogenlabs.ai).

Based on [tiredofit/docker-traefik-cloudflare-companion](https://github.com/tiredofit/docker-traefik-cloudflare-companion). Modernized to remove proprietary base image dependency.

## What it does

When a container starts with Traefik routing labels like:

```yaml
labels:
  - "traefik.http.routers.myapp.rule=Host(`myapp.example.com`)"
```

This companion container automatically creates a CNAME record in Cloudflare pointing `myapp.example.com` to your server.

## Quick Start

```yaml
services:
  cf-companion:
    image: ghcr.io/smashingtags/cf-companion:latest
    container_name: cf-companion
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
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

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CF_TOKEN` | *required* | Cloudflare API token (needs DNS edit permission) |
| `CF_EMAIL` | | Cloudflare email (for global API key auth instead of token) |
| `TARGET_DOMAIN` | *required* | CNAME target (where records point to) |
| `DOMAIN1` | *required* | First domain to manage |
| `DOMAIN1_ZONE_ID` | *required* | Cloudflare Zone ID for DOMAIN1 |
| `DOMAIN1_PROXIED` | `FALSE` | Enable Cloudflare proxy (orange cloud) |
| `DOMAIN1_TTL` | `1` | TTL (1 = auto) |
| `DOMAIN1_EXCLUDED_SUB_DOMAINS` | | Comma-separated list of subdomains to skip |
| `DOMAIN2`, `DOMAIN3`, ... | | Additional domains (same pattern) |
| `TRAEFIK_VERSION` | `2` | Traefik version (1 or 2) |
| `DRY_RUN` | `FALSE` | Log what would happen without making changes |
| `REFRESH_ENTRIES` | `FALSE` | Update existing records even if target matches |
| `RC_TYPE` | `CNAME` | DNS record type to create |
| `DEFAULT_TTL` | `1` | Default TTL for all domains |
| `DOCKER_SWARM_MODE` | `FALSE` | Enable Docker Swarm service discovery |
| `ENABLE_TRAEFIK_POLL` | `FALSE` | Poll Traefik API instead of Docker events |
| `TRAEFIK_POLL_URL` | | Traefik API URL (e.g., `http://traefik:8080`) |
| `TRAEFIK_POLL_SECONDS` | `60` | Polling interval |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, VERBOSE, INFO) |
| `LOG_TYPE` | `BOTH` | Where to log (CONSOLE, FILE, BOTH) |

## Getting a Cloudflare API Token

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Create Token > Edit zone DNS template
3. Zone Resources: Include > Specific zone > your domain
4. Copy the token

## Getting Your Zone ID

Your Zone ID is on the right sidebar of your domain's overview page in Cloudflare.

## Changes from upstream

- Replaced proprietary `tiredofit/alpine` base image with standard `python:3.12-alpine`
- Removed custom init system (s6-overlay, cont-init.d, services.available)
- Direct Python entrypoint — no shell wrappers
- Published to GHCR instead of Docker Hub
- GitHub Actions CI/CD

## Credits

Original project by [Dave Conroy / tiredofit](https://github.com/tiredofit). Licensed under MIT.
