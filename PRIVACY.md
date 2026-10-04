# Privacy

Mtrini Workspace is local-first:

- Local models, agent, filesystem, terminal, Git, skills, editor, and settings work offline.
- Internet is needed only for model downloads, Hugging Face, cloud APIs, and updates.
- **No telemetry.** No analytics, no tracking, no mandatory cloud.
- Local inference traffic stays on your machine / LAN endpoint.
- Cloud API traffic goes only to the provider you selected and configured.
- Credentials are stored in the OS keychain (or a 0600 local file fallback) and never
  committed, logged, or shipped to any other party.
- Deleting `.mtrini/secrets.json` + keychain entries removes all stored credentials.
