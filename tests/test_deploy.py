"""Checks on the deployment files.

These do not deploy anything.  They guard against the mistakes that are
expensive precisely because they are only discovered on the server: a unit
file that points at the wrong path, an nginx site that forwards to the
wrong port, a script that was never marked executable.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"

SERVICE = DEPLOY / "yca.service"
NGINX = DEPLOY / "nginx-yca.conf"
INSTALL = DEPLOY / "install.sh"
GUIDE = DEPLOY / "README.md"

DUCK_UPDATE = DEPLOY / "duckdns-update.sh"
DUCK_SERVICE = DEPLOY / "duckdns.service"
DUCK_TIMER = DEPLOY / "duckdns.timer"

#: The port the unit binds and nginx forwards to.  If these ever disagree
#: the site returns 502, so it is worth asserting they are the same.
PORT = "8042"


class TestDeploymentFilesExist(unittest.TestCase):

    def test_every_file_is_present(self):
        for path in (SERVICE, NGINX, INSTALL, GUIDE,
                     DUCK_UPDATE, DUCK_SERVICE, DUCK_TIMER):
            with self.subTest(name=path.name):
                self.assertTrue(path.is_file(), f"{path.name} is missing")

    def test_shell_scripts_use_unix_line_endings(self):
        """A CRLF shebang makes bash fail with a baffling error."""
        for path in (INSTALL, DUCK_UPDATE):
            with self.subTest(name=path.name):
                self.assertNotIn(b"\r\n", path.read_bytes(),
                                 f"{path.name} must use LF endings")


class TestSystemdUnit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = SERVICE.read_text(encoding="utf-8")

    def test_binds_loopback_on_the_agreed_port(self):
        self.assertIn("--host 127.0.0.1", self.text)
        self.assertIn(f"--port {PORT}", self.text)

    def test_does_not_try_to_open_a_browser(self):
        """A server has no display; launching a browser would just fail."""
        self.assertIn("--no-browser", self.text)

    def test_refuses_to_drift_to_another_port(self):
        """nginx forwards to one port, so a clash must fail loudly."""
        self.assertIn("--exact-port", self.text)

    def test_runs_as_an_unprivileged_user(self):
        self.assertRegex(self.text, r"(?m)^User=(?!root$)\w+")
        self.assertIn("NoNewPrivileges=true", self.text)

    def test_sets_pythonpath_to_the_installed_source(self):
        self.assertIn("Environment=PYTHONPATH=/opt/yca/src", self.text)
        self.assertIn("WorkingDirectory=/opt/yca", self.text)

    def test_stops_with_sigterm(self):
        """The server traps SIGTERM, so systemd must send it."""
        self.assertIn("KillSignal=SIGTERM", self.text)

    def test_restarts_on_failure(self):
        self.assertIn("Restart=on-failure", self.text)

    def test_is_hardened(self):
        for directive in ("ProtectSystem=strict", "PrivateTmp=true",
                          "ProtectHome=true", "RestrictSUIDSGID=true"):
            with self.subTest(directive=directive):
                self.assertIn(directive, self.text)


class TestNginxSite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = NGINX.read_text(encoding="utf-8")

    def test_forwards_to_the_port_the_unit_binds(self):
        self.assertIn(f"server 127.0.0.1:{PORT}", self.text)

    def test_placeholder_domain_is_obvious(self):
        """The installer substitutes this; it must be findable."""
        self.assertIn("YOUR_DOMAIN", self.text)

    def test_passes_the_forwarding_headers(self):
        for header in ("X-Real-IP", "X-Forwarded-For", "X-Forwarded-Proto"):
            with self.subTest(header=header):
                self.assertIn(header, self.text)

    def test_rate_limits_the_api(self):
        self.assertIn("limit_req_zone", self.text)
        self.assertIn("zone=yca_api", self.text)

    def test_proxies_the_health_endpoint(self):
        self.assertIn("/healthz", self.text)

    def test_hides_the_version_banner(self):
        self.assertIn("server_tokens off", self.text)


class TestInstallScript(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = INSTALL.read_text(encoding="utf-8")

    def test_aborts_on_any_error(self):
        """Without this a failed step would be papered over."""
        self.assertIn("set -euo pipefail", self.text)

    def test_installs_no_python_packages(self):
        """The project's whole claim is that it needs none."""
        self.assertNotRegex(self.text, r"(?m)^\s*pip3? install")

    def test_installs_the_unit_and_the_site(self):
        self.assertIn("yca.service", self.text)
        self.assertIn("nginx-yca.conf", self.text)
        self.assertIn("systemctl enable yca", self.text)

    def test_validates_nginx_before_reloading(self):
        self.assertIn("nginx -t", self.text)

    def test_verifies_health_before_claiming_success(self):
        self.assertIn("/healthz", self.text)

    def test_checks_the_app_imports_before_installing_the_unit(self):
        """Catch a broken copy on the server, not after the service flaps."""
        import_check = self.text.index("import yca.web")
        # Anchor on the install destination, not the bare filename: the
        # filename also appears in comments further up the script.
        unit_install = self.text.index("/etc/systemd/system/yca.service")
        self.assertLess(import_check, unit_install)

    def test_app_port_agrees_with_the_unit_and_the_site(self):
        """Three files name this port; a silent disagreement is a 502."""
        self.assertIn(f"APP_PORT={PORT}", self.text)

    def test_refuses_to_start_on_an_occupied_port(self):
        """A shared server may already have something on that port."""
        self.assertIn("already in use by another program", self.text)

    def test_unlinks_its_own_site_if_nginx_rejects_it(self):
        """A broken file left in sites-enabled breaks unrelated sites too."""
        self.assertIn("rm -f /etc/nginx/sites-enabled/yca", self.text)

    def test_only_removes_the_untouched_default_site(self):
        """Other people's sites live in that directory."""
        self.assertIn("-L /etc/nginx/sites-enabled/default", self.text)

    def test_health_check_names_the_host_it_wants(self):
        """A bare loopback request hits whichever site is default_server."""
        self.assertIn('-H "Host: ${HOST_HEADER}"', self.text)

    def test_guards_against_duplicate_rate_limit_zones(self):
        """A duplicate zone name is fatal to every site on the server."""
        self.assertIn("zone=${zone}:", self.text)


class TestDuckDns(unittest.TestCase):
    """DuckDNS has two sharp edges; both must be handled, not documented."""

    @classmethod
    def setUpClass(cls):
        cls.install = INSTALL.read_text(encoding="utf-8")
        cls.updater = DUCK_UPDATE.read_text(encoding="utf-8")
        cls.timer = DUCK_TIMER.read_text(encoding="utf-8")
        cls.guide = GUIDE.read_text(encoding="utf-8")

    def test_installer_recognises_a_duckdns_domain(self):
        self.assertIn("*.duckdns.org", self.install)

    def test_installer_strips_the_suffix_for_the_api(self):
        """The update API takes the bare label; the FQDN returns a flat KO."""
        self.assertIn('DUCKDNS_SUBDOMAIN="${DOMAIN%.duckdns.org}"',
                      self.install)

    def test_updater_sends_the_bare_label_not_the_fqdn(self):
        self.assertIn("domains=${DUCKDNS_SUBDOMAIN}", self.updater)
        self.assertNotIn("${DUCKDNS_SUBDOMAIN}.duckdns.org&", self.updater)

    def test_updater_lets_duckdns_detect_the_address(self):
        """An empty ip= makes DuckDNS use the request's source address."""
        self.assertIn("&ip=", self.updater)

    def test_updater_checks_the_body_not_the_status_code(self):
        """DuckDNS answers 200 with the body 'KO' when it refuses."""
        self.assertIn('"$response" == OK*', self.updater)

    def test_token_file_is_root_only(self):
        """The token can repoint the domain, so it is a bearer secret."""
        self.assertIn("chmod 600 /etc/yca/duckdns.env", self.install)
        self.assertIn("install -d -m 700 /etc/yca", self.install)

    def test_record_is_pointed_here_before_certbot_runs(self):
        """HTTP-01 lands on whatever the name resolves to at that moment."""
        update = self.install.index("duckdns-update.sh")
        certbot = self.install.index("certbot --nginx")
        self.assertLess(update, certbot)

    def test_timer_does_not_poll_too_often(self):
        """DuckDNS asks clients to stay at or above five minutes."""
        self.assertIn("OnUnitActiveSec=5min", self.timer)

    def test_guide_warns_about_the_subdomain_trap(self):
        self.assertIn("bare label", self.guide)

    def test_guide_explains_the_public_suffix_list(self):
        """Why DuckDNS certificates are not rate-limited into the ground."""
        self.assertIn("Public Suffix List", self.guide)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
