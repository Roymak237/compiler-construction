"""Token types and token records for the Yaounde urban-speech analyzer.

The token type is the *parser-facing* category: it is what appears as a
terminal symbol in the context-free grammar.  Linguistic information that is
interesting for the report but irrelevant to parsing (slang status, source
language, code-mixing) is kept as separate annotation fields so that the two
concerns never get tangled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TokenType(str, Enum):
    """Terminal symbols of the grammar."""

    VOC = "VOC"          # vocative / address term:  Chef, Mami, Boss
    NOUN = "NOUN"        # nouns and proper places:  quartier, Mokolo, tchop
    PRON = "PRON"        # pronouns:                 me, you, us, am
    DET = "DET"          # determiners:              this, ma, ce, your
    NUM = "NUM"          # numerals and money:       deux mille, 500, two
    ADJ = "ADJ"          # adjectives:               cher, long, zero-zero
    ADV = "ADV"          # adverbials:               today, small small, trop
    VERB = "VERB"        # lexical verbs:            drop, hala, finish
    AUX = "AUX"          # aspect / modal markers:   don, dey, make, fit
    NEG = "NEG"          # negation:                 no, pas, never
    PREP = "PREP"        # prepositions:             for, since, go
    COP = "COP"          # copula:                   na, c'est, be
    CONJ = "CONJ"        # coordinators:             and, et, but
    INTERJ = "INTERJ"    # interjections / slang cry: hmmm, ekiee, je wanda
    PART = "PART"        # post-nominal particles:   la, sef, o
    SEP = "SEP"          # internal separator:       ,  ;
    TERM = "TERM"        # terminator:               .  !  ?
    UNKNOWN = "UNKNOWN"  # not covered by the lexical specification
    EOF = "$"            # end-of-input marker used by the parser

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Token types that the lexer may produce (EOF is added by the parser driver).
LEXICAL_TYPES = tuple(t for t in TokenType if t is not TokenType.EOF)


class Language(str, Enum):
    """Source language attributed to a token, used for code-mixing analysis."""

    ENGLISH = "English"
    FRENCH = "French"
    PIDGIN = "Pidgin"
    CAMFRANGLAIS = "Camfranglais"
    EWONDO = "Ewondo"
    FULFULDE = "Fulfulde"
    PROPER = "ProperName"
    SYMBOL = "Symbol"
    UNKNOWN = "Unknown"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Token:
    """A single lexeme produced by the lexical analyzer.

    Attributes
    ----------
    type:
        Grammar terminal used by the parser.
    lexeme:
        The text exactly as it was transcribed, accents and all.  This is never
        rewritten, so the raw field data stays auditable.
    normalized:
        Case-folded, accent-folded form used for dictionary lookup and for
        grouping spelling variants during frequency analysis.
    line, column, start, end:
        1-based line/column and 0-based character offsets into the statement.
    languages:
        Languages the lexeme draws on.  More than one means the lexeme itself
        is code-mixed (for example ``c'est`` inside an English frame).
    is_slang:
        True for slang / Camfranglais items, which the brief asks us to count.
    rule:
        Name of the lexical rule that matched, for the token table in the
        report.
    """

    type: TokenType
    lexeme: str
    normalized: str
    line: int
    column: int
    start: int
    end: int
    languages: tuple[Language, ...] = (Language.UNKNOWN,)
    is_slang: bool = False
    rule: str = ""
    gloss: str = ""
    notes: str = ""

    @property
    def is_multiword(self) -> bool:
        """True when the lexeme spans more than one orthographic word."""
        return " " in self.lexeme.strip()

    @property
    def is_code_mixed(self) -> bool:
        """True when the single lexeme mixes more than one source language."""
        return len(self.languages) > 1

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.type}({self.lexeme!r})"


@dataclass
class LexError:
    """An unrecognised stretch of text, reported instead of being dropped."""

    lexeme: str
    line: int
    column: int
    start: int
    end: int
    message: str = "not covered by the lexical specification"

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"line {self.line}, col {self.column}: {self.lexeme!r} {self.message}"


@dataclass
class LexResult:
    """Everything the lexer produced for one statement."""

    source: str
    tokens: list[Token] = field(default_factory=list)
    errors: list[LexError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def types(self) -> list[TokenType]:
        return [t.type for t in self.tokens]

    def type_string(self) -> str:
        return " ".join(str(t.type) for t in self.tokens)
