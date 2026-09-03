"""
Market Snapshot — CCIL NDS-OM Bonds + TradingView Prices
==========================================================
Section 1 (CCIL):  LTP & LTY for 06.94 GS 2036, 06.68 GS 2040, 07.24 GS 2055
Section 2 (TV):    Gold, USD/INR, DXY, Brent — price, prev close, change

Requirements:
    pip install playwright requests beautifulsoup4
    python -m playwright install chromium
"""

import time, json, re, requests, os
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

EMAIL_CONFIG = {
    "api_url"   : "https://fiber.nuvamapis.com/email/send",
    "x_api_key" : "UbO2ODRvx65ddZxJBmhChOsFM9CVhMwIVVuqrq40",
    "token"     : "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjbGllbnRfaWQiOiIyczJhdmJjdjJrNXFsamdoYWF0c3I2c2c0YSIsImNsaWVudF9zZWNyZXQiOiIxMTRmMTEzbjBvdG85YnFxb2dxcm44MXRlMmkycDk0bzc4M20wbjM0ZTg4NzNqZm1nb2JtIiwic2NvcGVzIjpbIkVXTS9FYXN5RW1haWxTZW5kX3l2dnY5bzh3MjIiLCJFV00vT2F1dGgyXzd6MjM5emFvN2kiXSwiWGFwaUtleSI6WyJZODFpdURqY05lNTRNQmw3QVNETUoxdDlaMUVpZklxVTZ6U0FucDdkIiwiTjA4VklLYTBYaDVhVk54M0pvS1RiOWYyQTVjZTQ0MFUzQlFYbTZ6ZyIsIjhySjM5N1hkR0N2S3lNaFlLWmszN2VyVzAyYXRtRWo0Y2hPRlU2QzgiLCI0SnNZMmFoeVVXNHhvS0RQYktaaUU4QWdqM1dDN2lHOTZac2kwdUtMIiwiZFI1TzZVTTU0NzRuNVIzaEd5N0E1YXB3cExCWVFkQklSRVdsVTkwMCIsImIxSldGRUU4b3Q5SXRZNE9vaU1CMDg4cFltT2xsVnZvMTNtdnVCRkQiLCJ0UWZjbnZybHV3MURzRVdTZlpaMWYyWXI1UThTcjBsWTJOWkRjUmNkIiwiWWNiRlhVbGlTUWd1R2drRHBzVlY3YzRuTU45YXNSVDZqWFBPZ2xSYiIsImlPdFNaZHBpdW42bkE4QzlWRkFzUDZnSzR6MGNoeGRZNDF6eUxoeVkiLCJsNTRBR1U4MGk5MnBVODV1SmtXQ3c5WElnd2x3QmNaRjFwNXRLODBiIiwiREFQR0lGemgyWklpZTc5M0x0TzI3eklaTlhoRlZ4MWFHOVZ4enVqMCIsIjdmSmlLbkp4UmY2b2ZNNXdyeFBhaDVabUdnZkZQSXRYM01GNUtrYTAiLCJDbGh4SmE4UmpyYU9VbDFDNHlVMHU2MnBFVktMaEo2WWF",
    "from_email": "support@aimin.co",
    "to_emails" : "athu.waze@gmail.com,harshadgupta0406@gmail.com,lakshana1803@gmail.com,s_sheldekar@yahoo.com",
    "bcc_emails": None,
}

TELEGRAM_CONFIG = {
    "bot_token": "8541819358:AAGZC0GEO-hiviIKhVDwsTuJCZRzqiSl668",
}
# Flat file that persists bond prev levels between runs (sits next to this script)
# Edit prev_levels.json directly to add/remove/update bonds.
LEVELS_FILE = "prev_levels.json"

# If script runs at or after this hour (IST, 24h) → snapshot as next prev levels
EOD_HOUR = 17

CCIL_URL = (
    "https://www.ccilindia.com/rbi-nds-om1"
    "?p_p_id=com_ccil_ndsom_entire_CCILNdsOM_EntirePortlet_INSTANCE_zavb"
    "&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view"
    "&p_p_resource_id=ndsom&p_p_cacheability=cacheLevelPage"
)
CCIL_BASE = "https://www.ccilindia.com"

TV_SYMBOLS = [
    {"name": "Gold",    "url": "https://in.tradingview.com/symbols/GOLD/"},
    {"name": "USD/INR", "url": "https://in.tradingview.com/symbols/USDINR/"},
    {"name": "DXY",     "url": "https://in.tradingview.com/symbols/TVC-DXY/"},
    {"name": "Brent",   "url": "https://in.tradingview.com/symbols/UKOIL/"},
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

PAGE_WAIT_MS     = 8_000
NAVIGATE_TIMEOUT = 45_000



# ══════════════════════════════════════════════════════════════════════════════
#  PREV LEVELS — file-backed persistence
# ══════════════════════════════════════════════════════════════════════════════

def load_prev_levels() -> dict:
    """Load prev levels from prev_levels.json. Raises if file is missing."""
    path = Path(LEVELS_FILE)
    if not path.exists():
        raise FileNotFoundError(
            f"{LEVELS_FILE} not found. "
            "Create it with your bond prev levels before running."
        )
    with open(path) as f:
        data = json.load(f)
    print(f"  Loaded {len(data)} bonds from {path.resolve()}")
    return data


def save_prev_levels(bonds: list, prev: dict) -> dict:
    """
    Snapshot today's scraped yield+price as tomorrow's prev levels.
    Only updates bonds that have valid (non-N/A) scraped data.
    Preserves existing values for bonds that had errors today.
    Returns the updated dict.
    """
    updated = dict(prev)  # start from current file state
    for b in bonds:
        if b.lty and b.ltp and b.lty != "N/A" and b.ltp != "N/A" and not b.error:
            updated[b.security] = [b.lty, b.ltp]
    path = Path(LEVELS_FILE)
    with open(path, "w") as f:
        json.dump(updated, f, indent=2)
    print(f"  EOD snapshot saved → {path.resolve()}")
    for sec, vals in updated.items():
        print(f"    {sec}: yield={vals[0]}  price={vals[1]}")
    return updated


def is_eod() -> bool:
    """Return True if current IST time is at or after EOD_HOUR."""
    from datetime import timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist)
    return now_ist.hour >= EOD_HOUR

# ══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BondQuote:
    security: str
    ltp: Optional[str] = None        # Last Traded Price  (today)
    lty: Optional[str] = None        # Last Traded Yield  (today)
    prev_price: Optional[str] = None # Previous price from PREV_LEVELS
    prev_yield: Optional[str] = None # Previous yield from PREV_LEVELS
    price_chg: Optional[str] = None  # price change  (today − prev), formatted
    yield_chg: Optional[str] = None  # yield change  (today − prev), formatted
    error: Optional[str] = None


def _fmt_chg(today: Optional[str], prev: Optional[str], decimals: int = 2) -> Optional[str]:
    """Return formatted change string like '+0.05' or '−0.03', or None."""
    if not today or not prev:
        return None
    try:
        diff = round(float(today.replace(",", "")) - float(prev.replace(",", "")), decimals)
        sign = "+" if diff >= 0 else "−"
        return f"{sign}{abs(diff):.{decimals}f}"
    except (ValueError, TypeError):
        return None


def _enrich_bond(bq: BondQuote, prev_levels: dict) -> BondQuote:
    """Attach prev levels and compute changes from loaded prev_levels dict."""
    prev = prev_levels.get(bq.security)
    if prev:
        bq.prev_yield = prev[0]
        bq.prev_price = prev[1]
        bq.yield_chg  = _fmt_chg(bq.lty,  bq.prev_yield, decimals=2)
        bq.price_chg  = _fmt_chg(bq.ltp,  bq.prev_price, decimals=2)
    return bq

@dataclass
class Quote:
    name: str
    url: str
    current_price: Optional[str] = None
    currency: Optional[str] = None
    previous_close: Optional[str] = None
    change: Optional[str] = None
    change_pct: Optional[str] = None
    error: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
#  CCIL SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def _normalize(s: str) -> str:
    """Normalize bond name for fuzzy matching — collapse spaces, uppercase."""
    return re.sub(r'\s+', ' ', s).strip().upper()


def _parse_ccil_html(html: str, target_bonds: list) -> list[BondQuote]:
    """
    Parse CCIL NDS-OM HTML/JSON response.
    Handles:
      (a) JSON array of dicts
      (b) HTML table (most common for lifecycle=2 portlet responses)
    """
    results = {_normalize(b): BondQuote(security=b) for b in target_bonds}

    # ── Try JSON first ────────────────────────────────────────────────────────
    try:
        data = json.loads(html)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            # common wrappers: {"data": [...]} or {"records": [...]}
            rows = data.get("data") or data.get("records") or data.get("trades") or []
        else:
            rows = []

        for row in rows:
            # key names vary: Security / security / SECURITY / instrument etc.
            sec_val = None
            for k in ["Security", "security", "SECURITY", "instrument", "Instrument",
                       "INSTRUMENT", "desc", "Desc", "Description"]:
                if k in row:
                    sec_val = str(row[k]).strip()
                    break
            if not sec_val:
                continue

            norm = _normalize(sec_val)
            for target_norm, bq in results.items():
                if target_norm in norm or norm in target_norm:
                    # LTP
                    for k in ["LTP", "ltp", "LastTradedPrice", "last_traded_price",
                               "Price", "price", "PRICE"]:
                        if k in row and row[k] not in (None, "", "N/A"):
                            bq.ltp = str(row[k])
                            break
                    # LTY
                    for k in ["LTY", "lty", "LastTradedYield", "last_traded_yield",
                               "Yield", "yield", "YIELD"]:
                        if k in row and row[k] not in (None, "", "N/A"):
                            bq.lty = str(row[k])
                            break
        return list(results.values())
    except (json.JSONDecodeError, Exception):
        pass

    # ── Try HTML table ────────────────────────────────────────────────────────
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        for bq in results.values():
            bq.error = "No table found in response"
        return list(results.values())

    for table in tables:
        headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]
        if not headers:
            # try first row as header
            first_row = table.find("tr")
            if first_row:
                headers = [td.get_text(strip=True).upper() for td in first_row.find_all(["td", "th"])]

        # Identify column indices
        def col_idx(candidates):
            for c in candidates:
                for i, h in enumerate(headers):
                    if c in h:
                        return i
            return None

        sec_col = col_idx(["SECURITY", "INSTRUMENT", "DESC", "BOND", "SCRIP"])
        ltp_col = col_idx(["LTP", "LAST TRADED PRICE", "PRICE"])
        lty_col = col_idx(["LTY", "LAST TRADED YIELD", "YIELD"])

        if sec_col is None:
            continue  # wrong table, try next

        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) <= sec_col:
                continue
            sec_val = cells[sec_col]
            norm    = _normalize(sec_val)

            for target_norm, bq in results.items():
                if target_norm in norm or norm in target_norm:
                    if ltp_col is not None and len(cells) > ltp_col:
                        bq.ltp = cells[ltp_col] or None
                    if lty_col is not None and len(cells) > lty_col:
                        bq.lty = cells[lty_col] or None
                    break

    return list(results.values())


def scrape_ccil(page, target_bonds: list) -> list[BondQuote]:
    """
    Strategy A: Hit the Liferay resource URL directly (fast, returns data fragment).
    Strategy B: Load the full page and extract from the rendered DOM.
    """
    print("  Fetching CCIL NDS-OM …")

    # ── Strategy A: Direct resource URL ──────────────────────────────────────
    try:
        # First load the base page to get cookies/session
        page.goto(CCIL_BASE, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2000)

        # Now hit the AJAX resource endpoint
        response = page.request.get(
            CCIL_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/html, */*",
                "Referer": CCIL_BASE,
            },
            timeout=20_000,
        )
        raw = response.text()
        if raw and len(raw) > 50 and "Host not in allowlist" not in raw:
            bonds = _parse_ccil_html(raw, target_bonds)
            # Check if we got any data
            if any(b.ltp for b in bonds):
                return bonds
            # Got a response but parsing found nothing — still try strategy B
    except Exception as e:
        print(f"    Strategy A failed: {e}")

    # ── Strategy B: Full page scrape ──────────────────────────────────────────
    try:
        page.goto(
            "https://www.ccilindia.com/rbi-nds-om1",
            wait_until="networkidle",
            timeout=NAVIGATE_TIMEOUT,
        )
        page.wait_for_timeout(5000)

        # Wait for a table to appear
        try:
            page.wait_for_selector("table", timeout=10_000)
        except Exception:
            pass

        html = page.content()
        bonds = _parse_ccil_html(html, target_bonds)

        # If still empty, try to intercept XHR responses
        if not any(b.ltp for b in bonds):
            # Trigger any lazy-load by scrolling
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            html = page.content()
            bonds = _parse_ccil_html(html, target_bonds)

        return bonds

    except Exception as e:
        return [BondQuote(security=b, error=str(e)) for b in TARGET_BONDS]


# ══════════════════════════════════════════════════════════════════════════════
#  TRADINGVIEW SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def get_current_price(page):
    for sel in [".js-symbol-last", '[data-qa-id="symbol-last-value"]']:
        try:
            el = page.locator(sel).first
            if el.count() == 0:
                continue
            price = el.inner_text().strip().replace("\n", "")
            if price:
                currency = None
                for csel in [".js-symbol-currency", '[data-qa-id="symbol-currency"]']:
                    try:
                        currency = page.locator(csel).first.inner_text().strip()
                        break
                    except Exception:
                        pass
                return price, currency
        except Exception:
            pass
    return None, None


def get_prev_close(page):
    result = page.evaluate("""
    () => {
        const KEYWORDS = ['prev. close', 'previous close', 'prev close'];
        for (const el of document.querySelectorAll('*')) {
            const txt = (el.innerText || '').trim().toLowerCase();
            if (txt.length > 40 || txt.length < 4) continue;
            if (!KEYWORDS.some(k => txt.includes(k))) continue;
            const candidates = [
                el.nextElementSibling,
                el.parentElement && el.parentElement.nextElementSibling,
                ...(el.parentElement ? [...el.parentElement.children] : []),
            ].filter(Boolean);
            for (const c of candidates) {
                if (c === el) continue;
                const val = (c.innerText || '').trim().replace(/,/g, '');
                if (/^\\d{1,6}(\\.\\d+)?$/.test(val)) return c.innerText.trim();
            }
        }
        return null;
    }
    """)
    if result:
        return result
    try:
        body = page.inner_text("body")
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if any(k in line.lower() for k in ["prev. close", "previous close", "prev close"]):
                for token_line in lines[i:i+4]:
                    for token in token_line.split():
                        try:
                            float(token.replace(",", ""))
                            return token
                        except ValueError:
                            continue
    except Exception:
        pass
    return None


def get_change(page):
    for sel in [".js-symbol-change", '[class*="change-"][class*="js-symbol-change"]']:
        try:
            el = page.locator(sel).first
            if el.count():
                spans = [s.strip() for s in el.locator("span").all_text_contents() if s.strip()]
                if len(spans) >= 2:
                    return spans[0], spans[1]
                elif spans:
                    return spans[0], None
        except Exception:
            pass
    return None, None


def scrape_tv_symbol(page, symbol):
    quote = Quote(name=symbol["name"], url=symbol["url"])
    try:
        page.goto(symbol["url"], wait_until="networkidle", timeout=NAVIGATE_TIMEOUT)
        try:
            page.wait_for_selector(".js-symbol-last", timeout=10_000)
        except Exception:
            pass
        page.wait_for_timeout(PAGE_WAIT_MS)
        quote.current_price, quote.currency = get_current_price(page)
        quote.previous_close                = get_prev_close(page)
        quote.change, quote.change_pct      = get_change(page)
        if not quote.current_price:
            quote.error = "Price element not found"
    except PWTimeout:
        quote.error = f"Timed out"
    except Exception as exc:
        quote.error = str(exc)
    return quote


def scrape_all(prev_levels: dict):
    bonds, quotes = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-IN",
        )
        page = context.new_page()

        def block_media(route, request):
            if request.resource_type in {"image", "media", "font"}:
                route.abort()
            else:
                route.continue_()
        page.route("**/*", block_media)

        # ── CCIL first ────────────────────────────────────────────────────────
        bonds = [_enrich_bond(b, prev_levels) for b in scrape_ccil(page, list(prev_levels.keys()))]

        # ── TradingView ───────────────────────────────────────────────────────
        for symbol in TV_SYMBOLS:
            print(f"  Fetching {symbol['name']} …")
            quotes.append(scrape_tv_symbol(page, symbol))
            time.sleep(1)

        browser.close()
    return bonds, quotes


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL
# ══════════════════════════════════════════════════════════════════════════════
def build_email_body(bonds: list[BondQuote], quotes: list[Quote]) -> str:
    timestamp = datetime.now().strftime("%d %b %Y, %I:%M %p")

    # ── Bond rows ─────────────────────────────────────────────────────────────
    bond_rows = ""
    for b in bonds:
        if b.error:
            bond_rows += f"""
            <tr>
              <td class="sym">{b.security}</td>
              <td colspan="4" class="red" style="font-size:11px;">ERR: {b.error}</td>
            </tr>"""
        else:
            bond_rows += f"""
            <tr>
              <td class="sym">{b.security}</td>
              <td class="price">{b.ltp  or "N/A"}</td>
              <td class="price">{b.lty  or "N/A"}</td>
              <td class="prev">{b.prev_price or "N/A"}</td>
              <td class="prev">{b.prev_yield or "N/A"}</td>
            </tr>"""

    # ── Market rows ───────────────────────────────────────────────────────────
    def chg_cls(q):
        if q.change and (q.change.startswith("−") or q.change.startswith("-")):
            return "red"
        return "grn"

    mkt_rows = ""
    for q in quotes:
        if q.error:
            mkt_rows += f"""
            <tr>
              <td class="sym">{q.name}</td>
              <td colspan="3" class="red" style="font-size:11px;">ERR: {q.error}</td>
            </tr>"""
        else:
            price    = f"{q.current_price or 'N/A'} {q.currency or ''}".strip()
            prev     = q.previous_close or "N/A"
            chg      = q.change     or ""
            pct      = q.change_pct or ""
            chg_html = f"{chg}<br><small>{pct}</small>" if chg and pct else (chg or pct or "N/A")
            mkt_rows += f"""
            <tr>
              <td class="sym">{q.name}</td>
              <td class="price">{price}</td>
              <td class="prev">{prev}</td>
              <td class="chg {chg_cls(q)}">{chg_html}</td>
            </tr>"""

    return f"""
        <html>
        <head>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <style>
        body{{margin:0;padding:12px;background:#f5f5f5;font-family:Arial,sans-serif;}}
        .wrap{{max-width:480px;margin:0 auto;background:#fff;border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden;}}
        /* header */
        .hdr{{background:#1a237e;padding:10px 14px;}}
        .hdr h2{{color:#fff;margin:0;font-size:14px;}}
        .hdr p{{color:#c5cae9;margin:3px 0 0;font-size:11px;}}
        /* section labels */
        .sec-hdr{{background:#e8eaf6;padding:6px 10px;font-size:11px;font-weight:700;
                    color:#3949ab;letter-spacing:.5px;text-transform:uppercase;
                    border-top:1px solid #dde3f0;}}
        /* tables */
        table{{width:100%;border-collapse:collapse;font-size:13px;}}
        th{{background:#f0f4ff;padding:6px 7px;text-align:left;color:#555;
            font-weight:600;border-bottom:2px solid #dde3f0;white-space:nowrap;}}
        td{{padding:6px;border-bottom:1px solid #f0f0f0;vertical-align:middle;}}
        .sym{{font-weight:700;white-space:nowrap;font-size:12px;}}
        .price{{white-space:nowrap;}}
        .prev{{color:#777;white-space:nowrap;}}
        .chg{{font-weight:600;white-space:nowrap;}}
        .red{{color:#c0392b;}} .grn{{color:#27ae60;}}
        .ft{{padding:10px 14px;font-size:10px;color:#bbb;border-top:1px solid #eee;}}
        small{{font-size:10px;opacity:.85;}}
        </style>
        </head>
        <body>
        <div class="wrap">

        <!-- Header -->
        <div class="hdr">
            <h2>📊 Market Snapshot</h2>
            <p>{timestamp}</p>
        </div>

        <!-- ── Section 1: G-Sec Bonds ── -->
        <div class="sec-hdr">🏦 G-Sec &nbsp;·&nbsp; RBI NDS-OM</div>
        <table>
            <thead>
            <tr>
                <th>Security</th>
                <th>Price</th>
                <th>Yield&nbsp;%</th>
                <th>Prev<br>Price</th>
                <th>Prev<br>Yield&nbsp;%</th>
            </tr>
            </thead>
            <tbody>{bond_rows}
            </tbody>
        </table>

        <!-- ── Section 2: Market Prices ── -->
        <div class="sec-hdr">🌐 Markets &nbsp;·&nbsp; TradingView</div>
        <table>
            <thead>
            <tr>
                <th>Symbol</th>
                <th>Price</th>
                <th>Prev</th>
                <th>Chg&nbsp;/ %</th>
            </tr>
            </thead>
            <tbody>{mkt_rows}
            </tbody>
        </table>

        <div class="ft">Sources: CCIL NDS-OM &nbsp;·&nbsp; TradingView &nbsp;·&nbsp; Auto-generated</div>
        </div>
        </body>
        </html>
    """


def send_telegram(bonds: list[BondQuote], quotes: list[Quote]) -> None:
    token    = TELEGRAM_CONFIG["bot_token"]
    base_url = f"https://api.telegram.org/bot{token}"

    # ── Get all chat IDs ──────────────────────────────────────────────────────
    data     = requests.get(f"{base_url}/getUpdates", timeout=10).json()
    chat_ids = set()
    for update in data.get("result", []):
        msg = update.get("message") or update.get("channel_post")
        if msg and msg.get("chat"):
            chat_ids.add(msg["chat"]["id"])

    if not chat_ids:
        print("  No chat IDs found — has anyone messaged the bot yet?")
        return

    # ── Build message ─────────────────────────────────────────────────────────
    ts  = datetime.now().strftime("%d %b %Y, %I:%M %p")
    msg = f"<b>📊 Market Snapshot</b>  <i>{ts}</i>\n\n"

    # Bonds
    msg += "<b>🏦 G-Sec · RBI NDS-OM</b>\n"
    msg += "<pre>"
    msg += f"{'Security':<18} {'Px':>8} {'Yld':>7} {'PxPv':>8} {'YPv':>7}\n"
    msg += "─" * 52 + "\n"
    for b in bonds:
        if b.error:
            msg += f"{b.security:<18} ERROR\n"
        else:
            msg += (f"{b.security:<18}"
                    f" {(b.ltp or 'N/A'):>8}"
                    f" {(b.lty or 'N/A'):>7}"
                    f" {(b.prev_price or 'N/A'):>8}"
                    f" {(b.prev_yield or 'N/A'):>7}\n")
    msg += "</pre>\n"

    # Markets
    msg += "<b>🌐 Markets · TradingView</b>\n"
    msg += "<pre>"
    msg += f"{'Sym':<8} {'Price':>9} {'Prev':>9} {'Chg':>7} {'%':>6}\n"
    msg += "─" * 44 + "\n"
    for q in quotes:
        if q.error:
            msg += f"{q.name:<8} ERROR\n"
        else:
            price = q.current_price or "N/A"
            prev = q.previous_close or "N/A"
            chg = q.change or "N/A"
            pct = q.change_pct or ""
            msg += (f"{q.name:<8}"
                     f" {price:>9}"
                     f" {prev:>9}"
                     f" {chg:>7}"
                     f" {pct:>6}\n")
    msg += "</pre>"

    # ── Send to all chats ─────────────────────────────────────────────────────
    for chat_id in chat_ids:
        r = requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=20,
        )
        print(f"  → chat {chat_id}: {r.json().get('ok')}")


def send_email(bonds: list[BondQuote], quotes: list[Quote]) -> str:
    cfg     = EMAIL_CONFIG
    subject = f"Market Snapshot — {datetime.now().strftime('%d %b %Y %I:%M %p')}"
    body    = build_email_body(bonds, quotes)


    payload = {
        "fromEmailId": cfg["from_email"],
        "toEmailIds" : cfg["to_emails"],
        "subject"    : subject,
        "emailBody"  : body,
    }
    if cfg.get("bcc_emails"):
        payload["bccEmailIds"] = cfg["bcc_emails"]

    headers = {
        "authorization": cfg["token"],
        "cache-control": "no-cache",
        "x-api-key"    : cfg["x_api_key"],
    }

    user = "atharva.waze"
    password = "Mumbai@12361"

    proxies = {
        "http": f"http://{user}:{password}@zia.nuvama.com:80",
        "https": f"http://{user}:{password}@zia.nuvama.com:443",
    }
    
    response = requests.post(
        cfg["api_url"],
        data=payload,
        headers=headers,
        verify=False,
        timeout=30,
    )
    return response.text


# ══════════════════════════════════════════════════════════════════════════════
#  CONSOLE OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

def print_results(bonds, quotes):
    print("\n── G-Sec Bonds (CCIL NDS-OM) " + "─" * 45)
    print(f"{'Security':<22} {'Yield%':<10} {'Yld Chg':<10} {'Price':<10} {'Px Chg'}")
    print("-" * 66)
    for b in bonds:
        if b.error:
            print(f"{b.security:<22} ERROR: {b.error}")
        else:
            print(f"{b.security:<22} {b.lty or 'N/A':<10} {b.yield_chg or 'N/A':<10} "
                  f"{b.ltp or 'N/A':<10} {b.price_chg or 'N/A'}")

    print("\n── Markets (TradingView) " + "─" * 40)
    print(f"{'Symbol':<10} {'Price':<16} {'Prev Close':<14} {'Change'}")
    print("-" * 58)
    for q in quotes:
        if q.error:
            print(f"{q.name:<10} ERROR: {q.error}")
        else:
            price  = f"{q.current_price or 'N/A'} {q.currency or ''}".strip()
            prev   = q.previous_close or "N/A"
            change = f"{q.change or ''} {q.change_pct or ''}".strip() or "N/A"
            print(f"{q.name:<10} {price:<16} {prev:<14} {change}")
    print()


def save_json(bonds, quotes, path="quotes.json"):
    with open(path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "bonds"    : [asdict(b) for b in bonds],
            "markets"  : [asdict(q) for q in quotes],
        }, f, indent=2)
    print(f"Results saved → {path}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ── Load prev levels (file → seed fallback) ───────────────────────────────
    prev_levels = load_prev_levels()
    # Bonds to extract from CCIL NDS-OM (driven by PREV_LEVELS keys)
    TARGET_BONDS = list(prev_levels.keys())
    print(f"Loaded prev levels for {len(prev_levels)} bonds.")

    # ── Scrape ────────────────────────────────────────────────────────────────
    print("Fetching data …\n")
    bonds, quotes = scrape_all(prev_levels)
    print_results(bonds, quotes)
    save_json(bonds, quotes)

    # ── EOD snapshot ──────────────────────────────────────────────────────────
    if is_eod():
        print("\n[EOD] Time >= 17:00 IST — saving today\'s levels as tomorrow\'s prev …")
        prev_levels = save_prev_levels(bonds, prev_levels)
    else:
        from datetime import timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = __import__("datetime").datetime.now(ist)
        print(f"\n[info] Not EOD yet ({now_ist.strftime('%H:%M')} IST). "
              f"Prev levels unchanged.")

    # ── Send email ────────────────────────────────────────────────────────────
    # print("\nSending email …")
    # result = send_email(bonds, quotes)
    # print(f"API response: {result}")
    print("\nSending Telegram message …")
    send_telegram(bonds, quotes)
