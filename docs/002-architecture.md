# 002 · 架构与接口

## 1. 分层

```
                       ┌──────────────────────────────────────────────┐
  web/ (vanilla JS)    │ Console · Cockpit · Tickets · Ledger · Dossier · Feishu · Audit │
                       └───────────────▲──────────────────────────────┘
                             SSE + REST │ /api/state, /api/stream
                       ┌───────────────┴──────────────────────────────┐
                       │ app/server.py   ThreadingHTTPServer, 零依赖  │
                       └───────────────▲──────────────────────────────┘
                       ┌───────────────┴──────────────────────────────┐
   Router 层            │ app/runtime.py   组装 + 4 个后台循环 + 飞书桥 │
                       │   passes(0.8s) effects(0.4s) watchdog(2s) sim │
                       │ app/engine.py    唯一写者：intake→eval→ticket │
                       │ app/policy.py    版本化策略、gate、规则研判   │
                       └───────────────▲──────────────────────────────┘
                       ┌───────────────┴──────────────────────────────┐
   Worker 层            │ app/executor.py  ToolBox(scope) + 两个 planner │
                       │ app/carbon.py    因子/计算/方法学/哈希         │
                       │ app/ledger.py    哈希链追加与校验              │
                       └───────────────▲──────────────────────────────┘
                       ┌───────────────┴──────────────────────────────┐
   状态                 │ app/store.py  SQLite(WAL), 单写锁, 17 张表    │
                       │ var/tickets/<ticket>/  transcript.md, findings.md, dossier.md, footprint-*.json │
                       └──────────────────────────────────────────────┘
```

## 2. 一次请求的完整生命周期

1. `POST /api/demo/anomaly` → `Sim.tick(anomaly)`：写一行 `reading`，越阈值则 `engine.intake()`
2. `intake()`：写 Trigger；Thread 上**已有 open 工单**就作为 Input 扇出（原型 Subscription 规则），否则 `thread.queued += 1`
3. `passes()`（0.8s 一轮）：对 `queued>0` 的 Thread 跑一次 Eval
4. `Policy.evaluate()`：Gate（source 开、actor 白名单）→ 规则匹配 → accept / ignore（`no_rule`、`below_threshold`、`duplicate_open_ticket`、`would_accept`）
5. accept：一个事务里建 Ticket + Mandate + Assignment，提交后 `enqueue("launch")`
6. `_effects_once()`：`launch` → `Worker.launch()`（线程 + `var/tickets/<id>/` 独立目录）
7. Worker：`assignment_started` → 心跳 → 逐步调工具（每个工具先过 scope）→ `report(state, summary, question?)`
8. `report()`：写 `report` 行、更新 `ticket.latest_report`；`ready|dropped` 即结束工单；有 `question` 则 `attention()` 入 Outbox 并在面板置顶
9. SSE 推送 `worker.step` / `report.recorded` / `ticket.ended` → 前端 350ms 去抖后拉 `/api/state`
10. 如果工单的 Thread 带 `feishu_chat_id`，`report.recorded` 会经飞书桥回写同一条会话

## 3. 数据模型（`var/state.db`，17 张表）

| 表 | 一行是什么 | 关键约束 |
| --- | --- | --- |
| `policy` | 一个策略版本 | `version` 主键，`doc` 规范化 JSON，`hash` 为 SHA-256 |
| `thread` | 一条时间线（舱/批次/区域/收件箱/飞书会话） | `queued` 计数驱动 passes；`meta.feishu_chat_id` 绑定群 |
| `trigger` | 一个不可变事件 | `disposition`: received / queued / accepted / fanned_out / ignore |
| `decision` | 一次研判 | 记录 outcome、strength、reason、ticket |
| `ticket` | 一张授权工单 | `mandate`、`scope`、`policy_version`、`dir`、`latest_report` |
| `assignment` | 一次派工 | `attempts`、`heartbeat_at`、`error` |
| `report` | 一次 Worker 报告 | 六态之一 + `question` |
| `input` | 送到工单的上下文 | `delivered` 标记（fan-out / recovery / policy / person / retry） |
| `effect` | 持久副作用 | `(kind,key)` 去重，`due_at` 退避重试 |
| `outbox` | 一条消息回执 | `id` 唯一，状态 pending / sent |
| `reading` | 一次传感器采样 | 6 个指标 + 能耗 |
| `batch` | 一个采收批次 | 活动数据（kWh、水、肥料、运费、区域） |
| `ledger_entry` | 账本的一行 | `(prev_hash, hash)` 链；`kind=computed/revision` |
| `event` | 审计事件流 | 只追加，前端时间线来源 |
| `feishu_event` | 一条入站回调 | `id` = event_id（去重）；`handled` received/done/error |
| `feishu_out` | 一条出站消息 | 状态 queued/simulated/sent/failed + `error` |

## 4. Worker 工具与授权

| 工具 | 作用 | 典型 scope 命中 |
| --- | --- | --- |
| `telemetry.read(cabin,hours)` | 聚合窗口统计 | `iot.drift.high`、`human.message` |
| `carbon.compute(batch)` | 计算并落 `footprint-<id>.json` | `harvest.recorded`、`factor.updated` |
| `ledger.append(batch)` | 追加一次哈希链 run | `harvest.recorded`、`factor.updated` |
| `dossier.render()` | 渲染方法学档案 | `harvest.recorded`、`human.message` |
| `file.write(name,content)` | 写产物到工单目录 | 全部 accept 规则 |
| `report(state,summary,question?)` | 唯一收尾方式 | 不受 scope 限制 |

越界调用 → `ToolError` → 写进 `transcript.md` 与事件流，且**不会**被静默忽略。

## 5. 副作用与重启

- `effect` 在事务内登记、提交后执行；同一 `(kind,key)` 覆盖旧 payload，失败按 `2^n` 秒退避（上限 60s）。
- 重启恢复：`pending` 的 Assignment 重新入队；`running` 的被判定为中断，走 `interrupt()`（最多 3 次，之后 `blocked` + 一个问题）。
- Watchdog：每 2s 扫 `running`，心跳超过 `watchdog_stale_s`（默认 90s）即中断；这是"卡死不算活着"的唯一判据。
- Worker 崩溃（异常）→ `report(failed, ...)`，绝不留静默。

## 6. API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/state` | 全量快照（面板唯一数据源） |
| GET | `/api/stream` | SSE：`trigger.received`、`worker.step`、`report.recorded`、`ticket.ended`、`reply` |
| GET | `/api/health` | 循环健康度 |
| GET | `/api/ticket/{id}/file?name=` | 读工单目录里的产物 |
| POST | `/api/console` | `{text}` 人说的话 → Trigger（source=brand, actor=erik） |
| POST | `/api/demo/anomaly` | `{cabin}` 注入一次漂移 |
| POST | `/api/demo/harvest` | `{batch_id?}` 采收事件 |
| POST | `/api/demo/factor` | `{region}` 因子更新事件 |
| POST | `/api/tickets/{id}/stop`·`retry`·`resume` | 人的三个动作 |
| POST | `/api/feishu/events` | 飞书事件订阅回调：验签 → challenge → 去重 → 指令/Trigger（原始字节参与签名） |
| POST | `/api/feishu/simulate` | 无凭据时驱动同一条代码路径（面板「飞书」App 用它） |
| POST | `/api/policy` | `{paused?, mode?, watchdog_stale_s?}` → 新版本 + 通知在办工单 |
| POST | `/api/secrets/reload` | 重读 `var/*.env`，热换模型 key / 飞书凭据（返回掩码后的摘要） |
| GET | `/api/export/batch/{id}.pdf` | 一页纸 PDF（纯 Python 生成，文本可 grep） |
| GET | `/api/export/batch/{id}.zip` | Zenodo 包：methodology/dossier/footprint/ledger/batch + README |
| POST | `/api/ledger/{batch}/recompute` | 追加一次 revision（不改旧行） |

鉴权：除 `/api/feishu/events`（自带验签）、`/api/health`、`/api/feishu/ping` 外，所有 `/api/*` 需要 `Authorization: Bearer <token>` 或 `?token=`；token 首次启动自动生成到 `var/auth.env`。

错误码：400 参数、404 无此对象、500 内部异常（异常会打到 stderr，不吞）。飞书回调另有 403：验签失败或 Verification Token 不匹配。

## 7. 文件索引

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `app/store.py` | 243 | schema（17 张表）、时间格式、`tx()` |
| `app/policy.py` | 273 | 默认策略、哈希、gate/rule、Mandate、策略迁移 |
| `app/engine.py` | 340 | intake/eval/ticket/report/watchdog/policy_changed |
| `app/executor.py` | 408 | ToolBox、MockPlanner、LivePlanner、Worker |
| `app/carbon.py` | 156 | 因子、计算、方法学文档 |
| `app/ledger.py` | 97 | 链式追加、校验、批次汇总 |
| `app/sim.py` | 133 | 采样状态机 + 阈值触发 |
| `app/feishu.py` | 455 | 飞书桥：验签、去重、指令、入站/出站、白名单引导 |
| `app/runtime.py` | 302 | 组装、循环、快照、动作 |
| `app/server.py` | 233 | HTTP/SSE/静态/webhook |
| `web/app.js` | 612 | 七个 App 的渲染与动作 |
| `tests/smoke.py` | 231 | 内核 + 飞书 43 项断言 |
| `tests/ui_smoke.mjs` | 69 | 无浏览器渲染校验（DOM stub + 真实快照） |
| `tools/feishu_probe.py` | 100 | 真实飞书自检：token / chats / send |
| `tools/feishu_doctor.py` | 190 | 飞书体检：逐项列出还缺什么、去哪加 |
| `tools/llm_probe.py` | 120 | 模型端点自检：key、模型名、工具调用（约 20 token） |

## 8. 为什么不用框架

零依赖是刻意的：`python app/server.py` 能跑，才可能在别人的机器上、在断网的农场里、在三年后还能跑起来。代价是 UI 要手写、路由要手写，收益是没有构建、没有版本漂移、没有 `npm install` 失败。
