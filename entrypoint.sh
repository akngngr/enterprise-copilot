#!/bin/bash
set -euo pipefail

# Materialise Streamlit's [auth] config from environment variables.
#
# Streamlit reads secrets ONLY from ~/.streamlit/secrets.toml - there is no
# environment-variable equivalent for [auth]. The repo cannot carry that file
# (it holds a client secret and is gitignored) and .dockerignore excludes
# .streamlit, so the image has no way to obtain it. Generating it here keeps
# every credential in the platform's secret store instead of the repository.
#
# All six variables are required. A missing one fails the boot loudly rather
# than starting an app whose sign-in button cannot work.
SECRETS_DIR="${STREAMLIT_SECRETS_DIR:-${HOME:-/root}/.streamlit}"
SECRETS_FILE="${SECRETS_DIR}/secrets.toml"

: "${STREAMLIT_AUTH_REDIRECT_URI:?STREAMLIT_AUTH_REDIRECT_URI is required}"
: "${STREAMLIT_AUTH_CLIENT_ID:?STREAMLIT_AUTH_CLIENT_ID is required}"
: "${STREAMLIT_AUTH_CLIENT_SECRET:?STREAMLIT_AUTH_CLIENT_SECRET is required}"
: "${STREAMLIT_AUTH_COOKIE_SECRET:?STREAMLIT_AUTH_COOKIE_SECRET is required}"
: "${STREAMLIT_AUTH_SERVER_METADATA_URL:?STREAMLIT_AUTH_SERVER_METADATA_URL is required}"

mkdir -p "$SECRETS_DIR"
# Single-quoted heredoc: the values are written literally, never expanded or
# interpreted, so a secret containing $ or a backtick cannot execute.
cat >"$SECRETS_FILE" <<EOF
[auth]
redirect_uri       = "${STREAMLIT_AUTH_REDIRECT_URI}"
cookie_secret      = "${STREAMLIT_AUTH_COOKIE_SECRET}"
client_id          = "${STREAMLIT_AUTH_CLIENT_ID}"
client_secret      = "${STREAMLIT_AUTH_CLIENT_SECRET}"
server_metadata_url = "${STREAMLIT_AUTH_SERVER_METADATA_URL}"
expose_tokens      = "${STREAMLIT_AUTH_EXPOSE_TOKENS:-id}"
EOF
chmod 600 "$SECRETS_FILE"

# Refuse to boot on a config that Streamlit would reject at runtime with an
# opaque StreamlitAuthError. These three keys are required for EVERY provider,
# default one included (auth_util.validate_auth_credentials).
for key in client_id client_secret server_metadata_url; do
    grep -q "^${key}" "$SECRETS_FILE" || {
        echo "::error::${key} missing from generated secrets.toml" >&2
        exit 1
    }
done

echo "Wrote Streamlit auth config to ${SECRETS_FILE}"

ollama serve &
PIDS=("$!")

if [ "${ENABLE_OLLAMA_PULL:-false}" = "true" ]; then
    ollama pull nomic-embed-text &
    PIDS+=("$!")
    ollama pull llama3 &
    PIDS+=("$!")
fi

alembic upgrade head

uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8000}" &
API_PID=$!
PIDS+=("$API_PID")

streamlit run app/frontend.py --server.address=0.0.0.0 --server.port="${PORT:-8501}" &
UI_PID=$!
PIDS+=("$UI_PID")

cleanup() {
    kill "${PIDS[@]}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait -n "$API_PID" "$UI_PID"
