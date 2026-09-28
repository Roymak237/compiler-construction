"""Unit tests for the lexical analyzer."""

from __future__ import annotations

import unittest

from yca.lexer import tokenize
from yca.lexspec import fold
from yca.tokens import Language, TokenType


class TestFolding(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(fold("Chef"), "chef")

    def test_strips_accents(self):
        self.assertEqual(fold("réseau"), "reseau")

    def test_unifies_apostrophes(self):
        self.assertEqual(fold("c\u2019est"), fold("c'est"))

    def test_collapses_whitespace(self):
        self.assertEqual(fold("small   small"), "small small")


class TestBasicTokenization(unittest.TestCase):
    def test_simple_statement(self):
        result = tokenize("Chef, drop me.")
        self.assertEqual(
            result.types,
            [
                TokenType.VOC,
                TokenType.SEP,
                TokenType.VERB,
                TokenType.PRON,
                TokenType.TERM,
            ],
        )
        self.assertTrue(result.ok)

    def test_terminators(self):
        for text, count in [("drop me.", 1), ("drop me!", 1), ("drop me?", 1)]:
            with self.subTest(text=text):
                types = tokenize(text).types
                self.assertEqual(types.count(TokenType.TERM), count)

    def test_positions_are_recorded(self):
        result = tokenize("Chef, drop me.")
        first = result.tokens[0]
        self.assertEqual(first.line, 1)
        self.assertEqual(first.column, 1)
        drop = result.tokens[2]
        self.assertEqual(drop.lexeme, "drop")
        self.assertEqual(drop.column, 7)


class TestOriginalTextPreserved(unittest.TestCase):
    def test_case_is_not_rewritten(self):
        token = tokenize("Chef.").tokens[0]
        self.assertEqual(token.lexeme, "Chef")
        self.assertEqual(token.normalized, "chef")

    def test_accents_are_not_rewritten(self):
        token = tokenize("réseau.").tokens[0]
        self.assertEqual(token.lexeme, "réseau")
        self.assertEqual(token.normalized, "reseau")

    def test_lexemes_reconstruct_the_source(self):
        text = "Mami, reduce this tomate small."
        result = tokenize(text)
        for token in result.tokens:
            self.assertEqual(text[token.start:token.end], token.lexeme)


class TestMultiwordLexemes(unittest.TestCase):
    def test_small_small_is_one_token(self):
        result = tokenize("dey small small.")
        adverbs = [t for t in result.tokens if t.type is TokenType.ADV]
        self.assertEqual(len(adverbs), 1)
        self.assertEqual(adverbs[0].lexeme, "small small")
        self.assertTrue(adverbs[0].is_multiword)

    def test_je_wanda_is_one_interjection(self):
        result = tokenize("Je wanda.")
        self.assertEqual(result.types[0], TokenType.INTERJ)
        self.assertEqual(result.tokens[0].lexeme, "Je wanda")

    def test_money_phrase_is_one_numeral(self):
        result = tokenize("deux cents.")
        self.assertEqual(result.types[0], TokenType.NUM)
        self.assertEqual(result.tokens[0].lexeme, "deux cents")

    def test_longest_match_wins(self):
        # 'deux' alone is also a NUM; the two-word form must be preferred.
        result = tokenize("deux cents.")
        self.assertEqual(len(result.tokens), 2)  # NUM + TERM


class TestPatternRules(unittest.TestCase):
    def test_hesitation_cry(self):
        for cry in ["hmmm", "Hmmm", "aaah", "eeeh"]:
            with self.subTest(cry=cry):
                token = tokenize(f"{cry}.").tokens[0]
                self.assertEqual(token.type, TokenType.INTERJ)
                self.assertTrue(token.is_slang)

    def test_lengthened_slang(self):
        token = tokenize("Garrr.").tokens[0]
        self.assertEqual(token.type, TokenType.INTERJ)
        self.assertTrue(token.is_slang)

    def test_bare_digits(self):
        token = tokenize("500.").tokens[0]
        self.assertEqual(token.type, TokenType.NUM)

    def test_money_with_unit(self):
        token = tokenize("500 frs.").tokens[0]
        self.assertEqual(token.type, TokenType.NUM)
        self.assertIn("frs", token.lexeme)


class TestUnknownHandling(unittest.TestCase):
    def test_unknown_word_is_reported_not_dropped(self):
        result = tokenize("xyzzy.")
        self.assertFalse(result.ok)
        self.assertEqual(result.types[0], TokenType.UNKNOWN)
        self.assertEqual(len(result.errors), 1)

    def test_error_carries_position(self):
        result = tokenize("Chef, xyzzy.")
        error = result.errors[0]
        self.assertEqual(error.line, 1)
        self.assertEqual(error.column, 7)
        self.assertEqual(error.lexeme, "xyzzy")

    def test_stray_character_is_reported(self):
        result = tokenize("chef @ me.")
        self.assertFalse(result.ok)
        self.assertTrue(any(e.lexeme == "@" for e in result.errors))

    def test_nothing_is_silently_discarded(self):
        result = tokenize("chef @ xyzzy.")
        self.assertEqual(len(result.errors), 2)


class TestAnnotations(unittest.TestCase):
    def test_code_mixed_token_flagged(self):
        token = tokenize("Je wanda.").tokens[0]
        self.assertTrue(token.is_code_mixed)
        self.assertIn(Language.FRENCH, token.languages)
        self.assertIn(Language.PIDGIN, token.languages)

    def test_slang_flag(self):
        token = tokenize("Ekiee.").tokens[0]
        self.assertTrue(token.is_slang)
        self.assertIn(Language.EWONDO, token.languages)

    def test_rule_name_is_recorded(self):
        result = tokenize("Chef, small small.")
        rules = {t.rule for t in result.tokens}
        self.assertIn("R-VOCAB", rules)
        self.assertIn("R-PHRASE", rules)


class TestWhitespaceAndPunctuation(unittest.TestCase):
    def test_extra_whitespace_is_ignored(self):
        a = tokenize("Chef,   drop   me.").types
        b = tokenize("Chef, drop me.").types
        self.assertEqual(a, b)

    def test_quotes_are_skipped(self):
        result = tokenize('"Chef, drop me."')
        self.assertTrue(result.ok)
        self.assertEqual(result.types[0], TokenType.VOC)

    def test_empty_input(self):
        result = tokenize("")
        self.assertEqual(result.tokens, [])
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
