\
import os
import time
import html
import re
import traceback
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Bot
import orjson

# --------------------
# Config
# --------------------
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
USERS = [u.strip().lstrip("@") for u in os.getenv("USERS", "").split(",") if u.strip()]
KEYWORDS = [k.strip().lower() for k in os.getenv("KEYWORDS", "").split(",") if k.strip()]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "45"))
USE_PLAYWRIGHT_FALLBACK = os.getenv("USE_PLAYWRIGHT_FALLBACK", "true").lower() == "true"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))

if not BOT_TOKEN or not CHAT_ID or not USERS or not KEYWORDS:
    raise SystemExit("Please configure BOT_TOKEN, CHAT_ID, USERS, KEYWORDS in .env")

bot = Bot(token=BOT_TOKEN)
session = requests.Session()

# Optional proxies
http_proxy = os.getenv("HTTP_PROXY")
https_proxy = os.getenv("HTTPS_PROXY")
if http_proxy or https_proxy:
    session.proxies.update({k: v for k, v in {"http": http_proxy, "https": https_proxy}.items() if v})

# Persistent in-memory state; replace with SQLite if desired
last_seen: Dict[str, str] = {}  # username -> last status id string

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html"}
BASE = "https://truthsocial.com"

# --------------------
# Helpers
# --------------------
def telegram_notify(text: str, disable_preview: bool = False):
    bot.send_message(chat_id=CHAT_ID, text=text, disable_web_page_preview=disable_preview)

def norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()

def matches_keywords(text: str, keywords: List[str]) -> Tuple[bool, List[str]]:
    t = text.lower()
    hit = [k for k in keywords if k in t]
    return (len(hit) > 0, hit)

# --------------------
# API mode (Mastodon-like)
# --------------------
def api_lookup_account(username: str) -> Optional[dict]:
    url = f"{BASE}/api/v1/accounts/lookup"
    try:
        r = session.get(url, params={"acct": username}, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None

def api_fetch_statuses(account_id: str, since_id: Optional[str] = None) -> Optional[List[dict]]:
    url = f"{BASE}/api/v1/accounts/{account_id}/statuses"
    params = {
        "exclude_replies": "true",
        "limit": 40,
    }
    if since_id:
        params["since_id"] = since_id
    try:
        r = session.get(url, params=params, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None

# --------------------
# Playwright fallback
# --------------------
def scrape_statuses_playwright(username: str, since_status_url: Optional[str]) -> List[dict]:
    """Scrape the user page and return pseudo-status dicts: {id,url,created_at,content}
    Requires `playwright install chromium` once.
    """
    from playwright.sync_api import sync_playwright

    items: List[dict] = []
    user_url = f"{BASE}/@{username}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()
        page.goto(user_url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT * 1000)
        # Try to wait a bit for client render
        try:
            page.wait_for_timeout(2000)
        except Exception:
            pass

        # Truth Social uses Mastodon-like markup with <article> per post; be defensive
        articles = page.locator("article")
        count = articles.count()
        for i in range(min(count, 30)):
            el = articles.nth(i)
            # Try extract link to status
            hrefs = el.locator("a[href*='/@']").all()
            status_url = None
            for a in hrefs:
                try:
                    h = a.get_attribute("href") or ""
                    if "/@" in h and "/posts/" in h:
                        status_url = h if h.startswith("http") else BASE + h
                        break
                except Exception:
                    continue
            if not status_url:
                continue
            if since_status_url and status_url <= since_status_url:
                # naive gate; API path uses ids; here we fall back to URL lexicographic check
                pass

            # Extract content text
            html_content = el.inner_html()
            soup = BeautifulSoup(html_content, "html.parser")
            text = norm_text(soup.get_text(" "))
            # Fake an id as the tail of the URL
            sid = status_url.rstrip("/").split("/")[-1]
            items.append({
                "id": sid,
                "url": status_url,
                "created_at": None,
                "content": text,
            })
        browser.close()
    return items

# --------------------
# Core loop
# --------------------
def process_user(username: str):
    global last_seen
    try:
        # Try API mode first
        acct = api_lookup_account(username)
        statuses: List[dict] = []
        if acct and "id" in acct:
            acct_id = str(acct["id"])
            statuses = api_fetch_statuses(acct_id, since_id=last_seen.get(username)) or []
            # API returns newest first; we want chronological send
            statuses = list(reversed(statuses))
        elif USE_PLAYWRIGHT_FALLBACK:
            statuses = scrape_statuses_playwright(username, None)
            # Already oldest->newest order by our scan
        else:
            return

        for st in statuses:
            sid = str(st.get("id"))
            content_html = st.get("content", "")
            # API mode content is HTML. Scraping returns plain text already.
            if "<" in content_html:
                soup = BeautifulSoup(content_html, "html.parser")
                text = norm_text(soup.get_text(" "))
            else:
                text = norm_text(content_html)

            ok, hits = matches_keywords(text, KEYWORDS)
            if not ok:
                continue

            url = st.get("url") or f"{BASE}/@{username}"
            created_at = st.get("created_at", "")
            hits_str = ", ".join(hits)

            msg = (
                f"👀 <b>Truth Social</b> — @{html.escape(username)} posted about <b>{html.escape(hits_str)}</b>\n"
                f"{html.escape(text[:400])}{'…' if len(text)>400 else ''}\n"
                f"\n🔗 {html.escape(url)}"
            )
            # send with HTML parse mode
            bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", disable_web_page_preview=False)

            # advance last seen
            last_seen[username] = sid

        # If we fetched nothing but have an acct, still bump last_seen to newest id (first page)
        if acct and "id" in acct and username not in last_seen:
            bootstrap = api_fetch_statuses(str(acct["id"])) or []
            if bootstrap:
                last_seen[username] = str(bootstrap[0].get("id"))

    except Exception as e:
        err = f"Error processing @{username}: {e}\n{traceback.format_exc()}"
        telegram_notify(f"⚠️ Truth watcher error for @{username}: {e}", disable_preview=True)
        print(err)

def main():
    telegram_notify(
        "✅ Truth watcher started. Users: " + ", ".join([f"@{u}" for u in USERS]) +
        " | Keywords: " + ", ".join(KEYWORDS),
        disable_preview=True,
    )
    while True:
        for u in USERS:
            process_user(u)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
