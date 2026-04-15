#!/bin/sh
# Corvus entrypoint wrapper — fetches API keys from 1Password Connect at startup
set -e

OPC_HOST="${OP_CONNECT_HOST:?OP_CONNECT_HOST required}"
OPC_TOKEN="${OP_CONNECT_TOKEN:?OP_CONNECT_TOKEN required}"
VAULT_NAME="${VAULT_NAME:-Homelab}"
ITEM_NAME="${ITEM_NAME:-Dockp04-Corvus-Secrets}"

echo "[corvus-opc] Fetching secrets from 1Password Connect..."

VAULT_ID=$(curl -s -H "Authorization: Bearer ${OPC_TOKEN}" \
  "${OPC_HOST}/v1/vaults" | \
  jq -r ".[] | select(.name==\"${VAULT_NAME}\") | .id")

if [ -z "${VAULT_ID}" ] || [ "${VAULT_ID}" = "null" ]; then
  echo "[corvus-opc] ERROR: Vault not found" >&2; exit 1
fi

ITEM_ID=$(curl -s -H "Authorization: Bearer ${OPC_TOKEN}" \
  "${OPC_HOST}/v1/vaults/${VAULT_ID}/items" | \
  jq -r ".[] | select(.title==\"${ITEM_NAME}\") | .id")

if [ -z "${ITEM_ID}" ] || [ "${ITEM_ID}" = "null" ]; then
  echo "[corvus-opc] ERROR: Item not found" >&2; exit 1
fi

FIELDS=$(curl -s -H "Authorization: Bearer ${OPC_TOKEN}" \
  "${OPC_HOST}/v1/vaults/${VAULT_ID}/items/${ITEM_ID}/fields")

CORVUS_API_KEYS=$(echo "${FIELDS}" | jq -r '.[] | select(.label=="CORVUS_API_KEYS") | .value // .password // empty')

if [ -z "${CORVUS_API_KEYS}" ]; then
  echo "[corvus-opc] ERROR: CORVUS_API_KEYS not found" >&2; exit 1
fi

export CORVUS_API_KEYS
echo "[corvus-opc] ✓ CORVUS_API_KEYS set"
echo "[corvus-opc] Starting Corvus..."