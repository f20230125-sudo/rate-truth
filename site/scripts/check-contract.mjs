// Fixtures and optional live responses use the Python-generated JSON Schemas.
// Ajv is already in the site's eslint dependency tree. No schema is generated from zod.
import { createRequire } from "node:module";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";
const require = createRequire(import.meta.url);
const Ajv = require("ajv");
const schemas = path.resolve("../docs/schemas");
const fixtures = path.resolve("tests/fixtures");
// Pydantic uses 2020-12. Our models use the shared draft-07 vocabulary, with
// $defs as local references; Ajv 6 handles those after dropping the dialect URI.
const ajv = new Ajv({ allErrors: true, unknownFormats: "ignore", schemaId: "auto" });
let checks = 0;
function check(name, value) {
  const schema = JSON.parse(readFileSync(path.join(schemas, `${name}.json`), "utf8"));
  delete schema.$schema;
  const validate = ajv.compile(schema);
  if (!validate(value)) throw new Error(`${name}: ${JSON.stringify(validate.errors)}`);
  checks++;
}
for (const file of readdirSync(fixtures).filter((file) => file.endsWith(".json"))) {
  const name = file.slice(0, -5);
  if (existsSync(path.join(schemas, file)))
    check(name, JSON.parse(readFileSync(path.join(fixtures, file), "utf8")));
}
for (const frame of JSON.parse(readFileSync(path.join(fixtures, "ask.json"), "utf8"))) {
  check(frame.event === "error" ? "stream-error" : frame.event, frame.data);
}
for (const frame of readFileSync(path.join(fixtures, "ask.sse"), "utf8")
  .split(/\r?\n\r?\n/)
  .filter(Boolean)) {
  const event = frame.match(/^event: (.+)$/m)?.[1];
  const data = frame.match(/^data: (.+)$/m)?.[1];
  if (event && data) check(event === "error" ? "stream-error" : event, JSON.parse(data));
}
if (process.env.CONTRACT_API_URL) {
  for (const name of ["meta", "hotels", "accuracy", "faults", "feeds", "taxes", "eval"]) {
    const response = await fetch(`${process.env.CONTRACT_API_URL}/api/${name}`);
    if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
    check(name, await response.json());
  }
  const base = process.env.CONTRACT_API_URL;
  const hotels = await (await fetch(`${base}/api/hotels?limit=1`)).json();
  const id = hotels.items[0].id;
  check("hotel", await (await fetch(`${base}/api/hotels/${encodeURIComponent(id)}`)).json());
  const date = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dubai" });
  check(
    "quote",
    await (await fetch(`${base}/api/quote?${new URLSearchParams({ hotel_id: id, checkin: date })}`)).json(),
  );
  check(
    "market",
    await (await fetch(`${base}/api/market?${new URLSearchParams({ hotel_id: id, live: "false" })}`)).json(),
  );
  check("market-summary", await (await fetch(`${base}/api/market/summary`)).json());
}
console.log(`${checks} JSON Schema contract checks passed`);
