# 007 · 雾化咖啡种植 Super-agent（第三个垂直域）

**版本** `0.1.0` · 2026-11-22 · 代码 `app/grow.py` · 面板 `web/grow.html` · 测试 `tests/grow_smoke.py`
**来源会话** `chat.deepseek.com/share/4tm4ifxlchkksetj0e`（直连 403，经只读镜像取到原文，见 §1）
**一句话** 把「雾化咖啡种植」从一段架构话术，变成一条可跑、可验、可审计的链：
**物候 CPM → 舱内读数 → 确定性 Critic → 四眼审批 → 执行 → 哈希链 → 飞书回话**，并接上已有的仓存域。

---

## 1. 会话说了什么，哪些成立

会话（DeepSeek 侧）给的是一套 **MVP 脚手架**：飞书机器人收 `/cpm BATCH001` → Harness 调 CPM Agent →
IoT 模拟器上报温湿度/根区湿度/雾滴粒径 → 超阈值推卡片 → 高风险指令走飞书审批 → 结果写多维表格。
技术栈建议 FastAPI + Docker + Redis/TimescaleDB + Mosquitto + networkx + lark-oapi + ngrok。

判定（按"能否在本仓库被验证"分类）：

| 会话主张 | 判定 | 处理 |
| --- | --- | --- |
| CPM 管物候排程，算关键路径与总浮动 | **成立且是核心** | 实现为真正的正推/逆推，见 §4；但**修掉了它的一个硬伤**：示例任务是纯线性链（外植体消毒→接种→…→采摘），线性链上总浮动恒为 0，关键路径恒等于全链，CPM 等于装饰。本实现加入并行支路 **V2 树冠整形（21 d）∥ R1 根系更新（14 d）**，R1 因此有 7 d 浮动，关键路径才可能移动 |
| 安全边界（EC/pH/温度…）+ 越界拦截 | **成立** | 落成 `BOUNDS` + 确定性 Critic；阈值标 `unverified`（会话给的数值本身没有出处） |
| 高风险动作走飞书审批 | **成立** | 四眼原则 + 申请人不能自批（除非 `--force`，且写进哈希链） |
| IoT 模拟器上报 | **成立** | `gw_sample` 一张表，`tick()` 与真实网关写同一张表 |
| 多维表格当台账 | 方向对，成本被低估 | 本仓库台账是 SQLite + 哈希链（可离线复核）；Bitable 同步列为 P1（要 tenant token + 字段映射） |
| FastAPI/Docker/Redis/Postgres/Mosquitto/networkx/lark-oapi/ngrok | **不采纳** | 见 §2 末：为了演示一条 CPM 链引入 7 个服务，违反本仓库"零依赖、一个写者、可断点复跑"的约束；CPM 40 行标准库实现已可复现 |
| "我不能直接在你的环境创建" | **本次被推翻** | 已在本仓库落地可运行内核 + 面板 + 测试；但保留同一句边界：不驱动真实 PLC、不承诺产量 |

**一句话反转**：这不是"给种植加一个聊天机器人"，而是**把"什么时候能推进下一个物候期"变成一个有证据、有签名、可反查的判断**。

## 2. 映射表（会话条目 → 本仓库落点）

| 会话里的东西 | 本仓库落点 | 怎么验 |
| --- | --- | --- |
| `cpm_agent.compute_cpm()`（networkx） | `grow.cpm()` 自写正推/逆推，确定性 tie-break | `python tests/grow_smoke.py` · `cpm:` 断言 |
| `data/cpm_tasks.json`（线性链） | `STAGES` DAG（含并行支路） | 同上 · `R1 float = 7.0` |
| `safety.SAFE_BOUNDS` | `grow.BOUNDS`（8 个参数，含单步上限 `step`） | `critic:` 断言 |
| 飞书 `/cpm`、`/iot` | `/gw cpm`、`/gw set`、`/gw advance`、`/gw harvest`、`/gw scan`、`/gw q` | `feishu:` 断言 |
| FastAPI `main.py` 事件回调 | 复用已有 `app/server.py`（`/api/grow/*`、`/api/feishu/events`）与轮询模式（不需要 ngrok） | `python app/server.py` |
| `feishu_client.send_text` | 复用已有 `app/feishu.py`（含卡片、去重、白名单、出站队列） | `feishu: grow card enqueued` |
| 审批（`approval_code`） | 本仓库的审批是**状态机 + 四眼**（不依赖飞书审批实例），卡片按钮走同一闸门 | `feishu: card click …` 断言 |
| 多维表格台账 | `gw_task` / `gw_audit` / `gw_harvest` + `/api/grow/state` | 面板 Audit 页 |
| 采收 → 仓存 | 采收通过后自动生成**仓存入库单**（第二个人仍要审批，四眼不合并） | `harvest: 61.5 kg landed in G-BR` |

## 3. 领域模型

- **工作单元**：`批次 × 雾化舱 × 物候期`（不是"舱"，也不是"订单"）。
- **一个批次可以同时处在两个阶段**：`V2 树冠整形` 与 `R1 根系更新` 并行；`gw_batch.stage` 只报"最靠后的活跃阶段"，
  展示层用 `active_label()` 显示 `V2+R1`。
- **不可逆动作三个**：
  1. **推进物候期** —— 轮子转过去就回不来（回退只能新建批次并写依据）；
  2. **改配方/设定点** —— 一次改动作用于整舱根系；
  3. **采收** —— 果实离开舱，变成库存。
- **保护性动作走 fail-safe**：`quarantine()` 立即执行（停雾化只减少执行），但照样记账、照样告警。
  闸门是为了拦住"增加风险"的动作，不是为了拦住"减少风险"的动作。

## 4. CPM 口径（审阅者会拿计算器反推）

- 节点 = 物候阶段；边 = 依赖；工期 = 计划天数（基线）或**剩余工期**（现状）。
- 正推：`ES = max(EF(deps))`，`EF = ES + d`；逆推：`LF = min(LS(succ))`，`LS = LF - d`；
  总浮动 `TF = LS - ES`；`|TF| < 1e-6` 记为关键。
- **剩余工期**：已完成阶段记 0；进行中 = `max(0, plan_days - 已用天数)`；未开始 = `plan_days`。
  所以"预测完工"是**从今天起算**的日期，不是项目起始日。
- **漂移** = 预测完工日期 − 基线完工日期（基线 = `started_at + 基线总工期`），单位天；
  `|漂移| ≥ 3 d` 或关键路径变化 → 告警。示例子：`CB-C3-01` 因 V1 拖 6 d、V2 拖 3 d、F3 已逾 5 d，漂移 **+14 d**。
- 基线总工期 **296 d**（P0 7 + V1 90 + V2 21 + F1 35 + F2 10 + F3 21 + F4 70 + F5 28 + H1 14）；
  R1 14 d 在 V2 之后并行，浮动 **7 d**。
- **这些天数是示例排程，不是品种标定。** 换品种必须同时改 DAG、`min_days` 与证据窗口，并在本文档记 changelog。

## 5. 闸门表

| 动作 | 检查 | 阻断/警告 | 依据 |
| --- | --- | --- | --- |
| 改设定点 | `bounds` 值在区间内 | 阻断 | `BOUNDS`（unverified） |
| | `jump` 单次变化 ≤ step | 阻断 | 防一步到位把根区打穿 |
| | `fresh_data` 15 分钟内有样本 | 阻断 | 没有新鲜读数就不许改配方 |
| | `cabin_state` 舱未隔离 | 阻断 | — |
| | `rate_limit` 24h 内 ≤ 2 次 | 阻断 | 防抖 |
| | `vpd_envelope` 变更后 VPD ∈ 0.4–1.6 kPa | **警告** | 物理量，非建议 |
| 推进阶段 | `to_pending` / `deps` | 阻断 | — |
| | `min_days.<stage>` 本阶段已过最短天数 | 阻断 | `STAGES.min` |
| | `evidence.<stage>` 窗口内样本数 ≥ need 且 ≥75% 在界内 | 阻断 | 无证据不推进 |
| | `cabin_state` | 阻断 | — |
| | 并行开启（不关阶段） | 只要求 24h 内 ≥4 条读数 | 证明舱在仪表上 |
| 采收 | `stage == H1` / `quantity > 0` | 阻断 | — |
| | `wh_sku` 品种→仓存 SKU 已映射 | 阻断 | 没有 SKU 就没有入库单 |
| | `yield_vs_target` > 目标 150% | **警告** | 不拦，叫你看一眼 |
| 审批 | 申请人 ≠ 审批人 | 阻断 | 四眼；`--force` 记 `four_eyes.waived` |
| 隔离 | 无（保护性动作） | 立即执行 + 记账 | fail-safe |

**事实只有一个版本**：`gw_setpoint` 是活值的唯一来源，`BOUNDS` 是限值的唯一来源，`gw_audit` 是"谁改了什么"的唯一来源；
面板、飞书回话、`/api/grow/state` 全部读同一处。

## 6. 飞书指令

```
/gw                       概览（批次、活跃阶段、预测完工、漂移、待审批、告警）
/gw cpm CB-A1-01          阶段表：剩余 d / ES / EF / 浮动 / 是否关键 + 关键路径 + 基线对比
/gw drift [批次]          预测完工 vs 基线，路径是否已变，本阶段是否逾期
/gw cabins                每舱最新读数、设定点、越界标红
/gw set A1 ec=2.0         配方变更 → Critic →（通过则）四眼审批
/gw advance CB-B2-01 R1   开启并行支路；不带阶段则取第一个合法后继
/gw harvest CB-C3-01 61   采收 → 生成仓存入库单（仍需第二位审批人）
/gw approve|reject gwt_x  审批；--force 会写进哈希链
/gw scan | sample | q C3  巡检 · 注入一拍读数 · 隔离（立即执行）
/gw tasks | alerts | verify gwt_x
```

## 7. 验证

```powershell
python tests/grow_smoke.py            # 69 项断言：CPM/闸门/四眼/幂等/链/飞书卡片/采收移交/快照
node   tests/grow_ui_smoke.mjs        # 面板 8 个视图（+ 英文变体）的无浏览器渲染校验（需服务在 8795）
python app/grow.py                    # 一次性演示：CPM → 拦截 → 审批 → 并行支路
python app/server.py                  # http://127.0.0.1:8787/grow.html
```

回归：`python tests/smoke.py`（45 项）、`python tests/wh_smoke.py`（仓存）、`python tests/export_smoke.py` 均须仍为绿。

## 8. 边界（写在页面上，也写在这里）

- **不驱动真实施肥/雾化 PLC**：执行是"改数据库里的设定点"，真实下发要接网关（Modbus/MQTT），协议文档到位后再换 `_execute` 里的那一行。
- **不承诺产量与品质**：`target_kg`、物候天数、证据窗口都是示例；采收只记账，不声称达标。
- **阈值未核证**：`BOUNDS_STATUS = "unverified"`，每个面都必须显示；换品种/换设备必须重新标定。
- **读数是合成的**：`source=sim.sensor`；真实接入前，曲线只用于演示闸门。
- **审计链只证明本机写入顺序**，不是外部时间戳、不是第三方见证；哈希构造与仓存域相同（`prev | sha256(body)`），一个校验器能验两条链。
- **不支持回退阶段**：要回退就新建批次并写明依据——否则"阶段"这个词就没有意义。
- **单机单用户**：没有多租户；暴露到公网前先做鉴权与 HTTPS（沿用主仓库 P1-1）。

## 9. 下一步（按值排序）

1. **P1-1 真实网关**：`gw_sample` 接 MQTT/Modbus 网关；`_execute` 下发设定点前加"读回校验"（写后 60 s 内读值必须收敛，否则告警并回滚到旧值）。
2. **P1-2 Bitable 台账**：批次、任务、漂移三张表同步；字段映射见 §2，只写不读（避免两个写者）。
3. **P1-3 采收 → 碳账本**：采收移交仓存后，把能耗/水耗带进 `carbon.compute`，让"雾化批次"有一张完整的 Scope 1/2/3 账。
4. **P2 证据升级**：把"样本在界内"升级为"样本 + 人工巡检记录 + 图像"（当前只有前者，且没有图像能力）。
