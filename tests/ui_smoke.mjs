/* Headless check of the panel without a browser: a tiny DOM stub, the real
   app.js, and a live snapshot from the running server.

   node tests/ui_smoke.mjs                      (expects http://127.0.0.1:8787)
*/
import fs from "node:fs";
import vm from "node:vm";

const BASE = process.env.COSA_BASE || "http://127.0.0.1:8787";
// the panel is token-protected now; the probe authenticates the same way the browser does
import fs0 from "node:fs";
let TOKEN = process.env.COSA_TOKEN || "";
if (!TOKEN) {
  try {
    const line = fs0.readFileSync(new URL("../var/auth.env", import.meta.url), "utf8")
      .split("\n").find((l) => l.startsWith("COSA_AUTH_TOKEN="));
    TOKEN = line ? line.split("=")[1].trim() : "";
  } catch { /* no token file */ }
}
globalThis.__COSA_TOKEN = TOKEN;

class El {
  constructor(sel) {
    this.sel = sel; this._html = ""; this._text = ""; this.tagName = "DIV";
    this.dataset = {}; this.style = {}; this.value = ""; this.id = sel.replace(/[^a-z0-9]/gi, "");
    this.classList = { add() {}, remove() {}, contains: () => false, toggle() {} };
  }
  set innerHTML(v) { this._html = String(v); } get innerHTML() { return this._html; }
  set textContent(v) { this._text = String(v); } get textContent() { return this._text; }
  insertAdjacentHTML(_p, h) { this._html += h; }
  appendChild() {} remove() {} addEventListener() {} removeEventListener() {}
  setAttribute() {} getAttribute() { return null; } closest() { return null; } querySelector() { return null; }
}
const nodes = new Map();
const documentStub = {
  querySelector(sel) { if (!nodes.has(sel)) nodes.set(sel, new El(sel)); return nodes.get(sel); },
  createElement(tag) { const e = new El("created"); e.tagName = tag.toUpperCase(); return e; },
  addEventListener() {}, body: { appendChild() {} }, activeElement: null,
};
const store = {};
const localStorageStub = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
class EventSourceStub { constructor() { this.onopen = null; this.onmessage = null; this.onerror = null; } }

globalThis.document = documentStub;
globalThis.localStorage = localStorageStub;
globalThis.EventSource = EventSourceStub;
globalThis.location = { origin: BASE };
globalThis.window = globalThis;

const appSource = fs.readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
const probe = `
(async () => {
  const state = await (await fetch(${JSON.stringify(BASE + "/api/state")}, {
    headers: globalThis.__COSA_TOKEN ? { Authorization: "Bearer " + globalThis.__COSA_TOKEN } : {}
  })).json();
  S = state;
  const checks = [];
  for (const app of ["console", "cockpit", "tickets", "ledger", "dossier", "feishu", "audit"]) {
    APP = app; if (state.tickets.length) SEL = state.tickets[0].id;
    try {
      render();
      const html = document.querySelector("#main").innerHTML;
      checks.push({ app, bytes: html.length, head: html.includes("viewhead"),
                    undefined: /undefined/.test(html), nan: /NaN/.test(html) });
    } catch (err) {
      checks.push({ app, error: String(err && err.stack || err) });
    }
  }
  try { LANG = "en"; APP = "ledger"; render();
    const html = document.querySelector("#main").innerHTML;
    checks.push({ app: "ledger-en", bytes: html.length, head: html.includes("viewhead") }); }
  catch (err) { checks.push({ app: "ledger-en", error: String(err) }); }
  globalThis.__checks = checks;
  globalThis.__snapshot = { tickets: state.tickets.length, cabins: state.cabins.length, ledger: state.ledger.length };
})();
`;

vm.runInThisContext(appSource + "\n" + probe, { filename: "app.js" });

await new Promise((r) => setTimeout(r, 2500));
const checks = globalThis.__checks || [];
let bad = 0;
for (const c of checks) {
  if (c.error) { bad++; console.log(`[FAIL] ${c.app}: ${c.error}`); continue; }
  const okLen = c.bytes > 300 && c.head;   // an empty list is a valid state, a missing header is not
  const clean = !c.undefined && !c.nan;
  if (!okLen || !clean) bad++;
  console.log(`${okLen && clean ? "[ok]" : "[FAIL]"} ${c.app}: ${c.bytes}B head=${!!c.head} undefined=${!!c.undefined} NaN=${!!c.nan}`);
}
if (!checks.length) { console.log("[FAIL] no view rendered"); bad++; }
console.log("snapshot:", JSON.stringify(globalThis.__snapshot));
process.exit(bad ? 1 : 0);
