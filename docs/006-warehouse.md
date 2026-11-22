# 006 · 咖啡仓存 Super-agent（生豆 / 熟豆）

> 一句话：这其实不是"再做一个仓储系统"，而是把**一次库存变更**做成一件可复核的事——
> 计划 → Critic 硬校验 → dry-run → 第二个人批准 → 落库 → 核验账实 → 写进哈希链。
> 飞书负责"让人在群里看见并拍板"，Agent 负责"不让人绕过规则"。

- 版本：wh v1（2026-11-22）
- 代码：`app/warehouse.py` · 面板 `web/warehouse.html` · 测试 `tests/wh_smoke.py`（内核为本地原型，源码按需提供；公开页见 [`warehouse.html`](warehouse.html)）
- 运行：`python app/server.py` → `http://127.0.0.1:8787/warehouse.html`（与碳核证面板同一个内核、同一个 token）
- 边界：原型；非 WMS；不对外签发碳标签；环境阈值为**示例且未核证**；演示数据为合成数据。

---

## 1. 来源与取舍

本模块实现自一份 DeepSeek 分享会话（两轮）：

| 轮次 | 会话里做了什么 | 本仓库落成了什么 |
| --- | --- | --- |
| 1 | 按"库存是现金/质量/交付/追溯"规划咖啡生豆+熟豆仓储 Agent：批次、库位、FIFO/FEFO、温湿度、盘点、补货、审批 | 领域层 `warehouse.py`：9 个批次、3 个库位、6 个 SKU 的完整规则与状态机 |
| 2 | 升级为 Super-agent：Supervisor + 专家 Agent + 事件驱动 + 规则引擎 + 飞书（消息/审批/多维表格/任务/日历/文档/事件订阅） | Supervisor/Critic/Verifier 编排、事件扫描、飞书指令与卡片按钮、`/api/wh/*` |

会话里的一张架构图不够用，落地时只保留了三件能验证的东西：**确定性规则、审批闸门、审计链**。
LLM 在本模块里**不决定数量、分配顺序、审批人**——它只在 `--live` 模式下润色 `report` 措辞
（沿用 `app/executor.py` 的 Worker，本模块本身不调用任何模型）。

> 分享链接 `chat.deepseek.com/share/ih3poi7utpn2g1bb51` 直连返回 **HTTP 403**（CloudFront），
> 内容是经只读镜像读取的；会话里的结论按上表映射，未逐字复制。

**口径确认（2026-11-22，Erik）**：① "与飞书拼" = 协作，不是替代 → §5 按协作写；
② 环境阈值**尚未核证** → 全部保持 `status=unverified`，不升级、不引用；
③ 公开发布范围 = `os.shinae.work` 只放能力说明页（静态快照），内核与源码留在本地。

---

## 2. 架构：同一个 kernel，第二个垂直域

```
飞书群 / 面板 / API
   │  /wh out R-V60 20 · 卡片按钮 · POST /api/wh/out
   ▼
Supervisor（app/warehouse.py）
   ├─ Planner    plan_outbound / plan_inbound / purchase_plan   ← 纯函数，可重放
   ├─ Critic     critic_outbound：sku/数量/单位/库存/临期/隔离/…
   ├─ Dry-run    逐批 before→after、安全库存警告
   ├─ Gate       approve(task, actor)：四眼原则 + --force 留痕
   ├─ Executor   _apply()：唯一写 wh_lot.qty_kg 的入口（幂等键）
   ├─ Verifier   consistency()：lot 缓存 == move 账本；verify_task()：哈希链
   └─ Reflector  _reflect()：低库存 / 盘点漂移 → 告警
   ▼
SQLite：wh_lot · wh_move · wh_task · wh_audit · wh_env · wh_alert · wh_inbound
```

碳核证域（`app/engine.py`）与仓存域共用：`Store`、`Policy`（来源白名单）、`FeishuBridge`、
token 鉴权、SSE、`event` 表。两域互不写对方的表。

### 2.1 不变量（破坏即 bug）

| # | 不变量 | 由谁保证 |
| --- | --- | --- |
| I1 | `wh_lot.qty_kg` == Σ `wh_move.delta_kg` | `_apply()` 单写入口 + `consistency()` |
| I2 | 非 `released` 或已过 `best_before` 的批次永不被选中 | `eligible()` + `critic` 双保险 |
| I3 | 同一 `idem` 只落一次 | `wh_move.idem UNIQUE` |
| I4 | 申请人 ≠ 批准人（除非 `--force`，且写入链） | `approve()` |
| I5 | 每个任务的 plan→critic→dryrun→approval→execute→verify 都有哈希行 | `_audit()` |
| I6 | 拦截态（`blocked`）不产生任何 move | `submit_*` 与 `approve()` 的 stage 检查 |

### 2.2 写操作状态机

```
submit ──► awaiting_approval ──approve──► done ──verify──► (reflect → alert?)
   │                │
   │                └─reject──► rejected
   └─critic 失败──► blocked（可修参数后重新提交，不撤销历史）
```

每个任务固定 4–7 行审计：`plan.created` → `critic.evaluated` → `dryrun.computed` →
`approval.requested|blocked` → `approval.granted|rejected` → `executed` → `verified`。
`--force` 会多一行 `four_eyes.waived`。

---

## 3. 领域规则

| 规则 | 生豆 green | 熟豆 roast |
| --- | --- | --- |
| 默认出库策略 | FIFO（入库日升序） | FEFO（best_before 升序） |
| 可出库条件 | `status=released` 且未过 `best_before` | 同左 + 赏味期未过 |
| 库位 | WH-G（恒温库） | WH-R（阴凉库） |
| 隔离 | WH-Q，物理隔离；隔离中的批次不可出库 | 同左 |
| 安全库存 | 按 SKU（G-ET 200 / G-BR 300 / G-CO 120 kg） | 按 SKU（R-ESP 15 / R-V60 10 kg） |
| 临期 | — | 10 天内告警；FEFO 自动优先 |
| 入库校验 | 水分 8–13 %（warn）、库位与品类匹配 | 必须有 `roast_at`；库位必须是 WH-R |
| 补货口径 | 安全库存 − 现有 − 在途 | 再加 14 天用量；覆盖 < 7 天即建议 |

**环境阈值（示例，`status=unverified`）**：绿咖啡 15–25 °C / 50–65 %RH；熟豆 15–25 °C / 40–60 %RH。
页面、`/wh env`、`/wh scan`、快照 `env.note` 四处都写明"示例、未核证"。
2026-11-22 确认：**阈值尚未核证**，因此不升级为正式口径、不用于任何对外声明；
改成企业标准前，自动隔离任务只生成"待审批"，不会自动执行。

---

## 4. 飞书集成

### 4.1 指令（群里 @bot 或单聊）

| 指令 | 行为 | 写库存？ |
| --- | --- | --- |
| `/wh` | 概览：绿/熟库存、待审批、告警、临期、账实一致性 | 否 |
| `/wh stock [green\|roast]` | 批次清单与是否可出库 | 否 |
| `/wh lot L-ET-2605` | 批次详情 + 最近流水 | 否 |
| `/wh out G-ET 120 [fifo\|fefo]` | 生成出库计划 → Critic → 卡片送审 | 审批后 |
| `/wh in G-ET 300 WH-G 11.2` | 入库送审（新批次号在批准时才创建） | 审批后 |
| `/wh approve <任务> [备注] [--force]` | 审批（四眼） | 是 |
| `/wh reject <任务> [备注]` | 驳回 | 否 |
| `/wh scan` | 立即巡检：环境告警 + 自动生成隔离任务 | 否（任务待审） |
| `/wh expire [天]` | 熟豆临期扫描 | 否 |
| `/wh stocktake <批次> <实盘kg>` | 盘点差异送审 | 审批后 |
| `/wh buy` | 补货建议送审 | 审批后只出采购草单 |
| `/wh verify <任务>` / `/wh consistency` | 校验哈希链 / 校验账实 | 否 |
| `/wh tasks` / `/wh alerts` / `/wh env` | 列表类 | 否 |

### 4.2 事件与回调

- 订阅 `im.message.receive_v1`（文字指令）→ 已有 `FeishuBridge.handle_webhook`。
- 订阅 **`card.action.trigger`**（卡片按钮）→ 新增 `FeishuBridge._handle_card_action`：
  点击"批准/驳回"**不绕过** `approve()`，仍走四眼、dry-run、哈希链；申请人自己点会被拒。
- 审批、任务、多维表格、日历、云文档的写入**本构建未做**（见 §9）；目前出站只有文本/卡片，
  由 `feishu_out` 表留痕，`sim` 通道不真发。

### 4.3 卡片长什么样

`card_for_task()` 生成：标题（⏳/⛔/✅ + 任务名）→ 计划摘要（策略、批次、before→after、警告）→
`批准` / `驳回` 两个按钮（`value={"wh_action":"approve","task":"wht_…"}`）→ 脚注（任务号、
"阈值未核证"）。卡片发送失败会自动降级为纯文本，结果不会因为卡片格式问题丢失。

### 4.4 凭据与权限（示例，以飞书后台实际名称为准）

```
FEISHU_APP_ID / FEISHU_APP_SECRET
FEISHU_VERIFICATION_TOKEN     # 校验每个回调
FEISHU_ALLOW=feishu:ou_xxx    # 或面板里 /api/feishu/allow 加白
```

权限：`im:message`、`im:message:send_as_bot`；卡片按钮需开启交互卡片能力。
**Encrypt Key 留空**（本构建无 AES，见 `docs/005-feishu.md`）。
没有公网地址时用轮询模式（`FEISHU_POLL=1`，默认），5 秒拉一次会话历史。

---

## 5. 与飞书协作：优势怎么拼

> 口径已确认（2026-11-22）：这里的"拼"是 **working together / collaborate**，不是替代。
> 飞书是"人已经在的地方"，本系统是"规则与证据在的地方"。

### 5.1 能力矩阵

| 能力 | 飞书原生 | 本系统 | 结论 |
| --- | --- | --- | --- |
| 群内指令、卡片、@bot | 强（消息卡片、机器人） | 复用飞书，自己只出卡片 JSON | **用飞书** |
| 多人审批、催办、抄送 | 强（审批中心） | 四眼 + dry-run + 哈希链，单层或双人 | 飞书做流程，Agent 做闸门 |
| 表格录入、看板、视图 | 强（多维表格） | 无 UI 表格编辑器 | **用飞书录数**，不回写主台账 |
| 任务分派到人 | 强（任务） | 只生成"该做什么"，不负责人事 | 组合 |
| 日历（到货、盘点窗口） | 强 | 只给日期建议 | 组合 |
| 知识库 / SOP | 强（云文档） | 审计链可回放，但不成文 | 组合 |
| 跨批次追溯（谁、何时、为什么改数量） | 弱 | **强**：move 账本 + 哈希链 | **用本系统** |
| 领域硬规则（FEFO/FIFO、临期、隔离、单位） | 弱（要靠人） | **强**：Critic 拦截并给理由 | **用本系统** |
| 幂等与并发扣减 | 无 | `idem` 唯一键 + 单写入口 | **用本系统** |
| 离线/无凭据演示 | 需真实租户 | `sim` 通道全链路可跑 | **用本系统** |

### 5.2 三条组合原则

1. **人机分工按"不可逆性"切**：只读查询随便问；一旦改数量，必须过 Critic + 第二个人。
2. **台账只有一个版本**：数量以 `wh_move` 为准，飞书多维表格只做现场录入与看板，禁止双写。
3. **规则不进聊天记录**：FEFO、临期、安全库存写在代码与测试里，不靠 prompt 约束模型。

### 5.3 什么情况下别用这套

- SKU < 20、无批次/赏味期要求、一个人管库：**多维表格 + 审批** 就够了，别上 Agent。- 需要财务过账、税务发票、多组织结算：接 ERP，本系统只做"仓储动作闸门"。
- 需要对外碳标签/原产地证明：本系统明确不做（见 `docs/004-methodology.md` 的不可外声明）。

### 5.4 一句话对比

飞书把"人拉到一个地方做事"做到极致；这套东西补的是**"做事之后还能证明发生了什么"**。
两者不是替代关系，缺一个都会退化成"群里说一声就改了库存"。

---

## 6. 自动化机制（哪里真的省人）

| 机制 | 触发 | 人还要做什么 |
| --- | --- | --- |
| 环境巡检 | 后台每 300 s（`WH_SCAN_INTERVAL_S`）或 `/wh scan` | 审批隔离任务 |
| 临期扫描 | 同上 / `/wh expire` | 决定降价或 FEFO 优先出库 |
| 安全库存告警 | 出库执行后 `_reflect()` | 审批补货建议 |
| 隔离建议 | 环境超限自动生成任务（每库位去重） | 审批 |
| 盘点差异 | 提交盘点即出差异与比例 | 审批过账 |
| 补货建议 | `/wh buy` 或面板按钮 | 审批 → 生成采购草单 |
| 审计与账实校验 | 每次审批自动写链、自动校验 | 抽查 |

**不做自动执行的部分**：任何 `out` / `in` / `adjust` / `quarantine` 都必须有人批准。
这是产品决定，不是能力不足。

---

## 7. KPI（先定口径，再谈数字）

本仓库不虚构现状值，下表是**目标口径**：

| KPI | 口径 | 目标 |
| --- | --- | --- |
| 账实一致率 | `consistency().ok` 为真的时间占比 | 100 %（不一致即告警） |
| FEFO/FIFO 合规率 | 出库批次顺序符合策略的订单占比 | ≥ 99 % |
| 临期损耗率 | 过期 kg / 入库熟豆 kg | < 2 % |
| 环境异常 MTTA | 读数超限 → 首个审批动作 | < 30 min |
| 审批平均时长 | `approval.requested` → `approval.granted` | < 2 h |
| 库存准确率 | 盘点一致批次 / 盘点批次 | ≥ 98 % |
| 人工接管率 | 需人工重规划的任务 / 总任务 | < 10 % |
| 报表工时 | 每周手工整理时长 | 降 80 % |

---

## 8. 路线图

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| P0 | 领域内核、FIFO/FEFO、Critic、四眼、审计链、面板、`/wh` 指令 | **已交付** |
| P1 | 飞书审批实例/任务/多维表格写入（需真实租户 + 权限） | 未做，接口已留 `notify()` |
| P1 | 真实传感器接入（替换 `wh_env` 种子，保留 `source` 字段） | 未做 |
| P2 | 与碳域联动：批次出库 → 运输里程 → Scope 3 增量 | 未做 |
| P2 | 供应商质量记忆（到货水分/缺陷率 → 入库建议） | 未做 |
| P3 | 需求预测（按渠道销量 → 烘焙计划 → 生豆补货） | 未做 |

---

## 9. 运行与测试

```powershell
python app/server.py                      # 8787，面板 /warehouse.html
python app/server.py --port 8791 --var var/wh-demo-run

python tests/wh_smoke.py                  # 领域 + 审批 + 审计链 + 飞书（45 项左右断言）
node   tests/wh_ui_smoke.mjs              # 面板 9 个视图无浏览器渲染（服务需在 8791）
python tests/smoke.py                     # 碳核证域回归，必须仍然全绿
```

`/api/wh/*` 端点：`state` `out` `in` `approve` `reject` `scan` `expire` `stocktake`
`purchase` `verify` `consistency` `card` `command`。写端点返回 `plan` + `critic` + `dryrun`，
不隐藏任何一步。

---

## 10. 边界（写在页面上，也写在这里）

- **原型，不是 WMS**：无多仓调拨网络、无序列号/货架位精细管理、无财务过账。
- **阈值未核证**：`ENV_PROFILE` 全部 `status=unverified`，示例值不能当合规依据。
- **数据是合成的**：`DEFAULT_LOTS` / `_seed_env()` 生成；接入真实系统前不要拿数字对外。
- **单机单用户 token**：与碳核证面板同一 token；没有角色体系，四眼靠 actor 字符串，属于**演示级**约束，
  生产需要接 SSO/RBAC。
- **哈希链只证明本机写入顺序**：不是外部时间戳、不是第三方见证；删库重建等于重来。
- **模型不参与决策**：本模块不调用 LLM；`--live` 只影响碳域 Worker 的措辞。
- **飞书写入只做了一半**：卡片与文本出站已通；审批实例/多维表格/日历/文档未接（P1）。
