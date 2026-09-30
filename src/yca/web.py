"""Browser front end for the Yaounde urban-speech analyzer.

Like the desktop window, this is a *view* only: every verdict, token, tree,
trace and statistic it serves comes from the same :class:`~yca.pipeline.Analyzer`
the command line uses, so the three front ends cannot disagree.

Run it with::

    python -m yca web

The server is built on :mod:`http.server` from the standard library, so the
project still installs with no third-party packages.  That is deliberate: a
marker can clone the repository and run it on a bare Python.

The HTTP surface is small and entirely documented here:

==========================  =========================================
``GET  /``                  the single-page application
``GET  /app.css``           stylesheet
``GET  /app.js``            client script
``GET  /assets/logo.png``   the crest, used for the splash and favicon
``GET  /api/bootstrap``     grammar, corpus, statistics, examples
``POST /api/analyze``       analyze one transcription
==========================  =========================================
"""

from __future__ import annotations

import json
import socket
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, corpus
from .analysis import frequency_report
from .grammar import EPSILON
from .grammar_def import (
    DOCUMENTED_CONFLICTS,
    PreparedGrammar,
    prepare,
    undocumented_conflicts,
)
from .parser import ParseNode
from .pipeline import Analyzer, StatementResult
from .suggest import corrections

#: Where the static files live.
ASSETS = Path(__file__).resolve().parent / "webassets"

#: Crest shown on the splash screen and used as the favicon.
ICON_NAME = "cc.png"

#: The largest request body we will read, so a stray client cannot exhaust
#: memory.  A transcription is a sentence; 64 KiB is already absurd.
MAX_BODY = 64 * 1024

#: The longest transcription we will analyze.  The parse trace grows with the
#: input, so this bounds the response as well as the work.
MAX_TEXT = 2000

#: How long the splash screen holds before the application fades in.
SPLASH_MS = 3000


def find_asset(name: str) -> Path | None:
    """Locate *name* beside the package, at the project root, or in the cwd."""
    here = Path(__file__).resolve()
    for folder in (here.parent, *here.parents[1:3], Path.cwd()):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------------------
# Serialisation
#
# Each helper turns one analyzer object into plain JSON-safe data.  Keeping
# them together means the client contract is readable in one place.
# --------------------------------------------------------------------------

def token_json(index: int, token) -> dict:
    return {
        "i": index,
        "lexeme": token.lexeme,
        "normalized": token.normalized,
        "type": str(token.type),
        "languages": [str(lang) for lang in token.languages],
        "slang": token.is_slang,
        "multiword": token.is_multiword,
        "mixed": token.is_code_mixed,
        "rule": token.rule,
        "gloss": token.gloss,
        "line": token.line,
        "column": token.column,
    }


def tree_json(node: ParseNode) -> dict:
    """Nested form of the parse tree, so the browser can draw a real tree."""
    return {
        "symbol": node.symbol,
        "lexeme": node.token.lexeme if node.token is not None else None,
        "terminal": node.token is not None,
        "epsilon": node.symbol == EPSILON,
        "children": [tree_json(child) for child in node.children],
    }


def derivation_steps(result: StatementResult, grammar: PreparedGrammar) -> list[str]:
    """Replay the parse trace as a leftmost derivation.

    The trace records which production the parser output at each step; applying
    those productions to the sentential form, always at the leftmost matching
    nonterminal, reconstructs the derivation the report describes.
    """
    if result.parse.tree is None:
        return []

    base = grammar.after_left_factoring
    form = [base.start]
    lines = [base.start]
    for step in result.parse.trace:
        if not step.action.startswith("output "):
            continue
        head, _, body = step.action[len("output "):].partition(" -> ")
        head = head.strip()
        symbols = [s for s in body.split() if s and s != EPSILON]
        for i, symbol in enumerate(form):
            if symbol == head:
                form[i:i + 1] = symbols
                break
        lines.append(" ".join(form) if form else EPSILON)
    return lines


def corrections_json(report) -> dict:
    """Serialise a :class:`~yca.suggest.CorrectionReport` for the browser."""
    return {
        "kind": report.kind,
        "headline": report.headline,
        "suggestions": [
            {
                "lexeme": s.lexeme,
                "line": s.line,
                "column": s.column,
                "advice": s.advice,
                "confident": s.confident,
                "split": list(s.split) if s.split else None,
                "replacement": s.replacement,
                "candidates": [
                    {
                        "form": c.form,
                        "type": c.token_type,
                        "languages": list(c.languages),
                        "gloss": c.gloss,
                        "score": c.score,
                        "reason": c.reason,
                        "source": c.source,
                    }
                    for c in s.candidates
                ],
            }
            for s in report.suggestions
        ],
        "hint": (
            {
                "advice": report.hint.advice,
                "message": report.hint.message,
                "atLexeme": report.hint.at_lexeme,
                "line": report.hint.line,
                "column": report.hint.column,
                "expected": [
                    {"terminal": t, "examples": report.hint.examples.get(t, [])}
                    for t in report.hint.expected
                ],
            }
            if report.hint is not None
            else None
        ),
        "proposal": report.proposal if report.has_proposal else "",
        "proposalAccepted": report.proposal_accepted,
        "proposalNote": report.proposal_note,
    }


def analysis_json(
    result: StatementResult, grammar: PreparedGrammar, analyzer: Analyzer | None = None
) -> dict:
    return {
        "text": result.text,
        "verdict": result.verdict,
        "accepted": result.accepted,
        "lexOk": result.lex_ok,
        "reason": result.reason,
        "tokens": [token_json(i, t) for i, t in enumerate(result.lex.tokens, 1)],
        "lexErrors": [
            {
                "lexeme": e.lexeme,
                "line": e.line,
                "column": e.column,
                "message": e.message,
            }
            for e in result.lex.errors
        ],
        "typeString": result.lex.type_string(),
        "tree": tree_json(result.parse.tree) if result.parse.tree else None,
        "treeText": (
            "\n".join(result.parse.tree.render()) if result.parse.tree else ""
        ),
        "trace": [
            {
                "number": s.number,
                "stack": s.stack,
                "remaining": s.remaining,
                "action": s.action,
            }
            for s in result.parse.trace
        ],
        "derivation": derivation_steps(result, grammar),
        "expected": list(result.parse.expected),
        # The correction engine turns a rejection into advice; it is given the
        # analyzer so it can re-run its own proposal instead of asserting it.
        "corrections": corrections_json(corrections(result, analyzer)),
    }


def bootstrap_json(analyzer: Analyzer, grammar: PreparedGrammar) -> dict:
    """Everything the page needs once, at start-up."""
    table = grammar.table
    results = analyzer.analyze_all(corpus.CORPUS, trace=False)
    report = frequency_report(results)

    total_tokens = report.total_tokens or 1
    total_lang = sum(report.language_counts.values()) or 1

    corpus_rows = []
    for statement, result in zip(corpus.CORPUS, results):
        corpus_rows.append({
            "sid": result.sid,
            "text": result.text,
            "topic": result.topic,
            "verdict": result.verdict,
            "accepted": result.accepted,
            "reason": result.reason,
            "gloss": statement.gloss,
            "where": statement.where,
            "when": statement.when,
            "speaker": statement.speaker,
            "kind": "corpus",
        })

    for nid, text, intent in corpus.NEGATIVE_TESTS:
        outcome = analyzer.analyze_text(text, sid=nid, trace=False)
        corpus_rows.append({
            "sid": nid,
            "text": text,
            "topic": "negative test",
            "verdict": outcome.verdict,
            # A negative test passes when it is *rejected*, so the colour of
            # the row follows the test outcome, not the parse verdict.
            "accepted": not outcome.accepted,
            "reason": outcome.reason or intent,
            "gloss": intent,
            "where": "",
            "when": "",
            "speaker": "",
            "kind": "negative",
        })

    return {
        "version": __version__,
        "splashMs": SPLASH_MS,
        "course": corpus.COURSE.replace("---", "\u2014"),
        "institution": corpus.INSTITUTION,
        "group": [{"name": m.name, "matricule": m.matricule} for m in corpus.GROUP],
        "grammar": {
            "nonterminals": len(table.grammar.rules),
            "terminals": len(table.grammar.terminals),
            "cells": len(table.table),
            "conflicts": [
                {
                    "text": str(c),
                    "nonterminal": c.nonterminal,
                    "terminal": c.terminal,
                    "chosen": f"{c.nonterminal} -> {' '.join(c.existing)}",
                    "rejected": f"{c.nonterminal} -> {' '.join(c.incoming)}",
                    # A conflict with a note is a decision we took and
                    # defended; one without is an unreviewed defect.
                    "documented": (c.nonterminal, c.terminal) in DOCUMENTED_CONFLICTS,
                    "note": DOCUMENTED_CONFLICTS.get(
                        (c.nonterminal, c.terminal), ""),
                }
                for c in table.conflicts
            ],
            "unreviewed": len(undocumented_conflicts(table)),
            "start": table.grammar.start,
        },
        "sets": [
            {
                "nt": nt,
                "first": sorted(table.first[nt]),
                "follow": sorted(table.follow[nt]),
            }
            for nt in table.grammar.rules
        ],
        "corpus": corpus_rows,
        "examples": [
            {"label": "Accepted", "text": "Chef, drop me for Carrefour Obili."},
            {"label": "Multiword", "text": "Mbom, deux mille na last price o."},
            {"label": "Elongation", "text": "Garrrrrrr, wehhhh, hmmmmm!"},
            {"label": "Unknown word", "text": "Mbom, the flurble don wibble."},
            {"label": "Bad structure", "text": "for Mokolo drop me."},
        ],
        "stats": {
            "statements": len(corpus.CORPUS),
            "accepted": report.accepted,
            "rejected": report.rejected,
            "totalTokens": report.total_tokens,
            "distinctLexemes": report.distinct_lexemes,
            "typeTokenRatio": round(report.type_token_ratio, 3),
            "slangTokens": sum(report.slang_counts.values()),
            "multiword": sum(report.multiword.values()),
            "types": [
                {"name": name, "count": n, "share": round(100 * n / total_tokens, 1)}
                for name, n in report.type_counts.most_common()
            ],
            "languages": [
                {"name": name, "count": n, "share": round(100 * n / total_lang, 1)}
                for name, n in report.language_counts.most_common()
            ],
            "variants": [
                {
                    "normalized": v.normalized,
                    "type": str(v.token_type),
                    "spellings": v.spelling_list(),
                    "total": v.total,
                }
                for v in report.varying_items()[:12]
            ],
        },
    }


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------

class _State:
    """Grammar and analyzer, built once and shared by every request.

    The LL(1) construction takes a moment, so it is done on a worker thread
    while the splash screen is showing.  Requests that arrive first simply
    wait on the same lock rather than building a second copy.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._grammar: PreparedGrammar | None = None
        self._analyzer: Analyzer | None = None
        self._bootstrap: dict | None = None

    def ensure(self) -> tuple[Analyzer, PreparedGrammar]:
        with self._lock:
            if self._analyzer is None or self._grammar is None:
                self._grammar = prepare()
                self._analyzer = Analyzer(self._grammar)
            return self._analyzer, self._grammar

    def bootstrap(self) -> dict:
        analyzer, grammar = self.ensure()
        with self._lock:
            if self._bootstrap is None:
                self._bootstrap = bootstrap_json(analyzer, grammar)
            return self._bootstrap

    @property
    def is_ready(self) -> bool:
        """True once the grammar is built, without blocking to find out."""
        return self._bootstrap is not None

    def warm(self) -> None:
        """Build everything ahead of the first request."""
        try:
            self.bootstrap()
        except Exception:  # pragma: no cover - defensive
            pass


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    """Routes the handful of paths the application uses."""

    server_version = f"yca/{__version__}"
    protocol_version = "HTTP/1.1"
    state: _State = _State()
    quiet = True

    # -- plumbing --------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:  # noqa: D102
        if not self.quiet:  # pragma: no cover - only when --verbose
            super().log_message(fmt, *args)

    def _send(self, body: bytes, content_type: str,
              status: int = HTTPStatus.OK, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", status)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._json({"error": f"{path.name} is missing"},
                       HTTPStatus.NOT_FOUND)
            return
        ctype = _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        self._send(path.read_bytes(), ctype)

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"

        if route in ("/", "/index.html"):
            self._file(ASSETS / "index.html")
        elif route in ("/app.css", "/app.js"):
            self._file(ASSETS / route.lstrip("/"))
        elif route in ("/assets/logo.png", "/favicon.ico"):
            icon = find_asset(ICON_NAME)
            if icon is None:
                self._send(b"", "image/png", HTTPStatus.NOT_FOUND)
            else:
                # The crest is large and never changes during a run, so it is
                # worth caching; the splash would otherwise re-fetch it.
                self._send(icon.read_bytes(), "image/png",
                           cache="public, max-age=86400")
        elif route == "/api/bootstrap":
            try:
                self._json(self.state.bootstrap())
            except Exception as exc:  # pragma: no cover - defensive
                self._json({"error": str(exc)},
                           HTTPStatus.INTERNAL_SERVER_ERROR)
        elif route == "/healthz":
            # Cheap liveness probe for the reverse proxy and for monitoring;
            # it reports whether the grammar has finished building.
            self._json({"status": "ok", "version": __version__,
                        "ready": self.state.is_ready})
        elif route == "/api/analyze":
            # Allowed as a GET too, so a result can be linked to directly.
            from urllib.parse import parse_qs
            text = parse_qs(urlparse(self.path).query).get("text", [""])[0]
            self._analyze(text)
        else:
            self._json({"error": "no such route"}, HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route != "/api/analyze":
            self._json({"error": "no such route"}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._json({"error": "request too large"},
                       HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json({"error": "body was not valid JSON"},
                       HTTPStatus.BAD_REQUEST)
            return

        self._analyze(str(payload.get("text", "")))

    def _analyze(self, text: str) -> None:
        text = text.strip()
        if not text:
            self._json({"error": "no text given"}, HTTPStatus.BAD_REQUEST)
            return
        if len(text) > MAX_TEXT:
            self._json(
                {"error": f"transcription longer than {MAX_TEXT} characters"},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        try:
            analyzer, grammar = self.state.ensure()
            result = analyzer.analyze_text(text, trace=True)
            self._json(analysis_json(result, grammar, analyzer))
        except Exception as exc:  # pragma: no cover - defensive
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def _free_port(host: str, preferred: int, tries: int = 20) -> int:
    """Return *preferred* if it is free, else the next port that is.

    Refusing to start because a stale server holds 8000 would be needlessly
    unhelpful, so we walk forward instead.
    """
    for offset in range(tries):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"no free port in {preferred}..{preferred + tries - 1}")


def build_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """Create the HTTP server, bound but not yet serving."""
    handler = type("BoundHandler", (Handler,), {"state": _State()})
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str = "127.0.0.1", port: int = 8000, *,
          open_browser: bool = True, verbose: bool = False,
          exact_port: bool = False, out=None) -> int:
    """Run the web application until interrupted or told to stop.

    On a server the port must be the one the reverse proxy expects, so
    *exact_port* disables the search for a free one: a clash should fail
    loudly rather than silently move the service somewhere nginx is not
    looking.
    """
    import signal
    import sys

    out = out or sys.stdout
    try:
        if not exact_port:
            port = _free_port(host, port)
        httpd = build_server(host, port)
    except OSError as exc:
        print(f"Could not start the server: {exc}", file=out)
        return 1

    httpd.RequestHandlerClass.quiet = not verbose  # type: ignore[attr-defined]
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "::") else host
    url = f"http://{shown}:{port}/"

    # Build the grammar straight away so the first analysis is instant; on a
    # desktop this happens while the splash screen is still on screen.
    threading.Thread(
        target=httpd.RequestHandlerClass.state.warm,  # type: ignore[attr-defined]
        daemon=True,
    ).start()

    print(f"Yaounde Urban-Speech Analyzer is serving at {url}", file=out)
    print("Press Ctrl+C to stop.", file=out)
    try:
        out.flush()
    except Exception:  # pragma: no cover - not every stream flushes
        pass

    # systemd stops a unit with SIGTERM, so shut down cleanly on it rather
    # than being killed mid-response.
    def _stop(_signum, _frame):  # pragma: no cover - signal path
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _stop)
            except ValueError:  # pragma: no cover - not on the main thread
                pass

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        pass
    finally:
        httpd.server_close()
        print("Stopped.", file=out)
    return 0


def main() -> int:  # pragma: no cover - convenience entry point
    return serve()
