$env:PATH = "C:\Program Files\Git\cmd;C:\Program Files\GitHub CLI;" + $env:PATH
Set-Location "c:\Users\locmai\WorkBuddy\Claw\nga-daily-news"

# Quick test: fetch thread list and try getting first thread detail
python -c "
import urllib.request, json, re, sys

NGA_COOKIE = 'ngaPassportCid=Z8ejjfq987q4g395fnp1jv6h2255o4ue4o1ji7p0;ngaPassportUid=294188;ngaPassportUrlencodedUname=zuoka;_178i=1'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'

def fetch(url):
    req = urllib.request.Request(url)
    req.add_header('User-Agent', UA)
    req.add_header('Referer', 'https://bbs.nga.cn/')
    req.add_header('Cookie', NGA_COOKIE)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        for enc in ['utf-8','gbk','gb2312']:
            try: return raw.decode(enc)
            except: continue
        return raw.decode('utf-8', errors='replace')

def parse_json(body):
    body = body.strip().lstrip('\ufeff')
    body = re.sub(r'^[a-zA-Z_][\w.]*\s*=\s*', '', body)
    body = body.rstrip(';').strip()
    try: return json.loads(body)
    except:
        start = body.find('{')
        if start >= 0:
            depth = 0
            for i in range(start, len(body)):
                if body[i] == '{': depth += 1
                elif body[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try: return json.loads(body[start:i+1])
                        except: break
        return None

# Get thread list
print('=== Fetching thread list ===')
body = fetch('https://bbs.nga.cn/thread.php?fid=843&order_by=postdatedesc&__output=11')
data = parse_json(body)
threads_raw = data.get('data',{}).get('__T',[])
threads = []
if isinstance(threads_raw, list):
    threads = [t for t in threads_raw if isinstance(t, dict) and t.get('tid')]
elif isinstance(threads_raw, dict):
    threads = [v for v in threads_raw.values() if isinstance(v, dict) and v.get('tid')]
threads.sort(key=lambda t: int(t.get('replies',0)), reverse=True)

for t in threads[:3]:
    tid = t['tid']
    subj = t.get('subject','')
    print(f'\n=== Thread tid={tid}: {subj} ===')
    
    # Fetch detail
    body2 = fetch(f'https://bbs.nga.cn/read.php?tid={tid}&__output=11&page=1')
    data2 = parse_json(body2)
    if not data2:
        print('  FAILED to parse detail JSON')
        continue
    
    replies_raw = data2.get('data',{}).get('__R',[])
    reply_list = []
    if isinstance(replies_raw, list):
        reply_list = [r for r in replies_raw if isinstance(r, dict)]
    elif isinstance(replies_raw, dict):
        reply_list = [v for v in replies_raw.values() if isinstance(v, dict)]
    
    print(f'  Reply count: {len(reply_list)}')
    if reply_list:
        first = reply_list[0]
        raw_content = first.get('content','')
        print(f'  First reply raw content type: {type(raw_content).__name__}')
        print(f'  First reply raw content (first 300 chars): {str(raw_content)[:300]}')
        
        # Clean it
        s = str(raw_content)
        s = re.sub(r'<br\s*/?>', '\n', s)
        s = re.sub(r'<[^>]+>', '', s)
        s = s.replace('&amp;','&').replace('&lt;','<').replace('&gt;','>').replace('&quot;','\"').replace('&#39;',\"'\").replace('&nbsp;',' ')
        s = re.sub(r'\[/?[a-zA-Z]+[^\]]*\]', '', s)
        s = s.strip()
        print(f'  Cleaned content length: {len(s)}')
        print(f'  Cleaned content (first 200 chars): {s[:200]}')
    
    import time
    time.sleep(0.6)

print('\n=== Done ===')
"
