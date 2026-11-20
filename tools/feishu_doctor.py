"""Feishu doctor: what still needs a human, in one run.

    python tools/feishu_doctor.py

Reads credentials the same way the server does (env or var/feishu.env), probes the
real open platform for every scope the bridge needs, and asks the local server
(if it is running) what it currently sees. Each failed line carries the exact fix.

Exit code: 0 = ready, 1 = a person still has to do something.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://open.feishu.cn"
APP_ID_HINT = os.environ.get("FEISHU_APP_ID", "")


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


def call(path: str, payload: dict | None = None, token: str | None = None, method: str = "GET"):
    data = json.dumps(payload).encode() if (payload is not None and method != "GET") else None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode())
        except Exception:
            return {"code": exc.code, "msg": "http error"}
    except Exception as exc:
        return {"code": "ERR", "msg": repr(exc)}


def code_of(d: dict) -> int | str:
    return d.get("code", "ERR")


def scope_missing(d: dict) -> bool:
    return str(d.get("code")) == "99991672" or "scopes is required" in str(d.get("msg"))


def upload_probe(token: str) -> dict:
    """Upload a 40-byte probe file to prove `im:resource`. Leaves one orphan file."""
    boundary = "----doctor"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file_type\"\r\n\r\nstream\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file_name\"\r\n\r\nprobe.txt\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"probe.txt\"\r\n"
            f"Content-Type: text/plain\r\n\r\ndoctor probe 2026\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(
        BASE + "/open-apis/im/v1/files", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Authorization": f"Bearer {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode())
        except Exception:
            return {"code": exc.code, "msg": "http error"}
    except Exception as exc:
        return {"code": "ERR", "msg": repr(exc)}


def missing_scope(d: dict) -> str:
    msg = str(d.get("msg") or "")
    if "One of the following scopes" in msg:
        return msg.split("required: [")[1].split("]")[0]
    return ""


class Checker:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []  # (status, item, fix)

    def ok(self, item: str, detail: str = ""):
        self.rows.append(("OK", item, detail))

    def todo(self, item: str, fix: str):
        self.rows.append(("TODO", item, fix))

    def warn(self, item: str, fix: str):
        self.rows.append(("WARN", item, fix))

    def render(self) -> int:
        icon = {"OK": "[ok]  ", "TODO": "[todo]", "WARN": "[warn]"}
        for status, item, detail in self.rows:
            print(f"{icon[status]} {item}" + (f"\n        → {detail}" if detail else ""))
        todo = sum(1 for s, _, _ in self.rows if s == "TODO")
        print()
        if todo:
            print(f"{todo} item(s) need a person.")
        else:
            print("nothing left for a person; the bridge is ready.")
        return 1 if todo else 0


def auth_token() -> str:
    tok = os.environ.get("COSA_AUTH_TOKEN", "").strip()
    if tok:
        return tok
    path = os.path.join(ROOT, "var", "auth.env")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            if line.strip().startswith("COSA_AUTH_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def local_state() -> dict | None:
    tok = auth_token()
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    try:
        req = urllib.request.Request("http://127.0.0.1:8787/api/state", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return {"__unauthorized": True}
        return None
    except Exception:
        return None


def main() -> int:
    load_env()
    c = Checker()
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    vtoken = os.environ.get("FEISHU_VERIFICATION_TOKEN", "").strip()
    if not (app_id and secret):
        c.todo("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置", "放到 var/feishu.env，见 docs/005 §1")
        return c.render()
    c.ok("App ID / App Secret 存在", f"cli_…{app_id[-4:]}")

    tok = call("/open-apis/auth/v3/tenant_access_token/internal",
               {"app_id": app_id, "app_secret": secret}, method="POST")
    if code_of(tok) != 0:
        c.todo("凭证校验失败", f"code={code_of(tok)} msg={str(tok.get('msg'))[:120]}；App Secret 是否重置过？")
        return c.render()
    token = tok["tenant_access_token"]
    c.ok("tenant_access_token 获取成功")

    if vtoken:
        c.ok("Verification Token 已配置（回调会校验 token）")
    else:
        c.todo("Verification Token 未配置", "事件与回调 → 加密策略 → 复制 Verification Token 写进 var/feishu.env（公网回调必须）")

    # --- 发消息权限 -------------------------------------------------------
    probe = call("/open-apis/im/v1/messages?receive_id_type=chat_id",
                 {"receive_id": "oc_DOCTOR_PROBE", "msg_type": "text",
                  "content": json.dumps({"text": "doctor"})}, token=token, method="POST")
    BAD_ID = {"230001", "230002", "230013", "230020", "99992361"}
    if scope_missing(probe):
        c.todo("发消息权限缺失", f"缺 [{missing_scope(probe)}]；权限管理里加 im:message + im:message:send_as_bot")
    elif str(code_of(probe)) in BAD_ID:
        c.ok("发消息权限可用", f"（探测到不存在的会话，符合预期：code={code_of(probe)}）")
    elif code_of(probe) == 0:
        c.warn("发消息权限可用，但探测消息居然发出去了", "code=0，检查 receive_id 是否被当作有效会话")
    else:
        c.warn("发消息返回未知错误", f"code={code_of(probe)} msg={str(probe.get('msg'))[:160]}")

    # --- 列群权限 ---------------------------------------------------------
    chats = call("/open-apis/im/v1/chats?page_size=50", token=token)
    chat_ids: list[str] = []
    if code_of(chats) == 0:
        items = (chats.get("data") or {}).get("items") or []
        chat_ids = [x["chat_id"] for x in items if x.get("chat_id")]
        if chat_ids:
            c.ok("列群权限可用", f"{len(chat_ids)} 个群：" + ", ".join(
                f"{x.get('name') or '?'}({x['chat_id']})" for x in items[:5]))
        else:
            c.todo("机器人还没进任何群", "把机器人拉进目标群（群设置 → 群机器人 → 添加），或先单聊它")
    elif scope_missing(chats):
        c.todo("列群权限缺失", f"缺 [{missing_scope(chats)}]；加 im:chat:readonly（轮询自动发现群要用）")
    else:
        c.warn("列群失败", f"code={code_of(chats)} msg={str(chats.get('msg'))[:160]}")

    # --- 读消息权限（轮询用） --------------------------------------------
    target = chat_ids[0] if chat_ids else "oc_DOCTOR_PROBE"
    hist = call(f"/open-apis/im/v1/messages?container_id_type=chat&container_id={target}"
                f"&sort_type=ByCreateTimeDesc&page_size=1", token=token)
    if code_of(hist) == 0:
        c.ok("读会话历史权限可用", "轮询模式可以工作")
    elif scope_missing(hist):
        c.todo("读消息权限缺失", f"缺 [{missing_scope(hist)}]；权限管理里加 im:message（收消息的本体权限）")
    elif str(code_of(hist)) in BAD_ID:
        c.ok("读消息权限可用", f"（会话不存在，符合预期：code={code_of(hist)}；进群后再验一次）")
    else:
        c.warn("读会话历史失败", f"code={code_of(hist)} msg={str(hist.get('msg'))[:160]}")

    # --- 版本/可用范围 ----------------------------------------------------
    if not chat_ids:
        c.warn("无法判断版本是否已发布", "机器人能进群、能收到消息，通常意味着版本已发布且在可用范围")

    if "--deep" in sys.argv:
        up = upload_probe(token)
        if code_of(up) == 0:
            c.ok("文件上传权限可用", "卡片附件（im:resource）可发；本次体检留下一个 40B 的 probe.txt")
        elif scope_missing(up):
            c.todo("文件上传权限缺失", f"缺 [{missing_scope(up)}]；权限管理里加 im:resource（只影响附件，卡片仍可发）")
        else:
            c.warn("文件上传失败", f"code={code_of(up)} msg={str(up.get('msg'))[:160]}")

    # --- 本机服务 ---------------------------------------------------------
    state = local_state()
    if state and state.get("__unauthorized"):
        c.warn("面板启用了 token，但 doctor 没读到", "把 var/auth.env 里的 COSA_AUTH_TOKEN 放进环境变量，或确认文件还在")
        return c.render()
    if not state:
        c.warn("本机服务未运行", "python app/server.py --port 8787（面板在 http://127.0.0.1:8787）")
        return c.render()
    f = state.get("feishu") or {}
    cfg = f.get("config") or {}
    c.ok("本机服务在线", f"transport={cfg.get('transport')} poll={cfg.get('poll_enabled')} "
                        f"policy v{state['status']['policy_version']}")
    if cfg.get("transport") != "api":
        c.todo("服务还在 sim 通道", "确认 var/feishu.env 被加载（启动日志有一行 loaded N secret(s)），或显式传 --live 之外的环境变量")
    poll = f.get("poll") or {}
    if cfg.get("poll_enabled"):
        if poll.get("last_error"):
            c.todo("轮询报错", str(poll["last_error"])[:200])
        else:
            c.ok("轮询运行中", f"chats={len(poll.get('chats') or [])} cycles={f.get('counters', {}).get('poll_cycles')}")
    allow = ((f.get("policy") or {}).get("allow") or [])
    refused = [e for e in (f.get("events") or []) if e.get("handled") == "refused" and e.get("actor") not in allow]
    if refused:
        c.warn("白名单外的发信人（可能是测试或真人）",
               f"{refused[0]['actor']}；真人就在面板点 + 白名单，测试账号可忽略")
    elif len(allow) > 2:
        c.ok("白名单已包含真实用户", ", ".join(a for a in allow if "sim" not in a) or "仅默认项")
    if not state.get("feishu", {}).get("out"):
        c.warn("还没有出站消息", "发一句 /status 测试端到端")
    return c.render()


if __name__ == "__main__":
    raise SystemExit(main())
