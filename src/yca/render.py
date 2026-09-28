"""Small helpers for rendering plain-text tables and headings."""

from __future__ import annotations

from collections.abc import Iterable


def table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    """Render an ASCII table sized to its content."""
    headers = [str(h) for h in headers]
    body = [[("" if c is None else str(c)) for c in row] for row in rows]
    if not body:
        body = [["-"] * len(headers)]

    widths = [len(h) for h in headers]
    for row in body:
        for i, cell in enumerate(row[: len(widths)]):
            widths[i] = max(widths[i], len(cell))

    def line(char: str = "-") -> str:
        return "+" + "+".join(char * (w + 2) for w in widths) + "+"

    def render(cells: list[str]) -> str:
        padded = [
            cells[i].ljust(widths[i]) if i < len(cells) else " " * widths[i]
            for i in range(len(widths))
        ]
        return "| " + " | ".join(padded) + " |"

    out = [line("="), render(headers), line("=")]
    out += [render(row) for row in body]
    out.append(line("="))
    return "\n".join(out)


def heading(text: str, level: int = 1) -> str:
    """Return an underlined heading."""
    char = {1: "=", 2: "-", 3: "."}.get(level, ".")
    return f"\n{text}\n{char * len(text)}"


def bullet(items: Iterable[str], marker: str = "  - ") -> str:
    return "\n".join(f"{marker}{item}" for item in items)


def wrap(text: str, width: int = 78, indent: str = "") -> str:
    """Wrap *text* to *width*, preserving explicit blank lines."""
    import textwrap

    blocks = text.split("\n\n")
    out = []
    for block in blocks:
        out.append(
            textwrap.fill(
                " ".join(block.split()),
                width=width,
                initial_indent=indent,
                subsequent_indent=indent,
            )
        )
    return "\n\n".join(out)
