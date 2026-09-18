# OSINT AI project instructions

This project helps compliance officers research organizations and individuals
using publicly accessible sources. Separate supported facts, inferences, and
unknowns. Cite original sources and never invent verification results.

## Where to write skills — mandatory

The working project is `/workspace`, backed by the user's Windows checkout.
Create every user-authored skill at:

```text
/workspace/agents/<skill-name>/SKILL.md
```

Put helper scripts, references, and assets beneath the same skill directory.
Use YAML frontmatter with `name` and `description`. Pi explicitly discovers
`./agents`; run `/reload` after creating or changing skills.

**Never put user skills in WSL `$HOME`, `~/.pi/agent/skills`, `~/.agents`,
`.agents/skills`, or `.pi/skills`.** The user must be able to inspect every skill
in Windows File Explorer and Notepad, then commit it using a Windows Git GUI.
Do not copy or synchronize generated skills into a second checkout.

## Editable files and tools

- You may edit this `AGENTS.md`, `pixi.toml`, `pixi.lock`, and project content.
- Add Python tools with `pixi add <conda-package>` or
  `pixi add --pypi <package>`. Use `pixi run python ...` for the default tools
  environment. Do not use sudo or install into system Python.
- `.pixi` is writable Linux storage mounted inside the Windows checkout.
  Do not move it, replace it with a symlink, or enable detached environments.
- Installer scripts and bundled recipes are read-only during skill authoring.
- Git metadata is hidden. Do not commit, push, configure Git, or request GitHub
  credentials. The human reviews and publishes through a Windows Git GUI.
- Pi logins and sessions are managed separately in the application's private
  Linux state. Never write API keys, tokens, sessions, or model weights into
  the repository.
- Local inference runs outside the agent sandbox. Do not attempt to bypass the
  sandbox or launch Windows executables. Tell the user to run `start-server`
  in their OSINT AI WSL terminal when local inference is needed.

## Reviewing changes

Summarize created/changed files using Windows-friendly relative paths such as
`agents/company-check/SKILL.md`. Explain how to test the skill and what remains
unverified. The user has no programming or Git experience: use plain language.
