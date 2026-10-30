# Mtrini Cloud

Optional Mtrini accounts: sign in with Google, Discord or GitHub. Later it also carries end-to-end
encrypted sync and the phone-to-PC bridge (see `docs/android-design.md`). Runs on Cloudflare Workers
with a D1 database, on the free plan.

How sign-in works: the app asks for a one-time sign-in link, opens it in the browser, and polls until
the person has signed in with their provider. Session tokens are stored only as SHA-256 hashes, and a
token is created only when the app that started the sign-in collects it. A new sign-in is a new
account; other sign-ins are linked from Settings → Account, never matched by email.

## Set up (about 20 minutes)

The address below assumes the Worker runs at
`https://mtrini-cloud.roblox-event-bot-worker.workers.dev` (your account's workers.dev name). If you
change it, use the new address everywhere below and in `wrangler.toml`.

### 1. Database and Worker
Run in this folder:
```
npx wrangler d1 create mtrini-cloud
```
Copy the `database_id` it prints into `wrangler.toml`, then:
```
npx wrangler d1 migrations apply mtrini-cloud --remote
npx wrangler deploy
```
Open `https://mtrini-cloud.roblox-event-bot-worker.workers.dev/health`; it shows `"providers": []`
until step 3.

### 2. Register the three sign-in apps
Use the company account (contact.compiwerai@gmail.com) for each. All free.

**Google**
1. Open https://console.cloud.google.com, create a project called **Mtrini**.
2. **APIs & Services → OAuth consent screen**: User type **External**. App name **Mtrini**, support email
   and developer email **contact.compiwerai@gmail.com**, app logo optional, homepage
   `https://compiwerai.vercel.app`, privacy policy `https://github.com/compiwerai/mtrini-workspace/blob/main/PRIVACY.md`.
   Scopes: add `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (all non-sensitive, no review needed).
   Then **Publish app** (otherwise only test users can sign in).
3. **Credentials → Create credentials → OAuth client ID**, type **Web application**, name **Mtrini Cloud**.
   Authorized redirect URI: `https://mtrini-cloud.roblox-event-bot-worker.workers.dev/auth/google/callback`
4. Keep the **Client ID** and **Client secret** for step 3.

**Discord**
1. Open https://discord.com/developers/applications → **New Application** → name **Mtrini**.
2. **OAuth2** → **Redirects** → add `https://mtrini-cloud.roblox-event-bot-worker.workers.dev/auth/discord/callback` → Save.
3. Copy the **Client ID**; click **Reset Secret** and copy the **Client Secret**.

**GitHub** (best under the compiwerai organization)
1. Open https://github.com/organizations/compiwerai/settings/applications (or your own
   Settings → Developer settings → OAuth Apps) → **New OAuth App**.
2. Name **Mtrini**, homepage `https://compiwerai.vercel.app`, callback URL
   `https://mtrini-cloud.roblox-event-bot-worker.workers.dev/auth/github/callback`. Leave device flow off.
3. Copy the **Client ID**; **Generate a new client secret** and copy it.

### 3. Store the IDs and secrets on Cloudflare
Run each line and paste the value when asked (they're stored encrypted on Cloudflare, never in this folder):
```
npx wrangler secret put GOOGLE_CLIENT_ID
npx wrangler secret put GOOGLE_CLIENT_SECRET
npx wrangler secret put DISCORD_CLIENT_ID
npx wrangler secret put DISCORD_CLIENT_SECRET
npx wrangler secret put GITHUB_CLIENT_ID
npx wrangler secret put GITHUB_CLIENT_SECRET
```
`/health` should now list `["google", "discord", "github"]`.

### 4. Turn accounts on in the app
Set `CLOUD_URL` in `backend/mtrini/account.py` to the Worker's address, then build and release.

Current setup (30 Oct 2026): live at `https://mtrini-cloud.roblox-event-bot-worker.workers.dev` with
Discord and GitHub. Google waits for a domain of our own (its consent screen asks for one).

## Test
```
npm test        # Node 22.5 or newer (uses node:sqlite as a stand-in for D1)
```
