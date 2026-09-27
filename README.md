# OSINT AI

A private, AI-assisted filing cabinet for compliance research. You ask it about
a company or a person. It reads public sources (registries, sanctions lists,
company websites, news, filings) and writes down what it **verified**, what is
only **reported**, what it **inferred** and what it **could not check**. Every
fact carries a link and the date you looked.

Nothing is hidden from you. The instructions the assistant follows are plain
text files you can read, change and share. They are called **skills**, and
building them up is the point of the project.

---

## Contents

1. [Install once (Windows)](#install-once)
2. [Install on Linux](#install-on-linux)
3. [Start chatting](#start-chatting)
4. [Save your work with Git](#save-your-work-with-git)
5. [Talking to the assistant](#talking-to-the-assistant)
6. [AGENTS.md](#agentsmd)
7. [Skills: your repeatable checks](#skills-your-repeatable-checks)
8. [After any change: commit and push](#after-any-change-commit-and-push)
9. [Spreadsheets and PDF reports](#spreadsheets-and-pdf-reports)
10. [If something goes wrong](#if-something-goes-wrong)
11. [Uninstall everything](#uninstall-everything)

---

## Install once

This section is for Windows 11. On Linux, use
[Install on Linux](#install-on-linux) instead; everything after
[Start chatting](#start-chatting) is the same on both.

You need a Windows 11 PC (Intel or AMD), internet access and about 5 GB of free
disk space. An NVIDIA graphics card is optional; without one the assistant runs
more slowly on the processor.

1. Download and unzip the installation package.
2. Double-click **`windows\Install.cmd`** and follow the prompts. If Windows asks
   for permission to make changes, allow it.
3. If Windows asks you to restart, do it, then double-click
   **`windows\Install.cmd`** again. Setup continues where it stopped.

When it finishes you get three desktop icons:

| Icon | What it does |
| --- | --- |
| **OSINT AI Terminal** | Opens the assistant and starts it for you. This is the one you use every day. |
| **OSINT AI Terminal (basic)** | Same, in a plain Windows window. Use it if the other one ever misbehaves. |
| **OSINT AI Files** | Opens your research folder in File Explorer. |

Setup takes a while the first time: it downloads a Linux system, the assistant,
and a terminal program called MobaXterm (separate freeware; its own licence
applies).

## Install on Linux

There is no installer script for Linux. If you are comfortable in a terminal you
do not need one; from an empty folder:

```bash
curl -fsSL https://pixi.sh/install.sh | sh      # or use your package manager
git clone https://github.com/crusaderky/osint-ai.git
cd osint-ai && pixi install --locked -e default
pixi r osint-pi
```

That is all. `pixi r osint-pi` starts the assistant inside bubblewrap, working
in `workspace/`, with the same rules, skills and commands as on Windows. Your
sign-in, chat history and settings are kept in `~/.local/state/osint-ai`.

Two requirements: the `bubblewrap` package, and unprivileged user namespaces.
If the sandbox refuses to start, [docs/development.md](docs/development.md)
has the AppArmor profile Ubuntu 24.04 asks for.

`pixi r install` re-runs those checks and names whatever is missing; it installs
nothing. Local inference is not set up on Linux. Either use a hosted model with
`/login`, or build the llama.cpp runtime yourself, which
[docs/development.md](docs/development.md) explains.

## Start chatting

1. Double-click **OSINT AI Terminal**. A Linux-style window opens and the
   assistant starts on its own. Wait for the prompt. On Linux, run
   `pixi r osint-pi` in the project folder instead.
2. Type **`/login`**, press Enter, choose **OpenRouter** (see
   [the account section](#before-the-first-chat-openrouter)), paste your key, and
   the assistant remembers it from now on.
3. Type **`/model`** and pick a model.
4. Ask something in ordinary English:
   *"Check the public ownership records of ACME LTD, Nicosia, and tell me what
   you could not verify."*

Anything you type goes to the AI service you chose. Do not paste client
confidential material or personal data you are not allowed to send.

### Before the first chat: OpenRouter

OpenRouter is a shop for AI models: one account, one payment method, many models.

1. Go to <https://openrouter.ai> and create an account (you can sign in with
   Google).
2. In the OpenRouter site, click your name → **Keys** (Keys / API Keys) →
   **Create Key**. Give it a name you recognise, e.g. `osint-pc`.
3. Copy the key shown (it looks like `sk-or-v1-...`) and keep it secret, like a
   bank card PIN. Add a small amount of credit under **Credits** if you want to
   use paid models; some free models exist for testing.
4. In the assistant, type `/login`, choose **OpenRouter**, then paste the key
   (in MobaXterm: right-click to paste).

The key is stored inside the private Linux part of the installation, never in
your research folder, so it is not committed or shared.

## Save your work with Git

Git keeps a history of your files and shares it with your team through GitHub.
You do not have to understand it; you need four moves.

### 1. Create a GitHub account

Go to <https://github.com/signup>, choose a name and password, verify your email.

### 2. Install GitHub Desktop

Go to <https://desktop.github.com>, click **Download GitHub Desktop for Windows**,
install it and sign in with the account you just made.

### 3. Put your OSINT AI folder in GitHub Desktop

1. Open GitHub Desktop → **File** → **Add local repository**.
2. Choose the OSINT AI folder. It is normally
   `C:\Users\<your name>\osint-ai`. Click **Add repository**.

If it complains that the folder is not a repository, ask whoever gave you the
installation to link it to your GitHub account first.

### 4. The four moves you will use

| Move | Button | When |
| --- | --- | --- |
| **Commit** | **Commit to main**, after ticking the changed files, and write one line about what you changed | Whenever you finished a piece of work |
| **Push** | **Push origin** | Right after committing, so others get it |
| **Pull** | **Fetch origin** / **Pull origin** | Before you start work, to get your team's changes |
| **History** | **History** | To see earlier versions; right-click a change → **Revert changes** to put one back |

Commit, then Push. Everything you finish here ends with those two buttons.

On Linux, the same four moves are `git add`, `git commit`, `git push` and
`git pull` typed in the project folder.

The assistant can see this folder and run `git status` on it, so it can tell you
what is not saved yet. It is told never to commit, push or throw work away; that
stays your job in GitHub Desktop. If it ever offers to press those buttons for
you, say no and look at what it changed.

## Talking to the assistant

Type a slash, then a word, then Enter.

| Command | What it does |
| --- | --- |
| `/login` | Connect an AI service (OpenRouter and others) and store the key |
| `/model` | Choose which AI model answers you. Press **Ctrl+S** in the list to make one your usual choice |
| `/scoped-models` | Choose which models you switch between with **Ctrl+P**: tick a handful, leave the rest off |
| `/thinking` | How much "thinking time" the model gets: low is fast and cheap, high is slower and better for difficult work. Some guides call this reasoning effort |
| `/new` | Clean slate. Use it when you start a different subject |
| `/resume` | Open an earlier conversation and continue it |
| `/tree` | Walk back inside today's conversation: pick an earlier point and continue from there instead of the end. Nothing is deleted |
| `/reload` | After you edited `AGENTS.md` or a skill, this loads the new version |
| `/quit` | Close the assistant. Close the window too, or type `exit` |

Good habits:

* New subject → `/new`. Long, tangled conversation → `/tree` and jump back.
* Costly or slow model → `/model` down, or lower `/thinking`.
* The assistant writes files for you. It never commits them; that is your
  Commit and Push.

### When the assistant calls in help

For a long, wide job (a company with twenty sources to sweep, a report with many
sections) the assistant can start **sub-agents**: small copies of itself that
each do one narrow job and hand the result back. Each one is the same model, in
the same sandbox, under the same rules. The assistant still writes the answer,
and every fact still needs a link and a date.

Expect it to take longer and to use more of the model at once, so on a local
model a sub-agent job can be slow. Say plainly what you want, for example *"Check
the four registries in parallel and tell me what you could not verify"*, and keep
one subject per request. If you would rather it answered directly, say so. That
is a normal request.

If a sub-agent gets stuck, it asks the window it came from. The windows are not
connected to each other: open a second **OSINT AI Terminal** and each gets its
own channel. Nothing survives a restart.

## AGENTS.md

**`AGENTS.md`** is a plain text file the assistant reads every time it starts. It
says what a good answer looks like: which sources you trust, how to label an
unconfirmed report, where reports go, what never to do.

Yours is `workspace\AGENTS.md`, and it is safe to edit: the assistant only
follows what is written there.

You do not have to type it yourself. Ask:

> "Add a rule to AGENTS.md: every finding must state the register name and the
> search date, and any figure taken from a spreadsheet must quote the sheet and
> the row range."

Then read what it wrote, type `/reload`, and
**Commit + Push** in GitHub Desktop with a note like `rule: cite register and date`.

Keep it short and specific. Ten clear rules beat a hundred vague ones. If the
assistant ignores a rule, the rule is probably too vague: ask it to rewrite that
rule.

## Skills: your repeatable checks

A **skill** is one repeatable check, written down so the assistant does it the
same way every time. After a Commit and Push it works the same for everyone on
your team.

Skills live in `workspace\.agents\skills\<name>\SKILL.md`. Three come with the
installation: `spreadsheet-reader` (reads Excel files), `compliance-report`
(lays out the report you hand over) and `markdown-pdf` (turns Markdown into a
PDF, and a PDF back into Markdown).

Ask the assistant to make one:

> "Create a skill called `sanctions-screening` that checks the names and
> addresses we give it against publicly available sanctions lists, records the
> search URL and the date for every list, and says clearly when a list could not
> be reached."

Then:

1. Open the new `SKILL.md` in Notepad from **OSINT AI Files** and read it.
2. Type `/reload` in the assistant.
3. Test it on something you know the answer to.
4. Ask the assistant to fix what was wrong. It edits the same file.
5. **Commit + Push.**

A good skill names its inputs, lists the sources in order, says what "verified"
means, and says what to do when a source fails. Skills are instructions the
assistant trusts, so never put passwords or API keys in one.

## After any change: commit and push

`AGENTS.md` and everything under `workspace\.agents` are your team's knowledge.
They only count once they are saved to GitHub.

**After every change to `AGENTS.md` or a skill: Commit, then Push.**

The assistant will remind you when it notices unsaved or unsynced changes. If
you close the terminal straight after editing something, the change exists only
on that PC: someone else may redo work you already finished.

## Spreadsheets and PDF reports

* **Read a spreadsheet:** drop the file into your research folder (or tell the
  assistant where it is) and ask *"What sheets and columns are in
  `payments.xls`?"* or *"Convert the Ledger sheet of `payments.xlsx` into a table
  I can paste into my report."*
* **Get a PDF:** ask *"Write the findings as a PDF report."* The assistant writes
  a Markdown file first, then converts it to a PDF with page numbers and your
  title, and tells you both filenames in your research folder.
* **Read a PDF:** ask *"Summarise `annual-report.pdf` and list the related
  companies it mentions."* If the PDF is a scanned image, the assistant says so
  instead of guessing.

## If something goes wrong

| Symptom | Try this |
| --- | --- |
| The window opens and closes | Open **OSINT AI Terminal (basic)** instead and read the message |
| `Invalid API key` | Generate a new key in the OpenRouter portal and run `/login` again |
| Replies are slow | Your model may be busy: `/model`, or run the assistant with a different provider |
| The assistant does not know a rule or skill you just added | Type `/reload` |
| Something you edited is missing | Check File Explorer first, then GitHub Desktop → **History** |
| Teammates' new skills are missing | GitHub Desktop → **Pull**, then `/reload` |
| Local model will not load | The model may be too large for your PC; pick a smaller one with `/models` |

Review what the assistant produces before you rely on it. It gets things wrong,
it can repeat mistakes made by the pages it read, and an online service receives
whatever you send it. Keep confidential files outside the project folder.

If you only want to sign out of the AI service but keep the program, type
**`/logout`** in the assistant instead of uninstalling.

## Uninstall everything

Uninstalling removes the program and its private Linux part. It **never deletes
anything on GitHub**, and it does not delete your research folder unless you
delete it yourself in step 6.

You do not need administrator rights.

### 1. Save your work first

Open GitHub Desktop, tick the files, press **Commit**, then **Push**. If GitHub
Desktop is not available, copy `C:\Users\<your name>\osint-ai` somewhere else.

### 2. Close it

In the assistant type `/quit`, then close the terminal window.

### 3. Delete the desktop icons

Right-click **OSINT AI Terminal**, **OSINT AI Terminal (basic)** and **OSINT AI
Files** → **Delete**.

### 4. Remove the private Linux part (the big one)

This is where the AI sign-in, your chat history, downloaded models and the
program's Linux tools live. It cannot be undone from Windows.

Press the Windows key, type `PowerShell`, press Enter, then type these two lines,
one after the other, pressing Enter after each:

```text
wsl --list
wsl --unregister osint-ai
```

The first line lists the Linux systems on your PC; the second deletes only the
one called **osint-ai**.

> **Do not** run `wsl --uninstall`. That removes Linux from the whole computer
> and can delete other Linux systems you or your company use.

### 5. Delete the program's app folder

Press **Windows key + R**, type `%LOCALAPPDATA%`, press Enter, right-click the
**osint-ai** folder → **Delete**. This removes the downloaded installer, the copy
of MobaXterm that setup created, and the Linux disk file if step 4 was skipped.
Same thing in PowerShell:

```text
Remove-Item -LiteralPath "$env:LOCALAPPDATA\osint-ai" -Recurse -Force
```

If Windows says a file is in use, close the terminal window and try again.

If MobaXterm was already on this PC before OSINT AI, setup only pointed at it, so
it stays. Remove it through **Settings → Apps** if you want it gone.

### 6. Delete the research folder (optional)

`C:\Users\<your name>\osint-ai` holds your skills, `AGENTS.md` and reports. Delete
it only after step 1. In GitHub Desktop, choose **Repository → Remove** so it
stops appearing in the list; that only takes it off the list and deletes no
files.

### 7. Clean up your accounts

* Delete the key you made for this PC: open <https://openrouter.ai> → your name →
  **Keys** → **Delete** next to that key. Worth doing if anyone else uses this
  computer, and it stops the key working anywhere, even if a copy survived.
* GitHub Desktop: **File → Options → Accounts → Sign out** if you use a shared PC.

### 8. Leave Windows Subsystem for Linux alone

Windows' Linux feature is shared with other programs and with your company's
tools. Keep it installed unless you are certain nothing else uses it; removing it
needs an administrator and a restart
(**Windows key**, type `Turn Windows features on or off`, untick **Windows
Subsystem for Linux**, restart).

### 9. Check it is really gone

* PowerShell → `wsl --list` shows no `osint-ai`.
* **Windows key + R** → `%LOCALAPPDATA%` has no **osint-ai** folder.
* The three desktop icons are gone.

To start again later: run `windows\Install.cmd`, then in GitHub Desktop use
**Pull** to bring your skills and rules back.

On Linux there is less to remove: delete `~/.local/state/osint-ai` (sign-in,
chat history, settings) and, if you do not want it any more, the checkout. Your
work is on GitHub.

---

[Software engineer documentation](docs/development.md)
