# OSINT AI

OSINT AI is a research assistant for regulatory compliance work. Ask it about
an organisation or person, and it can check public registries, sanctions lists,
company websites and news, then draft a report.

Its instructions require source links and dates, and a clear distinction between
verified facts, unconfirmed reports, inferences and anything it could not check.
**Review the original sources before relying on its findings.**

## Contents

- [Install on Windows](#install-on-windows) · [Install on Linux](#install-on-linux)
- [Your first chat](#your-first-chat)
- [The model shortlist](#the-model-shortlist)
- [Files and reports](#files-and-reports)
- [Save and share your work](#save-and-share-your-work)
- [Useful commands](#useful-commands)
- [Instructions and skills](#instructions-and-skills)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)

## Install on Windows

You need Windows 11 on an Intel or AMD PC, internet access and several GB of free
space. Local AI models need additional space. If this is a work PC, check with
your IT team before installing.

1. Get the installation package from your project maintainer and unzip it.
2. Double-click **`windows\Install.cmd`** inside the extracted folder. Follow
   the prompts and approve the Windows permission request if one appears.
3. If asked to restart Windows, do so, then run **`windows\Install.cmd`** again.

Setup downloads the tools it needs, so the first installation takes a while.
It creates these desktop shortcuts:

| Shortcut | Use it to… |
| --- | --- |
| **OSINT AI Terminal** | Open the assistant. Use this for everyday work. |
| **Start llama.cpp** | Start the local model server, so the assistant can use models that run on this PC. |
| **Stop llama.cpp** | Stop it again when you are finished; it also stops when you restart the PC. |
| **OSINT AI Files** | Open the project folder in File Explorer. Your research is in `workspace`. |
| **OSINT AI Terminal (basic)** | Open an alternative chat window if the main one has problems. |

Setup may ask for Windows permission twice: once to add Windows' Linux feature,
and once to let the assistant reach the local model server, which runs on Windows
itself. The **basic** shortcut is optional: if MobaXterm is unavailable, the main
shortcut uses a plain Windows window instead. MobaXterm is a separate terminal
program with its own licence.

## Your first chat

Double-click **OSINT AI Terminal** and wait for the chat prompt. On Linux,
run `pixi r osint-pi` in the project folder instead.

### Connect an online AI service

OpenRouter gives you access to several AI models through one account. Other
services are also available through `/login`; use one your organisation approves.

1. Create an account at <https://openrouter.ai>.
2. Open [API Keys](https://openrouter.ai/settings/keys), create a key and copy it.
   This key lets the assistant use your account; keep it secret.
3. For paid models, add credit on the
   [Credits page](https://openrouter.ai/settings/credits). Check the model's
   price before using it.
4. In the assistant, type **`/login`** and press Enter. Choose **Sign in with an
   API key**, then **OpenRouter**, and paste your key when prompted. In MobaXterm,
   right-click to paste.
5. Type **`/model`** and choose a model. Use the arrow keys and Enter in menus.

Your sign-in is saved outside the project folder, along with your chat history
and settings. You do not need to enter the key each time.

> **Privacy:** An online AI service receives your prompts and any file content
> the assistant sends it. Web searches also send queries to search services.
> Do not include confidential material or personal data unless your organisation
> permits it.

### Ask a question

Give the name, location and the checks you need. For example:

> Check the public ownership records of ACME LTD in Nicosia. Cite each source
> and the search date, and tell me what you could not verify.

### Use a model on this PC instead (Windows)

Local models run on Windows itself, not inside the assistant's Linux system, so
they can use your graphics card. No online AI account is needed.

1. Double-click **Start llama.cpp** and wait for its window to close.
2. Open the assistant, type **`/model`** and choose the model whose name ends in
   **`(local)`** — for example `MiniCPM5-2B (local)`.

The first time a model is used, it is downloaded: this can take several minutes
and several GB of space, and the assistant may appear to be waiting while it
happens. To watch the progress, or to download a model before you need it, type
**`/llama`** and choose it there. Choose a small model to start with; larger ones
may not fit your PC's memory. A Vulkan-capable graphics card makes local models
much faster — most modern ones are — and without one the assistant uses the
processor instead, which is slow. Web research always uses the internet.

## The model shortlist

The assistant starts with a pre-configured list of scoped models, short list of models
worth using, picked for research and report work and for a price that makes sense for
it:

| Model | Suggested thinking level | Where it runs | Typical cost for a 1h session |
| --- | --- | --- | --- |
| `deepseek-v4.1-flash` | high or max | OpenRouter | $1.00 |
| `mimo-v2.6-pro` | high | OpenRouter | $0.90 |
| `glm-5.3-flash` | high _(not max)_ | OpenRouter | $0.66 |
| `mimo-v2.6-flash` | high | OpenRouter | $0.30 |
| `MiniCPM5-2B (local)` | n/a | your PC | $0.01 (electricity) |

The above is up to date as of **10 October 2026** and it will change over time as better
and cheaper models appear.

MiniCPM5-2B is substantially less intelligent than the other models and should be used
only for running the skills, not to write new ones. It requires a 4GB video card and to
start llama.cpp before it can be used; see
[local models](#use-a-model-on-this-pc-instead-windows).

Type `/model` in pi to select a model; type `/thinking` to select a thinking effort.

## Files and reports

Open **OSINT AI Files**, then **`workspace`**. On Linux, open `workspace/` in
your project folder. Put files you want the assistant to read here; it cannot
open arbitrary files elsewhere on your PC. Its reports are saved here too.

Try requests such as:

- **Spreadsheet:** “List the sheets and columns in `payments.xlsx`.” Excel
  (`.xls`, `.xlsx`, `.xlsb`) and CSV files are supported.
- **PDF report:** “Write these findings as a PDF report.” You get the PDF and
  an editable Markdown (`.md`) text version.
- **Read a PDF:** “Summarise `annual-report.pdf` and list the related companies.”
  Scanned PDFs may need text recognition before they can be read.

Keep confidential files that the assistant should not read outside the project
folder.

## Save and share your work

Files are saved on your PC as you work. Git records versions of those files;
GitHub stores the versions you upload and lets your team share them. Chat
history and AI sign-in details are stored separately, not in this folder.

### Set up GitHub Desktop (Windows)

1. [Create a GitHub account](https://github.com/signup) if you do not have one.
2. Install [GitHub Desktop](https://desktop.github.com) and sign in.
3. Choose **File → Add Local Repository** and select your project folder,
   normally `C:\Users\<your name>\osint-ai` — not just its `workspace` subfolder.

Before uploading work, ask your project maintainer to connect this folder to
your team's repository. **The default software repository is public.** Check
who can access the destination, and use a private repository for non-public
work. If GitHub Desktop cannot add the folder or upload changes, ask the
maintainer for help.

### Everyday steps

| When | What to do in GitHub Desktop |
| --- | --- |
| Before working | Click **Fetch origin**, then **Pull origin** if it appears, to get your team's changes. Type `/reload` in the assistant if instructions or skills changed. |
| After finishing | Review the changed files, tick only those you want to save, write a short summary and click **Commit to…**. This records a version on your PC. |
| To share that version | Review the commits waiting to be uploaded, then click **Push origin**. This uploads all pending commits, not just selected files. |
| To see earlier versions | Open **History**. |

The assistant works on a branch called **staging**, never on the published
version. Leave the branch shown in GitHub Desktop alone: your maintainer merges
**staging** into the published version. The assistant can make a commit when you
ask. It is instructed not to push, ask for your GitHub credentials or discard
work. Review its changes yourself; these instructions are not a substitute for
backups.

On Linux, use a Git app or run `git add`, `git commit`, `git pull` and `git push`
in the project folder. The assistant can commit; you handle uploading.

## Useful commands

Type the command and press Enter. Type `/` on its own to browse available
commands. Press **Esc** to stop the assistant while it is working.

| Command | What it does |
| --- | --- |
| `/model` | Choose an AI model, including one that runs on this PC. Press **Ctrl+S** in the list to save your usual choice. |
| `/llama` | Load or remove local models, and download new ones. Only useful after **Start llama.cpp**. |
| `/new` | Start a fresh conversation for a different subject. |
| `/resume` | Continue a saved conversation. |
| `/reload` | Load changes to instructions or skills. |
| `/quit` | Close the assistant; then close the window. |

<details>
<summary>More controls</summary>

- **`/thinking`** changes how much reasoning the model uses, where supported.
  Higher levels can take longer and cost more; they do not guarantee accuracy.
- **`/scoped-models`** chooses which models you cycle through with **Ctrl+P**.
- **`/tree`** lets you continue from an earlier point in the current conversation.
  It does **not** undo file changes.
- **`/login`** connects another AI service; **`/logout`** removes a saved sign-in.
  Logging out does not revoke the key at the service.

For larger jobs, the assistant may use helper assistants to split up research.
This can increase time and cost. Ask it to work without helpers if you prefer.

</details>

## Instructions and skills

You can change how the assistant works through plain text files in `workspace`.
Ask it to make the change, then open the file in Notepad to read it.
Leave the other project folders and top-level files to your maintainer.

### Working rules: AGENTS.md

**`workspace\AGENTS.md`** sets rules for all your research: trusted sources,
report locations and how to handle unconfirmed information. This is the
assistant's instruction file; the top-level `AGENTS.md` is for maintainers.

For example:

> Add a rule to AGENTS.md: every finding must name the register and search date.

After a change, read the file and type **`/reload`**. Test the rule on a familiar
case and ask for corrections if needed. Then
[commit and push](#save-and-share-your-work) when it is ready to share.

### Repeatable checks: skills

A **skill** is a set of instructions for a particular task. Three are included:

| Skill | Purpose |
| --- | --- |
| `spreadsheet-reader` | Read Excel and CSV files. |
| `compliance-report` | Structure a report with evidence and confidence labels. |
| `markdown-pdf` | Convert Markdown to PDF and extract text from PDFs. |

To add your own:

> Create a skill called `sanctions-screening`. Check names and addresses against
> public sanctions lists. Record each search URL and date, and say when a list
> could not be reached.

Skills belong in **`workspace\.agents\skills\<name>\SKILL.md`**. Read the new
file, type **`/reload`**, and test it on a case you know. Ask for corrections
before sharing it. Never put passwords, API keys or personal data in a skill.

## Troubleshooting

| Problem | Try this |
| --- | --- |
| The chat window closes immediately | Use **OSINT AI Terminal (basic)** if available. Otherwise, ask your maintainer for help. |
| `Invalid API key` | Check or replace your key in OpenRouter, then run `/login` again. |
| Replies are slow | Try a different model with `/model`, or lower `/thinking` where supported. |
| A new rule or skill is not recognised | Type `/reload`. |
| A teammate's changes are missing | In GitHub Desktop, click **Fetch origin**, then **Pull origin**, then type `/reload`. |
| A local model is not in the list, or will not load | Double-click **Start llama.cpp** and try again. If that window shows an error, share it with your maintainer. |
| A file seems to be missing | Check `workspace` in File Explorer, then GitHub Desktop → **History**. |

Pulling team files does not update the installed program. For program changes,
ask your maintainer to update the project root checkout and run `update-project`
on the WSL side (Windows' Linux system). Some changes require reinstalling;
see the [maintenance guide](docs/development.md).

## Uninstall

### Windows

**Back up first.** Copy your project folder somewhere safe, or commit and push
files that are safe to share. Uninstalling deletes saved AI sign-ins, chat
history and downloaded models. It does not delete your Windows project folder
or anything already on GitHub.

1. Type `/quit`, close the terminal windows and delete the OSINT AI desktop
   shortcuts.
2. Open **PowerShell** from the Windows Start menu. Run:

   ```powershell
   wsl --list
   ```

   Confirm that `osint-ai` is listed. The next command **permanently deletes
   that Linux system and everything inside it**:

   ```powershell
   wsl --unregister osint-ai
   ```

   **Do not run `wsl --uninstall` or unregister any other Linux system.**
3. Press **Windows key + R**, enter `%LOCALAPPDATA%`, and delete the `osint-ai`
   folder. If Windows says a file is in use, close the terminal and try again.
   This also removes the local model server and the tools it installed.
4. Delete the downloaded local models, which are large: press **Windows key + R**,
   enter `%USERPROFILE%\.cache`, and delete the `huggingface` folder. Only do this
   if no other program on this PC uses it.
5. Optionally remove the Windows permission the installer added: open PowerShell
   as administrator and run
   `Remove-NetFirewallRule -DisplayName 'OSINT AI local inference'`.
6. Optionally delete `C:\Users\<your name>\osint-ai` after checking your backup.
   Keep it if you want to retain your research and skills.
7. Delete this PC's key on the [OpenRouter API Keys page](https://openrouter.ai/settings/keys).
   On a shared PC, also sign out of GitHub Desktop.

Leave Windows' Linux feature installed; other programs may use it. An existing
MobaXterm installation is left in place. To reinstall, run
**`windows\Install.cmd`** again; an existing project folder is preserved.

### Linux

Back up your work, then remove `~/.local/state/osint-ai` to delete sign-ins,
chat history and settings. A local model server installed with
`pixi r start-server` keeps its runtime in `.pixi/envs/llamacpp-binary-vulkan`
inside the project folder, its log and pid file in that same state directory, and
its weights in `~/.cache/huggingface`; remove those separately. Remove the
project folder only if you no longer need it. See the
[maintenance guide](docs/development.md) for the locations.

## Install on Linux

On an x64 Linux system, install Git and [Pixi](https://pixi.sh), then open a new
terminal:

```bash
git clone https://github.com/crusaderky/osint-ai.git
cd osint-ai
pixi install --locked -e default
pixi r install
pixi r osint-pi
```

Use an online AI service as described under [Your first chat](#your-first-chat).
Sign-ins, chats and settings are kept in `~/.local/state/osint-ai`, outside the
project folder.

To run a model on your own PC instead, start the model server:

```bash
pixi r start-server      # first run downloads the model server, then starts it on 127.0.0.1:8080
```

Then start the assistant, type `/model` and choose the model whose name ends in
`(local)`. It uses a Vulkan-capable graphics card when one works and falls back
to the processor otherwise. More:
[local inference](docs/development.md#providers-and-local-inference).

`pixi r install` checks the setup and makes the sandbox allowed to run. It installs
no extra programs: the sandbox uses the copy of bubblewrap that comes with the rest
of the program, not one your system provides. On Ubuntu 24.04 it asks for your
password once, because Ubuntu needs a security setting switched before that copy
may start; see the
[AppArmor setup](docs/development.md#installing-on-linux).

If the assistant will not start, run `pixi r install` again and fix the lines
marked MISSING. The sandbox needs unprivileged user namespaces.

---

For maintainers: [development](docs/development.md) ·
[security](docs/security.md) · [testing](docs/testing.md).
