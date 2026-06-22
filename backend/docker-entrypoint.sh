#!/bin/sh
set -eu

DATA_DIR="${DATA_ROOT:-/app/data}"
SECRET_FILE="${DATA_DIR}/.secret_key"

secret_is_weak() {
  case "${SECRET_KEY:-}" in
    ""|"change-me")
      return 0
      ;;
  esac

  byte_count="$(printf '%s' "${SECRET_KEY:-}" | wc -c | tr -d '[:space:]')"
  [ "$byte_count" -lt 32 ]
}

mkdir -p "$DATA_DIR"

if secret_is_weak; then
  if [ -s "$SECRET_FILE" ]; then
    SECRET_KEY="$(cat "$SECRET_FILE")"
  else
    SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
    printf '%s\n' "$SECRET_KEY" > "$SECRET_FILE"
    chmod 600 "$SECRET_FILE"
  fi
  export SECRET_KEY
fi

exec "$@"
