# 001 · 框架映射：DeepSeek Super-agent → Coffee Super-Agent OS

**一句话本质：这不是再造一个 agent 框架，而是把 Super-agent 的「注意力经济学 + Router/Worker 双层 + 事件驱动 + 存算分离 + Watchdog」装进一个雾化咖啡农场。**
农场是天然的 Source 富矿（每 12 秒一次读数、每次采收、每次电网因子变更），而人（Erik）只有有限注意力。系统的价值不是"多干活"，而是**把每一份需要人注意的东西压到最低，把每一份不需要人的东西做干净并留痕**。

## 1. 引用的框架（外部事实，非本仓库发明）

DeepSeek Harness 团队 2026-10-31 发布《Super-agent 设计探索：迈向更自主的 Agent 系统》并开源
[`deepseek-ai/dsh-superagent-prototype`](https://github.com/deepseek-ai/dsh-superagent-prototype)。其文档给出的骨架是：

| 框架部件 | 原型里的说法 | 本仓库的对应物 |
| --- | --- | --- |
| 双层架构 | Router 承接人类与多渠道消息并分派；Worker 各自持有独立上下文与目录 | `engine.py`（Router/Eval/Ticket）+ `executor.py`（Worker 会话、独立目录、受限工具） |
| 事件驱动 | Source 产出 Trigger，Thread 串起来，Eval 批量研判 | `intake()` → `thread` → `passes()` → `evaluate_thread()` |
| 面向人的交互 | 只在"必须有人行动"或"结果可用"时说话；一次只问一个结构化问题 | `report()` / `attention()`：`blocked|failed` 才升问题，`ready` 只回一句结果 |
| 计算、状态、环境分离 | 状态在 Store，执行在 Executor 会话与目录，可重启恢复 | SQLite `state.db` + `var/tickets/<id>/` + `_resume_after_restart()` |
| Watchdog | 外部看门狗，卡住就重启并留下恢复说明 | `_watchdog_loop`：心跳超时 → `engine.interrupt()` → 最多重试 3 次 → `blocked` 并升给人 |
| 域模型 | Source / Trigger / Thread / Eval / Decision / Mandate / Ticket / Assignment / Channel / Policy / Subscription | 同名同义，见下表 |

域模型与原型 `docs/001-domain.md` 的对照（只保留本系统真正用到的部分）：

| 概念 | 原型定义要点 | 本系统实现 | 代码位置 |
| --- | --- | --- | --- |
| Source | 事件流；一个 kind + 一个实例配置；自己保存读位置 | `aero` / `field` / `carbon` / `brand` 四个 source id | `policy.py` `sources` |
| Trigger | 不可变的单个事件，带 actor；同一事件接两次只产生一个工单 | `trigger` 表 + `intake()` 幂等写入 | `store.py`, `engine.py` |
| Thread | 按时间排的 Trigger 序列；同时最多一个 Eval | `thread.key`（`aero/cabin-A1` 等），`queued` 计数 | 同上 |
| Eval / Gate / Assessment | 准入是确定性的（谁可发起），研判是模型的 | `Policy.gate()` 确定性；`Policy.match_rule()` 规则研判；`MockPlanner`/`LivePlanner` 只做执行 | `policy.py` |
| Decision | accept / stop / ignore / unavailable | `decision` 表，含 `reason` 与 `strength` | `engine.py` |
| Mandate | 授权：策略版本、范围、强度、依据规则；不可变 | `ticket.mandate` JSON：`policy_version`、`policy_hash`、`scope`、`rule`、`via` | `policy.py:mandate()` |
| Ticket | 授权工作的单位；只由 Eval 创建 | `ticket` 表；Worker 无权创建 | `engine.py` |
| Assignment | 工单与某个执行器实例的绑定；pending→running→ended | `assignment` 表，含 `attempts`、`heartbeat_at` | `engine.py` |
| Channel | Thread 的写侧；多种写（回执、答复、结果） | `outbox` 表 + `reply` effect，`channel=panel` | `engine.py:reply()` |
| Policy | 版本化规则 + 每个 Source 的白名单；版本一变，跑着的 Eval 重来 | `policy` 表逐版本存储并哈希；`policy_changed()` 通知在办工单 | `policy.py`, `engine.py` |
| Effect | 事务内登记、提交后执行的持久副作用队列 | `effect` 表 + `_effects_once()`，失败的指数退避重试 | `runtime.py` |
| Outbox | 每条消息一张回执，同一 id 永不重复入队 | `outbox.id` 唯一 + `reply()` 先查后写 | `engine.py` |
| Report | progress / waiting / ready / blocked / failed / dropped | 六态同原型；`ready|dropped` 结束工单 | `engine.py:report()` |
| Attention | 等人回答的问题 | `attention:{ticket_id}` 回执 + 面板置顶计数 | `engine.py:attention()` |

## 2. 领域适配（这是本仓库自己的判断，不是原型的内容）

| 框架中立概念 | 咖啡 × 碳语境下的具体形态 |
| --- | --- |
| Source | ① `aero`：雾化舱 IoT（EC/pH/水温/RH/PPFD/kWh）；② `field`：田间与采收日志；③ `carbon`：电网因子/方法学变更的登记处推送；④ `brand`：品牌与审阅者提问（面板控制台）；⑤ `feishu`：飞书群消息——同一个内核，入口换成群，身份按 Source 本地隔离 |
| Trigger | 阈值越界、采收入库、因子更新、人的一句话 |
| Gate 的三条准入 | 来源开着、发起人白名单、规则命中；未命中 → `ignore/no_rule`，不惊动人 |
| 主动工作 | 只有 `brand.proactive` 一条推断规则；`mode=record` 时只记录 `would_accept` 不建工单（原型 philosophy 的"先只看它会做什么"） |
| Worker 工具 | `telemetry.read`、`carbon.compute`、`ledger.append`、`dossier.render`、`file.write`、`report`，逐个过 Mandate `scope` 检查 |
| 人的注意力预算 | 面板只在三处要求人：`blocked/failed` 的问题、待办工单、策略变更；其余自动留痕在 ticket 目录里 |

## 3. 明确不做的（避免"看起来像"）

| 没做 | 为什么 | 什么时候做 |
| --- | --- | --- |
| 真实 GitHub 连接器 | 本系统的 Source 是传感器、碳登记处与飞书群，不是代码仓库 | P2 若要把 PR 审阅接进来 |
| 飞书卡片消息与文件上传 | 文本消息已够"下指令 / 收结果"；卡片是表现层优化 | P1：卡片模板 + 文件上传 |
| 多租户与鉴权 | 单机单人创作工具，先要跑通闭环 | P1：`tenant_id` + token，前置条件是路由层重写 |
| Prompt 版本编辑面板 | 原型的 004-prompts 是一等公民；本系统先用规则 + 固定 prompt | P2 |
| 第三方核证因子库 | 没有授权数据源，硬编会造假 | P1：接 Ecoinvent/CLCD 或供应商 EPD |
| 真正的 LCA 建模（过程树、分配、截断） | v0.1 只做批次级 cradle-to-gate 手算，边界写在档案里 | P2 |

## 4. 与原型一致的三条硬规矩

1. **Engine 是唯一写者**：Trigger/Thread/Decision/Ticket/Assignment 只有 `engine.py` 写。
2. **Worker 只能报告**：`report` 是 Worker 影响工单的唯一入口；工具越界即 `ToolError`，错误进 transcript。
3. **策略版本随 Mandate 走**：工单记录它被接受时的 policy 版本与哈希；策略变更不撤销 Mandate，只发 Input 通知（原型 `policyEffects` 的简化版）。
