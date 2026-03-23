# Security Policy

## Supported Versions

Only the latest release is supported.

| Version | Supported |
|---------|-----------|
| Latest (`main` branch) | Yes |
| Older versions | No |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Report security issues privately:

- **Email:** michael@mjashley.com
- **Subject line:** `[SECURITY] cf-companion — <brief description>`

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

### Response timeline

- **Acknowledgment:** Within 48 hours
- **Fix (critical):** Within 72 hours of confirmation
- **Fix (high):** Within 2 weeks
- **Fix (medium/low):** Next release cycle

### What happens next

1. We confirm receipt and begin investigation
2. We work on a fix in a private branch
3. We release a patched version
4. We publicly disclose the vulnerability after the fix is available
5. We credit the reporter (unless they prefer anonymity)

## Security Considerations

### Docker Socket

CF Companion requires read-only access to the Docker socket to watch container events. Always mount it read-only:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

### Cloudflare API Token

- Use a **scoped API token** with DNS edit permission on specific zones only — not a global API key
- Store tokens in environment variables or Docker secrets, never in compose files committed to version control
- The `CF_TOKEN` / `CF_EMAIL` variables are passed to the Cloudflare SDK and never logged

### Network

- CF Companion does not expose any ports or HTTP endpoints
- It only makes outbound API calls to `api.cloudflare.com`
- Run it on the same Docker network as Traefik (`proxy`)

## Scope

This policy covers the CF Companion application code and Docker images. It does not cover:

- The Cloudflare API or dashboard
- Traefik or other reverse proxies
- Your server's OS or network configuration

## Acknowledgments

We appreciate responsible disclosure and will credit security researchers who report valid vulnerabilities.
