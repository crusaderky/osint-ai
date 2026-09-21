#!/usr/bin/env bash
# Turn a Markdown report into a PDF with pandoc + WeasyPrint, then verify it.
#
#   build-pdf.sh report.md                       -> report.pdf
#   build-pdf.sh report.md -o out/report.pdf -t "Shell company check"
#
# Requires only the project environment (pandoc, weasyprint, pdfinfo, pdftotext).
set -euo pipefail

usage() {
    echo "Usage: build-pdf.sh INPUT.md [-o OUTPUT.pdf] [-t TITLE] [--toc] [--css FILE]" >&2
    exit 2
}

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
[[ $# -ge 1 ]] || usage
input=$1
[[ $input != -. ]] || usage
shift
output=""
title=""
toc=()
css="$here/../assets/report.css"
while [[ $# -gt 0 ]]; do
    case $1 in
        -o) output=${2:?missing value for -o}; shift 2 ;;
        -t) title=${2:?missing value for -t}; shift 2 ;;
        --toc) toc=(--toc); shift ;;
        --css) css=${2:?missing value for --css}; shift 2 ;;
        *) usage ;;
    esac
done
[[ -f $input ]] || { echo "No such Markdown file: $input" >&2; exit 1; }
[[ -f $css ]] || { echo "No such stylesheet: $css" >&2; exit 1; }
output=${output:-"${input%.*}.pdf"}
mkdir -p "$(dirname "$output")"
title=${title:-$(awk '/^# / { sub(/^# /, ""); print; exit }' "$input")}
if [[ -z $title ]]; then
    title=${input%.*}
fi

log=$(mktemp)
trap 'rm -f "$log"' EXIT
if ! pandoc "$input" \
    --output "$output" \
    --standalone \
    --from markdown+pipe_tables+task_lists+footnotes \
    --pdf-engine=weasyprint \
    --css "$css" \
    --metadata "title=$title" \
    --metadata "date=$(date +%Y-%m-%d)" \
    --metadata "lang=en" \
    --metadata "encoding=utf-8" \
    ${toc[@]+"${toc[@]}"} > "$log" 2>&1; then
    cat "$log" >&2
    echo "Conversion failed; no PDF was written to $output" >&2
    exit 1
fi
if grep -q "notdef glyph" "$log"; then
    grep "notdef glyph" "$log" | head -5
    echo "WARNING: some characters have no glyph in the installed fonts and appear as boxes." >&2
    echo "Fix: install the needed font inside the OSINT AI WSL distribution, for example" >&2
    echo "  wsl.exe -d osint-ai -u root -- apt-get install -y fonts-noto-cjk" >&2
    echo "Say so in the report until that is done. Do not claim the PDF is complete." >&2
fi

pages=$(pdfinfo "$output" | awk '/^Pages:/ { print $2 }')
if [[ ! -s $output || ${pages:-0} -lt 1 ]]; then
    echo "Conversion produced no readable PDF: $output" >&2
    exit 1
fi
echo "Wrote $output (${pages} page(s), title: $title)"
echo "Check it before delivering: pdftotext -layout '$output' - | head -40"
