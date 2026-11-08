# Backend wishlist (from the mobile app)

API gaps the mobile app works around today. Nothing here has been changed
in the backend; each item says what the app does meanwhile.

## Safety of retries

1. **Idempotency key for `POST /api/tickets`.** A timed-out create can't be
   retried safely, because the ticket may already exist. Accept an
   `Idempotency-Key` header and return the first result for a repeat.
   *Now:* on a timeout the app tells the customer to check Tickets before
   trying again, and never retries by itself.
2. **The same for chat turns: `POST /api/chats` and
   `POST /api/chats/{id}/messages`.** A timed-out turn may already be
   stored, so a resend would post the message twice and start a second AI
   turn. *Now:* on a timeout the app reloads the chat, warns that the
   message may have gone through, and only gives the text back to the
   composer for a failure that definitely didn't send it.

## Fewer round trips

3. **`POST /api/tickets/{id}/reply` should return the updated thread**
   (the same body as `GET /api/tickets/{id}`), as the chat endpoints
   already return the whole session. *Now:* a second GET after every reply.
4. **A changed-since filter on `GET /api/tickets/mine` and
   `GET /api/chats`** (`?updated_since=<ISO time>`), plus paging
   (`limit` / `cursor`). *Now:* the whole list is fetched every time a tab
   comes into view.
5. **Server-side search on `GET /api/tickets/mine`.** *Now:* the app
   filters the loaded list on the phone.
6. **Mark-read as its own call** (`POST /api/tickets/{id}/read`). *Now:*
   `GET /api/tickets/{id}` always marks the ticket read, so even a
   pull-to-refresh does.

## Chat

7. **Fixed choices on AI questions.** The how-to and clarify questions
   that list options ("which part of the product: A, B or C?",
   "I have a guide for each of these: …") come back as plain sentences in
   `messages[].content`. Add an optional `choices: string[]` to AI chat
   messages (built from the same confirmed terms the sentence is made
   from) so the app can show tappable options. *Now:* plain text; the
   customer types the answer.
8. **A typing / progress signal for long AI turns** (or a streamed
   reply). *Now:* the app shows a typing indicator for the whole request,
   up to its 120 s timeout.
9. **No unread state for chats.** An escalated chat's replies arrive on its
   ticket, which has the unread dot, so this is minor.

## Push and localisation

10. **Device-token endpoint for push**
    (`POST /api/devices {token, platform}` and `DELETE` on sign-out), and a
    push on a staff reply or status change. *Now:* no push; lists refresh
    on focus and pull-to-refresh.
11. **Localisable server messages.** `detail` strings, the AI-unavailable
    message, chat system replies ("I've passed this to our support team as
    ticket …") and the follow-up questions are English only. A stable
    `code` next to each `detail` (e.g. `chat_not_active`,
    `ai_unavailable`) would let the app translate them for Tamil and Hindi.

## Account (carried over from Stage 1)

12. **Forgot password / self-service reset.** *Now:* the customer asks the
    admin.
13. **Refresh tokens.** *Now:* when the JWT expires the customer signs in
    again.
14. **An explicit customer "close ticket" action.** *Now:* a ticket closes
    only through the AI's closing-acknowledgment path or staff.

## Attachments

15. **Staff can't attach files to a reply.** `POST /api/tickets/{id}/attachments`
    is customer-only and there is no staff equivalent, so a technician can't
    send a customer a file (a corrected document, a screenshot of the fix).
    The app already downloads and opens any attachment on any visible
    message. *Now:* tested by adding one to a staff reply directly in the
    local test database.
16. **Upload together with the message, or an idempotency key on upload.**
    Files go up in a second request after the ticket or reply exists. If
    that request times out, the files may or may not have arrived, and a
    blind retry could attach them twice (until the 5-per-message cap).
    *Now:* a refused or failed upload can be retried (the server checks all
    files before storing any, so nothing is half-saved); after a timeout the
    app says to check the ticket and offers no retry.
17. **Return a clear upload error code.** The 400 `detail` strings ("x
    doesn't look like a PDF file") are English and parsed by eye only; a
    `code` plus the offending filename would let the app mark the right
    file and translate the message.
