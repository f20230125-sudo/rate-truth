// Launch Next directly: Playwright's Windows webServer teardown uses taskkill /T,
// which this restricted workspace denies. Owning one child lets us close it cleanly.
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
const base = process.env.BASE_URL ?? "http://127.0.0.1:3171";
const server = process.env.BASE_URL
  ? null
  : spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "-p", "3171", "-H", "127.0.0.1"], {
      stdio: "inherit",
      windowsHide: true,
    });
let runner;
function cleanup() {
  if (runner && runner.exitCode === null) runner.kill();
  if (server && server.exitCode === null) server.kill();
}
process.once("SIGINT", () => {
  cleanup();
  process.exitCode = 130;
});
process.once("SIGTERM", () => {
  cleanup();
  process.exitCode = 143;
});
try {
  if (server) {
    let ready = false;
    for (let i = 0; i < 120; i++) {
      if (server.exitCode !== null) throw new Error(`Next exited with ${server.exitCode}`);
      try {
        if ((await fetch(base)).ok) {
          ready = true;
          break;
        }
      } catch {}
      await delay(500);
    }
    if (!ready) throw new Error("Next did not become ready on 3171.");
  }
  runner = spawn(
    process.execPath,
    ["node_modules/@playwright/test/cli.js", "test", ...process.argv.slice(2)],
    { stdio: "inherit", windowsHide: true, env: { ...process.env, BASE_URL: base } },
  );
  process.exitCode = await new Promise((resolve, reject) => {
    runner.once("exit", (code) => resolve(code ?? 1));
    runner.once("error", reject);
  });
} finally {
  cleanup();
}
