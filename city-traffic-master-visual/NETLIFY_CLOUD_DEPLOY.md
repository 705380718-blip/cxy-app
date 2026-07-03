# Netlify 云端存储部署说明

本版本已加入 Netlify Functions + Netlify Blobs：

- 前端点击“云同步”后输入玩家名。
- 登录时会把当前浏览器本地城市数据合并同步到云端一次。
- 之后保存、新建、删城、恢复会继续同步到云端。
- 城市 JSON 存在 Netlify Blobs 的 `city-traffic-master-cities` store。

## 重要

只拖 `dist/` 到 Netlify Drop 会发布静态页面，但不会部署 `netlify/functions/` 后端函数。

要启用云端存储，请用 Git 连接部署，或在本目录运行 Netlify CLI：

```bash
npm install
npx netlify login
npx netlify link
npx netlify deploy --prod
```

已有站点时，`npx netlify link` 选择你的 `rad-jalebi-7a035c` 项目。

Netlify 会读取 `netlify.toml`：

```toml
[build]
  publish = "dist"
  command = "npm run build"

[functions]
  directory = "netlify/functions"
```
