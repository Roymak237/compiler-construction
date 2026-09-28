"""Lexical analyzer: raw transcription -> stream of grammar terminals.

Design decisions worth knowing before reading the code
------------------------------------------------------
* **Longest match first.**  Multiword lexemes are tried before single words, so
  ``small small`` is one adverbial token and never ``small`` + ``small``.
* **Nothing is silently dropped.**  Text the specification does not cover is
  emitted as an ``UNKNOWN`` token *and* recorded as a :class:`LexError` with its
  position, so the report can show exactly what the analyzer failed to handle.
* **The transcription is never rewritten.**  Folding happens only to build a
  lookup key; ``Token.lexeme`` keeps the original spelling, accents and case.
"""

from __future__ import annotations

import re

from . import lexspec
from .lexspec import PATTERNS, PHRASES, WORDS, fold
from .tokens import Language, LexError, LexResult, Token, TokenType

#: Chunking pattern: one orthographic word, possibly containing ' or -.
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]+(?:['\u2019\u2018-][A-Za-zÀ-ÿ]+)*")
_SPACE_RE = re.compile(r"\s+")

#: Longest phrase in the specification, measured in orthographic words.
_MAX_PHRASE_WORDS = max((len(p.split()) for p in PHRASES), default=1)


class Lexer:
    """Turn one transcribed statement into a token stream."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.pos = 0
        self.line = 1
        self.line_start = 0
        self.tokens: list[Token] = []
        self.errors: list[LexError] = []

    # -- position helpers -------------------------------------------------

    def _column(self, index: int) -> int:
        return index - self.line_start + 1

    def _advance_over(self, text: str) -> None:
        """Keep line/column bookkeeping correct across newlines."""
        for i, ch in enumerate(text):
            if ch == "\n":
                self.line += 1
                self.line_start = self.pos + i + 1

    # -- scanning ---------------------------------------------------------

    def _skip_ignorable(self) -> None:
        src = self.source
        while self.pos < len(src):
            m = _SPACE_RE.match(src, self.pos)
            if m:
                self._advance_over(m.group())
                self.pos = m.end()
                continue
            m = lexspec.IGNORE_RE.match(src, self.pos)
            if m:
                self.pos = m.end()
                continue
            return

    def _word_runs(self, limit: int) -> list[tuple[int, int]]:
        """Return spans of up to *limit* consecutive words starting at ``pos``."""
        runs: list[tuple[int, int]] = []
        cursor = self.pos
        src = self.source
        for _ in range(limit):
            m = _WORD_RE.match(src, cursor)
            if not m:
                break
            runs.append((m.start(), m.end()))
            cursor = m.end()
            space = _SPACE_RE.match(src, cursor)
            if not space:
                break
            cursor = space.end()
        return runs

    def _emit(
        self,
        ttype: TokenType,
        start: int,
        end: int,
        languages: tuple[Language, ...],
        slang: bool,
        rule: str,
        gloss: str = "",
        notes: str = "",
    ) -> None:
        lexeme = self.source[start:end]
        self.tokens.append(
            Token(
                type=ttype,
                lexeme=lexeme,
                normalized=fold(lexeme),
                line=self.line,
                column=self._column(start),
                start=start,
                end=end,
                languages=languages,
                is_slang=slang,
                rule=rule,
                gloss=gloss,
                notes=notes,
            )
        )
        self._advance_over(lexeme)
        self.pos = end

    def _try_lexicon(self) -> bool:
        """Match the longest phrase or single word from the declared lexicon."""
        runs = self._word_runs(_MAX_PHRASE_WORDS)
        for n in range(len(runs), 0, -1):
            start = runs[0][0]
            end = runs[n - 1][1]
            key = fold(self.source[start:end])
            entry = PHRASES.get(key)
            rule = "R-PHRASE"
            if entry is None and n == 1:
                entry = WORDS.get(key)
                rule = "R-VOCAB"
            if entry is not None:
                ttype, languages, slang, gloss = entry
                note = "multiword lexeme" if n > 1 else ""
                self._emit(ttype, start, end, languages, slang, rule, gloss, note)
                return True
        return False

    def _try_patterns(self) -> bool:
        src = self.source
        for name, pattern, ttype, languages, slang in PATTERNS:
            m = pattern.match(src, self.pos)
            if not m or m.end() == m.start():
                continue
            if ttype is TokenType.UNKNOWN:
                # R-WORD is the catch-all: report it rather than hide it.
                self.errors.append(
                    LexError(
                        lexeme=m.group(),
                        line=self.line,
                        column=self._column(m.start()),
                        start=m.start(),
                        end=m.end(),
                    )
                )
                self._emit(
                    TokenType.UNKNOWN, m.start(), m.end(),
                    (Language.UNKNOWN,), False, name,
                    notes="not in lexical specification",
                )
                return True
            self._emit(ttype, m.start(), m.end(), languages, slang, name)
            return True
        return False

    def tokenize(self) -> LexResult:
        """Run the scanner to completion."""
        while True:
            self._skip_ignorable()
            if self.pos >= len(self.source):
                break
            if self._try_lexicon():
                continue
            if self._try_patterns():
                continue
            # Single stray character that no rule accepts.
            start = self.pos
            self.errors.append(
                LexError(
                    lexeme=self.source[start],
                    line=self.line,
                    column=self._column(start),
                    start=start,
                    end=start + 1,
                    message="unexpected character",
                )
            )
            self._emit(
                TokenType.UNKNOWN, start, start + 1,
                (Language.UNKNOWN,), False, "R-STRAY",
                notes="unexpected character",
            )
        return LexResult(source=self.source, tokens=self.tokens, errors=self.errors)


def tokenize(source: str) -> LexResult:
    """Convenience wrapper: tokenize a single statement."""
    return Lexer(source).tokenize()
