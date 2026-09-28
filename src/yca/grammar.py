"""Context-free grammar machinery: CFG, transformations, FIRST/FOLLOW, LL(1).

Everything here is computed, not hard-coded.  The report prints the tables this
module derives, so the numbers in the report can never drift away from the
parser's actual behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EPSILON = "ε"
END = "$"


def _body(symbols: list[str]) -> tuple[str, ...]:
    """Build a production body, dropping EPSILON from non-empty sequences."""
    real = [s for s in symbols if s != EPSILON]
    return tuple(real) if real else (EPSILON,)


@dataclass
class Grammar:
    """A context-free grammar over string symbols."""

    start: str
    #: ``nonterminal -> list of productions``; each production is a tuple of
    #: symbols, and ``(EPSILON,)`` denotes the empty production.
    rules: dict[str, list[tuple[str, ...]]] = field(default_factory=dict)

    # -- basic queries ----------------------------------------------------

    @property
    def nonterminals(self) -> list[str]:
        return list(self.rules.keys())

    @property
    def terminals(self) -> list[str]:
        seen: list[str] = []
        for prods in self.rules.values():
            for prod in prods:
                for sym in prod:
                    if sym != EPSILON and sym not in self.rules and sym not in seen:
                        seen.append(sym)
        return seen

    def is_nonterminal(self, symbol: str) -> bool:
        return symbol in self.rules

    def productions(self) -> list[tuple[str, tuple[str, ...]]]:
        return [(head, prod) for head, prods in self.rules.items() for prod in prods]

    def clone(self) -> "Grammar":
        return Grammar(self.start, {h: list(p) for h, p in self.rules.items()})

    # -- presentation -----------------------------------------------------

    def format(self) -> str:
        lines = []
        width = max(len(h) for h in self.rules)
        for head, prods in self.rules.items():
            bodies = " | ".join(" ".join(p) for p in prods)
            lines.append(f"{head:<{width}} -> {bodies}")
        return "\n".join(lines)

    def numbered_productions(self) -> list[str]:
        out = []
        for i, (head, prod) in enumerate(self.productions(), 1):
            out.append(f"{i:>2}. {head} -> {' '.join(prod)}")
        return out


# --------------------------------------------------------------------------
# Transformation 1: left-recursion removal
# --------------------------------------------------------------------------

@dataclass
class TransformStep:
    """A single recorded transformation, for the report's derivation trail."""

    kind: str
    nonterminal: str
    before: list[str]
    after: list[str]
    note: str = ""


def remove_left_recursion(grammar: Grammar) -> tuple[Grammar, list[TransformStep]]:
    """Eliminate immediate left recursion (Aho/Sethi/Ullman Algorithm 4.1).

    Returns the new grammar and a log of what changed.  If the grammar has no
    left recursion the log is empty -- and the report says so explicitly rather
    than inventing a transformation.
    """
    out = Grammar(grammar.start, {})
    steps: list[TransformStep] = []

    for head, prods in grammar.rules.items():
        recursive = [p for p in prods if p and p[0] == head]
        other = [p for p in prods if not (p and p[0] == head)]

        if not recursive:
            out.rules[head] = list(prods)
            continue

        tail = f"{head}'"
        while tail in grammar.rules or tail in out.rules:
            tail += "'"

        before = [f"{head} -> {' '.join(p)}" for p in prods]
        new_head = [_body(list(p) + [tail]) for p in other] or [(tail,)]
        new_tail = [_body(list(p[1:]) + [tail]) for p in recursive] + [(EPSILON,)]

        out.rules[head] = new_head
        out.rules[tail] = new_tail
        steps.append(
            TransformStep(
                kind="left recursion",
                nonterminal=head,
                before=before,
                after=[f"{head} -> {' '.join(p)}" for p in new_head]
                + [f"{tail} -> {' '.join(p)}" for p in new_tail],
                note=f"immediate left recursion on {head}, introduced {tail}",
            )
        )

    return out, steps


# --------------------------------------------------------------------------
# Transformation 2: left factoring
# --------------------------------------------------------------------------

def _longest_common_prefix(prods: list[tuple[str, ...]]) -> tuple[str, ...]:
    """Longest prefix shared by at least two of *prods*."""
    best: tuple[str, ...] = ()
    for i, a in enumerate(prods):
        for b in prods[i + 1:]:
            k = 0
            while k < len(a) and k < len(b) and a[k] == b[k] and a[k] != EPSILON:
                k += 1
            if k > len(best):
                best = a[:k]
    return best


def left_factor(grammar: Grammar) -> tuple[Grammar, list[TransformStep]]:
    """Left-factor the grammar until no common prefixes remain."""
    out = grammar.clone()
    steps: list[TransformStep] = []
    changed = True

    while changed:
        changed = False
        for head in list(out.rules.keys()):
            prods = out.rules[head]
            prefix = _longest_common_prefix(prods)
            if not prefix:
                continue

            shared = [p for p in prods if p[:len(prefix)] == prefix]
            rest = [p for p in prods if p[:len(prefix)] != prefix]

            tail = f"{head}_f"
            while tail in out.rules:
                tail += "_f"

            before = [f"{head} -> {' '.join(p)}" for p in prods]
            out.rules[head] = rest + [_body(list(prefix) + [tail])]
            out.rules[tail] = [
                _body(list(p[len(prefix):])) for p in shared
            ]
            steps.append(
                TransformStep(
                    kind="left factoring",
                    nonterminal=head,
                    before=before,
                    after=[f"{head} -> {' '.join(p)}" for p in out.rules[head]]
                    + [f"{tail} -> {' '.join(p)}" for p in out.rules[tail]],
                    note=f"common prefix {' '.join(prefix)!r}, introduced {tail}",
                )
            )
            changed = True

    return out, steps


# --------------------------------------------------------------------------
# FIRST and FOLLOW
# --------------------------------------------------------------------------

def compute_first(grammar: Grammar) -> dict[str, set[str]]:
    """FIRST set for every nonterminal (fixed-point iteration)."""
    first: dict[str, set[str]] = {nt: set() for nt in grammar.rules}

    def first_of_symbol(sym: str) -> set[str]:
        if sym == EPSILON:
            return {EPSILON}
        if grammar.is_nonterminal(sym):
            return first[sym]
        return {sym}

    changed = True
    while changed:
        changed = False
        for head, prods in grammar.rules.items():
            for prod in prods:
                before = len(first[head])
                if prod == (EPSILON,):
                    first[head].add(EPSILON)
                else:
                    nullable_all = True
                    for sym in prod:
                        fs = first_of_symbol(sym)
                        first[head] |= fs - {EPSILON}
                        if EPSILON not in fs:
                            nullable_all = False
                            break
                    if nullable_all:
                        first[head].add(EPSILON)
                if len(first[head]) != before:
                    changed = True
    return first


def first_of_sequence(
    seq: tuple[str, ...], grammar: Grammar, first: dict[str, set[str]]
) -> set[str]:
    """FIRST of a string of grammar symbols."""
    out: set[str] = set()
    if seq == (EPSILON,) or not seq:
        return {EPSILON}
    for sym in seq:
        if sym == EPSILON:
            out.add(EPSILON)
            break
        fs = first[sym] if grammar.is_nonterminal(sym) else {sym}
        out |= fs - {EPSILON}
        if EPSILON not in fs:
            break
    else:
        out.add(EPSILON)
    return out


def compute_follow(
    grammar: Grammar, first: dict[str, set[str]]
) -> dict[str, set[str]]:
    """FOLLOW set for every nonterminal."""
    follow: dict[str, set[str]] = {nt: set() for nt in grammar.rules}
    follow[grammar.start].add(END)

    changed = True
    while changed:
        changed = False
        for head, prods in grammar.rules.items():
            for prod in prods:
                if prod == (EPSILON,):
                    continue
                for i, sym in enumerate(prod):
                    if not grammar.is_nonterminal(sym):
                        continue
                    before = len(follow[sym])
                    rest = prod[i + 1:]
                    fs = first_of_sequence(rest, grammar, first) if rest else {EPSILON}
                    follow[sym] |= fs - {EPSILON}
                    if EPSILON in fs:
                        follow[sym] |= follow[head]
                    if len(follow[sym]) != before:
                        changed = True
    return follow


# --------------------------------------------------------------------------
# LL(1) parsing table
# --------------------------------------------------------------------------

@dataclass
class LL1Conflict:
    """Two productions competing for one table cell."""

    nonterminal: str
    terminal: str
    existing: tuple[str, ...]
    incoming: tuple[str, ...]

    def __str__(self) -> str:  # pragma: no cover - display helper
        return (
            f"M[{self.nonterminal}, {self.terminal}] already holds "
            f"{self.nonterminal} -> {' '.join(self.existing)}; "
            f"cannot also add {self.nonterminal} -> {' '.join(self.incoming)}"
        )


@dataclass
class LL1Table:
    """A parse table plus the conflicts found while building it."""

    grammar: Grammar
    first: dict[str, set[str]]
    follow: dict[str, set[str]]
    table: dict[tuple[str, str], tuple[str, ...]]
    conflicts: list[LL1Conflict]

    @property
    def is_ll1(self) -> bool:
        return not self.conflicts

    def lookup(self, nonterminal: str, terminal: str) -> tuple[str, ...] | None:
        return self.table.get((nonterminal, terminal))

    def expected_terminals(self, nonterminal: str) -> list[str]:
        return sorted(t for (nt, t) in self.table if nt == nonterminal)


def build_ll1_table(grammar: Grammar) -> LL1Table:
    """Construct the LL(1) table, recording rather than hiding conflicts."""
    first = compute_first(grammar)
    follow = compute_follow(grammar, first)
    table: dict[tuple[str, str], tuple[str, ...]] = {}
    conflicts: list[LL1Conflict] = []

    for head, prods in grammar.rules.items():
        for prod in prods:
            fs = first_of_sequence(prod, grammar, first)
            targets = set(fs - {EPSILON})
            if EPSILON in fs:
                targets |= follow[head]
            for terminal in targets:
                key = (head, terminal)
                if key in table and table[key] != prod:
                    conflicts.append(
                        LL1Conflict(head, terminal, table[key], prod)
                    )
                    continue
                table[key] = prod

    return LL1Table(grammar, first, follow, table, conflicts)
