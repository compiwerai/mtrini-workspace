# Mtrini Workspace

[![Release](https://img.shields.io/github/v/release/compiwerai/mtrini-workspace)](https://github.com/compiwerai/mtrini-workspace/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![CI](https://github.com/compiwerai/mtrini-workspace/actions/workflows/ci.yml/badge.svg)](https://github.com/compiwerai/mtrini-workspace/actions)

**Your AI. Your code. Your workspace.**

Open-source AI development environment by **Compiwer AI** — *Building AI For Everyone.*

> Build software with local models, Hugging Face models, and configurable cloud/API models — through one model-agnostic agent.

- Local AI (llama.cpp / Ollama / vLLM / any OpenAI-compatible server)
- Hugging Face browser, auth, downloads
- API providers: OpenAI, Anthropic, Gemini, OpenRouter, Mistral, DeepSeek, Groq,
  Together, Fireworks, xAI (Grok), Cohere, Cerebras, DeepInfra, Nebius, SambaNova,
  Novita, SiliconFlow, Azure OpenAI, custom (24 total)
- Local runtimes: llama.cpp, Ollama, LM Studio, vLLM, any OpenAI-compatible server
- MCP dev tools: connect any MCP server (stdio / streamable HTTP), lend tools to
  the agent, inspect schemas and run calls manually
- Mtrini Images: generate pictures with image models from any image-capable
  provider (OpenAI, Together, Fireworks, xAI, Gemini, Hugging Face, SD WebUI…)
- Real tool-using coding agent (inspect → plan → change → test → verify) with plan mode,
  task lists, diffs, rewind, subagents, hooks, web search and a headless CLI
- Monaco editor, terminal, Git, skills, specialized agents, model routing
- Local-first, no telemetry, Apache-2.0

## Architecture

```
frontend/  React + TypeScript + Vite + Monaco (port 5173)
backend/   Python + FastAPI + asyncio (port 8787, REST + SSE)
.mtrini/   project memory: config.json, instructions.md, skills/, agents/
```

Agent loop: `UNDERSTAND → PLAN → INSPECT → USE TOOLS → MODIFY → TEST → FIX → VERIFY → RESPOND`.
The agent only speaks the unified `ModelProvider` interface (`chat/stream/list_models/...`), so
Mtrini → Qwen → Gemini → OpenAI → local llama.cpp needs no agent rewrite.

## Desktop app (Windows exe + setup)

No Python/Node needed at runtime:

```powershell
.\scripts\build-exe.ps1        # builds frontend, exe -> dist\MtriniWorkspace\
iscc scripts\setup.iss         # needs Inno Setup 6 -> installer\MtriniWorkspace-Setup-0.8.0.exe
```

Run `MtriniWorkspace.exe` (or install the Setup): it serves the API **and**
the UI from one process and opens `http://127.0.0.1:8787` in your browser.
Silent install: `MtriniWorkspace-Setup-0.8.0.exe /SILENT`.

## Hugging Face → run locally (tested flow)

Verified end-to-end with `Segilmez06/SmolLM2-135M-Instruct-Q2_K-GGUF` (88 MB)
on `llama-server` + the Mtrini `local` provider:

1. Models panel → search HF → download. Big repos: use the single-file endpoint
   so only one `.gguf` is fetched (size reported, no silent multi-GB pulls):
   `POST /api/hf/download-file {"repo": "...", "filename": "model-q4_k_m.gguf"}`
   → stored in `.mtrini/models/<repo>/` + registered in `/api/registry`.
2. Serve it: `llama-server -m .mtrini/models/<repo>/model-q4_k_m.gguf --port 8000`
3. Settings → Providers → `local`, Base URL `http://localhost:8000/v1` → top-bar
   pill → pick the model. Check `/api/local/endpoint` for reachability.
4. Chat/agent streams from your local GPU/CPU; nothing leaves the machine.

Only `.gguf` runs on llama.cpp/Ollama. Safetensors snapshots import fine but need
a transformers/vLLM server instead — the UI shows the format so this is explicit.

## Installation

Requires Node 18+ and Python 3.10+.

```bash
git clone <your-fork> mtrini-workspace && cd mtrini-workspace
pip install -r backend/requirements.txt
npm install --prefix frontend
```

## Run

Two processes (or `npm run dev` from the root with `concurrently`):

```bash
# backend (http://localhost:8787)
python -m uvicorn mtrini.main:app --app-dir backend --reload --port 8787

# frontend (http://localhost:5173)
npm run dev --prefix frontend
```

Or via CLI:

```bash
pip install -e backend
mtrini /path/to/project --provider local --model mymodel
mtrini --version
```

Pick a working folder on first launch (sidebar → folder button, recents kept).
Threads, skills, automations and the model registry are stored per folder.
Configure a provider in Settings → Providers (local server or API key) to start a thread.

## Local models

Settings → Providers → **local**:

| Field | Example |
|---|---|
| Base URL | `http://localhost:8000/v1` |
| Model | `mtrini-27b` |

Works with `llama-server`, Ollama (`http://localhost:11434/v1`), vLLM, or any OpenAI-compatible server.
Runtime detection lives in Settings (python/git/node/ollama/llama-server).

## Hugging Face

Models panel → search, or Settings → Providers → `huggingface` → paste token
(stored in OS keychain via `keyring`, fallback `.mtrini/secrets.json` with 0600, gitignored, never logged).
Search → details → download → import into the local registry.

## API providers

Settings → Providers: OpenAI, Anthropic, Gemini, OpenRouter, Mistral, DeepSeek, Groq,
Together, Fireworks, xAI, Cohere, Azure OpenAI (deployment name = model), custom.
Ollama and LM Studio have one-click presets. Each chat can work in its own folder
(composer folder chip). Cmd/Ctrl+K opens the command menu (threads, files, actions).
The composer thinking selector (Off/Low/Medium/High/XHigh/Max) drives native reasoning
controls on OpenAI, Anthropic, Gemini and Azure reasoning models, and deepens the
agent's tool loop from 12 up to 60 steps.
Settings cover appearance (liquid glass / dark / light / system theme, accent, density, editor font,
minimap, word wrap), agent permission defaults, terminal size, providers, shortcuts
and about — no emoji chrome, all stroke icons.
Each stores: name, API key (keychain), base URL, default model. Model selector in the top bar switches without restart.

## Agent

The agent works in a loop: it reads, plans, edits, runs commands and tests, and checks its
work, with a live timeline of every step. Each session keeps its full tool history in
`.mtrini/sessions/`, so an approval continues the same turn instead of starting over.

- **Permission modes:** Ask before edits, Auto-accept edits, Read-only, and **Plan mode**
  (researches read-only, then shows a plan you approve, send back with notes, or approve
  straight into auto mode).
- **Approvals:** Allow once, Deny, or **Always allow**. Rules live in
  `.mtrini/permissions.json`; shell rules cover one command prefix (`npm test`) and never a
  chain like `npm test && …`, and commands flagged destructive always ask.
- **Task list:** for longer jobs the agent keeps a checklist above the composer.
- **Diffs:** every file write and edit shows a colored diff in the timeline.
- **Rewind:** the ↺ button on any of your messages puts back the files the agent changed
  from that point on and removes those turns. Changes made by shell commands are not undone.
- **Subagents:** the agent can hand a self-contained job to a subagent with its own context.
  Subagents can read and search, and only change files in auto mode. Define project agents in
  `.mtrini/agents/<name>.md`.
- **Context compaction:** near the model's context limit, older turns are summarized
  automatically; `/compact` does it on demand.
- **Hooks:** `.mtrini/hooks.json` runs your commands on `PreToolUse` (exit code 2 blocks the
  call), `PostToolUse`, `UserPromptSubmit` and `Stop`. Hooks stay off until you trust that
  exact file (trust is stored outside the project, so a cloned repo can't switch them on).
- **Web:** `web_fetch` reads pages; `web_search` uses Brave, Tavily or your own SearXNG
  (Settings → Agent → Web search).
- **Images:** paste or drop screenshots into the composer (vision models).
- **Providers:** tool calling works with OpenAI-compatible servers, Anthropic (official SDK,
  adaptive thinking with effort levels on current Claude models) and Gemini (function calling).

Slash commands: `/help /clear /compact /init /agents /permissions /skills /mcp /settings`.
Project memory: `.mtrini/instructions.md`, `.mtrini/skills/*/SKILL.md`, `.mtrini/agents/*.md`.

### Headless (CLI)

```bash
mtrini -p "fix the failing test"                 # one agent turn in the terminal
echo "explain main.py" | mtrini -p -             # prompt from stdin
mtrini -p "update deps" --mode auto --json       # no approvals, JSON events (CI)
mtrini -p "now add tests" --thread cli-1a2b3c4d  # continue a session
```

In a terminal, approvals are asked inline (`y`es / `a`lways / `n`o). Without a terminal, a
step that needs approval stops with exit code 2.

## Skills

Create `.mtrini/skills/<name>/SKILL.md` (or `~/.mtrini/skills/` for global skills).
They are listed in the project endpoint and injected into agent context on demand.

## Development

```bash
pytest backend/tests -q          # backend (test stub, no paid APIs, no network)
npm test --prefix frontend
npm run build --prefix frontend  # production build
ruff check backend
```

CI (GitHub Actions): lint + typecheck + backend tests + frontend tests + build, no secrets required.

## API

| Method | Route |
|---|---|
| GET | `/api/health` `/api/about` `/api/runtimes` |
| GET/POST | `/api/providers` `/api/providers/configure` `/api/models` |
| GET/POST | `/api/registry` (local model registry) |
| GET | `/api/hf/search` `/api/hf/details` `/api/hf/whoami` |
| POST | `/api/hf/download` |
| GET | `/api/project` `/api/skills/{name}` `/api/git/status` `/api/git/diff` |
| POST | `/api/chat` (SSE) `/api/agent` (SSE; `threadId`, `resume`, `images`) `/api/tools/execute` `/api/terminal/exec` |
| GET/POST | `/api/agent/session/{id}` `/api/agent/rewind` `/api/agent/compact` |
| GET/POST | `/api/hooks` `/api/hooks/trust` `/api/permissions` `/api/websearch` |

Full reference: `docs/API.md`.

## Privacy

Local models stay local. No telemetry. API requests go only to providers you configure.
Credentials live in the OS keychain (documented file fallback), never in `config.json`, git, logs, or frontend source.
See `PRIVACY.md` and `SECURITY.md`.

## License

Apache-2.0 — see `LICENSE`. Third-party licenses: `docs/THIRD-PARTY.md`.
