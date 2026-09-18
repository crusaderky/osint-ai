# OSINT AI

OSINT AI is a research assistant for regulatory compliance work. Ask it about an
organisation or person and it can check public registries, sanctions lists, company
websites and news, then draft a report.

It is instructed to produce source links, dates, and a clear distinction between
verified facts, unconfirmed reports, inferences and anything it could not check.
**Review the original sources before relying on its findings.**

## Contents

- [Install on Windows](#install-on-windows)
- [Your first chat](#your-first-chat)
  - [Connect to an online AI service](#connect-to-an-online-ai-service)
  - [Choose a model](#choose-a-model)
  - [Use a local model](#use-a-local-model)
  - [Interact with the agent](#interact-with-the-agent)
  - [Session management](#session-management)
- [Working with files](#working-with-files)
  - [Global working rules: AGENTS.md](#global-working-rules-agentsmd)
  - [Skills](#skills)
  - [Save and share changes with git](#save-and-share-changes-with-git)
  - [Set up GitHub Desktop (Windows)](#set-up-github-desktop-windows)
  - [The git workflow](#the-git-workflow)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [Linux](#linux)
  - [Install on Linux](#install-on-linux)
  - [Working in Linux](#working-in-linux)
  - [Uninstall from Linux](#uninstall-from-linux)

## Install on Windows

You need Windows 11, internet access, a few GB of free disk space, and Administrator
permissions.

1. Open **PowerShell**: press the Windows key, type `powershell`, and press Enter.
   Do not choose *Run as administrator*; the installer asks for permission by
   itself when it needs it.
2. Copy the whole line below, paste it into the window (right-click pastes) and
   press Enter.

   ```powershell
   $p = "$env:TEMP\osint-ai-install.ps1"; irm https://raw.githubusercontent.com/crusaderky/osint-ai/main/windows/Install.ps1 -OutFile $p; powershell -NoProfile -ExecutionPolicy Bypass -File $p
   ```

   Approve the Windows permission request if one appears.
3. If asked to restart Windows, do so, then paste the same line again.

Setup downloads the tools it needs, so the first installation takes a while.
It creates these desktop shortcuts:

| Shortcut | Use it to… |
| --- | --- |
| **OSINT AI Terminal** | Open the assistant. Use this for everyday work. |
| **Start llama.cpp** | Start the local model server, so the assistant can use models that run on this PC. |
| **Stop llama.cpp** | Stop the local model server (not needed if you just shut down or restart your PC). |
| **Update OSINT AI** | Install the newest version of the program. |
| **OSINT AI Files** | Open the project folder in File Explorer. Your research is in `workspace`. |

## Your first chat

Double-click **OSINT AI Terminal** and wait for the chat prompt.

### Connect to an online AI service

[OpenRouter](https://openrouter.ai) gives you access to many AI models through one
account, pay-as-you-go for every prompt.

1. Create an account at <https://openrouter.ai>.
2. Add credit on the [Credits page](https://openrouter.ai/settings/credits). For the
   models recommended for OSINT AI (read below), $5 is a good starter which should last
   you for several hours of work.
3. Open [API Keys](https://openrouter.ai/settings/keys), create a key and copy it.
   This key lets the assistant use your account; keep it secret.

   You should keep an eye from time to time on the [activity control
   panel](https://openrouter.ai/activity). If you notice activity that you don't
   recognize, it is likely that your API key was stolen. Check your computer for
   malware. You should revoke the API key from the OpenRouter control panel. Also revoke
   the API key e.g. in case of stolen laptop.

   If you wish to share your OpenRouter credit with someone else, *never* give them your
   OpenRouter login/password. Instead, create a separate API key for them, which you can
   limit, monitor, and revoke independently.

4. In the chat prompt, type `/login` and press Enter. Choose **Sign in with an API
   key**, then **OpenRouter**, and paste your key when prompted. In MobaXterm,
   right-click to paste.

5. Close the terminal window and open it again (Double-click **OSINT AI Terminal**
   again) to load [the shortlist of recommended models](#choose-a-model).

Several alternative API providers are also available through `/login`. You can also use
one of many subscription services, where you pay a flat monthly fee which gives you a
certain amount of monthly usage. [OpenCode Go](https://opencode.ai/go) is a good
example. **Note:** you can't use an Anthropic (Claude) subscription.

> **Privacy:** An online AI service receives your prompts and any files the assistant
> sends it. Web searches also send queries to search services. Do not include
> confidential material or personal data unless your organisation permits it. Anything
> inside the `workspace` folder, as well as anything you write in the assistant
> terminal, could be read by third parties.

### Choose a model

Once you restart the terminal, the first model of the OSINT-AI shortlist should now be
preselected. Type `/model` to choose a different model. Use the arrow keys and Enter in
menus. Models in the shortlist are in the "scoped" tab. You can choose from all
available models by switching to "all".

**Warning:** some models are wildly more expensive than others. The most expensive
models (outside of the shortlist) will drain $5 in less than a minute!

The shortlist is up to date as of **10 October 2026** and it will change over time as
better and cheaper models appear:

| Model | Suggested thinking level | Where it runs | Ballpark cost for a 1h session |
| --- | --- | --- | --- |
| `deepseek-v4.1-flash` | high or max | OpenRouter | $1.00 |
| `mimo-v2.6-pro` | high | OpenRouter | $0.90 |
| `glm-5.3-flash` | high **(not max)** | OpenRouter | $0.66 |
| `mimo-v2.6-flash` | high | OpenRouter | $0.30 |
| `MiniCPM5-2B` | n/a | your PC | $0.01 (electricity) |

As a rule of thumb:

- more expensive models tend to be smarter;
- writing a skill requires more intelligence than following one (read below for what a
  skill is);
- a model that is too smart for a task is just wasted money.

You should experiment and find out the cheapest model that lets you write skills quickly
and precisely, and then the cheapest model that follows the instruction correctly.

Type `/thinking` in the prompt to tweak the thinking effort level. Given the same model,
higher thinking translates to better results, but also longer wait and higher cost.
Above you find a suggestion for the recommended thinking level for each model.

Regardless of intelligence and cost, prose and interaction style varies substantially
across models. Some models [talk in weird
English](https://programasweights.com/claudish/dictionary); some are extremely verbose;
some have a habit to gaslight you; some exhibit other unpleasant (in)human behaviour,
and some do all of the above at once. The models in the shortlist have been vetted and
should be *tolerable*, but there will still be differences between them. You should try
them and find out which ones you prefer.

### Use a local model

**MiniCPM5-2B** is a local model, which means it runs on your computer, doesn't require
you to pay anything, and nobody can read your conversations with it. **It is
substantially less intelligent than the other models** and should be treated as
experimental.

A gaming video card with 4GB memory or more is recommended. If you don't have one, the
model should still run but it may be extremely slow.

1. Double-click **Start llama.cpp** and wait for its window to close.
2. Open the assistant, type `/model` and choose `MiniCPM5-2B (local)`.
3. The first prompt will download the model file (~1.6 GB). After the initial download,
   you won't need internet access anymore (as long as you work on local files only).
4. When you're finished, in addition to closing the terminal, you should double-click on
   **Stop llama.cpp**.

### Interact with the agent

You can converse with the agent in the terminal in plain English.
The agent can:

- search the internet;
- access websites;
- read and write any files in the `workspace` folder;
- write and run programs to automate its own work.

After your initial prompt, the agent will generate an answer.
A few example prompts you may give:

- > What's the weather like tomorrow in London?
- > I dropped the PDF of a contract in the workspace. Are there any non-compete clauses
  > in it?
- > Fetch the stock prices for the latest year of Nvidia and Google and plot them on top
  > of each other. Save the plot as an image in the workspace.
- > Check the public records of ACME LTD and produce a full PDF report; save it in the
  > workspace.

After the initial response, you can continue the conversation, e.g. to ask follow-up
questions or to refine the output:

- > Are these non-compete clauses enforceable under British law?
- > Modify the Nvidia/Google plot: normalize both stock prices as a percentage of their
  > value from day 1, i.e. both lines must start at 1 by definition.

### Session management

When you open a new agent terminal, you are dropped into a brand new *session*. The
agent won't have any memory of previous sessions. You can resume a previous session with
`/resume`. You can also rewind the active session to a previous point, for example if
the conversation went off-path, with `/tree`.

The longer a conversation becomes, the harder it gets for the model to keep track of
what was said before; it also becomes progressively more expensive. **You should keep
separate conversations in separate sessions**. You can create a brand new session with
`/new`; you can jump back into an old one with `/resume`. You can also have multiple
parallel conversations by opening different terminals.

## Working with files

Open **OSINT AI Files**, then `workspace`. Put files you want the assistant to read
here; it cannot open arbitrary files elsewhere on your PC. Anything the assistant
generates, e.g. reports, plots, or spreadsheets, is saved here too. Keep confidential
files that the assistant should not read outside the project folder.

The `workspace` folder contains two special items: a text file named `AGENTS.md` and a
sub-folder named `.agents`.

### Global working rules: AGENTS.md

The agent automatically reads `osint-ai\workspace\AGENTS.md` every time it starts. This
is a rich-text, plain-English file, which you can open and edit with Notepad, that sets
rules for all your research: what a typical research workflow looks like, general
behaviour rules, etc.

Think about it as an instruction manual which is meant for the AI agent instead of
humans.

You can view and edit this file with any text editor. However, it is typically easier to
ask the assistant itself to update the file. **This allows it to memorize instructions
and change its behaviour across sessions.**

For example, you could prompt:

> I don't ever want you to say the word "load-bearing" again. Note it down in AGENTS.md.

**Note:** `osint-ai\workspace\AGENTS.md` should not be confused with
`osint-ai\AGENTS.md`, which is one level up, and is meant for code maintenance. You
should ignore it. Your agent can't see or modify it either.

After a change, type `/reload`, or close and reopen your terminal window to let new
sessions read the updated file.

### Skills

A **skill** is a list of instructions for a specific task. Unlike `AGENTS.md`, the AI
assistant only knows the title and brief description of each skill when it starts, and
opens the full instruction manual only when needed. This allows it to be cheaper,
faster, and more precise.

- General, always-relevant instructions go in `AGENTS.md`
- Detailed instructions to perform a specific task go in a skill; one skill per task.

Skills are also rich-text files, and they're called

`osint-ai\workspace\.agents\skills\<skill name>\SKILL.md`.

Just like `AGENTS.md`, you can prompt the assistant to create new skills or edit already
existing ones. You don't need to know the exact skill name; you can ask the agent to come
up with it. Example prompts:

> Learn how to perform a search on acme.com; then write a skill about it. On this
> website, you search for the name of one of the product ACME sells or sold in the past.
> Their search engine will get you pages with the information. There can be multiple
> pages for the same product e.g. different variant models, in which case you need to
> parse them all. The information that you need to extract are: when was it released on
> the market, at what price, and with what volume. Disregard the rest.

Or:
> You just said there's no data available before 2010 on acme.com. That's because before
> that date it can only be found at acme.com/archive, and it won't show up if you type
> it on the search bar on the front page of the website. Learn how to use the separate
> search bar for archive data and update the relevant skill.

A "task" can be any small, well-defined and constrained activity. When you need to
perform large, complex activities, always ask yourself: can they be broken down into
smaller activities that are independent of each other? If so, you should write these
sub-activities each as its own skill, **and then write another skill on top that
tells the agent to invoke the other skills and to merge their outputs**.

e.g.
> When I ask you to check for info about ACME products, you need to look them up on
> acme.com but also on amazon.com and ebay.com. Notably, acme.com will give you the
> nominal price; amazon.com gives you the real market price for new items; ebay.com can
> be used to get how much used items sell for. Write a skill that explain this; call it
> "look up ACME products" or something similar.

### Save and share changes with git

The assistant can only see and modify the `workspace` folder on your computer. Inside
it, however, it could potentially delete everything by accident! You should get into the
habit of using this workflow:

1. make a change to `AGENTS.md` or to a skill
2. test it in a new session and check if the assistant behaves as desired
3. once you're happy, *commit* the change to git and *push* it to GitHub (see next
   section).

Your agent can't do irreversible damage to anything that you committed and pushed to
GitHub. Any unwanted changes can be rolled back with GitHub Desktop (read below).

You should only use this for changes to `AGENTS.md` and to skills, to make the
assistant's behaviour repeatable. git is not a backup system for your ongoing
investigation work. You should copy-paste investigation reports etc. out of `workspace`
and into your long-term document folders.

**IMPORTANT:** everything you push to GitHub becomes visible to everybody on the
internet. **DO NOT, EVER, push confidential information such as logins, passwords, or
any other piece of data that is not publicly available on the internet.**

### Set up GitHub Desktop (Windows)

1. [Create a GitHub account](https://github.com/signup) if you do not have one.
2. Install [GitHub Desktop](https://desktop.github.com) and sign in.
3. Choose **File → Add Local Repository** and select your project folder, normally
   `C:\Users\<your name>\osint-ai` — not just its `workspace` subfolder.
4. You need to be added to the osint-ai team to be able to push to GitHub. Open a ticket
   on https://github.com/crusaderky/osint-ai/issues to ask for it.

### The git workflow

| When | What to do in GitHub Desktop |
| --- | --- |
| Before working | Click **Fetch origin**, then **Pull origin** if it appears, to get your team's changes. Type `/reload` in the assistant if instructions or skills changed. |
| After finishing | Review the changed files, tick only those you want to save, write a short summary and click **Commit to…**. This records a version on your PC. |
| To share that version | Review the commits waiting to be uploaded, then click **Push origin**. This uploads all pending commits, not just selected files. |
| To see earlier versions | Open **History**. |

Both your assistant and yourself should always work on a branch called **staging**;
never on the main branch. Your maintainer merges **staging** into the published version.

The assistant can make a commit when you ask, but it cannot push to GitHub for you.
You can also recover a previous version, selectively undoing changes. For example:

> Yesterday I told you that from now on ACME products must be looked up on newacme.com
> instead of acme.com. You updated your skills in the commit titled "use newacme instead
> of acme". That was wrong; newacme.com is a scam website. I need you to revert the
> commit.

Or you can ask it to investigate the git history for you:
> Two weeks ago you had no problems looking stuff up on acme.com and now you're failing.
> Did anything change in your relevant skill files in the meantime?

## Troubleshooting

| Problem | Solution |
| --- | --- |
| I can't see any models in the "scoped" tab | You aren't logged into OpenRouter. After `/login`, you must close the terminal and reopen it. |
| `Invalid API key` | Check or replace your key in OpenRouter, then run `/login` again. |
| A laptop with an OpenRouter API key was stolen or was riddled with malware | Sign in to the OpenRouter control panel from a different computer or phone and revoke the API key. |
| Replies are slow | Try a different model with `/model`, or lower `/thinking` where supported. |
| A new rule or skill is not recognised | Type `/reload`. If the problem persists, ask the assistant to investigate. |
| A teammate's changes are missing | In GitHub Desktop, click **Fetch origin**, then **Pull origin**, then type `/reload`. |
| MiniCPM5-2B doesn't load | Double-click **Start llama.cpp** and try again. If that window shows an error, share it with your maintainer. |
| MiniCPM5-2B is extremely slow | You need a video card with at least 4GB RAM. This is separate from your main computer's RAM. |
| The assistant is too stupid | Try a different model. |
| The assistant is too stupid and the smarter models are too expensive | Refine AGENTS.md and the skill files to make them idiot-proof. It's a good idea to spend more for a smarter model to write better skill files, and then use a dumber model to read them. |
| It's painful to read the assistant's prose | Try a different model. Try guiding behaviour using AGENTS.md. |
| It said "compacting context" and now the assistant forgot half of what we discussed before | Keep your sessions shorter and more focused. Use `/new` to clean the session. Use `/tree` to undo distracting conversation turns. |
| A skill file seems to be missing | Check `workspace` in File Explorer, then GitHub Desktop → **History**. Alternatively, ask the assistant to search in the git history for you. |

## Uninstall

Uninstalling deletes saved AI sign-ins, chat history and downloaded models. It does not
delete your Windows project folder or anything already on GitHub.

1. **Back up first.** Ensure that you left nothing important in the `workspace` folder.
2. Close the terminal windows and delete the OSINT AI desktop shortcuts.
3. Open **PowerShell** from the Windows Start menu. Run:

   ```powershell
   wsl --list
   ```

   Confirm that `osint-ai` is listed. The next command **permanently deletes
   that Linux system and everything inside it**:

   ```powershell
   wsl --unregister osint-ai
   ```

   **Do not run `wsl --uninstall` or unregister any other Linux system.**
4. Press **Windows key + R**, enter `%LOCALAPPDATA%`, and delete the `osint-ai`
   folder. If Windows says a file is in use, close the terminal and try again.
5. Delete the downloaded local models, which are large: press **Windows key + R**,
   enter `%USERPROFILE%\.cache`, and delete the `huggingface` folder.
6. Remove the Windows permission the installer added: open PowerShell
   as administrator and run
   `Remove-NetFirewallRule -DisplayName 'OSINT AI local inference'`.
7. Open `C:\Users\<your name>\osint-ai`; check that nothing important is left in the
   workspace; then delete it.
8. Revoke this PC's key on the [OpenRouter API Keys
   page](https://openrouter.ai/settings/keys). On a shared PC, also sign out of GitHub
   Desktop.

## Linux

If you have Linux as your desktop OS, you can run osint-ai natively.

### Install on Linux

Open a terminal and install Git and [Pixi](https://pixi.sh):

```bash
sudo apt install git                          # Debian and Ubuntu
sudo dnf install git                          # Fedora
curl -fsSL https://pixi.sh/install.sh | sh    # installs Pixi
```

Open a new terminal so the `pixi` command is found, then download and prepare the
program and start the assistant:

```bash
git clone https://github.com/crusaderky/osint-ai.git
cd osint-ai
pixi r install
```

On Ubuntu, `pixi r install` asks for your password to set up the apparmor sandbox.

### Working in Linux

Open a terminal, then `cd` to the project directory.
You have these commands available:

- `pixi r osint-pi` to start the OSINT AI terminal inside the `workspace/` directory
- `pixi r start-server` to start llama.cpp to run a local model
- `pixi r stop-server` to stop llama.cpp to run a local model
- `pixi r update-project` to get the latest software from the remote project on GitHub.

### Uninstall from Linux

- Credentials, chat history and settings are stored in `~/.local/state/osint-ai`
- Local model weights are stored in `~/.cache/huggingface/hub`
- Pixi is installed in `~/.pixi`
- Everything else is self-contained in the `osint-ai` directory.
