# OSINT AI

The functional project is `/workspace`. User-authored skills MUST live in
`/workspace/.agents/skills/<skill-name>/SKILL.md`, with supporting files beneath
that skill directory. Never create user skills under `$HOME`, `~/.pi`,
`~/.pi/agent/skills`, `~/.agents`, or `.pi/skills`: they would sit outside the
user's checkout, unreviewed and uncommittable.

Read `/workspace/AGENTS.md` for the working rules, including running
`git status` yourself in the checkout you work in to remind the user to commit
and push with their own Git app (GitHub Desktop on Windows). Never commit, push,
switch branches or
discard work yourself; the user reviews every change. The program itself is a
different checkout, mounted read-only at `/opt/osint-ai/project`; you cannot
change it from here.
