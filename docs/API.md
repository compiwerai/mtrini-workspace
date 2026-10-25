# API reference (local backend, default http://localhost:8787)

Health/meta: `GET /api/health`, `GET /api/about`, `GET /api/runtimes`
Providers: `GET /api/providers`, `POST /api/providers/configure {provider, apiKey?, baseUrl?, model?}`,
  `POST /api/providers/disconnect {provider}`, `GET /api/models?provider=…`
Registry: `GET /api/registry`, `POST /api/registry {id, provider, …}`
Endpoint probe: `GET /api/local/endpoint?baseUrl=…`
Hugging Face: `GET /api/hf/whoami`, `GET /api/hf/search?q=`, `GET /api/hf/details?repo=`, `POST /api/hf/download {repo}`
Project: `GET /api/project`, `GET /api/skills/{name}`
Tools: `POST /api/tools/execute {tool, args}` — tool names: list_directory, read_file,
  write_file, edit_file, delete_file, move_file, file_exists, execute_command,
  git_status, git_diff, git_log, git_branch, git_show, search_code, search_filename,
  inspect_project, detect_language, detect_package_manager, run_python
Git: `GET /api/git/status`, `GET /api/git/diff?path=`(+`&cached=true` for staged),
  `POST /api/git/stage {paths[]}`, `POST /api/git/commit {message}`
Threads: `GET/POST /api/threads`, `GET/PATCH/DELETE /api/threads/{id}` (PATCH takes
  `{title?, folder?}` — each thread has its own working folder),
  `POST /api/threads/{id}/messages {role, content}`
Automations: `GET/POST /api/automations`, `DELETE /api/automations/{id}`, `POST /api/automations/{id}/run`
Meta: `GET /api/browse?path=` (server-side folder picker), `POST /api/project/open`
  All `/api/*` accept an optional `workspace` (query or body) selecting the working folder.
MCP: `GET/POST /api/mcp/servers` (`GET` takes `?format=claude|mtrini`), `PATCH/DELETE /api/mcp/servers/{name}`,
  `GET /api/mcp/servers/{name}/tools`, `POST /api/mcp/call {server, tool, args}`,
  `POST /api/mcp/import {config}` (Claude `mcpServers` shape, array, or single object).
  Config is plain JSON in `.mtrini/mcp.json`.
Images: `GET /api/images/support`, `POST /api/images/generate {provider, model, prompt, size}`,
  `GET /api/images`, `GET /api/images/{id}/file`, `DELETE /api/images/{id}`
Chat (SSE): `POST /api/chat {provider, model, messages[], effort?}`
Agent (SSE): `POST /api/agent {provider, model, message, threadId?, permissionMode, effort?, images?[], resume?, history?[]}`
  `threadId` keeps the agent's session (tool calls and results, todos, a paused approval) in
  `.mtrini/sessions/<threadId>.json`; turns are also recorded in the thread file.
  `permissionMode`: ask | auto | readonly | plan. `images`: `[{mime, data}]` (base64, up to 8).
  `effort` is one of off|low|medium|high|xhigh|max (default off): native reasoning on OpenAI
  (`reasoning_effort`), Anthropic (adaptive thinking + `output_config.effort` on current models,
  a thinking budget on older ones), Gemini (`thinkingBudget`), Azure, plus a deeper loop (12→60 steps).
  events: status, turn, assistant_delta, tool_start, tool_result, permission_request, plan, todos,
  mode, compacted, subagent, hooks_untrusted, done, error. Tool events carry the call `id`;
  subagent tool events carry `parent`.
  A turn that needs an answer ends with `done` + `pendingApproval` or `pendingPlan`. Answer it with
  `{threadId, resume: {decision}}`: `allow | always | deny` for tools (`feedback` optional),
  `approve` (with `mode: ask|auto`) or `reject` (with `feedback`) for plans. The same loop continues.
  Legacy one-shot approval without `threadId`: `{approve: {tool, args}}`.
Agent session: `GET /api/agent/session/{threadId}` (todos, mode, pending card, checkpoints),
  `POST /api/agent/rewind {threadId, turn, files?, conversation?}` (restores files changed by file
  tools from that turn on, drops those turns, returns the turn's prompt),
  `POST /api/agent/compact {threadId, provider, model}`
Hooks: `GET /api/hooks` (present, trusted, hooks), `POST /api/hooks/trust`
Permission rules: `GET /api/permissions`, `POST /api/permissions {allow: [...]}`
Web search: `GET /api/websearch`, `POST /api/websearch {provider: brave|tavily|searxng|"", apiKey?, baseUrl?}`
CLI: `mtrini -p "<prompt>" [path] [--provider] [--model] [--mode] [--effort] [--thread] [--json]`
Terminal: `POST /api/terminal/exec {command, cwd?, timeout?}`
