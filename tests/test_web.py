"""Tests for the browser front end.

A real server is started on a free port and driven over HTTP, so these cover
the routing, the JSON contract and the serialisers together rather than
poking at internals.  Nothing is mocked: if the page would break, these
break.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from yca import corpus
from yca.pipeline import Analyzer
from yca.web import (
    ASSETS,
    SPLASH_MS,
    analysis_json,
    bootstrap_json,
    build_server,
    derivation_steps,
    find_asset,
    tree_json,
)
from yca.grammar_def import prepare


class TestAssets(unittest.TestCase):
    """The static files the server promises must actually be there."""

    def test_asset_files_exist(self):
        for name in ("index.html", "app.css", "app.js"):
            with self.subTest(name=name):
                self.assertTrue((ASSETS / name).is_file(),
                                f"{name} is missing from webassets/")

    def test_index_references_its_assets(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        self.assertIn("/app.css", html)
        self.assertIn("/app.js", html)
        self.assertIn("/assets/logo.png", html)

    def test_splash_is_three_seconds(self):
        """The brief asked for roughly three seconds on the logo."""
        self.assertEqual(SPLASH_MS, 3000)

    def test_icon_is_found(self):
        self.assertIsNotNone(find_asset("cc.png"),
                             "the crest cc.png could not be located")


class TestSerialisers(unittest.TestCase):
    """The JSON must say exactly what the analyzer says."""

    @classmethod
    def setUpClass(cls):
        cls.grammar = prepare()
        cls.analyzer = Analyzer(cls.grammar)

    def test_accepted_statement_serialises(self):
        result = self.analyzer.analyze_text("Chef, drop me for Carrefour Obili.")
        data = analysis_json(result, self.grammar)

        self.assertTrue(data["accepted"])
        self.assertEqual(data["verdict"], result.verdict)
        self.assertEqual(len(data["tokens"]), len(result.lex.tokens))
        self.assertIsNotNone(data["tree"])
        self.assertTrue(data["trace"])
        self.assertTrue(data["derivation"])

    def test_rejected_statement_keeps_its_reason(self):
        result = self.analyzer.analyze_text("for Mokolo drop me.")
        data = analysis_json(result, self.grammar)

        self.assertFalse(data["accepted"])
        self.assertIsNone(data["tree"])
        self.assertEqual(data["derivation"], [])
        self.assertTrue(data["reason"])

    def test_unknown_word_is_reported_not_dropped(self):
        result = self.analyzer.analyze_text("Mbom, the flurble don wibble.")
        data = analysis_json(result, self.grammar)
        self.assertFalse(data["lexOk"])
        self.assertTrue(data["lexErrors"])

    def test_payload_is_json_serialisable(self):
        result = self.analyzer.analyze_text("Mbom, deux mille na last price o.")
        json.dumps(analysis_json(result, self.grammar))
        json.dumps(bootstrap_json(self.analyzer, self.grammar))

    def test_tree_json_keeps_every_node(self):
        result = self.analyzer.analyze_text("Chef, drop me for Carrefour Obili.")
        tree = tree_json(result.parse.tree)

        def count(node):
            return 1 + sum(count(c) for c in node["children"])

        def count_real(node):
            return 1 + sum(count_real(c) for c in node.children)

        self.assertEqual(count(tree), count_real(result.parse.tree))

    def test_derivation_starts_at_the_start_symbol(self):
        result = self.analyzer.analyze_text("Chef, drop me for Carrefour Obili.")
        steps = derivation_steps(result, self.grammar)
        self.assertEqual(steps[0], self.grammar.after_left_factoring.start)

    def test_bootstrap_covers_corpus_and_negatives(self):
        boot = bootstrap_json(self.analyzer, self.grammar)
        self.assertEqual(
            len(boot["corpus"]),
            len(corpus.CORPUS) + len(corpus.NEGATIVE_TESTS),
        )
        self.assertEqual(boot["stats"]["statements"], len(corpus.CORPUS))
        self.assertEqual(len(boot["group"]), len(corpus.GROUP))

    def test_negative_tests_are_green_when_they_are_rejected(self):
        """A negative test that is rejected has *passed*, so it shows green."""
        boot = bootstrap_json(self.analyzer, self.grammar)
        negatives = [r for r in boot["corpus"] if r["kind"] == "negative"]
        self.assertTrue(negatives)
        for row in negatives:
            with self.subTest(sid=row["sid"]):
                self.assertTrue(row["accepted"],
                                f"{row['sid']} was accepted by the parser")

    def test_conflicts_carry_their_explanation(self):
        """The page must be able to say *why* a conflict is acceptable."""
        boot = bootstrap_json(self.analyzer, self.grammar)
        conflicts = boot["grammar"]["conflicts"]
        self.assertTrue(conflicts, "expected the documented NGopt conflict")

        for c in conflicts:
            with self.subTest(cell=(c["nonterminal"], c["terminal"])):
                self.assertIn("chosen", c)
                self.assertIn("rejected", c)
                self.assertNotEqual(c["chosen"], c["rejected"])
                if c["documented"]:
                    self.assertTrue(c["note"],
                                    "a documented conflict must carry a note")

    def test_no_conflict_is_left_unreviewed(self):
        """Every conflict is accounted for, so none is an outstanding defect."""
        boot = bootstrap_json(self.analyzer, self.grammar)
        self.assertEqual(
            boot["grammar"]["unreviewed"], 0,
            "an unreviewed conflict is a real defect, not a design decision",
        )

    def test_the_known_conflict_is_the_noun_compounding_one(self):
        boot = bootstrap_json(self.analyzer, self.grammar)
        cells = {(c["nonterminal"], c["terminal"])
                 for c in boot["grammar"]["conflicts"]}
        self.assertIn(("NGopt", "NOUN"), cells)


class TestServer(unittest.TestCase):
    """Drive the real HTTP server."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = build_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str):
        with urllib.request.urlopen(self.url(path), timeout=30) as res:
            return res.status, res.headers.get("Content-Type", ""), res.read()

    def post_json(self, path: str, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url(path), data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.loads(res.read().decode("utf-8"))

    # -- static ----------------------------------------------------------

    def test_index_is_served(self):
        status, ctype, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"splash", body)

    def test_stylesheet_and_script_are_served(self):
        for path, expected in (("/app.css", "text/css"),
                               ("/app.js", "text/javascript")):
            with self.subTest(path=path):
                status, ctype, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertIn(expected, ctype)
                self.assertTrue(body)

    def test_logo_is_served_as_png(self):
        status, ctype, body = self.get("/assets/logo.png")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_unknown_route_is_a_clean_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/nope")
        self.assertEqual(ctx.exception.code, 404)

    # -- api -------------------------------------------------------------

    def test_bootstrap_endpoint(self):
        status, ctype, body = self.get("/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("grammar", data)
        self.assertIn("corpus", data)
        self.assertEqual(data["splashMs"], SPLASH_MS)

    def test_analyze_accepts_a_good_statement(self):
        status, data = self.post_json(
            "/api/analyze", {"text": "Chef, drop me for Carrefour Obili."})
        self.assertEqual(status, 200)
        self.assertTrue(data["accepted"])
        self.assertTrue(data["tokens"])

    def test_analyze_rejects_a_bad_statement(self):
        _, data = self.post_json("/api/analyze", {"text": "for Mokolo drop me."})
        self.assertFalse(data["accepted"])
        self.assertTrue(data["reason"])

    def test_empty_text_is_a_bad_request(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_json("/api/analyze", {"text": "   "})
        self.assertEqual(ctx.exception.code, 400)

    def test_malformed_body_is_a_bad_request(self):
        req = urllib.request.Request(
            self.url("/api/analyze"), data=b"{not json",
            headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=30)
        self.assertEqual(ctx.exception.code, 400)

    def test_analyze_also_works_as_a_get(self):
        from urllib.parse import quote

        status, _, body = self.get("/api/analyze?text=" + quote("Chef, waka."))
        self.assertEqual(status, 200)
        self.assertIn("verdict", json.loads(body.decode("utf-8")))

    def test_health_endpoint(self):
        """nginx and systemd both need a cheap liveness probe."""
        status, ctype, body = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "ok")
        self.assertIn("ready", data)

    def test_absurdly_long_input_is_refused(self):
        """The trace grows with the input, so the length must be bounded."""
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_json("/api/analyze", {"text": "na " * 5000})
        self.assertEqual(ctx.exception.code, 413)

    def test_web_agrees_with_the_pipeline(self):
        """The page and the command line must never disagree."""
        analyzer = Analyzer()
        for statement in corpus.CORPUS:
            with self.subTest(sid=statement.sid):
                expected = analyzer.analyze_statement(statement, trace=False)
                _, data = self.post_json("/api/analyze",
                                         {"text": statement.text})
                self.assertEqual(data["accepted"], expected.accepted)
                self.assertEqual(data["verdict"], expected.verdict)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
