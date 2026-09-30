# Screenshots

The brief requires "Screenshots of working analyzer" as part of the final
report. The report references the files below by name. Drop a PNG with the
matching name into this folder and recompile -- nothing else needs editing.

Any file that is missing is replaced in the PDF by a labelled placeholder
naming the file it wants, so the report always compiles and the gaps are
obvious rather than silent.

All nine are currently present, so the report embeds real captures and no
placeholder is drawn.

## The captures

The right-hand column records the file each capture was renamed from, so a
figure that turns out to be mislabelled can be traced back and swapped
without re-taking anything.

| File | What it shows | Renamed from |
|---|---|---|
| `app-overview.png` | The whole window just after analysing a corpus statement, with the verdict visible and the tab bar showing the seven panels. | `1st screenshot.png` |
| `tokens-panel.png` | The **Tokens** tab for an analysed statement. | `2nd screenshot.png` |
| `tree-panel.png` | The **Parse tree** tab. | `3rd screenshot.png` |
| `conflict-panel.png` | The documented conflict, on the Statistics tab. | `5th screenshot.png` |
| `derivation-panel.png` | The **Derivation** tab. | `6th screenshot.png` |
| `sets-panel.png` | The **FIRST / FOLLOW** tab. | `7th screenshot.png` |
| `trace-accepted.png` | The **Parse trace** tab for an accepted statement. | `8th screenshot.png` |
| `trace-rejected.png` | The **Parse trace** tab for a rejected one, with the reason visible. | `9th screenshot.png` |
| `web-deployed.png` | The browser at the public URL, with the padlock and address bar visible. | `web_deployed image.png` |

The two pairings matter for layout: `tree-panel` sits beside
`derivation-panel`, and `trace-accepted` beside `trace-rejected`. Each pair
is printed at the same width, so captures of similar proportions sit best
together.

## Retaking one

Start the web front end:

    set PYTHONPATH=src
    python -m yca web

Then analyse a statement, for example
`Chef, drop me for Carrefour Obili.`, and capture each tab.

On Windows, `Win+Shift+S` captures a region and `Alt+PrtScn` captures the
active window only, which is usually the cleaner choice.

## Keep them legible

The report prints a single capture at roughly 62% of the text width, and a
pair of captures at 45% each. A 1200--1600 px wide capture is ample; much
wider mostly inflates the PDF.

Crop away the desktop background and anything personal --- other tabs,
bookmarks, file paths containing your name. Prefer a maximised window on a
plain background.
