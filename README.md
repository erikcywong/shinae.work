# Coffee Super-Agent OS

**把 DeepSeek Super-agent 的 Router/Worker 双层架构，装进一个雾化咖啡农场的碳账本里。**
一个能跑起来的全栈系统：IoT 读数 → Trigger → 策略准入 → 工单 → 独立目录里的 Worker → 哈希链账本 → 双语面板，并且**可以从飞书群里直接下指令、在同一个群里拿到结果**。

> 本仓库是研究/创作原型，不是 DeepSeek 官方产品，也不是可对外签发的碳核证系统。

## 90 秒跑起来

```powershell
python app/server.py            # → http://127.0.0.1:8787  （默认离线 mock planner）
python app/server.py --live     # 用 DeepSeek API 跑 Worker（需 $env:DEEPSEEK_API_KEY）
```

零依赖：Python 3.11+ 标准库 + 一个 SQLite 文件，没有 npm、没有构建、没有容器。

打开页面后，四个动作就能看完整个闭环：

1. **Cockpit → A1 注入异常**：一行越阈读数 → Trigger → 30 秒内出一张工单，Worker 写 `findings.md`
2. **Cockpit → 记录采收**：批次 → `carbon.compute` → `ledger.append`（6 行哈希链）→ `dossier.render`
3. **Console → 说一句话**："给我 B-2026-11 的碳账本与方法学摘要" → 走 `human.message` 规则
4. **Feishu → `/status` 或一句话**：同一条链路，只是入口是群；结果回到同一个群（无凭据时走 sim 通道，不真的发出）

## 它到底做了什么

| 层 | 做什么 | 代码 |
| --- | --- | --- |
| Router | 唯一写者：intake → Eval（gate + 规则）→ Ticket + Mandate → Assignment | [`app/engine.py`](app/engine.py) |
| Policy | 版本化白名单与规则，哈希固定；变更只通知在办工单，不撤销授权 | [`app/policy.py`](app/policy.py) |
| Worker | 独立目录 + 6 个工具，工具越界即拒绝；`report` 是唯一出口 | [`app/executor.py`](app/executor.py) |
| 碳 | Scope 1/2/3、强度、方法学档案、SHA-256 文档哈希 | [`app/carbon.py`](app/carbon.py) |
| 账本 | 追加式哈希链、每次渲染即校验、重算=新增 revision | [`app/ledger.py`](app/ledger.py) |
| Watchdog | 心跳超时 → 中断 → 最多重试 3 次 → 带着问题升给人 | [`app/runtime.py`](app/runtime.py) |
| 飞书桥 | 第 5 个 Source：验签 → 去重 → 指令/Trigger → 结果回到同一会话 | [`app/feishu.py`](app/feishu.py) |
| 面板 | 7 个 App、中英切换、SSE 实时 | [`web/app.js`](web/app.js) |

## 七个 App

| App | 看什么 |
| --- | --- |
| **Console** 控制台 | 你说的话就是 Trigger；回来看工单与报告 |
| **Cockpit** 雾化舱 | 3 个舱的 EC/pH/水/能耗曲线与阈值线；注入异常、记录采收、因子更新 |
| **Tickets** 工单 | 每张工单的 Mandate（policy 版本 + 哈希 + scope + 强度）、assignment、步骤、产物 |
| **Ledger** 碳账本 | 批次总量、Scope 2/3 占比、链上每行哈希、链完整性 |
| **Dossier** 方法学 | 版本、边界、因子状态、失效条件、**不可对外**的红框 |
| **Feishu** 飞书桥 | 通道/白名单/事件订阅地址、指令表、入站出站流水、模拟发消息 |
| **Audit** 审计 | 事件流、副作用队列、Watchdog 中断次数、Outbox 回执、策略切换 |

## 飞书怎么接

```powershell
$env:FEISHU_APP_ID="cli_xxx"; $env:FEISHU_APP_SECRET="xxx"
$env:FEISHU_VERIFICATION_TOKEN="xxx"; $env:FEISHU_ALLOW="ou_xxxxxxxx"
python app/server.py
```

事件订阅地址填 `https://<公网域名>/api/feishu/events`，订阅 `im.message.receive_v1`，权限 `im:message` + `im:message:send_as_bot`，**Encrypt Key 留空**（本构建不含 AES）。没有公网地址时用**轮询模式**：`FEISHU_POLL=1`（默认），5 秒拉一次会话历史，不需要隧道。完整步骤、指令表、时序与排障见 [`docs/005-feishu.md`](docs/005-feishu.md)。

群里的一句话 → Trigger → 工单 → Worker → 结果回到**同一条会话**；同一线程上已有人在办工单时，追加的指令作为 Input 扇出，不新开单；工单在等人时，你的下一句话会唤醒它。

## 访问令牌（面板与 API）

首次启动会生成 `var/auth.env`（gitignored），控制台打印一行 `panel token generated → …`。面板会要求粘贴一次，存在浏览器 localStorage；API 用 `Authorization: Bearer <token>` 或 `?token=`。

```powershell
# 自己指定而不是自动生成
$env:COSA_AUTH_TOKEN="your-own-long-token"
python app/server.py --port 8787
```

豁免的只有三个无数据端点：飞书 webhook（用它自己的验签 + Verification Token）、`/api/health`、`/api/feishu/ping`。没有 token 时 `/api/state` 返回 401。

## 轮换密钥（不重启）

```powershell
# 改 var/llm.env 或 var/feishu.env，然后：
curl -X POST http://127.0.0.1:8787/api/secrets/reload -H "Authorization: Bearer <token>"
# 返回 {variables, mode, llm_key: "…c73b", feishu: {...}}
```

## 导出（PDF / Zenodo 包）

面板 Ledger 每行有 `PDF` 与 `Zenodo zip`；也可直接下载：

```
GET /api/export/batch/B-2026-11.pdf     # 一页纸，含逐项足迹、链头、不可外声明
GET /api/export/batch/B-2026-11.zip     # methodology/dossier/footprint/ledger/batch + README
```

PDF 用纯 Python 手写（无依赖、文本可 grep），zip 里带 `README.txt`（哈希 + 复核命令 + DOI 占位），审阅者不需要我们的软件就能复核。

## 访问令牌 / 导出 / 轮换 的自测

```powershell
python tools/feishu_doctor.py --deep   # 飞书侧
python tests/export_smoke.py           # PDF 结构 + zip 内容 + 免责声明
```

## 切真模型（Worker 由模型规划，而不是模板）

```ini
# var/llm.env（gitignored，启动自动加载）
DEEPSEEK_API_KEY=sk-xxxxxxxx
DSH_LLM_MODEL=deepseek-chat                  # 可选
# DSH_LLM_URL=https://api.deepseek.com/chat/completions   # 任意 OpenAI 兼容端点
```

```powershell
python app/server.py --live
```

面板顶栏会从 `mock` 变成 `live · deepseek-chat`；`mandate` / `report` / `scope` 的规则完全不变，只有 Worker 的计划和措辞来自模型。**默认永远是 mock**——只有显式加 `--live` 才走模型；key 无效时那张工单会变成 `blocked` 并附一句修法，不会静默降级、也不会假装成功。

先用 20 token 验一下 key 和端点：`python tools/llm_probe.py`（返回 `[ok] model=… tools accepted=True` 即可）。

不带 key 也能验这条链路：`python tests/live_smoke.py` 用一个本地 OpenAI 风格 stub 跑完「模型选择工具 → 执行 → report」，证明 live 循环是通的。

## 清空演示数据

```powershell
pwsh -File run.ps1 -Reset     # 备份 var/state.db → var/backups/，保留 feishu.env 与 llm.env
```

## 测试

```powershell
python tests/smoke.py        # 内核 + 飞书 45 项断言：全链路、扇出、幂等、验签、去重、白名单、轮询游标、链校验与篡改检测
python tests/live_smoke.py   # live planner：模型选工具 → 执行 → report（含 401 降级路径）
python tests/feishu_media_smoke.py  # multipart 上传 + interactive 卡片 + 文件消息
python tests/export_smoke.py        # PDF 结构 + Zenodo 包内容 + 免责声明
node   tests/ui_smoke.mjs    # 七个视图的无浏览器渲染校验（DOM stub + 真实快照，需服务已启动）
```

`smoke.py` 用临时 `var/smoke-*` 目录，不碰你的演示状态。

## 目录

```
app/        store · policy · engine · executor · carbon · ledger · sim · feishu · runtime · server
web/        index.html · os.css · app.js          （单页桌面式面板，无框架）
docs/       001 框架映射 · 002 架构与接口 · 003 路线图 · 004 方法学口径 · 005 飞书桥
tests/      smoke.py · ui_smoke.mjs
tools/      feishu_doctor.py（体检：还缺什么）、feishu_probe.py（token / chats / send）
var/        运行时状态（state.db + tickets/<id>/ + feishu.env），可整体删除重来
```

飞书凭据放 `var/feishu.env`（gitignored），启动自动加载；`tools/feishu_probe.py token` 一秒验证凭证是否有效。

## 边界（写在页面上，也写在这里）

- **因子未核证**：`app/carbon.py` 里每个因子都带 `status=unverified` 与 `replace_with`，不可用于对外碳标签。
- **数据是模拟的**：`app/sim.py` 生成传感器读数，面板有 `simulated` 徽章；真实部署见 P1-4。
- **飞书回调不支持加密**：设了 Encrypt Key 会被 400 拒绝并提示——标准库没有 AES，请留空或前置代理；出站只发文本，失败不自动重试（`feishu_out.status=failed` 可见）。
- **单机单用户**：没有鉴权、没有多租户，默认只监听 `127.0.0.1`。要暴露到网络，先做 P1-1（公网 webhook 至少要有 HTTPS + Verification Token + 反向代理）。
- **Worker 是同进程线程**：每个工单有独立目录与 scope 检查，但没有 OS 级隔离；生产应换子进程/容器。
- **不做**：自建推理、通用 Agent 框架、自动对外碳声明、区块链。理由见 [`docs/003-roadmap.md`](docs/003-roadmap.md)。

## 来源与致谢

- 架构依据：DeepSeek Harness 团队《Super-agent 设计探索：迈向更自主的 Agent 系统》（2026-10-31）及其开源原型 [`deepseek-ai/dsh-superagent-prototype`](https://github.com/deepseek-ai/dsh-superagent-prototype)（MIT）。本仓库只复用其**概念与规则**，未复制代码。
- 分享链接 `chat.deepseek.com/share/r8rfqu3ltx2a5mjdug` 在构建时返回 **HTTP 403**（CloudFront 拦截），无法读取会话原文；因此本系统按该团队公开的框架文档实现，未引用该会话内容。若需要对齐会话里的具体结论，把文本贴进来即可增量修正。
- 碳核算式与因子出处见 [`docs/004-methodology.md`](docs/004-methodology.md)；飞书事件、指令与验签见 [`docs/005-feishu.md`](docs/005-feishu.md)。

## 许可

代码 MIT。方法学文档与因子表以 CC BY 4.0 提供，**且仅限 draft 用途**。
