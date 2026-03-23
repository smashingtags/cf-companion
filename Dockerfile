FROM python:3.12-alpine

LABEL maintainer="Imogen Labs (github.com/smashingtags)"
LABEL org.opencontainers.image.source="https://github.com/smashingtags/cf-companion"
LABEL org.opencontainers.image.description="Auto-create Cloudflare DNS records for containers with Traefik labels"

RUN apk add --no-cache gcc musl-dev libffi-dev && \
    pip install --no-cache-dir \
        "docker>=7.0.0" \
        "cloudflare>=4.1.0,<5.0.0" \
        get-docker-secret \
        requests && \
    apk del gcc musl-dev libffi-dev

RUN addgroup -g 1001 -S cfcompanion && \
    adduser -S cfcompanion -u 1001 -G cfcompanion && \
    mkdir -p /logs && chown cfcompanion:cfcompanion /logs

COPY app/cloudflare-companion.py /app/cloudflare-companion.py

USER cfcompanion

ENTRYPOINT ["python3", "-u", "/app/cloudflare-companion.py"]
