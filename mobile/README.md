# Sahayak mobile (customer app)

React Native + Expo (SDK 58), TypeScript, Expo Router. Android first; the
same code builds for iOS. Customers only: staff and admins use the web
portal, and the app turns their accounts away at sign-in.

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
- Not yet: attachments (Stage 4), push notifications.
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
