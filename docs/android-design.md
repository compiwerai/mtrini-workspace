# Mtrini Workspace for Android, and Mtrini accounts: design

Status: agreed (30 Oct 2026); see Decisions at the end. Nothing here is built yet.

## What we want

1. **One account on every device.** Sign in with Google, Discord or GitHub on the PC and the phone.
2. **The phone controls your PC** when the PC is on: see your sessions, send tasks, approve steps, read diffs,
   watch the agent work, all on your own projects and files.
3. **The phone still works when the PC is off:** chat with the agent, read and continue your sessions, and
   work on (and test) code that lives on GitHub.
4. **Mtrini stays local-first.** Accounts are optional. Without signing in, the desktop app works exactly as
   it does today.

## The pieces

```
 Phone (Android app)  ──┐                       ┌──  PC (Mtrini Workspace desktop)
                        │   Mtrini Cloud        │     connects out when "Remote access" is on;
                        ├── sign-in, sync,  ────┤     no open ports, works behind any router
                        │   live bridge         │
                        └──────────┬────────────┘
                                   │
            Free model relay (exists) · your providers · GitHub (repos, Actions)
```

### Mtrini Cloud (new)
Runs on the Cloudflare account we already use for the free-model relay, inside its free plan:

- **Sign-in:** OAuth 2.0 with Google, Discord and GitHub (authorization code + PKCE). Mtrini only asks for
  your name, email and avatar; GitHub additionally asks for repository access only if you connect a repo.
  Mtrini issues its own short-lived session tokens; you can see and sign out devices in Settings.
- **Accounts and devices:** a small SQLite database (Cloudflare D1): account, linked sign-ins, devices.
- **Sync:** session titles, messages and to-do lists, so the phone can read and continue them when the PC
  is off. **End-to-end encrypted:** each account has a key that only your devices hold (shared by scanning
  a QR code when you add a device), so Mtrini Cloud stores data it cannot read. Files from your projects are
  never uploaded.
- **Live bridge:** when the PC is on and "Remote access" is enabled, the desktop app keeps one outbound
  connection to Mtrini Cloud (a Cloudflare Durable Object). The phone talks to the PC through it. The bridge
  forwards encrypted messages; it does not run anything.

### Desktop app changes
- Settings → Account: sign in / out, list of devices, "Remote access" switch (off by default).
- A new device must be approved on the PC once (a 6-digit code shown on both screens).
- Everything a phone asks for goes through the same permission rules as typing on the PC: approval cards
  appear on the phone, destructive steps always ask, and "Auto" mode can't be switched on from the phone
  unless you allow that on the PC.

### Android app
- **Built from the existing interface** with Capacitor (the same React code as the desktop app, packaged as a
  real Android app), with phone layouts for the session view, approvals and diffs. This reuses most of what
  exists and keeps both apps in step.
- **PC on:** pick a project on the PC, chat, approve, see diffs and test output, live.
- **PC off:**
  - Chat with the free model (Heabsy-sponsored relay) or your own provider keys, which are stored in
    Android's secure keystore on the phone, never synced.
  - Read and continue synced sessions. When the PC comes back, they're there.
  - **GitHub projects:** connect a repository; the agent reads and edits it through the GitHub API on a
    branch, and **tests run on GitHub Actions** (free for public repos, 2,000 minutes a month for private
    ones). You review the diff and open a pull request from the phone.
- Push notifications when the agent needs an approval or finishes (Firebase Cloud Messaging, free).

## Security and privacy

- Remote access lets a phone run commands on your PC, so it is off by default, needs a signed-in account,
  a one-time device approval on the PC, and every risky step still needs approval. Any device can be revoked
  instantly from either side.
- Synced sessions are end-to-end encrypted; losing every device means losing synced history (the PC's local
  copy stays). Provider keys never leave the device they were entered on.
- PRIVACY.md gets an "Accounts" section before launch; signing in stays optional.

## What it costs

| Item | Cost |
|---|---|
| Cloudflare Workers, D1, Durable Objects | free plan (we're far below its limits) |
| Firebase Cloud Messaging | free |
| Google Play developer account | $25 once (or ship the APK on GitHub first, free) |
| A domain (recommended for the sign-in screens and privacy policy) | about $10 a year |

Registering the OAuth apps (Google Cloud Console, Discord Developer Portal, GitHub) is free and has to be done
by you, under the company's accounts.

## Phases

1. **Accounts:** Mtrini Cloud sign-in (Google, Discord, GitHub), Settings → Account on desktop. About 1 week.
2. **Phone controls the PC:** Android app (Capacitor), live bridge, device approval, approvals and diffs on the
   phone, notifications. About 2 weeks. First release as an APK on GitHub.
3. **PC-off mode:** encrypted sync, free model and own keys on the phone, GitHub repos with Actions tests.
   About 2 weeks.
4. **Google Play** listing.

## Decisions (30 Oct 2026)

1. Sign-in: **Google, Discord and GitHub.** Google is postponed until Mtrini has its own domain (its
   consent screen wants one); Discord and GitHub go first. Adding Google later is configuration only.
2. PC-off testing: **GitHub repos, tests on GitHub Actions.**
3. Sync: **end-to-end encrypted.**
4. First release: **APK on GitHub**, Google Play later.
