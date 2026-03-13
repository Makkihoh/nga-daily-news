# NGA 国际新闻速报

自动抓取 NGA 国际新闻杂谈板块 (fid=843) 热帖，生成静态新闻速报页面。

## 功能

- 每 6 小时自动从 NGA 抓取最新帖子列表
- 按回复数排序取 Top 10 热帖
- 抓取每个帖子的精选评论
- 生成美观的静态 HTML 页面
- 自动部署到 GitHub Pages

## 数据流

```
NGA API → fetch_and_build.py → index.html → GitHub Pages
```

## 设置

1. Fork 本仓库
2. 在仓库 Settings → Secrets 中添加 `NGA_COOKIE`（你的 NGA 登录 Cookie）
3. 在 Settings → Pages 中启用 GitHub Actions 部署
4. 工作流会自动每 6 小时运行一次

## 手动触发

在 Actions 页面点击 "Run workflow" 可手动触发更新。
