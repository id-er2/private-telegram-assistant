# Private Telegram AI Assistant (Local LLM)

A personal Telegram bot that answers only its owner, running entirely on a local LLM through Ollama. Built as a private cybersecurity study companion: it explains tools from a static knowledge base, tracks lab progress, remembers only what the owner explicitly asks it to remember, and refuses to work outside authorized lab, CTF, and explicitly permitted environments.

No cloud model API. The only external connection is Telegram's Bot API itself; the model runs on your own machine.

## Features

- **Owner-only access control.** Every handler checks the Telegram user ID against `AUTHORIZED_USER_ID` and only answers in private chat. Group messages and strangers get silence, not an error.
- **Local models via Ollama.** Defaults to `qwen2.5:7b`; `llama3` or any other pulled model works by editing `.env`. A remote Ollama URL is possible but the bot warns at startup, since conversations would leave the machine.
- **Real streaming.** Model tokens stream through a background thread into the async Telegram loop with `call_soon_threadsafe`, editing the reply message as text arrives. Telegram length limits are counted in UTF-16 units, so emoji and Arabic text chunk correctly.
- **Static tool knowledge base.** Questions about six widely known security tools are answered from a local Arabic lookup table with short general descriptions only. It provides no commands, usage examples, payloads, or attack instructions.
- **Honest persistence.** Conversation history and owner facts live in local JSON files with atomic writes and one-time `.bak` backups. A corrupt state file stops writes instead of being overwritten, and save failures are reported in chat rather than hidden.
- **Explicit memory only.** The bot never saves facts about you on its own. Say "تذكر إن ..." to store a fact, "انسَ ..." to delete it, `/profile` to review everything stored.
- **Lab tracking.** `/lab start`, `note`, `status`, `end`, `history`, and `forget` manage an active lab and an archive of finished ones. Current lab notes are injected into the model context so follow-up answers account for what you already tried.
- **Token-safe logging.** A logging filter and formatter scrub bot-token-shaped strings from every log line, including tracebacks, and httpx/httpcore request logging is silenced.

## Safety scope

The assistant's system prompt limits its help to defensive education, the owner's own lab environments, CTF challenges, and systems he has explicit permission to test. It asks about scope when permission is unclear and refuses requests to target people, systems, or services outside it. This boundary was tightened deliberately before publication.

## Project layout

```text
private-telegram-assistant/
  main.py              Telegram handlers, menus, streaming loop, access gate
  agent.py             Ollama chat calls, payload building, streaming
  config.py            Environment-based settings, system prompt, log scrubbing
  memory.py            Atomic JSON conversation history with legacy migration
  owner_state.py       Saved facts and lab state, fail-closed on corruption
  tools_knowledge.py   Arabic lookup of brief descriptions for six known tools
  tests/test_offline.py  23 offline tests (no Telegram or Ollama needed)
  run.bat              Windows launcher: isolated .venv, dependency install, start
  requirements.txt
  .env.example         Copy to .env and fill in your own values
```

## Requirements

- Python 3.10 or newer
- Ollama running locally, with the model pulled:

```bash
ollama pull qwen2.5:7b
```

- A Telegram bot token from BotFather and your numeric Telegram user ID (for example via @userinfobot)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env               # fill in TELEGRAM_BOT_TOKEN and AUTHORIZED_USER_ID
python main.py
```

On Windows, `run.bat` does all of this in an isolated `.venv` inside the project folder and refuses to start without a `.env`.

## Configuration

Everything sensitive or machine-specific comes from `.env`; nothing is hardcoded:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | (required) | BotFather token |
| `AUTHORIZED_USER_ID` | (required) | Numeric Telegram user ID of the only person the bot answers |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint; a non-local host triggers a startup warning |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Model name as known to Ollama |
| `CONTEXT_WINDOW` | `20` | Messages fed back to the model |
| `MAX_RESPONSE_TOKENS` | `900` | `num_predict` ceiling |
| `MAX_CONVERSATIONS` | `300` | History trim length |
| `SAVE_INTERVAL` | `5` | Periodic save cadence between forced saves |
| `MEMORY_FILE` / `OWNER_STATE_FILE` / `LOG_FILE` | local filenames | Runtime state locations |

`memory.json`, `owner_state.json`, their `.bak` copies, and logs are local runtime data and are excluded by `.gitignore`.

## Tests

```bash
python -m unittest discover -s tests -v
```

23 tests run fully offline with stubbed network modules: Arabic remember/forget parsing, UTF-16 chunking, state rollback on disk failure, corrupt-file fail-closed behavior, legacy memory migration, token scrubbing in logs and tracebacks, the access gate (group and stranger silence), thread-safe streaming, and context injection of saved facts and lab notes.

## Known limitations

- The tool directory provides brief descriptions only. It does not explain operational use or verify whether a tool is appropriate for a particular system.
- **The bot does not execute commands.** It analyzes and advises; it cannot run tools on your machine.
- **Live Telegram and Ollama paths are untested here.** The offline suite covers logic, not real message delivery or real model responses; verify on first run.
- **Abrupt shutdown can lose recent exchanges.** Completed exchanges save immediately, but an unfinished stream may not persist.
