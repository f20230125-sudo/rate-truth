# Integration patterns

External assistants connect to the stateless HTTP endpoint or launch stdio, as
shown in the [README](../README.md) and [tool reference](tools.md). The gateway
returns the same structured contracts on both transports. MCP clients should use
the SDK protocol negotiation rather than hand-written legacy JSON-RPC headers.

## Shopping and confirmation

Search or retrieve sourced hotel cards, then request rates for the exact stay.
Compare folios for the same dates, guests, room and plan. Display the all-in total,
rate ID, computation time, synthetic disclosure and charge sources. Observed
market prices remain separately labelled and must not become supplier offers.

The application agent never calls `hold_offer`. It obtains an offer capability
from `get_rates`, emits a UI `hold_request`, and waits for the traveller's Confirm
button. The browser posts the exact rate ID and capability with `confirm=true` to
`/api/holds`. Typed conversational confirmation is insufficient. External MCP
clients must likewise collect explicit UI confirmation before invoking the hold
tool. A hold is a signed mock receipt, expires, and never books a room.

## Distribution operations

Generate Hotel List/Property Data or itinerary/ARI messages, then pass the exact
XML and format kind to `validate_feed`. Published cached XSDs validate Hotel List,
Property Data and Transaction XML; ARI checks are labelled structural. An audit
compares prices parsed from serialized feeds with the supplier's `/quote` response.
Use the same seed, sample count and faults when requesting `explain_mismatch` for
an audit sample. Neither validation nor an audit submits anything to Google.

## Hosting

The Next.js project and Python ASGI API can be hosted separately. Set `RT_API_URL`
before building the site; its same-origin rewrites keep browser API traffic on
the site's origin. Configure the API's exact `RATE_TRUTH_ORIGIN` and allowed hosts.
The [Dockerfile](../Dockerfile) runs only the API, on port 8000 as a non-root user.
It includes local OSM, tax rules, feed schemas and evaluation results; credentials
are runtime environment variables and are excluded from the build context.

Use a shared `RATE_TRUTH_SECRET` to verify offer capabilities across workers.
Inventory, consumed-token state, rate limiting and SQLite budgets remain local to
an instance. Durable global reservations or distributed quota coordination require
additional infrastructure; this demo does not claim those properties.
