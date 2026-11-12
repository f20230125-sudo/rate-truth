import { readFileSync } from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
const readFixture = (name: string) => readFileSync(path.join(process.cwd(), "tests/fixtures", name), "utf8");
const readJsonFixture = (name: string) => JSON.parse(readFixture(`${name}.json`));

function collectBrowserErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function expectNoSeriousAccessibilityIssues(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  const violations = results.violations
    .filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))
    .map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target).join(", ")}`);
  expect(violations).toEqual([]);
}

async function expectNoDocumentOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);
}

async function expectSkipLinkOffscreen(page: Page) {
  const skip = page.getByRole("link", { name: "Skip to content" });
  const bounds = await skip.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.y + bounds!.height).toBeLessThan(0);
  await expect(skip).toHaveCSS("position", "fixed");
  await expect(skip).toHaveCSS("opacity", "0");
}

async function expectFolioBelowParagraph(page: Page, section: string, paragraph: string) {
  const chip = page.locator(`${section} .folio-chip`);
  const panelId = await chip.getAttribute("aria-controls");
  expect(panelId).toBeTruthy();
  const panel = page.locator(`[id="${panelId}"]`);
  await expect(panel.locator(".folio")).toBeVisible();
  await expect(page.locator(`${paragraph} .folio`)).toHaveCount(0);
  const paragraphBounds = await page.locator(paragraph).boundingBox();
  const folioBounds = await panel.locator(".folio").boundingBox();
  expect(folioBounds!.y).toBeGreaterThanOrEqual(paragraphBounds!.y + paragraphBounds!.height);
}

async function mockSupplierApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const endpoint = url.pathname.replace("/api/", "");
    if (endpoint === "ask")
      return route.fulfill({ contentType: "text/event-stream", body: readFixture("ask.sse") });
    if (endpoint.startsWith("feeds/"))
      return route.fulfill({
        contentType: "application/xml",
        headers: { "Content-Disposition": 'attachment; filename="hotel_list.xml"' },
        body: readFixture("feed.xml"),
      });
    if (endpoint === "hotels") {
      const data = readJsonFixture("hotels");
      const q = url.searchParams.get("q")?.toLowerCase();
      const area = url.searchParams.get("area")?.toLowerCase();
      data.items = data.items.filter(
        (h: { name: string; area: string }) =>
          (!q || h.name.toLowerCase().includes(q)) && (!area || h.area.toLowerCase().includes(area)),
      );
      data.total = data.items.length;
      return route.fulfill({ json: data });
    }
    const name = endpoint.startsWith("hotels/")
      ? "hotel"
      : endpoint === "accuracy" && url.searchParams.get("faults")
        ? "accuracy-faults"
        : endpoint;
    return route.fulfill({ json: readJsonFixture(name) });
  });
}
test.beforeEach(async ({ page }) => {
  await mockSupplierApi(page);
});

test("desk reads live meta before asking, then done mode; no empty grounding claim", async ({ page }) => {
  await page.route("**/api/meta", (route) =>
    route.fulfill({ json: { ...readJsonFixture("meta"), llm_mode: "live" } }),
  );
  const events = [
    {
      event: "answer",
      data: {
        text: "The live model is busy (free-tier limit). Try one of the three recorded demos, or ask again in a minute.",
        prices: [],
        folios: [],
        cited_cards: [],
      },
    },
    { event: "grounding", data: { traced: 0, total: 0, ok: true, cards_ok: true, untraced: [] } },
    { event: "done", data: { mode: "replay", model: "scripted-offline-demo", steps: 1, total_ms: 5 } },
  ];
  await page.route("**/api/ask", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join(""),
    }),
  );
  await page.goto("/");
  await expect(page.getByText("LIVE · bounded agent loop", { exact: true })).toBeVisible();
  await expect(page.getByText("OFFLINE REPLAY", { exact: false })).toHaveCount(0);
  await page.getByLabel("YOUR STAY REQUEST").fill("A custom question");
  await page.getByRole("button", { name: "Ask the desk" }).click();
  await expect(page.getByText("OFFLINE REPLAY", { exact: false })).toBeVisible();
  await expect(page.getByText("No prices in this answer.", { exact: true })).toBeVisible();
  await expect(page.locator(".grounding")).toHaveCount(0);
});

test("all faults have usable checkboxes and labelled policy sources", async ({ page }) => {
  await page.goto("/accuracy");
  const faults = readJsonFixture("faults");
  await expect(page.getByRole("checkbox")).toHaveCount(faults.length);
  for (const fault of faults) {
    const checkbox = page.getByRole("checkbox", { name: fault.label, exact: true });
    await expect(checkbox).toBeVisible();
    const bounds = await checkbox.boundingBox();
    expect(bounds!.width).toBeGreaterThanOrEqual(12);
    await checkbox.check();
    await expect(checkbox).toBeChecked();
  }
  for (const source of faults.at(-1).sources) {
    await expect(page.getByRole("link", { name: source.label, exact: true })).toHaveAttribute(
      "href",
      source.url,
    );
  }
  await expectNoDocumentOverflow(page);
});

test("accuracy defaults to future stay and retains historical controls and URL selection", async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date("2026-11-12T12:00:00Z"));
  const data = readJsonFixture("accuracy");
  data.samples[0].checkin = "2026-05-01";
  await page.route("**/api/accuracy?*", (route) => route.fulfill({ json: data }));
  await page.goto("/accuracy");
  await expect(page.getByRole("button", { name: "Sample 2: match", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "Sample 1: match", exact: true }).click();
  await expect(page).toHaveURL(/sample=sample-1/);
  await expect(page.getByRole("button", { name: "Sample 1: match", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: /30 samples matched/ }).click();
  await expect(page.getByRole("cell", { name: /2026-05-01/ })).toBeVisible();
});

test("hotel displays English name, grouped IDs and a compact fact preview", async ({ page }) => {
  const data = readJsonFixture("hotel");
  data.hotel.name = "فندق الاختبار";
  data.hotel.name_en = "Test hotel";
  data.hotel.mapped_osm_ids = [data.hotel.id, "node/456", "way/789", "node/987"];
  data.hotel.landmarks = Array.from({ length: 30 }, (_, i) => ({
    name: `Landmark ${i + 1}`,
    metres: (i + 1) * 100,
  }));
  const fact = (text: string) => ({ text, source: "https://www.openstreetmap.org/node/456" });
  data.card.facts = [
    fact(data.hotel.name),
    fact("OSM coordinates: 25.2, 55.28"),
    fact("OSM stars tag: 3"),
    fact("Proximity: near Downtown Dubai; selected landmark within 2 km"),
    fact(`Website: ${data.hotel.website}`),
    fact(`metro: ${data.hotel.nearest_metro.name}: 950 metres straight-line from hotel`),
    fact(`beach: ${data.hotel.nearest_beach.name}: 5700 metres straight-line from hotel`),
    ...data.hotel.landmarks.map((p: { name: string; metres: number }) =>
      fact(`${p.name}: ${p.metres} metres straight-line from hotel`),
    ),
  ];
  await page.route("**/api/hotels?*", (route) =>
    route.fulfill({ json: { total: 1, items: [{ ...data.hotel, from_folio: data.tonight }] } }),
  );
  await page.route("**/api/hotels/*", (route) => route.fulfill({ json: data }));
  await page.goto(`/hotels?q=test&hotel=${data.hotel.mapped_osm_ids[1]}`);
  await expect(page.locator(".hotel-name")).toContainText("Test hotel");
  await expect(page.locator(".hotel-row")).toContainText("also mapped as 4 OSM elements");
  await expect(page.locator(".hotel-open > .ledger > div")).toHaveCount(8);
  await expect(page.locator(".hotel-open > .ledger")).not.toContainText("Landmark 4:");
  await page.getByText(`Show all ${data.card.facts.length} facts`, { exact: true }).click();
  await expect(page.locator(".hotel-open details .ledger")).toContainText("Landmark 30:");
  await page.getByText("OSM elements (4)", { exact: true }).click();
  for (const osmId of data.hotel.mapped_osm_ids) {
    await expect(page.getByRole("link", { name: osmId, exact: true })).toHaveAttribute(
      "href",
      `https://www.openstreetmap.org/${osmId}`,
    );
  }
  await expect(page).toHaveURL(/q=test/);
});

test("card citation failure leaves the price grounding line driven by ok", async ({ page }) => {
  const events = readJsonFixture("ask");
  for (const frame of events) {
    if (frame.event === "answer") {
      frame.data.prices = frame.data.prices.filter((price: { traced: boolean }) => price.traced);
      frame.data.text = `AED ${frame.data.prices[0].amount}`;
    }
    if (frame.event === "grounding") {
      frame.data = { traced: 1, total: 1, ok: true, cards_ok: false, untraced: [] };
    }
  }
  await page.route("**/api/ask", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: events
        .map(
          (frame: { event: string; data: unknown }) =>
            `event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`,
        )
        .join(""),
    }),
  );
  await page.goto("/");
  await page.getByLabel("YOUR STAY REQUEST").fill("Find a hotel");
  await page.getByRole("button", { name: "Ask the desk" }).click();
  await expect(page.locator(".grounding")).toContainText("1 of 1 prices traced to rate_id");
  await expect(page.locator(".grounding")).not.toContainText("failed");
});
test("ask: ordered trace, answer, grounding, folio and explicit hold", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  const order: string[] = [];
  let holds = 0;
  // Deliver the routed fixture one event at a time, with gates controlled below.
  // This proves intermediate UI states rather than only inspecting the final DOM.
  await page.addInitScript(() => {
    const original = window.fetch;
    window.fetch = async (...args: Parameters<typeof fetch>) => {
      const response = await original(...args);
      if (!response.headers.get("content-type")?.includes("text/event-stream")) return response;
      const frames = (await response.text()).split("\n\n").filter(Boolean);
      const body = new ReadableStream<Uint8Array>({
        async start(controller) {
          for (const frame of frames) {
            controller.enqueue(new TextEncoder().encode(`${frame}\n\n`));
            await new Promise<void>((resolve) => {
              (window as unknown as { nextAskChunk: () => void }).nextAskChunk = resolve;
            });
          }
          controller.close();
        },
      });
      return new Response(body, { headers: response.headers, status: response.status });
    };
  });

  page.on("request", (r) => {
    if (r.url().endsWith("/api/holds")) {
      holds++;
      expect(r.postDataJSON()).toEqual(readJsonFixture("hold-request"));
    }
  });
  await page.goto("/");
  await expect(page.getByText("OFFLINE REPLAY", { exact: false })).toBeVisible();
  await page.evaluate(() => {
    const events: string[] = [];
    (window as unknown as { observed: string[] }).observed = events;
    new MutationObserver(() => {
      for (const [selector, name] of [
        [".trace li", "trace"],
        [".answer", "answer"],
        [".grounding", "grounding"],
      ])
        if (document.querySelector(selector) && !events.includes(name)) events.push(name);
    }).observe(document.querySelector("main")!, { childList: true, subtree: true });
  });
  await page.getByLabel("YOUR STAY REQUEST").fill("Find a refundable stay near a metro");
  await page.getByRole("button", { name: "Ask the desk" }).click();
  await expect(page.locator(".trace li")).toHaveCount(1);
  await expect(page.locator(".answer")).toHaveCount(0);
  expect(holds).toBe(0);
  const deliverNextAskEvent = () =>
    page.evaluate(() => (window as unknown as { nextAskChunk: () => void }).nextAskChunk());
  await deliverNextAskEvent();
  await expect(page.locator(".trace li")).toHaveCount(2);
  await expect(page.locator(".answer")).toHaveCount(0);
  await deliverNextAskEvent();
  await expect(page.locator(".answer")).toBeVisible();
  await expect(page.locator(".grounding")).toHaveCount(0);
  await deliverNextAskEvent();
  await expect(page.locator(".grounding")).toContainText("1 of 2 prices traced");
  await deliverNextAskEvent();
  await expect(page.getByRole("button", { name: "Confirm mock hold" })).toBeVisible();
  await deliverNextAskEvent();
  await deliverNextAskEvent();
  order.push(...(await page.evaluate(() => (window as unknown as { observed: string[] }).observed)));
  expect(order).toEqual(["trace", "answer", "grounding"]);
  await expect(page.locator(".untraced")).toContainText("not traced to a tool result");
  await expect(page.locator(".untraced s")).toHaveText("AED 999.00");
  await expect(page.getByRole("button", { name: "Confirm mock hold" })).toBeVisible();
  expect(holds).toBe(0);
  const chip = page.locator(".answer .folio-chip");
  await chip.click();
  await expect(chip).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".answer .folio")).toBeVisible();
  await expect(page).toHaveURL(/folio=test-rate/);
  await page.keyboard.press("Escape");
  await expect(chip).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "Confirm mock hold" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Mock hold" })).toContainText("mock-hold-test-1");
  expect(holds).toBe(1);
  expect(errors).toEqual([]);
});
test("hotel URL filters, open facts, 30 nights, keyboard and history", async ({ page }) => {
  await page.goto("/hotels");
  await expect(page.locator(".row-head")).toHaveCount(2);
  await page.keyboard.press("/");
  await expect(page.getByRole("searchbox")).toBeFocused();
  await page.keyboard.press("Escape");
  await page.keyboard.press("j");
  await expect(page.locator(".row-head").first()).toBeFocused();
  await page.keyboard.press("k");
  await page.keyboard.press("Enter");
  await expect(page.locator(".hotel-open > .ledger a")).toHaveCount(2);
  await expect(page.locator(".hotel-open .strip>span")).toHaveCount(30);
  await expect(page).toHaveURL(/hotel=/);
  await page.keyboard.press("Escape");
  await expect(page.locator(".hotel-open")).toHaveCount(0);
  await page.getByRole("searchbox").fill("Rove");
  await expect(page).toHaveURL(/q=Rove/);
  await expect(page.locator(".row-head")).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole("searchbox")).toHaveValue("Rove");
});
test("fault bench re-queries and resets the score; sample lives in URL", async ({ page }) => {
  await page.goto("/accuracy");
  await expect(page.locator(".score")).toHaveText("100.0%");
  await page.getByLabel("Omit taxes and fees", { exact: false }).check();
  await page.getByRole("button", { name: "Run audit" }).click();
  await expect(page.locator(".score")).toHaveText("50.0%");
  await expect(page.locator(".diff")).toContainText("TAXES_AND_FEES");
  await page.getByRole("button", { name: "Sample 3: mismatch", exact: true }).click();
  await expect(page).toHaveURL(/sample=sample-3/);
  await expect(page.locator(".diff-grid .mismatch")).toHaveCount(2);
  await page.getByRole("button", { name: "Reset faults" }).click();
  await expect(page.locator(".score")).toHaveText("100.0%");
});
test("rate limiting and malformed data fail visibly", async ({ page }) => {
  await page.route("**/api/ask", (r) => r.fulfill({ status: 429, json: readJsonFixture("error") }));
  await page.goto("/");
  await page.getByLabel("YOUR STAY REQUEST").fill("A stay");
  await page.getByRole("button", { name: "Ask the desk" }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("42 seconds");
  await page.route("**/api/feeds", (r) => r.fulfill({ json: { items: [{ valid: "yes" }] } }));
  await page.goto("/feeds");
  await expect(page.locator("main").getByRole("alert")).toContainText("does not match");
});
test("tax quote, feed download, honest eval and connect", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/taxes");
  await page.getByRole("button", { name: "Price a two-night stay under this rule" }).first().click();
  await expect(page.locator(".folio")).toBeVisible();
  await page.goto("/feeds");
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download hotel_list.xml" }).click();
  expect((await download).suggestedFilename()).toBe("hotel_list.xml");
  await page.goto("/method");
  await expect(page.getByText("Evaluation not run yet.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Copy command" }).click();
  await expect(page.getByRole("button", { name: "Copied", exact: true })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "claude mcp add --transport http rate-truth http://127.0.0.1:3171/mcp",
  );
  await page.route("**/api/eval", (r) => r.fulfill({ json: readJsonFixture("eval-run") }));
  await page.reload();
  await expect(page.getByRole("cell", { name: "0.85", exact: true })).toBeVisible();
});
const pages = [
  ["/", "Every price"],
  ["/hotels", "Real places"],
  ["/accuracy", "Does the landing"],
  ["/feeds", "Published formats"],
  ["/taxes", "The date"],
  ["/method", "Evidence before"],
];
for (const theme of ["light", "dark"])
  for (const [url, heading] of pages)
    test(`${theme}: ${url} loads, accessible, no overflow or console errors`, async ({ page }, testInfo) => {
      const errors = collectBrowserErrors(page);
      await page.addInitScript((t) => localStorage.setItem("rt-theme", t), theme);
      await page.goto(url);
      await expect(page.locator("h1")).toContainText(heading);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByText("Reading the supplier API…")).toHaveCount(0);
      if (url === "/hotels") {
        await page.locator(".row-head").first().click();
        await expect(page.locator(".hotel-open .folio")).toBeVisible();
      }
      if (url === "/") {
        await page
          .getByRole("button", { name: "Find a stay and prepare a mock hold.", exact: false })
          .click();
        await expect(page.locator(".grounding")).toBeVisible();
        await page.locator(".answer .folio-chip").click();
      }
      await expectNoSeriousAccessibilityIssues(page);
      await expectSkipLinkOffscreen(page);
      await page.screenshot({ path: testInfo.outputPath("page.png"), fullPage: true });
      await page.setViewportSize({ width: 375, height: 812 });
      await expectNoDocumentOverflow(page);
      expect(errors).toEqual([]);
    });
test("theme persists, skip link and 404 work; security headers", async ({ page, request }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const response = await page.goto("/no-such-entry");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("link", { name: "Return to the desk" })).toBeVisible();
  const headers = (await request.get("/")).headers();
  expect(headers["content-security-policy"]).toContain("connect-src 'self';");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["x-powered-by"]).toBeUndefined();
});

test("desk keeps its heading, answer and hold summary readable", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.locator("h1")).toHaveText("Every price has a paper trail.");
  await expectSkipLinkOffscreen(page);
  await page.getByRole("button", { name: "Find a stay and prepare a mock hold.", exact: false }).click();
  await expect(page.getByRole("button", { name: "Confirm mock hold" })).toBeEnabled();
  await expectSkipLinkOffscreen(page);
  await expect(page.locator(".hold .folio")).toHaveCount(0);
  await expect(page.locator(".hold-summary")).toContainText("Rove Downtown");
  await expect(page.locator(".hold-summary")).toContainText("2026-11-14 – 2026-11-16");
  await expect(page.locator(".hold-summary")).toContainText("AED 1,032.28");
  await expect(page.locator(".hold-summary")).toContainText("rate_id test-rate");

  const paragraph = page.locator(".answer-paragraph");
  await expect(paragraph).toContainText("for two nights.");
  const originalText = (await paragraph.textContent())!.replace(/[+−]/g, "");
  await page.locator(".answer .folio-chip").click();
  await expectFolioBelowParagraph(page, ".answer", ".answer-paragraph");
  await expect(page.locator(".hold .folio")).toHaveCount(0);
  expect((await paragraph.textContent())!.replace(/[+−]/g, "")).toBe(originalText);
  await page.keyboard.press("Escape");
  await page.locator(".hold .folio-chip").click();
  await expectFolioBelowParagraph(page, ".hold", ".hold-summary");
  await expectNoDocumentOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("desk-expanded.png"), fullPage: true });

  if (testInfo.project.name === "desktop") {
    const trace = page.locator(".desk-trace");
    await expect(trace).toHaveCSS("position", "sticky");
    await page.evaluate(() => window.scrollTo(0, 600));
    const traceBounds = await trace.boundingBox();
    expect(traceBounds!.y).toBeCloseTo(24, 0);
  }
});

test("skip link stays at the viewport corner only while focused", async ({ page }) => {
  await page.goto("/");
  await expectSkipLinkOffscreen(page);
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(skip).toHaveCSS("opacity", "1");
  await page.evaluate(() => window.scrollTo(0, 300));
  const bounds = await skip.boundingBox();
  expect(bounds!.x).toBe(16);
  expect(bounds!.y).toBe(12);
  await page.getByLabel("YOUR STAY REQUEST").click();
  await expectSkipLinkOffscreen(page);
});

test("folio evidence uses a second row with unbroken source links", async ({ page }) => {
  await page.goto("/hotels");
  await page.locator(".folio-chip").first().click();
  const line = page
    .locator(".hotel-row")
    .first()
    .locator(".folio-line")
    .filter({ has: page.locator("a") })
    .first();
  const label = await line.locator("dt").boundingBox();
  const amount = await line.locator(".line-amount").boundingBox();
  const evidence = await line.locator(".rule-id").boundingBox();
  expect(amount!.x).toBeGreaterThan(label!.x);
  expect(evidence!.y).toBeGreaterThanOrEqual(label!.y + label!.height);
  await expect(line.locator(".rule-id")).toHaveCSS("font-size", "11px");
  await expect(line.locator("a")).toHaveCSS("white-space", "nowrap");
  expect(await line.locator("a").evaluate((link) => link.getClientRects().length)).toBe(1);
});

test("sample ledger shows mismatches before 27 expandable matches", async ({ page }) => {
  const audit = readJsonFixture("accuracy");
  const faults = readJsonFixture("accuracy-faults");
  for (const index of [0, 2, 4]) {
    audit.samples[index] = faults.samples[index];
  }
  audit.score = 0.9;
  audit.by_reason = { TAXES_AND_FEES: 3 };
  await page.route("**/api/accuracy?**", (route) => route.fulfill({ json: audit }));
  await page.goto("/accuracy");
  const ledger = page.getByRole("region", { name: "Sample ledger" });
  await expect(ledger.locator("[data-row]")).toHaveCount(3);
  await expect(ledger.locator("tbody tr").first()).toContainText("Mismatch");
  const toggle = ledger.getByRole("button", { name: "27 more samples matched — show" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(ledger.locator("[data-row]")).toHaveCount(30);
  await ledger.getByRole("button", { name: "27 more samples matched — hide" }).click();
  await expect(ledger.locator("[data-row]")).toHaveCount(3);
  await expect(page.locator(".strip button")).toHaveCount(30);
  await page.getByRole("button", { name: "Sample 2: match", exact: true }).click();
  await expect(page).toHaveURL(/sample=sample-2/);
  await expect(page.locator(".diff")).toContainText("Match");
});

test("fault bench uses only API labels and optional descriptions", async ({ page }) => {
  const faults = readJsonFixture("faults");
  delete faults[0].description;
  faults[0].label = "API supplied fault label";
  await page.route("**/api/faults", (route) => route.fulfill({ json: faults }));
  await page.goto("/accuracy");
  const options = page.locator(".fault-option");
  await expect(options).toHaveCount(7);
  await expect(options.first()).toHaveText("API supplied fault label");
  await expect(options.first().locator("small")).toHaveCount(0);
  for (const [index, fault] of faults.entries()) {
    await expect(options.nth(index)).toContainText(fault.label);
    if (fault.description) await expect(options.nth(index)).toContainText(fault.description);
  }
  await expect(page.getByText("Inject a test fault into the audit.", { exact: true })).toHaveCount(0);
});

test("phone navigation exposes Method without clipping", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const method = page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Method", exact: true });
  await expect(method).toBeInViewport({ ratio: 1 });
  await method.click();
  await expect(page).toHaveURL(/\/method$/);
  await expectNoDocumentOverflow(page);
});
