#!/usr/bin/env bash
#
# Deploy the Yaounde Urban-Speech Analyzer to a fresh Contabo VPS
# (Ubuntu 22.04 / 24.04 or Debian 12).
#
#   sudo bash deploy/install.sh                          # plain HTTP on the IP
#   sudo bash deploy/install.sh yca.example.com          # HTTPS via Let's Encrypt
#   sudo bash deploy/install.sh myapp.duckdns.org TOKEN  # HTTPS + DuckDNS updater
#
# DuckDNS domains work with Let's Encrypt exactly like any other: duckdns.org
# is on the Public Suffix List, so your subdomain gets its own certificate
# rate limit rather than sharing one with every other DuckDNS user.
#
# The script is idempotent: running it again upgrades in place.

set -euo pipefail

DOMAIN="${1:-}"
DUCKDNS_TOKEN="${2:-}"
APP_DIR=/opt/yca
APP_USER=yca
# Loopback port for the Python server. Must match deploy/yca.service and the
# upstream in deploy/nginx-yca.conf. 8000 and 8080 are the usual squatters on
# a shared box, so this deliberately sits well clear of them.
APP_PORT=8042
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!!  %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run this with sudo"

# DuckDNS names end in .duckdns.org and need an extra step or two.
IS_DUCKDNS=false
DUCKDNS_SUBDOMAIN=""
if [[ "$DOMAIN" == *.duckdns.org ]]; then
    IS_DUCKDNS=true
    # The update API wants the bare label, not the full name. Passing
    # "myapp.duckdns.org" here is the single most common DuckDNS mistake
    # and fails with a bare "KO" and no explanation.
    DUCKDNS_SUBDOMAIN="${DOMAIN%.duckdns.org}"
fi

# --------------------------------------------------------------------------
say "Installing packages"
# Only python3 and nginx are needed. The application itself has no
# third-party dependencies, so there is no pip step at all.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 nginx rsync ca-certificates

PY_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 - <<'EOF' || die "Python 3.10 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
EOF
say "Python ${PY_VERSION} is good"

# --------------------------------------------------------------------------
say "Creating the service account"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    # A locked system account: it owns the files and nothing else.
    adduser --system --group --home "$APP_DIR" --no-create-home \
            --shell /usr/sbin/nologin "$APP_USER"
fi

# --------------------------------------------------------------------------
say "Copying the application to ${APP_DIR}"
mkdir -p "$APP_DIR"
rsync -a --delete \
      --exclude '__pycache__' \
      --exclude '*.pyc' \
      --exclude '.git' \
      --exclude 'docs/report.aux' \
      --exclude 'docs/report.log' \
      --exclude 'docs/report.out' \
      --exclude 'docs/report.toc' \
      "$REPO_ROOT/src"    "$APP_DIR/"
rsync -a "$REPO_ROOT/cc.png" "$APP_DIR/" 2>/dev/null || \
    say "note: cc.png not found, the crest will not appear"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod -R go-w "$APP_DIR"

# Fail fast if the app cannot even import.
say "Checking the application starts"
sudo -u "$APP_USER" env PYTHONPATH="$APP_DIR/src" \
    python3 -c "import yca.web; print('import ok, version', yca.__version__)" \
    || die "the application does not import; deployment aborted"

# --------------------------------------------------------------------------
if [[ "$IS_DUCKDNS" == true ]]; then
    say "Configuring DuckDNS for ${DOMAIN}"

    if [[ -z "$DUCKDNS_TOKEN" ]]; then
        warn "No DuckDNS token given, so the record will not be kept fresh."
        warn "That is usually fine on Contabo, whose IPs are static, but the"
        warn "record must already point here or certbot will fail."
        warn "To enable it: bash deploy/install.sh ${DOMAIN} YOUR_TOKEN"
    else
        install -d -m 700 /etc/yca
        # Root-only: this token can repoint the domain at anyone's server.
        cat > /etc/yca/duckdns.env <<EOF
DUCKDNS_SUBDOMAIN=${DUCKDNS_SUBDOMAIN}
DUCKDNS_TOKEN=${DUCKDNS_TOKEN}
EOF
        chmod 600 /etc/yca/duckdns.env

        install -m 755 "$REPO_ROOT/deploy/duckdns-update.sh" \
                "$APP_DIR/duckdns-update.sh"
        install -m 644 "$REPO_ROOT/deploy/duckdns.service" \
                /etc/systemd/system/duckdns.service
        install -m 644 "$REPO_ROOT/deploy/duckdns.timer" \
                /etc/systemd/system/duckdns.timer

        systemctl daemon-reload
        systemctl enable --now duckdns.timer

        # Point the record at this machine before asking for a certificate,
        # otherwise the HTTP-01 challenge lands on the wrong host.
        say "Pointing ${DOMAIN} at this server"
        "$APP_DIR/duckdns-update.sh" || die "DuckDNS update failed"
    fi

    # Whether or not we just updated it, verify the name actually resolves
    # here. certbot's failure message is far less clear than this one.
    if command -v dig >/dev/null 2>&1 || apt-get install -y -qq dnsutils; then
        RESOLVED=$(dig +short "$DOMAIN" @1.1.1.1 | tail -n1)
        MYIP=$(curl -fsS --max-time 10 https://api.ipify.org || echo "")
        if [[ -n "$RESOLVED" && -n "$MYIP" && "$RESOLVED" != "$MYIP" ]]; then
            warn "${DOMAIN} resolves to ${RESOLVED} but this server is ${MYIP}."
            warn "certbot will fail until that agrees. Give DNS a minute,"
            warn "or set the IP by hand at https://www.duckdns.org/"
        elif [[ -n "$RESOLVED" ]]; then
            say "${DOMAIN} resolves to ${RESOLVED} -- correct"
        fi
    fi
fi

# --------------------------------------------------------------------------
say "Installing the systemd unit"

# This server may already host other applications. If something other than a
# previous copy of ourselves holds the port, stop now rather than fight it:
# a flapping service that loses a bind race is far harder to diagnose later.
if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${APP_PORT}\$"; then
    if systemctl is-active --quiet yca; then
        say "Port ${APP_PORT} is held by the existing yca service; replacing it"
    else
        die "port ${APP_PORT} is already in use by another program.
Edit APP_PORT in this script and the matching --port in deploy/yca.service
and the upstream in deploy/nginx-yca.conf, then rerun."
    fi
fi

install -m 644 "$REPO_ROOT/deploy/yca.service" /etc/systemd/system/yca.service
systemctl daemon-reload
systemctl enable yca
systemctl restart yca

sleep 2
systemctl is-active --quiet yca || {
    journalctl -u yca -n 30 --no-pager
    die "the service did not start"
}
say "Service is running"

# --------------------------------------------------------------------------
say "Configuring nginx"
SITE=/etc/nginx/sites-available/yca
install -m 644 "$REPO_ROOT/deploy/nginx-yca.conf" "$SITE"

if [[ -n "$DOMAIN" ]]; then
    sed -i "s/YOUR_DOMAIN/${DOMAIN}/g" "$SITE"
else
    # No domain: answer on whatever name or IP the request arrives with.
    sed -i "s/server_name YOUR_DOMAIN;/server_name _;/" "$SITE"
fi

# A duplicate limit_req_zone name is a fatal nginx error, and it would take
# down every other site on the box, not just this one. If the names are
# already defined elsewhere, drop ours and reuse theirs.
for zone in yca_api yca_page; do
    if grep -rqs --exclude=yca "zone=${zone}:" /etc/nginx/ 2>/dev/null; then
        warn "limit_req_zone ${zone} already exists; reusing the existing zone"
        sed -i "\#^limit_req_zone .*zone=${zone}:#d" "$SITE"
    fi
done

# Only ever remove the stock Debian default site, and only if it is the
# untouched symlink. Other people's work lives in this directory.
if [[ -L /etc/nginx/sites-enabled/default ]] && \
   [[ "$(readlink -f /etc/nginx/sites-enabled/default)" == /etc/nginx/sites-available/default ]]; then
    rm -f /etc/nginx/sites-enabled/default
fi

ln -sf "$SITE" /etc/nginx/sites-enabled/yca

# If our site is bad, unlink it again before bailing out. Leaving a broken
# file in sites-enabled would break the next person's unrelated reload.
if ! nginx -t; then
    rm -f /etc/nginx/sites-enabled/yca
    die "nginx rejected the configuration; our site has been unlinked again
so the other sites on this server are unaffected"
fi
systemctl reload nginx

# --------------------------------------------------------------------------
say "Opening the firewall"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow 'Nginx Full' >/dev/null
    # The app port stays shut: only nginx on loopback may reach the app.
    say "ufw updated (port ${APP_PORT} deliberately left closed)"
fi

# --------------------------------------------------------------------------
if [[ -n "$DOMAIN" ]]; then
    say "Requesting a TLS certificate for ${DOMAIN}"
    apt-get install -y -qq certbot python3-certbot-nginx
    if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
               --register-unsafely-without-email --redirect; then
        say "HTTPS is on, and certbot will renew it automatically"
    else
        warn "certbot failed -- the site still works over plain HTTP."
        if [[ "$IS_DUCKDNS" == true ]]; then
            warn "For DuckDNS, check in this order:"
            warn "  1. https://www.duckdns.org/ shows this server's IP"
            warn "  2. port 80 is reachable from outside (HTTP-01 needs it)"
            warn "  3. dig +short ${DOMAIN}  matches  curl https://api.ipify.org"
        else
            warn "Check that ${DOMAIN}'s A record points at this server."
        fi
        warn "Then rerun: certbot --nginx -d ${DOMAIN}"
    fi
fi

# --------------------------------------------------------------------------
say "Verifying"
sleep 1

# Check the application directly first. If this fails the fault is ours.
if curl -fsS --max-time 10 "http://127.0.0.1:${APP_PORT}/healthz" >/dev/null; then
    say "Application responds on 127.0.0.1:${APP_PORT}"
else
    die "the application is not answering; see: journalctl -u yca -n 50"
fi

# Then check it through nginx. On a server hosting several sites, a bare
# request to 127.0.0.1 lands on whichever block is default_server, which is
# probably somebody else's site -- so ask for our name explicitly.
HOST_HEADER="${DOMAIN:-localhost}"
if curl -fsS --max-time 10 -H "Host: ${HOST_HEADER}" \
        http://127.0.0.1/healthz >/dev/null; then
    say "nginx is routing ${HOST_HEADER} to the application"
else
    warn "the app is healthy but nginx did not route ${HOST_HEADER} to it."
    warn "Check: nginx -T | grep -A5 'server_name ${HOST_HEADER}'"
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "------------------------------------------------------------"
if [[ -n "$DOMAIN" ]]; then
    echo "  Live at:  https://${DOMAIN}/"
else
    echo "  Live at:  http://${IP}/"
fi
echo
echo "  Logs:     journalctl -u yca -f"
echo "  Restart:  systemctl restart yca"
echo "  Status:   systemctl status yca"
if [[ "$IS_DUCKDNS" == true && -n "$DUCKDNS_TOKEN" ]]; then
echo
echo "  DuckDNS:  systemctl list-timers duckdns.timer"
echo "            journalctl -u duckdns -n 20"
fi
echo "------------------------------------------------------------"
