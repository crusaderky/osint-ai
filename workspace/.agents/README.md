# Your skills

Ask the chatbot to create skills here. Each skill gets its own folder:

```text
workspace/
  AGENTS.md                 rules the chatbot always follows
  .agents/
    skills/
      compliance-report/   how the final report is put together
      markdown-pdf/         PDF <-> Markdown conversion kit
      spreadsheet-reader/
      your-new-skill/
        SKILL.md
        scripts/
        references/
```

Open this folder with the **OSINT AI Files** desktop icon, then
`workspace` \ `.agents` \ `skills`. (Turn on "show hidden files" in File Explorer
if `.agents` is invisible: View tab → tick "Hidden items".)

* Review any `SKILL.md` with Notepad.
* After editing or adding a skill, type `/reload` in the chatbot.
* A skill is an instruction the chatbot trusts, so read what it wrote before you
  rely on it.
* Finished work stays useful: open your Windows Git app (GitHub Desktop),
  **Commit** the changes, then **Push** so your team and your other PCs get them.

The three skills that come with the project:

| Skill | What it does |
| --- | --- |
| `spreadsheet-reader` | Reads `.xls`, `.xlsx`, `.xlsb` and CSV files |
| `compliance-report` | Structures the report you hand over: sections, confidence labels, sources |
| `markdown-pdf` | Turns a Markdown file into a PDF, and a PDF back into Markdown |
