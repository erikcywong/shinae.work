"""HTTP surface: one JSON API, one SSE stream, one static tree. Zero dependencies.

    python app/server.py --port 8787            # mock planner (offline)
    python app/server.py --port 8787 --live      # DeepSeek tool-calling workers
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import re
import secrets
import signal
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import carbon  # noqa: E402
import export  # noqa: E402
import ledger as ledger_mod  # noqa: E402
from executor import probe_key  # noqa: E402
from runtime import Runtime  # noqa: E402
from store import loads, utcnow  # noqa: E402

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
RT: Runtime | None = None
AUTH_TOKEN = ""
OPEN_PATHS = {"/api/feishu/events", "/api/feishu/ping", "/api/health"}
MAX_BODY = 256 * 1024


def load_or_create_token(var_dir: str) -> tuple[str, str]:
    """One bearer token for the panel and the JSON API.

    A token that does not exist is generated and written to var/auth.env, so a
    fresh checkout is never accidentally an open control panel.
    """
    env = os.environ.get("COSA_AUTH_TOKEN", "").strip()
    if env:
        return env, "env"
    path = os.path.join(var_dir, "auth.env")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("COSA_AUTH_TOKEN="):
                    return line.split("=", 1)[1].strip(), "file"
    token = secrets.token_urlsafe(24)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Panel bearer token — gitignored. Rotate by replacing this value.\n"
                f"COSA_AUTH_TOKEN={token}\n")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return token, "generated"


class Handler(BaseHTTPRequestHandler):
    server_version = "CoffeeSuperAgentOS/0.1"

    # ------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):
        if os.environ.get("COSA_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, obj, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code: int, msg: str, **extra):
        self._json({"error": msg, **extra}, code)

    def _bytes(self, data: bytes, ctype: str, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        q = parse_qs(urlparse(self.path).query)
        return (q.get("token") or [""])[0]

    def _authorized(self, path: str) -> bool:
        if not AUTH_TOKEN or path in OPEN_PATHS:
            return True
        return secrets.compare_digest(self._token(), AUTH_TOKEN)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"bad json: {exc}")

    # ------------------------------------------------------------ routing
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        try:
            if path.startswith("/api/") and not self._authorized(path):
                return self._err(401, "unauthorized: send Authorization: Bearer <panel token> "
                                      "or ?token= (see var/auth.env)")
            if path == "/api/state":
                return self._json(RT.snapshot())
            if path == "/api/health":
                return self._json({"ok": True, "uptime_s": RT.snapshot()["status"]["uptime_s"],
                                   "health": RT.health})
            if path == "/api/feishu/chats":
                try:
                    items = RT.feishu._discover_chats()
                    return self._json({"ok": True, "chats": items, "error": RT.feishu.poll_state.get("last_error", "")})
                except Exception as exc:
                    return self._json({"ok": False, "chats": [], "error": repr(exc)})
            if path == "/api/feishu/ping":
                # tiny, no-DB probe: open this in a browser on any network to test reachability
                return self._json({"ok": True, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                   "transport": RT.feishu.cfg.transport,
                                   "seen_hits": RT.store.q1("SELECT COUNT(*) n FROM event "
                                                            "WHERE kind='feishu.hit'")["n"]})
            if path == "/api/stream":
                return self._stream()
            m = re.match(r"^/api/export/batch/([^/]+)\.(pdf|zip)$", path)
            if m:
                return self._export(m.group(1), m.group(2))
            if path.startswith("/api/ticket/") and path.endswith("/file"):
                q = parse_qs(u.query)
                return self._file(path.split("/")[3], (q.get("name") or [""])[0])
            if path.startswith("/api/"):
                return self._err(404, f"no route {path}")
            return self._static(path)
        except Exception as exc:
            traceback.print_exc()
            return self._err(500, repr(exc))

    def _export(self, batch_id: str, fmt: str):
        b = RT.store.q1("SELECT * FROM batch WHERE id=?", (batch_id,))
        if not b:
            return self._err(404, f"no batch {batch_id}")
        doc = carbon.compute(b)
        doc["computed_at"] = utcnow()
        rows = RT.store.q("SELECT * FROM ledger_entry WHERE batch_id=? ORDER BY id", (batch_id,))
        verify = ledger_mod.verify(RT.store, batch_id)
        if fmt == "pdf":
            data = export.batch_pdf(b, doc, rows, verify)
            return self._bytes(data, "application/pdf", f"{batch_id}-footprint.pdf")
        dossier = ""
        tdir = None
        for t in RT.store.q("SELECT dir FROM ticket WHERE thread_key=? ORDER BY created_at DESC LIMIT 1",
                            (f"field/batch-{batch_id}",)):
            tdir = t["dir"]
        if tdir and os.path.isfile(os.path.join(tdir, "dossier.md")):
            with open(os.path.join(tdir, "dossier.md"), encoding="utf-8") as f:
                dossier = f.read()
        data = export.zenodo_bundle(b, doc, rows, verify, carbon.methodology_doc(), dossier)
        return self._bytes(data, "application/zip", f"{batch_id}-zenodo.zip")

    def _raw(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(n) if n else b""

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/feishu/events":
            # must see the exact bytes: the signature covers them
            try:
                raw = self._raw()
                headers = {k.lower(): v for k, v in self.headers.items()}
                code, body = RT.feishu.handle_webhook(headers, raw, remote=self.client_address[0])
                return self._json(body, code)
            except ValueError as exc:
                return self._err(413, str(exc))
            except Exception as exc:
                traceback.print_exc()
                return self._err(500, repr(exc))
        try:
            body = self._body()
        except ValueError as exc:
            return self._err(400, str(exc))
        if path.startswith("/api/") and not self._authorized(path):
            return self._err(401, "unauthorized")
        try:
            return self._post(path, body)
        except KeyError as exc:
            return self._err(404, f"not found: {exc}")
        except ValueError as exc:
            return self._err(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            return self._err(500, repr(exc))

    def _post(self, path: str, body: dict):
        if path == "/api/secrets/reload":
            return self._json(RT.reload_secrets())
        if path == "/api/console":
            text = (body.get("text") or "").strip()
            if not text:
                raise ValueError("text is required")
            return self._json({"ok": True, **RT.human_message(text)})
        if path == "/api/demo/anomaly":
            return self._json({"ok": True, **RT.inject_anomaly(body.get("cabin") or "A1")})
        if path == "/api/demo/harvest":
            return self._json({"ok": True, **RT.record_harvest(body.get("batch_id"))})
        if path == "/api/demo/factor":
            return self._json({"ok": True, **RT.factor_update(body.get("region") or "CN")})
        if path == "/api/policy":
            patch = {k: v for k, v in body.items() if k in
                     ("paused", "mode", "eval_timeout_s", "watchdog_stale_s", "sources", "rules")}
            if not patch:
                raise ValueError("no policy field given")
            return self._json({"ok": True, **RT.set_policy(patch)})
        m = re.match(r"^/api/tickets/([^/]+)/(stop|retry|resume)$", path)
        if m:
            tid, action = m.group(1), m.group(2)
            if action == "stop":
                ok = RT.engine.stop_ticket(tid, body.get("reason") or "stopped from the panel")
                return self._json({"ok": ok})
            if action == "retry":
                res = RT.engine.retry_ticket(tid)
                return self._json({"ok": bool(res), **(res or {})})
            return self._json({"ok": True, **(RT.engine.resume_with_message(tid, body.get("text") or "(no text)"))})
        m = re.match(r"^/api/ledger/([^/]+)/recompute$", path)
        if m:
            return self._json({"ok": True, **RT.recompute(m.group(1))})
        if path == "/api/sim/tick":
            return self._json({"ok": True, "readings": RT.sim.tick()})
        if path == "/api/feishu/simulate":
            text = (body.get("text") or "").strip()
            if not text:
                raise ValueError("text is required")
            res = RT.feishu.simulate(text, body.get("chat_id") or "oc_sim_demo",
                                     body.get("actor") or "feishu:ou_sim_erik")
            return self._json({"ok": res.get("status") == 200, **res})
        if path == "/api/feishu/allow":
            actor = (body.get("actor") or "").strip()
            if not actor:
                raise ValueError("actor is required (feishu:ou_xxx or ou_xxx)")
            return self._json(RT.feishu.allow_actor(actor))
        raise KeyError(path)

    # ------------------------------------------------------------ static
    def _static(self, path: str):
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(os.path.normpath(WEB_DIR)) or not os.path.isfile(full):
            return self._err(404, "not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, ticket_id: str, name: str):
        t = RT.engine.ticket(ticket_id)
        if not t:
            return self._err(404, "no ticket")
        full = os.path.join(t["dir"], os.path.basename(name))
        if not os.path.isfile(full):
            return self._err(404, "no file")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown; charset=utf-8"
                         if name.endswith(".md") else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------ SSE
    def _stream(self):
        q = RT.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            last = time.time()
            while True:
                try:
                    msg = q.get(timeout=2.0)
                    payload = json.dumps(msg, ensure_ascii=False, default=str)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last = time.time()
                except queue.Empty:
                    if time.time() - last > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            RT.unsubscribe(q)


def load_env_file(path: str) -> int:
    """Minimal dotenv: KEY=VALUE lines, `#` comments, no interpolation.

    Secrets live in `var/feishu.env` (gitignored), never in the repository.
    """
    if not os.path.isfile(path):
        return 0
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                n += 1
    return n


def main(argv=None):
    global RT
    ap = argparse.ArgumentParser(description="Coffee Super-Agent OS")
    ap.add_argument("--port", type=int, default=int(os.environ.get("COSA_PORT", 8787)))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--live", action="store_true", help="use the DeepSeek API for workers")
    ap.add_argument("--var", default=None, help="state directory (default ./var)")
    ap.add_argument("--sim-interval", type=float, default=12.0)
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    var = args.var or os.path.join(root, "var")
    loaded = load_env_file(os.path.join(root, ".env"))
    loaded += load_env_file(os.path.join(var, "llm.env"))
    loaded += load_env_file(os.path.join(var, "feishu.env"))
    if loaded:
        print(f"loaded {loaded} secret(s) from the local env file (never committed)")
    preset = (os.environ.get("LLM_PRESET") or "").strip().lower()
    presets = {
        "deepseek": ("https://api.deepseek.com/chat/completions", "deepseek-chat"),
        "ark": ("https://ark.cn-beijing.volces.com/api/v3/chat/completions", ""),
        "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "deepseek/deepseek-chat"),
        "siliconflow": ("https://api.siliconflow.cn/v1/chat/completions", "deepseek-ai/DeepSeek-V3"),
        "ollama": ("http://127.0.0.1:11434/v1/chat/completions", "qwen2.5:7b"),
    }
    if preset in presets:
        url, model = presets[preset]
        os.environ.setdefault("DSH_LLM_URL", url)
        if model:
            os.environ.setdefault("DSH_LLM_MODEL", model)
        print(f"llm preset: {preset} → {os.environ.get('DSH_LLM_URL')} · {os.environ.get('DSH_LLM_MODEL')}")

    mode = "live" if args.live else None
    RT = Runtime(var_dir=args.var, mode=mode, sim_interval=args.sim_interval)
    if RT.mode == "live":
        ok, why = probe_key(RT.api_key or "")
        if not ok:
            print(f"WARNING: model key check failed → running in MOCK ({why})")
            print("         put a working key in var/llm.env, then POST /api/secrets/reload")
            RT.mode = "mock"
            RT.worker.mode = "mock"

    global AUTH_TOKEN
    AUTH_TOKEN, token_src = load_or_create_token(RT.var_dir)
    if token_src == "generated":
        print(f"panel token generated → paste it into the panel: {AUTH_TOKEN}")
        print(f"  (stored in {os.path.join(RT.var_dir, 'auth.env')}, gitignored)")
    else:
        print(f"panel token loaded from {token_src}; open the panel and paste it if asked")

    RT.start()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True

    def bye(*_):
        RT.stop()
        httpd.shutdown()

    signal.signal(signal.SIGINT, lambda *a: bye())
    try:
        signal.signal(signal.SIGTERM, lambda *a: bye())
    except (AttributeError, ValueError):
        pass
    print(f"Coffee Super-Agent OS {RT.mode.upper()} on http://{args.host}:{args.port}  (var: {RT.var_dir})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        bye()


if __name__ == "__main__":
    main()
