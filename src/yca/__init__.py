"""Public entry points for the Yaounde urban-speech analyzer."""

from __future__ import annotations

from .analysis import CorpusReport, analyze_corpus, frequency_report
from .corpus import CORPUS, NEGATIVE_TESTS, Statement, provenance_warning
from .grammar_def import prepare
from .lexer import Lexer, tokenize
from .parser import LL1Parser, ParseResult
from .pipeline import Analyzer, StatementResult
from .tokens import Language, LexResult, Token, TokenType

__version__ = "1.0.0"

__all__ = [
    "Analyzer",
    "StatementResult",
    "CorpusReport",
    "analyze_corpus",
    "frequency_report",
    "CORPUS",
    "NEGATIVE_TESTS",
    "Statement",
    "provenance_warning",
    "prepare",
    "Lexer",
    "tokenize",
    "LL1Parser",
    "ParseResult",
    "Language",
    "LexResult",
    "Token",
    "TokenType",
    "__version__",
]
