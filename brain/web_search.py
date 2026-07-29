"""
EMO Live Google & Web Search Engine
====================================
Fetches real-time web search results from Google & DuckDuckGo APIs
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

    # 1. DuckDuckGo Instant Answer API
    try:
        ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
        req = urllib.request.Request(ddg_url, headers={"User-Agent": "EMO-AI/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            abstract = data.get("AbstractText", "").strip()
            if abstract:
                results.append(f"Instant Fact: {abstract}")
            
            # Extract related topics
            topics = data.get("RelatedTopics", [])
            for t in topics[:2]:
                txt = t.get("Text", "").strip()
                if txt and txt not in results:
                    results.append(f"Related: {txt}")
    except Exception as e:
        print(f"[WebSearch] DDG API Error: {e}")

    # 2. DuckDuckGo / Google HTML Scraper fallback
    if len(results) < 2:
        try:
            encoded_q = urllib.parse.quote(query)
            html_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
            req = urllib.request.Request(
                html_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw_html = resp.read().decode("utf-8", errors="ignore")
                
            snippets = re.findall(r'class="result__snippet[^">]*>(.*?)</a>', raw_html, re.DOTALL)
            for s in snippets[:3]:
                clean_text = re.sub(r'<[^>]+>', '', s)
                clean_text = html.unescape(clean_text).strip()
                if clean_text and clean_text not in results:
                    results.append(clean_text)
        except Exception as e:
            print(f"[WebSearch] HTML Scrape Error: {e}")

    # 3. Wikipedia Knowledge Fallback
    if not results:
        try:
            wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(query)}"
            req = urllib.request.Request(wiki_url, headers={"User-Agent": "EMO-AI/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                extract = data.get("extract", "").strip()
                if extract:
                    results.append(extract)
        except Exception:
            pass

    if results:
        return "\n".join(f"• {r}" for r in results[:max_results])

    return f"Live web search for '{query}' returned no instant results."

def is_search_needed(user_msg):
    """Detects if user prompt asks for live news, facts, scores, or web search."""
    low = user_msg.lower()
    keywords = [
        "search", "google", "latest", "news", "today", "current", "weather",
        "score", "match", "stock", "price", "who is", "what is", "where is",
        "when did", "happened", "updates", "result", "winner", "president", "price of"
    ]
    return any(k in low for k in keywords)
