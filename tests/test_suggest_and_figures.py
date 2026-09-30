"""Tests for the correction engine and the generated diagrams.

These cover three things the rest of the suite does not reach.

The string measures are tested against the transcription slips they were
designed for, not against synthetic strings, because the whole justification
for combining three signals is that real disagreements in this material are
about sound rather than about typing.

The end-to-end behaviour is tested through the analyzer, so a proposal is
only counted as correct when it actually parses.  A suggestion engine that
proposes something plausible and wrong is worse than one that says nothing,
and only re-analysis distinguishes the two.

The figure module is tested structurally rather than by compiling it -- no
LaTeX engine is assumed -- which catches the mistakes that would abort
pdflatex, and one extra rule this project imposes on itself: the report's own
validation treats a stray per-cent or dollar sign as an error, so the shared
figures must contain neither.
"""

from __future__ import annotations

import re
import unittest

from yca import figures, slides
from yca.figures import (
    compiler_phases,
    figure_names,
    figure_sizes,
    lexer_automaton,
    parser_machine,
    slide_scale,
)
from yca.lexspec import PHRASES, WORDS
from yca.pipeline import Analyzer
from yca.suggest import (
    CONFIDENT,
    MIN_BASE,
    consonant_key,
    corrections,
    edit_distance,
    phonetic_key,
    similarity,
    split_repair,
    suggest_lexeme,
)


class TestEditDistance(unittest.TestCase):
    """The base measure, including the transposition case."""

    def test_identical_strings_are_zero_apart(self):
        self.assertEqual(edit_distance("mokolo", "mokolo"), 0)

    def test_empty_string_costs_the_whole_word(self):
        self.assertEqual(edit_distance("", "chef"), 4)
        self.assertEqual(edit_distance("chef", ""), 4)

    def test_single_substitution(self):
        self.assertEqual(edit_distance("drop", "drap"), 1)

    def test_transposition_counts_as_one_edit(self):
        # This is the reason for using Damerau rather than plain Levenshtein:
        # swapped letters are one slip of the pen, not two changes. Plain
        # Levenshtein scores each of these 2.
        self.assertEqual(edit_distance("mokolo", "mkoolo"), 1)
        self.assertEqual(edit_distance("form", "from"), 1)
        self.assertEqual(edit_distance("chef", "cehf"), 1)

    def test_distance_is_symmetric(self):
        for a, b in [("tchop", "chop"), ("wanda", "ouanda"), ("na", "an")]:
            with self.subTest(pair=(a, b)):
                self.assertEqual(edit_distance(a, b), edit_distance(b, a))

    def test_similarity_is_bounded(self):
        self.assertEqual(similarity("chef", "chef"), 1.0)
        self.assertEqual(similarity("", ""), 1.0)
        for a, b in [("chef", "mokolo"), ("a", "zzzzzz"), ("drop", "")]:
            with self.subTest(pair=(a, b)):
                self.assertGreaterEqual(similarity(a, b), 0.0)
                self.assertLessEqual(similarity(a, b), 1.0)


class TestPhoneticKey(unittest.TestCase):
    """The key must collapse the spellings transcribers actually disagree on."""

    def test_hush_consonant_spellings_agree(self):
        self.assertEqual(phonetic_key("tchop"), phonetic_key("chop"))
        self.assertEqual(phonetic_key("tchop"), phonetic_key("shop"))

    def test_w_and_ou_agree(self):
        self.assertEqual(phonetic_key("wanda"), phonetic_key("ouanda"))

    def test_silent_h_is_ignored(self):
        self.assertEqual(phonetic_key("hala"), phonetic_key("ala"))

    def test_doubled_letters_collapse(self):
        self.assertEqual(phonetic_key("drapp"), phonetic_key("drap"))

    def test_case_and_accent_are_folded(self):
        self.assertEqual(phonetic_key("CHEF"), phonetic_key("chef"))
        self.assertEqual(phonetic_key("frere"), phonetic_key("fr\u00e8re"))

    def test_genuinely_different_words_do_not_collide(self):
        # The key is allowed to be generous, but not so generous that it
        # makes unrelated vocabulary interchangeable.
        self.assertNotEqual(phonetic_key("mokolo"), phonetic_key("chef"))
        self.assertNotEqual(phonetic_key("drop"), phonetic_key("mami"))

    def test_key_is_never_empty_for_a_real_word(self):
        # "hey" is all silent-h and vowel-ish letters; the fallback in the
        # implementation exists precisely so it does not fold to nothing.
        for word in ("hey", "hi", "ah", "eh"):
            with self.subTest(word=word):
                self.assertNotEqual(phonetic_key(word), "")


class TestConsonantKey(unittest.TestCase):
    """The weakest signal: same consonants, different vowels."""

    def test_vowel_changes_do_not_alter_the_skeleton(self):
        self.assertEqual(consonant_key("drop"), consonant_key("drap"))
        self.assertEqual(consonant_key("drop"), consonant_key("drup"))

    def test_consonant_changes_do_alter_it(self):
        self.assertNotEqual(consonant_key("drop"), consonant_key("brop"))


class TestSuggestLexeme(unittest.TestCase):
    """Ranking has to put the intended word first, and stay quiet otherwise."""

    def _forms(self, lexeme: str) -> list[str]:
        return [c.form for c in suggest_lexeme(lexeme)]

    def test_a_declared_word_suggests_itself_first(self):
        self.assertEqual(self._forms("chef")[0], "chef")

    def test_vowel_slip_finds_the_intended_verb(self):
        self.assertEqual(self._forms("drapp")[0], "drop")

    def test_doubled_consonant_finds_the_intended_noun(self):
        self.assertEqual(self._forms("tchopp")[0], "tchop")

    def test_nonsense_suggests_nothing(self):
        self.assertEqual(suggest_lexeme("zxqwv"), [])

    def test_empty_input_suggests_nothing(self):
        self.assertEqual(suggest_lexeme(""), [])
        self.assertEqual(suggest_lexeme("   "), [])

    def test_results_are_ranked_high_to_low(self):
        scores = [c.score for c in suggest_lexeme("tchopp")]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_the_limit_is_respected(self):
        self.assertLessEqual(len(suggest_lexeme("chef", limit=2)), 2)

    def test_every_candidate_clears_the_base_floor(self):
        # A bonus must never be able to rescue a candidate that was
        # implausible on letters alone; otherwise the ranking is noise.
        for candidate in suggest_lexeme("tchopp"):
            with self.subTest(form=candidate.form):
                self.assertGreaterEqual(
                    similarity("tchopp", candidate.form), MIN_BASE
                )

    def test_candidates_are_all_declared_entries(self):
        for candidate in suggest_lexeme("drapp"):
            with self.subTest(form=candidate.form):
                self.assertTrue(
                    candidate.form in WORDS or candidate.form in PHRASES,
                    "the engine must never invent a form",
                )

    def test_every_candidate_carries_a_reason(self):
        for candidate in suggest_lexeme("drapp"):
            with self.subTest(form=candidate.form):
                self.assertTrue(candidate.reason.strip())

    def test_ranking_is_deterministic(self):
        self.assertEqual(self._forms("drapp"), self._forms("drapp"))


class TestSplitRepair(unittest.TestCase):
    """Two declared words written together are a fact, not a guess."""

    def test_particle_glued_to_a_noun_is_split(self):
        self.assertEqual(split_repair("quartierla"), ("quartier", "la"))

    def test_a_declared_word_is_not_split(self):
        self.assertIsNone(split_repair("quartier"))

    def test_nonsense_is_not_split(self):
        self.assertIsNone(split_repair("zxqwvpolm"))

    def test_short_runs_are_left_alone(self):
        self.assertIsNone(split_repair("ab"))

    def test_both_halves_must_be_declared(self):
        left_right = split_repair("quartierla")
        assert left_right is not None
        for half in left_right:
            with self.subTest(half=half):
                self.assertIn(half, WORDS)


class TestCorrectionReport(unittest.TestCase):
    """End-to-end: what the user is actually shown."""

    @classmethod
    def setUpClass(cls):
        cls.analyzer = Analyzer()

    def _report(self, text: str):
        return corrections(self.analyzer.analyze_text(text, trace=False),
                           self.analyzer)

    def test_an_accepted_statement_has_nothing_to_correct(self):
        report = self._report("Chef, drop me for Carrefour Obili.")
        self.assertTrue(report.accepted)
        self.assertEqual(report.kind, "none")
        self.assertEqual(report.suggestions, [])
        self.assertIsNone(report.hint)
        self.assertFalse(report.has_proposal)

    def test_a_misspelling_is_diagnosed_as_lexical(self):
        report = self._report("Chef, drapp me for Carrefour Obili.")
        self.assertEqual(report.kind, "lexical")
        self.assertEqual(len(report.suggestions), 1)
        self.assertEqual(report.suggestions[0].lexeme, "drapp")

    def test_a_proposal_is_verified_by_re_analysis(self):
        report = self._report("Chef, drapp me for Carrefour Obili.")
        self.assertTrue(report.has_proposal)
        # The claim in the panel must be the outcome of an actual parse.
        self.assertIs(report.proposal_accepted, True)
        again = self.analyzer.analyze_text(report.proposal, trace=False)
        self.assertTrue(again.accepted)

    def test_a_glued_particle_is_repaired_and_parses(self):
        report = self._report("Chef, drop me for quartierla.")
        self.assertEqual(report.suggestions[0].split, ("quartier", "la"))
        self.assertIn("quartier la", report.proposal)
        self.assertIs(report.proposal_accepted, True)

    def test_several_errors_are_repaired_together(self):
        report = self._report("Chef, drapp me for quartierla.")
        self.assertEqual(len(report.suggestions), 2)
        self.assertNotIn("drapp", report.proposal)
        self.assertNotIn("quartierla", report.proposal)

    def test_the_rewrite_preserves_surrounding_punctuation(self):
        report = self._report("Chef, drapp me for Carrefour Obili.")
        self.assertTrue(report.proposal.startswith("Chef,"))
        self.assertTrue(report.proposal.endswith("."))

    def test_unrecoverable_input_yields_no_proposal(self):
        report = self._report("Chef, zxqwv me for Carrefour Obili.")
        self.assertEqual(report.kind, "lexical")
        self.assertFalse(report.has_proposal)
        self.assertEqual(report.suggestions[0].candidates, [])

    def test_a_word_order_failure_is_diagnosed_as_syntax(self):
        report = self._report("drop for me Chef.")
        self.assertEqual(report.kind, "syntax")
        self.assertIsNotNone(report.hint)
        self.assertEqual(report.suggestions, [])

    def test_a_syntax_hint_names_the_terminals_the_table_accepts(self):
        report = self._report("drop for me Chef.")
        assert report.hint is not None
        self.assertTrue(report.hint.expected)
        self.assertTrue(report.hint.advice.strip())

    def test_working_without_an_analyzer_makes_no_unchecked_claim(self):
        result = self.analyzer.analyze_text("Chef, drapp me for Obili.",
                                            trace=False)
        report = corrections(result)
        self.assertTrue(report.has_proposal)
        # No analyzer was supplied, so the engine must not assert an outcome.
        self.assertIsNone(report.proposal_accepted)

    def test_confidence_threshold_is_respected(self):
        report = self._report("Chef, drapp me for Carrefour Obili.")
        best = report.suggestions[0].best
        assert best is not None
        self.assertGreaterEqual(best.score, CONFIDENT)

    def test_every_corpus_statement_reports_cleanly(self):
        # The engine runs on every verdict, so it must not raise on any of
        # them, and it must never contradict the verdict it was given.
        from yca import corpus

        for result in self.analyzer.analyze_all(corpus.CORPUS, trace=False):
            with self.subTest(sid=result.sid):
                report = corrections(result, self.analyzer)
                self.assertEqual(report.accepted, result.accepted)
                self.assertTrue(report.lines())

    def test_every_negative_test_is_explained(self):
        from yca import corpus

        for nid, text, _why in corpus.NEGATIVE_TESTS:
            with self.subTest(sid=nid):
                report = self._report(text)
                self.assertFalse(report.accepted)
                self.assertIn(report.kind, ("lexical", "syntax"))
                self.assertTrue(report.headline.strip())


class TestGeneratedFigures(unittest.TestCase):
    """Structural checks on the shared TikZ diagrams.

    No LaTeX engine is assumed, so these stand in for compilation in the same
    way the report's own LaTeX tests do.
    """

    FIGURES = {
        "lexer": lexer_automaton,
        "parser": parser_machine,
        "phases": compiler_phases,
    }

    def test_every_figure_is_a_single_picture(self):
        for key, fn in self.FIGURES.items():
            with self.subTest(figure=key):
                text = fn()
                self.assertEqual(text.count(r"\begin{tikzpicture}"), 1)
                self.assertEqual(text.count(r"\end{tikzpicture}"), 1)
                self.assertTrue(text.startswith(r"\begin{tikzpicture}"))
                self.assertTrue(text.rstrip().endswith(r"\end{tikzpicture}"))

    def test_braces_are_balanced(self):
        for key, fn in self.FIGURES.items():
            with self.subTest(figure=key):
                text = fn()
                opens = len(re.findall(r"(?<!\\)\{", text))
                closes = len(re.findall(r"(?<!\\)\}", text))
                self.assertEqual(opens, closes)

    def test_no_character_the_report_tests_reject(self):
        # report.py's own validation treats a bare '%' or '$' as an
        # unescaped special character, and these strings pass through it.
        for key, fn in self.FIGURES.items():
            for ch in "%$":
                with self.subTest(figure=key, character=ch):
                    self.assertNotIn(ch, fn())

    def test_no_literal_epsilon(self):
        # The report requires epsilon to be written as \eps{}; a raw one
        # here would fail that check from inside a figure.
        for key, fn in self.FIGURES.items():
            with self.subTest(figure=key):
                self.assertNotIn("\u03b5", fn())

    def test_scale_is_applied(self):
        self.assertIn("scale=0.5", lexer_automaton(0.5))
        self.assertIn("scale=1", lexer_automaton(1.0))

    def test_only_declared_colours_are_used(self):
        # Both preambles declare exactly these six; anything else would
        # compile in one document and fail in the other.
        declared = {"ink", "clay", "moss", "slate", "parchment", "rule",
                    "white", "black"}
        for key, fn in self.FIGURES.items():
            text = fn()
            used = set(re.findall(r"(?:draw|fill|text)=([a-z]+)", text))
            with self.subTest(figure=key):
                self.assertTrue(used <= declared, f"undeclared: {used - declared}")

    def test_every_figure_has_a_name_and_a_size(self):
        for key in self.FIGURES:
            with self.subTest(figure=key):
                self.assertIn(key, figure_names)
                self.assertIn(key, figure_sizes)
                self.assertTrue(figure_names[key].strip())

    def test_slide_scale_fits_the_frame(self):
        for key in self.FIGURES:
            with self.subTest(figure=key):
                scale = slide_scale(key)
                width, height = figure_sizes[key]
                self.assertGreater(scale, 0.0)
                self.assertLessEqual(scale * width, 138.0)
                self.assertLessEqual(scale * height, 60.0)

    def test_module_exports_match_its_contents(self):
        for name in figures.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(figures, name))


class TestSlidesModuleImports(unittest.TestCase):
    """The deck generator must at least be importable and runnable.

    It earns its own test because nothing else in the suite imports it, and
    a syntax error in a module no test touches is invisible until the day of
    the talk.
    """

    def test_the_deck_builds(self):
        text = slides.build_slides()
        self.assertIn(r"\documentclass", text)
        self.assertTrue(text.rstrip().endswith(r"\end{document}"))

    def test_the_frame_cap_is_honoured(self):
        text = slides.build_slides()
        self.assertLessEqual(
            text.count(r"\begin{frame}"), slides.MAX_SLIDES,
            "the deck has outgrown its own cap",
        )

    def test_frames_are_balanced(self):
        text = slides.build_slides()
        self.assertEqual(text.count(r"\begin{frame}"),
                         text.count(r"\end{frame}"))

    def test_the_diagrams_reach_the_deck(self):
        text = slides.build_slides()
        self.assertEqual(text.count(r"\begin{tikzpicture}"),
                         text.count(r"\end{tikzpicture}"))
        # The three shared figures plus the hand-drawn pipeline and the two
        # background templates; the point is simply that they arrived.
        self.assertGreaterEqual(text.count(r"\begin{tikzpicture}"), 6)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
