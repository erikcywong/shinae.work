# 部署与自定义域名

## 现状（2026-11-23）

| 项 | 值 |
| --- | --- |
| 仓库 | `erikcywong/shinae.work`（public） |
| Pages 源 | `main` 分支 `/docs`，`.nojekyll` |
| 站点（一直可用） | https://erikcywong.github.io/shinae.work/ |
| 目标域名 | **www.shinae.work** |
| 当前绑定 | 无（`cname: null`）——`os.shinae.work` 已主动解绑，避免“域名叫 os”的误导 |
| 阻塞 | GitHub 返回 `The custom domain www.shinae.work is already taken`：该域名被**另一个 GitHub 账号**声明过（不是本账号下 72 个 Pages 仓库中的任何一个） |

DNS（阿里云 HiChina，`dns17/dns18.hichina.com`）已经指向 GitHub Pages：

```
shinae.work      A     185.199.108.153 / .109.153 / .110.153 / .111.153
www.shinae.work  CNAME erikcywong.github.io
```

所以问题不在 DNS，而在 GitHub 侧的“域名归属”。

## 三条路，按推荐顺序

### A. 认领域名（最干净，需在 GitHub 网页操作）

1. 仓库 → **Settings → Pages → Custom domain**，输入 `www.shinae.work` 保存
2. 若提示已被占用，点 **Verify domain**，GitHub 会给出形如
   `_github-pages-challenge-<owner>.shinae.work` 的 TXT 记录与令牌
3. 到阿里云 DNS 加这条 TXT（主机记录 `_github-pages-challenge-<owner>`，值 = 令牌）
4. 回 GitHub 点 **Verify**；若对方是“未验证”的占用，认领成功后即可绑定
5. 绑定成功后执行（已备好脚本）：

   ```powershell
   pwsh -File tools/set_pages_domain.ps1 -Domain www.shinae.work
   ```

   `-owner` 记下 TXT 里的 `<owner>`：它直接告诉你是哪个账号占着。

### B. 换托管（不等 GitHub，最可控）

Cloudflare Pages / Netlify / Vercel 都可直接连这个 GitHub 仓库构建 `/docs`，自定义域名走它们自己的校验，不受 GitHub Pages 的占用影响。DNS 侧把 `www` 的 CNAME 改成它们给的目标即可。

### C. 在 DNS 层做 301（最快，1 分钟）

阿里云 DNS 支持“URL 转发”：`www` → `https://erikcywong.github.io/shinae.work/`（显性/隐性转发，选 301 显性）。
用户看到的是 `www.shinae.work`，内容来自 Pages；代价是 HTTPS 证书由阿里云签发、且不是 Pages 原生绑定。

## 绑定后的收尾（脚本会做）

```powershell
pwsh -File tools/set_pages_domain.ps1 -Domain www.shinae.work -EnforceHttps
```

脚本做的事：`PUT /pages {cname}` → `PUT /pages {https_enforced:true}` → 打印 Pages 状态与 DNS 记录。域名解绑同理：`-Domain ""`。

## 边界

- GitHub Pages 只能托管静态文件；Python 内核仍在本机/服务器上跑。
- `docs/` 里的 `CNAME` 文件必须与 Pages 设置一致；改域名请用上面的脚本 + 提交，别手改。
