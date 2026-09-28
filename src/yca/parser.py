"""Table-driven LL(1) parser.

The parser is a plain predictive stack machine: push the start symbol, then
repeatedly either match a terminal or expand a nonterminal using the cell
``M[top, lookahead]``.  Acceptance requires that the stack empties *and* the
input is fully consumed, so trailing tokens can never be ignored.

Every step is recorded, which is what lets the analyzer justify a rejection
instead of merely announcing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .grammar import END, EPSILON, LL1Table
from .tokens import Token, TokenType


@dataclass
class ParseStep:
    """One row of the parse trace."""

    number: int
    stack: str
    remaining: str
    action: str


@dataclass
class ParseNode:
    """A node of the concrete syntax tree."""

    symbol: str
    token: Token | None = None
    children: list["ParseNode"] = field(default_factory=list)

    def render(self, prefix: str = "", last: bool = True, root: bool = True) -> list[str]:
        connector = "" if root else ("`-- " if last else "|-- ")
        if self.token is not None:
            label = f'{self.symbol} "{self.token.lexeme}"'
        else:
            label = self.symbol
        lines = [f"{prefix}{connector}{label}"]
        child_prefix = prefix if root else prefix + ("    " if last else "|   ")
        for i, child in enumerate(self.children):
            lines += child.render(child_prefix, i == len(self.children) - 1, False)
        return lines

    def __str__(self) -> str:  # pragma: no cover - display helper
        return "\n".join(self.render())


@dataclass
class ParseResult:
    """Outcome of parsing one token stream."""

    accepted: bool
    trace: list[ParseStep]
    tree: ParseNode | None
    error: str = ""
    error_token: Token | None = None
    expected: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "ACCEPTED" if self.accepted else "REJECTED"


class LL1Parser:
    """Predictive parser driven by a generated LL(1) table."""

    def __init__(self, table: LL1Table) -> None:
        self.table = table
        self.grammar = table.grammar

    def parse(self, tokens: list[Token], *, trace: bool = True) -> ParseResult:
        grammar = self.grammar
        steps: list[ParseStep] = []

        # Unknown lexemes can never match a terminal; fail early and say why.
        for tok in tokens:
            if tok.type is TokenType.UNKNOWN:
                return ParseResult(
                    accepted=False,
                    trace=steps,
                    tree=None,
                    error=(
                        f"lexical failure: {tok.lexeme!r} at line {tok.line}, "
                        f"column {tok.column} is not in the lexical specification"
                    ),
                    error_token=tok,
                )

        stream = [str(t.type) for t in tokens] + [END]
        root = ParseNode(grammar.start)
        # Stack of (symbol, node); the node is where matched children go.
        stack: list[tuple[str, ParseNode | None]] = [(END, None), (grammar.start, root)]
        index = 0
        step_no = 0

        def snapshot(action: str) -> None:
            nonlocal step_no
            if not trace:
                return
            step_no += 1
            steps.append(
                ParseStep(
                    number=step_no,
                    stack=" ".join(s for s, _ in reversed(stack)),
                    remaining=" ".join(stream[index:]),
                    action=action,
                )
            )

        while stack:
            top, node = stack[-1]
            lookahead = stream[index]

            if top == END:
                if lookahead == END:
                    snapshot("accept")
                    return ParseResult(True, steps, root)
                tok = tokens[index] if index < len(tokens) else None
                return ParseResult(
                    accepted=False,
                    trace=steps,
                    tree=None,
                    error=(
                        "trailing input: the statement was already complete at "
                        f"{lookahead}"
                    ),
                    error_token=tok,
                )

            if not grammar.is_nonterminal(top):
                # Terminal on top of the stack: it must match the lookahead.
                if top == lookahead:
                    snapshot(f"match {top}")
                    if node is not None and index < len(tokens):
                        node.token = tokens[index]
                    stack.pop()
                    index += 1
                    continue
                tok = tokens[index] if index < len(tokens) else None
                return ParseResult(
                    accepted=False,
                    trace=steps,
                    tree=None,
                    error=f"expected {top} but found {lookahead}",
                    error_token=tok,
                    expected=[top],
                )

            production = self.table.lookup(top, lookahead)
            if production is None:
                tok = tokens[index] if index < len(tokens) else None
                expected = self.table.expected_terminals(top)
                where = (
                    f"line {tok.line}, column {tok.column}: {tok.lexeme!r}"
                    if tok is not None
                    else "end of input"
                )
                return ParseResult(
                    accepted=False,
                    trace=steps,
                    tree=None,
                    error=(
                        f"no rule for {top} on {lookahead} at {where}; "
                        f"expected one of: {', '.join(expected) or '(nothing)'}"
                    ),
                    error_token=tok,
                    expected=expected,
                )

            snapshot(f"output {top} -> {' '.join(production)}")
            stack.pop()

            if production == (EPSILON,):
                if node is not None:
                    node.children.append(ParseNode(EPSILON))
                continue

            children = [ParseNode(sym) for sym in production]
            if node is not None:
                node.children.extend(children)
            for sym, child in zip(reversed(production), reversed(children)):
                stack.append((sym, child))

        return ParseResult(
            accepted=False,
            trace=steps,
            tree=None,
            error="internal error: stack emptied without reaching the end marker",
        )
