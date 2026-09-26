# Runtime workspace

This folder is what the agent has access to at runtime (in addition to the internet)/

- `AGENTS.md`: this teaches the agent its overall behaviour. It is visible to it at all
  times. This files is for the agent to read; not for humans.
- `.agents/skills/*/SKILL.md`: each of these files is a script that teaches a specific
  action to the agent. The agent only reads it when it needs to.
- Any files that you want your agent to see (copy-pasted from elsewhere on your disk)
- Any files that your agent creates

## What you can ask the agent

### Run research on organizations and individuals

- _"Find out everything about Nigel Farage and generate a PDF report."_
- _"Take a look at @suspicious_claim.pdf that some guy just emailed me and
  prove or disprove their claims."_

### Add/update skills

- _"Open website dirtysecrets.com and search for Nigel Farage on its search bar. In the
  returned HTML page, the important bits are X and Y. Disregard the rest. Note down how
  to correctly query this source in a new skill, which you must call
  'source-dirtysecrets'"_.
- _"While analysing the data from dirtysecrets.com, you returned data from 2013, which
  is outdated. On this website specifically, you must always ignore data earlier than
  2024. Update the relevant skill to avoid the same mistake in the future."_
- _"Do not, EVER, say the word 'load-bearing' again. Note it down in @AGENTS.md."_

You shouldn't typically need to write these files by hand. Asking the agent to modify
them itself is easier.
