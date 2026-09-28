"""Unit tests for the grammar transformations and table construction."""

from __future__ import annotations

import unittest

from yca.grammar import (
    END,
    EPSILON,
    Grammar,
    build_ll1_table,
    compute_first,
    compute_follow,
    left_factor,
    remove_left_recursion,
)
from yca.grammar_def import base_grammar, prepare, undocumented_conflicts


class TestLeftRecursionRemoval(unittest.TestCase):
    def test_removes_immediate_left_recursion(self):
        g = Grammar("E", {"E": [("E", "+", "T"), ("T",)], "T": [("id",)]})
        out, steps = remove_left_recursion(g)
        self.assertEqual(len(steps), 1)
        self.assertIn("E'", out.rules)
        self.assertEqual(out.rules["E"], [("T", "E'")])
        self.assertIn((EPSILON,), out.rules["E'"])

    def test_no_recursion_leaves_grammar_alone(self):
        g = Grammar("S", {"S": [("a", "b")]})
        out, steps = remove_left_recursion(g)
        self.assertEqual(steps, [])
        self.assertEqual(out.rules, g.rules)

    def test_corpus_grammar_has_recursion_removed(self):
        prepared = prepare()
        self.assertTrue(prepared.recursion_steps)
        for head, prods in prepared.after_left_recursion.rules.items():
            for prod in prods:
                self.assertNotEqual(
                    prod[0], head, f"{head} is still left recursive"
                )


class TestLeftFactoring(unittest.TestCase):
    def test_factors_common_prefix(self):
        g = Grammar("S", {"S": [("a", "b"), ("a", "c")]})
        out, steps = left_factor(g)
        self.assertEqual(len(steps), 1)
        self.assertEqual(len(out.rules["S"]), 1)

    def test_no_common_prefix_leaves_grammar_alone(self):
        g = Grammar("S", {"S": [("a",), ("b",)]})
        out, steps = left_factor(g)
        self.assertEqual(steps, [])

    def test_result_has_no_common_prefixes(self):
        prepared = prepare()
        for head, prods in prepared.final.rules.items():
            firsts = [p[0] for p in prods if p != (EPSILON,)]
            self.assertEqual(
                len(firsts), len(set(firsts)),
                f"{head} still has productions sharing a first symbol",
            )


class TestFirstFollow(unittest.TestCase):
    def setUp(self):
        # Classic expression grammar from the dragon book.
        self.g = Grammar(
            "E",
            {
                "E": [("T", "E'")],
                "E'": [("+", "T", "E'"), (EPSILON,)],
                "T": [("F", "T'")],
                "T'": [("*", "F", "T'"), (EPSILON,)],
                "F": [("(", "E", ")"), ("id",)],
            },
        )
        self.first = compute_first(self.g)
        self.follow = compute_follow(self.g, self.first)

    def test_first_sets(self):
        self.assertEqual(self.first["E"], {"(", "id"})
        self.assertEqual(self.first["E'"], {"+", EPSILON})
        self.assertEqual(self.first["F"], {"(", "id"})

    def test_follow_sets(self):
        self.assertEqual(self.follow["E"], {")", END})
        self.assertEqual(self.follow["E'"], {")", END})
        self.assertEqual(self.follow["T"], {"+", ")", END})
        self.assertEqual(self.follow["F"], {"+", "*", ")", END})

    def test_start_symbol_follows_end_marker(self):
        self.assertIn(END, self.follow["E"])

    def test_expression_grammar_is_ll1(self):
        self.assertTrue(build_ll1_table(self.g).is_ll1)


class TestCorpusGrammarTable(unittest.TestCase):
    def setUp(self):
        self.prepared = prepare()

    def test_no_unreviewed_conflicts(self):
        remaining = undocumented_conflicts(self.prepared.table)
        self.assertEqual(
            remaining, [],
            "unreviewed LL(1) conflicts: " + "; ".join(str(c) for c in remaining),
        )

    def test_start_symbol_is_reachable(self):
        self.assertIn("Statement", self.prepared.final.rules)

    def test_every_nonterminal_has_a_table_entry(self):
        for nt in self.prepared.final.nonterminals:
            entries = [k for k in self.prepared.table.table if k[0] == nt]
            self.assertTrue(entries, f"{nt} has no table entries")

    def test_terminator_is_required(self):
        # FOLLOW(ClauseList) must contain TERM: a statement cannot end early.
        self.assertIn("TERM", self.prepared.table.follow["ClauseList"])

    def test_base_grammar_is_not_already_ll1(self):
        # The assignment asks us to demonstrate the transformations, so the
        # starting grammar must genuinely need them.
        base = base_grammar()
        recursive = any(
            prod and prod[0] == head
            for head, prods in base.rules.items()
            for prod in prods
        )
        self.assertTrue(recursive, "base grammar has no left recursion to remove")


if __name__ == "__main__":
    unittest.main()
