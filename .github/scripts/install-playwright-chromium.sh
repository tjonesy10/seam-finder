#!/usr/bin/env bash
# Install the lockfile's Playwright Chromium and its apt packages.
#
# GitHub-hosted runners stay in place. The visual job is pinned to
# ubuntu-24.04 so F010/F011 screenshot baselines keep the same font
# rasterization. Apt retries inside one attempt, then the install
# commands retry with backoff. When the runner's Ubuntu archive names
# do not resolve, apt is pointed at another mirror of the same archive
# so the retry does not spend ten minutes on dead DNS.
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

probe_host() {
  timeout 5 getent hosts "$1" >/dev/null 2>&1
}

archive_host() {
  local url="$1"
  url="${url#http://}"
  url="${url#https://}"
  url="${url%%/*}"
  printf '%s\n' "$url"
}

write_mirrors() {
  local conf="/etc/apt/apt-mirrors.txt"
  local body=""
  local priority=1
  local url
  for url in "$@"; do
    body+="${url}"$'\t'"priority:${priority}"$'\n'
    priority=$((priority + 1))
  done
  if [[ "${EUID}" -eq 0 ]]; then
    printf '%s' "$body" >"$conf"
  else
    printf '%s' "$body" | sudo tee "$conf" >/dev/null
  fi
  echo "wrote ${conf}:"
  cat "$conf"
}

# Return 0 when at least one mirror resolves. Leave the runner's mirror
# list untouched when azure, archive, and security all resolve.
select_ubuntu_mirrors() {
  local -a defaults=(
    "http://azure.archive.ubuntu.com/ubuntu/"
    "https://archive.ubuntu.com/ubuntu/"
    "https://security.ubuntu.com/ubuntu/"
  )
  local -a fallbacks=(
    "https://mirrors.kernel.org/ubuntu/"
    "https://mirrors.edge.kernel.org/ubuntu/"
    "https://mirror.csclub.uwaterloo.ca/ubuntu/"
    "https://mirrors.ocf.berkeley.edu/ubuntu/"
  )
  local -a chosen=()
  local url host
  for url in "${defaults[@]}"; do
    host="$(archive_host "$url")"
    if probe_host "$host"; then
      chosen+=("$url")
      echo "mirror dns ok: ${host}"
    else
      echo "mirror dns miss: ${host}"
    fi
  done
  if [[ "${#chosen[@]}" -eq 0 ]]; then
    echo "runner Ubuntu archive names did not resolve; probing fallbacks"
    for url in "${fallbacks[@]}"; do
      host="$(archive_host "$url")"
      if probe_host "$host"; then
        chosen+=("$url")
        echo "fallback dns ok: ${host}"
      else
        echo "fallback dns miss: ${host}"
      fi
    done
  fi
  if [[ "${#chosen[@]}" -eq 0 ]]; then
    echo "no Ubuntu mirror DNS yet"
    return 1
  fi
  if [[ "${#chosen[@]}" -eq ${#defaults[@]} ]]; then
    echo "keeping runner apt mirror list"
    return 0
  fi
  write_mirrors "${chosen[@]}"
}

install_chromium_deps() {
  if ! select_ubuntu_mirrors; then
    echo "skipping apt until a Ubuntu mirror resolves"
    return 100
  fi
  npx playwright install-deps chromium
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
  retry "$MAX_ATTEMPTS" "$INITIAL_DELAY" install_chromium_deps
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
