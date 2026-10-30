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
- Requests to OpenRouter name the app ("Mtrini Workspace" and its GitHub URL) so it
  appears in OpenRouter's public app rankings. Nothing about you or your code is added.
- **The free built-in model** (Qwen3.8 27B, sponsored by Heabsy) sends your requests through
  Compiwer's relay to Heabsy's EU-hosted API. To apply daily limits, the app adds an anonymous
  install id (a random number stored in `~/.mtrini/install-id`), and the relay keeps a hash of your
  IP address and your spend for the current UTC day; those counters are deleted when the day ends.
  The relay does not store prompts or answers. Heabsy's own terms apply to what it receives.
  Pick any other provider and nothing goes through the relay.
- **Mtrini accounts are optional.** If you sign in (Settings → Account) with Discord or
  GitHub, Mtrini Cloud stores your name, email, picture, which sign-ins you linked, and a list of your
  signed-in devices with their names and last-seen times. It receives nothing from your projects.
  Sessions are stored only as hashes. You can sign devices out, unlink sign-ins, or delete the
  account (which removes all of this) from Settings → Account.
- Credentials are stored in the OS keychain (or a 0600 local file fallback) and never
  committed, logged, or shipped to any other party.
- Deleting `.mtrini/secrets.json` + keychain entries removes all stored credentials.
