# DESIGN.md: Rate Truth

Status: direction set by Claude on 11 Nov 2026. It uses the method of Intern Radar's DESIGN.md (one unusual object at
the centre, a timetable layout, neutral greys, one hue with one meaning, behaviour counts as design, contrast
tested in code). It deliberately does **not** reuse Intern Radar's fonts or signal colour, so the two sites read
as siblings by quality, not as copies.

## What it is
An MCP gateway between a Dubai hotel supplier and Google Hotels. The site is how a person *sees* it work. There
are two audiences:
- **A recruiter or engineer from TPConnects** following the CV link. In 30 seconds they want to see:
  - an agent answering a real stay request through MCP tools;
  - every price on screen traced to the rate engine;
  - the Google-side machinery (feeds, schema validation, price accuracy) actually running.
- **An MCP developer** who wants the endpoint, the tool list and a one-line `claude mcp add`.

## The one unusual object: the folio
A hotel bill, itemised. Every price on the site is a folio, never a bare number:

```
Rove Downtown · 2 nights · 14–16 Nov · Standard King · Refundable
  Room rate            2 × AED 412.00        AED 824.00   rate_engine/base
  Service charge 10%                          AED  82.40   tax/dxb-service-2019   ↗ source
  Municipality fee 7%                         AED  57.68   tax/dxb-municipality   ↗ source
  VAT 5%                                      AED  48.20   tax/uae-vat-2018       ↗ source
  Tourism Dirham       2 × AED 10             AED  20.00   tax/dxb-tdirham-3star  ↗ source
  ------------------------------------------------------------------------------
  All-in                                     AED 1,032.28
  rate_id 7f3a…c2 · computed 11 Nov 21:04:12 GST · synthetic rate on a real hotel (OSM 123456)
```
(The numbers above are illustrative; the real ones come from the engine.)

Prices in an agent answer are **folio chips**: the amount, underlined. Opening a chip unfolds that folio in
place. A price that cannot be traced is never shown as a chip. It shows struck through, with "not traced to a
tool result", and the grounded check fails visibly.

The second object is the **diff**. On the accuracy page a sample is two folios side by side, feed against landing
page, with the differing lines marked and the reason code (Google's wording) beside them.

## Pages
1. **`/` Desk.** Chat on the left, live **trace** on the right; on a phone the trace sits under the answer as a
   collapsible block.
   - The trace is the timetable: a mono column with elapsed ms, then the tool name, the arguments (compact JSON,
     with keys in ink-3) and the result summary.
   - Each `rate_id` in the trace links to its folio.
   - The answer ends with the grounded check: "3 of 3 prices traced to rate_id …".
   - Suggested asks sit under the input as plain text buttons, not pills.
   - There is a visible offline-replay label when no LLM key or quota is available.
2. **`/hotels`.** The real hotel list as rows (no cards).
   - Each row shows the name, area, stars (OSM tag, or "estimated" in ink-3), metro and beach distance in metres,
     and "from AED x all-in tonight".
   - Filters live in the URL.
   - An open row shows the content card (every fact with its OSM source), the folio for tonight, and the
     availability strip for the next 30 nights.
3. **`/accuracy`.** The headline is the score as a number, with its definition one click away (ours, inspired by
   Google's description).
   - A 30-sample strip of match/mismatch bars, Intern Radar's daily strip reused as a pattern.
   - A sample table with the reason codes.
   - A **fault bench**: pick a fault, run the audit, watch the score drop and the classifier name the cause.
     Reset restores the clean state. Faults are per-visitor and never persisted.
4. **`/feeds`.** Each generated feed (Hotel List, Property Data, Transaction/ARI) shows the schema URL, the XSD
   fetch date, the validation result with error lines if any, its size, and a download.
5. **`/taxes`.** The effective-dated Dubai stack as a timeline (2026 relief included). Every row carries its
   source link, the access date and its confidence. Each rule has a "price this stay under that rule" control.
6. **`/method`.** The eval tables (from `results.json`), the limits stated plainly, OSM attribution, and Connect
   (endpoint, tool list, copyable `claude mcp add` and Claude Desktop config).

## Type (self-hosted via @fontsource-variable, none of them a framework default)
- **Schibsted Grotesk** for headings and hotel names: a newspaper grotesk, firm at 20–40 px.
- **Public Sans** for body and facts: plain and very legible.
- **Martian Mono** for every amount, rate_id, time and tool name. A folio is tabular by nature, and its width
  axis lets amounts sit tight in the folio and wider in the score headline.

Scale (px): 12 mono labels · 14 facts · 16 body · 20 hotel name · 28 and 40 headings · 56 score headline.
Numbers are tabular everywhere; amounts right-aligned on the decimal.

## Colour
Neutral greys in both themes, with no tint. One hue, used only for **mismatch / untraced / failed**. A match is
not green: it is ink with a ✓ glyph, so the page reads in greyscale and for colour-blind readers.

| Role | Light | Dark | Used for |
|---|---|---|---|
| page | `#f7f7f7` | `#101010` | ground |
| surface | `#ffffff` | `#181818` | folio, open row, inputs |
| wash | `#efefef` | `#212121` | hover, trace rows, code |
| rule | `#e0e0e0` | `#2b2b2b` | row lines, folio rules |
| rule-2 | `#c4c4c4` | `#454545` | input borders, folio total rule |
| ink | `#121212` | `#eeeeee` | text, amounts |
| ink-2 | `#454545` | `#bcbcbc` | secondary |
| ink-3 | `#696969` | `#939393` | labels, rule ids, ms |
| alarm | `#b42318` | `#ff7a6b` | mismatch, untraced price, XSD error, injected fault |
| alarm-wash | `#fdecea` | `#2f1614` | background of a mismatched folio line |

Contrast for every pair is computed and tested (4.5:1 text, 3:1 for meaningful borders and glyphs). Light theme
is the default ([[project-light-mode-default]]); there is a toggle.

## Layout
- One column, 1160 px at most, 16 px side gutters on a phone (20 from 720 px).
- Rows separated by single rules. No cards, no shadows except on a popover, radius 4 px on controls only.
- The folio is a ruled block with a heavier rule above the total and amounts in a right-aligned mono column.
  On a phone the rule-id column drops under the label.
- Desk: a 7/5 split from 1024 px; stacked below that.

## Motion
Only where it carries information:
- each trace row appears as its tool call returns;
- a folio unfolds in 160 ms;
- the score number counts to its new value once after a fault-bench run.

`prefers-reduced-motion` turns all of it off.

## Behaviour that counts as design
- Streaming trace: the visitor sees the MCP calls happen in order, with real timings.
- Every amount is a folio or it is flagged. There are no bare prices anywhere on the site.
- URL state for filters, the selected sample and the open folio, so any view can be shared.
- Keyboard: `/` focuses the ask box, `j`/`k` move between rows, `Enter` opens, `Esc` closes.
- Rate-limited politely: the message says when the visitor can ask again, and replay still works.

## Voice
Plain and exact. "All-in AED 1,032.28 for 2 nights", "not traced to a tool result", "synthetic rate on a real
hotel". No "discover", no "seamless", no exclamation marks. The site never says "integrated with Google"; it says
"built to Google's published formats".
