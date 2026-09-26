---
name: compliance-report
description: Write the final compliance report deliverable - structure, section order, confidence labels, tone, evidence tables and the formatting rules that survive PDF export. Use whenever the user asks for a report, write-up, assessment, findings document, memo or any deliverable to hand over - and before converting one to PDF.
---

# Compliance report

How the final document is put together: what goes in it, in what order, in what
voice, and what a reader must be able to check. This skill ends at the file
path of the finished Markdown.

Converting that Markdown to a PDF is a separate job: the **markdown-pdf** skill
owns it. Do not build a PDF from here, and do not describe a report's findings
from there.

## Before writing a word

Fix these four, because they change the whole document:

1. **Subject and identifier** - the exact legal name, registration number,
   jurisdiction. Check the spelling against the source, not from memory.
2. **Question** - what the user actually asked: ownership, sanctions, adverse
   media, licence status. One question per report.
3. **Date and cutoff** - the date of the search, stated in the document.
4. **Scope** - countries, time range and entity types checked, and what was
   deliberately left out.

If the subject is ambiguous, ask the user now. Do not guess a company.

## Confidence labels

Every factual statement carries one. Use these four words, never your own:

| Label | Means |
| --- | --- |
| **verified** | You read it in a primary or authoritative source, and you name that source |
| **reported but unconfirmed** | Stated by a secondary source, or by a primary source you could not open in full |
| **inference** | Your reasoning from verified facts, labelled as reasoning |
| **unknown** | Not established; say what stopped you |

A registry result you did not open is not *verified*. A search that returned
nothing is not evidence of absence - it is an *unknown*.

## Structure

Use these sections unless the user asked for something else. Drop a section
only when it is genuinely empty, and say so in one line rather than deleting it.

```markdown
# <Subject>: <type of check>

## Executive summary
Three to six sentences. Findings first, each with its confidence label. No
setup, no methodology, no recommendations unless asked for.

## Scope and method
What was checked, which sources and tools, the date of the search, what was
excluded and why.

## Findings
### Verified facts
### Reported but unconfirmed
### Inferences

## Unknowns and failed checks
What could not be established, and the reason: paywall, captcha, registry
offline, scan without a text layer, blocked request.

## Sources
Numbered, most authoritative first.
```

The reader should get the answer from the executive summary alone. Findings hold
the detail; the summary never introduces a fact that appears nowhere else.

## Evidence

One finding is one block. Keep the same four fields in the same order so a
reader can scan a column:

* **Statement** - what is claimed, in plain words.
* **Source** - document or page title, publisher, URL.
* **Date** - published, and the date you accessed it.
* **Confidence** - one of the four labels above.

Tables are for comparison, not for prose:

| Subject | Ownership | Source | Published | Accessed | Confidence |
| --- | --- | --- | --- | --- | --- |
| ACME LTD | Nominee A 100% | CY registry entry | 2026-04-02 | 2026-05-01 | verified |

Keep columns to about six or seven, use short cell values, and escape a literal
pipe as `\|`. Put anything longer than one sentence underneath the table, with
the entity it belongs to named in the text.

## Voice

* Third person, present tense, no first-person narration of the process.
* No hedging stacks: write *not registered as a shareholder* rather than *does
  not appear to have been registered as a shareholder at this point in time*.
* Quote exactly when wording matters, and say it is a quotation.
* Never round, merge or infer a figure. Never present a failed check as a
  negative finding.
* Do not write legal conclusions. State what a register says and what it means
  for the question asked, and recommend asking counsel when the answer has legal
  consequences.

## Formatting that survives PDF export

* One `# ` title on the **first line** - the exporter moves it to the title
  page, and a title further down prints in the wrong place.
* `## ` for sections, `### ` for subsections, never deeper than that.
* Blank line before and after every table, list, blockquote and heading.
* `<div class="new-page"></div>` when a section must not share a page, for
  example the appendix after the findings.
* Images referenced relatively (`![](images/map.png)`) and stored under
  `workspace/`. Give every image a one-line caption and say where it came from.
* Long documents get a table of contents; the exporter adds it at build time
  with `--toc`, not in the Markdown.

## Before you hand it over

1. Every fact has a source, a date and a label.
2. Every unknown names its reason.
3. The executive summary matches the findings - no claim that is not in the body.
4. No placeholder text, no `TODO`, no invented identifier left behind.
5. File name: `workspace/reports/<subject>-<YYYY-MM-DD>.md`, lower case, no
   spaces. Keep the Markdown; it is the version the user revises.

Then follow the commit reminder in the workspace `AGENTS.md`: tell the user which
files changed and to open GitHub Desktop, Commit, then Push. You have no Git
access yourself.

## Produce the PDF

When the user wants a file to open, switch to the **markdown-pdf** skill. The
one command it documents:

```bash
bash /workspace/.agents/skills/markdown-pdf/scripts/build-pdf.sh \
     workspace/reports/acme-ltd-2026-05-01.md --toc --date 2026-05-01
```

That skill also covers verifying the result, the fonts, and reading a supplied
PDF back into Markdown. Do not add PDF options here; if a conversion option is
missing, say what is missing and ask for it to be added to the skill.
