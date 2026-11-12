import { expect, test } from "@playwright/test";

test.skip(process.env.LIVE_API !== "1", "Set LIVE_API=1 with the real API running on 8170.");

test("real OSM API: hotels, balanced folio, fault bench, feeds, taxes, method and streamed desk", async ({
  page,
  request,
}) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const meta = await (await request.get("/api/meta")).json();
  expect(meta.hotels).toBe(737);
  expect(["live", "replay"]).toContain(meta.llm_mode);
  const hotels = await (await request.get("/api/hotels")).json();
  await page.goto("/hotels");
  await expect(page.getByText(`${hotels.total} HOTELS`, { exact: false })).toBeVisible();
  const detailResponse = page.waitForResponse((r) => r.url().includes("/api/hotels/") && r.ok());
  await page.locator(".row-head").first().click();
  const detail = await (await detailResponse).json();
  expect(detail.hotel.id).toMatch(/^(node|way|relation)\/\d+$/);
  const folio = detail.tonight;
  const fils = (amount: string) => Number(amount.replace(".", ""));
  expect(folio.lines.reduce((sum: number, line: { amount: string }) => sum + fils(line.amount), 0)).toBe(
    fils(folio.total),
  );
  await expect(page.locator(".hotel-open .folio")).toBeVisible();
  await expect(page.locator(".hotel-open")).toContainText(detail.hotel.name);

  await page.goto("/accuracy");
  await expect(page.locator(".score")).toHaveAttribute("aria-label", "100.0 percent price accuracy");
  await page.getByRole("checkbox", { name: /Stale cache/ }).check();
  const faultResponse = page.waitForResponse(
    (r) => r.url().includes("/api/accuracy?") && r.url().includes("stale_cache") && r.ok(),
  );
  await page.getByRole("button", { name: "Run audit", exact: true }).click();
  const audit = await (await faultResponse).json();
  expect(audit.score).toBeGreaterThan(0.5);
  expect(audit.score).toBeLessThan(1);
  expect(
    audit.samples.some((sample: { detected_reason: string }) => sample.detected_reason === "stale_cache"),
  ).toBe(true);
  await expect(page.locator(".score")).not.toHaveAttribute("aria-label", "100.0 percent price accuracy");
  await expect(page.locator("main")).toContainText("PRICE_FEED_DELAYED");

  await page.goto("/feeds");
  await expect(page.getByText("XSD valid", { exact: false })).toHaveCount(3);
  await expect(page.getByText("Structurally checked", { exact: false })).toHaveCount(3);
  await page.goto("/taxes");
  await expect(page.locator(".tax-row").first()).toBeVisible();
  await expect(page.locator(".timeline")).toContainText("resolution 40 2026");
  await page.goto("/method");
  await expect(page.getByText("Evaluation not run yet.", { exact: false })).toBeVisible();

  await page.goto("/");
  await expect(
    page.getByText(meta.llm_mode === "replay" ? "OFFLINE REPLAY" : "LIVE · bounded", { exact: false }),
  ).toBeVisible();
  const askResponse = page.waitForResponse((r) => r.url().endsWith("/api/ask") && r.ok());
  await page.getByRole("button", { name: /Find a stay and prepare a mock hold/ }).click();
  const frames = (await (await askResponse).text()).split("\n\n").filter(Boolean);
  const order = frames.map((frame) => frame.match(/^event: (.+)$/m)?.[1]);
  const done = JSON.parse(frames.find((frame) => frame.startsWith("event: done\n"))!.split("\ndata: ")[1]);
  expect(["live", "replay"]).toContain(done.mode);
  expect(order).toContain("answer");
  expect(order).toContain("grounding");
  expect(order).toContain("hold_request");
  expect(order.at(-1)).toBe("done");
  if (done.mode === "replay") {
    expect(order).toEqual(["trace", "trace", "answer", "grounding", "hold_request", "done"]);
  }
  const holdFrame = frames.find((frame) => frame.startsWith("event: hold_request\n"))!;
  const holdRequest = JSON.parse(holdFrame.split("\ndata: ")[1]);
  expect(holdRequest.hold_token.length).toBeGreaterThan(32);
  const holdResponse = page.waitForResponse((r) => r.url().endsWith("/api/holds"));
  await page.getByRole("button", { name: "Confirm mock hold" }).click();
  const held = await holdResponse;
  expect(held.status()).toBe(201);
  expect(held.request().postDataJSON()).toEqual({
    rate_id: holdRequest.rate_id,
    hold_token: holdRequest.hold_token,
    confirm: true,
  });
  await expect(page.getByRole("status").filter({ hasText: "Mock hold" })).toBeVisible();
  await expect(page.locator(".grounding")).toContainText("prices traced to rate_id");
  await expect(page.locator(".grounding")).not.toContainText("failed");
  if (done.mode === "replay" && done.model === "scripted-offline-demo") {
    await expect(page.getByRole("region", { name: "Desk answer" })).toContainText(
      "scripted MCP demonstration",
    );
  }
  expect(errors).toEqual([]);
});
