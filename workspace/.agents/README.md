# Runtime workspace

This folder is what the agent can see at runtime, apart from the internet.

- `AGENTS.md`: the agent's overall behaviour. It is in front of the agent at all
  times. This file is for the agent to read, not for humans.
- `.agents/skills/*/SKILL.md`: each one teaches a specific action. The agent only
  reads a skill when it needs it.
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

You should rarely need to write these files yourself. Asking the agent to change
them is easier, and it keeps the wording in a form the agent follows.
