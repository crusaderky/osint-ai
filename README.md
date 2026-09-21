# OSINT AI

A private, AI-assisted filing cabinet for compliance research. You ask it about a
company or a person; it reads public sources — registries, sanctions lists,
company websites, news, filings — and writes down what it **verified**, what is
only **reported**, what it **inferred** and what it **could not check**. Every
fact carries a link and the date you looked.

You keep nothing in a black box: the research instructions it follows are plain
text files that you can read, change and share. Those files are called
**skills**, and building them up is the real value of this project.

---

## Contents

1. [Install once](#install-once)
2. [Start chatting](#start-chatting)
3. [Save your work with Git (5 minutes, once)](#save-your-work-with-git-5-minutes-once)
4. [Talking to the assistant (the commands you need)](#talking-to-the-assistant-the-commands-you-need)
5. [AGENTS.md: the rulebook](#agentsmd-the-rulebook)
6. [Skills: your repeatable checks](#skills-your-repeatable-checks)
7. [After any change: commit and push](#after-any-change-commit-and-push)
8. [Spreadsheets and PDF reports](#spreadsheets-and-pdf-reports)
9. [If something goes wrong](#if-something-goes-wrong)
10. [Uninstall everything](#uninstall-everything)

---

## Install once

You need a Windows 11 PC (Intel or AMD), internet access and about 5 GB of free
disk space. An NVIDIA graphics card is optional; without one the assistant runs
more slowly on the processor.

1. Download and unzip the installation package.
2. Double-click **`wsl\Install.cmd`** and follow the prompts. If Windows asks for
   permission to make changes, allow it.
3. If Windows asks you to restart, do it, then double-click **`wsl\Install.cmd`**
   again. Setup continues where it stopped.

When it finishes you get three desktop icons:

| Icon | What it does |
| --- | --- |
| **OSINT AI Terminal** | Opens the assistant and starts it for you. This is the one you use every day. |
| **OSINT AI Terminal (basic)** | Same, in a plain Windows window. Use it if the other one ever misbehaves. |
| **OSINT AI Files** | Opens your research folder in File Explorer. |

Setup takes a while the first time: it downloads a Linux system, the assistant,
and a terminal program called MobaXterm (separate freeware; its own licence
applies).

## Start chatting

1. Double-click **OSINT AI Terminal**. A Linux-style window opens and the
   assistant starts on its own. Wait for the prompt.
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

Commit, then Push. That order is enough to remember. Everything you do in this
project ends with those two buttons.

## Talking to the assistant (the commands you need)

Type a slash, then a word, then Enter.

| Command | What it does |
| --- | --- |
| `/login` | Connect an AI service (OpenRouter and others) and store the key |
| `/model` | Choose which AI model answers you. Press **Ctrl+S** in the list to make one your usual choice |
| `/scoped-models` | Choose which models you switch between with **Ctrl+P** — tick a handful, leave the rest off |
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

## AGENTS.md: the rulebook

**`AGENTS.md`** is a plain text file the assistant reads every time it starts. It
tells the assistant what "good" looks like: which sources you trust, how to
label an unconfirmed report, where to save a report, what never to do.

Yours is `workspace\AGENTS.md` (Windows) and it is safe to edit: the assistant
only follows what is written there.

You do not have to type it yourself. Ask:

> "Add a rule to AGENTS.md: every finding must state the register name and the
> search date, and any figure taken from a spreadsheet must quote the sheet and
> the row range."

Then read what it wrote, type `/reload`, and
**Commit + Push** in GitHub Desktop with a note like `rule: cite register and date`.

Keep it short and specific. Ten clear rules work better than a hundred vague
ones. If the assistant ignores a rule, the rule is usually too vague — ask it to
rewrite that rule.

## Skills: your repeatable checks

A **skill** is one repeatable check, written down so the assistant performs it
the same way every time — for you, and for everyone on your team after a
Commit and Push.

Skills live in `workspace\.agents\skills\<name>\SKILL.md`. Two come with the
installation: `spreadsheet-reader` (reads Excel files) and `markdown-pdf`
(writes PDF reports).

Ask the assistant to make one:

> "Create a skill called `sanctions-screening` that checks the names and
> addresses we give it against publicly available sanctions lists, records the
> search URL and the date for every list, and says clearly when a list could not
> be reached."

Then:

1. Open the new `SKILL.md` in Notepad from **OSINT AI Files** and read it.
2. Type `/reload` in the assistant.
3. Test it on something you know the answer to.
4. Ask the assistant to fix what was wrong — it edits the same file.
5. **Commit + Push.**

A good skill names its inputs, lists the sources in order, says what "verified"
means, and says what to do when a source fails. Skills are instructions the
assistant trusts, so never put passwords or API keys in one.

## After any change: commit and push

`AGENTS.md` and everything under `workspace\.agents` are your team's knowledge.
They only count once they are saved to GitHub.

**After every change to `AGENTS.md` or a skill — Commit, then Push.**

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

Review what the assistant produces before you rely on it. It can be wrong, it
repeats the mistakes of the pages it reads, and an online AI service receives
what you send it. Keep confidential files outside the project folder.

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

To start again later: run `wsl\Install.cmd`, then in GitHub Desktop use **Pull**
to bring your skills and rules back.

---

[Software engineer documentation](docs/development.md)
