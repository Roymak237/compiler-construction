"""The grammar of the mini-language, and the pipeline that prepares it.

The grammar is written first in the shape that reflects how the utterances are
actually built, *including* a left-recursive clause list and a pair of
productions with a common prefix.  Those are not accidents: they are the inputs
to the two transformations the assignment requires, and they are removed by
:func:`prepare`, which records every step so the report can show the working.

Design of the clause
--------------------
``Chef , drop me for Obili .`` decomposes as::

    Preamble   Chef ,          address / interjection run
    Clause     drop me for Obili
    TERM       .

A clause is a (possibly empty) subject followed by either a verbal predicate or
a copular predicate -- the two share the subject, which is what makes left
factoring necessary.
"""

from __future__ import annotations

from dataclasses import dataclass

from .grammar import (
    EPSILON,
    Grammar,
    LL1Table,
    TransformStep,
    build_ll1_table,
    left_factor,
    remove_left_recursion,
)


def base_grammar() -> Grammar:
    """The grammar as first written, before any transformation."""
    return Grammar(
        start="Statement",
        rules={
            # A statement is an optional run of openers, one or more clauses,
            # and a terminator.
            "Statement": [("Preamble", "ClauseList", "TERM")],

            # Interjections and vocatives that precede the clause.
            "Preamble": [("Opener", "Preamble"), (EPSILON,)],
            "Opener": [("INTERJ", "SepOpt"), ("VOC", "SepOpt")],
            "SepOpt": [("SEP",), (EPSILON,)],

            # LEFT RECURSIVE ON PURPOSE -- removed by remove_left_recursion().
            "ClauseList": [("ClauseList", "SEP", "Clause"), ("Clause",)],

            # COMMON PREFIX ON PURPOSE -- removed by left_factor().
            "Clause": [("Subj", "VP"), ("Subj", "COP", "Items")],

            # The subject may carry a prepositional modifier
            # ("queue for station dey long"). Keeping that modifier here,
            # rather than inside NP, is what keeps the table conflict-free:
            # FOLLOW(SubjPP) is {NEG, AUX, VERB, COP}, which excludes PREP.
            "Subj": [("NP", "SubjPP"), (EPSILON,)],
            "SubjPP": [("PP",), (EPSILON,)],

            # A verbal predicate is headed by negation, an aspect marker, or
            # the verb itself.  It is never empty, so a bare terminator cannot
            # be a statement.
            "VP": [
                ("NEG", "AuxSeq", "Core"),
                ("AUX", "AuxSeq", "Core"),
                ("VERB", "Items"),
            ],
            "AuxSeq": [("AUX", "AuxSeq"), (EPSILON,)],
            "Core": [("VERB", "Items"), ("Items",)],

            # Complements and arguments share one category, so a particle or
            # a prepositional phrase is always a sibling of the noun phrase
            # rather than a child of it. The structure is flat, but it is
            # unambiguous.
            "Items": [("Item", "Items"), (EPSILON,)],
            "Item": [("ADJ",), ("ADV",), ("PART",), ("NP",), ("PP",)],

            # Noun phrases: a head plus greedy noun compounding.
            "NP": [
                ("PRON",),
                ("DET", "NGopt"),
                ("NUM", "NGopt"),
                ("NOUN", "NGopt"),
            ],
            "NGopt": [("NOUN", "NGopt"), (EPSILON,)],
            "PP": [("PREP", "NP")],
        },
    )


@dataclass
class PreparedGrammar:
    """The grammar at every stage, plus the table built from the final form."""

    base: Grammar
    after_left_recursion: Grammar
    after_left_factoring: Grammar
    recursion_steps: list[TransformStep]
    factoring_steps: list[TransformStep]
    table: LL1Table

    @property
    def final(self) -> Grammar:
        return self.after_left_factoring


def prepare() -> PreparedGrammar:
    """Run the full grammar pipeline: base -> LR-free -> factored -> table."""
    base = base_grammar()
    g1, recursion_steps = remove_left_recursion(base)
    g2, factoring_steps = left_factor(g1)
    table = build_ll1_table(g2)
    return PreparedGrammar(
        base=base,
        after_left_recursion=g1,
        after_left_factoring=g2,
        recursion_steps=recursion_steps,
        factoring_steps=factoring_steps,
        table=table,
    )


#: Conflicts we have inspected and chosen to resolve a particular way, rather
#: than leave as an unexplained defect.  Keyed by ``(nonterminal, terminal)``.
DOCUMENTED_CONFLICTS: dict[tuple[str, str], str] = {
    ("NGopt", "NOUN"): (
        "Noun-compounding ambiguity. After a noun phrase, a following NOUN "
        "could extend that phrase (Carrefour Obili as one place name) or start "
        "a new argument. The grammar is ambiguous here, exactly like the "
        "dangling-else. It is resolved in favour of the first production, "
        "NGopt -> NOUN NGopt, i.e. greedy longest-match compounding, which is "
        "the correct reading for every compound in the corpus."
    ),
}


def undocumented_conflicts(table: LL1Table) -> list:
    """Conflicts that have *not* been reviewed -- these are real defects."""
    return [
        c for c in table.conflicts
        if (c.nonterminal, c.terminal) not in DOCUMENTED_CONFLICTS
    ]
