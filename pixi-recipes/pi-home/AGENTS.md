# OSINT AI

The functional project is `/workspace`. User-authored skills MUST live in
`/workspace/.agents/skills/<skill-name>/SKILL.md`, with supporting files beneath
that skill directory. Never create user skills under `$HOME`, `~/.pi`,
`~/.pi/agent/skills`, `~/.agents`, or `.pi/skills`: they would sit outside the
user's checkout, unreviewed and uncommittable.

Read `/workspace/AGENTS.md` for the working rules, including the read-only
`/run/git-status` summary you use to remind the user to commit and push with
their Windows Git GUI. The program itself is a different checkout, mounted
read-only at `/opt/osint-ai/project`; you cannot change it from here.
