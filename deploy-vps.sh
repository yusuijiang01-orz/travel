#!/usr/bin/env bash
# Public one-command installer for the family-trip path deployment.
# Usage: curl -fsSL https://raw.githubusercontent.com/yusuijiang01-orz/travel/main/deploy-vps.sh | sudo bash
set -Eeuo pipefail

if [[ $EUID -ne 0 ]]; then
  echo 'Run with sudo, for example: curl -fsSL https://raw.githubusercontent.com/yusuijiang01-orz/travel/main/deploy-vps.sh | sudo bash' >&2
  exit 1
fi
if [[ ! -r /etc/os-release ]]; then echo 'Cannot identify this operating system.' >&2; exit 1; fi
source /etc/os-release
case "$ID" in debian|ubuntu) ;; *) echo 'Supported systems: Debian or Ubuntu.' >&2; exit 1;; esac

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl git

project_dir=/opt/family-travel
repo=https://github.com/yusuijiang01-orz/travel.git
if [[ -e "$project_dir" && ! -d "$project_dir/.git" ]]; then
  echo "$project_dir exists but is not a Git checkout; stopping without changing it." >&2
  exit 1
fi
if [[ -d "$project_dir/.git" ]]; then
  git -C "$project_dir" remote get-url origin | grep -Fxq "$repo" || { echo "A different Git repository already exists at $project_dir; stopping." >&2; exit 1; }
  git -C "$project_dir" fetch --quiet origin main
  git -C "$project_dir" merge --ff-only FETCH_HEAD
else
  git clone --quiet --depth 1 --branch main "$repo" "$project_dir"
fi

cd "$project_dir"
deployment_failed() {
  local status=$?
  trap - ERR
  printf '\nDeployment failed (exit %s). Read-only VPS diagnosis follows:\n' "$status" >&2
  if [[ -f "$project_dir/diagnose-vps.sh" ]]; then
    bash "$project_dir/diagnose-vps.sh" || true
  else
    echo 'Diagnosis script is missing from the pulled project.' >&2
  fi
  exit "$status"
}
trap deployment_failed ERR
bash deploy.sh --mode path --base-path /family-trip --port 3100 --origin https://travel.lovenom.eu.org --auto-proxy
