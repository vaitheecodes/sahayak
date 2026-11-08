# Sahayak mobile (customer app)

React Native + Expo (SDK 58), TypeScript, Expo Router. Android first; the
same code builds for iOS. Customers only: staff and admins use the web
portal, and the app turns their accounts away at sign-in.

## Run on the Android emulator (no LAN needed)

Everything runs on this Mac: the emulator (window on screen) runs Expo Go,
which loads the app from Metro on port 8081 and talks to the backend on
port 8000. `adb reverse` maps both ports into the emulator, so the app uses
`http://127.0.0.1:8000` and no Wi-Fi or firewall is involved.

The backend runs from a **pinned worktree**, `../../sahayak-pin` (next to
the `sahayak/` folder): a detached checkout of one commit, so uncommitted
backend work in the main checkout can't break the test server. Its Python
venv (`.venv/`) and test data (`.devdata/`) live inside the pin and are
not tracked by git.

**Test logins** (customer `asha`, a fresh customer `ravi` who must change
their password, and a staff account that the app must turn away):

```bash
cat ../../sahayak-pin/.devdata/test-accounts.txt
```

### Start and stop (from `mobile/`)

```bash
scripts/devstack.sh start
```

This starts the emulator `Medium_Phone_API_36.1` with a visible window,
waits for it to boot, reverses ports 8000 and 8081, then starts the
backend from the pin (mock AI, database `../../sahayak-pin/.devdata/ticketapp.db`).
It also starts Metro and opens the app in Expo Go, installing Expo Go
from Expo's APK cache if it's missing. Each step is skipped if it's
already running.

```bash
scripts/devstack.sh stop
```

```bash
scripts/devstack.sh status
```

```bash
scripts/devstack.sh open
```

`open` reopens the app in Expo Go, e.g. after a crash. Logs and pid files
are in `mobile/.devstack/` (`backend.log`, `metro.log`, `emulator.log`).
Expo Go's developer menu opens with Cmd+M in the emulator window.

The same steps by hand, if the script isn't wanted:

```bash
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_36.1 -camera-back virtualscene -camera-front emulated &
```

```bash
~/Library/Android/sdk/platform-tools/adb wait-for-device && ~/Library/Android/sdk/platform-tools/adb reverse tcp:8000 tcp:8000 && ~/Library/Android/sdk/platform-tools/adb reverse tcp:8081 tcp:8081
```

```bash
cd ../../sahayak-pin && AI_PROVIDER=mock APP_ENV=development DB_PATH="$PWD/.devdata/ticketapp.db" .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

```bash
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000 npx expo start --localhost --port 8081
```

```bash
~/Library/Android/sdk/platform-tools/adb shell am start -a android.intent.action.VIEW -d exp://127.0.0.1:8081 host.exp.exponent
```

Stop the backend and Metro with Ctrl+C in their terminals, and the emulator
with `adb emu kill`.

### The pinned worktree

Create it (once, from the `sahayak/` repo root; `c7cb29c` is the pinned
commit), then give it a venv and a data folder:

```bash
git worktree add --detach ../sahayak-pin c7cb29c
```

```bash
cd ../sahayak-pin && python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt && mkdir -p .devdata
```

With an empty `.devdata/`, the backend creates a fresh database on first
start. Create customers in the web admin, or copy a database file in.

Move it to a newer commit (stop the backend first; `.venv/` and
`.devdata/` are untracked and stay):

```bash
git -C ../sahayak-pin checkout --detach <commit>
```

```bash
../sahayak-pin/.venv/bin/pip install -r ../sahayak-pin/requirements.txt
```

Remove it. This deletes its venv and test data too; `--force` is needed
because of those untracked folders:

```bash
git worktree remove --force ../sahayak-pin
```

## Run on a phone (Expo Go)

1. Start the backend from the repo root so the phone can reach it on your
   LAN: `uvicorn backend.main:app --host 0.0.0.0 --port 8000`.
2. `cp .env.example .env.local` and set `EXPO_PUBLIC_API_URL` to
   `http://<your computer's LAN IP>:8000`.
3. `npm install`, then `npx expo start` and scan the QR code with Expo Go
   (phone on the same Wi-Fi).

Accounts are created by the admin (web portal, Users). The first sign-in
asks for a new password.

## What's in the app

- Sign in (customers only), forced password change, session restore and
  expiry, Account tab (theme, change password, sign out).
- Tickets: list with All / Open / Resolved / Escalated filters, search,
  unread dot and pull-to-refresh (reloads whenever the tab comes back into
  view); email-style thread with incident notice, chat transcript, reply
  (4000 characters) and Reopen; new ticket (subject, category from
  `/api/meta`, priority, description up to 8000 characters). Long threads
  collapse their middle but always keep the newest staff reply open.
- Chat: start a chat (issue up to 500 characters, optional category) and
  see past chats; the conversation with a typing indicator while the bot
  answers, a 4000-character composer, "My issue is solved" and "Raise a
  ticket" (subject confirmed first). Resolved and escalated chats are
  read-only, with a link to the ticket. A timed-out message is never
  resent: the chat reloads and says it may have gone through.
- Attachments: up to 5 files of 10 MB on a new ticket or a reply, from the
  camera, photos or files (PNG, JPG, PDF, TXT, LOG; anything else is refused
  with a reason). Photos still in HEIC are converted to JPEG. Files go up
  after the ticket or reply is created; if the upload fails the ticket or
  reply stays and only the upload is retried. Tapping an attachment
  downloads it with the session's token and opens it (Android: a viewer
  app; iOS: the share sheet).
- Not yet: push notifications.
- API gaps the app works around: `BACKEND_WISHLIST.md`.

## API URL and https

The URL comes only from `EXPO_PUBLIC_API_URL` (`app.config.ts`), never the
source. Plain `http://` is allowed only when `APP_VARIANT` is
`development` (the default). The EAS `preview` profile sets
`APP_VARIANT=preview`, and `app.config.ts` then refuses to load (so the
build fails) unless the URL is `https://`. Set it as an EAS environment
variable for the `preview` environment (EAS dashboard or `eas env:create`).
A release JS bundle also refuses http at runtime.

## Tests

`npm test` (Jest + React Native Testing Library), `npm run typecheck` and
`npm run lint`.

## Layout

```
app/            routes (Expo Router): sign-in, change-password, offline,
                password (modal), (tabs)/{index=chat, tickets, account},
                tickets/[id] (thread), tickets/new (modal), chats/[id]
src/api/        fetch client, ApiError mapping, endpoint helpers (auth,
                tickets, meta, chats), types
src/auth/       SessionProvider (token in expo-secure-store), tokenStore
src/features/   screens by area
src/i18n/       i18next setup + locales/en.json (add ta.json / hi.json later)
src/lib/        error messages, 429 countdown hook, prefs
src/theme/      colour tokens (shared with the web app), ThemeProvider
src/ui/         shared components
__tests__/      Jest tests; test/ has the fake fetch and render helpers
```

## Android APK (internal)

`eas.json` has a `preview` profile that builds an APK for internal
distribution. Building runs on EAS (cloud); it is not run from here.
