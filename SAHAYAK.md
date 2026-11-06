# Sahayak

AI help desk: ticketing + KB ingester + mobile app, for any product.
Started as a copy of ticketapp-ai-aws @ b77e159 (tracked files only, no .env or local data).

backend/, frontend/  - the help desk; product-neutral, starts with an empty KB (CLAUDE.md, README.md)
kb_ingester/         - builds the knowledge base from links, docs and forums (generic, any product)
mobile/              - React Native (Expo) app, Android first
