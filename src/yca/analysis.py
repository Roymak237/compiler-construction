"""Token frequency, spelling variation and code-mixing statistics.

These are the numbers the assignment asks for under "Analyze token frequency
and variation".  Variation is measured by grouping the raw lexemes under their
folded form, so ``reseau`` / ``réseau`` / ``Reseau`` are counted as one lexical
item with three attested spellings -- the point being that the transcription is
never altered, only indexed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .corpus import Statement
from .pipeline import StatementResult
from .tokens import Language, Token, TokenType


@dataclass
class VariantGroup:
    """One lexical item and every spelling attested for it."""

    normalized: str
    token_type: TokenType
    spellings: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.spellings.values())

    @property
    def variation(self) -> int:
        return len(self.spellings)

    def spelling_list(self) -> str:
        return ", ".join(
            f"{s} ({n})" for s, n in self.spellings.most_common()
        )


@dataclass
class CorpusReport:
    """Aggregated lexical statistics over a set of analyzed statements."""

    results: list[StatementResult]
    type_counts: Counter
    lexeme_counts: Counter
    variants: dict[str, VariantGroup]
    language_counts: Counter
    slang_counts: Counter
    multiword: Counter
    code_mixed_tokens: Counter
    mixed_statements: list[tuple[str, list[str]]]
    unknown: Counter

    # -- derived numbers --------------------------------------------------

    @property
    def total_tokens(self) -> int:
        return sum(self.type_counts.values())

    @property
    def distinct_lexemes(self) -> int:
        return len(self.variants)

    @property
    def accepted(self) -> int:
        return sum(1 for r in self.results if r.accepted)

    @property
    def rejected(self) -> int:
        return len(self.results) - self.accepted

    @property
    def type_token_ratio(self) -> float:
        return self.distinct_lexemes / self.total_tokens if self.total_tokens else 0.0

    def varying_items(self) -> list[VariantGroup]:
        """Lexical items attested with more than one spelling."""
        return sorted(
            (v for v in self.variants.values() if v.variation > 1),
            key=lambda v: (-v.variation, -v.total, v.normalized),
        )

    def top_lexemes(self, n: int = 20) -> list[tuple[str, int]]:
        return self.lexeme_counts.most_common(n)


def _iter_tokens(results: list[StatementResult]):
    for result in results:
        for token in result.lex.tokens:
            yield result, token


def frequency_report(results: list[StatementResult]) -> CorpusReport:
    """Build the full lexical report from analyzed statements."""
    type_counts: Counter = Counter()
    lexeme_counts: Counter = Counter()
    variants: dict[str, VariantGroup] = {}
    language_counts: Counter = Counter()
    slang_counts: Counter = Counter()
    multiword: Counter = Counter()
    code_mixed_tokens: Counter = Counter()
    unknown: Counter = Counter()
    per_statement_languages: dict[str, set[Language]] = defaultdict(set)

    for result, token in _iter_tokens(results):
        type_counts[str(token.type)] += 1
        lexeme_counts[token.normalized] += 1

        group = variants.get(token.normalized)
        if group is None:
            group = VariantGroup(token.normalized, token.type)
            variants[token.normalized] = group
        group.spellings[token.lexeme] += 1

        for language in token.languages:
            language_counts[str(language)] += 1
            if language not in (Language.SYMBOL, Language.UNKNOWN):
                per_statement_languages[result.sid].add(language)

        if token.is_slang:
            slang_counts[token.normalized] += 1
        if token.is_multiword:
            multiword[token.normalized] += 1
        if token.is_code_mixed:
            code_mixed_tokens[token.normalized] += 1
        if token.type is TokenType.UNKNOWN:
            unknown[token.lexeme] += 1

    mixed_statements = sorted(
        (
            (sid, sorted(str(l) for l in langs))
            for sid, langs in per_statement_languages.items()
            if len(langs) > 1
        ),
        key=lambda item: item[0],
    )

    return CorpusReport(
        results=results,
        type_counts=type_counts,
        lexeme_counts=lexeme_counts,
        variants=variants,
        language_counts=language_counts,
        slang_counts=slang_counts,
        multiword=multiword,
        code_mixed_tokens=code_mixed_tokens,
        mixed_statements=mixed_statements,
        unknown=unknown,
    )


def analyze_corpus(statements: list[Statement]) -> CorpusReport:
    """Analyze a corpus end to end and return its lexical report."""
    from .pipeline import Analyzer

    analyzer = Analyzer()
    return frequency_report(analyzer.analyze_all(statements))


def token_table(result: StatementResult) -> list[tuple[str, ...]]:
    """Rows for the per-statement token table printed in the report."""
    rows: list[tuple[str, ...]] = []
    for i, token in enumerate(result.lex.tokens, 1):
        rows.append(
            (
                str(i),
                token.lexeme,
                str(token.type),
                "/".join(str(l) for l in token.languages),
                "yes" if token.is_slang else "",
                token.rule,
                token.gloss,
            )
        )
    return rows


def distinct_token_inventory(results: list[StatementResult]) -> list[Token]:
    """One representative token per distinct lexical item, sorted by type."""
    seen: dict[str, Token] = {}
    for _, token in _iter_tokens(results):
        seen.setdefault(f"{token.type}:{token.normalized}", token)
    return sorted(seen.values(), key=lambda t: (str(t.type), t.normalized))
