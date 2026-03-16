# NGA 综合速报（多板块）

自动抓取 NGA 论坛多个板块热帖，生成带 Tab 切换的多板块静态速报页面。

## 覆盖板块

| 板块 | fid | 说明 |
|------|-----|------|
| 🌍 国际新闻杂谈 | 843 | 国际时事、军事、地缘政治 |
| 📈 大时代 | 706 | 股票、基金、金融市场讨论 |

## 功能

- 每 6 小时自动从 NGA 抓取多个板块的最新帖子列表
- 每板块按回复数排序取 Top 10 热帖
- 抓取每个帖子的精选评论
- DeepSeek AI 生成摘要（无 API Key 时自动降级为文本摘要）
- 生成带 Tab 切换的多板块静态 HTML 页面
- 自动部署到 GitHub Pages

## 数据流

```
NGA API (多板块) → fetch_and_build.py → index.html (Tab 切换) → GitHub Pages
```

## 设置

1. Fork 本仓库
2. 在仓库 Settings → Secrets 中添加：
   - `NGA_COOKIE` — 你的 NGA 登录 Cookie
   - `DEEPSEEK_API_KEY` — DeepSeek API Key（可选，用于 AI 摘要）
3. 在 Settings → Pages 中启用 GitHub Actions 部署
4. 工作流会自动每 6 小时运行一次

## 手动触发

在 Actions 页面点击 "Run workflow" 可手动触发更新。

## 新增板块

在 `scripts/fetch_and_build.py` 的 `BOARDS` 列表中添加新条目即可：

```python
BOARDS = [
    {"fid": 843, "name": "国际新闻", "icon": "🌍", ...},
    {"fid": 706, "name": "大时代·股票", "icon": "📈", ...},
    # 新增板块只需加一行
]
```
