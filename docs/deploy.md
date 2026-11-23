# 部署与自定义域名

## 现状（2026-11-23 17:05 实测）

| 项 | 值 |
| --- | --- |
| 仓库 | `erikcywong/shinae.work`（public） |
| Pages 源 | `main` 分支 `/docs`，`.nojekyll` |
| **自定义域名** | **www.shinae.work**（`protected_domain_state: verified`） |
| HTTPS | **已强制**（http → https 301 自动升级） |
| 站点 | **https://www.shinae.work/** → 200，标题 `shinae.work — Coffee Super-Agent OS` |
| 文档页 | https://www.shinae.work/deploy.md → 200 |
| 裸域 | `http://shinae.work` → 200，最终跳到 `https://www.shinae.work/`；`https://shinae.work` 仍 404（见下） |

DNS（阿里云 HiChina，`dns17/dns18.hichina.com`，到期 2026-12-24）：

```
shinae.work      A      185.199.108.153 / .109.153 / .110.153 / .111.153
www.shinae.work  CNAME  erikcywong.github.io
```

## 历史：为什么之前绑不上

GitHub 曾返回 `The custom domain www.shinae.work is already taken`：域名被另一个 GitHub 账号声明过
（本账号下 72 个 Pages 仓库逐一核对均未占用）。2026-11-23 通过 **Settings → Pages → Verify domain**
加 TXT 记录完成认领后，绑定成功。占用者的账号名可以从当时的 TXT 记录名读出：
`_github-pages-challenge-<owner>.shinae.work`。

## 操作命令

```powershell
# 绑定并强制 HTTPS
pwsh -File tools/set_pages_domain.ps1 -Domain www.shinae.work -EnforceHttps

# 解绑
pwsh -File tools/set_pages_domain.ps1 -Domain ""

# 查看状态
gh api repos/erikcywong/shinae.work/pages --jq '{cname,https_enforced,status,protected_domain_state}'
```

Pages 会自动把域名写进 `docs/CNAME`（仓库里会多一个 `Create CNAME` 提交），不要手改该文件。

## 已知遗留：裸域 https 404

GitHub Pages 的自定义域名是 `www.shinae.work`，因此：

- HTTP 访问裸域会被 GitHub 301 到 `https://www.shinae.work/`（已实测 200）
- 但 `https://shinae.work` 没有对应证书 → 直接 404

两种修法，任选其一：

1. **DNS 转发（推荐）**：阿里云 DNS → 域名解析 → 添加「URL 转发」，主机记录 `@`，目标
   `https://www.shinae.work/`，转发类型选 **301 显性**。
2. **以裸域为主域名**：把 Pages 自定义域名改成 `shinae.work`，GitHub 会自动把 `www` 301 到裸域——
   但这会让规范域名变成不带 www 的形式，与当前要求相反。

## 边界

- GitHub Pages 只能托管静态文件；Python 内核（面板、飞书回调、账本、导出）仍在本机或自己的服务器上运行。
- 想让内核也对外可用，需要一台带持久磁盘的小服务器（Fly.io / Render / 轻量云主机）+ 反向代理，
  并把飞书事件订阅指到那台机器的 `/api/feishu/events`。
