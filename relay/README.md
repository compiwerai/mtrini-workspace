# Mtrini free-model relay

A small Cloudflare Worker that gives Mtrini Workspace users a free model with no key:
Qwen3.8 27B on [Heabsy](https://heabsy.com), sponsored by Heabsy.

```
Mtrini Workspace  →  this relay (holds the sponsored key, counts spend)  →  Heabsy API
```

The key never ships inside the app. The relay forwards chat requests, forces the model to
`qwen38`, caps answer length, and keeps spending inside the sponsorship with daily limits:

| Limit | Default | Setting |
|---|---|---|
| Per install, per day | $0.10 | `USER_DAILY_USD` |
| Per IP address, per day | $0.30 | `IP_DAILY_USD` |
| Everyone together, per day | $1.60 (under $50 a month) | `GLOBAL_DAILY_USD` |
| Requests per minute, per install / overall | 10 / 50 (the key allows 60) | `USER_RPM` / `GLOBAL_RPM` |
| Requests running at once, per install / overall | 2 / 8 (the key allows 8) | `USER_CONCURRENCY` / `GLOBAL_CONCURRENCY` |

Days are UTC. Counters (spend per anonymous install id, per hashed IP, and in total) are
deleted when the day changes. Prompts and answers are never stored.

Cost is computed from each response's token usage at Heabsy's list prices
(`PRICE_*_PER_M`). One request can run past a limit before the next one is refused, so
real spend can exceed a limit by about one request.

## Deploy (about 10 minutes)

You need Node.js (already installed) and a free Cloudflare account.

1. **Create the account.** Sign up at https://dash.cloudflare.com/sign-up and confirm your
   email. The free Workers plan is enough. No card is needed.
2. **Open a terminal in this folder:**
   ```
   cd C:\Users\NB\Desktop\Ayham\MTRINI-WORKSPACE\relay
   ```
3. **Log in.** This opens your browser; click **Allow**:
   ```
   npx wrangler login
   ```
4. **Add the Heabsy key as a secret.** Wrangler asks for the value: paste the key and press
   Enter. It's stored encrypted in Cloudflare and never appears in this folder or in Git.
   ```
   npx wrangler secret put HEABSY_KEY
   ```
   Until Konstantin sends the sponsored key, you can use your own trial key (the $20
   credit) to test. Run the same command again with the sponsored key before launch.
5. **Deploy:**
   ```
   npx wrangler deploy
   ```
   The first time, it asks you to choose a `workers.dev` subdomain (for example
   `compiwerai`). At the end it prints the relay's address, like
   `https://mtrini-free.compiwerai.workers.dev`.
6. **Check it:** open `https://mtrini-free.<your-subdomain>.workers.dev/health` in a browser.
   It should show `"configured": true`.
7. **Put the address in the app:** set `FREE_RELAY_URL` in
   `backend/mtrini/providers/free.py` to that address (it's not secret), then build and
   release. Until then the free model stays hidden in the app.

## Change limits or prices

Edit `[vars]` in `wrangler.toml`, then run `npx wrangler deploy` again.
To see live logs: `npx wrangler tail`.

## Test

```
npm test
```
