# Mtrini Workspace

[![Release](https://img.shields.io/github/v/release/compiwerai/mtrini-workspace)](https://github.com/compiwerai/mtrini-workspace/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![CI](https://github.com/compiwerai/mtrini-workspace/actions/workflows/ci.yml/badge.svg)](https://github.com/compiwerai/mtrini-workspace/actions)

**Your AI. Your code. Your workspace.**

Open-source AI development environment by **Compiwer AI** — *Building AI For Everyone.*

> Build software with local models, Hugging Face models, and configurable cloud/API models — through one model-agnostic agent.

**Docs & blog:** https://compiwerai.github.io/mtrini-workspace (enable Pages on first deploy, see below).

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
- Real tool-using coding agent (inspect → plan → change → test → verify)
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
iscc scripts\setup.iss         # needs Inno Setup 6 -> installer\MtriniWorkspace-Setup-0.6.1.exe
```

Run `MtriniWorkspace.exe` (or install the Setup): it serves the API **and**
the UI from one process and opens `http://127.0.0.1:8787` in your browser.
Silent install: `MtriniWorkspace-Setup-0.6.1.exe /SILENT`.

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

Agent panel (Ctrl+L): natural-language requests, live activity timeline
(planning → inspect → search → read → edit → terminal → tests), permission prompts
(`Allow once / Deny`) for write/execute/network/destructive operations.
Slash commands: `/help /status /clear /git /test /skills /agents /permissions`.
Project memory: `.mtrini/instructions.md`, `.mtrini/skills/*/SKILL.md`, `.mtrini/agents/*.md`.

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
| POST | `/api/chat` (SSE) `/api/agent` (SSE) `/api/tools/execute` `/api/terminal/exec` |

Full reference: `docs/API.md`.

## Privacy

Local models stay local. No telemetry. API requests go only to providers you configure.
Credentials live in the OS keychain (documented file fallback), never in `config.json`, git, logs, or frontend source.
See `PRIVACY.md` and `SECURITY.md`.

## License

Apache-2.0 — see `LICENSE`. Third-party licenses: `docs/THIRD-PARTY.md`.
