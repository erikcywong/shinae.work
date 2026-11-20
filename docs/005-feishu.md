# 005 · 飞书桥：四个值在哪拿，指令怎么跑

**一句话：飞书不是"通知渠道"，它是第 5 个 Source。** 群里的一句话就是一条 Trigger，走同一套 gate → Eval → Ticket → Worker；结果按报告状态回到发起它的那条会话。

本文先回答"四个值从哪来"，再给接入手册、指令表、时序与排障。

## 1. 四个值分别在哪拿

| 变量 | 在飞书开发者后台的位置 | 长什么样 | 是否必须 |
| --- | --- | --- | --- |
| `FEISHU_APP_ID` | 应用 → **凭证与基础信息** → 应用凭证 → App ID | `cli_a1b2c3d4e5f6g7h8` | 必须 |
| `FEISHU_APP_SECRET` | 同一页，App Secret（点"显示"） | 32 位随机串 | 必须 |
| `FEISHU_VERIFICATION_TOKEN` | **事件与回调** → 加密策略 → Verification Token | 随机串 | 生产必须；不填则回调不验真 |
| `FEISHU_ENCRYPT_KEY` | 同一处 Encrypt Key | 随机串 | **必须留空**（本构建无 AES） |
| `FEISHU_ALLOW` | 不是后台里的值，是**用户**的 open_id | `ou_xxxxxxxx` | 可留空，改用面板一键加入（见 §6） |

入口：企业自建应用 → [open.feishu.cn](https://open.feishu.cn)（国际版 Lark 用 [open.larksuite.com](https://open.larksuite.com)，路径一致）。没有应用就先"创建企业自建应用"，类型必须选**企业自建**。

### 1.1 一步步拿

1. 打开应用 → 左侧 **凭证与基础信息** → 复制 **App ID**、**App Secret**。
2. 左侧 **添加应用能力** → 开启 **机器人**。
3. 左侧 **权限管理** → API 权限，添加：
   - `im:message`（接收消息）
   - `im:message:send_as_bot`（以机器人身份发消息）
4. 左侧 **事件与回调** → **加密策略**：复制 **Verification Token**；**Encrypt Key 保持为空**（填了会让本系统拒绝回调并提示）。
5. 同一页 → **事件配置** → 订阅方式选 **将事件发送至开发者服务器**，请求地址填
   `https://<你的公网域名>/api/feishu/events`
   → **添加事件**：`接收消息 im.message.receive_v1`
   - 保存地址时飞书会立刻发一次 `url_verification`，所以服务器必须已经在跑、且 HTTPS 可达。
   - **不支持"长连接"模式**：本系统是 HTTP 回调；选长连接会收不到消息。
6. **版本管理与发布** → 创建版本 → 申请发布 → 企业管理员审核通过 → 在**可用范围**里把目标群/成员加进来。
7. 把机器人拉进群：群里 **@机器人** 发 `/status`（单聊不需要 @）。

### 1.2 `FEISHU_ALLOW` 那个 open_id 怎么来

三种办法，推荐第三种：

1. **面板自动捕获**（最快）：先不配 `FEISHU_ALLOW` 直接上线，让那个人在群里 @ 机器人发一句话 → 面板「飞书」App 的**入站事件**里会出现 `feishu:ou_xxxx`，点旁边的 **+ 白名单** → 生成新的 policy 版本，下一条消息就能通过。
2. **从回调原文里抄**：飞书事件 JSON 的 `event.sender.sender_id.open_id`。
3. **调接口查**：应用有通讯录读权限时，用 `contact/v3/users` 按邮箱/手机号查 `open_id`；或用"获取用户信息"接口拿当前用户。权限要额外申请，通常没必要。

> open_id 是**应用维度**的用户标识：同一个人在不同应用里 open_id 不同。别拿别的应用的 open_id 来填。

### 1.3 写成环境变量

```powershell
$env:FEISHU_APP_ID="cli_xxxxxxxx"
$env:FEISHU_APP_SECRET="xxxxxxxxxxxxxxxx"
$env:FEISHU_VERIFICATION_TOKEN="xxxxxxxx"
# $env:FEISHU_ENCRYPT_KEY  # 不要设
# $env:FEISHU_ALLOW="ou_aaaa,ou_bbbb"   # 可选；也可在面板里点 + 白名单
python app/server.py --port 8787
```

Linux/macOS：

```bash
export FEISHU_APP_ID=cli_xxxxxxxx FEISHU_APP_SECRET=xxx FEISHU_VERIFICATION_TOKEN=xxx
python3 app/server.py --port 8787
```

或者把凭据放进 **`var/feishu.env`**（已在 `.gitignore` 里，不会进仓库），服务启动时自动加载：

```ini
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx
FEISHU_VERIFICATION_TOKEN=xxxxxxxx
# FEISHU_ENCRYPT_KEY=   ← 保持注释掉
# FEISHU_ALLOW=ou_xxxx
```

启动日志会打印 `loaded N secret(s) from the local env file`。不要把这三个值写进 README、文档或提交记录。

### 1.4 用工具先自检（不用等飞书后台）

```powershell
python tools/feishu_doctor.py                      # 一次跑完：凭证、发消息、列群、读消息、本机轮询、白名单
python tools/feishu_probe.py token                 # 凭证是否有效（打印 token 长度，不打印 token）
python tools/feishu_probe.py chats                 # 机器人所在的群（需要 im:chat:readonly）
python tools/feishu_probe.py send <chat_id> "hi"   # 向指定群发一条
```

`feishu_doctor.py` 的每一行都会给出「缺什么 / 去哪加」，退出码 1 表示还有人要动手。**加完权限必须重新创建版本并发布**，权限才生效——这一点最容易漏。

常见报错直接告诉你缺哪个权限：

| 报错 | 含义 |
| --- | --- |
| `99991672 ... im:message, im:message:send_as_bot` | 应用没开消息权限，去「权限管理」加 |
| `99991672 ... im:chat:readonly` | 读群列表的权限没开（可选） |
| `230002 / chat not found` | chat_id 不对，或机器人不在该群 |
| `99991663 / tenant token invalid` | App Secret 不对，或应用已停用 |

启动后判断是否接上：面板「飞书」App 里 **通道 = api**、**app_id set**、**verification token on**；没有凭据时是 **sim**（消息只写 `feishu_out`，不会真的发）。

## 2. 两种通道，一条代码路径

| 通道 | 何时启用 | 行为 |
| --- | --- | --- |
| `api` | 配了 `FEISHU_APP_ID` + `FEISHU_APP_SECRET` | 真调开放平台：`tenant_access_token` → `im/v1/messages` |
| `sim` | 没凭据，或 `COSA_FEISHU_SIM=1` | 出站只写 `feishu_out`（标 `simulated`），入站可用面板或 `/api/feishu/simulate` 驱动 |

两条通道共用：验签 → 校验 Verification Token → 去重 → 指令/Trigger → 回写。所以没有飞书账号也能把整条链路跑完、跑测试。

## 3. 公网回调怎么来（本机没有公网 IP 时）

| 方式 | 命令 | 适用 |
| --- | --- | --- |
| Cloudflare 临时隧道 | `cloudflared tunnel --url http://127.0.0.1:8787` | 10 分钟验证，URL 每次变 |
| 反向代理 + 域名 + 证书 | nginx/caddy → `127.0.0.1:8787` | 长期使用 |
| 内网穿透（frp/nps） | 自建 | 有固定服务器时 |

拿到 `https://xxx` 后，把它拼上 `/api/feishu/events` 填进事件订阅。**注意**：暴露公网前至少要有 Verification Token；面板本身没有登录（P1-1）。

### 3.1 保存 URL 时报「请求超时」（最常见的一个坑）

飞书的服务器要在 **3 秒**内收到 `{"challenge": ...}`。超时几乎总是**链路**问题，不是代码慢：

1. 看面板「飞书」→ **入站事件** 上方是否出现 `feishu.hit` 记录。没有 → 请求根本没到我们这里，是链路；有但很慢 → 才是本机问题。
2. 本机自测（不经过飞书）：`python tools/feishu_probe.py` 之外的更直接办法——用另一台机器/手机流量打开 `https://<域名>/api/feishu/ping`，能秒回说明公网可达。
3. `*.trycloudflare.com` 这类临时隧道**从中国大陆网络经常不可达**（Cloudflare 边缘在国内质量差），飞书侧 3 秒必然超时。

两条出路，选一条：

| 方案 | 需要什么 | 延迟 | 适合 |
| --- | --- | --- | --- |
| **A. 轮询模式（已实现，无需公网）** | 只要 `im:message` + `im:chat:readonly` 权限 | 5 秒（可调） | 本机开发、笔记本、内网农场机 |
| **B. 公网回调** | 国内可达的 HTTPS 地址（国内穿透工具，或有域名的云主机 + 反代） | 实时 | 长期、多人使用 |

#### A. 轮询模式怎么开

不用配 `webhook`，也不用隧道。凭据在 `var/feishu.env` 时默认就开着（`FEISHU_POLL=1`）：

```ini
FEISHU_POLL=1
FEISHU_POLL_INTERVAL=5          # 秒，命令场景 3–5 秒够用
# FEISHU_POLL_CHATS=oc_xxx,oc_yyy   # 可选；留空则自动发现机器人所在的群（需要 im:chat:readonly）
```

工作方式：每 5 秒调一次「获取会话历史消息」`im/v1/messages?container_id_type=chat`，只取 `create_time` 之后的新消息，按 `message_id` 去重（和 webhook 共用同一张 `feishu_event` 表），然后走**完全相同**的指令/Trigger 逻辑。机器人自己发的消息按 `sender_type=app` 跳过，不会自问自答。

需要的最小权限：`im:message`（收发消息本体）+ `im:chat:readonly`（发现群）+ **`im:message.group_msg`**（读群历史；单聊需要 `im:message.p2p_msg`）。群里不需要 @ 机器人，只要它在群里。

> `im:message.group_msg` 属于敏感权限：企业若不允许自助申请，需要管理员审批；被拒时改用公网回调（B 方案）或长连接（P2）。

代价：5 秒延迟；每个群每 5 秒一次 API 调用（飞书对 `im/v1/messages` 有频控，长期用请把间隔调到 10–20 秒或改成 B）。

验收：面板「飞书」→ 配置里 `轮询 on · 5s · N cycles`，`chats` 出现群 ID；群里发 `/status`，5 秒内回。

## 4. 指令表

| 指令 | 行为 | 是否建单 |
| --- | --- | --- |
| `/help` | 指令表 | 否 |
| `/status` | 模式、策略版本与哈希、在办/已结束、待你决定、账本行数 | 否 |
| `/tickets` | 最近 8 张工单及状态 | 否 |
| `/ticket <id>` | 授权（policy 版本/强度/规则/scope）、报告、产物 | 否 |
| `/ledger [batch]` | 总量、强度、链头、链是否完整 | 否 |
| `/dossier` | 方法学版本、哈希、因子状态、**不可对外**声明 | 否 |
| `/anomaly A1\|B2\|C3` | 向雾化舱注入一次漂移 | 间接（走 aero Source） |
| `/harvest [batch]` | 记录采收，触发核算 | 是 |
| `/stop <id>` / `/retry <id>` | 人的动作：停/重试 | 否 |
| `/pause` / `/resume` | 暂停/恢复内核 | 否 |
| **任意文字** | 当作一个人的请求 → Trigger → Router 判断 | 是（或并入在办工单） |

## 5. 一次"共同执行"的完整时序

```
群里: "B-2026-11 的碳强度是多少，能不能对外报？"
  → webhook(im.message.receive_v1) → 校验 token → 验签 → event_id 去重
  → actor = feishu:ou_xxx（Source 本地身份）
  → engine.intake(source=feishu, thread=feishu/chat-<chat_id>, kind=human.message)
  → Thread 上无在办工单 → 排队 → passes() → gate 通过 → 规则 human.message 命中
  → Ticket + Mandate(policy vN, scope=[dossier.render, carbon.compute, ...]) + Assignment
  → Worker: dossier.render → carbon.compute → report(ready, summary)
  → report.recorded → bridge.on_engine_event → 回到 chat_id
群里: "✅ Human request: … / Batch B-2026-11: 1225.234 kgCO2e … / 产物：footprint-B-2026-11.json"
```

**追加指令不会新开一张单**：同一 `chat_id` 的 Thread 上有在办工单时，消息作为 Input 扇出（`fanned_out`），Worker 下次读输入时看到它。这就是"共同执行"——人随时补一句话，工作不重启、不丢上下文。

工单在等人（`blocked/failed/waiting`）时，人的下一句话会**自动唤醒**它（新 Assignment + 恢复说明）——这条既走"群里再发一句"，也走面板的「继续」按钮。

## 6. 身份与授权（最容易做错的一条）

- 飞书 `open_id` 只在 `feishu` 这条 Source 上有效，**不会**被映射成面板里的 `erik`。原型 `001-domain.md` 的规矩：跨 Source 不映射身份；需要关联时写进 prompt 文本，而不是建映射表。
- 白名单在 `policy.sources.feishu.allow`，格式 `feishu:ou_xxx`；`FEISHU_ALLOW` 只是启动时喂给策略迁移的输入（会生成新的 policy 版本，可审计）。
- **一键加入**：面板「飞书」→ 入站事件 → 未授权的那条 → `+ 白名单` → `POST /api/feishu/allow {actor}` → 新 policy 版本 + 通知在办工单。
- 工单的 Mandate 记录"这条 Source 上的谁、按哪条规则、什么强度"，审阅者拿工单号就能反查。

## 7. 已知限制

| 限制 | 影响 | 现状 |
| --- | --- | --- |
| 不支持加密回调（AES-256-CBC） | 设了 Encrypt Key，回调会被 400 拒绝并提示 | 标准库无 AES；请留空，或前置代理解密 |
| 未配 Verification Token 时无法验真 | 任何知道 URL 的人都能伪造一条来自白名单 open_id 的消息 | 面板红框警告；生产必须配 |
| 消息只发文本，不发卡片/附件 | 产物要回面板取 | P1-8：卡片模板 + 文件上传 |
| 出站失败不重试 | `feishu_out.status=failed` 可见但不会自动重发 | P1：接 Outbox 重试语义 |
| 只支持 `im.message.receive_v1` | 卡片按钮、表情回复不处理 | P2 |
| 不支持长连接订阅方式 | 选长连接会收不到消息 | 用"将事件发送至开发者服务器" |
| 面板无登录 | 能连到端口即可操作 | P1-1 |

## 8. 排障

| 现象 | 先看哪里 |
| --- | --- |
| 后台保存 URL 失败 | `curl -X POST https://<域名>/api/feishu/events -d '{"type":"url_verification","challenge":"x","token":"<token>"}'` 应回 `{"challenge":"x"}` |
| 保存 URL 报「请求超时」 | 见 3.1：先确认是否有 `feishu.hit`；多半是隧道从国内不可达 → 改用轮询模式 |
| 轮询不动 | 面板 `轮询` 行是否 on；`chats` 是否为空；错误框里的 `99991672` 说明缺 `im:chat:readonly` 或 `im:message` |
| 保存时报 403 | Verification Token 与后台不一致；或设了 Encrypt Key（本构建不支持） |
| 消息进了但没回 | 面板 → 飞书 → 入站事件 `handled=error`；再看 `feishu_out.error` |
| 机器人不回结果 | 会话是否绑定（`thread.meta.feishu_chat_id`）；工单 Thread 是否以 `feishu/chat-` 开头 |
| 身份被拒 | 白名单是否含 `feishu:ou_...`；面板 `refused` 计数；点 `+ 白名单` |
| 重复建单 | 不会：`event_id`/`message_id` 去重，见 `feishu_event` 表 |
| 签名失败 | 头 `X-Lark-Request-Timestamp/Nonce/Signature`；算法 `sha256(timestamp + nonce + encrypt_key + raw_body)` |
| 群里发了没反应 | 群里需要 **@机器人**；或应用版本未发布/不在可用范围 |

## 9. 接上之后的验收清单

按顺序打勾，任何一步不过都别往下走：

1. `python tools/feishu_probe.py token` → `app credential valid`
2. 公网地址能应答握手：向 `https://<域名>/api/feishu/events` POST `{"type":"url_verification","challenge":"x","token":"<Verification Token>"}` → 回 `{"challenge":"x"}`；token 错 → `403 verification token mismatch`
3. 飞书后台保存事件订阅地址不报错（说明第 2 步真的通了）
4. 用真实事件形状打一次公网地址（不改任何群）：
   `header.event_type=im.message.receive_v1` + `content={"text":"/status"}` → 回 `{"ok":true}`，面板「飞书」入站事件出现一条 `done`
5. 权限补齐后，群里 `@机器人 /status` → 群里收到 `mode … policy vN …`
6. 群里发一句自然语言 → 面板出现工单 → 30 秒内群里收到 `✅ …`
7. 陌生人发消息 → 入站事件 `refused` → 点 `+ 白名单` → 新 policy 版本 → 重发成功

> 第 4 步的价值：它把"公网可达 + token + 验签 + 入站解析"一次性验完，且不会惊动任何真实群。

## 10. 卡片与附件（P1-8）

工单结束时，群里收到的不再是纯文本，而是一张卡片：

```
┌ ✅ Cabin A1: root-cause drifted EC/pH … ─────────┐
│ 摘要（模型/模板写的那段结论）                      │
│ ─────────────────────────────────────────────── │
│ Policy  v6 · explicit   Ticket  tkt_9f1c…       │
│ Scope   telemetry.read, carbon.compute, …       │
│ 产物：dossier.md, footprint-B-2026-11.json       │
└─────────────────────────────────────────────────┘
```

- 状态色：`ready` 绿、`blocked/waiting` 橙、`failed` 红；`blocked/failed` 的问题会单独占一段「需要你决定」。
- **附件**：工单目录里的 `.md` / `.json` 会被上传并以文件消息发送（`transcript.md` 与超过上限的文件跳过）。
- 卡片发送失败会自动降级为纯文本（结果不会因为卡片被拒而丢）。
- 上传失败**不影响**卡片，只在面板记一条 `feishu.upload_failed`。

配置（`var/feishu.env`）：

```ini
FEISHU_UPLOAD=1              # 0 关闭附件
FEISHU_UPLOAD_MAX_KB=200     # 单文件上限
FEISHU_UPLOAD_MAX_FILES=3    # 每张工单最多几个
```

需要额外权限 **`im:resource`**（上传文件）；没有它卡片照发，附件跳过。体检：

```powershell
python tools/feishu_doctor.py --deep   # 会上传一个 40B 的 probe.txt 来验证该权限
```
