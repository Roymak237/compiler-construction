"""Command-line interface for the Yaounde urban-speech analyzer.

Run ``python -m yca --help`` for the list of sub-commands.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import analysis, corpus
from .analysis import distinct_token_inventory, frequency_report, token_table
from .grammar import END, EPSILON
from .grammar_def import DOCUMENTED_CONFLICTS, prepare, undocumented_conflicts
from .lexspec import regex_documentation, vocabulary_size
from .pipeline import Analyzer, StatementResult
from .render import bullet, heading, table, wrap
from .tokens import TokenType


# --------------------------------------------------------------------------
# Shared output pieces
# --------------------------------------------------------------------------

def _banner(out) -> None:
    """Reserved for a run-time banner.

    The provenance notice that used to appear here was removed at the
    group's request.  ``corpus.provenance_warning()`` still reports the
    state of the corpus for anyone who wants to check it.
    """
    return None


def _print_statement(result: StatementResult, out, *, show_trace: bool,
                     show_tree: bool) -> None:
    print(heading(f"[{result.sid}] {result.text}", 2), file=out)
    print(f"topic   : {result.topic}", file=out)
    print(f"verdict : {result.verdict}", file=out)
    if result.reason:
        print(f"reason  : {result.reason}", file=out)

    print(file=out)
    print(
        table(
            ["#", "lexeme", "token", "language", "slang", "rule", "gloss"],
            token_table(result),
        ),
        file=out,
    )
    print(f"\ntoken stream: {result.lex.type_string()} {END}", file=out)

    if show_tree and result.parse.tree is not None:
        print(heading("Parse tree", 3), file=out)
        print(str(result.parse.tree), file=out)

    if show_trace and result.parse.trace:
        print(heading("Parse trace", 3), file=out)
        print(
            table(
                ["#", "stack", "remaining input", "action"],
                [
                    (str(s.number), s.stack, s.remaining, s.action)
                    for s in result.parse.trace
                ],
            ),
            file=out,
        )


# --------------------------------------------------------------------------
# Sub-commands
# --------------------------------------------------------------------------

def cmd_lex(args, out) -> int:
    analyzer = Analyzer()
    result = analyzer.analyze_text(args.text, trace=False)
    print(
        table(
            ["#", "lexeme", "token", "language", "slang", "rule", "gloss"],
            token_table(result),
        ),
        file=out,
    )
    print(f"\ntoken stream: {result.lex.type_string()} {END}", file=out)
    if result.lex.errors:
        print(heading("Lexical errors", 3), file=out)
        print(bullet(str(e) for e in result.lex.errors), file=out)
        return 1
    return 0


def cmd_parse(args, out) -> int:
    analyzer = Analyzer()
    result = analyzer.analyze_text(args.text, trace=True)
    _print_statement(result, out, show_trace=args.trace, show_tree=not args.no_tree)
    return 0 if result.accepted else 1


def cmd_grammar(args, out) -> int:
    prepared = prepare()

    print(heading("1. Grammar as first written", 1), file=out)
    print(wrap(
        "This is the grammar written directly from the corpus. It is "
        "deliberately not yet LL(1): ClauseList is left recursive, and the two "
        "Clause productions share the prefix Subj."
    ), file=out)
    print(file=out)
    print(prepared.base.format(), file=out)

    print(heading("2. After removing left recursion", 1), file=out)
    if prepared.recursion_steps:
        for step in prepared.recursion_steps:
            print(f"\n{step.nonterminal}: {step.note}", file=out)
            print(bullet(step.before, "    from  "), file=out)
            print(bullet(step.after, "    to    "), file=out)
    else:
        print("No left recursion was present.", file=out)
    print(file=out)
    print(prepared.after_left_recursion.format(), file=out)

    print(heading("3. After left factoring", 1), file=out)
    if prepared.factoring_steps:
        for step in prepared.factoring_steps:
            print(f"\n{step.nonterminal}: {step.note}", file=out)
            print(bullet(step.before, "    from  "), file=out)
            print(bullet(step.after, "    to    "), file=out)
    else:
        print("No common prefixes were present.", file=out)
    print(file=out)
    print(prepared.final.format(), file=out)

    print(heading("4. Numbered productions of the final grammar", 1), file=out)
    print("\n".join(prepared.final.numbered_productions()), file=out)

    print(heading("5. FIRST and FOLLOW sets", 1), file=out)
    rows = []
    for nt in prepared.final.nonterminals:
        rows.append(
            (
                nt,
                "{ " + ", ".join(sorted(prepared.table.first[nt])) + " }",
                "{ " + ", ".join(sorted(prepared.table.follow[nt])) + " }",
            )
        )
    print(table(["nonterminal", "FIRST", "FOLLOW"], rows), file=out)

    print(heading("6. LL(1) parsing table", 1), file=out)
    if args.matrix:
        print(_format_ll1_matrix(prepared), file=out)
    else:
        print(
            wrap(
                "Listed one filled cell per row, which stays readable in a "
                "terminal. Use --matrix for the full grid, or read the "
                "generated report."
            ),
            file=out,
        )
        print(file=out)
        print(_format_ll1_cells(prepared), file=out)

    print(heading("7. Conflicts", 1), file=out)
    if not prepared.table.conflicts:
        print("None. The grammar is LL(1).", file=out)
    else:
        for conflict in prepared.table.conflicts:
            key = (conflict.nonterminal, conflict.terminal)
            note = DOCUMENTED_CONFLICTS.get(key)
            status = "reviewed and resolved" if note else "UNRESOLVED DEFECT"
            print(f"\n{conflict}  [{status}]", file=out)
            if note:
                print(wrap(note, 76, indent="    "), file=out)
        remaining = undocumented_conflicts(prepared.table)
        print(
            f"\n{len(prepared.table.conflicts)} conflict(s), "
            f"{len(remaining)} unreviewed.",
            file=out,
        )
    return 0


def _format_ll1_matrix(prepared) -> str:
    """The parse table as a full nonterminal x terminal grid."""
    grammar = prepared.final
    terminals = sorted(grammar.terminals) + [END]
    used = [
        t for t in terminals
        if any((nt, t) in prepared.table.table for nt in grammar.nonterminals)
    ]
    rows = []
    for nt in grammar.nonterminals:
        row = [nt]
        for t in used:
            prod = prepared.table.lookup(nt, t)
            row.append(" ".join(prod) if prod else "")
        rows.append(row)
    return table(["M[N, t]"] + used, rows)


def _format_ll1_cells(prepared) -> str:
    """The parse table as one row per filled cell."""
    grammar = prepared.final
    rows = []
    for nt in grammar.nonterminals:
        for t in sorted(grammar.terminals) + [END]:
            prod = prepared.table.lookup(nt, t)
            if prod is not None:
                rows.append((nt, t, f"{nt} -> {' '.join(prod)}"))
    return table(["nonterminal", "lookahead", "production to apply"], rows)


def cmd_corpus(args, out) -> int:
    _banner(out)
    analyzer = Analyzer()
    results = analyzer.analyze_all(corpus.CORPUS, trace=False)

    rows = [
        (r.sid, r.topic, r.verdict, r.text)
        for r in results
    ]
    print(heading("Corpus", 1), file=out)
    print(table(["id", "topic", "verdict", "transcription"], rows), file=out)

    for r in results:
        if not r.accepted:
            print(f"\n{r.sid}: {r.reason}", file=out)

    report = frequency_report(results)
    print(
        f"\n{report.accepted}/{len(results)} accepted, "
        f"{report.total_tokens} tokens, "
        f"{report.distinct_lexemes} distinct lexical items.",
        file=out,
    )
    return 0 if report.rejected == 0 else 1


def cmd_freq(args, out) -> int:
    analyzer = Analyzer()
    results = analyzer.analyze_all(corpus.CORPUS, trace=False)
    report = frequency_report(results)

    print(heading("Token type frequency", 1), file=out)
    print(
        table(
            ["token type", "count", "share"],
            [
                (t, str(n), f"{100 * n / report.total_tokens:.1f}%")
                for t, n in report.type_counts.most_common()
            ],
        ),
        file=out,
    )

    print(heading("Most frequent lexical items", 1), file=out)
    print(
        table(
            ["lexeme", "count", "token type", "spellings attested"],
            [
                (
                    norm,
                    str(count),
                    str(report.variants[norm].token_type),
                    report.variants[norm].spelling_list(),
                )
                for norm, count in report.top_lexemes(args.top)
            ],
        ),
        file=out,
    )

    print(heading("Spelling and form variation", 1), file=out)
    varying = report.varying_items()
    if varying:
        print(
            table(
                ["lexeme", "forms", "total", "attested spellings"],
                [
                    (v.normalized, str(v.variation), str(v.total), v.spelling_list())
                    for v in varying
                ],
            ),
            file=out,
        )
    else:
        print(
            wrap(
                "No lexical item appears with more than one spelling in this "
                "corpus. That is expected for a small, carefully transcribed "
                "set; variation shows up once the corpus grows or once several "
                "transcribers contribute."
            ),
            file=out,
        )

    print(heading("Language distribution", 1), file=out)
    total_lang = sum(report.language_counts.values())
    print(
        table(
            ["language", "tokens", "share"],
            [
                (lang, str(n), f"{100 * n / total_lang:.1f}%")
                for lang, n in report.language_counts.most_common()
            ],
        ),
        file=out,
    )

    print(heading("Slang and Camfranglais", 1), file=out)
    print(
        table(
            ["lexeme", "count"],
            [(k, str(v)) for k, v in report.slang_counts.most_common()],
        ),
        file=out,
    )

    print(heading("Multiword lexemes recognised as one token", 1), file=out)
    print(
        table(
            ["lexeme", "count"],
            [(k, str(v)) for k, v in report.multiword.most_common()],
        ),
        file=out,
    )

    print(heading("Code-mixing per statement", 1), file=out)
    print(
        table(
            ["statement", "languages drawn on"],
            [(sid, ", ".join(langs)) for sid, langs in report.mixed_statements],
        ),
        file=out,
    )
    print(
        f"\n{len(report.mixed_statements)} of {len(results)} statements draw on "
        f"more than one language.",
        file=out,
    )

    if report.unknown:
        print(heading("Unrecognised lexemes", 1), file=out)
        print(
            table(
                ["lexeme", "count"],
                [(k, str(v)) for k, v in report.unknown.most_common()],
            ),
            file=out,
        )
    return 0


def cmd_spec(args, out) -> int:
    print(heading("Lexical rules, in application order", 1), file=out)
    print(
        table(
            ["rule", "regular expression / method", "token type"],
            regex_documentation(),
        ),
        file=out,
    )
    print(heading("Declared vocabulary size by token type", 1), file=out)
    print(
        table(
            ["token type", "entries"],
            [(k, str(v)) for k, v in vocabulary_size().items()],
        ),
        file=out,
    )
    print(heading("Token types", 1), file=out)
    descriptions = {
        TokenType.VOC: "vocative / address term",
        TokenType.NOUN: "noun, including place names",
        TokenType.PRON: "pronoun",
        TokenType.DET: "determiner",
        TokenType.NUM: "numeral or money amount",
        TokenType.ADJ: "adjective",
        TokenType.ADV: "adverbial",
        TokenType.VERB: "lexical verb",
        TokenType.AUX: "aspect or modal marker",
        TokenType.NEG: "negation",
        TokenType.PREP: "preposition or directional marker",
        TokenType.COP: "copula",
        TokenType.CONJ: "coordinator",
        TokenType.INTERJ: "interjection or discourse cry",
        TokenType.PART: "post-nominal particle",
        TokenType.SEP: "internal separator",
        TokenType.TERM: "sentence terminator",
        TokenType.UNKNOWN: "outside the specification (always reported)",
    }
    print(
        table(
            ["token", "description"],
            [(str(k), v) for k, v in descriptions.items()],
        ),
        file=out,
    )
    return 0


def cmd_test(args, out) -> int:
    _banner(out)
    analyzer = Analyzer()

    print(heading("Positive tests: corpus statements", 1), file=out)
    results = analyzer.analyze_all(corpus.CORPUS, trace=False)
    rows = [(r.sid, r.verdict, r.text, r.reason or "") for r in results]
    print(table(["id", "result", "transcription", "reason"], rows), file=out)
    positives_ok = sum(1 for r in results if r.accepted)

    print(heading("Negative tests: expected rejections", 1), file=out)
    neg_rows = []
    negatives_ok = 0
    for sid, text, why in corpus.NEGATIVE_TESTS:
        r = analyzer.analyze_text(text, sid=sid, trace=False)
        ok = not r.accepted
        negatives_ok += ok
        neg_rows.append(
            (sid, text, why, "rejected" if ok else "ACCEPTED (unexpected)",
             r.reason[:60])
        )
    print(
        table(["id", "input", "why it should fail", "result", "reason"], neg_rows),
        file=out,
    )

    total = len(results) + len(corpus.NEGATIVE_TESTS)
    passed = positives_ok + negatives_ok
    print(
        f"\n{passed}/{total} checks passed "
        f"({positives_ok}/{len(results)} accepted, "
        f"{negatives_ok}/{len(corpus.NEGATIVE_TESTS)} correctly rejected).",
        file=out,
    )
    return 0 if passed == total else 1


def cmd_show(args, out) -> int:
    analyzer = Analyzer()
    wanted = {s.upper() for s in args.ids} if args.ids else None
    for statement in corpus.CORPUS:
        if wanted and statement.sid.upper() not in wanted:
            continue
        result = analyzer.analyze_statement(statement, trace=True)
        _print_statement(result, out, show_trace=args.trace, show_tree=True)
        print(file=out)
    return 0


def cmd_repl(args, out) -> int:
    analyzer = Analyzer()
    print("Yaounde urban-speech analyzer. Type a statement, or 'quit'.", file=out)
    while True:
        print("\n> ", end="", file=out)
        out.flush()
        try:
            text = input().strip()
        except (EOFError, KeyboardInterrupt):
            print(file=out)
            return 0
        if text.lower() in {"quit", "exit", "q"}:
            return 0
        if not text:
            continue
        result = analyzer.analyze_text(text, trace=args.trace)
        _print_statement(result, out, show_trace=args.trace, show_tree=True)


#: LaTeX engines tried, in order, when --pdf is given, with the number of
#: passes each needs.  pdflatex comes first because every TeX distribution has
#: it; it needs two passes before the table of contents resolves.  latexmk is
#: last because it manages its own reruns but depends on Perl, which is not
#: always installed alongside MiKTeX.
_LATEX_ENGINES: tuple[tuple[str, list[str], int], ...] = (
    ("pdflatex", ["-interaction=nonstopmode"], 2),
    ("tectonic", [], 1),
    ("latexmk", ["-pdf", "-interaction=nonstopmode"], 1),
)


def _latex_errors(log: Path) -> str:
    """The error lines from a LaTeX log, if there are any."""
    if not log.exists():
        return ""
    text = log.read_text(encoding="utf-8", errors="replace")
    lines = [l for l in text.splitlines() if l.startswith("! ")]
    return "\n".join(lines[:10])


def cmd_gui(args, out) -> int:
    """Open the desktop application.

    Tkinter is in the standard library but is packaged separately on some
    Linux distributions, so an absent Tk is reported as an instruction
    rather than as a traceback.
    """
    try:
        from .gui import main as gui_main
    except ImportError as exc:
        print(f"Cannot start the GUI: {exc}", file=out)
        print("The command line remains fully available; try 'yca repl'.",
              file=out)
        return 1
    return gui_main()


def cmd_web(args, out) -> int:
    """Serve the browser application.

    Unlike the Tkinter window this needs no display, so it is the front end
    to use over SSH or on a server.
    """
    from .web import serve

    return serve(
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        verbose=args.verbose,
        exact_port=args.exact_port,
        out=out,
    )


def _compile_pdf(path: Path, out) -> int:
    """Compile *path* to PDF with whichever LaTeX engine is installed.

    Each engine is tried in turn; failure of one is not fatal, because an
    engine can be present but unusable -- latexmk without Perl, for instance.
    """
    import shutil
    import subprocess

    pdf = path.with_suffix(".pdf")
    attempts: list[str] = []

    for name, flags, passes in _LATEX_ENGINES:
        exe = shutil.which(name)
        if exe is None:
            continue

        failure = ""
        for _ in range(passes):
            proc = subprocess.run(
                [exe, *flags, path.name],
                cwd=path.parent,
                capture_output=True,
                text=True,
                errors="replace",
            )
            if proc.returncode != 0:
                detail = (
                    _latex_errors(path.with_suffix(".log"))
                    or (proc.stderr or proc.stdout or "").strip()[-600:]
                    or "no diagnostic produced"
                )
                failure = f"{name} exited {proc.returncode}:\n{detail}"
                break

        if not failure and pdf.exists():
            print(f"PDF written to {pdf} (via {name})", file=out)
            return 0
        attempts.append(failure or f"{name} produced no PDF")

    if attempts:
        print("Could not compile the LaTeX source.\n", file=out)
        for attempt in attempts:
            print(attempt + "\n", file=out)
        return 1

    tried = ", ".join(name for name, _, _ in _LATEX_ENGINES)
    print(
        wrap(
            "No LaTeX engine found on PATH (looked for " + tried + "). "
            "The .tex file has been written but not compiled. Install "
            "TeX Live, MiKTeX or Tectonic, or compile it elsewhere.",
            76,
        ),
        file=out,
    )
    return 1


def cmd_report(args, out) -> int:
    from .report import write_report

    path = write_report(args.output)
    print(f"LaTeX report written to {path}", file=out)

    status = 0
    if args.pdf:
        status = _compile_pdf(path, out)
    else:
        print(
            f"Compile with: cd {path.parent} && pdflatex {path.name} "
            f"(twice), or rerun with --pdf.",
            file=out,
        )

    return status


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yca",
        description="Lexical and syntactic analyzer for informal Yaounde speech.",
    )
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("lex", help="tokenize one statement")
    s.add_argument("text")
    s.set_defaults(func=cmd_lex)

    s = sub.add_parser("parse", help="tokenize and parse one statement")
    s.add_argument("text")
    s.add_argument("--trace", action="store_true", help="show the parse trace")
    s.add_argument("--no-tree", action="store_true", help="hide the parse tree")
    s.set_defaults(func=cmd_parse)

    s = sub.add_parser("grammar", help="show the grammar, transformations and table")
    s.add_argument("--matrix", action="store_true",
                   help="print the parse table as a full grid (very wide)")
    s.set_defaults(func=cmd_grammar)

    s = sub.add_parser("corpus", help="analyze every corpus statement")
    s.set_defaults(func=cmd_corpus)

    s = sub.add_parser("freq", help="token frequency and variation analysis")
    s.add_argument("--top", type=int, default=25)
    s.set_defaults(func=cmd_freq)

    s = sub.add_parser("spec", help="show the lexical specification")
    s.set_defaults(func=cmd_spec)

    s = sub.add_parser("test", help="run positive and negative test cases")
    s.set_defaults(func=cmd_test)

    s = sub.add_parser("show", help="full detail for corpus statements")
    s.add_argument("ids", nargs="*", help="statement ids, e.g. S01 S02")
    s.add_argument("--trace", action="store_true")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("repl", help="interactive analyzer")
    s.add_argument("--trace", action="store_true")
    s.set_defaults(func=cmd_repl)

    s = sub.add_parser("gui", help="open the desktop application")
    s.set_defaults(func=cmd_gui)

    s = sub.add_parser("web", help="serve the browser application")
    s.add_argument("--host", default="127.0.0.1",
                   help="interface to bind (use 0.0.0.0 to expose it)")
    s.add_argument("-p", "--port", type=int, default=8000,
                   help="preferred port; the next free one is used if taken")
    s.add_argument("--exact-port", action="store_true",
                   help="fail if the port is taken instead of moving to "
                        "the next one (use this behind a reverse proxy)")
    s.add_argument("--no-browser", action="store_true",
                   help="do not open a browser window automatically")
    s.add_argument("--verbose", action="store_true",
                   help="log every request")
    s.set_defaults(func=cmd_web)

    s = sub.add_parser("report", help="generate the full written report (LaTeX)")
    s.add_argument("-o", "--output", default="docs/report.tex")
    s.add_argument(
        "--pdf",
        action="store_true",
        help="also compile the .tex to PDF if a LaTeX engine is installed",
    )
    s.set_defaults(func=cmd_report)

    return p


def _safe_stdout():
    """Return a stdout that survives a non-UTF-8 Windows console.

    The grammar uses the real epsilon character. Legacy PowerShell and cmd
    consoles run a code page that cannot render it, which would otherwise turn
    every empty production into mojibake. We test the *console's* encoding
    before touching the stream: if it cannot represent epsilon we transliterate
    on the way out. Files are always written as UTF-8 regardless.
    """
    stream = sys.stdout
    console_encoding = getattr(stream, "encoding", None) or "ascii"

    try:
        EPSILON.encode(console_encoding)
    except (UnicodeEncodeError, LookupError):
        return _Transliterating(stream, console_encoding)

    try:
        stream.reconfigure(encoding=console_encoding, errors="replace")
    except Exception:  # pragma: no cover - older stdout objects
        pass
    return stream


class _Transliterating:
    """Minimal stdout proxy that replaces characters the console cannot show."""

    _MAP = {
        EPSILON: "<eps>",
        "\u2019": "'",
        "\u2018": "'",
        "\u2014": "--",
        "\u2013": "-",
    }

    def __init__(self, stream, encoding: str) -> None:
        self._stream = stream
        self._encoding = encoding

    def write(self, text: str) -> int:
        for src, dst in self._MAP.items():
            text = text.replace(src, dst)
        safe = text.encode(self._encoding, "replace").decode(self._encoding)
        return self._stream.write(safe)

    def flush(self) -> None:
        self._stream.flush()


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a subcommand, or open the GUI when given none.

    Launching with no arguments -- double-clicking the package, or pressing
    Run in an editor -- opens the desktop window, which is what a user of a
    graphical application expects. Every subcommand remains available.
    """
    args = build_parser().parse_args(argv)
    out = _safe_stdout()
    if getattr(args, "func", None) is None:
        return cmd_gui(args, out)
    return args.func(args, out)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
