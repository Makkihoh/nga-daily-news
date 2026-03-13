#!/usr/bin/env python3
"""
NGA International News Fetcher & HTML Builder
Fetches top threads from NGA fid=843, parses replies, and generates a static HTML page.
Designed to run in GitHub Actions every 6 hours.
"""

import json
import re
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# ── Config ──────────────────────────────────────────────────────────────────
NGA_FID = 843
NGA_COOKIE = os.environ.get("NGA_COOKIE", "")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
TOP_N = 10
DELAY_SEC = 0.6
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CN_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# ── Helpers ─────────────────────────────────────────────────────────────────
def nga_request(url):
    """Make a request to NGA with proper headers."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Referer", "https://bbs.nga.cn/")
    if NGA_COOKIE:
        req.add_header("Cookie", NGA_COOKIE)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            # Try UTF-8 first, fallback to GBK
            for enc in ["utf-8", "gbk", "gb2312"]:
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}")
        return None


def clean_nga_html(text):
    """Strip HTML tags and NGA bbcode from content."""
    if not text:
        return ""
    s = str(text)
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    s = s.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    s = re.sub(r'\[/?[a-zA-Z]+[^\]]*\]', '', s)
    return s.strip()


def html_escape(text):
    """Escape HTML special characters."""
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


# ── Step 1: Fetch thread list ──────────────────────────────────────────────
def fetch_thread_list():
    """Fetch thread list from NGA and return top N by reply count."""
    print("Fetching thread list from NGA fid=843...")
    url = f"https://bbs.nga.cn/thread.php?fid={NGA_FID}&order_by=postdatedesc&__output=11"
    body = nga_request(url)
    if not body:
        return []

    data = json.loads(body)
    threads_raw = data.get("data", {}).get("__T", [])

    threads = []
    if isinstance(threads_raw, list):
        threads = [t for t in threads_raw if isinstance(t, dict) and t.get("tid")]
    elif isinstance(threads_raw, dict):
        threads = [v for v in threads_raw.values() if isinstance(v, dict) and v.get("tid")]

    # Sort by replies descending, take top N
    threads.sort(key=lambda t: int(t.get("replies", 0)), reverse=True)
    top = threads[:TOP_N]

    result = []
    for i, t in enumerate(top):
        result.append({
            "rank": i + 1,
            "tid": t["tid"],
            "subject": t.get("subject", ""),
            "author": t.get("author", ""),
            "replies": int(t.get("replies", 0)),
        })

    print(f"  Found {len(threads)} threads, selected top {len(result)}")
    return result


# ── Step 2: Fetch thread details ───────────────────────────────────────────
def fetch_thread_detail(tid):
    """Fetch a single thread's replies."""
    url = f"https://bbs.nga.cn/read.php?tid={tid}&__output=11&page=1"
    body = nga_request(url)
    if not body:
        return None, []

    data = json.loads(body)
    replies_raw = data.get("data", {}).get("__R", [])

    reply_list = []
    if isinstance(replies_raw, list):
        reply_list = [r for r in replies_raw if isinstance(r, dict)]
    elif isinstance(replies_raw, dict):
        reply_list = [v for v in replies_raw.values() if isinstance(v, dict)]

    main_content = ""
    interesting = []
    first = True
    for r in reply_list:
        content = clean_nga_html(r.get("content", ""))
        if first:
            main_content = content
            first = False
        else:
            if 10 < len(content) < 500:
                score = int(r.get("score", 0)) if r.get("score") else 0
                interesting.append({
                    "content": content,
                    "score": score,
                    "author": str(r.get("author", "")),
                    "lou": str(r.get("lou", "")),
                })

    interesting.sort(key=lambda x: x["score"], reverse=True)
    return main_content, interesting[:10]


# ── Step 3: Build HTML ─────────────────────────────────────────────────────
def build_html(threads_data, now):
    """Generate the full HTML page."""
    date_str = now.strftime("%Y年%-m月%-d日") if os.name != "nt" else now.strftime("%Y年%m月%d日")
    weekday = CN_WEEKDAYS[now.weekday()]
    time_str = now.strftime("%H:%M")
    total_replies = sum(t["replies"] for t in threads_data)

    # Determine tags based on subject keywords
    def get_tags(subject):
        tags = []
        kw_map = [
            (["美国", "美军", "美帝", "川普", "特朗普", "白宫", "五角大楼", "中期选举", "共和党", "民主党"], "美国"),
            (["伊朗", "波斯", "霍尔木兹", "哈梅内伊", "德黑兰"], "伊朗"),
            (["日本", "自卫队", "签证", "东京"], "日本"),
            (["中东", "以色列", "犹太", "黎巴嫩", "巴勒斯坦", "哈马斯", "真主党"], "中东"),
            (["俄罗斯", "乌克兰", "俄军", "俄乌"], "俄乌"),
            (["军事", "航母", "导弹", "战斧", "空袭", "轰炸", "海军"], "军事"),
            (["选举", "政治", "翻盘", "投票"], "政治"),
        ]
        for keywords, tag in kw_map:
            if any(kw in subject for kw in keywords):
                tags.append(tag)
        return tags[:3] if tags else ["国际"]

    cards_html = ""
    for t in threads_data:
        rank = t["rank"]
        rank_class = f"r{rank}" if rank <= 3 else "normal"
        heat_tag = {1: "最热", 2: "超热", 3: "冲击"}.get(rank, "热门" if rank <= 6 else "")
        heat_class = "hot" if rank <= 3 else "warm"

        tags = get_tags(t["subject"])
        tags_html = ""
        if heat_tag:
            tags_html += f'<span class="tag {heat_class}">{heat_tag}</span>'
        for tag in tags:
            tags_html += f'<span class="tag blue">{html_escape(tag)}</span>'

        # Comments section
        comments_html = ""
        if t.get("top_replies"):
            items = ""
            for i, c in enumerate(t["top_replies"]):
                content = html_escape(c["content"])
                # Truncate very long comments
                if len(content) > 120:
                    content = content[:117] + "..."
                items += f'        <div class="comment"><span class="cnum">#{i+1}</span>{content} <span class="score">+{c["score"]}</span></div>\n'
            comments_html = f"""    <details class="comments-toggle">
      <summary>查看精选评论 <span class="comment-count">{len(t["top_replies"])} 条</span></summary>
      <div class="comments-body">
{items}      </div>
    </details>"""
        else:
            comments_html = '    <div class="no-comments">* 评论数据暂未获取</div>'

        summary = html_escape(t.get("summary", t["subject"]))

        cards_html += f"""
<!-- #{rank} -->
<div class="card">
  <div class="card-inner">
    <div class="card-top">
      <div class="rank {rank_class}">{rank}</div>
      <div class="card-title"><a href="https://ngabbs.com/read.php?tid={t['tid']}" target="_blank">{html_escape(t['subject'])}</a></div>
    </div>
    <div class="meta"><span>{html_escape(t['author'])}</span><span class="replies">{t['replies']} 回复</span></div>
    <div class="tags">{tags_html}</div>
    <div class="summary">
      <span class="key-point">要点：</span>{summary}
    </div>
{comments_html}
  </div>
</div>
"""

    # Build overview bullets from top threads
    overview_items = ""
    for t in threads_data[:6]:
        overview_items += f'    <li><strong>{html_escape(t["subject"][:15])}...</strong> -- {html_escape(t["subject"])}</li>\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NGA 国际新闻速报 - {date_str}</title>
<style>
:root{{
  --bg:#F0EAD6;
  --row-white:#FFFDF5;
  --row-tint:#F5F0E0;
  --card-hover:#FFF8E8;
  --border:#D5CAB1;
  --border-light:#E0D6C0;
  --accent:#486A84;
  --accent-dark:#2B3E50;
  --hot:#C0392B;
  --warm:#D4780A;
  --green:#27763D;
  --text:#333333;
  --text-dim:#555555;
  --text-muted:#888888;
  --tag-bg:rgba(72,106,132,0.1);
  --link:#3B5998;
  --head-bg:#7EB4A0;
  --head-dark:#5A9A82;
  --tab-bg:#E8E0CC;
  --table-head:#8FC0A8
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Microsoft YaHei","PingFang SC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);line-height:1.7;font-size:14px}}
.banner{{background:var(--tab-bg);border-bottom:1px solid var(--border)}}
.banner-inner{{max-width:880px;margin:0 auto;padding:0 16px}}
.banner-tabs{{display:flex;gap:0;border-bottom:none}}
.banner-tab{{padding:8px 18px;font-size:13px;color:var(--text-dim);background:var(--tab-bg);border:1px solid var(--border);border-bottom:none;border-radius:4px 4px 0 0;cursor:pointer;margin-right:-1px;position:relative;top:1px}}
.banner-tab.active{{background:var(--row-white);color:var(--text);font-weight:700;border-bottom:1px solid var(--row-white);z-index:1}}
.header{{background:linear-gradient(160deg,rgba(43,62,80,0.92) 0%,rgba(52,73,94,0.85) 50%,rgba(72,106,132,0.8) 100%);padding:0;position:relative;overflow:hidden}}
.header-content{{max-width:880px;margin:0 auto;padding:28px 24px 22px;display:flex;align-items:center;gap:24px;position:relative;z-index:1}}
.header-logo{{width:80px;height:80px;border-radius:12px;background:rgba(255,255,255,0.12);display:flex;flex-direction:column;align-items:center;justify-content:center;flex-shrink:0;border:2px solid rgba(232,200,114,0.35);box-shadow:0 2px 8px rgba(0,0,0,0.15);backdrop-filter:blur(4px)}}
.header-logo .nga-text{{font-size:22px;font-weight:900;color:#E8C872;letter-spacing:1px;line-height:1}}
.header-logo .nga-cn{{font-size:9px;color:rgba(255,255,255,0.7);margin-top:3px;letter-spacing:0.5px}}
.header-info{{flex:1}}
.header-info h1{{font-size:22px;font-weight:700;color:#fff;letter-spacing:1px;text-shadow:0 1px 3px rgba(0,0,0,0.3);margin-bottom:4px}}
.header-info .sub{{font-size:13px;color:rgba(255,255,255,0.65);letter-spacing:0.3px}}
.header-stats{{display:flex;gap:16px;flex-shrink:0}}
.header-stat{{text-align:center;background:rgba(255,255,255,0.1);border:1px solid rgba(232,200,114,0.3);border-radius:8px;padding:10px 16px;min-width:72px;backdrop-filter:blur(4px)}}
.header-stat .val{{font-size:22px;font-weight:800;color:#E8C872;text-shadow:0 0 8px rgba(232,200,114,0.2)}}
.header-stat .label{{font-size:10px;color:rgba(255,255,255,0.55);letter-spacing:0.5px;margin-top:1px}}
.container{{max-width:880px;margin:0 auto;padding:20px 16px 40px}}
.section-head{{font-size:14px;font-weight:700;color:#fff;margin:20px 0 12px;padding:8px 14px;background:linear-gradient(135deg,var(--accent-dark),var(--accent));border-radius:4px;display:flex;align-items:center;gap:8px}}
.section-head .dot{{width:5px;height:5px;border-radius:50%;background:#E8C872;flex-shrink:0}}
.overview{{background:var(--row-white);border:1px solid var(--border-light);border-radius:6px;padding:20px 22px;margin-bottom:20px}}
.overview h3{{font-size:14px;color:var(--accent-dark);margin-bottom:10px;font-weight:700;padding-bottom:8px;border-bottom:1px solid var(--border-light)}}
.overview ul{{list-style:none;padding:0}}
.overview li{{padding:4px 0 4px 18px;position:relative;font-size:13px;color:var(--text-dim);line-height:1.8}}
.overview li::before{{content:'\\25B8';position:absolute;left:2px;color:var(--warm);font-size:11px}}
.overview li strong{{color:var(--text)}}
.card{{border:1px solid var(--border-light);border-radius:6px;margin-bottom:10px;overflow:hidden;transition:all .2s;background:var(--row-white)}}
.card:hover{{border-color:var(--accent);box-shadow:0 2px 8px rgba(72,106,132,0.12);background:var(--card-hover)}}
.card-inner{{padding:18px 20px}}
.card-top{{display:flex;align-items:flex-start;gap:12px;margin-bottom:10px}}
.rank{{min-width:30px;height:30px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:800;flex-shrink:0;border:1px solid}}
.rank.r1,.rank.r2,.rank.r3{{background:#FFF0F0;color:var(--hot);border-color:#FFCCCC}}
.rank.normal{{background:var(--row-tint);color:var(--accent);border-color:var(--border)}}
.card-title{{font-size:15px;font-weight:700;color:var(--text);line-height:1.5;flex:1}}
.card-title a{{color:var(--link);text-decoration:none}}
.card-title a:hover{{color:var(--hot);text-decoration:underline}}
.meta{{display:flex;gap:12px;font-size:12px;color:var(--text-muted);margin-bottom:10px;flex-wrap:wrap;align-items:center}}
.meta .replies{{color:var(--warm);font-weight:700}}
.tags{{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px}}
.tag{{font-size:10.5px;padding:2px 9px;border-radius:3px;font-weight:600;letter-spacing:0.3px}}
.tag.hot{{background:#FFE5E5;color:var(--hot);border:1px solid #FFCCCC}}
.tag.warm{{background:#FFF2DC;color:var(--warm);border:1px solid #F0D8A8}}
.tag.blue{{background:rgba(72,106,132,0.08);color:var(--accent);border:1px solid rgba(72,106,132,0.2)}}
.tag.green{{background:#E5F3E8;color:var(--green);border:1px solid #B8D8BE}}
.summary{{font-size:13px;color:var(--text-dim);line-height:1.85;padding:12px 14px;background:var(--row-tint);border-radius:4px;border-left:3px solid var(--border)}}
.summary .key-point{{color:var(--text);font-weight:700}}
.comments-toggle{{margin-top:8px}}
.comments-toggle summary{{cursor:pointer;font-size:12px;color:var(--accent);padding:6px 12px;border-radius:4px;background:var(--row-tint);border:1px solid var(--border-light);transition:all .15s;user-select:none;list-style:none;display:flex;align-items:center;gap:6px}}
.comments-toggle summary::-webkit-details-marker{{display:none}}
.comments-toggle summary::before{{content:'';display:inline-block;width:0;height:0;border-left:5px solid var(--accent);border-top:3.5px solid transparent;border-bottom:3.5px solid transparent;transition:transform .2s;flex-shrink:0}}
.comments-toggle[open] summary::before{{transform:rotate(90deg)}}
.comments-toggle summary:hover{{background:#E8E0CC;border-color:var(--accent)}}
.comments-toggle summary .comment-count{{font-size:10px;color:var(--text-muted);margin-left:auto}}
.comments-body{{padding:10px 0 2px;animation:fadeIn .25s ease}}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(-4px)}}to{{opacity:1;transform:translateY(0)}}}}
.comment{{font-size:12.5px;color:var(--text-dim);padding:7px 10px;margin-bottom:4px;border-radius:4px;background:var(--row-white);border:1px solid var(--border-light);border-left:3px solid var(--border);line-height:1.6;position:relative;padding-right:48px}}
.comment .score{{position:absolute;top:7px;right:8px;font-size:10px;color:var(--accent);font-weight:700}}
.comment:hover{{background:var(--row-tint);border-left-color:var(--accent)}}
.comment .cnum{{font-size:10px;color:var(--text-muted);opacity:0.6;margin-right:5px}}
.no-comments{{font-size:12px;color:var(--text-muted);opacity:0.6;padding:8px 14px;margin-top:8px;font-style:italic}}
.footer{{text-align:center;padding:28px 20px;color:var(--text-muted);font-size:11px;border-top:1px solid var(--border);letter-spacing:0.3px;background:var(--tab-bg)}}
.footer a{{color:var(--link);text-decoration:none}}
.footer a:hover{{text-decoration:underline}}
.footer p+p{{margin-top:3px}}
@media(max-width:640px){{
  .header-content{{flex-direction:column;text-align:center;gap:14px}}
  .header-stats{{justify-content:center}}
  .header-logo{{width:64px;height:64px}}
  .header-logo .nga-text{{font-size:18px}}
}}
</style>
</head>
<body>
<div class="banner">
  <div class="banner-inner">
    <div class="banner-tabs">
      <div class="banner-tab active">国际新闻</div>
      <div class="banner-tab">热帖精选</div>
      <div class="banner-tab">每日速报</div>
    </div>
  </div>
</div>
<div class="header">
  <div class="header-content">
    <div class="header-logo">
      <span class="nga-text">NGA</span>
      <span class="nga-cn">国际新闻</span>
    </div>
    <div class="header-info">
      <h1>NGA 国际新闻速报</h1>
      <div class="sub">{date_str} {weekday} | NGA 国际新闻杂谈板块 (fid=843)</div>
    </div>
    <div class="header-stats">
      <div class="header-stat"><div class="val">{len(threads_data)}</div><div class="label">热点话题</div></div>
      <div class="header-stat"><div class="val">{total_replies}</div><div class="label">总讨论</div></div>
      <div class="header-stat"><div class="val">{len(set(t for tags in [get_tags(td["subject"]) for td in threads_data] for t in tags))}</div><div class="label">涉及领域</div></div>
    </div>
  </div>
</div>

<div class="container">

<div class="section-head"><div class="dot"></div>今日要闻速览</div>
<div class="overview">
  <h3>国际局势摘要</h3>
  <ul>
{overview_items}  </ul>
</div>

<div class="section-head"><div class="dot"></div>热帖详情 &amp; 精选评论</div>
{cards_html}
</div>

<div class="footer">
  <p>NGA 国际新闻速报 | 自动生成于 {now.strftime("%Y-%m-%d %H:%M")} (UTC+8)</p>
  <p>数据来源: <a href="https://ngabbs.com/thread.php?fid=843" target="_blank">NGA 国际新闻杂谈板块 (fid=843)</a></p>
  <p style="margin-top:6px;opacity:0.6">本报告由 GitHub Actions 自动抓取并生成，每 6 小时更新一次</p>
</div>
</body>
</html>"""
    return html


def get_tags(subject):
    """Helper for tag counting in header stats."""
    tags = []
    kw_map = [
        (["美国", "美军", "美帝", "川普", "特朗普", "白宫", "五角大楼", "中期选举", "共和党", "民主党"], "美国"),
        (["伊朗", "波斯", "霍尔木兹", "哈梅内伊", "德黑兰"], "伊朗"),
        (["日本", "自卫队", "签证", "东京"], "日本"),
        (["中东", "以色列", "犹太", "黎巴嫩", "巴勒斯坦", "哈马斯", "真主党"], "中东"),
        (["俄罗斯", "乌克兰", "俄军", "俄乌"], "俄乌"),
        (["军事", "航母", "导弹", "战斧", "空袭", "轰炸", "海军"], "军事"),
        (["选举", "政治", "翻盘", "投票"], "政治"),
    ]
    for keywords, tag in kw_map:
        if any(kw in subject for kw in keywords):
            tags.append(tag)
    return tags[:3] if tags else ["国际"]


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    print(f"=== NGA Daily News Builder === {now.strftime('%Y-%m-%d %H:%M')} UTC+8")

    if not NGA_COOKIE:
        print("WARNING: NGA_COOKIE not set. Requests may fail or return limited data.")

    # Step 1: Fetch thread list
    threads = fetch_thread_list()
    if not threads:
        print("ERROR: No threads fetched. Exiting.")
        return

    # Step 2: Fetch details for each thread
    for t in threads:
        tid = t["tid"]
        print(f"  Fetching thread #{t['rank']}: {t['subject'][:30]}... (tid={tid})")
        main_content, top_replies = fetch_thread_detail(tid)
        t["main_content"] = main_content or ""
        t["top_replies"] = top_replies
        t["summary"] = t["subject"]  # Use subject as summary fallback
        time.sleep(DELAY_SEC)

    # Step 3: Generate HTML
    html = build_html(threads, now)

    out_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nHTML written to: {out_path}")
    print(f"File size: {os.path.getsize(out_path)} bytes")


if __name__ == "__main__":
    main()
