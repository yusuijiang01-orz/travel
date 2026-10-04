#!/usr/bin/env bash
# Standalone: sudo bash deploy.sh
# Existing proxy: sudo bash deploy.sh --mode path --base-path /test --port 3100
set -Eeuo pipefail
trap 'printf "Deployment stopped at line %s. Fix the reported cause and rerun.\n" "$LINENO" >&2' ERR
export DEBIAN_FRONTEND=noninteractive
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

usage() {
  printf '%s\n' 'Usage: sudo bash deploy.sh [--mode standalone|path] [--base-path /test] [--port 3100] [--origin https://domain] [--domain domain]'
  printf '%s\n' 'path starts only the app on loopback. Add proxy/nginx-test.conf or proxy/caddy-test.caddy to your existing TLS proxy.'
}
if [[ ${1:-} == --help ]]; then usage; exit 0; fi
if [[ $EUID -ne 0 ]]; then printf 'Run with sudo bash deploy.sh\n' >&2; exit 1; fi
if [[ ! -f compose.yaml || ! -f compose.path.yaml || ! -f server.mjs ]]; then printf 'Upload the full travel project first.\n' >&2; exit 1; fi
if [[ ! -r /etc/os-release ]]; then printf 'Debian or Ubuntu is required.\n' >&2; exit 1; fi
source /etc/os-release
case "$ID" in debian|ubuntu) ;; *) printf 'Supported systems: Debian/Ubuntu.\n' >&2; exit 1;; esac

# Read only known plain values. Never execute .env as shell code.
if [[ -f .env ]]; then
  while IFS='=' read -r key value; do
    value=${value%$'\r'}
    case "$key" in
      TRAVEL_DOMAIN) TRAVEL_DOMAIN=${TRAVEL_DOMAIN:-$value};;
      ACME_EMAIL) ACME_EMAIL=${ACME_EMAIL:-$value};;
      DEPLOY_MODE) DEPLOY_MODE=${DEPLOY_MODE:-$value};;
      BASE_PATH) BASE_PATH=${BASE_PATH:-$value};;
      APP_PORT) APP_PORT=${APP_PORT:-$value};;
      PUBLIC_ORIGIN) PUBLIC_ORIGIN=${PUBLIC_ORIGIN:-$value};;
    esac
  done < .env
fi
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode|--base-path|--port|--origin|--domain)
      if [[ $# -lt 2 ]]; then usage >&2; exit 1; fi
      case "$1" in
        --mode) DEPLOY_MODE=$2;; --base-path) BASE_PATH=$2;; --port) APP_PORT=$2;;
        --origin) PUBLIC_ORIGIN=$2;; --domain) TRAVEL_DOMAIN=$2;;
      esac
      shift 2;;
    *) usage >&2; exit 1;;
  esac
done
DEPLOY_MODE=${DEPLOY_MODE:-standalone}
TRAVEL_DOMAIN=${TRAVEL_DOMAIN:-travel.lovenom.eu.org}
APP_PORT=${APP_PORT:-3100}
case "$DEPLOY_MODE" in
  standalone) BASE_PATH=${BASE_PATH:-};;
  path) BASE_PATH=${BASE_PATH:-/test};;
  *) printf 'Mode must be standalone or path.\n' >&2; exit 1;;
esac
BASE_PATH=${BASE_PATH%/}
if [[ ! "$TRAVEL_DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ || "$TRAVEL_DOMAIN" != *.* ]]; then
  printf 'Invalid domain. Use a plain hostname.\n' >&2; exit 1
fi
if [[ -n "$BASE_PATH" && ! "$BASE_PATH" =~ ^/([A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+$ ]]; then
  printf 'BASE_PATH must be empty or a path such as /test.\n' >&2; exit 1
fi
if [[ "$DEPLOY_MODE" == path && -z "$BASE_PATH" ]]; then printf 'Path mode requires a nonempty path.\n' >&2; exit 1; fi
if [[ ! "$APP_PORT" =~ ^[1-9][0-9]{3,4}$ ]] || (( APP_PORT < 1024 || APP_PORT > 65535 )); then
  printf 'Choose an unused high port between 1024 and 65535.\n' >&2; exit 1
fi
PUBLIC_ORIGIN=${PUBLIC_ORIGIN:-https://$TRAVEL_DOMAIN}
PUBLIC_ORIGIN=${PUBLIC_ORIGIN%/}
if [[ ! "$PUBLIC_ORIGIN" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$ ]]; then
  printf 'PUBLIC_ORIGIN must be the existing public origin, for example https://travel.lovenom.eu.org, without /test.\n' >&2; exit 1
fi
if [[ "$DEPLOY_MODE" == standalone ]]; then
  PUBLIC_ORIGIN=https://$TRAVEL_DOMAIN
  if [[ -z ${ACME_EMAIL:-} || ${ACME_EMAIL:-} == 'you@example.com' ]]; then
    read -r -p 'Email for HTTPS certificate notices: ' ACME_EMAIL
  fi
  if [[ ! "$ACME_EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
    printf 'A valid email is required for standalone HTTPS.\n' >&2; exit 1
  fi
fi

apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl iproute2
if [[ "$DEPLOY_MODE" == standalone ]]; then
  apt-get install -y --no-install-recommends dnsutils python3
  host_ipv4=$(curl -4 --fail --silent --show-error --max-time 15 https://api.ipify.org)
  if [[ ! "$host_ipv4" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then printf 'Cannot determine public IPv4.\n' >&2; exit 1; fi
  dns_records=$(dig +short A "$TRAVEL_DOMAIN" @1.1.1.1 | awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/')
  if [[ -z "$dns_records" ]]; then printf 'Create a DNS A record for %s pointing to %s, then rerun.\n' "$TRAVEL_DOMAIN" "$host_ipv4" >&2; exit 1; fi
  while IFS= read -r address; do
    if [[ "$address" != "$host_ipv4" ]]; then
      printf 'DNS %s points to %s; this VPS is %s. Fix DNS and rerun.\n' "$TRAVEL_DOMAIN" "$address" "$host_ipv4" >&2; exit 1
    fi
  done <<< "$dns_records"
  dns_ipv6=$(dig +short AAAA "$TRAVEL_DOMAIN" @1.1.1.1 | awk '/:/')
  if [[ -n "$dns_ipv6" ]]; then
    host_ipv6=$(curl -6 --fail --silent --max-time 10 https://api6.ipify.org || true)
    if [[ -z "$host_ipv6" ]]; then printf 'AAAA exists but no public IPv6 is confirmed. Fix/remove AAAA.\n' >&2; exit 1; fi
    while IFS= read -r address; do
      if [[ "$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_address(sys.argv[1]))' "$address")" != "$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_address(sys.argv[1]))' "$host_ipv6")" ]]; then
        printf 'AAAA does not point to this VPS. Fix/remove it and rerun.\n' >&2; exit 1
      fi
    done <<< "$dns_ipv6"
  fi
  printf 'DNS verified: %s -> %s\nInbound TCP 80/443 must be open in provider and OS firewalls.\n' "$TRAVEL_DOMAIN" "$host_ipv4"
else
  printf 'Path mode: existing proxy keeps DNS/TLS and ports 80/443. This app will bind only 127.0.0.1:%s.\n' "$APP_PORT"
fi

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl --fail --silent --show-error "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  architecture=$(dpkg --print-architecture)
  codename=${VERSION_CODENAME:?OS codename unavailable}
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' "$architecture" "$ID" "$codename" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  if command -v docker >/dev/null; then
    # Preserve a running engine and its existing services; only add Compose.
    apt-get install -y --no-install-recommends docker-compose-plugin
  else
    apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
fi
if ! docker info >/dev/null 2>&1; then systemctl enable --now docker; fi
export TRAVEL_DOMAIN PUBLIC_ORIGIN BASE_PATH APP_PORT
export ACME_EMAIL=${ACME_EMAIL:-}
if [[ "$DEPLOY_MODE" == path ]]; then
  compose=(docker compose -f compose.path.yaml)
  existing_app=$("${compose[@]}" ps -q app 2>/dev/null || true)
  existing_port=''
  if [[ -n "$existing_app" ]]; then
    existing_port=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "3000/tcp") 0).HostPort}}' "$existing_app" 2>/dev/null || true)
  fi
  if [[ -n "$(ss -H -ltn "sport = :$APP_PORT")" && "$existing_port" != "$APP_PORT" ]]; then
    printf 'Port %s is occupied. Choose another --port and update the proxy snippet to match.\n' "$APP_PORT" >&2; exit 1
  fi
else
  compose=(docker compose -f compose.yaml)
  existing_caddy=$("${compose[@]}" ps -q caddy 2>/dev/null || true)
  if [[ -z "$existing_caddy" && -n "$(ss -H -ltn 'sport = :80 or sport = :443')" ]]; then
    printf 'Port 80/443 is occupied. Use --mode path and your existing proxy. No existing service was stopped.\n' >&2; exit 1
  fi
fi

# Preserve unrelated .env settings, update only the app deployment values.
umask 077
temp_env=$(mktemp .env.XXXXXX)
if [[ -f .env ]]; then awk '!/^(TRAVEL_DOMAIN|ACME_EMAIL|DEPLOY_MODE|BASE_PATH|APP_PORT|PUBLIC_ORIGIN)=/' .env > "$temp_env"; fi
printf 'DEPLOY_MODE=%s\nTRAVEL_DOMAIN=%s\nPUBLIC_ORIGIN=%s\nBASE_PATH=%s\nAPP_PORT=%s\nACME_EMAIL=%s\n' "$DEPLOY_MODE" "$TRAVEL_DOMAIN" "$PUBLIC_ORIGIN" "$BASE_PATH" "$APP_PORT" "$ACME_EMAIL" >> "$temp_env"
mv -- "$temp_env" .env
"${compose[@]}" up --build -d --wait --wait-timeout 180
if [[ "$DEPLOY_MODE" == path ]]; then
  curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:$APP_PORT$BASE_PATH/api/health" >/dev/null
  printf '\nApp ready on loopback: http://127.0.0.1:%s%s/\n' "$APP_PORT" "$BASE_PATH"
  printf 'Public target: %s%s/ (existing proxy configuration still required).\n' "$PUBLIC_ORIGIN" "$BASE_PATH"
  printf 'Add proxy/nginx-test.conf or proxy/caddy-test.caddy to your existing HTTPS site, matching path and port.\n'
  printf 'No proxy config was changed, no certificates were requested, and no existing service was stopped.\n'
  exit 0
fi
printf 'Containers started. Waiting for automatic HTTPS issuance...\n'
for attempt in {1..30}; do
  if curl --fail --silent --show-error --max-time 10 "$PUBLIC_ORIGIN$BASE_PATH/api/health" >/dev/null 2>&1; then
    printf '\nReady: %s%s/\nVotes: family-travel_votes Docker volume.\n' "$PUBLIC_ORIGIN" "$BASE_PATH"; exit 0
  fi
  sleep 5
done
printf 'HTTPS is not confirmed. Check firewall/DNS and run: docker compose logs --tail=80 caddy app\n' >&2
exit 1
