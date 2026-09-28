"""End-to-end pipeline: transcription -> tokens -> parse decision."""

from __future__ import annotations

from dataclasses import dataclass

from .corpus import Statement
from .grammar_def import PreparedGrammar, prepare
from .lexer import tokenize
from .parser import LL1Parser, ParseResult
from .tokens import LexResult


@dataclass
class StatementResult:
    """Everything the analyzer determined about one statement."""

    sid: str
    text: str
    topic: str
    lex: LexResult
    parse: ParseResult

    @property
    def accepted(self) -> bool:
        return self.parse.accepted

    @property
    def lex_ok(self) -> bool:
        return self.lex.ok

    @property
    def verdict(self) -> str:
        if self.accepted:
            return "ACCEPTED"
        return "REJECTED (lexical)" if not self.lex_ok else "REJECTED (syntax)"

    @property
    def reason(self) -> str:
        """Why the statement was rejected, distinguishing the two failure kinds."""
        if self.accepted:
            return ""
        if not self.lex_ok:
            return "; ".join(str(e) for e in self.lex.errors)
        return self.parse.error


class Analyzer:
    """Lexer + LL(1) parser behind one call."""

    def __init__(self, grammar: PreparedGrammar | None = None) -> None:
        self.grammar = grammar or prepare()
        self.parser = LL1Parser(self.grammar.table)

    def analyze_text(
        self, text: str, *, sid: str = "-", topic: str = "-", trace: bool = True
    ) -> StatementResult:
        lex = tokenize(text)
        parse = self.parser.parse(lex.tokens, trace=trace)
        return StatementResult(sid=sid, text=text, topic=topic, lex=lex, parse=parse)

    def analyze_statement(
        self, statement: Statement, *, trace: bool = True
    ) -> StatementResult:
        return self.analyze_text(
            statement.text,
            sid=statement.sid,
            topic=statement.topic,
            trace=trace,
        )

    def analyze_all(
        self, statements: list[Statement], *, trace: bool = False
    ) -> list[StatementResult]:
        return [self.analyze_statement(s, trace=trace) for s in statements]
