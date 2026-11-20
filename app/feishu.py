"""Feishu (Lark) bridge — the Source that lets a team drive the kernel from chat.

    inbound   POST /api/feishu/events   verify -> dedupe -> command or Trigger
    outbound  report.recorded           ready / blocked / failed -> the originating chat

Two transports, one code path:

    api  real open platform (tenant_access_token + im/v1/messages)
    sim  no credentials: every outbound message is written to `feishu_out`,
         and the webhook can be driven from /api/feishu/simulate

Design rules borrowed from dsh-superagent/docs/001-domain.md:

* a Trigger carries the actor **as this Source names it**; Feishu open_ids are
  never mapped onto panel identities, the allowlist lives in `policy.sources.feishu`;
* the bridge may read, but it may not write Tickets — it only calls
  `engine.intake()` or a person-action (`stop`, `retry`, `policy`);
* every outbound message has one row in `feishu_out`, so a person can see
  exactly what the bot said on their behalf.

Feishu encryption (AES-256-CBC body) is NOT implemented: stdlib has no AES.
Set `FEISHU_ENCRYPT_KEY` empty in the app console, or put a proxy in front.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

from store import Store, dumps, loads, new_id, utcnow

FEISHU_BASE = os.environ.get("FEISHU_BASE", "https://open.feishu.cn")
WEBHOOK_PATH = "/api/feishu/events"


class FeishuError(RuntimeError):
    pass


class FeishuConfig:
    def __init__(self):
        self.app_id = os.environ.get("FEISHU_APP_ID", "").strip()
        self.app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        self.verification_token = os.environ.get("FEISHU_VERIFICATION_TOKEN", "").strip()
        self.encrypt_key = os.environ.get("FEISHU_ENCRYPT_KEY", "").strip()
        self.allow = [x.strip() for x in os.environ.get("FEISHU_ALLOW", "").split(",") if x.strip()]
        force_sim = os.environ.get("COSA_FEISHU_SIM", "").strip() in ("1", "true", "yes")
        self.sim = force_sim or not (self.app_id and self.app_secret)
        self.default_chat = os.environ.get("FEISHU_DEFAULT_CHAT", "").strip()
        # Polling is the no-public-IP path: we read the chat history instead of receiving callbacks.
        self.poll = os.environ.get("FEISHU_POLL", "1").strip() not in ("0", "false", "no")
        self.poll_interval = float(os.environ.get("FEISHU_POLL_INTERVAL", "5") or 5)
        self.poll_chats = [x.strip() for x in os.environ.get("FEISHU_POLL_CHATS", "").split(",") if x.strip()]
        self.upload = os.environ.get("FEISHU_UPLOAD", "1").strip() not in ("0", "false", "no")
        self.upload_max_kb = int(os.environ.get("FEISHU_UPLOAD_MAX_KB", "200") or 200)
        self.upload_max_files = int(os.environ.get("FEISHU_UPLOAD_MAX_FILES", "3") or 3)

    @property
    def transport(self) -> str:
        return "sim" if self.sim else "api"

    def describe(self) -> dict:
        return {
            "transport": self.transport,
            "app_id_set": bool(self.app_id),
            "verification_token_set": bool(self.verification_token),
            "encrypt_key_set": bool(self.encrypt_key),
            "verify_enforced": bool(self.verification_token) or bool(self.encrypt_key),
            "allow_env": self.allow,
            "webhook_path": WEBHOOK_PATH,
            "default_chat_set": bool(self.default_chat),
            "poll_enabled": bool(self.poll and not self.sim),
            "poll_interval_s": self.poll_interval,
            "poll_chats_env": self.poll_chats,
            "upload_enabled": bool(self.upload and not self.sim),
            "upload_max_kb": self.upload_max_kb,
            "upload_max_files": self.upload_max_files,
        }


class FeishuClient:
    """Minimal open-platform client: tenant token + send one message."""

    def __init__(self, cfg: FeishuConfig):
        self.cfg = cfg
        self._token = ""
        self._expire_at = 0.0
        self._lock = threading.Lock()

    def _request(self, url: str, payload: dict, token: str | None = None, method: str = "POST") -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if method != "GET" else None
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise FeishuError(f"HTTP {exc.code}: {raw[:300]}")
        except urllib.error.URLError as exc:
            raise FeishuError(f"network: {exc.reason}")

    def token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expire_at:
                return self._token
            url = f"{FEISHU_BASE}/open-apis/auth/v3/tenant_access_token/internal"
            data = self._request(url, {"app_id": self.cfg.app_id, "app_secret": self.cfg.app_secret})
            if data.get("code") != 0:
                raise FeishuError(f"tenant_access_token: {data.get('code')} {data.get('msg')}")
            self._token = data["tenant_access_token"]
            self._expire_at = time.time() + max(60, int(data.get("expire", 7200)) - 120)
            return self._token

    def send(self, chat_id: str, msg_type: str, content: dict) -> dict:
        url = f"{FEISHU_BASE}/open-apis/im/v1/messages?receive_id_type=chat_id"
        data = self._request(
            url,
            {"receive_id": chat_id, "msg_type": msg_type, "content": json.dumps(content, ensure_ascii=False)},
            token=self.token(),
        )
        if data.get("code") != 0:
            raise FeishuError(f"send: {data.get('code')} {data.get('msg')}")
        return data

    def send_text(self, chat_id: str, text: str) -> dict:
        return self.send(chat_id, "text", {"text": text[:4000]})

    def send_card(self, chat_id: str, card: dict) -> dict:
        return self.send(chat_id, "interactive", card)

    def upload_file(self, path: str, file_name: str | None = None) -> str:
        """Upload one file as `stream` and return its file_key (im:resource)."""
        name = file_name or os.path.basename(path)
        with open(path, "rb") as f:
            blob = f.read()
        boundary = "----cosa" + uuid.uuid4().hex
        parts: list[bytes] = []
        for field, value in (("file_type", "stream"), ("file_name", name)):
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n{value}\r\n".encode())
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n".encode() + blob + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        url = f"{FEISHU_BASE}/open-apis/im/v1/files"
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                     "Authorization": f"Bearer {self.token()}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            raise FeishuError(f"upload: HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}")
        if data.get("code") != 0:
            raise FeishuError(f"upload: {data.get('code')} {data.get('msg')}")
        return (data.get("data") or {}).get("file_key") or ""

    def send_file(self, chat_id: str, file_key: str) -> dict:
        return self.send(chat_id, "file", {"file_key": file_key})

    # ------------------------------------------------------------ polling reads
    def chats(self) -> list[dict]:
        d = self._request(f"{FEISHU_BASE}/open-apis/im/v1/chats?page_size=50", {}, token=self.token(),
                          method="GET")
        if d.get("code") != 0:
            raise FeishuError(f"chats: {d.get('code')} {d.get('msg')}")
        return (d.get("data") or {}).get("items") or []

    def history(self, chat_id: str, start_time: int, page_size: int = 20) -> list[dict]:
        q = (f"{FEISHU_BASE}/open-apis/im/v1/messages?container_id_type=chat&container_id={chat_id}"
             f"&start_time={start_time}&sort_type=ByCreateTimeAsc&page_size={page_size}")
        d = self._request(q, {}, token=self.token(), method="GET")
        if d.get("code") != 0:
            raise FeishuError(f"history: {d.get('code')} {d.get('msg')}")
        return (d.get("data") or {}).get("items") or []


class FeishuBridge:
    COMMANDS = {
        "/help": "列出可用指令",
        "/status": "内核状态：模式、策略版本、在办工单、待你决定",
        "/tickets": "在办工单列表",
        "/ticket <id>": "一张工单的授权与报告",
        "/ledger [batch]": "碳账本总量、强度与链头",
        "/dossier": "方法学版本与哈希（含不可对外声明）",
        "/anomaly <cabin>": "注入一次环境漂移（A1/B2/C3）",
        "/harvest [batch]": "记录一次采收，触发核算",
        "/stop <id>": "停止工单（人的动作，撤授权）",
        "/retry <id>": "重试阻塞/失败的工单",
        "/pause | /resume": "暂停/恢复内核",
        "（任意文字）": "当作一个人的请求，交给 Router 判断",
    }

    def __init__(self, runtime):
        self.rt = runtime
        self.store: Store = runtime.store
        self.engine = runtime.engine
        self.policy = runtime.policy
        self.cfg = FeishuConfig()
        self.client = FeishuClient(self.cfg) if self.cfg.transport == "api" else None
        self._q: queue.Queue = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.counters = {"inbound": 0, "outbound": 0, "refused": 0, "errors": 0,
                         "poll_cycles": 0, "poll_messages": 0}
        self.last_error = ""
        self.poll_state: dict = {"chats": [], "last_cycle_at": None, "last_error": "",
                                 "started_at": None}

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._out_loop, daemon=True, name="feishu-out")
        self._thread.start()
        if self.cfg.poll and self.client:
            self.poll_state["started_at"] = utcnow()
            threading.Thread(target=self._poll_loop, daemon=True, name="feishu-poll").start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------ polling
    def _poll_loop(self) -> None:
        while not self._stop.wait(max(2.0, self.cfg.poll_interval)):
            try:
                self.poll_once()
            except Exception as exc:  # the poller must never kill the bridge
                self.counters["errors"] += 1
                self.poll_state["last_error"] = repr(exc)[:300]
                self.last_error = self.poll_state["last_error"]

    def poll_once(self) -> int:
        """Read new messages from the bot's chats. Fallback for a machine without a public URL."""
        if not self.client:
            return 0
        self.poll_state["last_error"] = ""
        chats = self.cfg.poll_chats or [c["chat_id"] for c in self._discover_chats()]
        self.poll_state["chats"] = chats
        seen = 0
        for chat_id in chats:
            key = f"feishu:last_seen:{chat_id}"
            row = self.store.q1("SELECT value FROM kv WHERE key=?", (key,))
            now_s = int(time.time())
            last = int(row["value"]) if row else now_s - 60
            if last >= now_s:  # a future cursor would make Feishu reject the window
                last = now_s - 60
            try:
                items = self.client.history(chat_id, last)
            except FeishuError as exc:
                # one chat without the history scope must not stop the others
                self.poll_state["last_error"] = str(exc)[:300]
                continue
            newest = last
            for it in items:
                if (it.get("sender") or {}).get("sender_type") == "app":
                    continue  # never answer ourselves
                if it.get("deleted"):
                    continue
                try:
                    body = json.loads((it.get("body") or {}).get("content") or "{}")
                except json.JSONDecodeError:
                    continue
                text = (body.get("text") or "").strip()
                if not text:
                    continue
                actor = "feishu:" + str((it.get("sender") or {}).get("id") or "unknown")
                payload = {
                    "schema": "2.0",
                    "header": {"event_id": it.get("message_id"), "event_type": "im.message.receive_v1",
                               "token": self.cfg.verification_token or "poll"},
                    "event": {"sender": {"sender_id": {"open_id": actor.split(":", 1)[-1]},
                                         "sender_type": (it.get("sender") or {}).get("sender_type", "user")},
                              "message": {"message_id": it.get("message_id"), "chat_id": chat_id,
                                          "chat_type": "group", "message_type": it.get("msg_type", "text"),
                                          "content": json.dumps({"text": text}, ensure_ascii=False)}},
                }
                code, resp = self._handle_message(payload, it.get("message_id") or "")
                if not resp.get("duplicate"):
                    seen += 1
                ts = int(it.get("create_time") or 0)
                while ts > 10 ** 11:  # Feishu gives milliseconds; the cursor is seconds
                    ts //= 1000
                newest = max(newest, ts or last)
            with self.store.tx() as c:
                c.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, str(newest)))
        self.counters["poll_cycles"] += 1
        self.counters["poll_messages"] += seen
        self.poll_state["last_cycle_at"] = utcnow()
        return seen

    def _discover_chats(self) -> list[dict]:
        row = self.store.q1("SELECT value FROM kv WHERE key='feishu:chats_cache'")
        cached = loads(row["value"], None) if row else None
        if cached and cached.get("at", 0) > time.time() - 300:
            return cached.get("items") or []
        try:
            items = self.client.chats()
        except FeishuError as exc:
            self.poll_state["last_error"] = str(exc)[:300]
            return []
        slim = [{"chat_id": c.get("chat_id"), "name": c.get("name"), "chat_mode": c.get("chat_mode")}
                for c in items if c.get("chat_id")]
        with self.store.tx() as c:
            c.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      ("feishu:chats_cache", dumps({"at": time.time(), "items": slim})))
        return slim

    # ------------------------------------------------------------ inbound
    def verify(self, headers: dict, raw: bytes) -> tuple[bool, str]:
        if not self.cfg.encrypt_key:
            return True, "no_signature_configured"
        ts = headers.get("x-lark-request-timestamp", "")
        nonce = headers.get("x-lark-request-nonce", "")
        sig = headers.get("x-lark-signature", "")
        if not (ts and nonce and sig):
            return False, "missing_signature_headers"
        expect = hashlib.sha256((ts + nonce + self.cfg.encrypt_key).encode("utf-8") + raw).hexdigest()
        if expect != sig:
            return False, "signature_mismatch"
        return True, "ok"

    def handle_webhook(self, headers: dict, raw: bytes, remote: str = "") -> tuple[int, dict]:
        started = time.time()
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            self._hit(remote, headers, {"error": "bad_json"}, started)
            return 400, {"error": f"bad json: {exc}"}
        self._hit(remote, headers, payload, started)
        if "encrypt" in payload:
            return 400, {"error": "encrypted callbacks are not supported by this build; "
                                  "clear the Encrypt Key in the Feishu console or use a proxy"}
        ok, why = self.verify(headers, raw)
        if not ok:
            return 403, {"error": why}
        if payload.get("type") == "url_verification":
            token = payload.get("token", "")
            if self.cfg.verification_token and token != self.cfg.verification_token:
                return 403, {"error": "verification token mismatch"}
            return 200, {"challenge": payload.get("challenge", "")}
        header = payload.get("header") or {}
        # v2 events carry the verification token in the header; check it for every callback,
        # otherwise anyone who learns the URL could forge a message from an allowlisted id.
        if self.cfg.verification_token:
            token = header.get("token") or payload.get("token") or ""
            if token != self.cfg.verification_token:
                return 403, {"error": "verification token mismatch"}
        event_type = header.get("event_type") or payload.get("type") or ""
        event_id = header.get("event_id") or ""
        if event_type != "im.message.receive_v1":
            return 200, {"ok": True, "ignored": event_type}
        return self._handle_message(payload, event_id)

    def _handle_message(self, payload: dict, event_id: str) -> tuple[int, dict]:
        ev = payload.get("event") or {}
        msg = ev.get("message") or {}
        sender = ev.get("sender") or {}
        msg_id = msg.get("message_id") or ""
        chat_id = msg.get("chat_id") or ""
        actor = "feishu:" + str((sender.get("sender_id") or {}).get("open_id") or "unknown")
        text = self._text_of(msg)
        dedupe = event_id or msg_id or new_id("fe")
        if self.store.q1("SELECT id FROM feishu_event WHERE id=?", (dedupe,)):
            return 200, {"ok": True, "duplicate": True}
        with self.store.tx() as c:
            c.execute("INSERT INTO feishu_event(id,at,event_type,msg_id,chat_id,actor,text,handled)"
                      " VALUES(?,?,?,?,?,?,?,?)",
                      (dedupe, utcnow(), "im.message.receive_v1", msg_id, chat_id, actor, text, "received"))
        self.counters["inbound"] += 1
        try:
            outcome = self._dispatch(chat_id, actor, text, msg_id, dedupe)
            with self.store.tx() as c:
                c.execute("UPDATE feishu_event SET handled=? WHERE id=?", (outcome, dedupe))
        except Exception as exc:  # a bridge error must be visible, never silent
            self.counters["errors"] += 1
            self.last_error = repr(exc)
            with self.store.tx() as c:
                c.execute("UPDATE feishu_event SET handled='error' WHERE id=?", (dedupe,))
            self._say(chat_id, f"处理失败：{exc}"[:400], kind="error")
        return 200, {"ok": True}

    def _hit(self, remote: str, headers: dict, payload: dict, started: float) -> None:
        """Record every callback we actually received — the only proof Feishu's probe arrived."""
        try:
            with self.store.tx() as c:
                c.execute("INSERT INTO event(at,kind,subject,data) VALUES(?,?,?,?)",
                          (utcnow(), "feishu.hit", remote or "?",
                           dumps({"type": payload.get("type") or (payload.get("header") or {}).get("event_type"),
                                  "remote": remote,
                                  "xff": headers.get("x-forwarded-for", ""),
                                  "cf": headers.get("cf-connecting-ip", ""),
                                  "ua": (headers.get("user-agent") or "")[:80],
                                  "ms": round((time.time() - started) * 1000, 1)})))
        except Exception:
            pass

    @staticmethod
    def _text_of(msg: dict) -> str:
        try:
            content = json.loads(msg.get("content") or "{}")
        except json.JSONDecodeError:
            return (msg.get("content") or "").strip()
        text = content.get("text") or ""
        for m in msg.get("mentions") or []:  # strip @bot prefixes
            key = m.get("key")
            if key:
                text = text.replace(key, " ")
        return " ".join(text.split())

    def _dispatch(self, chat_id: str, actor: str, text: str, msg_id: str, dedupe: str) -> str:
        if not self._allowed(actor):
            self.counters["refused"] += 1
            self._say(chat_id, "你的身份不在这个 Source 的白名单里（policy.sources.feishu.allow）。", kind="refused")
            return "refused"
        if not text:
            self._say(chat_id, "空消息。发 /help 看指令。", kind="help")
            return "empty"
        if text.startswith("/"):
            reply = self._command(chat_id, actor, text)
            if reply:
                self._say(chat_id, reply, kind="command")
            return "done"
        res = self.engine.intake(
            source="feishu", thread_key=f"feishu/chat-{chat_id}", kind="human.message",
            text=text, actor=actor, payload={"topic": text[:60], "chat_id": chat_id, "msg_id": msg_id},
            thread_label=f"Feishu {chat_id[-8:]}",
        )
        self._bind_chat(f"feishu/chat-{chat_id}", chat_id)
        if res["status"] == "fanned_out":
            self._say(chat_id, f"并入在办工单 {res['ticket_id']}，作为补充输入。", kind="accepted")
        else:
            self._say(chat_id, "已受理，Router 正在判断；有结论会回到这条会话。", kind="accepted")
        return "done"

    def _allowed(self, actor: str) -> bool:
        src = (self.policy.doc.get("sources") or {}).get("feishu") or {}
        allow = src.get("allow") or []
        return actor in allow

    def allow_actor(self, actor: str) -> dict:
        """Bootstrap the allowlist without editing code: a policy version records who was added.

        The operator sees a refused open_id in the panel, clicks once, and the next
        message from that person is admitted — with an auditable policy version.
        """
        actor = actor if actor.startswith("feishu:") else f"feishu:{actor}"
        cur = self.policy.doc
        sources = json.loads(json.dumps(cur.get("sources") or {}))
        feishu = sources.setdefault("feishu", {"enabled": True, "label": "Feishu (Lark)", "allow": []})
        allow = list(feishu.get("allow") or [])
        if actor in allow:
            return {"ok": True, "added": False, "version": cur["version"], "allow": allow}
        allow.append(actor)
        feishu["allow"] = allow
        row = self.policy.bump({"sources": sources})
        self.engine.policy_changed()
        return {"ok": True, "added": True, "version": row["version"], "allow": allow}

    # ------------------------------------------------------------ commands
    def _command(self, chat_id: str, actor: str, text: str) -> str:
        parts = text.split()
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd == "/help":
            lines = ["可用指令（中文说明）："]
            lines += [f"{k} — {v}" for k, v in self.COMMANDS.items()]
            return "\n".join(lines)
        if cmd == "/status":
            st = self.rt.snapshot()["status"]
            counts = self.rt.snapshot()["counts"]
            return (f"mode {st['mode']} · policy v{st['policy_version']} {st['policy_hash'][:8]} · "
                    f"paused={st['paused']}\n在办 {counts['open']} / 已结束 {counts['ended']} · "
                    f"待你决定 {counts['attention']} · 账本 {counts['ledger_rows']} 行")
        if cmd == "/tickets":
            rows = self.store.q("SELECT id,title,status,latest_report FROM ticket "
                                "ORDER BY created_at DESC LIMIT 8")
            if not rows:
                return "还没有工单。"
            out = []
            for r in rows:
                rep = loads(r["latest_report"], {}) or {}
                out.append(f"{r['id']} · {r['status']}/{rep.get('state', '-')} · {r['title'][:60]}")
            return "\n".join(out)
        if cmd == "/ticket":
            if not args:
                return "用法：/ticket tkt_xxx"
            t = self.engine.ticket(args[0])
            if not t:
                return f"没有这张工单：{args[0]}"
            m = t["mandate"]
            rep = t["latest_report"] or {}
            files = ", ".join(a["name"] for a in self._artifacts(t))
            return (f"{t['title']}\n状态 {t['status']} · 报告 {rep.get('state', '-')}\n"
                    f"授权 policy v{m.get('policy_version')} · {m.get('strength')} · rule {m.get('rule')}\n"
                    f"scope: {', '.join(t['scope'])}\n{(rep.get('summary') or '')[:600]}\n"
                    f"产物: {files or '—'}")
        if cmd == "/ledger":
            batch = args[0] if args else None
            import ledger as ledger_mod
            rows = self.store.q("SELECT * FROM batch" + (" WHERE id=?" if batch else ""),
                               (batch,) if batch else ())
            if not rows:
                return f"没有批次 {batch}"
            out = []
            for b in rows:
                last = self.store.q1("SELECT kgco2e,factor_value,hash,note FROM ledger_entry "
                                     "WHERE batch_id=? AND scope='total' ORDER BY id DESC LIMIT 1", (b["id"],))
                if not last:
                    out.append(f"{b['id']} · 尚未核算")
                else:
                    v = ledger_mod.verify(self.store, b["id"])
                    out.append(f"{b['id']} · {last['kgco2e']:.1f} kgCO₂e · "
                               f"{last['factor_value']:.3f}/kg · chain {'ok' if v['ok'] else 'BROKEN'} "
                               f"· head {last['hash'][:10]}")
            return "\n".join(out)
        if cmd == "/dossier":
            return self.rt.dossier_text()
        if cmd == "/anomaly":
            cabin = (args[0] if args else "A1").upper()
            if cabin not in ("A1", "B2", "C3"):
                return "用法：/anomaly A1|B2|C3"
            self.rt.inject_anomaly(cabin)
            return f"已向 {cabin} 注入一次漂移，等 Router 判断。"
        if cmd == "/harvest":
            res = self.rt.record_harvest(args[0] if args else None)
            self._bind_chat(f"field/batch-{args[0]}" if args else "field/batch-B-2026-11", chat_id)
            return f"采收事件已入队（{res.get('trigger_id')}）。"
        if cmd == "/stop":
            if not args:
                return "用法：/stop tkt_xxx"
            ok = self.engine.stop_ticket(args[0], reason=f"stopped from Feishu by {actor}")
            return "已停止。" if ok else "没有可停止的工单。"
        if cmd == "/retry":
            if not args:
                return "用法：/retry tkt_xxx"
            res = self.engine.retry_ticket(args[0])
            return "已重新派工。" if res else "只有开放的工单能重试。"
        if cmd in ("/pause", "/resume"):
            v = self.rt.set_policy({"paused": cmd == "/pause"})
            return f"kernel paused={v.get('paused')} · policy v{v['version']}"
        return f"未知指令 {cmd}。发 /help。"

    # ------------------------------------------------------------ outbound
    def _say(self, chat_id: str, text: str, kind: str = "message") -> None:
        self._enqueue(chat_id, kind, {"text": text})

    def _enqueue(self, chat_id: str, kind: str, body: dict) -> None:
        if not chat_id:
            chat_id = self.cfg.default_chat
        if not chat_id:
            return
        oid = new_id("fsm")
        simulated = bool(self.cfg.transport == "sim" or not self.client or chat_id.startswith("oc_sim"))
        with self.store.tx() as c:
            c.execute("INSERT INTO feishu_out(id,at,chat_id,kind,body,status) VALUES(?,?,?,?,?,?)",
                      (oid, utcnow(), chat_id, kind, dumps(body),
                       "simulated" if simulated else "queued"))
        self.counters["outbound"] += 1
        if not simulated:
            self._q.put(oid)

    def _out_loop(self) -> None:
        while not self._stop.wait(0.2):
            try:
                oid = self._q.get_nowait()
            except queue.Empty:
                continue
            self._deliver(oid)

    def _deliver(self, oid: str) -> None:
        row = self.store.q1("SELECT * FROM feishu_out WHERE id=?", (oid,))
        if not row or row["status"] == "sent":
            return
        body = loads(row["body"], {}) or {}
        if self.cfg.transport == "sim" or not self.client:
            with self.store.tx() as c:
                c.execute("UPDATE feishu_out SET status='simulated' WHERE id=?", (oid,))
            return
        try:
            # dispatch on the payload, not on the label: a card row is labelled `report:ready`
            if "card" in body:
                card = body.get("card") or {}
                try:
                    self.client.send_card(row["chat_id"], card)
                except Exception as card_exc:
                    # a rejected card must not cost the person the result:
                    # retry with a minimal card, then fall back to plain text
                    self.engine.emit("feishu.card_retry", row["ticket_id"] or "",
                                     {"error": str(card_exc)[:200]})
                    simple = {
                        "config": {"wide_screen_mode": True},
                        "header": card.get("header") or {"title": {"tag": "plain_text", "content": "result"}},
                        "elements": [{"tag": "div", "text": {
                            "tag": "lark_md", "content": (body.get("fallback") or "")[:1500]}}],
                    }
                    try:
                        self.client.send_card(row["chat_id"], simple)
                    except Exception:
                        self.client.send_text(row["chat_id"], (body.get("fallback") or "result ready")[:4000])
            elif "file_key" in body:
                self.client.send_file(row["chat_id"], body.get("file_key", ""))
            else:
                self.client.send_text(row["chat_id"], (body.get("text") or "")[:4000])
            with self.store.tx() as c:
                c.execute("UPDATE feishu_out SET status='sent' WHERE id=?", (oid,))
        except Exception as exc:
            self.counters["errors"] += 1
            self.last_error = repr(exc)
            with self.store.tx() as c:
                c.execute("UPDATE feishu_out SET status='failed', error=? WHERE id=?",
                          (repr(exc)[:300], oid))

    def _bind_chat(self, thread_key: str, chat_id: str) -> None:
        row = self.store.q1("SELECT meta FROM thread WHERE key=?", (thread_key,))
        meta = loads(row["meta"], {}) if row else {}
        if meta.get("feishu_chat_id") == chat_id:
            return
        meta["feishu_chat_id"] = chat_id
        with self.store.tx() as c:
            c.execute("UPDATE thread SET meta=? WHERE key=?", (dumps(meta), thread_key))

    def chat_of_ticket(self, ticket_id: str) -> str:
        t = self.store.q1("SELECT thread_key FROM ticket WHERE id=?", (ticket_id,))
        if not t:
            return ""
        row = self.store.q1("SELECT meta FROM thread WHERE key=?", (t["thread_key"],))
        meta = loads(row["meta"], {}) if row else {}
        return meta.get("feishu_chat_id") or ""

    def _artifacts(self, t: dict) -> list[dict]:
        out = []
        if os.path.isdir(t["dir"]):
            for f in sorted(os.listdir(t["dir"])):
                p = os.path.join(t["dir"], f)
                if os.path.isfile(p):
                    out.append({"name": f, "bytes": os.path.getsize(p)})
        return out

    def _upload_artifacts(self, t: dict) -> list[tuple[str, str]]:
        """Upload the ticket's text artifacts so they can be opened in the chat.

        Bounded on purpose: max files and max size are config, transcript.md stays
        internal, and a failed upload never blocks the report itself.
        """
        if not (self.cfg.upload and self.client and self.cfg.transport == "api"):
            return []
        done: list[tuple[str, str]] = []
        arts = sorted(self._artifacts(t), key=lambda a: (0 if a["name"].endswith(".md") else 1, a["name"]))
        for a in arts:
            if len(done) >= self.cfg.upload_max_files:
                break
            if a["name"] == "transcript.md" or a["bytes"] > self.cfg.upload_max_kb * 1024:
                continue
            try:
                fk = self.client.upload_file(os.path.join(t["dir"], a["name"]), a["name"])
                if fk:
                    done.append((a["name"], fk))
            except Exception as exc:
                self.counters["errors"] += 1
                self.last_error = repr(exc)[:300]
                self.engine.emit("feishu.upload_failed", t["id"],
                                 {"file": a["name"], "error": str(exc)[:200]})
        return done

    def _report_card(self, t: dict, rep: dict, state: str, attached: list[str]) -> dict:
        icon = {"ready": "✅", "blocked": "⛔", "failed": "❌", "waiting": "⏳"}.get(state, "•")
        template = {"ready": "green", "blocked": "orange", "failed": "red",
                    "waiting": "orange"}.get(state, "grey")
        summary = (rep.get("summary") or "")[:1200]
        m = t.get("mandate") or {}
        fields = [
            {"is_short": True, "text": {"tag": "lark_md",
                                        "content": f"**Policy**\nv{m.get('policy_version')} · {m.get('strength')}"}},
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**Ticket**\n{t['id']}"}},
            {"is_short": False, "text": {"tag": "lark_md",
                                         "content": f"**Scope**\n{', '.join(t.get('scope') or []) or '—'}"}},
        ]
        elements: list[dict] = [
            {"tag": "div", "text": {"tag": "lark_md", "content": summary or "（无摘要）"}},
            {"tag": "hr"},
            {"tag": "div", "fields": fields},
        ]
        if rep.get("question"):
            elements.insert(2, {"tag": "div", "text": {
                "tag": "lark_md", "content": f"**需要你决定**\n{rep['question'][:600]}"}})
        note = f"产物：{', '.join(attached) if attached else '见面板'} · {utcnow()}"
        elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": note[:300]}]})
        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"template": template,
                       "title": {"tag": "plain_text", "content": f"{icon} {t['title']}"[:80]}},
            "elements": elements,
        }

    # -------------------------------------------------------- engine events
    def on_engine_event(self, kind: str, data: dict) -> None:
        """Called from the runtime bus. Only the messages a person needs get out."""
        if kind != "report.recorded":
            return
        ticket_id = (data or {}).get("ticket")
        state = (data or {}).get("state")
        if not ticket_id or state not in ("ready", "blocked", "failed", "waiting"):
            return
        chat = self.chat_of_ticket(ticket_id)
        if not chat:
            return
        t = self.engine.ticket(ticket_id)
        if not t:
            return
        rep = t["latest_report"] or {}
        icon = {"ready": "✅", "blocked": "⛔", "failed": "❌", "waiting": "⏳"}.get(state, "•")
        attached = self._upload_artifacts(t)
        card = self._report_card(t, rep, state, [n for n, _ in attached])
        fallback = f"{icon} {t['title']}\n{(rep.get('summary') or '')[:800]}"
        if rep.get("question"):
            fallback += f"\n\n需要你决定：{rep['question']}"
        self._enqueue(chat, f"report:{state}", {"card": card, "fallback": fallback})
        for name, fk in attached:
            self._enqueue(chat, "file", {"file_key": fk, "name": name})

    # ---------------------------------------------------------- simulation
    def simulate(self, text: str, chat_id: str = "oc_sim_demo", actor: str = "feishu:ou_sim_erik") -> dict:
        """Drive the same code path as a real callback, without Feishu."""
        payload = {
            "schema": "2.0",
            "header": {"event_id": new_id("evt"), "event_type": "im.message.receive_v1",
                       "create_time": str(int(time.time() * 1000)), "token": self.cfg.verification_token or "sim"},
            "event": {
                "sender": {"sender_id": {"open_id": actor.split(":", 1)[-1]}, "sender_type": "user"},
                "message": {"message_id": new_id("om"), "chat_id": chat_id, "chat_type": "group",
                            "message_type": "text",
                            "content": json.dumps({"text": text}, ensure_ascii=False)},
            },
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        code, body = self.handle_webhook({"x-lark-request-timestamp": "",
                                          "x-lark-request-nonce": "",
                                          "x-lark-signature": ""}, raw)
        return {"status": code, **body}

    # --------------------------------------------------------------- reads
    def snapshot(self) -> dict:
        return {
            "config": self.cfg.describe(),
            "counters": self.counters,
            "last_error": self.last_error,
            "poll": self.poll_state,
            "policy": (self.policy.doc.get("sources") or {}).get("feishu", {}),
            "commands": dict(self.COMMANDS),
            "events": self.store.q("SELECT * FROM feishu_event ORDER BY at DESC LIMIT 25"),
            "out": self.store.q("SELECT * FROM feishu_out ORDER BY at DESC LIMIT 25"),
        }
