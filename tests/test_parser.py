"""Unit tests for the parser and the end-to-end pipeline."""

from __future__ import annotations

import unittest

from yca.corpus import CORPUS, NEGATIVE_TESTS
from yca.pipeline import Analyzer


class ParserTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer = Analyzer()

    def accept(self, text: str):
        result = self.analyzer.analyze_text(text)
        self.assertTrue(
            result.accepted,
            f"expected {text!r} to be accepted, but: {result.reason}",
        )
        return result

    def reject(self, text: str):
        result = self.analyzer.analyze_text(text)
        self.assertFalse(result.accepted, f"expected {text!r} to be rejected")
        return result


class TestCorpusAcceptance(ParserTestCase):
    def test_every_corpus_statement_is_accepted(self):
        failures = []
        for result in self.analyzer.analyze_all(CORPUS):
            if not result.accepted:
                failures.append(f"{result.sid}: {result.text} -> {result.reason}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_accepted_statements_have_a_parse_tree(self):
        for result in self.analyzer.analyze_all(CORPUS):
            if result.accepted:
                self.assertIsNotNone(result.parse.tree, result.sid)


class TestNegativeCases(ParserTestCase):
    def test_declared_negative_tests_are_rejected(self):
        failures = []
        for sid, text, why in NEGATIVE_TESTS:
            result = self.analyzer.analyze_text(text, sid=sid)
            if result.accepted:
                failures.append(f"{sid}: {text!r} was accepted but {why}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_missing_terminator_is_rejected(self):
        self.reject("Chef, drop me")

    def test_trailing_tokens_are_not_ignored(self):
        self.reject("Chef, drop me. drop")

    def test_empty_input_is_rejected(self):
        self.reject("")

    def test_terminator_alone_is_rejected(self):
        self.reject(".")

    def test_preamble_alone_is_rejected(self):
        self.reject("Chef.")


class TestFailureKinds(ParserTestCase):
    def test_unknown_word_is_a_lexical_rejection(self):
        result = self.reject("Chef, xyzzy me.")
        self.assertFalse(result.lex_ok)
        self.assertEqual(result.verdict, "REJECTED (lexical)")
        self.assertIn("xyzzy", result.reason)

    def test_wrong_order_is_a_syntactic_rejection(self):
        result = self.reject("for Mokolo drop me.")
        self.assertTrue(result.lex_ok)
        self.assertEqual(result.verdict, "REJECTED (syntax)")

    def test_rejection_reports_a_position(self):
        result = self.reject("for Mokolo drop me.")
        self.assertIsNotNone(result.parse.error_token)

    def test_rejection_reports_expected_terminals(self):
        result = self.reject("Chef chef.")
        self.assertTrue(result.parse.error)


class TestGrammarCoverage(ParserTestCase):
    """Each test names the construction it is exercising."""

    def test_vocative_then_imperative(self):
        self.accept("Chef, drop me.")

    def test_interjection_opener(self):
        self.accept("Hmmm, drop me.")

    def test_multiple_openers(self):
        self.accept("Hmmm, chef, drop me.")

    def test_no_opener(self):
        self.accept("drop me.")

    def test_perfective_aspect_marker(self):
        self.accept("Courant don finish.")

    def test_progressive_aspect_marker(self):
        self.accept("we dey wait.")

    def test_negation(self):
        self.accept("Courant no dey.")

    def test_copular_clause(self):
        self.accept("deux mille na last price.")

    def test_french_copula(self):
        self.accept("Courant c'est trop cher.")

    def test_coordinated_clauses(self):
        self.accept("Courant no dey, we dey wait.")

    def test_prepositional_phrase(self):
        self.accept("drop me for Obili.")

    def test_subject_with_prepositional_modifier(self):
        self.accept("queue for station dey long.")

    def test_noun_compounding(self):
        self.accept("drop me for Carrefour Obili.")

    def test_final_particle(self):
        self.accept("deux mille na last price o.")

    def test_serial_verb_directional(self):
        self.accept("carry me go Mokolo.")

    def test_determiner_phrase(self):
        self.accept("this road don cut.")

    def test_exclamation_terminator(self):
        self.accept("Chef, bring your carte nationale!")

    def test_question_terminator(self):
        self.accept("deux cents na for Mvan?")


class TestTraceAndTree(ParserTestCase):
    def test_trace_is_recorded_when_requested(self):
        result = self.analyzer.analyze_text("drop me.", trace=True)
        self.assertTrue(result.parse.trace)
        self.assertEqual(result.parse.trace[-1].action, "accept")

    def test_trace_is_skipped_when_not_requested(self):
        result = self.analyzer.analyze_text("drop me.", trace=False)
        self.assertEqual(result.parse.trace, [])

    def test_tree_root_is_the_start_symbol(self):
        result = self.accept("drop me.")
        self.assertEqual(result.parse.tree.symbol, "Statement")

    def test_tree_leaves_carry_their_tokens(self):
        result = self.accept("drop me.")
        lexemes = []

        def walk(node):
            if node.token is not None:
                lexemes.append(node.token.lexeme)
            for child in node.children:
                walk(child)

        walk(result.parse.tree)
        self.assertEqual(lexemes, ["drop", "me", "."])


class TestDeterminism(ParserTestCase):
    def test_same_input_gives_same_verdict(self):
        for _ in range(3):
            self.assertTrue(self.analyzer.analyze_text("drop me.").accepted)

    def test_case_does_not_change_the_verdict(self):
        self.assertEqual(
            self.analyzer.analyze_text("chef, drop me.").accepted,
            self.analyzer.analyze_text("CHEF, DROP ME.").accepted,
        )


if __name__ == "__main__":
    unittest.main()
