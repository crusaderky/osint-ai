#!/usr/bin/env python3
"""Inspect and convert spreadsheets without leaving the OSINT workspace.

Supports legacy Excel (.xls), Excel 2007+ (.xlsx/.xlsm), Excel binary (.xlsb)
and delimited text files. Values are read as text and objects so that
identifiers, IBANs, amounts and dates are reported exactly as stored.

Examples:
    sheet.py info accounts.xls
    sheet.py head accounts.xls --sheet Ledger --rows 20
    sheet.py to-md accounts.xls --sheet Ledger --out ledger.md
    sheet.py to-csv accounts.xls --all --outdir extracted
    sheet.py find accounts.xls "ACME LTD"
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

# Fallback order per extension; a file can be mislabelled by an exporter.
ENGINES = {
    ".xls": ["xlrd", "openpyxl", "pyxlsb"],
    ".xlsx": ["openpyxl", "xlrd", "pyxlsb"],
    ".xlsm": ["openpyxl", "pyxlsb"],
    ".xlsb": ["pyxlsb", "openpyxl"],
}
DELIMITED = {".csv", ".tsv", ".txt"}
MAX_SCAN_ROWS = 2000


def fail(message: str) -> None:
    raise SystemExit(f"sheet.py: {message}")


def read_sheet(path: Path, sheet, *, header, dtype=object):
    """Read one sheet, trying every plausible engine for the file's content."""
    if path.suffix.lower() in DELIMITED:
        options = {"sep": None, "engine": "python"} if path.suffix.lower() != ".tsv" else {"sep": "\t"}
        return pd.read_csv(path, header=header, dtype=dtype, encoding="utf-8-sig",
                           keep_default_na=False, na_values=[""], **options)
    engines = ENGINES.get(path.suffix.lower(), ["openpyxl"])
    errors = []
    for engine in engines:
        try:
            return pd.read_excel(path, sheet_name=sheet, engine=engine, header=header,
                                 dtype=dtype, keep_default_na=False, na_values=[""])
        except NotImplementedError as error:
            errors.append(f"{engine}: {error}")
        except Exception as error:  # wrong engine, broken workbook, wrong sheet name
            errors.append(f"{engine}: {type(error).__name__}: {error}")
    fail(f"cannot read {path.name} with {'/'.join(engines)}\n  " + "\n  ".join(errors))


def sheet_names(path: Path):
    if path.suffix.lower() in DELIMITED:
        return [path.name]
    for engine in ENGINES.get(path.suffix.lower(), ["openpyxl"]):
        try:
            with pd.ExcelFile(path, engine=engine) as workbook:
                return list(workbook.sheet_names)
        except Exception:
            continue
    fail(f"cannot list sheets in {path.name}; is it a spreadsheet?")


def looks_wrong(path: Path) -> str | None:
    """Warn when the extension disagrees with the file's magic bytes."""
    head = path.read_bytes()[:8]
    if head.startswith(b"PK\x03\x04") and path.suffix.lower() == ".xls":
        return "content is a zip (Excel 2007+ .xlsx) although the name ends in .xls"
    if head.startswith(b"\xd0\xcf\x11\xe0") and path.suffix.lower() in {".xlsx", ".xlsb"}:
        return "content is a legacy OLE workbook (.xls) although the name says otherwise"
    if head.startswith(b"%PDF"):
        return "content is a PDF, not a spreadsheet"
    if head[:5].lower() in (b"<html", b"<!doc"):
        return "content is HTML that only looks like a spreadsheet"
    return None


def cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return ""
    text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def markdown_table(frame: pd.DataFrame, limit: int | None = None) -> str:
    frame = frame if limit is None else frame.head(limit)
    columns = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(cell(name) for name in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(cell(value) for value in row) + " |")
    if limit is not None and len(frame) > limit:
        lines.append(f"\n_{len(frame)} rows in total; first {limit} shown._")
    return "\n".join(lines)


def resolve_sheet(names, requested: str | None):
    if requested is None:
        return 0
    for index, name in enumerate(names):
        if str(name) == str(requested) or str(index) == str(requested):
            return index
    fail(f"no sheet {requested!r}; available sheets: {', '.join(str(n) for n in names)}")


def command_info(path: Path, _args) -> None:
    warning = looks_wrong(path)
    print(f"file: {path}")
    if warning:
        print(f"warning: {warning}")
    for name in sheet_names(path):
        frame = read_sheet(path, resolve_sheet(sheet_names(path), str(name)), header=0)
        print(f"\nsheet: {name}  rows: {len(frame)}  columns: {len(frame.columns)}")
        for column in frame.columns:
            values = frame[column].dropna()
            example = "" if values.empty else f" e.g. {str(values.iloc[0])[:40]!r}"
            print(f"  - {column}{example}")


def command_head(path: Path, args) -> None:
    names = sheet_names(path)
    frame = read_sheet(path, resolve_sheet(names, args.sheet), header=args.header)
    print(markdown_table(frame, args.rows))


def command_to_markdown(path: Path, args) -> None:
    names = sheet_names(path)
    sheet = resolve_sheet(names, args.sheet)
    frame = read_sheet(path, sheet, header=args.header)
    title = str(names[sheet])
    text = f"# {title}\n\n" + markdown_table(frame, args.rows) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(args.out)
    else:
        sys.stdout.write(text)


def command_to_csv(path: Path, args) -> None:
    names = sheet_names(path)
    if not args.all and args.out:
        frame = read_sheet(path, resolve_sheet(names, args.sheet), header=args.header)
        frame.to_csv(args.out, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
        print(args.out)
        return
    if not args.outdir:
        fail("--all needs --outdir")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for name in names:
        safe = "".join(character if character.isalnum() or character in "-_." else "_"
                       for character in str(name)).strip("_") or "sheet"
        frame = read_sheet(path, resolve_sheet(names, str(name)), header=args.header)
        target = outdir / f"{path.stem}-{safe}.csv"
        frame.to_csv(target, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
        print(target)


def command_find(path: Path, args) -> None:
    needle = args.needle.lower()
    matches = 0
    for name in sheet_names(path):
        frame = read_sheet(path, resolve_sheet(sheet_names(path), str(name)), header=None,
                           dtype=str)
        if len(frame) > MAX_SCAN_ROWS:
            print(f"note: sheet {name} has {len(frame)} rows; only the first "
                  f"{MAX_SCAN_ROWS} were searched")
            frame = frame.head(MAX_SCAN_ROWS)
        for row_index, row in frame.iterrows():
            for column_index, value in enumerate(row):
                if isinstance(value, str) and needle in value.lower():
                    column = ""
                    index = column_index
                    while index >= 0:
                        column = chr(ord("A") + index % 26) + column
                        index = index // 26 - 1
                    print(f"{name}!{column}{row_index + 1}: {value.strip()[:200]}")
                    matches += 1
                    if matches >= args.limit:
                        print(f"(stopped after {args.limit} matches)")
                        return
    if not matches:
        print(f"no match for {args.needle!r}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["info", "head", "to-md", "to-csv", "find"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--sheet", help="Sheet name or number (default: first sheet).")
    parser.add_argument("--header", default="0",
                        help="Row number holding column names, or 'none' when there is none.")
    parser.add_argument("--rows", type=int, help="Maximum rows to print or export.")
    parser.add_argument("--out", help="Output file (Markdown or one CSV).")
    parser.add_argument("--outdir", help="Output folder for --all.")
    parser.add_argument("--all", action="store_true", help="Every sheet as a separate CSV.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum matches for find.")
    parser.add_argument("needle", nargs="?", default="", help="Text to search for in find.")
    args = parser.parse_args(argv)
    args.header = None if str(args.header).lower() in {"none", "-1"} else int(args.header)
    if not args.file.is_file():
        fail(f"not a file: {args.file}")
    if args.command == "info":
        command_info(args.file, args)
    elif args.command == "head":
        command_head(args.file, args)
    elif args.command == "to-md":
        command_to_markdown(args.file, args)
    elif args.command == "to-csv":
        command_to_csv(args.file, args)
    else:
        if not args.needle:
            fail("find needs a search term")
        command_find(args.file, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
