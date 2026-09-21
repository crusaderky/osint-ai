---
name: markdown-pdf
description: Convert between Markdown and PDF. Write a report as Markdown and produce a PDF with pandoc + WeasyPrint, or extract text from a supplied PDF and rebuild it as Markdown. Use whenever the user asks for a report, document or deliverable as PDF, or hands over a PDF to read, quote or convert.
---

# Markdown and PDF

Markdown is the source of truth. A PDF is generated output: never edit a PDF by
hand, edit the Markdown and rebuild.

```text
BUILD=/workspace/.agents/skills/markdown-pdf/scripts/build-pdf.sh
```

## Markdown to PDF (reports)

1. Write the report as Markdown, e.g. `workspace/reports/acme-ltd-2026-05-01.md`.
   Save it before converting, and keep it next to the PDF afterwards so the user
   can revise it.
2. Convert:

   ```bash
   bash "$BUILD" workspace/reports/acme-ltd-2026-05-01.md \
        -t "Ownership check - ACME LTD" --toc
   ```

   The script derives the title from the first `# ` heading if you leave `-t`
   out, writes `acme-ltd-2026-05-01.pdf` next to the Markdown file, and prints
   the page count. Use `-o` for another name and `--css FILE` for other styling.
3. Verify before you deliver. The script already fails if no readable PDF came
   out; still check the content yourself:

   ```bash
   pdfinfo workspace/reports/acme-ltd-2026-05-01.pdf
   pdftotext -layout workspace/reports/acme-ltd-2026-05-01.pdf - | head -60
   ```

   Say what you checked. If the page count or the text looks wrong, fix the
   Markdown and rebuild.
4. Missing characters: if the script prints `.notdef glyph rendered`, those
   characters show as empty boxes because no installed font covers them (CJK and
   some scripts need an extra font). Tell the user which script is affected, and
   state the limitation inside the report until a font is installed. Nothing is
   installed from inside the sandbox.

### Markdown rules that keep a report tidy

* One `# ` title, `## ` for sections; the built-in style adds page numbers.
* Blank line before and after every table, list and heading.
* Table cells: escape a literal pipe as `\|`; keep tables to about eight columns
  and put long prose in paragraphs instead of cells.
* Images: reference files inside `workspace/` with relative paths
  (`![](images/map.png)`); absolute Linux paths are invisible to the user.
* Start a new page with `<div class="new-page"></div>` when a section must not
  share a page.
* Footnotes (`[^1]`) and links (`<https://example.org>`) work; links break
  across lines rather than overflowing.

## PDF to Markdown (reading a supplied PDF)

```bash
pdfinfo statement.pdf                       # pages, title, producer, encryption
pdftotext -layout statement.pdf statement.txt
pdftotext -f 3 -l 4 statement.pdf -         # one page range, printed to screen
```

1. Read `pdfinfo` first. If `Pages` is more than 1 while the extracted text is
   almost empty, the PDF is a **scan without a text layer**: OCR is not
   installed, so say that the document cannot be read and ask for a searchable
   PDF or the original.
2. `-layout` preserves columns and tables; `-raw` keeps the storage order, which
   is sometimes better for two-column text. Compare both if the output is messy.
3. Text extraction loses structure. Rewrite the text into Markdown yourself:
   real headings, real tables, a `Sources` section holding the document title,
   its identifier or URL, issue date and the access date. Quote exact wording
   for anything you rely on, and keep the extracted `.txt` file next to the
   Markdown as a working file.
4. Never present extracted text as verified content: scans and generated PDFs
   contain errors, dropped characters and merged cells.

## Report skeleton

Use these sections unless the user asks for something else:

```markdown
# <Subject>: <type of check>

## Executive summary
Three to six sentences. Findings first, with the confidence label.

## Scope and method
What was checked, which sources and tools, date of the search, what was excluded.

## Findings
### Verified facts
Each item: statement, source title, URL or document reference, published date,
accessed date.

### Reported but unconfirmed
### Inferences
Reasoning from the verified facts, stated as reasoning.

## Unknowns and failed checks
What could not be established and why (paywall, captcha, no registry online,
scan without text layer, blocked request).

## Sources
Numbered list, most authoritative first.
```
