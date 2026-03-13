#!/usr/bin/env python3
"""Quick test to check what NGA returns for thread content."""
import urllib.request, json, re, time, sys

NGA_COOKIE = "ngaPassportCid=Z8ejjfq987q4g395fnp1jv6h2255o4ue4o1ji7p0;ngaPassportUid=294188;ngaPassportUrlencodedUname=zuoka;_178i=1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"

def fetch(url):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", "https://bbs.nga.cn/")
    req.add_header("Cookie", NGA_COOKIE)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        for enc in ["utf-8", "gbk", "gb2312"]:
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

def parse_json(body):
    body = body.strip().lstrip("\ufeff")
    body = re.sub(r"^[a-zA-Z_][\w.]*\s*=\s*", "", body)
    body = body.rstrip(";").strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start = body.find("{")
        if start >= 0:
            depth = 0
            for i in range(start, len(body)):
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(body[start:i+1])
                        except json.JSONDecodeError:
                            break
        return None

def clean_html(text):
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = s.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    s = re.sub(r"\[/?[a-zA-Z]+[^\]]*\]", "", s)
    return s.strip()

print("=== Fetching thread list ===")
body = fetch("https://bbs.nga.cn/thread.php?fid=843&order_by=postdatedesc&__output=11")
data = parse_json(body)
if not data:
    print("FAILED to parse thread list")
    sys.exit(1)

threads_raw = data.get("data", {}).get("__T", [])
threads = []
if isinstance(threads_raw, list):
    threads = [t for t in threads_raw if isinstance(t, dict) and t.get("tid")]
elif isinstance(threads_raw, dict):
    threads = [v for v in threads_raw.values() if isinstance(v, dict) and v.get("tid")]

threads.sort(key=lambda t: int(t.get("replies", 0)), reverse=True)

for t in threads[:3]:
    tid = t["tid"]
    subj = t.get("subject", "")
    print(f"\n=== Thread tid={tid}: {subj} ===")

    body2 = fetch(f"https://bbs.nga.cn/read.php?tid={tid}&__output=11&page=1")
    data2 = parse_json(body2)
    if not data2:
        print("  FAILED to parse detail JSON")
        continue

    replies_raw = data2.get("data", {}).get("__R", [])
    reply_list = []
    if isinstance(replies_raw, list):
        reply_list = [r for r in replies_raw if isinstance(r, dict)]
    elif isinstance(replies_raw, dict):
        reply_list = [v for v in replies_raw.values() if isinstance(v, dict)]

    print(f"  Reply count: {len(reply_list)}")
    if reply_list:
        first = reply_list[0]
        raw_content = first.get("content", "")
        print(f"  Raw content type: {type(raw_content).__name__}")
        print(f"  Raw content (first 400 chars): {str(raw_content)[:400]}")
        cleaned = clean_html(raw_content)
        print(f"  Cleaned length: {len(cleaned)}")
        print(f"  Cleaned (first 200 chars): {cleaned[:200]}")

        # Now test the summary logic
        summary = ""
        if cleaned:
            s = cleaned.replace("\n", " ").strip()
            s = re.sub(r"\s+", " ", s)
            if len(s) > 150:
                s = s[:147] + "..."
            summary = s
        if not summary or len(summary) < 20:
            # fallback to top reply
            for r in reply_list[1:]:
                rc = clean_html(r.get("content", ""))
                if len(rc) > 10:
                    best = rc.replace("\n", " ").strip()
                    best = re.sub(r"\s+", " ", best)
                    if len(best) > 120:
                        best = best[:117] + "..."
                    summary = (summary + " " + best).strip() if summary else best
                    break
        if not summary:
            summary = subj
        print(f"  FINAL SUMMARY: {summary}")
    else:
        print("  No replies found!")

    time.sleep(0.6)

print("\n=== Done ===")
