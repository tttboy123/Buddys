#!/usr/bin/env bash
set -euo pipefail

is_public_ipv4() {
  local candidate="${1:-}"
  [[ "${candidate}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  IFS=. read -r o1 o2 o3 o4 <<<"${candidate}"
  for octet in "$o1" "$o2" "$o3" "$o4"; do
    [[ "${octet}" =~ ^[0-9]+$ ]] || return 1
    (( octet >= 0 && octet <= 255 )) || return 1
  done
  (( o1 == 10 )) && return 1
  (( o1 == 127 )) && return 1
  (( o1 == 0 )) && return 1
  (( o1 == 169 && o2 == 254 )) && return 1
  (( o1 == 172 && o2 >= 16 && o2 <= 31 )) && return 1
  (( o1 == 192 && o2 == 168 )) && return 1
  return 0
}

first_public_ipv4_from_stream() {
  while IFS= read -r token; do
    for candidate in ${token}; do
      candidate="${candidate%%/*}"
      if is_public_ipv4 "${candidate}"; then
        printf '%s\n' "${candidate}"
        return 0
      fi
    done
  done
  return 1
}

query_metadata() {
  local endpoint="$1"
  curl -fsS --max-time 2 "${endpoint}" 2>/dev/null || return 1
}

main() {
  local candidate=""

  candidate="$(query_metadata "http://metadata.tencentyun.com/latest/meta-data/public-ipv4" || true)"
  if is_public_ipv4 "${candidate}"; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(query_metadata "http://metadata.tencentyun.com/meta-data/public-ipv4" || true)"
  if is_public_ipv4 "${candidate}"; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  if hostname -I 2>/dev/null | tr ' ' '\n' | first_public_ipv4_from_stream; then
    return 0
  fi

  if command -v ip >/dev/null 2>&1; then
    if ip -o -4 addr show scope global 2>/dev/null | awk '{print $4}' | first_public_ipv4_from_stream; then
      return 0
    fi
  fi

  printf '_\n'
}

main "$@"
