#!/usr/bin/env bash
# Convert a Markdown file to a PDF with pandoc + WeasyPrint, then verify it.
#
#   build-pdf.sh report.md
#   build-pdf.sh report.md -o out/report.pdf -t "Shell company check" --toc
#
# The first line of the Markdown is expected to be the "# " title. It is moved
# to a title page, so the title is printed once and lands in the PDF metadata;
# the source file is never modified. The rest of the document follows the
# table of contents.
#
# Programs: coreutils, grep, sed, awk, mktemp, pandoc, weasyprint, pdfinfo.
# All of them are on the project environment PATH; nothing is installed here.
set -euo pipefail

usage() {
    echo "Usage: build-pdf.sh INPUT.md [-o OUTPUT.pdf] [-t TITLE] [--toc]" \
         "[--css FILE] [--template FILE] [--date YYYY-MM-DD]" >&2
    exit 2
}

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
assets="$here/../assets"
[[ $# -ge 1 ]] || usage
input=$1
[[ $input != -. ]] || usage
shift
output=""
title=""
date_arg=""
toc=()
css="$assets/report.css"
template="$assets/template.html"
while [[ $# -gt 0 ]]; do
    case $1 in
        -o) output=${2:?missing value for -o}; shift 2 ;;
        -t) title=${2:?missing value for -t}; shift 2 ;;
        --toc) toc=(--toc); shift ;;
        --css) css=${2:?missing value for --css}; shift 2 ;;
        --template) template=${2:?missing value for --template}; shift 2 ;;
        --date) date_arg=${2:?missing value for --date}; shift 2 ;;
        *) usage ;;
    esac
done
[[ -f $input ]] || { echo "No such Markdown file: $input" >&2; exit 1; }
[[ -f $css ]] || { echo "No such stylesheet: $css" >&2; exit 1; }
[[ -f $template ]] || { echo "No such template: $template" >&2; exit 1; }
for tool in pandoc weasyprint pdfinfo; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "Missing program: $tool (ask the developer to add it to pixi.toml)" >&2
        exit 1
    }
done
output=${output:-"${input%.*}.pdf"}
mkdir -p "$(dirname "$output")"
date_arg=${date_arg:-$(date +%Y-%m-%d)}
[[ $date_arg =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || {
    echo "--date must look like 2026-05-01, got: $date_arg" >&2
    exit 2
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Split the title off the body. A title that pandoc would read as markup
# (emphasis, code, a link) is a warning, not a failure: -t overrides it.
body="$input"
doc_title=""
first=""
IFS= read -r first < "$input" || first=""
if [[ $first == "# "* ]]; then
    doc_title=$(sed -e 's/ *{[^}]*} *$//' <<<"${first#\# }")
    if grep -qE '[`*_\[]' <<<"$doc_title"; then
        echo "Note: the title contains Markdown markup and is used verbatim." >&2
        echo "Pass -t \"...\" to set a plain-text title instead." >&2
    fi
    tail -n +2 -- "$input" > "$work/body.md"
    body="$work/body.md"
else
    echo "Note: no \"# \" title on the first line; using the -t value or file name." >&2
fi
doc_title=${title:-${doc_title:-${input%.*}}}
doc_title=$(sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' <<<"$doc_title")

# Title page. The HTML is escaped here, so the title is never markup.
{
    printf '<h1 class="title">%s</h1>\n' \
        "$(sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$doc_title")"
    printf '<p class="reportdate">%s</p>\n' "$date_arg"
} > "$work/before.html"
# Metadata in a file, so a comma or a colon in the title is not misread.
printf 'title: "%s"\nlang: "en"\n' "$doc_title" > "$work/meta.yaml"

log="$work/pandoc.log"
if ! pandoc "$body" \
    --output "$output" \
    --standalone \
    --template "$template" \
    --from markdown+pipe_tables+task_lists+footnotes+strikeout+autolink_bare_uris+raw_html \
    --pdf-engine=weasyprint \
    --css "$css" \
    --metadata-file "$work/meta.yaml" \
    --include-before-body "$work/before.html" \
    ${toc[@]+"${toc[@]}"} > "$log" 2>&1; then
    cat "$log" >&2
    echo "Conversion failed; no PDF was written to $output" >&2
    exit 1
fi
if grep -q "notdef glyph" "$log"; then
    grep "notdef glyph" "$log" | head -5
    echo "WARNING: some characters have no glyph in the installed fonts and show as boxes." >&2
    echo "Fix: ask the developer to add a font package to pixi.toml, for example" >&2
    echo "  pixi add font-ttf-noto-cjk" >&2
    echo "Say so in the document until that is done. Do not claim the PDF is complete." >&2
fi

pages=$(pdfinfo "$output" | awk '/^Pages:/ { print $2 }')
if [[ ! -s $output || ${pages:-0} -lt 1 ]]; then
    echo "Conversion produced no readable PDF: $output" >&2
    exit 1
fi
echo "Wrote $output (${pages} page(s), title: $doc_title)"
echo "Check it before delivering:"
echo "  pdfinfo '$output'"
echo "  pdftotext -layout '$output' - | head -40"
