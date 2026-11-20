"""Small operator tool for the real Feishu API: who am I, which chats, send one message.

    python tools/feishu_probe.py token          # is the app credential valid
    python tools/feishu_probe.py chats          # which group chats the bot is in
    python tools/feishu_probe.py send <chat_id> "text"

Reads credentials from var/feishu.env or the environment. Never prints secrets.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://open.feishu.cn"


def load_env() -> None:
    for name in (".env", os.path.join("var", "feishu.env")):
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def call(path: str, payload: dict | None = None, token: str | None = None, method: str = "GET") -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        return {"code": exc.code, "msg": exc.read().decode()[:400]}


def token() -> str:
    d = call("/open-apis/auth/v3/tenant_access_token/internal",
             {"app_id": os.environ["FEISHU_APP_ID"], "app_secret": os.environ["FEISHU_APP_SECRET"]},
             method="POST")
    if d.get("code") != 0:
        raise SystemExit(f"token failed: code={d.get('code')} msg={d.get('msg')}")
    return d["tenant_access_token"]


def main(argv: list[str]) -> int:
    load_env()
    if not os.environ.get("FEISHU_APP_ID") or not os.environ.get("FEISHU_APP_SECRET"):
        print("no FEISHU_APP_ID / FEISHU_APP_SECRET in env or var/feishu.env")
        return 2
    cmd = argv[1] if len(argv) > 1 else "token"
    tok = token()
    if cmd == "token":
        print(f"app credential valid · tenant_access_token {len(tok)} chars")
        return 0
    if cmd == "chats":
        d = call("/open-apis/im/v1/chats?page_size=50", token=tok)
        if d.get("code") != 0:
            print(f"chats failed: code={d.get('code')} msg={d.get('msg')}")
            print("hint: grant im:chat:readonly, or just send a message in a group the bot is in")
            return 1
        items = (d.get("data") or {}).get("items") or []
        if not items:
            print("bot is in no group chat yet: add it to a group first")
        for c in items:
            print(f"{c.get('chat_id')}  {c.get('name')}  owner={c.get('owner_id')}  mode={c.get('chat_mode')}")
        return 0
    if cmd == "send" and len(argv) >= 4:
        chat_id, text = argv[2], argv[3]
        d = call("/open-apis/im/v1/messages?receive_id_type=chat_id",
                 {"receive_id": chat_id, "msg_type": "text",
                  "content": json.dumps({"text": text}, ensure_ascii=False)},
                 token=tok, method="POST")
        ok = d.get("code") == 0
        print(f"send {'ok' if ok else 'failed'} code={d.get('code')} msg={d.get('msg')} "
              f"message_id={(d.get('data') or {}).get('message_id')}")
        return 0 if ok else 1
    if cmd == "card" and len(argv) >= 5:
        chat_id, title, body = argv[2], argv[3], argv[4]
        card = {
            "config": {"wide_screen_mode": True},
            "header": {"template": "green",
                       "title": {"tag": "plain_text", "content": title[:80]}},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": body[:1500]}},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text",
                                              "content": "Coffee Super-Agent OS · card probe"}]},
            ],
        }
        d = call("/open-apis/im/v1/messages?receive_id_type=chat_id",
                 {"receive_id": chat_id, "msg_type": "interactive",
                  "content": json.dumps(card, ensure_ascii=False)},
                 token=tok, method="POST")
        ok = d.get("code") == 0
        print(f"card {'ok' if ok else 'failed'} code={d.get('code')} msg={d.get('msg')}")
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
