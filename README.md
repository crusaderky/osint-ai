# Open Source Intelligence AI

Research public information with a chatbot. Turn repeatable checks into **skills**:
reusable instructions you can review, improve, and share.

## Install

You need a Windows 11 PC with an Intel or AMD processor and internet access.
Setup may ask for administrator approval and a restart.

1. Download and extract the installation package.
2. Double-click **Install.cmd** and follow the prompts.
3. If asked to restart Windows, do so, then double-click **Install.cmd** again.

## Start chatting

1. Open the **OSINT AI Terminal** desktop shortcut.
2. Type this and press Enter:

   ```text
   osint-pi
   ```

3. Type **`/login`**, choose a service such as OpenRouter or OpenCode, and follow
   the instructions. Open any login link in your Windows browser.
4. Type **`/model`** to choose an AI model, then ask your question.

Your sign-in is remembered. Online services may charge for use.

### Optional: run AI on your own PC

An NVIDIA graphics card is required. In **OSINT AI Terminal**, run:

```text
start-server
osint-pi
```

Inside the chatbot, type **`/models`** to choose a local model. First use can
require a large download, and some models may be too large for your PC.

To stop local AI, leave the chatbot with `/quit`, then run `stop-server`.

## Create and share a skill

1. Ask the chatbot, for example: **“Create a skill for checking a company's
   public ownership records.”**
2. Open the **OSINT AI Files** desktop shortcut, then the **agents** folder.
3. Open the new skill's **SKILL.md** file with Notepad to review or edit it.
   Type `/reload` in the chatbot after making changes.
4. Open the project folder in your Windows Git app, such as GitHub Desktop or
   GitKraken. Review the changes, **commit** to save a revision, then **push**
   to share it on GitHub.

Review generated skills and findings before relying on them. Online AI services
may receive project content; keep private files outside the project.

---

[Software engineer documentation](docs/development.md)
