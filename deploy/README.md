# Deploying to a Contabo VPS

The application is pure standard-library Python, so a deployment is
`python3` plus `nginx` and nothing else. No `pip install`, no virtualenv,
no build step.

## What you need

- A Contabo VPS running **Ubuntu 22.04 / 24.04** or **Debian 12**
- Root access over SSH
- Optionally a domain pointing at the server's IP — a free
  **DuckDNS** subdomain works perfectly, see below

Contabo's smallest VPS is far more than enough: the analyzer builds its
parse table once at start-up and then holds it in memory, using roughly
40 MB.

## One-command install

From your machine, copy the project across and run the installer:

```bash
# 1. Copy the project to the server
scp -r "compiler construction" root@YOUR_SERVER_IP:/tmp/yca-src

# 2. Run the installer on the server
ssh root@YOUR_SERVER_IP
cd /tmp/yca-src
bash deploy/install.sh myapp.duckdns.org YOUR_DUCKDNS_TOKEN
```

Or without a domain — plain HTTP on the bare IP, fine for a demo:

```bash
bash deploy/install.sh
```

That script:

1. installs `python3` and `nginx`
2. creates a locked `yca` system account that cannot log in
3. copies the app to `/opt/yca`
4. checks that it imports before going any further
5. points your DuckDNS record at the server and keeps it fresh
6. installs and starts the `yca` systemd service
7. configures nginx as a reverse proxy with gzip and rate limiting
8. requests a Let's Encrypt certificate if you gave it a domain
9. confirms `/healthz` answers before declaring success

Re-running it upgrades in place.

## DuckDNS

DuckDNS gives you a free `something.duckdns.org` name, and it works with
Let's Encrypt exactly like a paid domain. Two facts make this painless:

- **`duckdns.org` is on the Public Suffix List.** Your subdomain therefore
  gets its *own* Let's Encrypt rate limit instead of sharing one with every
  other DuckDNS user. Certificate issuance just works.
- **HTTP-01 is the challenge used**, so nothing DNS-specific is needed.
  Port 80 simply has to be reachable from the internet.

### Setting it up

1. Sign in at [duckdns.org](https://www.duckdns.org/) with any of the
   supported logins.
2. Create a subdomain, say `myapp`. Your full name is
   `myapp.duckdns.org`.
3. Copy the **token** shown at the top of the page.
4. Set the IP field to your Contabo server's address, or just let the
   installer do it.
5. Run the installer with both arguments:

```bash
bash deploy/install.sh myapp.duckdns.org 8f3c1e7a-0000-0000-0000-2b9d4a6f1c05
```

### The one mistake everybody makes

The DuckDNS update API takes the **bare label**, not the full name:

```
https://www.duckdns.org/update?domains=myapp&token=...        correct
https://www.duckdns.org/update?domains=myapp.duckdns.org&...  wrong
```

The wrong form returns a flat `KO` with no explanation. The installer
strips the suffix for you, so this only bites if you write your own
updater.

### Is the updater even needed?

Contabo hands out **static** IPs, so strictly speaking, no. It is
installed anyway as cheap insurance for the day the server is rebuilt or
migrated. It runs every five minutes:

```bash
systemctl list-timers duckdns.timer   # when it next fires
journalctl -u duckdns -n 20           # what it last did
/opt/yca/duckdns-update.sh            # run it by hand
```

The token lives in `/etc/yca/duckdns.env`, mode `600`, root-only —
anyone holding it can repoint your domain at their own server.

## Why nginx is in front

The application serves itself with `http.server` from the standard library.
That is a deliberate trade: the project stays dependency-free, which matters
for a piece of coursework that a marker has to be able to clone and run.

But `http.server` is a *development* server. It has no TLS, no rate
limiting, and it is vulnerable to slow-client attacks. So it binds to
**127.0.0.1 only** and nginx handles everything facing the internet:

| Concern            | Handled by |
| ------------------ | ---------- |
| TLS / HTTPS        | nginx + certbot |
| gzip compression   | nginx |
| Static caching     | nginx |
| Rate limiting      | nginx (`10r/s` on `/api/`, `30r/s` on pages) |
| Slow clients       | nginx buffers them |
| Restart on crash   | systemd |

Port 8042 is never exposed. If you have `ufw` enabled the installer leaves
it closed deliberately.

## Running it

```bash
systemctl status yca      # is it up
systemctl restart yca     # restart
journalctl -u yca -f      # follow the logs
curl localhost/healthz    # liveness probe
```

## Updating after a code change

```bash
scp -r src root@YOUR_SERVER_IP:/tmp/
ssh root@YOUR_SERVER_IP 'rsync -a --delete /tmp/src /opt/yca/ \
    && chown -R yca:yca /opt/yca && systemctl restart yca'
```

Or just re-run `deploy/install.sh`.

## Hardening already applied

The systemd unit runs the service with `ProtectSystem=strict`,
`PrivateTmp`, `NoNewPrivileges`, a syscall allowlist, and a 512 MB memory
ceiling. It can open sockets and read its own code; it cannot write to the
filesystem, load kernel modules or escalate privileges.

## If something goes wrong

**Service will not start** — `journalctl -u yca -n 50`. Almost always a
path problem: check `/opt/yca/src/yca/web.py` exists and is owned by `yca`.

**502 Bad Gateway** — nginx is up but the app is not.
`systemctl status yca`.

**Crest does not appear** — `cc.png` did not get copied. Put it at
`/opt/yca/cc.png` and `systemctl restart yca`.

**certbot failed** — nearly always DNS or a blocked port 80. For DuckDNS,
check in this order:

```bash
dig +short myapp.duckdns.org      # what the world thinks
curl https://api.ipify.org        # what this server actually is
```

If they disagree, fix the IP at duckdns.org (or run
`/opt/yca/duckdns-update.sh`) and wait a minute. If they agree, confirm
port 80 is open from outside — Let's Encrypt's HTTP-01 challenge must
reach it. Then rerun:

```bash
certbot --nginx -d myapp.duckdns.org
```

The site works over plain HTTP meanwhile.

**DuckDNS replies `KO`** — either the token is wrong, or
`DUCKDNS_SUBDOMAIN` in `/etc/yca/duckdns.env` was written as the full
`myapp.duckdns.org` instead of just `myapp`.

## If this were going to carry real traffic

For a class demo the setup above is sound. For anything heavier, the honest
answer is to put a WSGI server in front — which does mean accepting a
dependency:

```bash
pip install waitress
```

and reworking `web.py`'s handler as a WSGI application. The analyzer itself
is already fully decoupled from the HTTP layer, so that change touches only
`web.py` and nothing else in the project.
