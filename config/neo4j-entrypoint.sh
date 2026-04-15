#!/bin/sh
# Neo4j entrypoint wrapper — fetches password from 1Password Connect at startup
set -e

OPC_HOST="${OP_CONNECT_HOST:?OP_CONNECT_HOST required}"
OPC_TOKEN="${OP_CONNECT_TOKEN:?OP_CONNECT_TOKEN required}"
VAULT_NAME="${VAULT_NAME:-Homelab}"
ITEM_NAME="${ITEM_NAME:-Dockp04-Corvus-Secrets}"

echo "[neo4j-opc] Fetching password from 1Password Connect..."

VAULT_ID=$(curl -s -H "Authorization: Bearer ${OPC_TOKEN}" \
  "${OPC_HOST}/v1/vaults" | \
  jq -r ".[] | select(.name==\"${VAULT_NAME}\") | .id")

if [ -z "${VAULT_ID}" ] || [ "${VAULT_ID}" = "null" ]; then
  echo "[neo4j-opc] ERROR: Vault not found" >&2; exit 1
fi

ITEM_ID=$(curl -s -H "Authorization: Bearer ${OPC_TOKEN}" \
  "${OPC_HOST}/v1/vaults/${VAULT_ID}/items" | \
  jq -r ".[] | select(.title==\"${ITEM_NAME}\") | .id")

if [ -z "${ITEM_ID}" ] || [ "${ITEM_ID}" = "null" ]; then
  echo "[neo4j-opc] ERROR: Item not found" >&2; exit 1
fi

FIELDS=$(curl -s -H "Authorization: Bearer ${OPC_TOKEN}" \
  "${OPC_HOST}/v1/vaults/${VAULT_ID}/items/${ITEM_ID}")

NEO4J_PASSWORD=$(echo "${FIELDS}" | jq -r '.fields[] | select(.label=="NEO4J_PASSWORD") | .value // .password // empty')

if [ -z "${NEO4J_PASSWORD}" ]; then
  echo "[neo4j-opc] ERROR: NEO4J_PASSWORD not found" >&2; exit 1
fi

export NEO4J_PASSWORD
echo "[neo4j-opc] ✓ NEO4J_PASSWORD set"
echo "[neo4j-opc] Starting Neo4j..."