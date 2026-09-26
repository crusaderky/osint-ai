---
name: markdown-pdf
description: Convert between Markdown and PDF. Build a PDF from a Markdown file with pandoc + WeasyPrint, or extract the text of a supplied PDF and rebuild it as Markdown. Use whenever a file has to become a PDF or a PDF has to be read, quoted, searched or converted - not for deciding what a report should contain.
---

# Markdown and PDF

A conversion kit. It moves bytes between Markdown and PDF and nothing else:
it does not decide what a document should say. For the structure, tone and
confidence labels of a compliance deliverable, use the **compliance-report**
skill first and come back here for the conversion.

Markdown is the source of truth. A PDF is generated output: never edit a PDF by
hand, edit the Markdown and rebuild.

```text
BUILD=/workspace/.agents/skills/markdown-pdf/scripts/build-pdf.sh
```

## Markdown to PDF

1. Save the Markdown under `/workspace`, e.g.
   `workspace/reports/acme-ltd-2026-05-01.md`, and keep it next to the PDF
   afterwards so the user can revise it.
2. Convert:

   ```bash
   bash "$BUILD" workspace/reports/acme-ltd-2026-05-01.md --toc
   ```

   The first line must be the `# ` title; the script moves it to a title page,
   adds today's date, writes `acme-ltd-2026-05-01.pdf` next to the Markdown,
   and prints the page count. It never writes to the Markdown.

   | Option | Effect |
   | --- | --- |
   | `-o FILE` | Write somewhere else |
   | `-t "Title"` | Plain-text title, overrides the `# ` line |
   | `--toc` | Table of contents under the title |
   | `--date YYYY-MM-DD` | Report date instead of today |
   | `--css FILE` | Other stylesheet |
3. Verify before you deliver. The script fails if no readable PDF came out, but
   the content is still your responsibility:

   ```bash
   pdfinfo workspace/reports/acme-ltd-2026-05-01.pdf   # pages, title, page size
   pdftotext -layout workspace/reports/acme-ltd-2026-05-01.pdf - | head -60
   pdftoppm -png -r 60 -f 1 -l 1 workspace/reports/acme-ltd-2026-05-01.pdf /tmp/page
   ```

   Read the text **and** the rendered page image. Text extraction hides layout
   faults: a table that overflows, a heading orphaned at the foot of a page or a
   title printed twice are invisible to `pdftotext`. If something is wrong, fix
   the Markdown or the stylesheet and rebuild.

   Say what you checked. A green run is not evidence that the PDF reads well.
4. WeasyPrint reports `notdef glyph` for characters that no installed font
   covers, so they show as empty boxes. Name the script affected, state the
   limitation in the document, and ask the developer to add a font package to
   `pixi.toml` (for example `pixi add font-ttf-noto-cjk`). Nothing can be
   installed from inside the sandbox.

### Markdown that survives the conversion

* Blank line before and after every table, list, blockquote and heading.
* A literal pipe inside a table cell is `\|`. Keep tables to about eight
  columns; long prose belongs in a paragraph, not in a cell.
* Headings, footnotes (`[^1]`) and `<https://example.org>` links all work.
  Links wrap instead of overflowing the page.
* Raw HTML passes through. `<div class="new-page"></div>` starts a new page.
* Images are referenced relative to the Markdown file
  (`![](images/map.png)`) and must live inside `workspace/`. An absolute Linux
  path is invisible in the PDF and to the user.
* Character sets: DejaVu, Noto (including CJK) and Source Code Pro ship with
  the project environment, so Latin, Greek, Cyrillic, Hebrew, Arabic, Devanagari
  and CJK text all get glyphs. Right-to-left scripts are not laid out
  right-to-left, so Hebrew and Arabic are readable but the punctuation sits
  wrongly - say so if the user asked about one of those languages.

## PDF to Markdown

```bash
pdfinfo statement.pdf                       # pages, title, producer, encryption
pdftotext -layout statement.pdf statement.txt
pdftotext -f 3 -l 4 statement.pdf -         # one page range, printed to screen
```

1. Read `pdfinfo` first. If `Pages` is more than 1 while the extracted text is
   almost empty, the PDF is a **scan without a text layer**. OCR is not
   installed: say the document cannot be read and ask for a searchable PDF or
   the original. Never reconstruct content you could not read.
2. `-layout` preserves columns and tables; `-raw` keeps the storage order, which
   is sometimes better for two-column text. Compare both if the output is
   messy.
3. Text extraction loses structure. Rebuild the Markdown yourself: real
   headings, real tables, and a `Sources` section holding the document title,
   its identifier or URL, issue date and the access date. Quote exact wording
   for anything you rely on, and keep the extracted `.txt` next to the Markdown
   as a working file.
4. Never present extracted text as verified content. Scans and generated PDFs
   contain errors, dropped characters and merged cells. Re-read the page image
   (`pdftoppm`) whenever a number, a name or a date matters.

When the PDF becomes a deliverable in its own right, hand the Markdown to
`bash "$BUILD"` and follow the checks above.
