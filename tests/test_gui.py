"""Tests for the Tkinter front end.

The window is never shown: the root is withdrawn, so these run unattended
on a normal desktop session.  Where Tk itself is unavailable -- a headless
CI box with no display -- the whole module is skipped rather than failed,
because that is an absent dependency and not a defect in the GUI.
"""

from __future__ import annotations

import time
import unittest

try:
    import tkinter as tk

    TK_AVAILABLE = True
    TK_REASON = ""
except Exception as exc:  # pragma: no cover - depends on the environment
    TK_AVAILABLE = False
    TK_REASON = f"Tk is unavailable: {exc}"

from yca import corpus

if TK_AVAILABLE:
    from yca.gui import EXAMPLES, AnalyzerApp


@unittest.skipUnless(TK_AVAILABLE, TK_REASON)
class TestAnalyzerApp(unittest.TestCase):
    """Drive the widgets directly and read the results back."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - headless box
            raise unittest.SkipTest(f"no display available: {exc}") from exc
        cls.root.withdraw()
        cls.app = AnalyzerApp(cls.root)
        # The grammar is prepared on a worker thread and collected by an
        # `after` callback, so the event loop has to be pumped *and* real
        # time has to pass.  Spinning update() alone can outrun the 50 ms
        # poll on a fast machine and never see the result, so wait against
        # the clock instead of against an iteration count.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            cls.root.update()
            if cls.app._analyzer is not None:
                break
            time.sleep(0.02)
        else:  # pragma: no cover - would mean a startup deadlock
            raise AssertionError("the analyzer never became ready")

    @classmethod
    def tearDownClass(cls):
        # Flush anything Tk has queued so it cannot fire against widgets
        # that are about to disappear.
        cls.root.update_idletasks()
        cls.root.destroy()

    def drive(self, text: str) -> str:
        """Type *text*, press Analyze, return the verdict banner."""
        self.app.entry.delete(0, "end")
        self.app.entry.insert(0, text)
        self.app.analyze()
        self.root.update()
        return self.app.banner.cget("text")

    # -- verdicts --------------------------------------------------------

    def test_accepts_a_wellformed_statement(self):
        self.assertIn("ACCEPTED", self.drive("Chef, drop me for Carrefour Obili."))

    def test_reports_lexical_and_syntactic_failure_differently(self):
        self.assertIn("lexical", self.drive("Mbom, the flurble don wibble."))
        self.assertIn("syntax", self.drive("for Mokolo drop me."))

    def test_rejection_is_explained(self):
        self.drive("for Mokolo drop me.")
        self.assertIn("expected", self.app.reason.cget("text"))

    def test_verdict_is_colour_coded(self):
        self.drive("Chef, drop me for Carrefour Obili.")
        good = self.app.banner.cget("background")
        self.drive("for Mokolo drop me.")
        self.assertNotEqual(good, self.app.banner.cget("background"))

    # -- panels ----------------------------------------------------------

    def test_token_table_matches_the_lexer(self):
        self.drive("Chef, drop me for Carrefour Obili.")
        expected = len(self.app._result.lex.tokens)
        self.assertEqual(len(self.app.tokens.get_children()), expected)

    def test_parse_tree_is_rooted_at_the_start_symbol(self):
        self.drive("Chef, drop me for Carrefour Obili.")
        body = self.app.tree_view.get("1.0", "end").strip()
        self.assertTrue(body.startswith("Statement"))

    def test_trace_is_populated_and_ends_in_accept(self):
        self.drive("Chef, drop me for Carrefour Obili.")
        rows = self.app.trace.get_children()
        self.assertGreater(len(rows), 10)
        last = self.app.trace.item(rows[-1], "values")
        self.assertIn("accept", str(last[-1]).lower())

    def test_derivation_is_leftmost_and_counted(self):
        self.drive("Chef, drop me for Carrefour Obili.")
        body = self.app.deriv_view.get("1.0", "end").strip()
        self.assertTrue(body.startswith("Statement"))
        self.assertIn("derivation steps", body)

    def test_rejected_input_yields_no_tree_or_derivation(self):
        self.drive("for Mokolo drop me.")
        self.assertIn("rejected", self.app.tree_view.get("1.0", "end").lower())
        self.assertIn("rejected", self.app.deriv_view.get("1.0", "end").lower())

    def test_first_follow_covers_every_nonterminal(self):
        table = self.app._grammar.table
        self.assertEqual(len(self.app.sets.get_children()),
                         len(table.grammar.rules))

    def test_corpus_tab_lists_statements_and_negative_tests(self):
        self.assertEqual(
            len(self.app.corpus_table.get_children()),
            len(corpus.CORPUS) + len(corpus.NEGATIVE_TESTS),
        )

    def test_statistics_reports_the_corpus(self):
        body = self.app.stats_view.get("1.0", "end")
        for heading in ("CORPUS", "TOKEN TYPES", "SOURCE LANGUAGES", "GRAMMAR"):
            with self.subTest(heading=heading):
                self.assertIn(heading, body)

    # -- controls --------------------------------------------------------

    def test_every_example_button_loads_and_analyzes(self):
        for ex in EXAMPLES:
            with self.subTest(example=ex.label):
                verdict = self.drive(ex.text)
                self.assertTrue(
                    "ACCEPTED" in verdict or "REJECTED" in verdict,
                    f"{ex.label} produced no verdict",
                )

    def test_corpus_picker_offers_every_statement(self):
        self.assertEqual(len(self.app.corpus_pick["values"]), len(corpus.CORPUS))

    def test_empty_input_is_handled_without_error(self):
        self.assertIn("Type a statement", self.drive("   "))

    def test_gui_agrees_with_the_pipeline(self):
        """The window must not invent verdicts of its own."""
        for statement in corpus.CORPUS:
            with self.subTest(sid=statement.sid):
                banner = self.drive(statement.text)
                direct = self.app._analyzer.analyze_text(statement.text)
                self.assertIn(direct.verdict, banner)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
