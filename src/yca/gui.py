"""Tkinter desktop front end for the Yaounde urban-speech analyzer.

The GUI is a *view* only.  Every verdict, token, tree and trace it shows is
produced by the same :class:`~yca.pipeline.Analyzer` the command line uses,
so the two front ends cannot drift apart or disagree.

Run it with::

    python -m yca gui

Tkinter ships with CPython on Windows and macOS.  On Debian/Ubuntu it is a
separate package (``sudo apt install python3-tk``); :func:`main` reports that
clearly rather than failing with an import traceback.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path

try:  # pragma: no cover - exercised only where Tk is absent
    import tkinter as tk
    from tkinter import filedialog, font as tkfont, messagebox, ttk
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Tkinter is not available in this Python installation. On Debian or "
        "Ubuntu install it with 'sudo apt install python3-tk'; on Windows and "
        "macOS it ships with python.org builds of CPython."
    ) from exc

from . import corpus
from .analysis import frequency_report
from .grammar import END, EPSILON
from .grammar_def import prepare
from .pipeline import Analyzer, StatementResult

# --------------------------------------------------------------------------
# Palette
#
# Built out from the ink/clay/moss/slate of the LaTeX report so the
# application and the document read as one piece of work, with the extra
# tints a screen needs: hover states, borders, selection and elevation.
# --------------------------------------------------------------------------

INK = "#1F3348"          # headings, header bar
INK_DEEP = "#162637"     # header foot, pressed states
INK_SOFT = "#2C4763"     # hovered header controls
CLAY = "#B4552D"         # primary action, rejection
CLAY_HOT = "#C8612F"     # primary action, hovered
CLAY_DEEP = "#8E4223"    # primary action, pressed
MOSS = "#3F6B52"         # acceptance
SLATE = "#4A5D78"        # secondary text
MIST = "#7A8CA3"         # tertiary text on dark

PARCHMENT = "#F1EDE4"    # window background
CARD = "#FFFFFF"         # panel background
WHITE = "#FFFFFF"        # kept as an alias; some widgets read it directly
RULE = "#D8D2C6"         # borders
ZEBRA = "#F8F6F2"        # alternating rows
HOVER = "#ECE7DC"        # hovered neutral control

ACCEPT_BG = "#E4EFE8"
ACCEPT_EDGE = "#3F6B52"
REJECT_BG = "#F9E6DC"
REJECT_EDGE = "#B4552D"
IDLE_BG = "#EDE9E0"
IDLE_EDGE = "#A9B4C2"

#: Filename of the application icon, looked for beside the package and at
#: the project root.
ICON_NAME = "cc.png"


def _find_asset(name: str) -> Path | None:
    """Locate *name* beside the package, at the project root, or in the cwd."""
    here = Path(__file__).resolve()
    for folder in (here.parent, here.parents[1], here.parents[2], Path.cwd()):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Example:
    """A one-click demonstration button."""

    label: str
    text: str


#: Chosen to exercise visibly different paths: acceptance, the two distinct
#: failure kinds, multiword lexemes, and the elongation rule.
EXAMPLES: tuple[Example, ...] = (
    Example("Accepted", "Chef, drop me for Carrefour Obili."),
    Example("Multiword", "Mbom, deux mille na last price o."),
    Example("Elongation", "Garrrrrrr, wehhhh, hmmmmm!"),
    Example("Unknown word", "Mbom, the flurble don wibble."),
    Example("Bad structure", "for Mokolo drop me."),
)


class AnalyzerApp(ttk.Frame):
    """The main window."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=0)
        self.master.title("Yaounde Urban-Speech Analyzer")
        self.master.minsize(1060, 720)
        self.master.configure(background=PARCHMENT)

        self._analyzer: Analyzer | None = None
        self._grammar = None
        self._result: StatementResult | None = None
        self._ready = queue.Queue()
        #: Tk garbage-collects images that nothing references, so every
        #: PhotoImage we create has to be kept alive here.
        self._images: list[tk.PhotoImage] = []

        self._mono = tkfont.nametofont("TkFixedFont").copy()
        self._mono.configure(size=10)

        self._apply_icon()
        self._build_styles()
        self._build_widgets()
        self.grid(row=0, column=0, sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)

        # Building the LL(1) table takes a moment; do it off the UI thread so
        # the window paints immediately instead of appearing to hang.
        threading.Thread(target=self._warm_up, daemon=True).start()
        self.after(50, self._poll_ready)

    # -- branding --------------------------------------------------------

    def _load_image(self, path: Path, target: int) -> tk.PhotoImage | None:
        """Load *path* and shrink it to roughly *target* pixels square.

        Tk 8.6 reads PNG natively but only subsamples by whole-number
        factors, so the result lands near the target rather than exactly on
        it -- which is fine for a crest.
        """
        try:
            image = tk.PhotoImage(file=str(path))
        except tk.TclError:
            return None
        factor = max(1, min(image.width(), image.height()) // target)
        if factor > 1:
            image = image.subsample(factor, factor)
        self._images.append(image)
        return image

    def _apply_icon(self) -> None:
        """Set the taskbar and title-bar icon, if the artwork is present."""
        path = _find_asset(ICON_NAME)
        if path is None:
            return
        icon = self._load_image(path, 64)
        if icon is None:
            return
        try:
            # default=True applies it to every window this app opens.
            self.master.iconphoto(True, icon)
        except tk.TclError:  # pragma: no cover - platform dependent
            pass

    # -- construction ----------------------------------------------------

    def _build_styles(self) -> None:
        style = ttk.Style()
        # 'clam' honours background colours on Windows, unlike the native
        # theme.  Switching themes broadcasts <<ThemeChanged>> to every
        # widget, so only switch when we are not already on it -- otherwise
        # a second window in the same interpreter queues events against the
        # widgets of the first.
        if style.theme_use() != "clam" and "clam" in style.theme_names():
            style.theme_use("clam")

        # -- surfaces -----------------------------------------------------
        style.configure("TFrame", background=PARCHMENT)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Header.TFrame", background=INK)

        # -- text ---------------------------------------------------------
        style.configure("TLabel", background=PARCHMENT, foreground=INK)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18),
                        foreground=CARD, background=INK)
        style.configure("Tagline.TLabel", font=("Segoe UI", 9),
                        foreground=MIST, background=INK)
        style.configure("Version.TLabel", font=("Segoe UI", 8),
                        foreground=MIST, background=INK)
        style.configure("Sub.TLabel", font=("Segoe UI", 9),
                        foreground=SLATE, background=PARCHMENT)
        style.configure("Field.TLabel", font=("Segoe UI Semibold", 10),
                        foreground=INK, background=PARCHMENT)

        # -- buttons ------------------------------------------------------
        style.configure("TButton", font=("Segoe UI", 9), padding=(11, 6),
                        background=CARD, foreground=INK,
                        bordercolor=RULE, focuscolor=PARCHMENT,
                        relief="flat", borderwidth=1)
        style.map("TButton",
                  background=[("pressed", RULE), ("active", HOVER)],
                  bordercolor=[("active", SLATE)])

        style.configure("Go.TButton", font=("Segoe UI Semibold", 10),
                        padding=(22, 8), background=CLAY, foreground=CARD,
                        bordercolor=CLAY, relief="flat", borderwidth=0)
        style.map("Go.TButton",
                  background=[("pressed", CLAY_DEEP), ("active", CLAY_HOT)],
                  foreground=[("disabled", MIST)])

        # -- notebook -----------------------------------------------------
        style.configure("TNotebook", background=PARCHMENT, borderwidth=0,
                        tabmargins=(0, 4, 0, 0))
        style.configure("TNotebook.Tab", font=("Segoe UI", 9),
                        padding=(16, 8), background=PARCHMENT,
                        foreground=SLATE, borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD), ("active", HOVER)],
                  foreground=[("selected", CLAY), ("active", INK)],
                  font=[("selected", ("Segoe UI Semibold", 9))],
                  expand=[("selected", (0, 0, 0, 1))])

        # -- tables -------------------------------------------------------
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9),
                        background=PARCHMENT, foreground=INK,
                        relief="flat", padding=(6, 7))
        style.map("Treeview.Heading", background=[("active", HOVER)])
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=25,
                        background=CARD, fieldbackground=CARD,
                        foreground=INK, borderwidth=0)
        style.map("Treeview", background=[("selected", INK_SOFT)],
                  foreground=[("selected", CARD)])

        # -- scrollbars and combobox --------------------------------------
        style.configure("Vertical.TScrollbar", background=PARCHMENT,
                        troughcolor=PARCHMENT, bordercolor=PARCHMENT,
                        arrowcolor=SLATE, relief="flat")
        style.configure("Horizontal.TScrollbar", background=PARCHMENT,
                        troughcolor=PARCHMENT, bordercolor=PARCHMENT,
                        arrowcolor=SLATE, relief="flat")
        style.configure("TCombobox", fieldbackground=CARD, background=CARD,
                        foreground=INK, arrowcolor=SLATE, bordercolor=RULE,
                        padding=(8, 5))

    def _build_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        # Rows 0-1 are the header and its accent rule; row 3 is the tab
        # stack, which is the only part that should absorb extra height.
        self.rowconfigure(3, weight=1)

        self._build_header()
        self._build_input()
        self._build_tabs()
        self._build_statusbar()

    def _build_header(self) -> None:
        bar = tk.Frame(self, background=INK)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)

        # -- crest --------------------------------------------------------
        path = _find_asset(ICON_NAME)
        logo = self._load_image(path, 46) if path else None
        if logo is not None:
            tk.Label(bar, image=logo, background=INK, borderwidth=0).grid(
                row=0, column=0, rowspan=2, padx=(18, 14), pady=13)

        # -- wordmark -----------------------------------------------------
        text = tk.Frame(bar, background=INK)
        text.grid(row=0, column=1, rowspan=2, sticky="w",
                  pady=13, padx=(0 if logo is not None else 18, 0))
        tk.Label(text, text="Yaound\u00e9 Urban-Speech Analyzer",
                 font=("Segoe UI Semibold", 18), foreground=CARD,
                 background=INK).pack(anchor="w")
        tk.Label(text,
                 text="Lexical and syntactic analysis of informal "
                      "Cameroonian urban speech  \u00b7  LL(1) predictive parser",
                 font=("Segoe UI", 9), foreground=MIST,
                 background=INK).pack(anchor="w", pady=(2, 0))

        from . import __version__

        tk.Label(bar, text=f"v{__version__}", font=("Segoe UI", 9),
                 foreground=MIST, background=INK).grid(
            row=0, column=2, rowspan=2, sticky="e", padx=20)

        # A clay hairline under the header ties it to the report's accent.
        tk.Frame(self, background=CLAY, height=3).grid(
            row=1, column=0, sticky="ew")

    def _build_input(self) -> None:
        box = ttk.Frame(self, padding=(18, 14, 18, 10))
        box.grid(row=2, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)

        ttk.Label(box, text="Statement", style="Field.TLabel").grid(
            row=0, column=0, sticky="w")

        entry_row = ttk.Frame(box)
        entry_row.grid(row=1, column=0, sticky="ew", pady=(5, 8))
        entry_row.columnconfigure(0, weight=1)

        # A 1px frame behind the Entry gives a crisp border that recolours
        # on focus; tk.Entry's own highlight ring is thicker and grey.
        self._entry_edge = tk.Frame(entry_row, background=RULE, padx=1, pady=1)
        self._entry_edge.grid(row=0, column=0, sticky="ew")
        self._entry_edge.columnconfigure(0, weight=1)

        self.entry = tk.Entry(self._entry_edge, font=("Consolas", 12),
                              relief="flat", borderwidth=0,
                              background=CARD, foreground=INK,
                              insertbackground=CLAY,
                              selectbackground=INK_SOFT,
                              selectforeground=CARD)
        self.entry.grid(row=0, column=0, sticky="ew", ipady=9, ipadx=10)
        self.entry.insert(0, EXAMPLES[0].text)
        self.entry.bind("<Return>", lambda _e: self.analyze())
        self.entry.bind(
            "<FocusIn>",
            lambda _e: self._entry_edge.configure(background=CLAY))
        self.entry.bind(
            "<FocusOut>",
            lambda _e: self._entry_edge.configure(background=RULE))

        self.go = ttk.Button(entry_row, text="Analyze", style="Go.TButton",
                             command=self.analyze)
        self.go.grid(row=0, column=1, padx=(10, 0), sticky="ns")

        # -- corpus picker and examples ----------------------------------
        tools = ttk.Frame(box)
        tools.grid(row=2, column=0, sticky="ew")

        ttk.Label(tools, text="Corpus", style="Sub.TLabel").pack(
            side="left", padx=(0, 6))
        self.corpus_pick = ttk.Combobox(tools, state="readonly", width=44,
                                        font=("Segoe UI", 9))
        self.corpus_pick["values"] = [
            f"{s.sid}   {s.text}" for s in corpus.CORPUS]
        self.corpus_pick.pack(side="left", padx=(0, 16))
        self.corpus_pick.bind("<<ComboboxSelected>>", self._pick_corpus)

        tk.Frame(tools, background=RULE, width=1, height=22).pack(
            side="left", padx=(0, 16), pady=2)

        ttk.Label(tools, text="Try", style="Sub.TLabel").pack(
            side="left", padx=(0, 6))
        for ex in EXAMPLES:
            ttk.Button(tools, text=ex.label,
                       command=lambda t=ex.text: self._load(t)).pack(
                side="left", padx=3)

        # -- verdict banner ----------------------------------------------
        # An accent stripe down the left edge carries the verdict colour, so
        # the state is readable at a glance without relying on the fill
        # alone -- which matters for anyone with impaired colour vision.
        self._banner_wrap = tk.Frame(box, background=IDLE_EDGE)
        self._banner_wrap.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self._banner_wrap.columnconfigure(0, weight=1)

        # The wrapper *is* the stripe: insetting the label by 4px on the
        # left leaves exactly that much of the coloured frame showing.
        self.banner = tk.Label(self._banner_wrap, text="Ready.", anchor="w",
                               font=("Segoe UI Semibold", 12),
                               background=IDLE_BG, foreground=SLATE,
                               padx=14, pady=11)
        self.banner.grid(row=0, column=0, sticky="ew", padx=(4, 0))

        self.reason = tk.Label(box, text="", anchor="w", justify="left",
                               font=("Segoe UI", 9), wraplength=980,
                               background=PARCHMENT, foreground=CLAY)
        self.reason.grid(row=4, column=0, sticky="ew", pady=(6, 0))

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self, padding=(18, 6, 18, 0))
        self.tabs.grid(row=3, column=0, sticky="nsew")

        self.tokens = self._make_table(
            "Tokens",
            ("#", "Lexeme", "Token", "Language", "Slang", "Rule", "Gloss"),
            (40, 150, 84, 124, 56, 90, 320),
        )
        self.tree_view = self._make_text("Parse tree")
        self.trace = self._make_table(
            "Parse trace",
            ("Step", "Stack", "Remaining input", "Action"),
            (52, 310, 270, 310),
        )
        self.deriv_view = self._make_text("Derivation")
        self.sets = self._make_table(
            "FIRST / FOLLOW",
            ("Nonterminal", "FIRST", "FOLLOW"),
            (140, 340, 410),
        )
        self.corpus_table = self._make_table(
            "Corpus",
            ("ID", "Verdict", "Topic", "Transcription", "Reason"),
            (56, 136, 126, 340, 310),
        )
        self.stats_view = self._make_text("Statistics")

    def _card(self, title: str) -> tk.Frame:
        """A hairline-bordered white panel, registered as a notebook tab."""
        holder = tk.Frame(self.tabs, background=RULE, padx=1, pady=1)
        inner = tk.Frame(holder, background=CARD)
        inner.pack(fill="both", expand=True)
        inner.rowconfigure(0, weight=1)
        inner.columnconfigure(0, weight=1)
        self.tabs.add(holder, text=title)
        return inner

    def _make_table(self, title: str, columns: tuple[str, ...],
                    widths: tuple[int, ...]) -> ttk.Treeview:
        inner = self._card(title)

        tree = ttk.Treeview(inner, columns=columns, show="headings",
                            selectmode="browse")
        for col, width in zip(columns, widths):
            tree.heading(col, text=col)
            tree.column(col, width=width, anchor="w",
                        stretch=(col in ("Gloss", "Action", "FOLLOW",
                                         "Transcription", "Reason")))
        tree.grid(row=0, column=0, sticky="nsew")

        bar = ttk.Scrollbar(inner, orient="vertical", command=tree.yview)
        bar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=bar.set)

        tree.tag_configure("odd", background=ZEBRA)
        tree.tag_configure("even", background=CARD)
        tree.tag_configure("bad", background=REJECT_BG, foreground=CLAY)
        tree.tag_configure("good", background=ACCEPT_BG, foreground=MOSS)
        return tree

    def _make_text(self, title: str) -> tk.Text:
        inner = self._card(title)

        text = tk.Text(inner, font=self._mono, wrap="none", relief="flat",
                       background=CARD, foreground=INK, padx=14, pady=12,
                       insertbackground=CLAY, selectbackground=HOVER,
                       selectforeground=INK, state="disabled",
                       borderwidth=0, highlightthickness=0)
        text.grid(row=0, column=0, sticky="nsew")

        vbar = ttk.Scrollbar(inner, orient="vertical", command=text.yview)
        vbar.grid(row=0, column=1, sticky="ns")
        hbar = ttk.Scrollbar(inner, orient="horizontal", command=text.xview)
        hbar.grid(row=1, column=0, sticky="ew")
        text.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        text.tag_configure("leaf", foreground=MOSS)
        text.tag_configure("eps", foreground=CLAY)
        text.tag_configure("head", foreground=INK, font=("Segoe UI", 10, "bold"))
        return text

    def _build_statusbar(self) -> None:
        tk.Frame(self, background=RULE, height=1).grid(
            row=4, column=0, sticky="ew", pady=(10, 0))

        bar = ttk.Frame(self, padding=(18, 8, 18, 10))
        bar.grid(row=5, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)

        # A small dot that goes from clay (busy) to moss (ready), which
        # reads faster than the wording beside it.
        self._lamp = tk.Canvas(bar, width=10, height=10, highlightthickness=0,
                               background=PARCHMENT)
        self._lamp_dot = self._lamp.create_oval(1, 1, 9, 9, fill=CLAY,
                                                outline="")
        self._lamp.grid(row=0, column=0, padx=(0, 8))

        self.status = ttk.Label(bar, text="Building the LL(1) table\u2026",
                                style="Sub.TLabel")
        self.status.grid(row=0, column=1, sticky="w")

        ttk.Button(bar, text="Save LaTeX report\u2026",
                   command=self.save_report).grid(row=0, column=2)

    # -- lifecycle -------------------------------------------------------

    def _warm_up(self) -> None:
        """Build the grammar off the UI thread."""
        try:
            grammar = prepare()
            self._ready.put(("ok", grammar))
        except Exception as exc:  # pragma: no cover - defensive
            self._ready.put(("error", exc))

    def _poll_ready(self) -> None:
        try:
            kind, payload = self._ready.get_nowait()
        except queue.Empty:
            self.after(50, self._poll_ready)
            return

        if kind == "error":  # pragma: no cover - defensive
            messagebox.showerror("Startup failed", str(payload))
            self.status.configure(text="Startup failed.")
            return

        self._grammar = payload
        self._analyzer = Analyzer(payload)
        self._fill_sets()
        self._fill_corpus()
        self._fill_stats()

        conflicts = len(payload.table.conflicts)
        self._lamp.itemconfigure(self._lamp_dot, fill=MOSS)
        self.status.configure(
            text=f"Ready   \u00b7   {len(payload.table.grammar.rules)} nonterminals"
                 f"   \u00b7   {len(payload.table.table)} table entries"
                 f"   \u00b7   {conflicts} documented conflict"
                 f"{'' if conflicts == 1 else 's'}"
        )
        self.analyze()

    # -- actions ---------------------------------------------------------

    def _load(self, text: str) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self.analyze()

    def _pick_corpus(self, _event: object) -> None:
        index = self.corpus_pick.current()
        if index >= 0:
            self._load(corpus.CORPUS[index].text)

    def analyze(self) -> None:
        """Run the pipeline on whatever is in the entry box."""
        if self._analyzer is None:
            return
        text = self.entry.get().strip()
        if not text:
            self._set_banner("Type a statement to analyze.", None)
            return

        result = self._analyzer.analyze_text(text, trace=True)
        self._result = result

        self._set_banner(result.verdict, result.accepted)
        self.reason.configure(text=result.reason)
        self._fill_tokens(result)
        self._fill_tree(result)
        self._fill_trace(result)
        self._fill_derivation(result)

    def _set_banner(self, text: str, accepted: bool | None) -> None:
        """Recolour the verdict banner and its accent stripe together."""
        if accepted is None:
            fill, edge, ink, mark = IDLE_BG, IDLE_EDGE, SLATE, ""
        elif accepted:
            fill, edge, ink, mark = ACCEPT_BG, ACCEPT_EDGE, MOSS, "\u2713   "
        else:
            fill, edge, ink, mark = REJECT_BG, REJECT_EDGE, CLAY, "\u2717   "
        self.banner.configure(text=mark + text, background=fill,
                              foreground=ink)
        self._banner_wrap.configure(background=edge)

    def save_report(self) -> None:
        """Write the LaTeX report through the same generator the CLI uses."""
        path = filedialog.asksaveasfilename(
            title="Save the LaTeX report",
            defaultextension=".tex",
            initialfile="report.tex",
            filetypes=[("LaTeX source", "*.tex"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            from .report import write_report

            write_report(path)
        except Exception as exc:  # pragma: no cover - defensive
            messagebox.showerror("Could not write the report", str(exc))
            return
        messagebox.showinfo(
            "Report written",
            f"LaTeX source written to:\n{path}\n\n"
            "Compile it with pdflatex, run twice so the contents page "
            "resolves.",
        )

    # -- population ------------------------------------------------------

    @staticmethod
    def _repopulate(tree: ttk.Treeview) -> None:
        tree.delete(*tree.get_children())

    def _fill_tokens(self, result: StatementResult) -> None:
        self._repopulate(self.tokens)
        for i, token in enumerate(result.lex.tokens, 1):
            unknown = str(token.type) == "UNKNOWN"
            self.tokens.insert(
                "", "end",
                values=(
                    i,
                    token.lexeme,
                    str(token.type),
                    "/".join(str(l) for l in token.languages),
                    "yes" if token.is_slang else "",
                    token.rule,
                    token.gloss,
                ),
                tags=("bad",) if unknown else
                     ("odd",) if i % 2 else ("even",),
            )

    def _fill_tree(self, result: StatementResult) -> None:
        if result.parse.tree is None:
            body = ("No parse tree: the statement was rejected.\n\n"
                    + (result.reason or ""))
        else:
            body = "\n".join(result.parse.tree.render())
        self._write(self.tree_view, body)

    def _fill_trace(self, result: StatementResult) -> None:
        self._repopulate(self.trace)
        for step in result.parse.trace:
            self.trace.insert(
                "", "end",
                values=(step.number, step.stack, step.remaining, step.action),
                tags=("odd",) if step.number % 2 else ("even",),
            )

    def _fill_derivation(self, result: StatementResult) -> None:
        """Replay the trace as a leftmost derivation."""
        if result.parse.tree is None:
            self._write(self.deriv_view,
                        "No derivation: the statement was rejected.")
            return

        grammar = self._grammar.after_left_factoring
        form = [grammar.start]
        lines = [grammar.start]
        for step in result.parse.trace:
            if not step.action.startswith("output "):
                continue
            head, _, body = step.action[len("output "):].partition(" -> ")
            head = head.strip()
            symbols = [s for s in body.split() if s and s != EPSILON]
            for i, sym in enumerate(form):
                if sym == head:
                    form[i:i + 1] = symbols
                    break
            lines.append(" ".join(form) if form else EPSILON)

        text = "\n=> ".join(lines)
        self._write(
            self.deriv_view,
            text + f"\n\n{len(lines) - 1} derivation steps.",
        )

    def _fill_sets(self) -> None:
        table = self._grammar.table
        self._repopulate(self.sets)
        for i, nt in enumerate(table.grammar.rules):
            self.sets.insert(
                "", "end",
                values=(
                    nt,
                    "{ " + ", ".join(sorted(table.first[nt])) + " }",
                    "{ " + ", ".join(sorted(table.follow[nt])) + " }",
                ),
                tags=("odd",) if i % 2 else ("even",),
            )

    def _fill_corpus(self) -> None:
        results = self._analyzer.analyze_all(corpus.CORPUS, trace=False)
        self._repopulate(self.corpus_table)
        for result in results:
            self.corpus_table.insert(
                "", "end",
                values=(result.sid, result.verdict, result.topic,
                        result.text, result.reason),
                tags=("good",) if result.accepted else ("bad",),
            )
        for nid, text, intent in corpus.NEGATIVE_TESTS:
            outcome = self._analyzer.analyze_text(text, sid=nid, trace=False)
            self.corpus_table.insert(
                "", "end",
                values=(nid, outcome.verdict, "negative test",
                        text, outcome.reason or intent),
                tags=("bad",) if outcome.accepted else ("good",),
            )

    def _fill_stats(self) -> None:
        results = self._analyzer.analyze_all(corpus.CORPUS, trace=False)
        report = frequency_report(results)

        lines = [
            "CORPUS",
            f"  statements            {len(corpus.CORPUS)}",
            f"  accepted              {report.accepted}",
            f"  rejected              {report.rejected}",
            f"  total tokens          {report.total_tokens}",
            f"  distinct lexemes      {report.distinct_lexemes}",
            f"  type/token ratio      {report.type_token_ratio:.2f}",
            "",
            "TOKEN TYPES",
        ]
        for ttype, n in report.type_counts.most_common():
            share = 100 * n / report.total_tokens
            lines.append(f"  {str(ttype):<10} {n:>4}   {share:5.1f}%")

        lines += ["", "SOURCE LANGUAGES"]
        total_lang = sum(report.language_counts.values())
        for lang, n in report.language_counts.most_common():
            share = 100 * n / total_lang
            lines.append(f"  {str(lang):<14} {n:>4}   {share:5.1f}%")

        lines += ["", "GRAMMAR"]
        table = self._grammar.table
        lines.append(f"  nonterminals          {len(table.grammar.rules)}")
        lines.append(f"  terminals             {len(table.grammar.terminals)}")
        lines.append(f"  filled table cells    {len(table.table)}")
        lines.append(f"  conflicts             {len(table.conflicts)}")
        for conflict in table.conflicts:
            lines.append(f"    - {conflict}")

        self._write(self.stats_view, "\n".join(lines))

    def _write(self, widget: tk.Text, body: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", body)
        self._highlight(widget)
        widget.configure(state="disabled")

    @staticmethod
    def _highlight(widget: tk.Text) -> None:
        """Tint quoted lexemes green and epsilon clay."""
        for pattern, tag in (('"', "leaf"), (EPSILON, "eps")):
            start = "1.0"
            while True:
                if pattern == '"':
                    begin = widget.search('"', start, "end")
                    if not begin:
                        break
                    end = widget.search('"', f"{begin}+1c", "end")
                    if not end:
                        break
                    widget.tag_add(tag, begin, f"{end}+1c")
                    start = f"{end}+1c"
                else:
                    begin = widget.search(pattern, start, "end")
                    if not begin:
                        break
                    widget.tag_add(tag, begin, f"{begin}+{len(pattern)}c")
                    start = f"{begin}+{len(pattern)}c"


def main() -> int:
    """Open the window. Returns a process exit status."""
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.25)
    except tk.TclError:  # pragma: no cover - platform dependent
        pass
    root.configure(background=PARCHMENT)
    AnalyzerApp(root)
    root.mainloop()
    return 0
