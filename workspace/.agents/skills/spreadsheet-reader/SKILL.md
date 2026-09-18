---
name: spreadsheet-reader
description: Read Excel and delimited spreadsheets (.xls, .xlsx, .xlsm, .xlsb, .csv, .tsv) - list sheets and columns, preview rows, search for a value, and convert a sheet to CSV or Markdown. Use whenever the user mentions a spreadsheet, workbook, an .xls/.xlsx file, or asks to extract or compare a table.
---

# Spreadsheet reader

Read spreadsheets with `pandas` through one helper script. It never opens a
network connection and never writes to the source file.

```text
SCRIPT=/osint-ai/workspace/.agents/skills/spreadsheet-reader/scripts/sheet.py
```

Always run the tools from `workspace/` and give files as `workspace/...` paths
so the user can open them with their own file manager.

## Commands

```bash
python3 "$SCRIPT" info accounts.xls                 # sheets, columns, one example value each
python3 "$SCRIPT" head accounts.xls --sheet Ledger --rows 20
python3 "$SCRIPT" to-md accounts.xls --sheet Ledger --out workspace/derived/ledger.md
python3 "$SCRIPT" to-csv accounts.xls --all --outdir workspace/derived
python3 "$SCRIPT" find accounts.xls "ACME LTD"       # sheet!cell plus the text
```

`--sheet` takes a name or a number. `--header N` sets which row holds the column
names; use `--header none` when there is no header row.

## Workflow for compliance work

1. Record the evidence first: `stat --printf='%n %s bytes %y\n' file.xls` and
   `sha256sum file.xls`. Quote both in the report.
2. `info` before anything else. Do not assume the first sheet or the first row
   is the real table; many exports have title rows, blank rows or notes.
3. Read identifiers (`id`, IBAN, LEI, registration number, phone) as text. The
   script keeps values as stored, so do not reformat numbers or dates by hand;
   if a value looks rounded, exponential or truncated, say so instead of
   "fixing" it.
4. Convert the sheet you actually need with `to-md` (for a report) or `to-csv`
   (for further analysis). Save derived files under `workspace/derived/`.
5. When you quote a figure, give the sheet name, the column heading and the row
   range, for example `Ledger!C2:C118`.
6. Cross-check totals: compare the stated total with the sum of the rows and
   report a mismatch as a finding.

## Limits you must state when relevant

* Formulas are **not** recalculated: pandas reads the last cached result. If the
  workbook was produced by another program, cached values may be missing.
* Pivot tables, charts, cell comments, conditional formatting and macros are not
  read. Hidden sheets are listed by `info`; mention them.
* A file can be mislabelled. The script warns when the content disagrees with
  the extension and tries the right reader; if it still fails, ask the user to
  re-export from Excel as `.xlsx` or `.csv`.
* A `.xls` that is really HTML (common with bank and registry exports) is
  reported as such; use the Markdown/PDF skill's text extraction route instead.
* Password-protected workbooks are not supported.

If the script reports an error you cannot resolve, show the exact error to the
user and state what could not be read. Never invent table contents.
