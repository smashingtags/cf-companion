# CF Companion — FAQ & Troubleshooting

## Permission denied when accessing Docker socket

**Error:**
```
requests.exceptions.ConnectionError: ('Connection aborted.', PermissionError(13, 'Permission denied'))
```

**Cause:** The container runs as a non-root user (`cfcompanion`) and doesn't have permission to access the Docker socket.

**Fix:** Add `--group-add` to your `docker run` command:
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
  --network proxy \
  smashingtags/cf-companion:latest
```

For Docker Compose, add `group_add` to your service:
```yaml
services:
  cf-companion:
    image: smashingtags/cf-companion:latest
    group_add:
      - ${DOCKER_GID:-999}
```
Then set the variable: `echo "DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)" >> .env`

---

## Unable to authenticate request (restart loop)

**Error:**
```
cloudflare.BadRequestError: Error code: 400 - {'success': False, 'errors': [{'code': 10001, 'message': 'Unable to authenticate request'}]}
```

**Cause:** Your Cloudflare API credentials are invalid or don't have the right permissions. The container crashes on startup, Docker restarts it, it crashes again — infinite loop.

**Stop the loop first:**
```bash
docker stop cf-companion
```

**Fix Option 1 — Use Global API Key (easiest):**

Replace `CF_TOKEN` with these two variables:
```
-e CLOUDFLARE_EMAIL=your@email.com
-e CLOUDFLARE_API_KEY=your_global_api_key
```
Get the Global API Key from: **Cloudflare Dashboard → My Profile → API Tokens → Global API Key → View**

**Fix Option 2 — Fix your API Token permissions:**

If you prefer scoped tokens (`CF_TOKEN`), create one with these permissions:
- Zone → DNS → Edit
- Zone → Zone → Read
- Zone Resources → Include → Specific zone → your domain

Create at: **Cloudflare Dashboard → My Profile → API Tokens → Create Token**

**Also check your Zone ID:**

Make sure `DOMAIN1_ZONE_ID` matches your domain. Find it at: **Cloudflare Dashboard → your domain → Overview → right sidebar → "Zone ID"**

---

## Container discovers services but doesn't create DNS records

**Cause:** Usually a zone ID mismatch. The container finds your Traefik containers but can't create records because the zone ID doesn't match the domain.

**Fix:** Verify your `DOMAIN1_ZONE_ID` matches the zone for `DOMAIN1`:
```bash
# Get zone ID from Cloudflare API
curl -s "https://api.cloudflare.com/client/v4/zones?name=yourdomain.com" \
  -H "Authorization: Bearer YOUR_CF_TOKEN" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result'][0]['id'])"
```

---

## Records created but site shows Cloudflare error (522/521)

**Cause:** DNS record points to the wrong IP, or the container isn't on the same Docker network as Traefik.

**Fix:**
1. Make sure `TARGET_DOMAIN` resolves to your server's public IP
2. Make sure the container is on the same Docker network as Traefik (usually `proxy`)
3. If using Cloudflare proxy (orange cloud), make sure your origin server accepts HTTPS or set SSL mode to "Flexible"

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `CF_TOKEN` | Yes* | Cloudflare API Token (scoped) |
| `CLOUDFLARE_EMAIL` | Yes* | Cloudflare account email (use with `CLOUDFLARE_API_KEY`) |
| `CLOUDFLARE_API_KEY` | Yes* | Cloudflare Global API Key (use with `CLOUDFLARE_EMAIL`) |
| `TARGET_DOMAIN` | Yes | Domain that DNS records should point to |
| `DOMAIN1` | Yes | First domain to manage |
| `DOMAIN1_ZONE_ID` | Yes | Cloudflare Zone ID for DOMAIN1 |
| `DOMAIN1_PROXIED` | No | Enable Cloudflare proxy (default: TRUE) |
| `TRAEFIK_VERSION` | No | Traefik version: 1 or 2 (default: 2) |
| `DOMAIN2`, `DOMAIN2_ZONE_ID` | No | Additional domains (DOMAIN3, DOMAIN4, etc.) |

*Use either `CF_TOKEN` OR both `CLOUDFLARE_EMAIL` + `CLOUDFLARE_API_KEY`. Not both.
