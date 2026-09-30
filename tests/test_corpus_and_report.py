"""Tests for the corpus, the frequency analysis and the report generator."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from yca import corpus
from yca.analysis import frequency_report, token_table
from yca.pipeline import Analyzer
from yca.report import build_report, write_report
from yca.tokens import TokenType


class TestCorpusIntegrity(unittest.TestCase):
    def test_corpus_size_meets_the_brief(self):
        self.assertGreaterEqual(len(corpus.CORPUS), 10)
        self.assertLessEqual(len(corpus.CORPUS), 15)

    def test_ids_are_unique(self):
        ids = [s.sid for s in corpus.CORPUS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_statement_has_metadata(self):
        for s in corpus.CORPUS:
            with self.subTest(sid=s.sid):
                self.assertTrue(s.text.strip())
                self.assertTrue(s.topic.strip())
                self.assertTrue(s.gloss.strip())

    def test_topics_span_the_required_range(self):
        # The brief lists ten topic areas; we require reasonable coverage.
        self.assertGreaterEqual(len(corpus.topics()), 8)

    def test_provenance_is_declared_honestly(self):
        field, total = corpus.field_data_ratio()
        warning = corpus.provenance_warning()
        if field == total:
            self.assertIsNone(warning)
        else:
            self.assertIsNotNone(
                warning,
                "constructed data must produce a provenance warning",
            )


class TestFrequencyAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = Analyzer().analyze_all(corpus.CORPUS)
        cls.report = frequency_report(cls.results)

    def test_token_count_matches_the_streams(self):
        expected = sum(len(r.lex.tokens) for r in self.results)
        self.assertEqual(self.report.total_tokens, expected)

    def test_type_counts_sum_to_the_total(self):
        self.assertEqual(
            sum(self.report.type_counts.values()), self.report.total_tokens
        )

    def test_distinct_items_do_not_exceed_tokens(self):
        self.assertLessEqual(self.report.distinct_lexemes, self.report.total_tokens)

    def test_multiword_lexemes_are_detected(self):
        self.assertTrue(self.report.multiword)

    def test_slang_is_detected(self):
        self.assertTrue(self.report.slang_counts)

    def test_code_mixing_is_detected(self):
        self.assertTrue(
            self.report.mixed_statements,
            "a Yaounde corpus should contain code-mixed statements",
        )

    def test_no_unknown_tokens_in_the_corpus(self):
        self.assertEqual(
            dict(self.report.unknown), {},
            "corpus contains lexemes outside the specification",
        )

    def test_variant_groups_preserve_original_spellings(self):
        for group in self.report.variants.values():
            self.assertTrue(group.spellings)
            self.assertEqual(group.total, sum(group.spellings.values()))


class TestTokenTable(unittest.TestCase):
    def test_table_has_one_row_per_token(self):
        result = Analyzer().analyze_text("Chef, drop me.")
        self.assertEqual(len(token_table(result)), len(result.lex.tokens))

    def test_rows_are_fully_populated(self):
        """Index, lexeme, token type and matching rule, for every token.

        Language, slang and gloss are properties of the lexical item rather
        than of the occurrence, so they are tabulated once each by
        ``distinct_token_inventory`` instead of being repeated here.
        """
        result = Analyzer().analyze_text("Chef, drop me.")
        for row in token_table(result):
            self.assertEqual(len(row), 4)
            self.assertTrue(all(cell != "" for cell in row))


class TestReportGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = build_report()

    def test_report_is_substantial(self):
        self.assertGreater(len(self.text), 10_000)

    def test_all_required_sections_present(self):
        for section in [
            "Data collection",
            "Lexical analysis",
            "regular expressions",
            "Token frequency",
            "the grammar",
            "Removing left recursion",
            "Left factoring",
            "FIRST and FOLLOW",
            "LL(1) parsing table",
            "Test results",
            "linguistically complex",
            "Limitations",
        ]:
            with self.subTest(section=section):
                self.assertIn(section, self.text)

    def test_every_statement_appears(self):
        for s in corpus.CORPUS:
            with self.subTest(sid=s.sid):
                self.assertIn(s.sid, self.text)

    def test_corpus_section_introduces_the_statements(self):
        self.assertIn("Data collection and raw statements", self.text)

    def test_scope_limits_are_stated(self):
        self.assertIn("semantic", self.text.lower())


class TestLatexWellFormedness(unittest.TestCase):
    """Structural checks on the generated LaTeX.

    No LaTeX engine is assumed to be installed, so these tests stand in for
    compilation: they catch the mistakes that would actually stop pdflatex,
    namely unbalanced environments or braces and unescaped special characters.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = build_report()
        cls.body = cls.text.split(r"\begin{document}", 1)[1]
        # Verbatim blocks follow different rules and are checked separately.
        cls.prose = re.sub(
            r"\\begin\{Verbatim\}.*?\\end\{Verbatim\}", "", cls.body, flags=re.S
        )

    def test_document_is_framed(self):
        self.assertIn(r"\documentclass", self.text)
        self.assertIn(r"\begin{document}", self.text)
        self.assertTrue(self.text.rstrip().endswith(r"\end{document}"))

    def test_preamble_defines_what_the_body_uses(self):
        for command in [
            r"\newcolumntype{L}",
            r"\newcommand{\eps}",
            r"\usepackage{longtable}",
            r"\usepackage{booktabs}",
            r"\usepackage{fancyvrb}",
            r"\usepackage{array}",
        ]:
            with self.subTest(command=command):
                self.assertIn(command, self.text)

    def test_environments_are_balanced(self):
        # 'body' begins just after \begin{document}, so that one is pre-opened.
        depth: dict[str, int] = {"document": 1}
        for kind, name in re.findall(r"\\(begin|end)\{([A-Za-z*]+)\}", self.body):
            depth[name] = depth.get(name, 0) + (1 if kind == "begin" else -1)
            self.assertGreaterEqual(
                depth[name], 0, f"\\end{{{name}}} without a matching \\begin"
            )
        unclosed = {k: v for k, v in depth.items() if v != 0}
        self.assertEqual(unclosed, {}, f"unclosed environments: {unclosed}")

    def test_braces_are_balanced(self):
        opens = len(re.findall(r"(?<!\\)\{", self.text))
        closes = len(re.findall(r"(?<!\\)\}", self.text))
        self.assertEqual(opens, closes, "unbalanced braces in the document")

    def test_special_characters_are_escaped(self):
        # '&' is excluded: in the body it is the legitimate column separator.
        for ch in "%$#_":
            offenders = [
                self.prose[max(0, m.start() - 50):m.start() + 10]
                for m in re.finditer(re.escape(ch), self.prose)
                if self.prose[m.start() - 1] != "\\"
            ]
            with self.subTest(character=ch):
                self.assertEqual(
                    offenders, [], f"unescaped '{ch}' would abort pdflatex"
                )

    def test_epsilon_is_always_a_latex_command(self):
        self.assertNotIn(
            "\u03b5", self.body,
            "a literal epsilon must be written as \\eps{} so it typesets",
        )

    def test_verbatim_blocks_contain_no_stray_commands(self):
        # commandchars re-enables '\', '{' and '}' inside Verbatim, so the only
        # command permitted there is \eps{}.
        for block in re.findall(
            r"\\begin\{Verbatim\}\[[^\]]*\]\n(.*?)\n\\end\{Verbatim\}",
            self.body,
            flags=re.S,
        ):
            leftover = block.replace(r"\eps{}", "")
            for ch in "\\{}":
                with self.subTest(character=ch, block=block[:40]):
                    self.assertNotIn(ch, leftover)

    def test_every_longtable_declares_its_header_rows(self):
        blocks = re.findall(
            r"\\begin\{longtable\}.*?\\end\{longtable\}", self.body, flags=re.S
        )
        self.assertTrue(blocks)
        for block in blocks:
            with self.subTest(block=block[:60]):
                for marker in [r"\endfirsthead", r"\endhead", r"\endfoot",
                               r"\endlastfoot", r"\toprule", r"\bottomrule"]:
                    self.assertIn(marker, block)

    def test_longtable_rows_have_a_consistent_column_count(self):
        pattern = re.compile(
            r"\\begin\{longtable\}\{([^\n]*)\}\n(.*?)\\end\{longtable\}",
            flags=re.S,
        )
        tables = pattern.findall(self.body)
        self.assertTrue(tables)
        for spec, contents in tables:
            columns = spec.count("L{")
            self.assertGreater(columns, 0, f"unreadable column spec: {spec!r}")
            for line in contents.splitlines():
                line = line.strip()
                if (not line.endswith(r"\\")
                        or line.startswith("\\")
                        or r"\multicolumn" in line):
                    continue
                cells = len(re.findall(r"(?<!\\)&", line)) + 1
                with self.subTest(row=line[:60]):
                    self.assertEqual(cells, columns)

    def test_written_file_is_utf8_and_named_tex(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(Path(tmp) / "docs" / "report.tex")
            self.assertTrue(path.exists())
            self.assertEqual(path.suffix, ".tex")
            self.assertIn(r"\end{document}",
                          path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
