# Privacy

Mtrini Workspace is local-first:

- Local models, agent, filesystem, terminal, Git, skills, editor, and settings work offline.
- Internet is needed only for model downloads, Hugging Face, cloud APIs, and updates.
- **Update checks.** The installed app asks GitHub (api.github.com) for the latest release a
  few times a day and downloads it from there. It sends nothing but a normal web request with the
  app's version in the user agent. Turn automatic updates off in Settings → About.
- **No telemetry.** No analytics, no tracking, no mandatory cloud.
- Local inference traffic stays on your machine / LAN endpoint.
- Cloud API traffic goes only to the provider you selected and configured.
- **Web search.** When the agent or a bot searches the web and you have not set a search service, the query goes
  to DuckDuckGo (html.duckduckgo.com), or to a Bing results page opened in the agent's own browser if that gives
  nothing. Set Brave, Tavily or your own SearXNG in Settings -> Web search and queries go only there.
- **Mtrini Bots.** A bot's files, memory, conversation and inbox stay in `~/.mtrini/bots/` on your computer. Its
  browser uses its own profile, separate from yours. If you connect Telegram, messages you exchange with your bots
  pass through Telegram's servers; the bot token is kept in the OS keychain.
- Requests to OpenRouter name the app ("Mtrini Workspace" and its GitHub URL) so it
  appears in OpenRouter's public app rankings. Nothing about you or your code is added.
- **The free built-in model** (Qwen3.8 27B, sponsored by Heabsy) sends your requests through
  Compiwer's relay to Heabsy's EU-hosted API. To apply daily limits, the app adds an anonymous
  install id (a random number stored in `~/.mtrini/install-id`), and the relay keeps a hash of your
  IP address and your spend for the current UTC day; those counters are deleted when the day ends.
  The relay does not store prompts or answers. Heabsy's own terms apply to what it receives.
  Pick any other provider and nothing goes through the relay.
- **Compiwer Free** (Grok 4.7) works the same way through a second Compiwer relay, which
  forwards your requests to [100miliongrok](https://100miliongrok.top), a free OpenAI-compatible
  service not affiliated with xAI. The same anonymous install id, hashed IP and daily counters
  apply. 100miliongrok's own terms apply to what it receives.
- **Compiwer Free · DeepSeek** (DeepSeek V4.1 Flash) uses a third relay with the same handling;
  it forwards to [100milionseek](https://100milionseek.top), a free OpenAI-compatible service not
  affiliated with DeepSeek. The same install id, hashed IP and daily counters apply, and
  100milionseek's own terms apply to what it receives.
- **Mtrini accounts are optional.** If you sign in (Settings → Account) with Discord or
  GitHub, Mtrini Cloud stores your name, email, picture, which sign-ins you linked, and a list of your
  signed-in devices with their names and last-seen times. It receives nothing from your projects.
  Sessions are stored only as hashes. You can sign devices out, unlink sign-ins, or delete the
  account (which removes all of this) from Settings → Account.
- Credentials are stored in the OS keychain (or a 0600 local file fallback) and never
  committed, logged, or shipped to any other party.
- Deleting `.mtrini/secrets.json` + keychain entries removes all stored credentials.
