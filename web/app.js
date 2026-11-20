/* Coffee Super-Agent OS — panel.
   One snapshot, one render path, SSE nudges. No framework, no build step. */

const I18N = {
  zh: {
    app_console: "控制台", app_cockpit: "雾化舱", app_tickets: "工单", app_ledger: "碳账本",
    app_dossier: "方法学", app_feishu: "飞书", app_audit: "审计",
    console_h: "控制台", console_p: "一句话进来，内核做准入判断，Worker 在独立目录里干活，结果回到这里。你说的话就是一条 Trigger。",
    cockpit_h: "雾化舱 AeroCabin", cockpit_p: "IoT 数据每 12s 写入一次；越过阈值即生成 Trigger，由策略决定是否开工单。数据为模拟，非实测。",
    tickets_h: "工单 Tickets", tickets_p: "每张工单带着它的授权（Policy 版本、scope、强度）。Worker 无权新建工单，只能报告。",
    ledger_h: "碳账本 Ledger", ledger_p: "每次计算追加一串哈希链行，永不改写。重算是新增一次 revision，旧行保留供审阅者反推。",
    dossier_h: "方法学档案 Dossier", dossier_p: "版本、边界、因子与失效条件。因子未核证——这页会明确写出来。",
    audit_h: "审计与健康", audit_p: "事件流、副作用队列、Watchdog 中断次数、Outbox 回执。",
    feishu_h: "飞书桥 Feishu bridge", feishu_p: "飞书是第 5 个 Source：同一条会话里下指令 → Router 建单 → Worker 执行 → 结果回到这条会话。身份按 Source 隔离，open_id 不映射到面板账号。",
    fs_sim: "模拟一条飞书消息", fs_chat: "会话 chat_id", fs_actor: "发送者 open_id", fs_send: "发送",
    fs_webhook: "事件订阅地址", fs_transport: "通道", fs_allow: "Source 白名单", fs_commands: "可用指令",
    fs_in: "入站事件", fs_out: "出站消息", fs_cfg: "配置", fs_hint: "没有飞书凭据时走 sim 通道：消息只写入 feishu_out，不真的发出。",
    fs_poll: "轮询",
    fs_quick: ["/status", "/tickets", "/ledger B-2026-11", "/dossier", "/anomaly A1"],
    fs_warn_token: "未配置 FEISHU_VERIFICATION_TOKEN：回调无法验真，任何知道这个地址的人都能伪造一条消息。仅适合本机演示。",
    fs_warn_enc: "已配置 Encrypt Key：本构建不支持 AES 加密回调，飞书会收到 400。请留空或前置代理。",
    fs_allow_add: "+ 白名单",
    send: "发送", sending: "发送中…", pause: "暂停内核", resume: "恢复内核", paused: "已暂停",
    inject: "注入异常", harvest: "记录采收", factor: "因子更新", recompute: "重算并追加",
    stop: "停止", retry: "重试", resume_t: "继续", view: "查看",
    attention: "待你决定", working: "执行中", ended: "已结束", open: "开放",
    mandate: "授权 Mandate", scope: "范围 scope", strength: "强度", rule: "依据规则",
    report: "报告", inputs: "输入", artifacts: "产物", steps: "Worker 步骤", transcript: "过程记录",
    chain: "哈希链", total: "总量", intensity: "强度", verify: "链校验", verified: "链完整",
    broken: "链断裂", factors: "因子表", status: "状态", warning: "边界与不做的事",
    events: "事件流", health: "系统健康", outbox: "回执 Outbox", policy: "策略",
    no_tickets: "还没有工单。去雾化舱注入一次异常，或直接在控制台说一句话。",
    offline: "连接断开，重试中…", online: "在线", live: "真实模型", mock: "离线模拟",
    lang_name: "EN", sim_note: "模拟数据", policy_ver: "策略",
    select_hint: "选一张工单看它的授权与过程。",
    question: "待回答", ask: "需要你决定的问题",
    count_open: "开放", count_ended: "已结束", count_triggers: "触发", count_decisions: "决定",
    count_ledger: "链上行", count_effects: "待办副作用", count_attention: "待你决定",
    boot: ["kernel: sqlite WAL, one writer", "policy: v1 loaded, hash pinned",
           "sources: aero · field · carbon · brand · feishu", "router: ready", "workers: pool up",
           "ledger: chain genesis verified", "watchdog: 2s heartbeat"],
    lang_btn: "EN", ok: "完成", fail: "失败",
    example1: "给我 B-2026-11 的碳账本与方法学摘要",
    example2: "舱 A1 的 EC 为什么上升？给我下一步动作。",
    example3: "用一句话解释我们的碳边界，中英双语。"
  },
  en: {
    app_console: "Console", app_cockpit: "Cockpit", app_tickets: "Tickets", app_ledger: "Ledger",
    app_dossier: "Dossier", app_feishu: "Feishu", app_audit: "Audit",
    console_h: "Console", console_p: "One sentence in. The kernel gates it, a Worker does the work in its own directory, the result comes back here. Your message is a Trigger.",
    cockpit_h: "AeroCabin", cockpit_p: "IoT writes every 12s; crossing a threshold becomes a Trigger and the policy decides whether a Ticket opens. Simulated data, not measured.",
    tickets_h: "Tickets", tickets_p: "Every Ticket carries its Mandate (policy version, scope, strength). A Worker may not create Tickets; it can only report.",
    ledger_h: "Carbon ledger", ledger_p: "Each computation appends a run of hash-chained rows and never rewrites. A recompute is a new revision; old rows stay for review.",
    dossier_h: "Methodology dossier", dossier_p: "Version, boundary, factors, invalidation conditions. The factors are unverified and this page says so.",
    audit_h: "Audit & health", audit_p: "Event stream, effect queue, watchdog interrupts, outbox receipts.",
    feishu_h: "Feishu bridge", feishu_p: "Feishu is the fifth Source: a command in a chat opens a Ticket, a Worker runs it, the result returns to that same chat. Identities stay Source-local — open_ids are never mapped onto panel accounts.",
    fs_sim: "Simulate a Feishu message", fs_chat: "chat_id", fs_actor: "sender open_id", fs_send: "Send",
    fs_webhook: "Event subscription URL", fs_transport: "Transport", fs_allow: "Source allowlist",
    fs_commands: "Commands", fs_in: "Inbound events", fs_out: "Outbound messages", fs_cfg: "Config",
    fs_poll: "Polling",
    fs_hint: "Without Feishu credentials the bridge runs on the sim transport: messages are recorded in feishu_out and never actually sent.",
    fs_quick: ["/status", "/tickets", "/ledger B-2026-11", "/dossier", "/anomaly A1"],
    fs_warn_token: "FEISHU_VERIFICATION_TOKEN is not set: callbacks cannot be authenticated, so anyone who learns this URL can forge a message. Local demos only.",
    fs_warn_enc: "Encrypt Key is set, but this build has no AES: Feishu will get a 400. Clear it or put a proxy in front.",
    fs_allow_add: "+ allow",
    send: "Send", sending: "sending…", pause: "Pause kernel", resume: "Resume kernel", paused: "paused",
    inject: "Inject anomaly", harvest: "Record harvest", factor: "Factor update", recompute: "Recompute + append",
    stop: "Stop", retry: "Retry", resume_t: "Continue", view: "View",
    attention: "needs you", working: "working", ended: "ended", open: "open",
    mandate: "Mandate", scope: "Scope", strength: "Strength", rule: "Rule",
    report: "Report", inputs: "Inputs", artifacts: "Artifacts", steps: "Worker steps", transcript: "Transcript",
    chain: "Hash chain", total: "Total", intensity: "Intensity", verify: "Chain check", verified: "chain intact",
    broken: "chain broken", factors: "Factors", status: "Status", warning: "Boundary and non-claims",
    events: "Events", health: "Health", outbox: "Outbox", policy: "Policy",
    no_tickets: "No Tickets yet. Inject an anomaly in the cockpit, or just say something in the console.",
    offline: "disconnected, retrying…", online: "online", live: "live model", mock: "offline mock",
    lang_name: "中文", sim_note: "simulated", policy_ver: "policy",
    select_hint: "Pick a Ticket to see its Mandate and its work.",
    question: "waiting", ask: "question for a person",
    count_open: "open", count_ended: "ended", count_triggers: "triggers", count_decisions: "decisions",
    count_ledger: "ledger rows", count_effects: "effects pending", count_attention: "needs you",
    boot: ["kernel: sqlite WAL, one writer", "policy: v1 loaded, hash pinned",
           "sources: aero · field · carbon · brand · feishu", "router: ready", "workers: pool up",
           "ledger: chain genesis verified", "watchdog: 2s heartbeat"],
    lang_btn: "中文", ok: "done", fail: "failed",
    example1: "Summarise the B-2026-11 carbon ledger and the methodology",
    example2: "Why did cabin A1 EC rise? Give me the next action.",
    example3: "Explain our carbon boundary in one bilingual sentence."
  }
};
const LANGS = ["zh", "en"];
let LANG = localStorage.getItem("cosa.lang") || "zh";
if (!I18N[LANG]) LANG = "zh";
const t = (k) => (I18N[LANG] && I18N[LANG][k] !== undefined ? I18N[LANG][k] : k);

let S = null;
let APP = localStorage.getItem("cosa.app") || "console";
let SEL = null;
let DRAFT = "";
let MODAL = null;
let PENDING_RENDER = false;
let LINK_OK = false;

const $ = (s) => document.querySelector(s);
const TOKEN_KEY = "cosa.token";
const token = () => localStorage.getItem(TOKEN_KEY) || "";

function showLogin(msg) {
  if (document.getElementById("login")) return;
  const d = document.createElement("div");
  d.id = "login";
  d.className = "modal";
  d.innerHTML = `<div class="card" style="max-width:520px">
    <h3 style="margin:0 0 6px">需要访问令牌 · panel token</h3>
    <p class="hint">服务端启动时会打印；也存在 <code>var/auth.env</code>。只在本机使用，别贴到公开地方。</p>
    <div class="composer" style="grid-template-columns:1fr auto">
      <input id="login-token" placeholder="paste token" style="background:var(--surface);border:1px solid #333639;border-radius:14px;padding:9px 12px;font-family:var(--mono)">
      <button class="btn primary" id="login-go">进入</button>
    </div>
    <div class="hint" style="margin-top:8px">${msg || ""}</div></div>`;
  document.body.appendChild(d);
  const go = () => {
    const v = ($("#login-token").value || "").trim();
    if (!v) return;
    localStorage.setItem(TOKEN_KEY, v);
    location.reload();
  };
  document.getElementById("login-go").addEventListener("click", go);
  $("#login-token").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  $("#login-token").focus();
}

async function apiFetch(url, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (token()) headers["Authorization"] = "Bearer " + token();
  const r = await fetch(url, { ...opts, headers });
  if (r.status === 401) { showLogin("令牌无效或已更换"); throw new Error("unauthorized"); }
  return r;
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (x, d = 2) => (x === null || x === undefined || Number.isNaN(Number(x)) ? "—" : Number(x).toFixed(d));
const short = (h, n = 10) => (h ? String(h).slice(0, n) + "…" : "—");
const ago = (iso) => {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
};

const APPS = [
  { id: "console", ico: "⌘" }, { id: "cockpit", ico: "◎" }, { id: "tickets", ico: "▤" },
  { id: "ledger", ico: "⛓" }, { id: "dossier", ico: "§" }, { id: "feishu", ico: "✈" },
  { id: "audit", ico: "◉" }
];

/* ---------------------------------------------------------------- boot */
function boot() {
  const box = $("#bootlog");
  const lines = t("boot");
  let i = 0;
  const tick = () => {
    if (i < lines.length) {
      box.insertAdjacentHTML("beforeend", `<div><span class="ok">✓</span> ${esc(lines[i++])}</div>`);
      setTimeout(tick, 110);
    } else {
      setTimeout(() => $("#boot").classList.add("gone"), 260);
    }
  };
  tick();
  // safety: never let the boot overlay outlive a broken script
  setTimeout(() => $("#boot").classList.add("gone"), 2500);
}
function skipBoot() { $("#boot").classList.add("gone"); }

/* ---------------------------------------------------------------- data */
async function refresh() {
  try {
    const r = await apiFetch("/api/state", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    S = await r.json();
    LINK_OK = true;
    $("#offline").classList.remove("on");
    render();
  } catch (e) {
    LINK_OK = false;
    if (e && e.message === "unauthorized") return;      // login overlay is already up
    $("#offline").classList.add("on");
    $("#link-dot").className = "dot bad";
    $("#link-text").textContent = t("offline");
    const m = $("#main");
    if (m && !S) {
      m.innerHTML = `<div class="card" style="max-width:720px;margin:24px auto">
        <h3>面板连不上内核 · cannot reach the kernel</h3>
        <p class="hint">${esc(String(e && e.message || e))}</p>
        <p class="hint">检查：服务是否在跑 <code>http://127.0.0.1:8787/api/health</code>；地址是否写成了
        <code>localhost</code>（本服务只监听 <code>127.0.0.1</code>）。</p>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button class="btn primary" data-act="refresh">retry</button>
          <button class="btn" data-act="change-token">换令牌</button>
        </div></div>`;
    }
  }
}
function connect() {
  try {
    const es = new EventSource("/api/stream?token=" + encodeURIComponent(token()));
    es.onopen = () => { $("#link-dot").className = "dot"; $("#link-text").textContent = t("online"); };
    es.onmessage = () => { clearTimeout(window.__nudge); window.__nudge = setTimeout(refresh, 350); };
    es.onerror = () => { $("#link-dot").className = "dot bad"; $("#link-text").textContent = t("offline"); };
  } catch (e) { /* polling still works */ }
}

async function post(url, body) {
  const r = await apiFetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { toast(`${r.status}: ${j.error || "error"}`, true); return null; }
  refresh();
  return j;
}
function toast(msg, bad = false) {
  const el = document.createElement("div");
  el.className = "t" + (bad ? " bad" : "");
  el.textContent = msg;
  $("#toast").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

/* ---------------------------------------------------------------- render */
function render() {
  if (!S) return;
  const ae = document.activeElement;
  if (ae && ["TEXTAREA", "INPUT", "SELECT"].includes(ae.tagName) && ae.closest("#main")) {
    PENDING_RENDER = true;
    return;
  }
  PENDING_RENDER = false;
  $("#ver").textContent = "v" + S.status.app;
  const live = S.status.llm === "live";
  $("#mode-dot").className = "dot " + (live ? "" : "idle");
  $("#mode-text").innerHTML = `<b>${live ? t("live") : t("mock")}</b>${live ? "" : " · " + esc(S.status.model)}`;
  $("#policy-text").textContent = `${t("policy_ver")} v${S.status.policy_version} · ${short(S.status.policy_hash, 8)}`;
  const attn = S.counts.attention;
  $("#attn-text").textContent = `${attn} ${t("count_attention")}`;
  $("#attn-dot").className = "dot " + (attn ? "warn" : "idle");
  $("#link-text").textContent = LINK_OK ? t("online") : t("offline");
  $("#link-dot").className = "dot " + (LINK_OK ? "" : "bad");
  $("#btn-pause").textContent = S.status.paused ? t("resume") : t("pause");
  $("#btn-lang").textContent = t("lang_btn");
  $("#clock").textContent = new Date().toLocaleTimeString("en-GB");

  $("#dock").innerHTML = APPS.map((a) => {
    const badge = a.id === "tickets" && attn ? `<span class="badge">${attn}</span>` : "";
    return `<button data-act="nav" data-app="${a.id}" class="${APP === a.id ? "on" : ""}">
      <span class="ico">${a.ico}</span><span>${esc(t("app_" + a.id))}</span>${badge}</button>`;
  }).join("") + `<div class="dockfoot">${S.counts.open} open<br>${S.counts.ledger_rows} chained</div>`;

  const views = { console: viewConsole, cockpit: viewCockpit, tickets: viewTickets, ledger: viewLedger, dossier: viewDossier, feishu: viewFeishu, audit: viewAudit };
  $("#main").innerHTML = (views[APP] || viewConsole)();
  if (MODAL) drawModal();
}

function viewHead(id, actions) {
  return `<div class="viewhead"><div><h1>${esc(t(id + "_h"))}</h1><p>${esc(t(id + "_p"))}</p></div>
    <div class="actions">${actions || ""}</div></div>`;
}

/* ---------------------------------------------------------------- console */
function viewConsole() {
  const tickets = (S.tickets || []).filter((x) => x.kind === "human.message").slice().reverse();
  const thread = tickets.length
    ? tickets.map((x) => {
        const rep = x.latest_report;
        const q = rep && rep.question ? `<div class="warnbox" style="margin-top:8px">${esc(t("ask"))}: ${esc(rep.question)}</div>` : "";
        return `<div class="msg">
          <div class="who"><span>erik</span><span>${esc((x.mandate && x.mandate.granted_at) || x.created_at)}</span><span class="badge info">${esc(x.status)}</span></div>
          <div class="body">${esc(x.title.replace(/^Human request:\s*/i, ""))}</div>
        </div>
        <div class="msg">
          <div class="who"><span>router · worker</span><span>${esc(x.id)}</span><span class="badge ${x.status === "ended" ? "ok" : "warn"}">${esc(x.status)}</span></div>
          <div class="body">${esc(rep ? rep.summary : "working…")}</div>${q}
          <div style="margin-top:8px;display:flex;gap:6px">
            <button class="btn tiny" data-act="select-ticket" data-id="${x.id}">${esc(t("mandate"))}</button>
            <button class="btn tiny" data-act="view-file" data-id="${x.id}" data-name="dossier.md">dossier.md</button>
          </div>
        </div>`;
      }).join("")
    : `<div class="empty">${esc(t("no_tickets"))}</div>`;

  return viewHead("console") + `<div class="console">
    <div class="chips">
      ${[t("example1"), t("example2"), t("example3")].map((x) => `<button class="chip" data-act="chip" data-text="${esc(x)}">${esc(x)}</button>`).join("")}
    </div>
    <div class="scroll"><div class="thread">${thread}</div></div>
    <form class="composer" data-act="send">
      <textarea id="composer" placeholder="…">${esc(DRAFT)}</textarea>
      <button class="btn primary" type="submit">${esc(t("send"))}</button>
    </form>
  </div>`;
}

/* ---------------------------------------------------------------- cockpit */
function spark(trend, key, color, thr) {
  if (!trend || trend.length < 2) return `<svg class="spark"></svg>`;
  const vals = trend.map((p) => Number(p[key]));
  const lo = Math.min(...vals, thr ?? Infinity), hi = Math.max(...vals, thr ?? -Infinity);
  const span = hi - lo || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * 100},${30 - ((v - lo) / span) * 28}`).join(" ");
  const ty = thr !== undefined ? 30 - ((thr - lo) / span) * 28 : null;
  return `<svg class="spark" viewBox="0 0 100 32" preserveAspectRatio="none">
    ${ty !== null ? `<line x1="0" y1="${ty}" x2="100" y2="${ty}" stroke="rgba(244,33,46,.55)" stroke-width=".5" stroke-dasharray="2 2"/>` : ""}
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.1" vector-effect="non-scaling-stroke"/>
  </svg>`;
}
function viewCockpit() {
  const acts = `<button class="btn" data-act="inject" data-cabin="A1">A1 ${esc(t("inject"))}</button>
    <button class="btn" data-act="inject" data-cabin="B2">B2 ${esc(t("inject"))}</button>
    <button class="btn" data-act="inject" data-cabin="C3">C3 ${esc(t("inject"))}</button>
    <button class="btn" data-act="harvest">${esc(t("harvest"))}</button>
    <button class="btn" data-act="factor">${esc(t("factor"))}</button>`;
  const cards = (S.cabins || []).map((c) => {
    const th = c.thresholds || {};
    const openTickets = (S.tickets || []).filter((x) => x.thread_key === "aero/cabin-" + c.id && x.status === "open");
    return `<div class="card cabin">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h3 style="margin:0">Cabin ${esc(c.id)}</h3>
        <span class="badge ${c.status === "ok" ? "ok" : "bad"}">${c.status === "ok" ? "stable" : "drift"} · ${esc(ago(c.at))} ago</span>
      </div>
      <div class="metric"><span>EC mS/cm</span><b>${num(c.ec, 2)}</b></div>
      ${spark(c.trend, "ec", "#1d9bf0", th.ec_high)}
      <div class="metric"><span>pH</span><b>${num(c.ph, 2)}</b></div>
      ${spark(c.trend, "ph", "#00ba7c", th.ph_high)}
      <div class="metric"><span>temp / RH</span><b>${num(c.temp_c, 1)}°C · ${num(c.rh, 0)}%</b></div>
      <div class="metric"><span>PPFD</span><b>${num(c.ppfd, 0)} µmol</b></div>
      <div class="metric"><span>water / kWh</span><b>${num(c.water_l, 1)} L · ${num(c.energy_kwh, 2)}</b></div>
      <div class="foot"><span class="hint">${openTickets.length ? openTickets.length + " open ticket" : "no open ticket"}</span>
        <span class="badge info">${esc(t("sim_note"))}</span></div>
    </div>`;
  }).join("");
  const open = (S.tickets || []).filter((x) => x.status === "open");
  const strip = open.length ? `<div class="card"><h3>${esc(t("working"))}</h3>` + open.map((x) =>
    `<div class="metric"><span>${esc(x.title.slice(0, 72))}</span><b class="badge warn">${esc(x.kind)}</b></div>`).join("") + `</div>` : "";
  return viewHead("cockpit", acts) + `<div class="scroll grid" style="align-content:start">
    <div class="grid c3">${cards}</div>${strip}</div>`;
}

/* ---------------------------------------------------------------- tickets */
function stageBadge(x) {
  if (x.status === "ended") {
    const o = x.outcome || "ended";
    return `<span class="badge ${o === "ready" ? "ok" : o === "stopped" ? "info" : "bad"}">${esc(o)}</span>`;
  }
  const st = x.latest_report ? x.latest_report.state : "queued";
  return `<span class="badge ${st === "blocked" || st === "failed" ? "bad" : "warn"}">${esc(st)}</span>`;
}
function viewTickets() {
  const list = (S.tickets || []);
  if (!SEL && list.length) SEL = list[0].id;
  const rows = list.length ? list.map((x) => `
    <div class="ticket ${SEL === x.id ? "sel" : ""}" data-act="select-ticket" data-id="${x.id}">
      <div><div class="title">${esc(x.title)}</div>
        <div class="meta"><span>${esc(x.id)}</span><span>${esc(x.kind)}</span><span>${esc(x.thread_key)}</span>
          <span>policy v${esc(x.policy_version)}</span><span>${esc(ago(x.created_at))} ago</span></div></div>
      <div class="right">${stageBadge(x)}</div>
    </div>`).join("") : `<div class="empty">${esc(t("no_tickets"))}</div>`;
  return viewHead("tickets") + `<div class="split" style="flex:1;min-height:0">
    <div class="scroll"><div class="ticketlist">${rows}</div></div>
    <div class="scroll">${ticketDetail()}</div></div>`;
}
function ticketDetail() {
  const x = (S.tickets || []).find((y) => y.id === SEL);
  if (!x) return `<div class="empty">${esc(t("select_hint"))}</div>`;
  const m = x.mandate || {};
  const rep = x.latest_report;
  const asg = (x.assignments || [])[0] || {};
  const acts = `<div style="display:flex;gap:6px;margin-bottom:8px">
      ${x.status === "open" ? `<button class="btn danger tiny" data-act="stop" data-id="${x.id}">${esc(t("stop"))}</button>` : ""}
      ${rep && ["blocked", "failed"].includes(rep.state) ? `<button class="btn tiny" data-act="retry" data-id="${x.id}">${esc(t("retry"))}</button>` : ""}
      <button class="btn tiny" data-act="resume" data-id="${x.id}">${esc(t("resume_t"))}</button></div>`;
  const artifacts = (x.artifacts || []).map((f) =>
    `<button class="btn tiny" data-act="view-file" data-id="${x.id}" data-name="${esc(f.name)}">${esc(f.name)} <span class="hint">${f.bytes}B</span></button>`).join(" ") || `<span class="hint">—</span>`;
  const steps = (x.steps || []).map((s) =>
    `<div><span class="tool">${esc(s.tool || "step")}</span> ${s.error ? `<span style="color:var(--danger)">${esc(s.error)}</span>` : esc(s.summary || "")}</div>`).join("") || `<div class="hint">—</div>`;
  const inputs = (x.inputs || []).slice(-4).map((i) =>
    `<div class="hint">· [${esc(i.kind)}] ${esc(i.text.slice(0, 130))} ${i.delivered ? "" : `<span class="badge warn">pending</span>`}</div>`).join("") || `<span class="hint">—</span>`;
  return `<div class="detail">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
      <div><div style="font-size:15px">${esc(x.title)}</div>
        <div class="hint mono">${esc(x.id)} · ${esc(x.thread_key)}</div></div>${stageBadge(x)}</div>
    ${acts}
    ${rep && rep.question ? `<div class="warnbox"><b>${esc(t("ask"))}:</b> ${esc(rep.question)}</div>` : ""}
    ${rep ? `<div class="card"><h4>${esc(t("report"))}</h4><div>${esc(rep.summary)}</div>
      <div class="hint mono" style="margin-top:6px">${esc(rep.state)} · ${esc(rep.at)}</div></div>` : ""}
    <div class="card"><h4>${esc(t("mandate"))}</h4>
      <dl class="kv">
        <dt>policy</dt><dd>v${esc(m.policy_version)} · ${esc(short(m.policy_hash, 18))}</dd>
        <dt>${esc(t("strength"))}</dt><dd>${esc(m.strength)} · ${esc(m.via)}</dd>
        <dt>${esc(t("rule"))}</dt><dd>${esc(m.rule || "—")}</dd>
        <dt>${esc(t("scope"))}</dt><dd>${esc((x.scope || []).join(" · ") || "—")}</dd>
      </dl></div>
    <div class="card"><h4>assignment</h4>
      <dl class="kv"><dt>attempts</dt><dd>${esc(asg.attempts ?? "—")}</dd>
        <dt>status</dt><dd>${esc(asg.status ?? "—")}</dd>
        <dt>heartbeat</dt><dd>${esc(asg.heartbeat_at ? ago(asg.heartbeat_at) + " ago" : "—")}</dd></dl></div>
    <div class="card"><h4>${esc(t("steps"))}</h4><div class="steps">${steps}</div></div>
    <div class="card"><h4>${esc(t("inputs"))}</h4>${inputs}</div>
    <div class="card"><h4>${esc(t("artifacts"))}</h4><div style="display:flex;gap:6px;flex-wrap:wrap">${artifacts}</div></div>
  </div>`;
}

/* ---------------------------------------------------------------- ledger */
function viewLedger() {
  const batches = S.ledger || [];
  const rows = batches.map((b) => {
    const bt = b.batch, tot = b.total;
    const s2 = (b.entries || []).filter((e) => String(e.scope).startsWith("scope2")).reduce((a, e) => a + e.kgco2e, 0);
    const s3 = (b.entries || []).filter((e) => String(e.scope).startsWith("scope3")).reduce((a, e) => a + e.kgco2e, 0);
    const total = (s2 + s3) || (tot ? tot.kgco2e : 1);
    const pct = (v) => Math.max(2, Math.min(100, (v / total) * 100));
    const chain = (b.entries || []).map((e) => `<tr>
        <td>${esc(e.scope)}</td><td>${num(e.kgco2e, 3)}</td><td>${esc(e.factor_id)}</td>
        <td class="hash" title="${esc(e.hash)}">${esc(short(e.hash, 20))}</td></tr>`).join("");
    return `<div class="batch">
      <div class="head"><b>${esc(bt.id)}</b><span class="hint">${esc(bt.name)}</span>
        <span class="badge ${b.verify.ok ? "ok" : "bad"}">${b.verify.ok ? t("verified") : t("broken")} · ${b.verify.checked}</span>
        <span class="badge">${esc(bt.region)} · ${num(bt.kg_green, 1)} kg</span>
        <span class="tot">${tot ? num(tot.kgco2e, 1) : "—"} kgCO₂e</span></div>
      <div class="hint mono">${num(bt.kwh, 0)} kWh · ${num(bt.water_l, 0)} L · ${esc(bt.harvest_at)} · ${tot ? num(tot.factor_value, 3) : "—"} kgCO₂e/kg · doc ${short((tot && tot.note || "").split("doc_hash=")[1], 16)}</div>
      <div class="bars">
        <div class="bar"><span>scope 2</span><span class="track"><span class="fill s2" style="width:${pct(s2)}%"></span></span><span>${num(s2, 2)}</span></div>
        <div class="bar"><span>scope 3</span><span class="track"><span class="fill s3" style="width:${pct(s3)}%"></span></span><span>${num(s3, 2)}</span></div>
      </div>
      <table class="chain"><thead><tr><th>${esc(t("chain"))}</th><th>kgCO₂e</th><th>factor</th><th>hash</th></tr></thead><tbody>${chain}</tbody></table>
      <div style="display:flex;gap:6px;margin-top:8px">
        <button class="btn tiny" data-act="recompute" data-batch="${esc(bt.id)}">${esc(t("recompute"))}</button>
        <button class="btn tiny" data-act="export" data-batch="${esc(bt.id)}" data-fmt="pdf">PDF</button>
        <button class="btn tiny" data-act="export" data-batch="${esc(bt.id)}" data-fmt="zip">Zenodo zip</button>
        <span class="hint">${esc(t("ledger_p"))}</span></div>
    </div>`;
  }).join("");
  return viewHead("ledger") + `<div class="scroll"><div class="batches">${rows || `<div class="empty">—</div>`}</div></div>`;
}

/* ---------------------------------------------------------------- dossier */
function viewDossier() {
  const d = S.dossier || {};
  const factors = S.factors || {};
  const rows = Object.entries(factors).map(([id, f]) => `<tr>
      <td class="mono">${esc(id)}</td><td class="mono">${esc(f.value)} ${esc(f.unit)}</td>
      <td>${esc(LANG === "zh" ? f.label_zh : f.label_en)}</td>
      <td><span class="badge ${f.status === "unverified" ? "warn" : "ok"}">${esc(f.status)}</span></td></tr>`).join("");
  return viewHead("dossier") + `<div class="scroll grid" style="align-content:start">
    <div class="warnbox"><b>${esc(t("warning"))}:</b> ${esc(d.status || "")} — no third-party verification, no accreditation, no registry issuance. Do not cite these numbers in an external carbon label.</div>
    <div class="grid c2">
      <div class="card md"><h1>${esc(d.id)} ${esc(d.version)}</h1>
        <dl class="kv"><dt>hash</dt><dd>${esc(d.hash || "—")}</dd>
          <dt>published</dt><dd>${esc(d.published_at || "—")}</dd>
          <dt>boundary</dt><dd>${esc(d.boundary || "—")}</dd>
          <dt>functional unit</dt><dd>${esc(d.functional_unit || "—")}</dd>
          <dt>GWP</dt><dd>${esc(d.gwp_set || "—")}</dd></dl>
      </div>
      <div class="card md"><h2>${esc(t("factors"))}</h2>
        <table><thead><tr><th>id</th><th>value</th><th>label</th><th>status</th></tr></thead><tbody>${rows}</tbody></table></div>
    </div>
    <div class="grid c2">
      <div class="card md"><h2>Rules</h2><ul>${(d.rules || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
      <div class="card md"><h2>Invalidated when</h2><ul>${(d.invalidated_when || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
    </div>
  </div>`;
}

/* ---------------------------------------------------------------- audit */
function viewAudit() {
  const h = S.health || {};
  const ev = (S.events || []).slice(0, 60).map((e) => {
    const hot = /report.recorded|ticket.ended|attention|interrupted/.test(e.kind);
    const warm = /trigger.received|ticket.created|worker.step/.test(e.kind);
    return `<div class="row ${hot ? "hot" : warm ? "warm" : ""}">
      <span class="sub">${esc((e.at || "").slice(11, 19))}</span>
      <span class="kind">${esc(e.kind)}</span>
      <span>${esc(short(e.subject, 34))} <span class="sub">${esc(JSON.stringify(e.data).slice(0, 120))}</span></span></div>`;
  }).join("");
  const ob = (S.outbox || []).slice(0, 8).map((o) =>
    `<div><span>${esc(o.channel)}</span><span>${esc(short(o.ticket_id, 18))} · ${esc(o.status)}</span></div>`).join("");
  const rules = (S.rules || []).map((r) =>
    `<div><span>${esc(r.id)}</span><span>${esc(r.outcome)} · ${esc(r.strength)} · ${r.enabled ? "on" : "off"}</span></div>`).join("");
  return viewHead("audit", `<button class="btn" data-act="toggle-pause">${esc(S.status.paused ? t("resume") : t("pause"))}</button>
      <button class="btn" data-act="refresh">refresh</button>`) +
    `<div class="scroll grid c2" style="align-content:start">
      <div class="card"><h3>${esc(t("health"))}</h3><div class="health">
        <div><span>passes</span><span>${esc(h.passes ?? 0)}</span></div>
        <div><span>last pass</span><span>${esc(h.last_pass_at ? ago(h.last_pass_at) + " ago" : "—")}</span></div>
        <div><span>effects done / failed</span><span>${esc(h.effects_done ?? 0)} / ${esc(h.effects_failed ?? 0)}</span></div>
        <div><span>watchdog interrupts</span><span>${esc(h.watchdog_interrupts ?? 0)}</span></div>
        <div><span>sim ticks</span><span>${esc(h.sim_ticks ?? 0)}</span></div>
        <div><span>uptime</span><span>${esc(S.status.uptime_s)}s</span></div>
        <div><span>effects pending</span><span>${esc(S.counts.effects_pending)}</span></div>
      </div>
      ${(h.errors || []).length ? `<div class="warnbox" style="margin-top:8px">${esc(h.errors[h.errors.length - 1].error)}</div>` : ""}
      <h3 style="margin-top:12px">${esc(t("outbox"))}</h3><div class="health">${ob || `<div><span>—</span></div>`}</div>
      </div>
      <div class="card"><h3>${esc(t("policy"))} · ${esc(t("count_triggers"))} ${S.counts.triggers} · ${esc(t("count_decisions"))} ${S.counts.decisions}</h3>
        <div class="health">${rules}</div>
        <div style="display:flex;gap:6px;margin-top:10px;align-items:center;flex-wrap:wrap">
          <label class="hint">mode
            <select id="policy-mode" class="btn tiny">
              <option value="auto" ${S.policy.mode === "auto" ? "selected" : ""}>auto (accept inferred)</option>
              <option value="record" ${S.policy.mode === "record" ? "selected" : ""}>record (record only)</option>
            </select></label>
          <label class="hint">watchdog
            <input id="watchdog" type="number" min="10" max="600" value="${esc(S.status.watchdog_stale_s)}" style="width:68px;background:var(--surface);border:1px solid #333639;border-radius:10px;padding:4px 8px"></label>
          <button class="btn tiny primary" data-act="save-policy">save</button>
        </div>
      </div>
      <div class="card" style="grid-column:1/-1"><h3>${esc(t("events"))}</h3><div class="timeline">${ev || `<div class="empty">—</div>`}</div></div>
    </div>`;
}

/* ---------------------------------------------------------------- feishu */
function viewFeishu() {
  const f = S.feishu || {};
  const c = f.config || {};
  const pol = (f.policy && f.policy.allow) || [];
  const counters = f.counters || {};
  const cmdRows = Object.entries(f.commands || {}).map(([k, v]) =>
    `<div><span>${esc(k)}</span><span class="hint">${esc(v)}</span></div>`).join("");
  const evRows = (f.events || []).map((e) => {
    const allowed = pol.includes(e.actor);
    return `<div class="row ${e.handled === "error" ? "hot" : ""}">
      <span class="sub">${esc((e.at || "").slice(11, 19))}</span>
      <span class="kind">${esc(e.actor)}</span>
      <span>${esc((e.text || "").slice(0, 80))} <span class="sub">${esc(e.handled)}</span>
        ${allowed ? "" : `<button class="btn tiny" data-act="fs-allow" data-actor="${esc(e.actor)}">${esc(t("fs_allow_add"))}</button>`}</span></div>`;
  }).join("");
  const outRows = (f.out || []).map((o) => {
    let body = o.body, kindLabel = o.kind;
    try {
      const parsed = JSON.parse(o.body);
      if (parsed && parsed.card) {
        body = (parsed.card.header && parsed.card.header.title && parsed.card.header.title.content) || "(card)";
        kindLabel = "card";
      } else if (parsed && parsed.file_key) {
        body = "file " + (parsed.name || parsed.file_key.slice(0, 12));
        kindLabel = "file";
      } else {
        body = parsed.text || "";
      }
    } catch (_) { /* plain body */ }
    return `<div><span>${esc((o.at || "").slice(11, 19))} · ${esc(kindLabel)}</span>
      <span title="${esc(o.chat_id)}">${esc(String(body).slice(0, 100))} · ${esc(o.status)}</span></div>`;
  }).join("");
  const webhook = (typeof location !== "undefined" && location.origin ? location.origin : "") + "/api/feishu/events";
  return viewHead("feishu", `<button class="btn" data-act="fs-sim-quick" data-text="/status">/status</button>
      <button class="btn" data-act="fs-sim-quick" data-text="/ledger B-2026-11">/ledger</button>
      <button class="btn" data-act="refresh">refresh</button>`) +
  `<div class="scroll grid" style="align-content:start">
    <div class="grid c3">
      <div class="card"><h3>${esc(t("fs_cfg"))}</h3><dl class="kv">
        <dt>${esc(t("fs_transport"))}</dt><dd>${esc(c.transport)} ${c.app_id_set ? "· app_id set" : "· no app_id"}</dd>
        <dt>${esc(t("fs_webhook"))}</dt><dd>${esc(webhook)}</dd>
        <dt>signature</dt><dd>${c.encrypt_key_set ? "on" : "off (no encrypt key)"}</dd>
        <dt>verification token</dt><dd>${c.verification_token_set ? "on" : "off"}</dd>
        <dt>in / out / refused</dt><dd>${esc(counters.inbound ?? 0)} / ${esc(counters.outbound ?? 0)} / ${esc(counters.refused ?? 0)}</dd>
        <dt>${esc(t("fs_poll"))}</dt><dd>${f.poll && f.poll.started_at ? `on · ${esc(c.poll_interval_s)}s · ${esc(counters.poll_cycles ?? 0)} cycles · ${esc(counters.poll_messages ?? 0)} msgs` : "off"}</dd>
        <dt>chats</dt><dd>${esc((f.poll && f.poll.chats || []).join(", ") || "—")}</dd>
      </dl>
      ${f.poll && f.poll.last_error ? `<div class="warnbox" style="margin-top:8px">${esc(f.poll.last_error)}</div>` : ""}
      ${c.encrypt_key_set ? `<div class="warnbox" style="margin-top:8px">${esc(t("fs_warn_enc"))}</div>` : ""}
      ${!c.verification_token_set ? `<div class="warnbox" style="margin-top:8px">${esc(t("fs_warn_token"))}</div>` : ""}
      </div>
      <div class="card"><h3>${esc(t("fs_allow"))}</h3>
        <div style="display:flex;gap:6px;flex-wrap:wrap">${pol.map((a) => `<span class="badge info mono">${esc(a)}</span>`).join("") || `<span class="hint">—</span>`}</div>
        <p class="hint" style="margin-top:8px">身份按 Source 隔离：飞书 open_id 只在这条 Source 上有效，永远不会被映射成面板账号。白名单在 policy.sources.feishu.allow。</p>
      </div>
      <div class="card"><h3>${esc(t("fs_commands"))}</h3><div class="health">${cmdRows}</div></div>
    </div>
    <div class="card"><h3>${esc(t("fs_sim"))}</h3>
      <p class="hint">${esc(t("fs_hint"))}</p>
      <div class="chips" style="margin-bottom:8px">
        ${(t("fs_quick") || []).map((x) => `<button class="chip" data-act="fs-chip" data-text="${esc(x)}">${esc(x)}</button>`).join("")}
      </div>
      <div class="composer" style="grid-template-columns:1fr 130px 150px auto">
        <input id="fs-text" placeholder="/status 或一句话请求" style="background:var(--surface);border:1px solid #333639;border-radius:14px;padding:9px 12px">
        <input id="fs-chat" value="oc_sim_demo" title="${esc(t("fs_chat"))}" style="background:var(--surface);border:1px solid #333639;border-radius:14px;padding:9px 12px;font-family:var(--mono);font-size:12px">
        <input id="fs-actor" value="ou_sim_erik" title="${esc(t("fs_actor"))}" style="background:var(--surface);border:1px solid #333639;border-radius:14px;padding:9px 12px;font-family:var(--mono);font-size:12px">
        <button class="btn primary" data-act="fs-sim">${esc(t("fs_send"))}</button>
      </div>
    </div>
    <div class="grid c2">
      <div class="card"><h3>${esc(t("fs_in"))}</h3><div class="timeline">${evRows || `<div class="empty">—</div>`}</div></div>
      <div class="card"><h3>${esc(t("fs_out"))}</h3><div class="health">${outRows || `<div>—</div>`}</div></div>
    </div>
  </div>`;
}

/* ---------------------------------------------------------------- modal */
function drawModal() {
  let host = $("#modal");
  if (!host) {
    host = document.createElement("div");
    host.id = "modal";
    host.className = "modal";
    host.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <h3 style="margin:0" id="modal-title"></h3><button class="btn tiny" data-act="close-modal">close</button></div>
      <pre class="file" id="modal-body"></pre></div>`;
    document.body.appendChild(host);
    host.addEventListener("click", (e) => { if (e.target === host) closeModal(); });
  }
  $("#modal-title").textContent = MODAL.name;
  $("#modal-body").textContent = MODAL.text;
}
function closeModal() {
  MODAL = null;
  const m = $("#modal");
  if (m) m.remove();
}
async function openFile(id, name) {
  try {
    const r = await apiFetch(`/api/ticket/${encodeURIComponent(id)}/file?name=${encodeURIComponent(name)}`);
    if (!r.ok) throw new Error(r.status);
    MODAL = { name, text: await r.text() };
    drawModal();
  } catch (e) { toast("cannot read file: " + e.message, true); }
}

/* ---------------------------------------------------------------- actions */
async function act(name, d, el) {
  switch (name) {
    case "nav": APP = d.app; localStorage.setItem("cosa.app", APP); render(); break;
    case "lang": LANG = LANG === "zh" ? "en" : "zh"; localStorage.setItem("cosa.lang", LANG);
      if (MODAL) closeModal(); render(); break;
    case "skip-boot": skipBoot(); break;
    case "toggle-pause": await post("/api/policy", { paused: !S.status.paused }); break;
    case "inject": { const j = await post("/api/demo/anomaly", { cabin: d.cabin }); if (j) toast(`${d.cabin}: drift injected → trigger`); break; }
    case "harvest": { const j = await post("/api/demo/harvest", {}); if (j) toast("harvest trigger queued"); break; }
    case "factor": { const j = await post("/api/demo/factor", { region: "CN" }); if (j) toast("factor.updated queued"); break; }
    case "chip": { const c = $("#composer"); if (c) c.value = d.text; DRAFT = d.text; break; }
    case "select-ticket": SEL = d.id; if (APP !== "tickets") { APP = "tickets"; localStorage.setItem("cosa.app", APP); } render(); break;
    case "stop": if (await post(`/api/tickets/${d.id}/stop`, { reason: "stopped from the panel" })) toast("ticket stopped"); break;
    case "retry": if (await post(`/api/tickets/${d.id}/retry`, {})) toast("retry queued"); break;
    case "resume": if (await post(`/api/tickets/${d.id}/resume`, { text: "Continue: finish the work and write the result into the ticket directory." })) toast("ticket resumed"); break;
    case "view-file": await openFile(d.id, d.name); break;
    case "close-modal": closeModal(); break;
    case "export": {
      try {
        const r = await apiFetch(`/api/export/batch/${encodeURIComponent(d.batch)}.${d.fmt === "zip" ? "zip" : "pdf"}`);
        if (!r.ok) throw new Error(r.status);
        const blob = await r.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${d.batch}${d.fmt === "zip" ? "-zenodo" : "-footprint"}.${d.fmt === "zip" ? "zip" : "pdf"}`;
        document.body.appendChild(a); a.click(); a.remove();
        toast("导出完成：" + a.download);
      } catch (e) { toast("导出失败：" + e.message, true); }
      break;
    }
    case "recompute": if (await post(`/api/ledger/${d.batch}/recompute`, {})) toast("revision appended"); break;
    case "refresh": refresh(); break;
    case "change-token": {
      localStorage.removeItem(TOKEN_KEY);
      location.reload();
      break;
    }
    case "fs-allow": {
      const r = await post("/api/feishu/allow", { actor: d.actor });
      if (r) toast(r.added ? `policy v${r.version} · 已加入 ${d.actor}` : `已在白名单（policy v${r.version}）`);
      break;
    }
    case "fs-chip": { const el2 = $("#fs-text"); if (el2) el2.value = d.text; break; }
    case "fs-sim-quick": { const el2 = $("#fs-text"); if (el2) el2.value = d.text; await act("fs-sim", d, el); break; }
    case "fs-sim": {
      const text = ($("#fs-text") && $("#fs-text").value || "").trim();
      if (!text) { toast("输入一条飞书消息", true); break; }
      const r = await post("/api/feishu/simulate", {
        text, chat_id: ($("#fs-chat").value || "oc_sim_demo").trim(),
        actor: "feishu:" + (($("#fs-actor").value || "ou_sim_erik").trim().replace(/^feishu:/, ""))
      });
      if (r) toast("→ " + (r.status === 200 ? "accepted" : "status " + r.status));
      setTimeout(refresh, 800); setTimeout(refresh, 2200);
      break;
    }
    case "save-policy": {
      const mode = $("#policy-mode").value;
      const wd = Number($("#watchdog").value) || 90;
      const j = await post("/api/policy", { mode, watchdog_stale_s: wd });
      if (j) toast(`policy v${j.version} · ${j.notified_tickets} tickets notified`);
      break;
    }
  }
}

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || el.tagName === "FORM") return;
  e.preventDefault();
  act(el.dataset.act, el.dataset, el);
});
document.addEventListener("submit", async (e) => {
  const form = e.target.closest("form[data-act='send']");
  if (!form) return;
  e.preventDefault();
  const ta = $("#composer");
  const text = (ta.value || "").trim();
  if (!text) return;
  ta.value = ""; DRAFT = "";
  const j = await post("/api/console", { text });
  if (j) toast("→ trigger " + short(j.trigger_id, 12));
  setTimeout(refresh, 900); setTimeout(refresh, 2600);
});
document.addEventListener("input", (e) => {
  if (e.target.id === "composer") DRAFT = e.target.value;
});
document.addEventListener("focusout", (e) => {
  if (e.target.closest("#main") && PENDING_RENDER) render();
});

boot();
connect();
refresh();
setInterval(refresh, 4000);
setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString("en-GB"); }, 1000);

// if nothing rendered after 6s, say why instead of leaving a blank page
setTimeout(() => {
  if (S) return;
  const m = $("#main");
  if (!m || m.innerHTML.indexOf("loading") === -1) return;
  m.innerHTML = `<div class="card" style="max-width:720px;margin:24px auto">
    <h3>还没连上内核 · no snapshot yet</h3>
    <p class="hint">令牌：${token() ? "已保存（…" + token().slice(-4) + "）" : "未保存"}。
    服务：<code>http://127.0.0.1:8787/api/health</code> 应返回 <code>{"ok":true}</code>。</p>
    <p class="hint">如果浏览器控制台（F12）有红色报错，把第一行发我即可。</p>
    <div style="display:flex;gap:8px;margin-top:8px">
      <button class="btn primary" data-act="refresh">retry</button>
      <button class="btn" data-act="change-token">换令牌</button>
    </div></div>`;
}, 6000);
