"""Check a model endpoint/key in ~10 tokens, without touching the kernel.

    python tools/llm_probe.py              # use DEEPSEEK_API_KEY / DSH_LLM_URL from env or var/llm.env
    python tools/llm_probe.py --selftest   # run against a local stub (no key needed)

Reports: endpoint, HTTP status, which model answered, whether tool calling is
accepted, latency and token usage. Exit 0 = ready for `--live`.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_URL = "https://api.deepseek.com/chat/completions"

# A key that is not `sk-…` is very likely from another provider; these presets save a round trip.
PRESETS = {
    "deepseek": ("https://api.deepseek.com/chat/completions", "deepseek-chat"),
    "ark": ("https://ark.cn-beijing.volces.com/api/v3/chat/completions", ""),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "deepseek/deepseek-chat"),
    "siliconflow": ("https://api.siliconflow.cn/v1/chat/completions", "deepseek-ai/DeepSeek-V3"),
    "ollama": ("http://127.0.0.1:11434/v1/chat/completions", "qwen2.5:7b"),
}


def load_env() -> None:
    for name in (".env", os.path.join("var", "llm.env"), os.path.join("var", "feishu.env")):
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


def probe(url: str, key: str, model: str) -> int:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 8,
        "temperature": 0,
        "tools": [{"type": "function", "function": {
            "name": "noop", "description": "does nothing",
            "parameters": {"type": "object", "properties": {}}}}],
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        ms = (time.time() - t0) * 1000
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")[:300]
        print(f"[FAIL] HTTP {exc.code}: {raw}")
        if exc.code == 401:
            print("       → key 无效或已吊销；到 platform.deepseek.com 重新创建")
        elif exc.code == 402:
            print("       → 余额不足；充值后再试")
        return 1
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1

    choice = (data.get("choices") or [{}])[0]
    used = data.get("model") or "?"
    usage = data.get("usage") or {}
    text = ((choice.get("message") or {}).get("content") or "").strip()
    print(f"[ok] {url}")
    print(f"     model={used} · {ms:.0f} ms · tokens in/out={usage.get('prompt_tokens')}/{usage.get('completion_tokens')}")
    print(f"     content={text!r} · tools accepted={bool(data.get('choices'))}")
    return 0


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        payload = {"model": "stub-model", "choices": [{"index": 0, "message": {
            "role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 1}}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def selftest() -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", 8898), Stub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    code = probe("http://127.0.0.1:8898/chat/completions", "sk-stub", "stub-model")
    httpd.shutdown()
    return code


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    load_env()
    preset = (os.environ.get("LLM_PRESET") or "").strip().lower()
    url = os.environ.get("DSH_LLM_URL") or (PRESETS[preset][0] if preset in PRESETS else DEFAULT_URL)
    model = os.environ.get("DSH_LLM_MODEL") or (PRESETS[preset][1] if preset in PRESETS else "") or "deepseek-chat"
    key = os.environ.get("DEEPSEEK_API_KEY") or ""
    if not key:
        print("no DEEPSEEK_API_KEY found.")
        print("→ 到 https://platform.deepseek.com → API keys → 创建，粘贴到 var/llm.env：")
        print("   DEEPSEEK_API_KEY=sk-…")
        return 2
    if not key.startswith("sk-"):
        print(f"warn: key 不以 'sk-' 开头（…{key[-4:]}）。DeepSeek 的 key 形如 sk-xxxxxxxx。")
        print("      UUID 形态通常是火山方舟(Ark)；若是别家，请在 var/llm.env 里同时给出：")
        print("      LLM_PRESET=ark|openrouter|siliconflow|ollama，或 DSH_LLM_URL + DSH_LLM_MODEL")
    print(f"probing {url} with model {model} (key …{key[-4:]})")
    return probe(url, key, model)


if __name__ == "__main__":
    raise SystemExit(main())
