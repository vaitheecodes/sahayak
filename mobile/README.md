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

## API URL and https

The URL comes only from `EXPO_PUBLIC_API_URL` (`app.config.ts`), never the
source. Plain `http://` is allowed only when `APP_VARIANT` is
`development` (the default). The EAS `preview` profile sets
`APP_VARIANT=preview`, and `app.config.ts` then refuses to load (so the
build fails) unless the URL is `https://`. Set it as an EAS environment
variable for the `preview` environment (EAS dashboard or `eas env:create`).
A release JS bundle also refuses http at runtime.

## Tests

`npm test` (Jest + React Native Testing Library) and `npm run typecheck`.

## Layout

```
app/            routes (Expo Router): sign-in, change-password, offline,
                password (modal), (tabs)/{index=chat, tickets, account}
src/api/        fetch client, ApiError mapping, endpoint helpers, types
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
