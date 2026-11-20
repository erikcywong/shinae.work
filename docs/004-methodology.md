# 004 · 方法学口径 v0.1-draft（与代码逐条对齐）

> 状态：**draft，未经第三方核证，不得用于对外碳标签或交易。**
> 代码：`app/carbon.py`（因子与公式）、`app/ledger.py`（账本与校验）
> 哈希：SHA-256，输入为规范化 JSON（`sort_keys=True, separators=(",",":")`, UTF-8，不转义中文）

## 1. 边界与功能单位

| 项 | 取值 |
| --- | --- |
| 系统边界 | cradle-to-gate，到"生豆装袋、出厂"为止 |
| 功能单位 | 1 kg green coffee（screen 15+，含水率 10–12%） |
| 时间边界 | 单一批次的完整雾化栽培周期 + 采后处理 |
| GWP | IPCC AR6 GWP100，单位 kgCO₂e |
| 分配 | 共享舱月按**采收绿重**分配到批次（非面积、非收入） |
| 截断 | 单项质量占比 <1% 且足迹占比 <0.5% 的输入排除，并在档案列出 |
| 移除/抵消 | 不计入任何碳汇、抵消或避免排放 |

## 2. 计算式

对每个批次 $b$：

```
Scope 1 = 0                                  # 全电雾化舱，无现场燃烧
Scope 2 = E_kwh(b) × EF_grid(region)         # 表计电量 × 区域电网因子
Scope 3 = m_nutrient × EF_nutrient
        + m_substrate × EF_substrate
        + m_packaging × EF_packaging
        + t_km_freight × EF_freight
Total   = Scope1 + Scope2 + Scope3
Intensity = Total / kg_green                  # kgCO₂e per kg green
```

## 3. 因子表（全部 `unverified`，替换后才能对外）

| 因子 id | 值 | 单位 | 说明 | 替换为 |
| --- | --- | --- | --- | --- |
| `grid.cn.avg.2023` | 0.5366 | kgCO₂e/kWh | 全国电网平均（常被引用的值） | 批次所在省级因子或市场化工具 |
| `grid.sg.avg.2023` | 0.4168 | kgCO₂e/kWh | 新加坡电网平均 | 电力公司当年公布值 |
| `nutrient.npk.synth` | 2.34 | kgCO₂e/kg | 合成 NPK 水溶肥（cradle-to-gate），文献区间 1.9–3.2 取中值 | 供应商 EPD |
| `substrate.coir` | 0.41 | kgCO₂e/kg | 椰糠（雾化栽培可为 0） | 供应商 EPD |
| `packaging.kraft` | 1.12 | kgCO₂e/kg | 牛皮纸+铝箔复合袋 | 包材供应商因子 |
| `freight.road.tkm` | 0.105 | kgCO₂e/t·km | 公路货运（GLEC 风格默认值） | 承运人实测强度 |

**这些数字不是"查到的标准值"，是待替换的占位值。** 每个因子在代码里带 `source`、`status`、`replace_with` 三个字段，面板的 Dossier 页原样展示。

## 4. 一份核算文档长什么样

```json
{
  "methodology": "coffee-aeroponic-pcf/v0.1-draft",
  "methodology_hash": "<sha256 of METHODOLOGY>",
  "batch_id": "B-2026-11",
  "items": [{"scope":"scope2","category":"electricity","qty":2180.0,"unit":"kWh",
             "factor_id":"grid.cn.avg.2023","factor_value":0.5366,
             "factor_status":"unverified","kgco2e":1169.788}],
  "totals": {"scope1":0.0,"scope2":1169.788,"scope3":55.446,"total":1225.234},
  "intensity_kgco2e_per_kg": 29.5237,
  "warnings": ["factor set is reference-grade only ...", "cradle-to-gate only ...", "..."],
  "hash": "<sha256 of the document without `hash`>"
}
```

`computed_at` 在计算后才写入，且不参与文档哈希——同一批活动数据在任何时间重算都得到同一个 `hash`，这是复核的前提。

## 5. 账本：追加、链、复核

- 每份文档写成一次 run：每个 scope 项一行 + 一行 `total`。
- 每行 `hash = SHA256(prev_hash + canonical({batch_id, scope, kgco2e, factor_id, factor_value, note}))`，批内首行的 `prev_hash = "0"×64`。
- 重算不修改旧行：`kind=revision`，`note` 写入触发它的工单与策略版本。
- 复核：`ledger.verify(store, batch)` 重建整条链；任一行被改动，`ok=false` 并给出断点 `id`。面板每次渲染都会跑一次（批次很少，代价可忽略）。

## 6. 何时失效（写进档案，也写进规则）

1. 批次所在区域电网因子变化 → `factor.updated` Trigger 触发重算；
2. 肥料供应商或配方变化；
3. 周期中途更换基质；
4. 表计电量被估算值替代。

## 7. 边界声明（对外必须原样附带）

- 本方法学**没有**第三方核证、没有认可资质、没有登记处签发；
- 不覆盖烘焙、零售、冲煮、废弃阶段；
- 不包含碳汇、抵消、避免排放；
- 因子未核证，任何对外标签/声明在 P1-5、P2-2 完成前都不成立。

## 8. 发布路径（P1-6）

1. 冻结 `METHODOLOGY` + 因子表 → 生成 `dossier.md` 与 `methodology.json`；
2. 把 `docs/004-methodology.md`、`dossier.md`、示例批次 JSON、`verify()` 输出一起打包；
3. Zenodo 上传，拿到 DOI，把 DOI 写回 `METHODOLOGY.published_at` 与面板；
4. 任何后续改动都发新版本（`v0.2-draft`），旧 DOI 永久指向旧口径。
