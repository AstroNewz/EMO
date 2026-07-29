"""
EMO Live Google & Web Search Engine
====================================
Fetches real-time web search results from DuckDuckGo Lite & Wikipedia APIs
for news, weather, stock prices, live events, and instant answers.
"""

import json
import re
import html
import urllib.request
import urllib.parse

def search_web(query, max_results=3):
    """
    Performs real-time web search for the given query.
    Returns clean snippets of live web data for the LLM.
    """
    if not query:
        return ""

    results = []

    # 1. Real-time DDG Lite POST Web Search
    try:
        url = "https://lite.duckduckgo.com/lite/"
        params = urllib.parse.urlencode({'q': query}).encode('utf-8')
        req = urllib.request.Request(url, data=params, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded"
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")
            tds = re.findall(r'<td[^>]*>(.*?)</td>', html_text, re.DOTALL)
            for t in tds:
                clean = html.unescape(re.sub(r'<[^>]+>', '', t)).strip()
                # Exclude navigation links, short UI snippets, and meta headers
                if len(clean) > 35 and "DuckDuckGo" not in clean and "Privacy" not in clean and "javascript" not in clean.lower():
                    if not any(clean in r or r in clean for r in results):
                        results.append(clean)
                        if len(results) >= max_results:
                            break
    except Exception as e:
        print(f"[WebSearch] DDG Lite Error: {e}")

    # 2. Wikipedia Search API (Fallback for instant facts, biographies, & definitions)
    if len(results) < max_results:
        clean_q = re.sub(r'\b(who|what|where|when|why|how|is|are|was|were|the|a|an|current|latest|today|search|google|tell|me|about|find|for)\b', ' ', query, flags=re.IGNORECASE)
        clean_q = ' '.join(clean_q.split()).strip() or query
        try:
            wurl = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={urllib.parse.quote(clean_q)}&limit=3&format=json"
            req = urllib.request.Request(wurl, headers={"User-Agent": "EMO-Assistant/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                titles = data[1] if len(data) > 1 else []
                for t in titles[:2]:
                    surl = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(t)}"
                    sreq = urllib.request.Request(surl, headers={"User-Agent": "EMO-Assistant/1.0"})
                    try:
                        with urllib.request.urlopen(sreq, timeout=3) as sresp:
                            sdata = json.loads(sresp.read().decode("utf-8"))
                            ext = sdata.get("extract", "").strip()
                            if ext and len(ext) > 25 and "may refer to" not in ext.lower():
                                if not any(ext[:40] in r for r in results):
                                    results.append(ext)
                                    if len(results) >= max_results:
                                        break
                    except Exception:
                        pass
        except Exception as e:
            print(f"[WebSearch] Wikipedia Error: {e}")

    if results:
        return "\n".join(f"• {r}" for r in results[:max_results])

    return ""

def is_search_needed(user_msg):
    """Detects if user prompt asks for live news, facts, scores, or web search."""
    low = user_msg.lower()
    keywords = [
        "search", "google", "latest", "news", "today", "current", "weather",
        "score", "match", "stock", "price", "who is", "what is", "where is",
        "when did", "happened", "updates", "result", "winner", "president", "price of",
        "prime minister"
    ]
    return any(k in low for k in keywords)
