#!/usr/bin/env bash
# Run from an uploaded travel project on a Debian/Ubuntu VPS: sudo bash deploy.sh
set -Eeuo pipefail
trap 'printf "Deployment stopped at line %s. Fix the reported cause and rerun.\n" "$LINENO" >&2' ERR
export DEBIAN_FRONTEND=noninteractive
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $EUID -ne 0 ]]; then printf 'Run with sudo bash deploy.sh\n' >&2; exit 1; fi
if [[ ! -f compose.yaml || ! -f server.mjs ]]; then printf 'Upload the full travel project first.\n' >&2; exit 1; fi
if [[ ! -r /etc/os-release ]]; then printf 'Debian or Ubuntu is required.\n' >&2; exit 1; fi
source /etc/os-release
case "$ID" in debian|ubuntu) ;; *) printf 'Supported systems: Debian/Ubuntu.\n' >&2; exit 1;; esac

# Never execute the .env file as shell code. Accept only these two plain values.
if [[ -f .env ]]; then
  while IFS='=' read -r key value; do
    value=${value%$'\r'}
    case "$key" in TRAVEL_DOMAIN) TRAVEL_DOMAIN=${TRAVEL_DOMAIN:-$value};; ACME_EMAIL) ACME_EMAIL=${ACME_EMAIL:-$value};; esac
  done < .env
fi
TRAVEL_DOMAIN=${TRAVEL_DOMAIN:-travel.lovenom.eu.org}
if [[ ! "$TRAVEL_DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ || "$TRAVEL_DOMAIN" != *.* ]]; then
  printf 'Invalid domain. Use a plain hostname.\n' >&2; exit 1
fi
if [[ -z ${ACME_EMAIL:-} || ${ACME_EMAIL:-} == 'you@example.com' ]]; then
  read -r -p 'Email for HTTPS certificate notices: ' ACME_EMAIL
fi
if [[ ! "$ACME_EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
  printf 'A valid email is required.\n' >&2; exit 1
fi

apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl dnsutils iproute2 python3
host_ipv4=$(curl -4 --fail --silent --show-error --max-time 15 https://api.ipify.org)
if [[ ! "$host_ipv4" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then printf 'Cannot determine public IPv4.\n' >&2; exit 1; fi
dns_records=$(dig +short A "$TRAVEL_DOMAIN" @1.1.1.1 | awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/')
if [[ -z "$dns_records" ]]; then printf 'Create a DNS A record for %s pointing to %s, then rerun.\n' "$TRAVEL_DOMAIN" "$host_ipv4" >&2; exit 1; fi
while IFS= read -r address; do
  if [[ "$address" != "$host_ipv4" ]]; then
    printf 'DNS A record %s points to %s; this VPS is %s. Set DNS-only mode, fix DNS and rerun.\n' "$TRAVEL_DOMAIN" "$address" "$host_ipv4" >&2; exit 1
  fi
done <<< "$dns_records"
dns_ipv6=$(dig +short AAAA "$TRAVEL_DOMAIN" @1.1.1.1 | awk '/:/')
if [[ -n "$dns_ipv6" ]]; then
  host_ipv6=$(curl -6 --fail --silent --max-time 10 https://api6.ipify.org || true)
  if [[ -z "$host_ipv6" ]]; then printf 'AAAA exists but this VPS has no confirmed public IPv6. Remove AAAA or configure IPv6.\n' >&2; exit 1; fi
  # Normalize compressed IPv6 addresses before comparing them.
  while IFS= read -r address; do
    if [[ "$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_address(sys.argv[1]))' "$address")" != "$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_address(sys.argv[1]))' "$host_ipv6")" ]]; then
      printf 'AAAA does not point to this VPS. Fix/remove it and rerun.\n' >&2; exit 1
    fi
  done <<< "$dns_ipv6"
fi
printf 'DNS verified: %s -> %s\n' "$TRAVEL_DOMAIN" "$host_ipv4"
printf 'Inbound TCP 80 and 443 must be open in BOTH your provider firewall and OS firewall. UDP 443 is optional for HTTP/3.\n'
printf 'The script does not modify your firewall or stop existing websites.\n'

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  # Install Docker through its official signed Debian/Ubuntu apt repository.
  install -m 0755 -d /etc/apt/keyrings
  curl --fail --silent --show-error "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  architecture=$(dpkg --print-architecture)
  codename=${VERSION_CODENAME:?OS codename unavailable}
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' "$architecture" "$ID" "$codename" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
export TRAVEL_DOMAIN ACME_EMAIL
existing_caddy=$(docker compose ps -q caddy 2>/dev/null || true)
if [[ -z "$existing_caddy" ]] && [[ -n "$(ss -H -ltn 'sport = :80 or sport = :443')" ]]; then
  printf 'Port 80/443 is already in use. Add this site to the existing reverse proxy or free the ports before deploying.\n' >&2; exit 1
fi
umask 077
printf 'TRAVEL_DOMAIN=%s\nACME_EMAIL=%s\n' "$TRAVEL_DOMAIN" "$ACME_EMAIL" > .env
docker compose up --build -d --wait --wait-timeout 180
printf 'Containers started. Waiting for DNS-based automatic HTTPS issuance...\n'
for attempt in {1..30}; do
  if curl --fail --silent --show-error --max-time 10 "https://$TRAVEL_DOMAIN/api/health" >/dev/null 2>&1; then
    printf '\nReady: https://%s\nVotes are stored in the family-travel_votes Docker volume.\n' "$TRAVEL_DOMAIN"; exit 0
  fi
  sleep 5
done
printf 'Containers are running, but HTTPS is not confirmed. Check firewall 80/443 and run: docker compose logs --tail=80 caddy app\n' >&2
exit 1
