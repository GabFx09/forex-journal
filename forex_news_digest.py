"""
forex_news_digest.py
====================
Mengambil berita Forex & Geopolitik dari 4 sumber, menganalisis sentimen,
lalu mengirim 3 email HTML terpisah ke Gmail setiap 07:00 WIB:

  ✉ Email 1 — Kalender Ekonomi Forex Minggu Ini (format tabel ForexFactory)
  ✉ Email 2 — Analisis Sentimen Lengkap
  ✉ Email 3 — Geopolitik Penting yang Mempengaruhi Pasar Forex

Sumber  : Reuters, Investing.com, ForexFactory, FinancialJuice,
          ForexLive, FXStreet, DailyFX, Bloomberg Markets, Reuters Currencies
Sentimen: VADER + booster kata kunci forex (min. 40 berita)
Geopolit: Fokus pada peristiwa yang mempengaruhi pasar valuta asing (min. 40 berita)
Filter  : Berita saham, kripto, komoditas pertanian otomatis disaring
Kirim   : Gmail SMTP (App Password)
Jadwal  : schedule library — jalankan script terus-menerus di background

Setup:
  1. pip install requests beautifulsoup4 feedparser vaderSentiment schedule python-dotenv
  2. Buat App Password Gmail di: https://myaccount.google.com/apppasswords
  3. Isi file .env (lihat .env.example)
  4. python forex_news_digest.py
"""

import smtplib
import feedparser
import requests
import schedule
import time
import logging
import html as html_module
import re
import json as _json
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from dotenv import load_dotenv
import os
import urllib.parse as _urlparse

# Gunakan path absolut agar .env ditemukan saat dipanggil Task Scheduler
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

# ─── CONFIG ──────────────────────────────────────────────────────────────────

GMAIL_USER      = os.getenv("GMAIL_USER", "")
GMAIL_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD", "")
SEND_TO         = os.getenv("SEND_TO", GMAIL_USER)
SEND_HOUR       = int(os.getenv("SEND_HOUR", "7"))
NEWS_HOURS_BACK     = 36
MAX_PER_SOURCE      = 20   # jumlah item per sumber (dinaikkan agar tab Sentimen bisa capai 80-100 berita)
MIN_NEWS_SENTIMEN   = 80   # target minimum berita sentimen (tab F10 SENT — day trader butuh cakupan lebih dalam)
MIN_NEWS_GEOPOLITIK = 30   # target minimum berita geopolitik
JSON_DIR            = os.getenv("JSON_DIR", os.path.join(_SCRIPT_DIR, "files-forex"))

_LOG_FILE = os.path.join(_SCRIPT_DIR, "forex_digest.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def _translate_id(texts: list[str]) -> list[str]:
    """Terjemahkan list judul dari Inggris ke Indonesia via Google Translate (tanpa package tambahan)."""
    if not texts:
        return texts
    results: list[str] = []
    for text in texts:
        try:
            q   = _urlparse.quote(text)
            url = (f"https://translate.googleapis.com/translate_a/single"
                   f"?client=gtx&sl=en&tl=id&dt=t&q={q}")
            r   = requests.get(url, timeout=5)
            data = r.json()
            translated = "".join(seg[0] for seg in (data[0] or []) if seg and seg[0])
            results.append(translated if translated else text)
        except Exception:
            results.append(text)
    return results


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─── KATA KUNCI MATA UANG & GEOPOLITIK ───────────────────────────────────────

CURRENCY_KEYWORDS: dict[str, list[str]] = {
    "USD": ["dollar", "usd", "fed ", "federal reserve", "fomc", "greenback", "us economy", "united states economy"],
    "EUR": ["euro", "eur ", "eurozone", "ecb ", "european central bank", "eu economy"],
    "GBP": ["pound", "sterling", "gbp", "bank of england", "boe ", "british economy", "uk economy"],
    "JPY": ["yen", "jpy ", "boj ", "bank of japan", "japan economy", "japanese economy"],
    "AUD": ["australian dollar", "aud ", "rba ", "reserve bank of australia", "australian economy"],
    "CAD": ["canadian dollar", "cad ", "bank of canada", "boc ", "loonie", "canadian economy"],
    "CHF": ["swiss franc", "chf ", "swiss national bank", "snb ", "swiss economy"],
    "NZD": ["new zealand dollar", "nzd ", "rbnz ", "kiwi dollar", "new zealand economy"],
    "CNY": ["yuan", "cny ", "renminbi", "rmb ", "pboc ", "china economy", "chinese economy"],
}

GEOPOLITIK_KEYWORDS: list[str] = [
    # Konflik & keamanan (mempengaruhi safe-haven currencies)
    "war", "conflict", "invasion", "attack", "missile", "troops", "military",
    "terrorism", "terrorist", "coup", "nuclear",
    "escalation", "ceasefire", "peace deal", "peace talks",
    # Sanksi & perdagangan (langsung mempengaruhi pasangan mata uang)
    "sanction", "embargo", "tariff", "trade war", "trade deal", "trade tension",
    "trade restriction", "export ban", "import duty", "trade deficit", "trade surplus",
    # Intervensi & kebijakan mata uang (forex-specific)
    "currency intervention", "forex intervention", "central bank intervention",
    "currency devaluation", "currency war", "capital control", "capital flight",
    "exchange rate manipulation", "competitive devaluation",
    # Krisis ekonomi (mempengaruhi nilai tukar)
    "recession", "default", "debt crisis", "financial crisis", "sovereign debt",
    "currency crisis", "balance of payment", "current account deficit",
    # Politik (mempengaruhi kepercayaan mata uang)
    "election", "government collapse", "political crisis", "political instability",
    # Organisasi internasional (kebijakan moneter global)
    "nato", "united nations", "g7", "g20", "imf", "world bank", "wto", "bis ",
    # Energi (relevan untuk CAD, NOK, AUD — commodity currencies)
    "opec", "oil price", "energy crisis", "oil sanction",
    # Umum
    "tension", "geopolit", "diplomatic", "diplomacy",
]

# Peta kata kunci geopolitik → pasangan forex yang terpengaruh
_GEO_PAIR_IMPACT: dict[str, list[str]] = {
    "war":                   ["USD/JPY", "XAU/USD", "USD/CHF"],
    "conflict":              ["USD/JPY", "EUR/USD", "XAU/USD"],
    "invasion":              ["EUR/USD", "USD/RUB", "XAU/USD"],
    "sanction":              ["EUR/USD", "USD/RUB"],
    "tariff":                ["USD/CNY", "AUD/USD", "EUR/USD"],
    "trade war":             ["USD/CNY", "AUD/USD"],
    "trade deal":            ["AUD/USD", "USD/CNY", "EUR/USD"],
    "trade restriction":     ["USD/CNY", "EUR/USD", "AUD/USD"],
    "currency intervention": ["USD/JPY", "EUR/USD", "USD/CHF"],
    "currency devaluation":  ["USD/CNY", "USD/TRY"],
    "currency war":          ["EUR/USD", "USD/JPY", "USD/CNY"],
    "capital control":       ["USD/CNY", "EUR/USD"],
    "capital flight":        ["USD/JPY", "USD/CHF", "XAU/USD"],
    "sovereign debt":        ["EUR/USD", "USD/JPY"],
    "currency crisis":       ["USD/JPY", "XAU/USD", "USD/CHF"],
    "opec":                  ["CAD/USD", "NOK/USD"],
    "oil price":             ["CAD/JPY", "NOK/SEK"],
    "election":              ["EUR/USD", "GBP/USD"],
    "rate hike":             ["USD", "EUR", "GBP"],
    "rate cut":              ["USD", "EUR", "GBP"],
    "recession":             ["USD/JPY", "USD/CHF", "XAU/USD"],
    "default":               ["USD", "EUR"],
    "tension":               ["USD/JPY", "XAU/USD"],
    "ceasefire":             ["EUR/USD", "XAU/USD"],
    "nuclear":               ["USD/JPY", "XAU/USD"],
    "imf":                   ["USD", "EUR", "emerging markets"],
    "g7":                    ["USD", "EUR", "GBP", "JPY"],
    "g20":                   ["USD", "CNY", "EUR"],
}

# ─── DATA MODEL ──────────────────────────────────────────────────────────────

@dataclass
class NewsItem:
    source: str
    title: str
    url: str
    summary: str = ""
    published: Optional[datetime] = None
    sentiment_label: str = "Netral"
    sentiment_score: float = 0.0
    sentiment_emoji: str = "⚪"
    impact: str = "low"


def _sort_key(item: NewsItem) -> datetime:
    """Kunci urut berdasarkan waktu publish (timezone-safe)."""
    if not item.published:
        return datetime.min.replace(tzinfo=timezone.utc)
    pub = item.published
    return pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc)


# ─── FILTER BERITA NON-FOREX ──────────────────────────────────────────────────

_NON_FOREX_FILTER: list[str] = [
    # Kripto / Cryptocurrency
    "bitcoin", "ethereum", "crypto market", "cryptocurrency market",
    "blockchain token", "nft market", "defi protocol", "dogecoin",
    "binance coin", "stablecoin", "web3 ", "crypto exchange",
    # Saham / Stocks (spesifik, bukan berita makro)
    "quarterly earnings", "earnings per share", "stock split", "ipo filing",
    "stock buyback", "stock rally", "equity market rally",
    "mutual fund", "hedge fund returns",
    # Komoditas pertanian / Agricultural
    "corn futures", "wheat futures", "soybean futures", "cocoa futures",
    "coffee futures", "sugar futures", "cotton futures", "livestock futures",
    "grain prices", "crop yield",
]

_FOREX_POSITIVE_KEYWORDS: list[str] = [
    "dollar", "euro", "pound", "yen", "forex", "currency", "exchange rate",
    "federal reserve", "ecb", "bank of england", "bank of japan",
    "interest rate", "inflation", "gdp", "nfp", "cpi", "pmi",
    "monetary policy", "rate hike", "rate cut", "central bank",
    "tariff", "trade war", "trade deal", "usd", "eur", "gbp", "jpy",
    "aud", "cad", "chf", "nzd", "fomc", "rba", "rbnz", "snb",
]


def _is_forex_relevant(item: NewsItem) -> bool:
    """Kembalikan True jika berita relevan dengan pasar forex (bukan saham/kripto/komoditas)."""
    text = f"{item.title} {item.summary}".lower()
    # Tolak jika mengandung kata kunci non-forex
    if any(kw in text for kw in _NON_FOREX_FILTER):
        return False
    # Terima tanpa syarat jika dari sumber khusus forex
    if item.source in ("ForexLive", "FXStreet", "DailyFX", "ForexFactory",
                       "Investing.com Forex", "FinancialJuice"):
        return True
    # Terima jika jelas geopolitik — peristiwa ini mempengaruhi forex
    # bahkan jika sumber adalah media umum (BBC, Al Jazeera, AP, dll)
    if any(kw in text for kw in GEOPOLITIK_KEYWORDS):
        return True
    # Untuk sumber umum lainnya: harus ada kata kunci forex eksplisit
    return any(kw in text for kw in _FOREX_POSITIVE_KEYWORDS)


# ─── KALENDER EKONOMI — MODEL & KONSTANTA ────────────────────────────────────

_HARI_ID: dict[str, str] = {
    "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
    "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu",
}

_BULAN_ID: dict[str, str] = {
    "January": "Januari", "February": "Februari", "March": "Maret",
    "April": "April", "May": "Mei", "June": "Juni",
    "July": "Juli", "August": "Agustus", "September": "September",
    "October": "Oktober", "November": "November", "December": "Desember",
}

_IMPACT_CFG: dict[str, dict] = {
    "high":    {"warna": "#ef4444", "bg": "#2d0a0a", "label": "Tinggi",  "dot_color": "#ef4444"},
    "medium":  {"warna": "#f97316", "bg": "#2d1505", "label": "Sedang",  "dot_color": "#f97316"},
    "low":     {"warna": "#eab308", "bg": "#2a2200", "label": "Rendah",  "dot_color": "#eab308"},
    "holiday": {"warna": "#6b7280", "bg": "#1e2030", "label": "Libur",   "dot_color": "#6b7280"},
    "none":    {"warna": "#374151", "bg": "#1e2030", "label": "—",       "dot_color": "#374151"},
}


@dataclass
class EconomicEvent:
    date_str: str      # "2025-01-15"
    day_id: str        # "Senin"
    time_wib: str      # "20:30" atau "Sepanjang Hari"
    currency: str      # "USD"
    impact: str        # "high" | "medium" | "low" | "holiday" | "none"
    event_name: str
    actual: str = ""
    forecast: str = ""
    previous: str = ""


# ─── SCRAPERS ─────────────────────────────────────────────────────────────────

def _strip_html(raw: str, max_len: int = 400) -> str:
    text = BeautifulSoup(raw, "html.parser").get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _parse_time(entry) -> Optional[datetime]:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return None


def _fetch_rss(feed_url: str, source_name: str) -> list[NewsItem]:
    items = []
    try:
        feed = feedparser.parse(feed_url, request_headers=HEADERS)
        for entry in feed.entries[:MAX_PER_SOURCE]:
            summary = ""
            if hasattr(entry, "summary"):
                summary = _strip_html(entry.summary)
            elif hasattr(entry, "description"):
                summary = _strip_html(entry.description)
            items.append(NewsItem(
                source=source_name,
                title=html_module.unescape(entry.get("title", "")).strip(),
                url=entry.get("link", ""),
                summary=summary,
                published=_parse_time(entry),
            ))
    except Exception as e:
        log.warning(f"[{source_name}] RSS gagal: {e}")
    return items


def fetch_reuters() -> list[NewsItem]:
    items = []
    for url, name in [
        ("https://feeds.reuters.com/reuters/businessNews", "Reuters Business"),
        ("https://feeds.reuters.com/reuters/worldNews",    "Reuters World"),
    ]:
        items.extend(_fetch_rss(url, name))
    log.info(f"[Reuters] {len(items)} item")
    return items


def fetch_investing() -> list[NewsItem]:
    items = []
    for url, name in [
        ("https://www.investing.com/rss/news_25.rss", "Investing.com Forex"),
        ("https://www.investing.com/rss/news_95.rss", "Investing.com Economy"),
    ]:
        items.extend(_fetch_rss(url, name))
    log.info(f"[Investing.com] {len(items)} item")
    return items


def fetch_forexfactory() -> list[NewsItem]:
    items = []
    try:
        feed = feedparser.parse("https://www.forexfactory.com/rss?type=news", request_headers=HEADERS)
        if feed.entries:
            for entry in feed.entries[:MAX_PER_SOURCE]:
                items.append(NewsItem(
                    source="ForexFactory",
                    title=html_module.unescape(entry.get("title", "")).strip(),
                    url=entry.get("link", "https://www.forexfactory.com/news"),
                    summary=_strip_html(entry.get("summary", "")),
                    published=_parse_time(entry),
                ))
            log.info(f"[ForexFactory] {len(items)} item (RSS)")
            return items
    except Exception as e:
        log.debug(f"[ForexFactory] RSS gagal, coba HTML scrape: {e}")

    try:
        resp = requests.get("https://www.forexfactory.com/news", headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []
        for sel in ["div.flexposts__story", "div.news-item", "article"]:
            articles = soup.select(sel)
            if articles:
                break
        for art in articles[:MAX_PER_SOURCE]:
            title_el = art.select_one("h3 a, h2 a, .flexposts__story-title a, .title a")
            if not title_el:
                continue
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.forexfactory.com" + href
            pub = None
            time_el = art.select_one("time")
            if time_el and time_el.get("datetime"):
                try:
                    pub = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00"))
                except Exception:
                    pass
            items.append(NewsItem(
                source="ForexFactory",
                title=title_el.get_text(strip=True),
                url=href, published=pub,
            ))
        log.info(f"[ForexFactory] {len(items)} item (HTML)")
    except Exception as e:
        log.warning(f"[ForexFactory] scrape gagal: {e}")
    return items


def fetch_financialjuice() -> list[NewsItem]:
    items = []
    for ep in [
        "https://www.financialjuice.com/home/GetLiveNews?type=forex&page=1",
        "https://www.financialjuice.com/home/loadmore?category=forex&page=1",
    ]:
        try:
            resp = requests.get(ep, headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"}, timeout=15)
            data = resp.json()
            rows = data if isinstance(data, list) else data.get("data", data.get("items", []))
            for row in rows[:MAX_PER_SOURCE]:
                title = row.get("headline", row.get("title", row.get("Headline", "")))
                if not title:
                    continue
                pub_str = row.get("time", row.get("created_at", row.get("Time", "")))
                pub = None
                if pub_str:
                    try:
                        pub = datetime.fromisoformat(str(pub_str).replace("Z", "+00:00").rstrip("+00:00"))
                    except Exception:
                        pass
                url = row.get("link", row.get("url", row.get("Link", "https://www.financialjuice.com")))
                items.append(NewsItem(
                    source="FinancialJuice",
                    title=title.strip(), url=url,
                    summary=_strip_html(str(row.get("description", row.get("body", "")))),
                    published=pub,
                ))
            if items:
                log.info(f"[FinancialJuice] {len(items)} item (JSON)")
                return items
        except Exception as e:
            log.debug(f"[FinancialJuice] JSON endpoint gagal: {e}")

    try:
        feed = feedparser.parse("https://www.financialjuice.com/feed", request_headers=HEADERS)
        if feed.entries:
            for entry in feed.entries[:MAX_PER_SOURCE]:
                items.append(NewsItem(
                    source="FinancialJuice",
                    title=html_module.unescape(entry.get("title", "")).strip(),
                    url=entry.get("link", ""),
                    summary=_strip_html(entry.get("summary", "")),
                    published=_parse_time(entry),
                ))
            log.info(f"[FinancialJuice] {len(items)} item (RSS)")
            return items
    except Exception as e:
        log.debug(f"[FinancialJuice] RSS gagal: {e}")

    try:
        resp = requests.get("https://www.financialjuice.com/", headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for el in soup.select(".newsfeed-item, .news-item, .feed-item, li.item")[:MAX_PER_SOURCE]:
            title_el = el.select_one("a, .headline, h3, h4")
            if title_el:
                items.append(NewsItem(
                    source="FinancialJuice",
                    title=title_el.get_text(strip=True),
                    url=title_el.get("href", "https://www.financialjuice.com"),
                ))
        log.info(f"[FinancialJuice] {len(items)} item (HTML)")
    except Exception as e:
        log.warning(f"[FinancialJuice] semua metode gagal: {e}")
    return items


_FJ_MUST_FOREX: list[str] = [
    # Mata uang utama — "franc" sengaja ditulis "swiss franc" (bukan "franc"
    # saja) karena "franc" adalah substring dari "france"/"french"
    "usd", "eur", "gbp", "jpy", "aud", "nzd", "cad", "chf", "cny", "yuan",
    "rmb", "dollar", "euro", "pound", "yen", "swiss franc", "kiwi", "loonie",
    # Bank sentral
    "fed ", "fomc", "ecb ", "boe ", "boj ", "rba ", "rbnz", "boc ", "snb ",
    "pboc", "federal reserve", "bank of england", "bank of japan",
    "bank of canada", "reserve bank", "european central bank",
    "central bank", "rate decision", "rate hike", "rate cut", "basis point",
    # Data ekonomi makro
    "cpi", "ppi", "gdp", "nfp", "pmi", "inflation", "deflation",
    "unemployment", "payroll", "payrolls", "retail sales", "trade balance",
    "current account", "fiscal", "monetary policy", "interest rate",
    "yield", "bond yield", "treasury",
    # Geopolitik / Makro global berdampak FX
    "tariff", "trade war", "trade deal", "sanction", "geopolit",
    "recession", "stagflation", "g7", "g20", "imf", "world bank",
    # Sentimen risiko & komoditas yang menggerakkan safe-haven/commodity currencies
    "safe haven", "safe-haven", "risk sentiment", "risk appetite",
    "risk aversion", "risk-off", "risk-on", "dollar index", "oil price",
    "crude oil", "gold price", "opec",
]

_FJ_BLOCK_STOCK: list[str] = [
    # Indeks saham
    "s&p 500", "s&p500", "nasdaq", "dow jones", "dow 30", "ftse", "dax ",
    "nikkei", "hang seng", "asx 200", "cac 40", "stoxx", "russell 2000",
    "stock market", "stock index", "equity market", "stock rally",
    "shares rally", "shares fall", "shares rise", "shares drop",
    # Istilah pasar saham
    "earnings per share", "quarterly earnings", "annual earnings",
    "revenue beat", "profit warning", "ipo ", "stock split", "dividend",
    "stock buyback", "share buyback", "market cap", "valuation",
    "analyst upgrade", "analyst downgrade", "price target",
    # Perusahaan spesifik (saham)
    "tesla ", "apple ", "microsoft ", "amazon ", "google ", "meta ",
    "nvidia ", "netflix ", "disney ", "boeing ", "toyota ", "samsung ",
    "volkswagen ", "shell ", "bp ", "exxon ",
    # Kripto
    "bitcoin", "ethereum", "crypto", "cryptocurrency", "blockchain",
    "defi", "nft", "token ", "altcoin", "stablecoin", "binance",
    # Komoditas non-FX
    "corn ", "wheat ", "soybean", "cocoa ", "coffee futures",
    "sugar futures", "cotton futures", "livestock", "grain ",
    # Misc non-forex
    "box office", "election campaign", "sport", "fifa", "nba", "nfl",
]


def _kw_hit(text: str, keywords: list[str]) -> bool:
    """Cocokkan kata kunci dengan batas kata (\\b), bukan substring polos —
    kode mata uang 3-huruf ("cad","aud","eur",dst) gampang nyangkut sbg
    substring kata lain sama sekali tak terkait (mis. "cad" di "decade",
    "aud" di "fraud", "eur" di "neuron"). \\b menghindari itu tanpa perlu
    daftar spasi manual per keyword."""
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw.strip()) + r"\b", text):
            return True
    return False


def _fj_is_forex_critical(title: str) -> bool:
    """True jika berita benar-benar penting untuk forex, tanpa unsur saham."""
    t = title.lower()
    # Blokir keras jika ada kata kunci non-forex
    if _kw_hit(t, _FJ_BLOCK_STOCK):
        return False
    # Wajib ada minimal satu kata kunci forex penting
    return _kw_hit(t, _FJ_MUST_FOREX)


def _fj_supplement_ok(item: "NewsItem") -> bool:
    """Filter suplemen tab Sentimen dari koleksi umum (items). Beda dari
    _fj_is_forex_critical(title) di atas: cek judul+ringkasan sekaligus,
    karena banyak berita (Reuters/Bloomberg/BBC dll) baru menyebut kata
    kunci forex di ringkasan, bukan di judul — kalau cuma cek judul,
    mayoritas kandidat yang sebenarnya relevan malah terbuang."""
    t = f"{item.title} {item.summary}".lower()
    if _kw_hit(t, _FJ_BLOCK_STOCK):
        return False
    return _kw_hit(t, _FJ_MUST_FOREX)


def fetch_fj_rss() -> list[NewsItem]:
    """FinancialJuice RSS — 80-100 item forex penting, tanpa saham, judul Bahasa Indonesia."""
    TARGET = 90
    seen: set[str] = set()
    candidates: list[NewsItem] = []

    rss_endpoints = [
        "https://www.financialjuice.com/feed.ashx?xy=rss",
        "https://www.financialjuice.com/feed.ashx?xy=rss&category=forex",
        "https://www.financialjuice.com/feed.ashx?xy=rss&type=all",
        "https://www.financialjuice.com/feed",
    ]

    for url in rss_endpoints:
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            added = 0
            for entry in feed.entries:
                title = html_module.unescape(entry.get("title", "")).strip()
                title = re.sub(r"^FinancialJuice:\s*", "", title)
                key   = title.lower()
                if not title or key in seen:
                    continue
                seen.add(key)
                if not _fj_is_forex_critical(title):
                    continue
                candidates.append(NewsItem(
                    source="FinancialJuice",
                    title=title,
                    url=entry.get("link", ""),
                    summary=_strip_html(entry.get("summary", "")),
                    published=_parse_time(entry),
                ))
                added += 1
            if added:
                log.info(f"[FJ-RSS] +{added} item forex lolos filter dari {url}")
        except Exception as e:
            log.debug(f"[FJ-RSS] {url} gagal: {e}")

    # Urutkan berita terbaru dulu — day trader butuh info paling mutakhir di atas
    candidates.sort(key=_sort_key, reverse=True)
    items = candidates[:TARGET]
    log.info(f"[FJ-RSS] {len(candidates)} lolos filter → ambil {len(items)} item")

    # Terjemahkan semua judul ke Bahasa Indonesia
    if items:
        titles     = [i.title for i in items]
        translated = _translate_id(titles)
        for i, item in enumerate(items):
            item.title = translated[i]
        log.info(f"[FJ-RSS] Terjemahan selesai → {len(items)} judul")

    return items


def fetch_forexlive() -> list[NewsItem]:
    """ForexLive — sumber berita forex real-time terpercaya."""
    items = []
    for url, name in [
        ("https://www.forexlive.com/feed/", "ForexLive"),
        ("https://www.forexlive.com/feed/news", "ForexLive News"),
    ]:
        fetched = _fetch_rss(url, name)
        if fetched:
            items.extend(fetched)
            break
    if not items:
        try:
            resp = requests.get("https://www.forexlive.com/news/", headers=HEADERS, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for art in soup.select("article, .article-item, .story-item")[:MAX_PER_SOURCE]:
                title_el = art.select_one("h2 a, h3 a, .article-title a")
                if not title_el:
                    continue
                href = title_el.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://www.forexlive.com" + href
                items.append(NewsItem(
                    source="ForexLive",
                    title=title_el.get_text(strip=True),
                    url=href,
                ))
        except Exception as e:
            log.warning(f"[ForexLive] HTML scrape gagal: {e}")
    log.info(f"[ForexLive] {len(items)} item")
    return items


def fetch_fxstreet() -> list[NewsItem]:
    """FXStreet — analisis dan berita forex profesional."""
    items = []
    # Tahap 1: coba RSS resmi FXStreet (beberapa kategori)
    for url, name in [
        ("https://rss.fxstreet.com/news",          "FXStreet"),
        ("https://www.fxstreet.com/rss/news",      "FXStreet News"),
        ("https://rss.fxstreet.com/central-banks", "FXStreet Central Banks"),
        ("https://rss.fxstreet.com/rates",         "FXStreet Rates"),
        ("https://rss.fxstreet.com/fundamentals",  "FXStreet Fundamentals"),
    ]:
        fetched = _fetch_rss(url, name)
        if fetched:
            items.extend(fetched)
            break
    if items:
        log.info(f"[FXStreet] {len(items)} item (RSS resmi)")
        return items
    # Tahap 2: fallback Google News RSS — andal, tidak bisa di-block
    for url, name in [
        ("https://news.google.com/rss/search?q=site:fxstreet.com+forex&hl=en-US&gl=US&ceid=US:en",
         "FXStreet via Google News"),
        ("https://news.google.com/rss/search?q=site:fxstreet.com+central+bank&hl=en-US&gl=US&ceid=US:en",
         "FXStreet Central Bank GNews"),
    ]:
        fetched = _fetch_rss(url, name)
        if fetched:
            for it in fetched:
                it.source = "FXStreet"
            items.extend(fetched)
            break
    log.info(f"[FXStreet] {len(items)} item")
    return items


def fetch_dailyfx() -> list[NewsItem]:
    """DailyFX — analisis forex dan berita bank sentral."""
    items = []
    # Tahap 1: coba RSS resmi DailyFX (beberapa endpoint)
    for url, name in [
        ("https://www.dailyfx.com/feeds/forex-market-news", "DailyFX"),
        ("https://www.dailyfx.com/feeds/all",               "DailyFX All"),
        ("https://www.dailyfx.com/feeds/central-bank",      "DailyFX Central Bank"),
        ("https://www.dailyfx.com/feeds/usd",               "DailyFX USD"),
        ("https://www.dailyfx.com/feeds/eur",               "DailyFX EUR"),
    ]:
        fetched = _fetch_rss(url, name)
        if fetched:
            items.extend(fetched)
            break
    if items:
        log.info(f"[DailyFX] {len(items)} item (RSS resmi)")
        return items
    # Tahap 2: fallback Google News RSS
    for url, name in [
        ("https://news.google.com/rss/search?q=site:dailyfx.com+forex&hl=en-US&gl=US&ceid=US:en",
         "DailyFX via Google News"),
        ("https://news.google.com/rss/search?q=site:dailyfx.com+currency&hl=en-US&gl=US&ceid=US:en",
         "DailyFX Currency GNews"),
    ]:
        fetched = _fetch_rss(url, name)
        if fetched:
            for it in fetched:
                it.source = "DailyFX"
            items.extend(fetched)
            break
    log.info(f"[DailyFX] {len(items)} item")
    return items


def fetch_bloomberg_currencies() -> list[NewsItem]:
    """Bloomberg Markets — berita mata uang dan kebijakan bank sentral."""
    items = []
    for url, name in [
        ("https://feeds.bloomberg.com/markets/news.rss", "Bloomberg Markets"),
        ("https://feeds.bloomberg.com/economy/news.rss", "Bloomberg Economy"),
    ]:
        fetched = _fetch_rss(url, name)
        items.extend(fetched)
    if items:
        log.info(f"[Bloomberg] {len(items)} item (RSS)")
        return items
    # Fallback: HTML scrape (Bloomberg bisa blokir bot)
    try:
        resp = requests.get(
            "https://www.bloomberg.com/markets/currencies",
            headers={**HEADERS, "Accept-Encoding": "gzip, deflate"},
            timeout=20,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for el in soup.select(
            "article, [data-type='article'], .story-package-module__story"
        )[:MAX_PER_SOURCE]:
            title_el = el.select_one("h3 a, h2 a, a[href*='/news/articles/']")
            if not title_el:
                continue
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.bloomberg.com" + href
            items.append(NewsItem(
                source="Bloomberg Currencies",
                title=title_el.get_text(strip=True),
                url=href,
            ))
        log.info(f"[Bloomberg] {len(items)} item (HTML)")
    except Exception as e:
        log.warning(f"[Bloomberg] gagal: {e}")
    return items


def fetch_reuters_currencies() -> list[NewsItem]:
    """Reuters Markets/Currencies — berita valuta asing dari Reuters."""
    items = []
    # Tahap 1: semua RSS Reuters yang relevan, filter hanya berita forex
    for url, name in [
        ("https://feeds.reuters.com/reuters/businessNews",  "Reuters Business"),
        ("https://feeds.reuters.com/reuters/worldNews",     "Reuters World"),
        ("https://feeds.reuters.com/Reuters/worldNewsUK",   "Reuters World UK"),
        ("https://feeds.reuters.com/reuters/companyNews",   "Reuters Company"),
    ]:
        for entry_item in _fetch_rss(url, name):
            text = f"{entry_item.title} {entry_item.summary}".lower()
            if any(kw in text for kw in _FOREX_POSITIVE_KEYWORDS):
                entry_item.source = "Reuters Currencies"
                if entry_item.url not in {i.url for i in items}:
                    items.append(entry_item)
    if items:
        log.info(f"[Reuters Currencies] {len(items)} item (RSS filter)")
        return items[:MAX_PER_SOURCE]
    # Tahap 2: fallback Google News RSS — Reuters tidak mengizinkan scraping langsung
    for url, name in [
        ("https://news.google.com/rss/search?q=site:reuters.com+forex+currency&hl=en-US&gl=US&ceid=US:en",
         "Reuters Currencies via Google News"),
        ("https://news.google.com/rss/search?q=site:reuters.com+central+bank+dollar&hl=en-US&gl=US&ceid=US:en",
         "Reuters Central Bank GNews"),
    ]:
        fetched = _fetch_rss(url, name)
        if fetched:
            for it in fetched:
                it.source = "Reuters Currencies"
            items.extend(fetched)
            break
    log.info(f"[Reuters Currencies] {len(items)} item")
    return items[:MAX_PER_SOURCE]


def fetch_gnews_forex() -> list[NewsItem]:
    """Google News RSS — berita forex umum sebagai pengisi jika sumber utama kurang."""
    items = []
    queries = [
        "forex+currency+dollar+interest+rate",
        "central+bank+monetary+policy+currency+exchange",
        "dollar+euro+pound+yen+exchange+rate+market",
    ]
    for q in queries:
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        fetched = _fetch_rss(url, "GNews Forex")
        for it in fetched:
            it.source = "Google News Forex"
        items.extend(fetched)
    log.info(f"[GNews Forex] {len(items)} item")
    return items


def fetch_gnews_geopolitik() -> list[NewsItem]:
    """Google News RSS — khusus berita geopolitik yang mempengaruhi pasar forex."""
    items = []
    queries = [
        "trade+war+tariff+currency+forex",
        "central+bank+intervention+currency+exchange+rate",
        "geopolitical+risk+dollar+forex+safe+haven",
        "sanctions+currency+exchange+forex+market",
        "election+economy+currency+forex+impact",
    ]
    for q in queries:
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        fetched = _fetch_rss(url, "GNews Geopolitik")
        for it in fetched:
            it.source = "Google News Geopolitik"
        items.extend(fetched)
    log.info(f"[GNews Geopolitik] {len(items)} item")
    return items


def fetch_geopolitik_news_sources() -> list[NewsItem]:
    """
    Sumber berita geopolitik tambahan:
    BBC World · Al Jazeera · Associated Press · MarketWatch · CNBC
    Semua RSS ini publik dan tidak diblokir.
    Berita difilter via _is_forex_relevant() → hanya yang relevan forex masuk.
    """
    items: list[NewsItem] = []
    feeds = [
        # ── BBC News ──────────────────────────────────────────────
        ("https://feeds.bbci.co.uk/news/world/rss.xml",       "BBC World"),
        ("https://feeds.bbci.co.uk/news/business/rss.xml",    "BBC Business"),
        ("https://feeds.bbci.co.uk/news/rss.xml",             "BBC Top Stories"),
        # ── Al Jazeera ────────────────────────────────────────────
        ("https://www.aljazeera.com/xml/rss/all.xml",         "Al Jazeera"),
        # ── Associated Press (via RSSHub — proxy publik gratis) ──
        ("https://rsshub.app/apnews/topics/World_News",       "AP World"),
        ("https://rsshub.app/apnews/topics/Business",         "AP Business"),
        # ── MarketWatch ───────────────────────────────────────────
        ("https://feeds.content.dowjones.io/public/rss/mw_topstories",   "MarketWatch"),
        ("https://feeds.content.dowjones.io/public/rss/mw_marketpulse",  "MarketWatch Pulse"),
        ("https://feeds.content.dowjones.io/public/rss/mw_economy",      "MarketWatch Economy"),
        # ── CNBC ──────────────────────────────────────────────────
        ("https://www.cnbc.com/id/15839069/device/rss/rss.html",  "CNBC Forex"),
        ("https://www.cnbc.com/id/10001147/device/rss/rss.html",  "CNBC Economy"),
        ("https://www.cnbc.com/id/100727362/device/rss/rss.html", "CNBC World"),
        ("https://www.cnbc.com/id/20910258/device/rss/rss.html",  "CNBC Markets"),
    ]
    source_counts: dict[str, int] = {}
    for url, name in feeds:
        fetched = _fetch_rss(url, name)
        if fetched:
            source_counts[name] = len(fetched)
            items.extend(fetched)
    if source_counts:
        detail = " · ".join(f"{k}:{v}" for k, v in source_counts.items())
        log.info(f"[Geo Sources] {len(items)} item — {detail}")
    else:
        log.warning("[Geo Sources] Semua feed gagal diakses")
    return items


# ─── SCRAPER KALENDER EKONOMI ─────────────────────────────────────────────────

# Waktu WIB default untuk event "Tentative" per mata uang
# (berdasarkan jam rilis tipikal di zona waktu negara masing-masing → WIB UTC+7)
_TENTATIVE_WIB: dict[str, str] = {
    "CNY": "09:00",  # 10:00 CST (UTC+8)
    "JPY": "07:50",  # 08:50 JST (UTC+9)
    "AUD": "08:30",  # 11:30 AEST (UTC+10)
    "NZD": "07:45",  # 09:45 NZST (UTC+12 → -1 day shift diabaikan, pakai jam lokal)
    "GBP": "13:00",  # 07:00 BST (UTC+1) → Apr–Oct
    "EUR": "15:00",  # 09:00 CEST (UTC+2) → Apr–Oct
    "CHF": "15:00",  # 09:00 CEST (UTC+2)
    "CAD": "19:30",  # 08:30 EDT (UTC-4) → Mar–Nov
    "USD": "19:30",  # 08:30 EDT (UTC-4) → Mar–Nov
}


def _et_to_wib(time_raw: str, currency: str = "") -> str:
    """Konversi waktu ET (default ForexFactory) → WIB (UTC+7)."""
    clean = re.sub(r"\s+", "", time_raw.strip().lower())
    if not clean or clean in ("allday", "tentative"):
        # Gunakan waktu rilis tipikal per mata uang; fallback ke 08:00 WIB
        # Bank holiday akan di-override ke "Sepanjang Hari" di call site
        return _TENTATIVE_WIB.get(currency.upper(), "08:00")
    # EST (Nov–Feb) = UTC-5 → WIB = ET+12; EDT (Mar–Oct) = UTC-4 → WIB = ET+11
    offset = 11 if 3 <= datetime.now(tz=timezone.utc).month <= 10 else 12
    # Coba format lama "8:30am" dulu, lalu fallback ke format 24-jam "08:30" (format baru FF)
    for fmt in ("%I:%M%p", "%H:%M"):
        try:
            t = datetime.strptime(clean, fmt)
            return f"{(t.hour + offset) % 24:02d}:{t.minute:02d}"
        except Exception:
            continue
    return time_raw.strip()


def _parse_ff_date(date_text: str, year: int) -> tuple[str, str]:
    """Parse teks tanggal ForexFactory ('Mon Jan 15') → ('2025-01-15', 'Senin')."""
    text = re.sub(r"\s+", " ", date_text.strip())
    for fmt in ("%a %b %d", "%A %b %d", "%a %B %d", "%A %B %d"):
        try:
            t = datetime.strptime(f"{text} {year}", f"{fmt} %Y")
            # Geser ke tahun berikutnya jika tanggal sudah jauh lewat
            if t.replace(tzinfo=None) < datetime.now() - timedelta(days=60):
                t = t.replace(year=year + 1)
            return t.strftime("%Y-%m-%d"), _HARI_ID.get(t.strftime("%A"), t.strftime("%A"))
        except Exception:
            continue
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%d"), _HARI_ID.get(now.strftime("%A"), "")


def fetch_forexfactory_calendar() -> list[EconomicEvent]:
    """Mengambil kalender ekonomi dari ForexFactory untuk minggu ini."""
    events: list[EconomicEvent] = []
    try:
        resp = requests.get(
            "https://www.forexfactory.com/calendar",
            headers=HEADERS,
            timeout=25,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        table = soup.select_one("table.calendar__table")
        if not table:
            log.warning("[FF Kalender] Tabel kalender tidak ditemukan — mungkin struktur HTML berubah.")
            return events

        now_utc = datetime.now(tz=timezone.utc)
        current_date = now_utc.strftime("%Y-%m-%d")
        current_day  = _HARI_ID.get(now_utc.strftime("%A"), "")

        for row in table.select("tr.calendar__row"):
            row_classes = row.get("class", [])

            # ── Baris pemisah hari ──
            # FF HTML: <td class="calendar__cell">Sun <span>May 17</span></td>
            # Gunakan separator=" " agar "Sun" + "May 17" tidak bergabung jadi "SunMay 17"
            if "calendar__row--day-breaker" in row_classes:
                date_text = row.get_text(separator=" ", strip=True)
                if date_text:
                    current_date, current_day = _parse_ff_date(date_text, now_utc.year)
                else:
                    log.warning(f"[FF Kalender] Day-breaker tanpa tanggal: {str(row)[:120]}")
                continue

            # ── Baris event ──
            time_el     = row.select_one("td.calendar__time")
            currency_el = row.select_one("td.calendar__currency")
            impact_el   = row.select_one("td.calendar__impact span")
            event_el    = row.select_one("span.calendar__event-title, a.calendar__event-title")
            actual_el   = row.select_one("td.calendar__actual")
            forecast_el = row.select_one("td.calendar__forecast")
            previous_el = row.select_one("td.calendar__previous")

            if not event_el:
                continue

            impact = "none"
            if impact_el:
                combined = (
                    " ".join(impact_el.get("class", [])) + " " +
                    impact_el.get("title", "")
                ).lower()
                # FF class format: icon--ff-impact-red/ora/yel/gra (tanpa title attribute)
                if "impact-red" in combined or "high" in combined:
                    impact = "high"
                elif "impact-ora" in combined or "impact-orange" in combined or "medium" in combined:
                    impact = "medium"
                elif "impact-yel" in combined or "impact-yellow" in combined or "low" in combined:
                    impact = "low"
                elif "impact-gra" in combined or "impact-gray" in combined or "holiday" in combined:
                    impact = "holiday"

            _ccy = (currency_el.get_text(strip=True) if currency_el else "").upper()
            _wib = _et_to_wib(time_el.get_text(strip=True) if time_el else "", _ccy)
            # Bank holiday tidak punya jam spesifik — tetap tampilkan "Sepanjang Hari"
            if impact == "holiday":
                _wib = "Sepanjang Hari"
            events.append(EconomicEvent(
                date_str=current_date,
                day_id=current_day,
                time_wib=_wib,
                currency=_ccy,
                impact=impact,
                event_name=event_el.get_text(strip=True),
                actual=(actual_el.get_text(strip=True) if actual_el else ""),
                forecast=(forecast_el.get_text(strip=True) if forecast_el else ""),
                previous=(previous_el.get_text(strip=True) if previous_el else ""),
            ))

        log.info(f"[FF Kalender] {len(events)} event berhasil diambil")
    except Exception as e:
        log.warning(f"[FF Kalender] Gagal mengambil kalender: {e}")
    return events


# ─── ANALISIS SENTIMEN ────────────────────────────────────────────────────────

_vader = SentimentIntensityAnalyzer()

_BULLISH_KEYWORDS = {
    "hawkish", "rate hike", "tightening", "beat", "surge", "rally",
    "strong", "growth", "gain", "optimism", "ceasefire", "deal", "agreement",
    "recovery", "expansion", "hiring", "jobs added",
}
_BEARISH_KEYWORDS = {
    "dovish", "rate cut", "easing", "miss", "decline", "recession",
    "weak", "fall", "loss", "risk", "war", "conflict", "sanction",
    "crisis", "default", "inflation surge", "layoffs", "tension",
    "attack", "escalation", "invasion",
}

# Klasifikasi dampak berita untuk trader harian — dipakai sbg badge di tab
# Sentimen supaya berita market-moving (rilis data/keputusan bank sentral)
# langsung kelihatan beda dari berita latar belakang biasa.
_IMPACT_HIGH_KEYWORDS: set[str] = {
    "nfp", "non-farm payroll", "nonfarm payroll", "payrolls report",
    "cpi", "ppi", "fomc", "rate decision", "interest rate decision",
    "gdp", "unemployment rate", "jobs report", "inflation report",
    "rate hike", "rate cut", "central bank decision",
    "federal reserve decision", "ecb decision", "boe decision", "boj decision",
    "war", "invasion", "sanction", "financial crisis", "debt crisis",
    "default", "recession", "currency intervention", "currency crisis",
}
_IMPACT_MEDIUM_KEYWORDS: set[str] = {
    "pmi", "retail sales", "trade balance", "consumer confidence",
    "housing starts", "durable goods", "speech", "testimony", "minutes",
    "current account", "manufacturing index", "services index",
    "tariff", "trade war", "trade deal", "election", "geopolit",
    "employment change", "wage growth", "producer price",
}


def _impact_level(text_lower: str) -> str:
    """Tentukan tingkat dampak berita (high/medium/low) dari kata kunci judul+ringkasan."""
    if any(kw in text_lower for kw in _IMPACT_HIGH_KEYWORDS):
        return "high"
    if any(kw in text_lower for kw in _IMPACT_MEDIUM_KEYWORDS):
        return "medium"
    return "low"


def _analyze(item: NewsItem) -> NewsItem:
    text = f"{item.title} {item.summary}".lower()
    scores = _vader.polarity_scores(text)
    compound = scores["compound"]
    for kw in _BULLISH_KEYWORDS:
        if kw in text:
            compound = min(1.0, compound + 0.08)
    for kw in _BEARISH_KEYWORDS:
        if kw in text:
            compound = max(-1.0, compound - 0.08)
    item.sentiment_score = round(compound, 3)
    if compound >= 0.05:
        item.sentiment_label, item.sentiment_emoji = "Bullish", "🟢"
    elif compound <= -0.05:
        item.sentiment_label, item.sentiment_emoji = "Bearish", "🔴"
    else:
        item.sentiment_label, item.sentiment_emoji = "Netral", "⚪"
    item.impact = _impact_level(text)
    return item


# ─── DETEKSI DAMPAK MATA UANG & GEOPOLITIK ───────────────────────────────────

def detect_currency_impact(items: list[NewsItem]) -> list[tuple[str, float, int]]:
    """Menghitung skor sentimen rata-rata per mata uang berdasarkan frekuensi penyebutan."""
    scores: dict[str, list[float]] = {c: [] for c in CURRENCY_KEYWORDS}
    for item in items:
        text = f"{item.title} {item.summary}".lower()
        for currency, keywords in CURRENCY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                scores[currency].append(item.sentiment_score)
    result = [
        (currency, round(sum(s) / len(s), 3), len(s))
        for currency, s in scores.items() if s
    ]
    result.sort(key=lambda x: x[2], reverse=True)
    return result


# Bobot kontribusi tiap berita ke skor fundamental berdasar level dampaknya —
# berita Tinggi (rilis data/keputusan bank sentral) jauh lebih berarti utk
# arah pasar drpd berita Rendah (latar belakang), jadi tidak boleh ditimbang
# sama rata seperti detect_currency_impact() di atas.
_IMPACT_WEIGHT = {"high": 3.0, "medium": 1.5, "low": 1.0}


def detect_currency_impact_weighted(items: list[NewsItem]) -> dict[str, dict]:
    """Skor sentimen per mata uang, ditimbang bobot dampak berita (dipakai
    khusus utk fundamental di tab Rekomendasi — bukan tab Sentimen)."""
    buckets: dict[str, list[tuple[float, float, str]]] = {c: [] for c in CURRENCY_KEYWORDS}
    for item in items:
        text = f"{item.title} {item.summary}".lower()
        w = _IMPACT_WEIGHT.get(item.impact, 1.0)
        for currency, keywords in CURRENCY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                buckets[currency].append((item.sentiment_score, w, item.impact))
    out: dict[str, dict] = {}
    for currency, rows in buckets.items():
        if not rows:
            continue
        total_w = sum(w for _, w, _ in rows)
        weighted_avg = sum(s * w for s, w, _ in rows) / total_w
        out[currency] = {
            "score":            round(weighted_avg, 3),
            "count":            len(rows),
            "weight":           round(total_w, 2),
            "high_impact_count": sum(1 for _, _, imp in rows if imp == "high"),
        }
    return out


def _is_geopolitical(item: NewsItem) -> bool:
    text = f"{item.title} {item.summary}".lower()
    return any(kw in text for kw in GEOPOLITIK_KEYWORDS)


# ─── AGREGATOR ───────────────────────────────────────────────────────────────

def collect_all_news() -> list[NewsItem]:
    log.info("Mengumpulkan berita forex dari semua sumber...")
    all_items: list[NewsItem] = []
    fetchers = [
        fetch_forexlive,            # ForexLive — khusus forex
        fetch_fxstreet,             # FXStreet — analisis forex
        fetch_dailyfx,              # DailyFX — berita bank sentral & forex
        fetch_forexfactory,         # ForexFactory — komunitas forex
        fetch_financialjuice,       # FinancialJuice — headline forex
        fetch_investing,            # Investing.com — data makro & forex
        fetch_reuters_currencies,   # Reuters Markets/Currencies
        fetch_bloomberg_currencies, # Bloomberg Markets
        fetch_gnews_forex,              # Google News — forex umum
        fetch_gnews_geopolitik,         # Google News — geopolitik forex (khusus)
        fetch_geopolitik_news_sources,  # BBC · Al Jazeera · AP · MarketWatch · CNBC
    ]
    for fetcher in fetchers:
        try:
            all_items.extend(fetcher())
        except Exception as e:
            log.error(f"{fetcher.__name__} error tidak tertangani: {e}")

    log.info(f"Total dikumpulkan: {len(all_items)} berita (sebelum filter)")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=NEWS_HOURS_BACK)
    recent = []
    for item in all_items:
        if item.published is None:
            recent.append(item)
        else:
            pub = item.published if item.published.tzinfo else item.published.replace(tzinfo=timezone.utc)
            if pub >= cutoff:
                recent.append(item)

    # Filter hanya berita yang relevan dengan forex
    forex_relevant = [i for i in recent if _is_forex_relevant(i)]
    log.info(f"Setelah filter forex: {len(forex_relevant)} dari {len(recent)} berita")

    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in forex_relevant:
        key = re.sub(r"[^a-z0-9]", "", item.title.lower())[:60]
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    result = [_analyze(i) for i in unique]
    n_geo = sum(1 for i in result if _is_geopolitical(i))
    log.info(f"Total unik setelah filter: {len(result)} berita ({n_geo} geopolitik)")
    return result


# ─── PEMBANTU HTML ────────────────────────────────────────────────────────────

_COLOR = {
    "Bullish": {"bg": "#0d3320", "border": "#22c55e", "badge_bg": "#16a34a", "badge_fg": "#fff"},
    "Bearish": {"bg": "#3b0d0d", "border": "#ef4444", "badge_bg": "#dc2626", "badge_fg": "#fff"},
    "Netral":  {"bg": "#1e1e2e", "border": "#6b7280", "badge_bg": "#374151", "badge_fg": "#d1d5db"},
}


def _pub_str(item: NewsItem) -> str:
    if not item.published:
        return ""
    pub = item.published if item.published.tzinfo else item.published.replace(tzinfo=timezone.utc)
    return (pub + timedelta(hours=7)).strftime("%d %b %Y %H:%M WIB")


def _news_card(item: NewsItem, show_score: bool = False) -> str:
    c = _COLOR.get(item.sentiment_label, _COLOR["Netral"])
    pub = _pub_str(item)
    summary_html = (
        f'<p style="margin:6px 0 0;color:#9ca3af;font-size:13px;line-height:1.5;">'
        f'{html_module.escape(item.summary[:300])}…</p>'
    ) if item.summary else ""
    score_html = (
        f'<span style="color:#6b7280;font-size:11px;margin-left:auto;">'
        f'skor: {item.sentiment_score:+.3f}</span>'
    ) if show_score else ""

    return f"""
    <div style="background:{c['bg']};border-left:4px solid {c['border']};
                border-radius:8px;padding:14px 16px;margin:10px 0;">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <span style="background:{c['badge_bg']};color:{c['badge_fg']};font-size:11px;
                     font-weight:700;padding:2px 8px;border-radius:12px;letter-spacing:.5px;">
          {item.sentiment_emoji} {item.sentiment_label.upper()}
        </span>
        <span style="color:#6b7280;font-size:12px;">{html_module.escape(item.source)}</span>
        {"<span style='color:#6b7280;font-size:12px;'>· " + pub + "</span>" if pub else ""}
        {score_html}
      </div>
      <a href="{html_module.escape(item.url)}"
         style="color:#e2e8f0;font-size:15px;font-weight:600;text-decoration:none;
                display:block;margin-top:8px;line-height:1.4;">
        {html_module.escape(item.title)}
      </a>
      {summary_html}
    </div>"""


def _email_wrapper(
    title: str, icon: str, subtitle: str, body: str,
    sources_line: str = "ForexLive · FXStreet · DailyFX · ForexFactory · FinancialJuice · Investing.com · Reuters · Bloomberg",
) -> str:
    now_wib = datetime.now(tz=timezone.utc) + timedelta(hours=7)
    date_str = now_wib.strftime("%A, %d %B %Y — %H:%M WIB")
    return f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html_module.escape(title)}</title>
</head>
<body style="margin:0;padding:0;background:#0f0f1a;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:680px;margin:0 auto;padding:24px 16px;">

  <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border-radius:12px;
              padding:24px;margin-bottom:20px;text-align:center;">
    <div style="font-size:28px;margin-bottom:8px;">{icon}</div>
    <h1 style="color:#f1f5f9;margin:0 0 4px;font-size:20px;font-weight:700;">
      {html_module.escape(title)}
    </h1>
    <p style="color:#94a3b8;margin:0 0 4px;font-size:13px;">{html_module.escape(subtitle)}</p>
    <p style="color:#6b7280;margin:0;font-size:12px;">{date_str}</p>
  </div>

  {body}

  <div style="margin-top:32px;padding-top:16px;border-top:1px solid #1e2030;
              text-align:center;color:#4b5563;font-size:11px;">
    <p style="margin:0;">
      Dikirim otomatis setiap 07:00 WIB &nbsp;·&nbsp;
      Sumber: {html_module.escape(sources_line)}
    </p>
    <p style="margin:4px 0 0;">Analisis sentimen: VADER + Forex Keyword Booster</p>
  </div>

</div>
</body>
</html>"""


# ─── EMAIL 1: KALENDER EKONOMI FOREX ─────────────────────────────────────────

def build_email_kalender(events: list[EconomicEvent]) -> str:
    # ── Ringkasan dampak ──
    count_high   = sum(1 for e in events if e.impact == "high")
    count_medium = sum(1 for e in events if e.impact == "medium")
    count_low    = sum(1 for e in events if e.impact == "low")

    stats_bar = f"""
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px;">
      <div style="background:#2d0a0a;border-left:3px solid #ef4444;border-radius:6px;
                  padding:10px 14px;min-width:90px;text-align:center;">
        <div style="font-size:22px;font-weight:700;color:#ef4444;">{count_high}</div>
        <div style="font-size:11px;color:#9ca3af;margin-top:2px;">Dampak Tinggi</div>
      </div>
      <div style="background:#2d1505;border-left:3px solid #f97316;border-radius:6px;
                  padding:10px 14px;min-width:90px;text-align:center;">
        <div style="font-size:22px;font-weight:700;color:#f97316;">{count_medium}</div>
        <div style="font-size:11px;color:#9ca3af;margin-top:2px;">Dampak Sedang</div>
      </div>
      <div style="background:#2a2200;border-left:3px solid #eab308;border-radius:6px;
                  padding:10px 14px;min-width:90px;text-align:center;">
        <div style="font-size:22px;font-weight:700;color:#eab308;">{count_low}</div>
        <div style="font-size:11px;color:#9ca3af;margin-top:2px;">Dampak Rendah</div>
      </div>
      <div style="background:#1e2030;border-left:3px solid #374151;border-radius:6px;
                  padding:10px 14px;min-width:90px;text-align:center;">
        <div style="font-size:22px;font-weight:700;color:#f1f5f9;">{len(events)}</div>
        <div style="font-size:11px;color:#9ca3af;margin-top:2px;">Total Event</div>
      </div>
    </div>"""

    legend = """
    <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:center;
                background:#1e2030;border-radius:8px;padding:10px 16px;margin-bottom:20px;">
      <span style="color:#6b7280;font-size:12px;font-weight:600;">Keterangan Dampak:</span>
      <span style="display:inline-flex;align-items:center;gap:5px;color:#ef4444;font-size:12px;">
        <span style="display:inline-block;width:10px;height:10px;background:#ef4444;
                     border-radius:50%;"></span>Tinggi
      </span>
      <span style="display:inline-flex;align-items:center;gap:5px;color:#f97316;font-size:12px;">
        <span style="display:inline-block;width:10px;height:10px;background:#f97316;
                     border-radius:50%;"></span>Sedang
      </span>
      <span style="display:inline-flex;align-items:center;gap:5px;color:#eab308;font-size:12px;">
        <span style="display:inline-block;width:10px;height:10px;background:#eab308;
                     border-radius:50%;"></span>Rendah
      </span>
      <span style="display:inline-flex;align-items:center;gap:5px;color:#6b7280;font-size:12px;">
        <span style="display:inline-block;width:10px;height:10px;background:#6b7280;
                     border-radius:50%;"></span>Tidak Ada
      </span>
    </div>"""

    # ── Kelompokkan per hari (urutan kemunculan dipertahankan) ──
    days: dict[str, list[EconomicEvent]] = {}
    for ev in events:
        days.setdefault(ev.day_id, []).append(ev)

    def _time_sort_key(e: EconomicEvent) -> str:
        return "00:00" if e.time_wib in ("Sepanjang Hari", "", "—") else e.time_wib

    tables_html = ""
    for day_id, day_events in days.items():
        date_str = day_events[0].date_str if day_events else ""
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            date_disp = d.strftime("%d %B %Y")
            for en, id_ in _BULAN_ID.items():
                date_disp = date_disp.replace(en, id_)
        except Exception:
            date_disp = date_str

        rows_html = ""
        for ev in sorted(day_events, key=_time_sort_key):
            cfg = _IMPACT_CFG.get(ev.impact, _IMPACT_CFG["none"])
            dot = (
                f'<span style="display:inline-block;width:11px;height:11px;'
                f'border-radius:50%;background:{cfg["dot_color"]};" '
                f'title="{cfg["label"]}"></span>'
            )

            actual_style = "color:#f1f5f9;"
            if ev.actual and ev.forecast:
                try:
                    def _num(s: str) -> float:
                        s = re.sub(r"[^\d.\-]", "",
                                   s.replace("K", "e3").replace("M", "e6").replace("B", "e9"))
                        return float(s)
                    actual_style = (
                        "color:#22c55e;font-weight:700;"
                        if _num(ev.actual) >= _num(ev.forecast)
                        else "color:#ef4444;font-weight:700;"
                    )
                except Exception:
                    pass

            def _cell(val: str, extra_style: str = "color:#94a3b8;") -> str:
                if val:
                    return html_module.escape(val)
                return f'<span style="color:#374151;">—</span>'

            rows_html += f"""
            <tr style="border-top:1px solid #1e2030;">
              <td style="padding:9px 10px;color:#94a3b8;font-size:12px;
                         white-space:nowrap;font-family:monospace;">
                {html_module.escape(ev.time_wib)}
              </td>
              <td style="padding:9px 10px;text-align:center;">
                <span style="background:#1a2035;border:1px solid #2d3748;color:#e2e8f0;
                             font-size:11px;font-weight:700;padding:2px 7px;
                             border-radius:4px;letter-spacing:.5px;">
                  {html_module.escape(ev.currency) if ev.currency else "—"}
                </span>
              </td>
              <td style="padding:9px 10px;text-align:center;">{dot}</td>
              <td style="padding:9px 10px;color:#e2e8f0;font-size:13px;line-height:1.4;">
                {html_module.escape(ev.event_name)}
              </td>
              <td style="padding:9px 10px;{actual_style}font-size:13px;text-align:center;">
                {_cell(ev.actual)}
              </td>
              <td style="padding:9px 10px;color:#94a3b8;font-size:13px;text-align:center;">
                {_cell(ev.forecast)}
              </td>
              <td style="padding:9px 10px;color:#6b7280;font-size:13px;text-align:center;">
                {_cell(ev.previous)}
              </td>
            </tr>"""

        tables_html += f"""
        <div style="margin-bottom:28px;">
          <div style="background:linear-gradient(90deg,#1a2035 0%,#1e2030 100%);
                      border-radius:8px 8px 0 0;padding:11px 15px;
                      border-left:4px solid #3b82f6;
                      display:flex;align-items:center;justify-content:space-between;">
            <div>
              <span style="color:#f1f5f9;font-weight:700;font-size:14px;">{day_id}</span>
              <span style="color:#6b7280;font-size:12px;margin-left:10px;">{date_disp}</span>
            </div>
            <span style="color:#6b7280;font-size:12px;">{len(day_events)} event</span>
          </div>
          <table style="width:100%;border-collapse:collapse;background:#0f0f1a;">
            <thead>
              <tr style="background:#161625;">
                <th style="padding:8px 10px;color:#6b7280;font-size:11px;
                           text-align:left;letter-spacing:.5px;white-space:nowrap;">
                  WAKTU (WIB)
                </th>
                <th style="padding:8px 10px;color:#6b7280;font-size:11px;
                           text-align:center;letter-spacing:.5px;">
                  MATA UANG
                </th>
                <th style="padding:8px 10px;color:#6b7280;font-size:11px;
                           text-align:center;letter-spacing:.5px;">
                  DAMPAK
                </th>
                <th style="padding:8px 10px;color:#6b7280;font-size:11px;
                           text-align:left;letter-spacing:.5px;">
                  NAMA EVENT
                </th>
                <th style="padding:8px 10px;color:#6b7280;font-size:11px;
                           text-align:center;letter-spacing:.5px;">
                  AKTUAL
                </th>
                <th style="padding:8px 10px;color:#6b7280;font-size:11px;
                           text-align:center;letter-spacing:.5px;">
                  PERKIRAAN
                </th>
                <th style="padding:8px 10px;color:#6b7280;font-size:11px;
                           text-align:center;letter-spacing:.5px;">
                  SEBELUMNYA
                </th>
              </tr>
            </thead>
            <tbody>{rows_html}
            </tbody>
          </table>
        </div>"""

    if not tables_html:
        tables_html = """
        <div style="background:#1e2030;border-radius:10px;padding:40px;text-align:center;">
          <div style="font-size:48px;margin-bottom:14px;">📅</div>
          <div style="color:#94a3b8;font-size:15px;font-weight:600;margin-bottom:8px;">
            Data Kalender Ekonomi Tidak Tersedia
          </div>
          <div style="color:#6b7280;font-size:13px;">
            ForexFactory mungkin sedang tidak dapat diakses atau
            struktur halaman telah berubah. Coba jalankan ulang nanti.
          </div>
        </div>"""

    return _email_wrapper(
        title="Kalender Ekonomi Forex Minggu Ini",
        icon="📅",
        subtitle="Jadwal rilis data ekonomi global · Waktu dalam WIB (UTC+7) · Aktual vs Perkiraan",
        body=stats_bar + legend + tables_html,
        sources_line="ForexFactory Economic Calendar · forexfactory.com",
    )


# ─── EMAIL 2: ANALISIS SENTIMEN LENGKAP ──────────────────────────────────────

def _build_recommendation(avg_score: float, currency_impacts: list[tuple[str, float, int]]) -> str:
    if avg_score >= 0.20:
        kondisi, warna, ikon = "SANGAT BULLISH", "#22c55e", "🚀"
        rekomen = (
            "Sentimen pasar sangat positif. Pertimbangkan posisi <strong>BUY</strong> pada "
            "pasangan mata uang berisiko (AUD/JPY, NZD/JPY). USD cenderung melemah jika "
            "risk appetite tinggi."
        )
    elif avg_score >= 0.05:
        kondisi, warna, ikon = "BULLISH", "#22c55e", "📈"
        rekomen = (
            "Sentimen pasar positif namun tidak ekstrem. Fokus pada konfirmasi teknikal "
            "sebelum membuka posisi <strong>BUY</strong>. Waspadai berita berkebalikan "
            "yang bisa membalikkan arah."
        )
    elif avg_score <= -0.20:
        kondisi, warna, ikon = "SANGAT BEARISH", "#ef4444", "📉"
        rekomen = (
            "Sentimen pasar sangat negatif. Pertimbangkan posisi <strong>SELL</strong> "
            "pada pasangan berisiko. JPY dan CHF biasanya menguat sebagai safe-haven "
            "dalam kondisi ini."
        )
    elif avg_score <= -0.05:
        kondisi, warna, ikon = "BEARISH", "#ef4444", "⚠️"
        rekomen = (
            "Sentimen pasar negatif. Berhati-hatilah membuka posisi <strong>BUY</strong>. "
            "Prioritaskan manajemen risiko dan pertimbangkan <strong>SELL</strong> "
            "dengan konfirmasi teknikal."
        )
    else:
        kondisi, warna, ikon = "NETRAL", "#6b7280", "⚖️"
        rekomen = (
            "Pasar dalam kondisi netral dan tidak ada arah yang jelas. "
            "Tunggu katalis fundamental atau breakout teknikal sebelum membuka posisi."
        )

    top_bullish = [(c, s) for c, s, _ in currency_impacts if s >= 0.05][:3]
    top_bearish = [(c, s) for c, s, _ in currency_impacts if s <= -0.05][:3]
    currency_info = ""
    if top_bullish:
        pairs = ", ".join(f"<strong>{c}</strong>" for c, _ in top_bullish)
        currency_info += f"<br><span style='color:#22c55e;'>▲ Cenderung Menguat:</span> {pairs}"
    if top_bearish:
        pairs = ", ".join(f"<strong>{c}</strong>" for c, _ in top_bearish)
        currency_info += f"<br><span style='color:#ef4444;'>▼ Cenderung Melemah:</span> {pairs}"

    return f"""
    <div style="background:#1a2035;border:1px solid {warna};border-radius:10px;
                padding:16px 20px;margin:16px 0;">
      <div style="font-size:15px;font-weight:700;color:{warna};margin-bottom:8px;">
        {ikon} Rekomendasi Arah Pasar Hari Ini: {kondisi}
      </div>
      <p style="margin:0;color:#d1d5db;font-size:13px;line-height:1.7;">
        {rekomen}{currency_info}
      </p>
      <p style="margin:10px 0 0;color:#6b7280;font-size:11px;">
        ⚠️ Bukan saran investasi. Selalu gunakan manajemen risiko yang tepat.
      </p>
    </div>"""


def build_email_sentimen(items: list[NewsItem]) -> str:
    if not items:
        return _email_wrapper(
            "Analisis Sentimen Pasar Forex", "📊",
            "Tidak ada data", "<p style='color:#6b7280;'>Tidak ada berita hari ini.</p>",
        )

    bullish = [i for i in items if i.sentiment_label == "Bullish"]
    bearish = [i for i in items if i.sentiment_label == "Bearish"]
    netral  = [i for i in items if i.sentiment_label == "Netral"]
    total   = len(items)
    avg_score = sum(i.sentiment_score for i in items) / total

    if avg_score >= 0.05:
        overall_emoji, overall_label, overall_color = "🟢", "BULLISH", "#22c55e"
    elif avg_score <= -0.05:
        overall_emoji, overall_label, overall_color = "🔴", "BEARISH", "#ef4444"
    else:
        overall_emoji, overall_label, overall_color = "⚪", "NETRAL", "#6b7280"

    pct_bullish = len(bullish) / total * 100
    pct_bearish = len(bearish) / total * 100
    pct_netral  = 100 - pct_bullish - pct_bearish
    if pct_bullish >= 60:
        tren_txt, tren_color = "↗ Tren Menguat (Bullish Dominan)", "#22c55e"
    elif pct_bearish >= 60:
        tren_txt, tren_color = "↘ Tren Melemah (Bearish Dominan)", "#ef4444"
    else:
        tren_txt, tren_color = "↔ Tren Campuran (Mixed Sentiment)", "#94a3b8"

    currency_impacts = detect_currency_impact(items)

    # ── Statistik ──
    stats = f"""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">
      <div style="background:#1e2030;border-radius:8px;padding:14px;text-align:center;">
        <div style="font-size:22px;font-weight:700;color:#f1f5f9;">{total}</div>
        <div style="font-size:11px;color:#6b7280;margin-top:2px;">Total Berita</div>
      </div>
      <div style="background:#0d3320;border-radius:8px;padding:14px;text-align:center;">
        <div style="font-size:22px;font-weight:700;color:#22c55e;">{len(bullish)}</div>
        <div style="font-size:11px;color:#6b7280;margin-top:2px;">Bullish</div>
      </div>
      <div style="background:#3b0d0d;border-radius:8px;padding:14px;text-align:center;">
        <div style="font-size:22px;font-weight:700;color:#ef4444;">{len(bearish)}</div>
        <div style="font-size:11px;color:#6b7280;margin-top:2px;">Bearish</div>
      </div>
      <div style="background:#1e1e2e;border-radius:8px;padding:14px;text-align:center;">
        <div style="font-size:22px;font-weight:700;color:#94a3b8;">{len(netral)}</div>
        <div style="font-size:11px;color:#6b7280;margin-top:2px;">Netral</div>
      </div>
    </div>"""

    # ── Sentimen Keseluruhan ──
    overall_box = f"""
    <div style="background:#1e2030;border-radius:10px;padding:16px 20px;margin-bottom:16px;">
      <div style="display:flex;align-items:center;justify-content:space-between;
                  flex-wrap:wrap;gap:8px;">
        <div>
          <div style="color:#94a3b8;font-size:12px;margin-bottom:4px;">
            Sentimen Keseluruhan Pasar
          </div>
          <div style="font-size:24px;font-weight:700;color:{overall_color};">
            {overall_emoji} {overall_label}
          </div>
          <div style="color:#6b7280;font-size:12px;margin-top:4px;">
            Skor rata-rata: <strong style="color:{overall_color};">{avg_score:+.4f}</strong>
          </div>
        </div>
        <div style="text-align:right;">
          <div style="color:{tren_color};font-size:13px;font-weight:600;">{tren_txt}</div>
          <div style="color:#6b7280;font-size:11px;margin-top:6px;">
            {pct_bullish:.0f}% Bullish &nbsp;·&nbsp;
            {pct_bearish:.0f}% Bearish &nbsp;·&nbsp;
            {pct_netral:.0f}% Netral
          </div>
        </div>
      </div>
      <!-- Bar proporsi sentimen -->
      <div style="margin-top:12px;background:#0f0f1a;border-radius:4px;height:8px;
                  overflow:hidden;display:flex;">
        <div style="background:#22c55e;width:{pct_bullish:.0f}%;"></div>
        <div style="background:#6b7280;width:{pct_netral:.0f}%;"></div>
        <div style="background:#ef4444;width:{pct_bearish:.0f}%;"></div>
      </div>
    </div>"""

    # ── Tabel Dampak Mata Uang ──
    currency_rows = ""
    for currency, avg, count in currency_impacts[:9]:
        if avg >= 0.05:
            c_color, c_label, c_arrow = "#22c55e", "Bullish", "▲"
        elif avg <= -0.05:
            c_color, c_label, c_arrow = "#ef4444", "Bearish", "▼"
        else:
            c_color, c_label, c_arrow = "#6b7280", "Netral", "→"
        bar_pct = int((avg + 1) / 2 * 100)
        currency_rows += f"""
        <tr style="border-top:1px solid #1e2030;">
          <td style="padding:8px 12px;color:#f1f5f9;font-weight:700;">{currency}</td>
          <td style="padding:8px 12px;color:{c_color};font-weight:600;">
            {c_arrow} {c_label}
          </td>
          <td style="padding:8px 12px;color:#6b7280;font-size:12px;">{count}×</td>
          <td style="padding:8px 12px;color:{c_color};font-size:13px;">{avg:+.3f}</td>
          <td style="padding:8px 12px;">
            <div style="background:#0f0f1a;border-radius:4px;height:8px;
                        width:100px;overflow:hidden;">
              <div style="background:{c_color};height:100%;width:{bar_pct}%;"></div>
            </div>
          </td>
        </tr>"""

    currency_table = f"""
    <div style="background:#1e2030;border-radius:10px;margin:16px 0;overflow:hidden;">
      <div style="padding:12px 16px;border-bottom:1px solid #374151;">
        <span style="color:#94a3b8;font-size:13px;font-weight:600;">
          💱 Dampak Sentimen per Mata Uang
        </span>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="background:#161625;">
            <th style="padding:8px 12px;color:#6b7280;font-size:11px;text-align:left;">MATA UANG</th>
            <th style="padding:8px 12px;color:#6b7280;font-size:11px;text-align:left;">ARAH</th>
            <th style="padding:8px 12px;color:#6b7280;font-size:11px;text-align:left;">SEBUTAN</th>
            <th style="padding:8px 12px;color:#6b7280;font-size:11px;text-align:left;">SKOR</th>
            <th style="padding:8px 12px;color:#6b7280;font-size:11px;text-align:left;">INDIKATOR</th>
          </tr>
        </thead>
        <tbody>{currency_rows}</tbody>
      </table>
    </div>""" if currency_rows else ""

    # ── Rekomendasi ──
    rekomen_box = _build_recommendation(avg_score, currency_impacts)

    # ── Berita per Sentimen dengan skor individual ──
    def _section(title_html: str, section_items: list[NewsItem], limit: int = 15) -> str:
        if not section_items:
            return ""
        cards = "".join(_news_card(i, show_score=True) for i in section_items[:limit])
        return f"""
        <h2 style="color:#e2e8f0;font-size:15px;margin:24px 0 6px;
                   border-bottom:1px solid #374151;padding-bottom:6px;">
          {title_html}
        </h2>{cards}"""

    # Urutkan berita per sentimen dari skor tertinggi
    bullish_sorted = sorted(bullish, key=lambda i: i.sentiment_score, reverse=True)
    bearish_sorted = sorted(bearish, key=lambda i: i.sentiment_score)
    netral_sorted  = sorted(netral,  key=lambda i: i.sentiment_score, reverse=True)

    news_sections = (
        _section(f"🟢 Berita Bullish ({len(bullish)}) — Skor Tertinggi ke Terendah", bullish_sorted) +
        _section(f"🔴 Berita Bearish ({len(bearish)}) — Skor Terendah ke Tertinggi", bearish_sorted) +
        _section(f"⚪ Berita Netral ({len(netral)})", netral_sorted, limit=10)
    )

    body = stats + overall_box + currency_table + rekomen_box + news_sections

    return _email_wrapper(
        title="Analisis Sentimen Pasar Forex",
        icon="📊",
        subtitle="Skor sentimen per berita · Dampak mata uang · Rekomendasi arah pasar",
        body=body,
    )


# ─── EMAIL 3: GEOPOLITIK PENTING ─────────────────────────────────────────────

def _geo_pairs_for_item(item: NewsItem) -> list[str]:
    text = f"{item.title} {item.summary}".lower()
    pairs: set[str] = set()
    for kw, pair_list in _GEO_PAIR_IMPACT.items():
        if kw in text:
            pairs.update(pair_list)
    return sorted(pairs)[:5]


def _geo_risk_level(geo_items: list[NewsItem]) -> tuple[str, str, str]:
    if not geo_items:
        return "RENDAH", "#22c55e", "🟢"
    avg = sum(i.sentiment_score for i in geo_items) / len(geo_items)
    count = len(geo_items)
    if avg <= -0.15 or count >= 10:
        return "TINGGI", "#ef4444", "🔴"
    elif avg <= -0.05 or count >= 5:
        return "SEDANG", "#f59e0b", "🟡"
    return "RENDAH", "#22c55e", "🟢"


def _geo_card(item: NewsItem) -> str:
    c = _COLOR.get(item.sentiment_label, _COLOR["Netral"])
    pub = _pub_str(item)
    pairs = _geo_pairs_for_item(item)
    pair_badges = "".join(
        f'<span style="background:#1e2030;border:1px solid #374151;color:#94a3b8;'
        f'font-size:10px;padding:1px 6px;border-radius:10px;margin-right:4px;">{p}</span>'
        for p in pairs
    )
    summary_html = (
        f'<p style="margin:6px 0 0;color:#9ca3af;font-size:13px;line-height:1.5;">'
        f'{html_module.escape(item.summary[:300])}…</p>'
    ) if item.summary else ""

    return f"""
    <div style="background:{c['bg']};border-left:4px solid {c['border']};
                border-radius:8px;padding:14px 16px;margin:10px 0;">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <span style="background:{c['badge_bg']};color:{c['badge_fg']};font-size:11px;
                     font-weight:700;padding:2px 8px;border-radius:12px;">
          {item.sentiment_emoji} {item.sentiment_label.upper()}
        </span>
        <span style="color:#6b7280;font-size:12px;">{html_module.escape(item.source)}</span>
        {"<span style='color:#6b7280;font-size:12px;'>· " + pub + "</span>" if pub else ""}
        <span style="color:#6b7280;font-size:11px;margin-left:auto;">
          skor: {item.sentiment_score:+.3f}
        </span>
      </div>
      <a href="{html_module.escape(item.url)}"
         style="color:#e2e8f0;font-size:15px;font-weight:600;text-decoration:none;
                display:block;margin-top:8px;line-height:1.4;">
        {html_module.escape(item.title)}
      </a>
      {summary_html}
      {('<div style="margin-top:8px;">' + pair_badges + '</div>') if pairs else ""}
    </div>"""


def build_email_geopolitik(items: list[NewsItem]) -> str:
    geo_items = [i for i in items if _is_geopolitical(i)]
    risk_level, risk_color, risk_emoji = _geo_risk_level(geo_items)

    if not geo_items:
        body = f"""
        <div style="background:#1e2030;border-radius:10px;padding:32px;text-align:center;">
          <div style="font-size:40px;margin-bottom:12px;">✅</div>
          <div style="font-size:16px;color:#94a3b8;font-weight:600;">
            Tidak ada peristiwa geopolitik signifikan hari ini.
          </div>
          <div style="font-size:13px;color:#6b7280;margin-top:8px;">
            Kondisi geopolitik global relatif tenang — risiko pasar dari faktor eksternal rendah.
          </div>
        </div>"""
        return _email_wrapper(
            title="Geopolitik Penting — Pasar Forex",
            icon="🌍",
            subtitle="Pemantauan risiko geopolitik yang mempengaruhi pasar valuta asing",
            body=body,
        )

    bullish_geo = [i for i in geo_items if i.sentiment_label == "Bullish"]
    bearish_geo = [i for i in geo_items if i.sentiment_label == "Bearish"]
    netral_geo  = [i for i in geo_items if i.sentiment_label == "Netral"]
    avg_geo = sum(i.sentiment_score for i in geo_items) / len(geo_items)

    # ── Kotak Tingkat Risiko ──
    risk_box = f"""
    <div style="background:#1e2030;border:2px solid {risk_color};border-radius:10px;
                padding:16px 20px;margin-bottom:16px;">
      <div style="display:flex;align-items:center;justify-content:space-between;
                  flex-wrap:wrap;gap:8px;">
        <div>
          <div style="color:#94a3b8;font-size:12px;">Tingkat Risiko Geopolitik Hari Ini</div>
          <div style="font-size:26px;font-weight:700;color:{risk_color};margin-top:4px;">
            {risk_emoji} {risk_level}
          </div>
        </div>
        <div style="text-align:right;">
          <div style="color:#f1f5f9;font-size:20px;font-weight:700;">
            {len(geo_items)} Peristiwa
          </div>
          <div style="color:#6b7280;font-size:12px;margin-top:2px;">
            {len(bullish_geo)} positif · {len(bearish_geo)} negatif · {len(netral_geo)} netral
          </div>
          <div style="color:#6b7280;font-size:11px;margin-top:2px;">
            Skor rata-rata: <strong style="color:{risk_color};">{avg_geo:+.3f}</strong>
          </div>
        </div>
      </div>
    </div>"""

    # ── Tabel Pasangan Forex yang Terpengaruh ──
    pair_counter: dict[str, list[float]] = {}
    for item in geo_items:
        for pair in _geo_pairs_for_item(item):
            pair_counter.setdefault(pair, []).append(item.sentiment_score)

    pair_rows = ""
    for pair, scores in sorted(pair_counter.items(), key=lambda x: -len(x[1]))[:8]:
        avg_pair = sum(scores) / len(scores)
        if avg_pair >= 0.05:
            p_color, p_label = "#22c55e", "Tekanan Naik ▲"
        elif avg_pair <= -0.05:
            p_color, p_label = "#ef4444", "Tekanan Turun ▼"
        else:
            p_color, p_label = "#6b7280", "Netral →"
        pair_rows += f"""
        <tr style="border-top:1px solid #1e2030;">
          <td style="padding:8px 12px;color:#f1f5f9;font-weight:700;">{pair}</td>
          <td style="padding:8px 12px;color:{p_color};font-weight:600;">{p_label}</td>
          <td style="padding:8px 12px;color:#6b7280;font-size:12px;">{len(scores)} kejadian</td>
          <td style="padding:8px 12px;color:{p_color};">{avg_pair:+.3f}</td>
        </tr>"""

    pair_table = f"""
    <div style="background:#1e2030;border-radius:10px;margin:16px 0;overflow:hidden;">
      <div style="padding:12px 16px;border-bottom:1px solid #374151;">
        <span style="color:#94a3b8;font-size:13px;font-weight:600;">
          📌 Pasangan Forex yang Terpengaruh
        </span>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="background:#161625;">
            <th style="padding:8px 12px;color:#6b7280;font-size:11px;text-align:left;">PASANGAN</th>
            <th style="padding:8px 12px;color:#6b7280;font-size:11px;text-align:left;">ARAH</th>
            <th style="padding:8px 12px;color:#6b7280;font-size:11px;text-align:left;">FREKUENSI</th>
            <th style="padding:8px 12px;color:#6b7280;font-size:11px;text-align:left;">SKOR</th>
          </tr>
        </thead>
        <tbody>{pair_rows}</tbody>
      </table>
    </div>""" if pair_rows else ""

    # ── Kartu Berita ──
    def _geo_section(title_html: str, section_items: list[NewsItem], limit: int = 15) -> str:
        if not section_items:
            return ""
        cards = "".join(_geo_card(i) for i in section_items[:limit])
        return f"""
        <h2 style="color:#e2e8f0;font-size:15px;margin:24px 0 6px;
                   border-bottom:1px solid #374151;padding-bottom:6px;">
          {title_html}
        </h2>{cards}"""

    news_sections = (
        _geo_section(f"🔴 Peristiwa Negatif/Bearish ({len(bearish_geo)})", bearish_geo) +
        _geo_section(f"🟢 Peristiwa Positif/Bullish ({len(bullish_geo)})", bullish_geo) +
        _geo_section(f"⚪ Peristiwa Netral ({len(netral_geo)})", netral_geo)
    )

    body = risk_box + pair_table + news_sections

    return _email_wrapper(
        title="Geopolitik Penting — Pasar Forex",
        icon="🌍",
        subtitle="Pemantauan risiko geopolitik yang mempengaruhi pasar valuta asing",
        body=body,
    )


# ─── PENGIRIM EMAIL ───────────────────────────────────────────────────────────

def send_one_email(subject: str, html_body: str, email_num: int) -> bool:
    if not GMAIL_USER or not GMAIL_PASSWORD:
        log.error("GMAIL_USER / GMAIL_APP_PASSWORD belum diisi di file .env — email tidak dikirim.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Forex Digest <{GMAIL_USER}>"
    msg["To"]      = SEND_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_PASSWORD)
            smtp.sendmail(GMAIL_USER, SEND_TO, msg.as_string())
        log.info(f"[Email {email_num}/3] Terkirim → {SEND_TO}")
        log.info(f"[Email {email_num}/3] Subjek: {subject}")
        return True
    except smtplib.SMTPAuthenticationError:
        log.error(
            "Autentikasi Gmail gagal. Pastikan:\n"
            "  1. GMAIL_APP_PASSWORD adalah App Password (bukan password akun)\n"
            "  2. 2-Step Verification sudah aktif di akun Google Anda\n"
            "  3. Buat App Password di: https://myaccount.google.com/apppasswords"
        )
        return False
    except Exception as e:
        log.error(f"[Email {email_num}/3] Gagal kirim: {e}")
        return False


def send_all_emails(items: list[NewsItem], calendar_events: list[EconomicEvent]) -> None:
    now_wib   = datetime.now(tz=timezone.utc) + timedelta(hours=7)
    date_str  = now_wib.strftime("%d %b %Y")
    n_bullish = sum(1 for i in items if i.sentiment_label == "Bullish")
    n_bearish = sum(1 for i in items if i.sentiment_label == "Bearish")
    n_geo     = sum(1 for i in items if _is_geopolitical(i))
    n_cal     = len(calendar_events)

    emails = [
        (
            f"📅 [1/3] Kalender Ekonomi Forex — {date_str} ({n_cal} Event)",
            build_email_kalender(calendar_events),
        ),
        (
            f"📊 [2/3] Analisis Sentimen Forex — {date_str} | "
            f"{n_bullish}🟢 Bullish · {n_bearish}🔴 Bearish",
            build_email_sentimen(items),
        ),
        (
            f"🌍 [3/3] Geopolitik Penting Forex — {date_str} ({n_geo} Peristiwa)",
            build_email_geopolitik(items),
        ),
    ]

    log.info(f"Mengirim 3 email ke {SEND_TO}...")
    for idx, (subject, html_body) in enumerate(emails, start=1):
        success = send_one_email(subject, html_body, idx)
        if not success:
            log.warning(f"Email {idx}/3 gagal dikirim, melanjutkan ke berikutnya...")
        if idx < len(emails):
            time.sleep(3)  # jeda antar email agar tidak dianggap spam


# ─── TECHNICAL ANALYSIS ──────────────────────────────────────────────────────

def fetch_forex_technicals() -> dict:
    """Ambil OHLC 1H dari Yahoo Finance dan hitung cross SMMA7/EMA9 untuk 26 pair."""
    PAIRS = [
        ("USDJPY=X","USD/JPY"), ("USDCHF=X","USD/CHF"), ("USDCAD=X","USD/CAD"),
        ("NZDUSD=X","NZD/USD"), ("NZDJPY=X","NZD/JPY"), ("NZDCHF=X","NZD/CHF"),
        ("NZDCAD=X","NZD/CAD"), ("GBPUSD=X","GBP/USD"), ("GBPJPY=X","GBP/JPY"),
        ("GBPCHF=X","GBP/CHF"), ("GBPCAD=X","GBP/CAD"), ("GBPAUD=X","GBP/AUD"),
        ("EURUSD=X","EUR/USD"), ("EURJPY=X","EUR/JPY"), ("EURGBP=X","EUR/GBP"),
        ("EURCHF=X","EUR/CHF"), ("EURCAD=X","EUR/CAD"), ("EURAUD=X","EUR/AUD"),
        ("EURNZD=X","EUR/NZD"), ("AUDUSD=X","AUD/USD"), ("AUDJPY=X","AUD/JPY"),
        ("AUDNZD=X","AUD/NZD"), ("AUDCAD=X","AUD/CAD"), ("CADJPY=X","CAD/JPY"),
        ("CADCHF=X","CAD/CHF"), ("CHFJPY=X","CHF/JPY"),
    ]

    def calc_rsi(closes: list[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        ag, al = 0.0, 0.0
        for i in range(1, period + 1):
            d = closes[i] - closes[i - 1]
            if d > 0: ag += d
            else:     al -= d
        ag /= period; al /= period
        for i in range(period + 1, len(closes)):
            d = closes[i] - closes[i - 1]
            ag = (ag * (period - 1) + max(d, 0))  / period
            al = (al * (period - 1) + max(-d, 0)) / period
        return round(100 - (100 / (1 + ag / al)), 1) if al else 100.0

    def calc_smma(closes: list[float], period: int) -> list[float | None]:
        """Smoothed MA (Wilder-style) — sama pola smoothing dgn calc_rsi di atas."""
        if len(closes) < period:
            return [None] * len(closes)
        out: list[float | None] = [None] * (period - 1)
        prev = sum(closes[:period]) / period
        out.append(prev)
        for i in range(period, len(closes)):
            prev = (prev * (period - 1) + closes[i]) / period
            out.append(prev)
        return out

    def calc_ema(closes: list[float], period: int) -> list[float | None]:
        if len(closes) < period:
            return [None] * len(closes)
        out: list[float | None] = [None] * (period - 1)
        prev = sum(closes[:period]) / period
        out.append(prev)
        k = 2 / (period + 1)
        for i in range(period, len(closes)):
            prev = closes[i] * k + prev * (1 - k)
            out.append(prev)
        return out

    def calc_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14):
        n = len(closes)
        if n < period + 1:
            return None
        trs = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, n)
        ]
        atr = sum(trs[:period]) / period
        for i in range(period, len(trs)):
            atr = (atr * (period - 1) + trs[i]) / period
        return atr

    def fetch_pair(sym: str, label: str) -> dict | None:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1h&range=30d"
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            r.raise_for_status()
            q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]
            valid = [
                (o, h, l, c) for o, h, l, c in zip(q["open"], q["high"], q["low"], q["close"])
                if None not in (o, h, l, c)
            ]
            if len(valid) < 30:
                return None
            highs  = [v[1] for v in valid]
            lows   = [v[2] for v in valid]
            closes = [v[3] for v in valid]
            n      = len(closes)
            last   = closes[-1]

            smma7 = calc_smma(closes, 7)
            ema9  = calc_ema(closes, 9)
            start = max(6, 8)  # index awal di mana smma7 & ema9 sudah valid
            diffs = [ema9[i] - smma7[i] for i in range(start, n)]

            # Cari cross (pergantian tanda) paling baru di antara diffs
            cross_k = None
            for k in range(len(diffs) - 1, 0, -1):
                a, b = diffs[k], diffs[k - 1]
                if a == 0 or b == 0:
                    continue
                if (a > 0) != (b > 0):
                    cross_k = k
                    break
            bars_since_cross = (len(diffs) - 1 - cross_k) if cross_k is not None else 999

            last_diff = diffs[-1]
            direction = "BUY" if last_diff > 0 else "SELL" if last_diff < 0 else "WAIT"

            atr14 = calc_atr(highs, lows, closes, 14)
            rsi   = calc_rsi(closes, 14)

            freshness_score = max(0, round(50 - bars_since_cross * 5))
            separation_score = min(25, round(abs(last_diff) / atr14 * 25)) if atr14 else 0
            if direction == "BUY":
                rsi_score = round(max(0.0, rsi - 50) / 50 * 25)
            elif direction == "SELL":
                rsi_score = round(max(0.0, 50 - rsi) / 50 * 25)
            else:
                rsi_score = 0
            score = min(100, freshness_score + separation_score + rsi_score)

            if bars_since_cross == 0:
                cross_label = "Baru saja"
            elif bars_since_cross >= 999:
                cross_label = "Belum ada cross baru"
            else:
                cross_label = f"{bars_since_cross} candle lalu"

            dp  = 3 if "JPY" in sym else 5
            fmt = lambda v: f"{v:.{dp}f}" if v is not None else "—"
            return {
                "label": label, "score": score, "direction": direction,
                "rsi": rsi, "last_close": fmt(last),
                "smma7": fmt(smma7[-1]), "ema9": fmt(ema9[-1]),
                "atr14": fmt(atr14) if atr14 else "—",
                "bars_since_cross": bars_since_cross, "cross_label": cross_label,
                "freshness_score": freshness_score, "separation_score": separation_score,
                "rsi_score": rsi_score,
            }
        except Exception as e:
            log.warning(f"[TEKNIKAL] {label} gagal: {e}")
            return None

    results = []
    for sym, label in PAIRS:
        p = fetch_pair(sym, label)
        if p:
            results.append(p)
        time.sleep(0.5)
    results.sort(key=lambda x: x["score"], reverse=True)

    now_wib = datetime.now(tz=timezone.utc) + timedelta(hours=7)
    log.info(f"[TEKNIKAL] {len(results)}/{len(PAIRS)} pair berhasil diambil.")
    return {
        "generated": now_wib.strftime("%d %b %Y %H:%M WIB"),
        "pairs": results,
        "total": len(results),
    }


# ─── FUNDAMENTAL ENRICHMENT ──────────────────────────────────────────────────

def _enrich_fundamental(rekomendasi_data: dict, weighted_impact: dict[str, dict],
                         events: list[EconomicEvent]) -> None:
    """Tambahkan analisis fundamental ke setiap pair — versi "disaring lebih
    dalam": sentimen ditimbang bobot dampak berita (bukan rata-rata mentah),
    mensyaratkan bukti minimum sebelum berani klaim Bullish/Bearish, dan
    memberi peringatan kalau ada rilis data dampak Tinggi utk mata uang itu
    HARI INI (kalender ekonomi yang sudah difetch, tidak perlu request baru).
    """
    if not rekomendasi_data or not rekomendasi_data.get("pairs"):
        return

    today_str = (datetime.now(tz=timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")
    high_today: dict[str, list[dict]] = {}
    for e in events:
        if e.impact == "high" and e.date_str == today_str:
            high_today.setdefault(e.currency, []).append(
                {"event_name": e.event_name, "time_wib": e.time_wib}
            )

    MIN_COUNT, MIN_WEIGHT = 2, 3.0

    def currency_view(cur: str) -> dict:
        d = weighted_impact.get(cur)
        if not d or d["count"] < MIN_COUNT or d["weight"] < MIN_WEIGHT:
            score = d["score"] if d else 0.0
            return {"sentiment": "Netral", "score": score,
                    "count": d["count"] if d else 0, "insufficient": True,
                    "high_count": d["high_impact_count"] if d else 0}
        sentiment = "Bullish" if d["score"] >= 0.05 else "Bearish" if d["score"] <= -0.05 else "Netral"
        return {"sentiment": sentiment, "score": d["score"], "count": d["count"],
                "insufficient": False, "high_count": d["high_impact_count"]}

    for pair in rekomendasi_data["pairs"]:
        parts = pair["label"].split("/")
        if len(parts) != 2:
            continue
        base, quote = parts
        bv, qv = currency_view(base), currency_view(quote)
        fund_score = round(bv["score"] - qv["score"], 3)
        signal = "BUY" if fund_score > 0.10 else "SELL" if fund_score < -0.10 else "Netral"

        has_high = bv["high_count"] > 0 or qv["high_count"] > 0
        if abs(fund_score) > 0.20 and has_high:
            confidence = "Kuat"
        elif abs(fund_score) > 0.10:
            confidence = "Sedang"
        else:
            confidence = "Lemah"

        calendar_warning = [
            {"currency": cur, **ev}
            for cur in (base, quote) for ev in high_today.get(cur, [])
        ]

        pair["fundamental"] = {
            "signal":            signal,
            "fund_score":        fund_score,
            "confidence":        confidence,
            "base":              base,
            "quote":             quote,
            "base_sentiment":    bv["sentiment"],
            "quote_sentiment":   qv["sentiment"],
            "base_score":        round(bv["score"], 3),
            "quote_score":       round(qv["score"], 3),
            "base_count":        bv["count"],
            "quote_count":       qv["count"],
            "base_insufficient": bv["insufficient"],
            "quote_insufficient": qv["insufficient"],
            "calendar_warning":  calendar_warning,
        }


# ─── MAIN JOB ────────────────────────────────────────────────────────────────

def save_news_data(items: list[NewsItem], events: list[EconomicEvent],
                   fj_items: list[NewsItem] | None = None,
                   rekomendasi_data: dict | None = None) -> None:
    """Simpan data ke JSON + news_data.js agar bisa dibaca oleh HTML app."""
    now_wib   = datetime.now(tz=timezone.utc) + timedelta(hours=7)
    generated = now_wib.strftime("%d %b %Y %H:%M WIB")

    # ── helper: NewsItem → dict ──
    def item_to_dict(item: NewsItem) -> dict:
        pub_str = ""
        if item.published:
            pub = item.published if item.published.tzinfo else item.published.replace(tzinfo=timezone.utc)
            pub_str = (pub + timedelta(hours=7)).strftime("%d %b %Y %H:%M WIB")
        return {
            "source":    item.source,
            "title":     item.title,
            "url":       item.url,
            "summary":   item.summary[:300] if item.summary else "",
            "published": pub_str,
            "sentiment": item.sentiment_label,
            "score":     item.sentiment_score,
            "emoji":     item.sentiment_emoji,
            "impact":    item.impact,
        }

    # ── Kalender ──
    kalender_data = {
        "generated": generated,
        "events": [
            {
                "date": e.date_str, "day": e.day_id, "time_wib": e.time_wib,
                "currency": e.currency, "impact": e.impact, "event": e.event_name,
                "actual": e.actual, "forecast": e.forecast, "previous": e.previous,
            }
            for e in events
        ],
    }

    # ── Sentimen ──
    bullish = [i for i in items if i.sentiment_label == "Bullish"]
    bearish = [i for i in items if i.sentiment_label == "Bearish"]
    netral  = [i for i in items if i.sentiment_label == "Netral"]
    avg_score = round(sum(i.sentiment_score for i in items) / len(items), 4) if items else 0
    currency_impacts = detect_currency_impact(items)
    sentimen_data = {
        "generated": generated,
        "summary": {
            "total": len(items), "bullish": len(bullish),
            "bearish": len(bearish), "netral": len(netral),
            "avg_score": avg_score,
            "overall": "Bullish" if avg_score >= 0.05 else "Bearish" if avg_score <= -0.05 else "Netral",
            "currency_impact": [
                {
                    "currency": c,
                    "sentiment": "Bullish" if s >= 0.05 else "Bearish" if s <= -0.05 else "Netral",
                    "score": round(s, 3), "count": n,
                }
                for c, s, n in currency_impacts[:9]
            ],
        },
        "items": [item_to_dict(i) for i in items],
    }

    # ── FJ Live (FinancialJuice RSS + suplemen hingga 80-100, forex-only, Bahasa Indonesia) ──
    TARGET_FJ = 90
    fj_analyzed = [_analyze(i) for i in (fj_items or [])]

    # Tambal kekurangan dari koleksi sentimen umum (items) jika FJ RSS < TARGET.
    # items sudah lolos _is_forex_relevant() di collect_all_news() (yang mempercayai
    # sumber forex dedicated apa adanya, sehingga kadang meloloskan berita non-forex
    # dari sumber tsb) dan judulnya sudah diterjemahkan ke Indonesia di run_job().
    # _fj_supplement_ok() menyaring ulang lebih ketat (judul+ringkasan) supaya isi
    # tab Sentimen tetap benar-benar tentang forex, bukan cuma bertambah jumlahnya.
    if len(fj_analyzed) < TARGET_FJ:
        fj_urls = {i.url for i in fj_analyzed}
        need    = TARGET_FJ - len(fj_analyzed)
        extras  = [
            i for i in items
            if i.url not in fj_urls and _fj_supplement_ok(i)
        ][:need]
        if extras:
            fj_analyzed.extend([_analyze(ex) for ex in extras])
            log.info(f"[FJ-RSS] Suplemen {len(extras)} item forex → total {len(fj_analyzed)}")

    # Urutkan gabungan (FJ + suplemen) berdasarkan waktu publish terbaru —
    # day trader melihat berita paling mutakhir lebih dulu di tab Sentimen.
    fj_analyzed.sort(key=_sort_key, reverse=True)

    fj_bull = [i for i in fj_analyzed if i.sentiment_label == "Bullish"]
    fj_bear = [i for i in fj_analyzed if i.sentiment_label == "Bearish"]
    fj_net  = [i for i in fj_analyzed if i.sentiment_label == "Netral"]
    fj_avg  = round(sum(i.sentiment_score for i in fj_analyzed) / len(fj_analyzed), 4) if fj_analyzed else 0
    fj_live_data = {
        "generated": generated,
        "summary": {
            "total":   len(fj_analyzed),
            "bullish": len(fj_bull),
            "bearish": len(fj_bear),
            "netral":  len(fj_net),
            "avg_score": fj_avg,
            "overall": "Bullish" if fj_avg >= 0.05 else "Bearish" if fj_avg <= -0.05 else "Netral",
        },
        "items": [item_to_dict(i) for i in fj_analyzed],
    }

    # ── Geopolitik ──
    geo_items = [i for i in items if _is_geopolitical(i)]
    risk_level, risk_color, risk_emoji = _geo_risk_level(geo_items)
    pair_counter: dict[str, list[float]] = {}
    for gi in geo_items:
        for pair in _geo_pairs_for_item(gi):
            pair_counter.setdefault(pair, []).append(gi.sentiment_score)
    pairs_affected = []
    for pair, scores in sorted(pair_counter.items(), key=lambda x: -len(x[1]))[:8]:
        avg_p = sum(scores) / len(scores)
        pairs_affected.append({
            "pair": pair,
            "direction": "Tekanan Naik ▲" if avg_p >= 0.05 else "Tekanan Turun ▼" if avg_p <= -0.05 else "Netral →",
            "score": round(avg_p, 3), "count": len(scores),
        })
    # Enrichment fundamental — tambah analisis sentimen per mata uang ke rekomendasi
    # (versi tertimbang-dampak, terpisah dari currency_impact mentah di atas
    # yang tetap dipakai ringkasan tab Sentimen)
    if rekomendasi_data:
        weighted_impact = detect_currency_impact_weighted(items)
        _enrich_fundamental(rekomendasi_data, weighted_impact, events)

    geopolitik_data = {
        "generated": generated,
        "risk_level": risk_level, "risk_color": risk_color, "risk_emoji": risk_emoji,
        "pairs_affected": pairs_affected,
        "items": [item_to_dict(i) for i in geo_items],
    }

    # ── Simpan file ──
    try:
        os.makedirs(JSON_DIR, exist_ok=True)
        for fname, data in [
            ("kalender.json",   kalender_data),
            ("sentimen.json",   sentimen_data),
            ("geopolitik.json", geopolitik_data),
        ]:
            path = os.path.join(JSON_DIR, fname)
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
            n = len(data.get("events", data.get("items", [])))
            log.info(f"[JSON] {fname} tersimpan ({n} item)")

        # news_data.js — satu file gabungan yang dibaca langsung oleh HTML
        combined = {
            "generated":   generated,
            "kalender":    kalender_data,
            "sentimen":    sentimen_data,
            "geopolitik":  geopolitik_data,
            "fj_live":     fj_live_data,
            "rekomendasi": rekomendasi_data,
        }
        js_path = os.path.join(JSON_DIR, "news_data.js")
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(f"// Diperbarui: {generated}\nwindow.FK_DATA = ")
            _json.dump(combined, f, ensure_ascii=False, indent=2)
            f.write(";\n")
        log.info(f"[JSON] news_data.js tersimpan → {js_path}")
    except Exception as e:
        log.warning(f"[JSON] Gagal menyimpan: {e}")


def run_job() -> None:
    log.info("=" * 60)
    log.info("Memulai job ringkasan berita forex...")
    items           = collect_all_news()
    calendar_events = fetch_forexfactory_calendar()
    if not items and not calendar_events:
        log.warning("Tidak ada berita maupun data kalender yang berhasil dikumpulkan.")
        return
    # Terjemahkan semua judul sentimen ke Bahasa Indonesia
    if items:
        log.info(f"Menerjemahkan {len(items)} judul berita ke Bahasa Indonesia...")
        translated = _translate_id([i.title for i in items])
        for idx, item in enumerate(items):
            item.title = translated[idx]
        log.info("Terjemahan selesai.")
    fj_items         = fetch_fj_rss()
    rekomendasi_data = fetch_forex_technicals()
    save_news_data(items, calendar_events, fj_items, rekomendasi_data)
    send_all_emails(items, calendar_events)
    log.info("Job selesai.")
    log.info("=" * 60)


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="ForexDigest — kumpulkan berita forex, simpan JSON, kirim email"
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Jalankan terus-menerus dengan Python scheduler (mode manual/testing)",
    )
    args = parser.parse_args()

    send_time = f"{SEND_HOUR:02d}:00"

    log.info("=" * 60)
    log.info("ForexDigest — Ringkasan Berita Forex Harian")
    log.info(f"Penerima   : {SEND_TO or '(belum diisi .env)'}")
    log.info(f"Sumber     : ForexLive · FXStreet · DailyFX · ForexFactory · "
             f"FinancialJuice · Investing.com · Reuters · Bloomberg · Google News")
    log.info(f"Target     : ≥{MIN_NEWS_SENTIMEN} berita sentimen · ≥{MIN_NEWS_GEOPOLITIK} berita geopolitik")
    log.info(f"Output     : {JSON_DIR}")
    log.info(f"Log file   : {_LOG_FILE}")
    log.info(f"Email      : ✉ Kalender · ✉ Sentimen · ✉ Geopolitik")

    if args.loop:
        # ── Mode loop: pakai Python scheduler (untuk testing manual) ──
        log.info(f"Mode       : Loop — kirim email setiap hari jam {send_time} WIB")
        log.info("Jalankan dulu sekali sebelum masuk loop...")
        log.info("=" * 60)
        run_job()
        schedule.every().day.at(send_time).do(run_job)
        log.info(f"Menunggu jadwal berikutnya ({send_time} WIB)... tekan Ctrl+C untuk berhenti.")
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)
        except KeyboardInterrupt:
            log.info("Script dihentikan oleh pengguna.")
    else:
        # ── Mode default: jalankan sekali lalu keluar ──
        # Digunakan oleh Windows Task Scheduler — dipanggil otomatis jam 07:00 WIB
        log.info(f"Mode       : Run-once (dipanggil Task Scheduler jam {send_time} WIB)")
        log.info("=" * 60)
        run_job()
        log.info("Script selesai dan keluar.")
