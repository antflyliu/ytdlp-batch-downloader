# WeChat API Proxy — Cloudflare Worker

通过 Cloudflare Worker 代理微信公众号 API 请求，解决本地动态 IP 无法加入微信 IP 白名单的问题。

## 原理

```
本地应用 → Cloudflare Worker (你的 workers.dev) → api.weixin.qq.com
```

Worker 的出口 IP 来自 Cloudflare 已公布的 IP 段。将这些 IP 段一次性添加到微信公众号白名单后，
无论本地 IP 如何变化，都能正常调用微信 API。

## 部署步骤

### 1. 安装 Wrangler CLI

```bash
npm install -g wrangler
```

### 2. 登录 Cloudflare

```bash
wrangler login
```

### 3. 生成一个随机认证 Token

用于保护你的 Worker 不被未授权访问：

```bash
# 生成随机 token（可用任何方式生成，保证足够随机即可）
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

记录下生成的 token 值。

### 4. 部署 Worker

```bash
cd cloudflare-worker/wechat-api-proxy
wrangler deploy
```

部署成功后会输出 Worker URL，如：`https://wechat-api-proxy.<your-name>.workers.dev`

### 5. 设置 Worker 环境变量

```bash
wrangler secret put PROXY_TOKEN
# 输入上面生成的 token 值
```

### 6. 配置微信公众号 IP 白名单

登录微信公众号后台 → 设置与开发 → 基本配置 → IP 白名单，添加以下 Cloudflare IP 段：

```
103.21.244.0/22
103.22.200.0/22
103.31.4.0/22
104.16.0.0/13
104.24.0.0/14
108.162.192.0/18
131.0.72.0/22
141.101.64.0/18
162.158.0.0/15
172.64.0.0/13
173.245.48.0/20
188.114.96.0/20
190.93.240.0/20
197.234.240.0/22
198.41.128.0/17
```

> IP 段来源：https://www.cloudflare.com/ips-v4/
> 这些 IP 段是 Cloudflare 全球网络的公开地址，变动极少。

### 7. 在本地应用中配置代理

打开 Web 管理界面 → 设置 → 微信公众号发布 → API 代理：

- **Cloudflare Worker 代理地址**：填入 Worker URL（如 `https://wechat-api-proxy.yourname.workers.dev`）
- **代理认证 Token**：填入步骤 3 生成的 token

保存后，所有微信 API 请求会自动通过 Worker 代理，不再受本地 IP 变化影响。

## 费用

Cloudflare Workers 免费额度：每天 100,000 次请求。个人公众号发布场景远低于此限制。

## 安全性

- Worker 使用 Bearer Token 认证，未携带正确 token 的请求会被拒绝
- Token 存储在 Cloudflare Worker 的加密环境变量中
- AppID/AppSecret 不上传到 Worker，仍由本地应用管理
- 建议定期更换 Token

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 401 Unauthorized | Token 不匹配 | 检查本地配置的 token 与 `wrangler secret` 设置的是否一致 |
| 502 Bad Gateway | Worker 无法连接微信 API | 检查 Cloudflare 服务状态 |
| 微信仍报 IP 白名单错误 | IP 段未正确添加 | 检查微信后台白名单是否包含全部 15 个 CIDR 段 |
