---
description: All files, data, and processing must stay local — no external connections, CDNs, or remote services
globs: ["**/*.py", "**/*.js", "**/*.html", "**/*.css"]
---

# Local-Only Rule

## Everything Runs Locally — No External Connections

1. **No CDNs or remote assets** — All CSS, JS, fonts, and images must be served from local files. Never use `<link>` or `<script>` tags pointing to external URLs.

2. **No external API calls** — The frontend talks ONLY to the local Python backend (`localhost`). No third-party APIs, no analytics, no telemetry.

3. **No remote fonts** — If using custom fonts (Inter, JetBrains Mono), bundle them as local files in `/static/fonts/`. Never load from Google Fonts or any CDN.

4. **No external libraries via URL** — All dependencies must be installed locally (pip, npm) or vendored into the project. No `<script src="https://...">`.

5. **CSV data stays on disk** — Uploaded CSV files are read and processed locally by the Python backend. Data is never sent to any external service.

6. **No WebSocket/SSE to external servers** — If WebSockets are used, they connect only to the local backend.

7. **No tracking or analytics** — No Google Analytics, no Sentry, no external error reporting. All logging is local (console or file).

## How to Check

Before adding any dependency or asset:
- Does it require a network connection to load? → **Reject it. Find a local alternative.**
- Does it phone home or send data externally? → **Reject it.**
- Can it work fully offline? → **Good. Use it.**
