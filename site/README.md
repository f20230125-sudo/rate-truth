# Rate Truth front end

Next.js 16.4.6, React, Zod, self-hosted Schibsted Grotesk, Public Sans and Martian Mono. The UI reads the Python API through same-origin rewrites. No fixture is used as production data.

Run `npm.cmd run dev` (port 3170) with the Python API on `http://127.0.0.1:8170`. Set `RT_API_URL` **before building** to use a different API origin. `/api/*` and `/mcp` are proxied; browser CSP keeps `connect-src 'self'`.

Checks:

```powershell
npm.cmd run lint
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
$env:PLAYWRIGHT_BROWSERS_PATH='..\.local\pw'
npx.cmd playwright install chromium
npm.cmd run e2e
```

The e2e command starts the production build on 3171 and closes its owned process afterward. Build first. Both desktop and Pixel 7 projects intercept API calls with `page.route()` and fixtures; no Python service is required. `BASE_URL` targets an existing server instead. The runner launches Next directly to avoid Windows `taskkill /T` in restricted environments.

All room prices must carry the current tool trace’s rate ID and match an attached folio. Untraced answer amounts are struck through and fail the grounding line, including amounts absent from the declared price list. Tax-rule values and accuracy thresholds are not stay offers; their Money components identify the relevant rule or definition as evidence. Holds are explicit, mock-only, and never sent by a stream event alone.

The eval contract specifies only `run_at` and otherwise leaves `results.json` open. The schema validates JSON values and a nullable run timestamp; the UI builds tables from the fields actually reported without asserting invented metric names.

© OpenStreetMap contributors, ODbL. Real hotel facts are supplied by the API. Rates and availability are synthetic. Feeds are built to Google’s published formats; Google endpoints are never called.
