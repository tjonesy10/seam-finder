#!/usr/bin/env bash
# Install the lockfile's Playwright Chromium and its apt packages.
#
# GitHub-hosted runners stay in place. The visual job is pinned to
# ubuntu-24.04 so F010/F011 screenshot baselines keep the same font
# rasterization. This script only makes the existing install survive a
# transient Ubuntu mirror or DNS outage: apt retries inside one attempt,
# then the install commands retry with backoff.
set -euo pipefail

MAX_ATTEMPTS="${PLAYWRIGHT_INSTALL_ATTEMPTS:-4}"
INITIAL_DELAY="${PLAYWRIGHT_INSTALL_RETRY_DELAY:-20}"

retry() {
  local max_attempts="$1"
  local delay="$2"
  shift 2
  local attempt=1
  local status=0
  while true; do
    if "$@"; then
      echo "succeeded on attempt ${attempt}/${max_attempts}: $*"
      return 0
    else
      status=$?
    fi
    if [[ "$attempt" -ge "$max_attempts" ]]; then
      echo "failed after ${attempt} attempts (exit ${status}): $*" >&2
      return "$status"
    fi
    echo "attempt ${attempt}/${max_attempts} failed (exit ${status}); retrying in ${delay}s: $*" >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    if [[ "$delay" -lt 120 ]]; then
      delay=$((delay * 2))
    fi
  done
}

configure_apt_retries() {
  local conf="/etc/apt/apt.conf.d/80-playwright-retries"
  local body
  body="$(cat <<'EOF'
Acquire::Retries "5";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
EOF
)"
  if [[ "${EUID}" -eq 0 ]]; then
    printf '%s\n' "$body" >"$conf"
    chmod 644 "$conf"
  else
    printf '%s\n' "$body" | sudo tee "$conf" >/dev/null
    sudo chmod 644 "$conf"
  fi
  echo "wrote ${conf}"
  cat "$conf"
}

main() {
  local repo_root
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  cd "${repo_root}/frontend"
  configure_apt_retries
  retry "$MAX_ATTEMPTS" "$INITIAL_DELAY" npx playwright install chromium
  retry "$MAX_ATTEMPTS" "$INITIAL_DELAY" npx playwright install-deps chromium
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
