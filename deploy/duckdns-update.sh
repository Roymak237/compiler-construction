#!/usr/bin/env bash
#
# Refresh this host's DuckDNS record.
#
# Contabo hands out a static IP, so this is belt-and-braces rather than a
# necessity: it matters only if the address ever changes (a rebuild, a
# migration, a move to a different plan). It is cheap to leave running.
#
# Credentials come from /etc/yca/duckdns.env, which is root-only because the
# token is a bearer secret -- anyone holding it can repoint the domain.

set -euo pipefail

ENV_FILE=/etc/yca/duckdns.env
[[ -r "$ENV_FILE" ]] || { echo "missing $ENV_FILE" >&2; exit 1; }
# shellcheck source=/dev/null
source "$ENV_FILE"

: "${DUCKDNS_SUBDOMAIN:?not set in $ENV_FILE}"
: "${DUCKDNS_TOKEN:?not set in $ENV_FILE}"

# Leaving ip= empty tells DuckDNS to take the source address of this
# request, which is exactly what we want and avoids having to discover our
# own public IP.
response=$(curl -fsS --max-time 20 \
    "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=")

# DuckDNS answers with the literal string OK or KO -- never a status code,
# so the body is the only signal there is.
if [[ "$response" == OK* ]]; then
    echo "DuckDNS: ${DUCKDNS_SUBDOMAIN}.duckdns.org updated"
    exit 0
fi

echo "DuckDNS refused the update (replied '${response}')." >&2
echo "Check the token, and that DUCKDNS_SUBDOMAIN is the bare label" >&2
echo "('myapp'), not the full name ('myapp.duckdns.org')." >&2
exit 1
