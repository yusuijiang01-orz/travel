#!/usr/bin/env bash
# Read-only diagnosis. Deliberately omits .env, process environments, and credentials.
set -u
echo '=== OS ==='
grep -E '^(ID|VERSION_ID)=' /etc/os-release 2>/dev/null || true
echo '=== Domain ==='
getent ahosts travel.lovenom.eu.org 2>/dev/null | awk '{print $1}' | sort -u | head -5 || true
echo '=== Services ==='
for service in nginx caddy docker; do printf '%s: ' "$service"; systemctl is-active "$service" 2>/dev/null || true; done
echo '=== Listening ports ==='
ss -ltnp 2>/dev/null | awk 'NR == 1 || /:(80|443|3100)([[:space:]]|$)/' || true
echo '=== Docker containers ==='
if command -v docker >/dev/null 2>&1; then docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | head -15; else echo 'docker not installed'; fi
echo '=== Travel app ==='
if [[ -d /opt/family-travel ]]; then
  git -C /opt/family-travel status -sb 2>/dev/null || true
  (cd /opt/family-travel && docker compose -f compose.path.yaml ps 2>/dev/null) || true
  curl -sS -o /dev/null -w 'Local health HTTP %{http_code}\n' --max-time 5 http://127.0.0.1:3100/family-trip/api/health 2>/dev/null || true
else echo '/opt/family-travel is not present'; fi
echo '=== Proxy config validation ==='
if systemctl is-active --quiet nginx && command -v nginx >/dev/null; then nginx -t 2>&1 | tail -5; fi
if systemctl is-active --quiet caddy && command -v caddy >/dev/null; then caddy validate --config /etc/caddy/Caddyfile 2>&1 | tail -5; fi
curl -sS -o /dev/null -w 'Public health HTTP %{http_code}\n' --max-time 10 https://travel.lovenom.eu.org/family-trip/api/health 2>/dev/null || true
