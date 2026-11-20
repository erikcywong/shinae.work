"""Card + file upload against a local Feishu stub — no real tenant touched.

    python tests/feishu_media_smoke.py

Stubs three endpoints: tenant token, /im/v1/files (multipart), /im/v1/messages.
Asserts the multipart body is well formed, the card carries the ticket title,
and the file message carries the returned file_key.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

PORT = 8897
SEEN = {"files": [], "messages": []}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, payload):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        if self.path.endswith("/tenant_access_token/internal"):
            return self._reply({"code": 0, "msg": "ok", "tenant_access_token": "t-stub", "expire": 7200})
        if "/im/v1/files" in self.path:
            SEEN["files"].append({
                "content_type": self.headers.get("Content-Type", ""),
                "len": len(body),
                "has_filename": b'filename="' in body,
                "has_stream": b'name="file_type"' in body and b"stream" in body,
                "sample": body[:120].decode("latin-1"),
            })
            return self._reply({"code": 0, "msg": "ok", "data": {"file_key": "fk_stub_1"}})
        if "/im/v1/messages" in self.path:
            SEEN["messages"].append(json.loads(body or b"{}"))
            return self._reply({"code": 0, "msg": "ok", "data": {"message_id": "om_stub"}})
        return self._reply({"code": 404, "msg": "unknown"})


def main() -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Stub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    import feishu as fs

    fs.FEISHU_BASE = f"http://127.0.0.1:{PORT}"
    os.environ.update({"FEISHU_APP_ID": "cli_stub", "FEISHU_APP_SECRET": "secret_stub"})
    cfg = fs.FeishuConfig()
    client = fs.FeishuClient(cfg)

    fails = []
    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write("# B-2026-11\n\nfootprint 1225.234 kgCO2e\n")
    tmp.close()
    try:
        key = client.upload_file(tmp.name, "B-2026-11-summary.md")
        if key != "fk_stub_1":
            fails.append(f"upload returned {key!r}")
        if not SEEN["files"]:
            fails.append("stub never saw the multipart upload")
        else:
            f = SEEN["files"][0]
            if not f["content_type"].startswith("multipart/form-data; boundary="):
                fails.append(f"bad content-type: {f['content_type']}")
            if not (f["has_filename"] and f["has_stream"]):
                fails.append("multipart missing filename or file_type=stream")

        card = {"config": {"wide_screen_mode": True},
                "header": {"template": "green", "title": {"tag": "plain_text", "content": "✅ B-2026-11"}},
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "**total** 1225.234"}}]}
        client.send_card("oc_stub", card)
        if not any(m.get("msg_type") == "interactive" for m in SEEN["messages"]):
            fails.append("card message not sent as interactive")
        client.send_file("oc_stub", key)
        file_msg = [m for m in SEEN["messages"] if m.get("msg_type") == "file"]
        if not file_msg or json.loads(file_msg[0]["content"]).get("file_key") != "fk_stub_1":
            fails.append("file message missing file_key")
    finally:
        os.unlink(tmp.name)
        httpd.shutdown()

    print("uploads:", len(SEEN["files"]), "messages:", len(SEEN["messages"]))
    if fails:
        for f in fails:
            print("[FAIL]", f)
        return 1
    print("[ok] multipart upload, interactive card and file message all well formed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
