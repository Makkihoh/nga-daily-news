#!/usr/bin/env python3
"""
NGA Multi-Board News Fetcher & HTML Builder
Fetches top threads from multiple NGA boards, parses replies, and generates
a static HTML page with Tab switching UI.
Designed to run in GitHub Actions every 8 hours (Mon-Sat).

Boards:
  - fid=843: International News (国际新闻杂谈)
  - fid=706: Da Shi Dai / Stock Market (大时代)
"""

import json
import re
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# ── Config ──────────────────────────────────────────────────────────────────
# 防重复：1小时内不重复执行（腾讯云触发器和GitHub schedule可能重叠）
SKIP_IF_RECENT_HOURS = 1


def check_recent_run():
    """Check if a workflow run already happened within SKIP_IF_RECENT_HOURS hours.
    Returns True if we should skip this run to avoid duplicate DeepSeek calls."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return False  # No token, can't check, proceed normally

    api_url = "https://api.github.com/repos/Makkihoh/nga-daily-news/actions/runs?per_page=1"
    req = urllib.request.Request(api_url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            runs = data.get("workflow_runs", [])
            if not runs:
                return False
            last_run = runs[0]
            # Parse the created_at timestamp
            created_at_str = last_run.get("created_at", "")
            if not created_at_str:
                return False
            last_time = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            diff = now - last_time
            hours = diff.total_seconds() / 3600
            print(f"[DEDUP] Last workflow run: {last_run.get('created_at')} ({hours:.1f}h ago), status: {last_run.get('status')}")
            if hours < SKIP_IF_RECENT_HOURS and last_run.get("status") == "completed":
                print(f"[DEDUP] Skipping — last run was {hours:.1f}h ago (< {SKIP_IF_RECENT_HOURS}h)")
                return True
    except Exception as e:
        print(f"[DEDUP] Could not check recent runs: {e}")
    return False
BOARDS = [
    {"fid": 843, "name": "国际新闻", "icon": "🌍", "section_title": "国际局势摘要",
     "link_text": "NGA 国际新闻杂谈板块"},
    {"fid": 706, "name": "大时代·股票", "icon": "📈", "section_title": "股市热点摘要",
     "link_text": "NGA 大时代板块"},
]

NGA_COOKIE = os.environ.get("NGA_COOKIE", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
TOP_N = 10
DELAY_SEC = 0.6
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CN_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# ── Tag keyword maps per board ──────────────────────────────────────────────
TAG_MAPS = {
    843: [
        (["美国", "美军", "美帝", "川普", "特朗普", "白宫", "五角大楼", "中期选举", "共和党", "民主党"], "美国"),
        (["伊朗", "波斯", "霍尔木兹", "哈梅内伊", "德黑兰"], "伊朗"),
        (["日本", "自卫队", "签证", "东京"], "日本"),
        (["中东", "以色列", "犹太", "黎巴嫩", "巴勒斯坦", "哈马斯", "真主党"], "中东"),
        (["俄罗斯", "乌克兰", "俄军", "俄乌"], "俄乌"),
        (["军事", "航母", "导弹", "战斧", "空袭", "轰炸", "海军"], "军事"),
        (["选举", "政治", "翻盘", "投票"], "政治"),
    ],
    706: [
        (["A股", "沪指", "深成指", "创业板", "上证", "涨停", "跌停", "大盘"], "A股"),
        (["美股", "纳斯达克", "道琼斯", "标普", "华尔街"], "美股"),
        (["基金", "ETF", "定投", "赎回"], "基金"),
        (["AI", "人工智能", "芯片", "半导体", "算力", "英伟达"], "AI/科技"),
        (["新能源", "锂电", "光伏", "风电", "储能"], "新能源"),
        (["房地产", "房价", "楼市", "房企"], "地产"),
        (["银行", "降息", "加息", "利率", "央行", "美联储"], "金融"),
        (["茅台", "白酒", "消费"], "消费"),
        (["医药", "医疗", "生物"], "医药"),
        (["军工", "国防"], "军工"),
    ],
}

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


def parse_nga_json(body):
    """Parse NGA response body which may not be clean JSON."""
    if not body:
        return None
    body = body.strip().lstrip('\ufeff')
    body = re.sub(r'^[a-zA-Z_][\w.]*\s*=\s*', '', body)
    body = body.rstrip(';').strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start = body.find('{')
        if start >= 0:
            depth = 0
            for i in range(start, len(body)):
                if body[i] == '{':
                    depth += 1
                elif body[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(body[start:i+1])
                        except json.JSONDecodeError:
                            break
        print(f"  WARNING: Could not parse JSON response (len={len(body)})")
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


def ai_summary(subject, content, top_replies, board_name="", fid=843):
    """Call DeepSeek API to extract highlights from a thread."""
    if not DEEPSEEK_API_KEY:
        return None

    # Build context: title + main content + top replies
    context = f"帖子标题：{subject}\n"
    if content:
        context += f"楼主正文：{content[:1500]}\n"
    for i, r in enumerate(top_replies[:5]):
        rc = r["content"][:300] if isinstance(r, dict) else str(r)[:300]
        context += f"热评{i+1}：{rc}\n"

    # Board-specific prompts for highlight extraction
    if fid == 706:
        prompt = (
            "你是一个股市资讯分析师。请根据以下NGA大时代板块的帖子信息，提炼1-2个最有价值的亮点。\n"
            "要求：\n"
            "- 重点关注：具体的行情观点、板块/个股判断、市场信号、数据分析结论\n"
            "- 如果有明确的多空观点或操作建议，优先提炼\n"
            "- 结合热评中的补充观点或争议焦点\n"
            "- 不超过120字，不要复述标题，不要用\"本帖\"\"该帖\"，直接说核心观点\n"
            "- 语气要像一个老股民在给朋友划重点\n\n"
            f"{context}"
        )
    else:
        prompt = (
            "你是一个国际新闻分析师。请根据以下NGA国际新闻板块的帖子信息，提炼1-2个最值得关注的亮点。\n"
            "要求：\n"
            "- 重点关注：关键事件进展、各方立场变化、潜在影响和后续走向\n"
            "- 结合热评中的独到分析或争议观点\n"
            "- 不超过120字，不要复述标题，不要用\"本帖\"\"该帖\"，直接说事\n"
            "- 语气要像一个资深时政记者在给读者划重点\n\n"
            f"{context}"
        )

    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 250,
        "temperature": 0.4
    }).encode("utf-8")

    req = urllib.request.Request("https://api.deepseek.com/chat/completions")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {DEEPSEEK_API_KEY}")

    try:
        with urllib.request.urlopen(req, body, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["choices"][0]["message"]["content"].strip()
            result = result.strip('"').strip('\u201c').strip('\u201d')
            print(f"    AI summary OK: {result[:60]}...")
            return result
    except Exception as e:
        print(f"    AI summary FAILED: {e}")
        return None


def html_escape(text):
    """Escape HTML special characters."""
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def get_tags(subject, fid=843):
    """Get tags for a thread subject based on board-specific keywords."""
    tag_map = TAG_MAPS.get(fid, TAG_MAPS[843])
    tags = []
    for keywords, tag in tag_map:
        if any(kw in subject for kw in keywords):
            tags.append(tag)
    default_tag = "国际" if fid == 843 else "股市"
    return tags[:3] if tags else [default_tag]


# ── Step 1: Fetch thread list (per board) ──────────────────────────────────
def fetch_thread_list(fid, board_name):
    """Fetch thread list from NGA and return top N by reply count.
    For fid=706 (大时代), filters out mega-threads (>=200 replies) to keep only fresh posts.
    """
    print(f"Fetching thread list from NGA fid={fid} ({board_name})...")
    url = f"https://bbs.nga.cn/thread.php?fid={fid}&order_by=postdatedesc&__output=11"
    body = nga_request(url)
    if not body:
        return []

    data = parse_nga_json(body)
    if not data:
        return []
    threads_raw = data.get("data", {}).get("__T", [])

    threads = []
    if isinstance(threads_raw, list):
        threads = [t for t in threads_raw if isinstance(t, dict) and t.get("tid")]
    elif isinstance(threads_raw, dict):
        threads = [v for v in threads_raw.values() if isinstance(v, dict) and v.get("tid")]

    # 大时代板块：过滤掉回复数>=200的万年老帖，只保留新鲜讨论
    if fid == 706:
        before = len(threads)
        threads = [t for t in threads if int(t.get("replies", 0)) < 200]
        filtered = before - len(threads)
        if filtered > 0:
            print(f"  Filtered out {filtered} mega-threads (>=200 replies) for 大时代 board")

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
            "fid": fid,
        })

    print(f"  Found {len(threads)} threads, selected top {len(result)}")
    return result


# ── Step 2: Fetch thread details ───────────────────────────────────────────
def fetch_thread_detail(tid):
    """Fetch a single thread's replies."""
    url = f"https://bbs.nga.cn/read.php?tid={tid}&__output=11&page=1"
    body = nga_request(url)
    if not body:
        return None, [], []

    data = parse_nga_json(body)
    if not data:
        return None, [], []
    replies_raw = data.get("data", {}).get("__R", [])

    reply_list = []
    if isinstance(replies_raw, list):
        reply_list = [r for r in replies_raw if isinstance(r, dict)]
    elif isinstance(replies_raw, dict):
        reply_list = [v for v in replies_raw.values() if isinstance(v, dict)]

    main_content = ""
    all_replies = []
    interesting = []
    first = True
    for r in reply_list:
        content = clean_nga_html(r.get("content", ""))
        if first:
            main_content = content
            first = False
        else:
            if len(content) > 5:
                all_replies.append(content)
            if 10 < len(content) < 500:
                score = int(r.get("score", 0)) if r.get("score") else 0
                interesting.append({
                    "content": content,
                    "score": score,
                    "author": str(r.get("author", "")),
                    "lou": str(r.get("lou", "")),
                })

    interesting.sort(key=lambda x: x["score"], reverse=True)
    return main_content, interesting[:10], all_replies


# ── Step 3: Build multi-tab HTML ───────────────────────────────────────────
def build_cards_html(threads_data, fid):
    """Build card HTML for one board's threads."""
    cards = ""
    for t in threads_data:
        rank = t["rank"]
        rank_class = f"r{rank}" if rank <= 3 else "normal"
        heat_tag = {1: "最热", 2: "超热", 3: "冲击"}.get(rank, "热门" if rank <= 6 else "")
        heat_class = "hot" if rank <= 3 else "warm"

        tags = get_tags(t["subject"], fid)
        tags_html = ""
        if heat_tag:
            tags_html += f'<span class="tag {heat_class}">{heat_tag}</span>'
        for tag in tags:
            tags_html += f'<span class="tag blue">{html_escape(tag)}</span>'

        comments_html = ""
        if t.get("top_replies"):
            items = ""
            for i, c in enumerate(t["top_replies"]):
                content = html_escape(c["content"])
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

        cards += f"""
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
    return cards


def build_overview_html(threads_data):
    """Build overview bullet list from top threads."""
    items = ""
    for t in threads_data[:6]:
        subj = html_escape(t["subject"])
        brief = html_escape(t.get("summary", t["subject"]))
        if len(brief) > 60:
            brief = brief[:57] + "..."
        items += f'    <li><strong>{subj}</strong> ({t["replies"]}回复) -- {brief}</li>\n'
    return items


def build_html(board_data, now):
    """Generate the full multi-tab HTML page.
    board_data: list of dicts with keys: board_config, threads
    """
    date_str = now.strftime("%Y年%-m月%-d日") if os.name != "nt" else now.strftime("%Y年%m月%d日")
    weekday = CN_WEEKDAYS[now.weekday()]
    time_str = now.strftime("%H:%M")

    # Calculate totals across all boards
    all_threads = []
    for bd in board_data:
        all_threads.extend(bd["threads"])
    total_topics = len(all_threads)
    total_replies = sum(t["replies"] for t in all_threads)
    total_boards = len(board_data)

    # Build tab buttons
    tab_buttons = ""
    for i, bd in enumerate(board_data):
        cfg = bd["board_config"]
        active = " active" if i == 0 else ""
        count = len(bd["threads"])
        tab_buttons += f'      <div class="board-tab{active}" onclick="switchTab({i})">{cfg["icon"]} {cfg["name"]} <span class="tab-count">({count})</span></div>\n'

    # Build tab panels
    tab_panels = ""
    for i, bd in enumerate(board_data):
        cfg = bd["board_config"]
        threads = bd["threads"]
        display = "block" if i == 0 else "none"

        overview_items = build_overview_html(threads)
        cards = build_cards_html(threads, cfg["fid"])

        board_replies = sum(t["replies"] for t in threads)

        tab_panels += f"""
<div class="tab-panel" id="panel-{i}" style="display:{display}">
  <div class="section-head"><div class="dot"></div>{cfg["icon"]} {cfg["name"]} · 今日要闻速览</div>
  <div class="overview">
    <h3>{cfg["section_title"]}</h3>
    <ul>
{overview_items}    </ul>
  </div>
  <div class="section-head"><div class="dot"></div>热帖详情 &amp; 精选评论（{len(threads)} 条 · {board_replies} 讨论）</div>
  {cards}
</div>
"""

    # Build footer links
    footer_links = ""
    for bd in board_data:
        cfg = bd["board_config"]
        footer_links += f'  <p>数据来源: <a href="https://ngabbs.com/thread.php?fid={cfg["fid"]}" target="_blank">{cfg["link_text"]} (fid={cfg["fid"]})</a></p>\n'

    # Refresh time for subtitle
    refresh_time_str = f"\u6700\u8fd1\u5237\u65b0: {time_str}"  # "最近刷新: HH:MM"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NGA 综合速报 - {date_str}</title>
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

/* === HEADER === */
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

/* === TAB NAVIGATION === */
.tab-nav{{background:var(--tab-bg);border-bottom:1px solid var(--border);padding:0}}
.tab-nav-inner{{max-width:880px;margin:0 auto;padding:0 16px;display:flex;gap:0}}
.board-tab{{padding:10px 20px;font-size:14px;color:var(--text-dim);background:var(--tab-bg);border:1px solid var(--border);border-bottom:none;border-radius:6px 6px 0 0;cursor:pointer;margin-right:-1px;position:relative;top:1px;transition:all .2s;user-select:none}}
.board-tab:hover{{background:#DDD6C0;color:var(--text)}}
.board-tab.active{{background:var(--row-white);color:var(--accent-dark);font-weight:700;border-bottom:1px solid var(--row-white);z-index:1}}
.board-tab .tab-count{{font-size:11px;color:var(--text-muted);font-weight:400}}

/* === CONTENT === */
.container{{max-width:880px;margin:0 auto;padding:20px 16px 40px}}

.section-head{{font-size:14px;font-weight:700;color:#fff;margin:20px 0 12px;padding:8px 14px;background:linear-gradient(135deg,var(--accent-dark),var(--accent));border-radius:4px;display:flex;align-items:center;gap:8px}}
.section-head .dot{{width:5px;height:5px;border-radius:50%;background:#E8C872;flex-shrink:0}}

.overview{{background:var(--row-white);border:1px solid var(--border-light);border-radius:6px;padding:20px 22px;margin-bottom:20px}}
.overview h3{{font-size:14px;color:var(--accent-dark);margin-bottom:10px;font-weight:700;padding-bottom:8px;border-bottom:1px solid var(--border-light)}}
.overview ul{{list-style:none;padding:0}}
.overview li{{padding:4px 0 4px 18px;position:relative;font-size:13px;color:var(--text-dim);line-height:1.8}}
.overview li::before{{content:'\\25B8';position:absolute;left:2px;color:var(--warm);font-size:11px}}
.overview li strong{{color:var(--text)}}

/* Cards */
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
  .board-tab{{padding:8px 14px;font-size:13px}}
}}
</style>
</head>
<body>

<div class="header">
  <div class="header-content">
    <div class="header-logo">
      <span class="nga-text">NGA</span>
      <span class="nga-cn">综合速报</span>
    </div>
    <div class="header-info">
      <h1>NGA 综合速报</h1>
      <div class="sub">{date_str} {weekday} | {refresh_time_str}</div>
    </div>
    <div class="header-stats">
      <div class="header-stat"><div class="val">{total_topics}</div><div class="label">热点话题</div></div>
      <div class="header-stat"><div class="val">{total_replies}</div><div class="label">总讨论</div></div>
      <div class="header-stat"><div class="val">{total_boards}</div><div class="label">覆盖板块</div></div>
    </div>
  </div>
</div>

<div class="tab-nav">
  <div class="tab-nav-inner">
{tab_buttons}  </div>
</div>

<div class="container">
{tab_panels}
</div>

<div class="footer">
  <p>NGA 综合速报 | 自动生成于 {now.strftime("%Y-%m-%d %H:%M")} (UTC+8)</p>
{footer_links}  <p style="margin-top:6px;opacity:0.6">本报告由 GitHub Actions 自动抓取并生成，每 2 小时更新一次</p>
</div>

<script>
function switchTab(idx) {{
  var tabs = document.querySelectorAll('.board-tab');
  var panels = document.querySelectorAll('.tab-panel');
  for (var i = 0; i < tabs.length; i++) {{
    tabs[i].classList.remove('active');
    panels[i].style.display = 'none';
  }}
  tabs[idx].classList.add('active');
  panels[idx].style.display = 'block';
}}
</script>
</body>
</html>"""
    return html


def build_summary(t, board_name, fid=843):
    """Build summary for a thread using DeepSeek AI only. No text-truncation fallback."""
    main_content = t.get("main_content", "")
    top_replies = t.get("top_replies", [])
    summary = ""

    # DeepSeek AI summary (the only method)
    if DEEPSEEK_API_KEY:
        summary = ai_summary(t["subject"], main_content, top_replies, board_name, fid=fid) or ""

    if summary and len(summary) >= 10:
        return summary

    # AI unavailable or failed -> use subject as last resort
    print(f"    AI summary unavailable, falling back to subject")
    return t["subject"]


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    print(f"=== NGA Multi-Board News Builder === {now.strftime('%Y-%m-%d %H:%M')} UTC+8")
    print(f"Boards: {', '.join(f'fid={b['fid']} ({b['name']})' for b in BOARDS)}")

    # Anti-duplicate: skip if a run already happened within the last hour
    # This prevents both GitHub schedule and Tencent Cloud trigger from
    # both firing at the same time and wasting DeepSeek tokens.
    print("\n[STEP 0] Checking for recent workflow runs...")
    if check_recent_run():
        print("=== SKIPPING: recent run detected, no DeepSeek token will be spent ===")
        return
    print("[STEP 0] No recent run found, proceeding...\n")

    if not NGA_COOKIE:
        print("WARNING: NGA_COOKIE not set. Requests may fail or return limited data.")

    board_data = []

    for board_cfg in BOARDS:
        fid = board_cfg["fid"]
        board_name = board_cfg["name"]

        print(f"\n{'='*60}")
        print(f"Processing board: {board_name} (fid={fid})")
        print(f"{'='*60}")

        # Step 1: Fetch thread list
        threads = fetch_thread_list(fid, board_name)
        if not threads:
            print(f"  WARNING: No threads fetched for fid={fid}. Skipping.")
            continue

        # Step 2: Fetch details for each thread
        for t in threads:
            tid = t["tid"]
            print(f"  Fetching thread #{t['rank']}: {t['subject'][:30]}... (tid={tid})")
            main_content, top_replies, all_replies = fetch_thread_detail(tid)
            t["main_content"] = main_content or ""
            t["top_replies"] = top_replies
            t["_all_replies"] = all_replies

            mc_len = len(main_content) if main_content else 0
            print(f"    main_content: {mc_len} chars, top_replies: {len(top_replies)}, all_replies: {len(all_replies)}")

            # Build summary
            t["summary"] = build_summary(t, board_name, fid=fid)
            print(f"    SUMMARY ({len(t['summary'])} chars): {t['summary'][:80]}...")

            time.sleep(DELAY_SEC)

        board_data.append({
            "board_config": board_cfg,
            "threads": threads,
        })
        print(f"\n  Board {board_name}: {len(threads)} threads processed.")

    if not board_data:
        print("ERROR: No data from any board. Exiting.")
        return

    # Step 3: Generate HTML
    html = build_html(board_data, now)

    out_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nHTML written to: {out_path}")
    print(f"File size: {os.path.getsize(out_path)} bytes")
    print(f"Boards: {len(board_data)}, Total threads: {sum(len(bd['threads']) for bd in board_data)}")


if __name__ == "__main__":
    main()
