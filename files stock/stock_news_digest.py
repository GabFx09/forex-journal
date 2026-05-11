#!/usr/bin/env python3
"""
stock_news_digest.py v2.3 — Analisis Saham Otomatis
Mengumpulkan berita saham, analisis sentimen, dan mengirim 3 email harian jam 07:00 WIB.

Penggunaan:
  python stock_news_digest.py --run-now     # Jalankan sekarang (test)
  python stock_news_digest.py               # Mode daemon — tunggu jam 07:00 WIB setiap hari
  python stock_news_digest.py --setup       # Buat ulang config_email.ini

Pembaruan v2.3:
  - Terjemahan: pakai translate.googleapis.com (client=gtx) via requests — TANPA package tambahan
  - Fallback otomatis ke MyMemory API jika Google gagal
  - Semua field judul_id + ringkasan_id tersedia di JSON untuk dashboard HTML

v2.1 improvements retained:
  - Kalender: 2 sumber (minggu ini + depan) + fallback hari kerja saat weekend
  - Sentimen: threshold ±1, rekomendasi_pasar, analisis indeks diperluas
  - Geopolitik: keyword diperluas ke pasar AS, fallback US market news
  - 12 feed US, max 15 artikel per feed
"""

import os, sys, re, json, time, logging, configparser, smtplib
from datetime import datetime, date as _date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import unescape

try:
    from zoneinfo import ZoneInfo
except ImportError:
    import pytz
    class ZoneInfo:
        def __init__(self, key): self._tz = pytz.timezone(key)
        def __call__(self): return self._tz
    _orig = ZoneInfo
    ZoneInfo = lambda k: _orig(k)._tz

try:
    import feedparser
except ImportError:
    sys.exit("ERROR: Jalankan dulu: pip install -r requirements.txt")

try:
    import requests
except ImportError:
    sys.exit("ERROR: Jalankan dulu: pip install -r requirements.txt")

try:
    import schedule
except ImportError:
    sys.exit("ERROR: Jalankan dulu: pip install -r requirements.txt")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ─── PATHS ────────────────────────────────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE     = os.path.join(BASE_DIR, 'config_email.ini')
KALENDER_FILE   = os.path.join(BASE_DIR, 'kalender.json')
SENTIMEN_FILE   = os.path.join(BASE_DIR, 'sentimen.json')
GEOPOLITIK_FILE = os.path.join(BASE_DIR, 'geopolitik.json')
DATA_JS_FILE    = os.path.join(BASE_DIR, 'stock_analysis_data.js')
LOG_FILE        = os.path.join(BASE_DIR, 'stock_digest.log')

WIB = ZoneInfo('Asia/Jakarta')

TRANSLATE_ENABLED = True

# ─── LOGGING ──────────────────────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)

# ─── RSS FEEDS (12 US + 3 ID) ─────────────────────────────────────────────────
FEEDS_US = [
    {'nama': 'Reuters',        'url': 'http://feeds.reuters.com/reuters/businessNews',         'asal': 'US'},
    {'nama': 'CNBC Markets',   'url': 'https://www.cnbc.com/id/100003114/device/rss/rss.html', 'asal': 'US'},
    {'nama': 'CNBC Top News',  'url': 'https://www.cnbc.com/id/100727362/device/rss/rss.html', 'asal': 'US'},
    {'nama': 'Yahoo Finance',  'url': 'https://finance.yahoo.com/news/rssindex',               'asal': 'US'},
    {'nama': 'MarketWatch',    'url': 'https://feeds.marketwatch.com/marketwatch/topstories/', 'asal': 'US'},
    {'nama': 'Investing.com',  'url': 'https://www.investing.com/rss/news_25.rss',             'asal': 'US'},
    {'nama': 'Motley Fool',    'url': 'https://www.fool.com/feeds/index.aspx',                 'asal': 'US'},
    {'nama': 'Seeking Alpha',  'url': 'https://seekingalpha.com/market_currents.xml',          'asal': 'US'},
    {'nama': 'Benzinga',       'url': 'https://www.benzinga.com/feed',                         'asal': 'US'},
    {'nama': 'TheStreet',      'url': 'https://www.thestreet.com/rss/index.xml',               'asal': 'US'},
    {'nama': 'Barrons',        'url': 'https://feeds.barrons.com/barrons/home',                'asal': 'US'},
    {'nama': 'AP Business',    'url': 'https://feeds.apnews.com/rss/business',                 'asal': 'US'},
]

FEEDS_ID = [
    {'nama': 'Kontan',           'url': 'https://rss.kontan.co.id/news/pasar-saham',       'asal': 'ID'},
    {'nama': 'CNBC Indonesia',   'url': 'https://www.cnbcindonesia.com/market/rss',         'asal': 'ID'},
    {'nama': 'Bisnis Indonesia', 'url': 'https://rss.bisnis.com/feed/articles/pasar-modal', 'asal': 'ID'},
]

# ─── KEYWORD LISTS ────────────────────────────────────────────────────────────
BULLISH_WORDS = [
    'surge', 'rally', 'gain', 'rise', 'jump', 'soar', 'climb', 'bull',
    'outperform', 'beat', 'record high', 'upgrade', 'buy rating', 'strong',
    'growth', 'profit', 'recovery', 'rebound', 'positive', 'optimism',
    'exceeded', 'revenue beat', 'better than expected', 'all-time high',
    'record', 'boom', 'expansion', 'accelerat', 'breakout', 'skyrocket',
    'top gainer', 'outperforms', 'buy signal', 'bullish', 'uptrend',
    'strong earnings', 'beat expectations', 'profit surge',
    'naik', 'menguat', 'reli', 'positif', 'tumbuh', 'meningkat',
    'melonjak', 'bertumbuh', 'untung', 'berhasil', 'rekor',
]

BEARISH_WORDS = [
    'fall', 'drop', 'decline', 'plunge', 'crash', 'bear', 'sell-off',
    'selloff', 'downgrade', 'miss', 'below expectations', 'recession',
    'contraction', 'layoff', 'bankrupt', 'concern', 'risk', 'worry',
    'warning', 'weak', 'loss', 'deficit', 'inflation fears', 'rate hike',
    'slowdown', 'shrink', 'contract', 'tumble', 'slide', 'slump',
    'miss expectations', 'earnings miss', 'profit warning', 'bearish',
    'downtrend', 'breakdown', 'sell signal', 'underperform', 'cut forecast',
    'guidance cut', 'revenue miss', 'job cuts', 'layoffs', 'bankruptcy',
    'turun', 'melemah', 'jatuh', 'rugi', 'koreksi', 'tekanan',
    'merosot', 'anjlok', 'tertekan', 'kerugian', 'terpuruk',
]

GEO_KEYWORDS = [
    'war', 'conflict', 'military', 'sanction', 'tariff', 'trade war',
    'geopolit', 'china', 'russia', 'ukraine', 'iran', 'north korea',
    'middle east', 'nato', 'brics', 'election', 'political',
    'opec', 'oil', 'energy', 'coup', 'taiwan',
    'south china sea', 'nuclear', 'missile', 'embargo', 'invasion',
    'ceasefire', 'trump tariff', 'trade deal', 'import duty', 'export ban',
    'trump', 'white house', 'congress', 'senate', 'federal reserve',
    'fed', 'rate hike', 'rate cut', 'interest rate', 'fomc',
    'inflation', 'recession', 'gdp', 'jobs report', 'unemployment',
    'debt ceiling', 'government', 'budget', 'deficit',
    'supply chain', 'semiconductor', 'chip', 'rare earth', 'export control',
    'wall street', 's&p', 'nasdaq', 'dow', 'stock market', 'stock',
    'market rally', 'market crash', 'bear market', 'bull market',
    'earnings', 'ipo', 'merger', 'acquisition', 'buyout',
    'hedge fund', 'short', 'volatility', 'vix', 'options',
    'geopolitik', 'perang', 'konflik', 'sanksi', 'pemilu', 'krisis',
    'blokade', 'invasi', 'serangan', 'militer', 'saham', 'pasar modal',
    'bank sentral', 'suku bunga', 'inflasi', 'resesi',
]

KNOWN_TICKERS = {
    'AAPL','MSFT','GOOGL','GOOG','AMZN','META','NVDA','TSLA','NFLX',
    'UBER','LYFT','INTC','AMD','QCOM','ORCL','CRM','ADBE','PYPL','SQ',
    'V','MA','JPM','GS','BAC','C','WFC','XOM','CVX','SPY','QQQ','DIA',
    'SHOP','SNAP','ABNB','COIN','HOOD','PLTR','ARM','SMCI','DELL',
    'IBM','HPQ','CSCO','AMAT','LRCX','KLAC','MU','WDC','STX','AVGO',
    'TXN','ADI','MCHP','SWKS','MPWR','ENTG','ONTO',
    'AMGN','BIIB','GILD','MRNA','PFE','JNJ','UNH','CVS','WBA','MCK',
    'DIS','CMCSA','T','VZ','TMUS','CHTR','PARA','WBD','FOX',
    'F','GM','RIVN','LCID','NIO','LI','XPEV',
    'BRK','WMT','TGT','COST','HD','LOW','SBUX','MCD','NKE','PG',
    'KO','PEP','PM','MO','BABA','JD','PDD','TSM',
}

TICKER_RE = re.compile(r'\b([A-Z]{2,5})\b')

GEO_KATEGORI_MAP = [
    (['tariff', 'trade war', 'import duty', 'export ban', 'trade deal'],  'Tarif/Perdagangan'),
    (['sanction', 'embargo', 'sanksi', 'blokade'],                         'Sanksi'),
    (['war', 'invasion', 'conflict', 'military', 'missile', 'nuclear',
      'perang', 'invasi', 'militer', 'serangan'],                          'Konflik Militer'),
    (['election', 'political', 'coup', 'pemilu'],                          'Politik'),
    (['opec', 'oil', 'energy', 'minyak', 'energi'],                        'Energi/OPEC'),
    (['china', 'taiwan', 'south china sea'],                                'China/Taiwan'),
    (['russia', 'ukraine', 'rusia', 'ukraina'],                             'Rusia/Ukraina'),
    (['iran', 'north korea', 'middle east'],                                'Timur Tengah'),
    (['nato', 'brics'],                                                     'Aliansi Global'),
    (['federal reserve', 'fed', 'fomc', 'rate', 'inflation'],              'Kebijakan Moneter'),
    (['s&p', 'nasdaq', 'dow', 'wall street', 'stock market'],              'Pasar Saham AS'),
    (['earnings', 'ipo', 'merger', 'acquisition'],                         'Aksi Korporasi'),
    (['semiconductor', 'chip', 'supply chain'],                            'Teknologi/Rantai Pasok'),
]

DAMPAK_MAP = {
    'High': 'Tinggi', 'Medium': 'Sedang', 'Low': 'Rendah',
    '3': 'Tinggi', '2': 'Sedang', '1': 'Rendah',
}

# ─── KAMUS NAMA EVENT EKONOMI ─────────────────────────────────────────────────
EVENT_NAMES_ID = {
    'non-farm payroll':          'Penggajian Non-Pertanian (NFP)',
    'nfp':                       'Penggajian Non-Pertanian (NFP)',
    'initial jobless claims':    'Klaim Pengangguran Awal',
    'continuing jobless claims': 'Klaim Pengangguran Berlanjut',
    'jobless claims':            'Klaim Pengangguran',
    'unemployment rate':         'Tingkat Pengangguran',
    'cpi':                       'Indeks Harga Konsumen (CPI)',
    'consumer price index':      'Indeks Harga Konsumen (CPI)',
    'core cpi':                  'CPI Inti (Tanpa Energi & Pangan)',
    'ppi':                       'Indeks Harga Produsen (PPI)',
    'producer price index':      'Indeks Harga Produsen (PPI)',
    'fomc':                      'Keputusan FOMC — Kebijakan Moneter Fed',
    'federal open market':       'Keputusan FOMC — Kebijakan Moneter Fed',
    'interest rate decision':    'Keputusan Suku Bunga Federal Reserve',
    'fed rate':                  'Suku Bunga Federal Reserve',
    'gdp':                       'Produk Domestik Bruto (PDB)',
    'retail sales':              'Penjualan Ritel',
    'pmi':                       'Indeks Manajer Pembelian (PMI)',
    'ism manufacturing':         'ISM Manufaktur',
    'ism services':              'ISM Jasa/Non-Manufaktur',
    'ism non-manufacturing':     'ISM Non-Manufaktur',
    'housing starts':            'Pembangunan Rumah Baru',
    'building permits':          'Izin Bangunan Baru',
    'existing home sales':       'Penjualan Rumah Bekas',
    'new home sales':            'Penjualan Rumah Baru',
    'pending home sales':        'Kontrak Rumah Tertunda',
    'trade balance':             'Neraca Perdagangan AS',
    'consumer confidence':       'Indeks Kepercayaan Konsumen',
    'consumer sentiment':        'Sentimen Konsumen Michigan',
    'durable goods':             'Pesanan Barang Tahan Lama',
    'factory orders':            'Pesanan Pabrik',
    'industrial production':     'Produksi Industri',
    'capacity utilization':      'Kapasitas Utilisasi',
    'empire state':              'Indeks Manufaktur Empire State',
    'philly fed':                'Indeks Fed Philadelphia',
    'beige book':                'Buku Beige Federal Reserve',
    'crude oil inventories':     'Stok Minyak Mentah AS (EIA)',
    'natural gas storage':       'Penyimpanan Gas Alam',
    'current account':           'Neraca Berjalan',
    'average hourly earnings':   'Rata-rata Upah Per Jam',
    'participation rate':        'Tingkat Partisipasi Tenaga Kerja',
    'jolts':                     'Data Lowongan Kerja (JOLTS)',
    'job openings':              'Lowongan Kerja (JOLTS)',
    'adp non-farm':              'Penggajian Non-Pertanian ADP',
    'adp employment':            'Data Ketenagakerjaan ADP',
    'personal income':           'Pendapatan Pribadi',
    'personal spending':         'Pengeluaran Pribadi',
    'pce price index':           'Indeks Harga PCE (Inflasi Favorit Fed)',
    'core pce':                  'PCE Inti (Inflasi Inti Fed)',
    'treasury':                  'Lelang Obligasi Treasury AS',
    '10-year':                   'Lelang Treasury 10 Tahun',
    '30-year':                   'Lelang Treasury 30 Tahun',
    'powell':                    'Pidato Ketua Fed Powell',
    'fed chair':                 'Pidato Ketua Federal Reserve',
    'fed speak':                 'Pidato Pejabat Federal Reserve',
    'flash pmi':                 'PMI Kilat (Estimasi Awal)',
    'chicago pmi':               'PMI Chicago',
    'richmond fed':              'Indeks Manufaktur Richmond Fed',
    'dallas fed':                'Indeks Manufaktur Dallas Fed',
    'kansas city fed':           'Indeks Manufaktur Kansas City Fed',
    'export prices':             'Indeks Harga Ekspor',
    'import prices':             'Indeks Harga Impor',
    'wholesale inventories':     'Inventori Pedagang Grosir',
    'business inventories':      'Inventori Bisnis',
    'leading indicators':        'Indeks Leading Ekonomi',
}

def translate_event_name(title):
    t = title.lower()
    for en, id_name in EVENT_NAMES_ID.items():
        if en in t:
            return id_name
    return title

# ─── TERJEMAHAN OTOMATIS (tanpa package tambahan) ─────────────────────────────
_TRANS_CACHE: dict = {}
_TRANS_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockDigest/2.3'}

def _try_google_gtx(text: str) -> str:
    """Google Translate via endpoint publik client=gtx — tidak butuh API key."""
    resp = requests.get(
        'https://translate.googleapis.com/translate_a/single',
        params={'client': 'gtx', 'sl': 'auto', 'tl': 'id', 'dt': 't', 'q': text[:500]},
        headers=_TRANS_HEADERS,
        timeout=8,
    )
    data = resp.json()
    # Format respons: [[['terjemahan', 'asli', ...], ...], ...]
    result = ''.join(part[0] for part in data[0] if part[0])
    return result if len(result) > 3 else ''

def _try_mymemory(text: str) -> str:
    """MyMemory API sebagai fallback."""
    r = requests.get(
        'https://api.mymemory.translated.net/get',
        params={'q': text[:450], 'langpair': 'en|id'},
        timeout=6,
        headers=_TRANS_HEADERS,
    )
    data = r.json()
    result = data.get('responseData', {}).get('translatedText', '')
    bad = ('MYMEMORY WARNING', 'PLEASE SELECT', 'QUOTA EXPIRED')
    if result and len(result) > 3 and result.upper() != text.upper() and not any(b in result.upper() for b in bad):
        return result
    return ''

def translate_to_id(text: str) -> str:
    if not text or len(text.strip()) < 5:
        return text
    key = text[:150]
    if key in _TRANS_CACHE:
        return _TRANS_CACHE[key]

    for fn in (_try_google_gtx, _try_mymemory):
        try:
            result = fn(text)
            if result:
                _TRANS_CACHE[key] = result
                return result
        except Exception as e:
            log.debug(f'{fn.__name__} gagal: {e}')

    _TRANS_CACHE[key] = text
    return text

def translate_articles(articles: list) -> list:
    for a in articles:
        if a.get('asal') != 'US':
            a['judul_id']     = a.get('judul', '')
            a['ringkasan_id'] = a.get('ringkasan', '')

    us_articles = [a for a in articles if a.get('asal') == 'US']
    if not TRANSLATE_ENABLED or not us_articles:
        for a in us_articles:
            a['judul_id']     = a.get('judul', '')
            a['ringkasan_id'] = a.get('ringkasan', '')
        return articles

    log.info(f'── Menerjemahkan {len(us_articles)} artikel US ke Bahasa Indonesia ──')
    for i, a in enumerate(us_articles, 1):
        a['judul_id']     = translate_to_id(a.get('judul', ''))
        time.sleep(0.12)
        ringkasan = a.get('ringkasan', '')
        a['ringkasan_id'] = translate_to_id(ringkasan) if ringkasan and len(ringkasan) > 5 else ringkasan
        time.sleep(0.12)
        if i % 10 == 0 or i == len(us_articles):
            log.info(f'  {i}/{len(us_articles)} artikel diterjemahkan')

    for a in articles:
        a.setdefault('judul_id',     a.get('judul', ''))
        a.setdefault('ringkasan_id', a.get('ringkasan', ''))

    log.info(f'  Selesai — {len(us_articles)} judul + {len(us_articles)} ringkasan')
    return articles

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def clean_html(raw):
    if not raw:
        return ''
    if HAS_BS4:
        return BeautifulSoup(raw, 'html.parser').get_text(' ', strip=True)
    return re.sub(r'<[^>]+>', ' ', unescape(str(raw))).strip()

def truncate(text, n=250):
    t = clean_html(text)
    return t[:n] + '…' if len(t) > n else t

def now_wib():
    return datetime.now(WIB)

def fmt_wib(dt=None):
    if dt is None:
        dt = now_wib()
    return dt.strftime('%Y-%m-%d %H:%M WIB')

def today_str():
    return now_wib().strftime('%Y-%m-%d')

def hari_label():
    dt = now_wib()
    hari  = ['Senin','Selasa','Rabu','Kamis','Jumat','Sabtu','Minggu']
    bulan = ['','Januari','Februari','Maret','April','Mei','Juni',
             'Juli','Agustus','September','Oktober','November','Desember']
    return f"{hari[dt.weekday()]}, {dt.day} {bulan[dt.month]} {dt.year}"

def _next_business_day(date_str: str) -> str:
    d = _date.fromisoformat(date_str) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()

def _last_business_day(date_str: str) -> str:
    d = _date.fromisoformat(date_str) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()

# ─── CONFIG ───────────────────────────────────────────────────────────────────
def create_default_config():
    c = configparser.ConfigParser()
    c['email'] = {
        'sender':    'your_email@gmail.com',
        'password':  'xxxx xxxx xxxx xxxx',
        'recipient': 'v3662432@gmail.com',
        'smtp_host': 'smtp.gmail.com',
        'smtp_port': '587',
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        c.write(f)
    log.info(f'Config dibuat: {CONFIG_FILE}')

def load_config():
    if not os.path.exists(CONFIG_FILE):
        create_default_config()
        log.warning('config_email.ini tidak ada — sudah dibuat template.')
        return None
    c = configparser.ConfigParser()
    c.read(CONFIG_FILE, encoding='utf-8')
    try:
        cfg = {
            'sender':    c['email']['sender'].strip(),
            'password':  c['email']['password'].strip(),
            'recipient': c['email']['recipient'].strip(),
            'smtp_host': c['email'].get('smtp_host', 'smtp.gmail.com').strip(),
            'smtp_port': int(c['email'].get('smtp_port', '587')),
        }
        if 'your_email' in cfg['sender'] or 'xxxx' in cfg['password']:
            log.error('config_email.ini belum diisi!')
            return None
        return cfg
    except (KeyError, ValueError) as e:
        log.error(f'Config tidak lengkap: {e}')
        return None

# ─── RSS FETCHING ─────────────────────────────────────────────────────────────
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockDigest/2.3 (+RSS)'}

def fetch_feed(source, timeout=12, max_per_feed=15):
    articles = []
    try:
        resp = requests.get(source['url'], headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:max_per_feed]:
            title   = clean_html(getattr(entry, 'title',   '') or '')
            summary = truncate(getattr(entry, 'summary', '') or getattr(entry, 'description', '') or '')
            link    = getattr(entry, 'link',      '') or ''
            pub     = getattr(entry, 'published', '') or getattr(entry, 'updated', '') or ''
            if not title:
                continue
            articles.append({
                'judul':     title[:300],
                'ringkasan': summary,
                'url':       link,
                'sumber':    source['nama'],
                'waktu':     fmt_wib(),
                'waktu_raw': pub,
                'asal':      source.get('asal', 'US'),
            })
        log.info(f"  ✓ {source['nama']}: {len(articles)} berita")
    except Exception as e:
        log.warning(f"  ⚠ {source['nama']}: {e}")
    return articles

def dedup(articles):
    seen, unique = set(), []
    for a in articles:
        key = re.sub(r'\s+', '', a['judul'][:50].lower())
        if key and key not in seen:
            seen.add(key)
            unique.append(a)
    return unique

def fetch_all_news():
    log.info('── Mengumpulkan berita RSS ──')
    us_arts, id_arts = [], []

    for s in FEEDS_US:
        us_arts.extend(fetch_feed(s))
        time.sleep(0.4)
    for s in FEEDS_ID:
        id_arts.extend(fetch_feed(s))
        time.sleep(0.3)

    us_dedup = dedup(us_arts)
    id_dedup = dedup(id_arts)

    total_target = max(50, len(us_dedup) + len(id_dedup))
    us_quota = int(total_target * 0.8)
    id_quota = total_target - us_quota

    combined = dedup(us_dedup[:us_quota] + id_dedup[:id_quota])
    log.info(f'Total berita unik: {len(combined)} (US={min(len(us_dedup), us_quota)}, ID={min(len(id_dedup), id_quota)})')
    return combined

# ─── SENTIMENT & GEO ANALYSIS ─────────────────────────────────────────────────
def analyze_sentiment(text):
    t = text.lower()
    score = sum(1 for w in BULLISH_WORDS if w in t) - sum(1 for w in BEARISH_WORDS if w in t)
    if score >= 1:
        return 'Bullish', score
    if score <= -1:
        return 'Bearish', score
    return 'Netral', score

def find_tickers(text):
    return [m for m in TICKER_RE.findall(text) if m in KNOWN_TICKERS]

def is_geopolitical(article):
    text = (article['judul'] + ' ' + article.get('ringkasan', '')).lower()
    return any(kw in text for kw in GEO_KEYWORDS)

def categorize_geo(article):
    text = (article['judul'] + ' ' + article.get('ringkasan', '')).lower()
    for kw_list, label in GEO_KATEGORI_MAP:
        if any(kw in text for kw in kw_list):
            return label
    return 'Pasar Saham AS'

# ─── ECONOMIC CALENDAR ────────────────────────────────────────────────────────
def _stock_impact_hint(title):
    t = title.lower()
    if 'non-farm' in t or 'nfp' in t:
        return 'Di atas ekspektasi → S&P naik; Di bawah → S&P turun'
    if 'pce' in t:
        return 'PCE adalah inflasi favorit Fed — tinggi berarti hawkish → negatif pasar'
    if 'cpi' in t or 'consumer price' in t:
        return 'CPI tinggi → Fed hawkish → pasar turun; CPI rendah → potensi rate cut → naik'
    if 'fomc' in t or 'federal open' in t or 'interest rate decision' in t:
        return 'Rate hike → negatif saham; Rate cut / dovish → sangat positif'
    if 'gdp' in t:
        return 'GDP kuat → ekonomi sehat → positif; GDP lemah → kekhawatiran resesi → negatif'
    if 'unemployment' in t or 'jobless' in t:
        return 'Pengangguran naik → pasar khawatir; Pengangguran turun → ekonomi sehat'
    if 'retail sales' in t:
        return 'Penjualan retail kuat → konsumsi tinggi → positif saham consumer'
    if 'pmi' in t:
        return 'PMI > 50 = ekspansi (bullish); PMI < 50 = kontraksi (bearish)'
    if 'ism' in t:
        return 'ISM tinggi → manufaktur/jasa kuat → positif ekonomi AS'
    if 'housing' in t or 'home sales' in t or 'building' in t:
        return 'Data perumahan kuat → ekonomi sehat; lemah → tekanan konsumen'
    if 'adp' in t:
        return 'Prekursor NFP — ADP kuat → ekspektasi NFP tinggi → pasar naik'
    if 'treasury' in t or 'yield' in t or '-year' in t:
        return 'Imbal hasil naik → saham growth tertekan; turun → saham teknologi naik'
    if 'powell' in t or 'fed chair' in t or 'fed speak' in t:
        return 'Nada dovish → pasar naik; nada hawkish → pasar turun'
    if 'oil' in t or 'crude' in t or 'natural gas' in t:
        return 'Stok naik → harga energi turun → positif sektor konsumer'
    return 'Pantau reaksi pasar — volatilitas mungkin terjadi'

def _format_event(ev, tanggal_label='Hari Ini'):
    impact = ev.get('impact', 'Low')
    title  = ev.get('title', '—')
    return {
        'waktu':         (ev.get('time') or '—') + ' ET',
        'event':         title,
        'event_id':      translate_event_name(title),
        'dampak':        DAMPAK_MAP.get(impact, 'Rendah'),
        'dampak_en':     impact,
        'mata_uang':     'USD',
        'aktual':        ev.get('actual')   or '—',
        'perkiraan':     ev.get('forecast') or '—',
        'sebelumnya':    ev.get('previous') or '—',
        'dampak_saham':  _stock_impact_hint(title),
        'tanggal_label': tanggal_label,
    }

def _fetch_ff_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f'  Kalender [{url.split("/")[-1]}] gagal: {e}')
        return []

def fetch_economic_calendar():
    log.info('── Mengambil kalender ekonomi ──')
    today = today_str()

    all_data: list = []
    all_data.extend(_fetch_ff_json('https://nfs.faireconomy.media/ff_calendar_thisweek.json'))
    time.sleep(0.5)
    all_data.extend(_fetch_ff_json('https://nfs.faireconomy.media/ff_calendar_nextweek.json'))

    all_usd = [ev for ev in all_data if ev.get('country', '').upper() == 'USD']
    available_dates = sorted(set(str(ev.get('date', ''))[:10] for ev in all_usd))
    log.info(f'  Kalender tersedia: {available_dates}')

    def filter_usd(target_date: str, label: str) -> list:
        return [_format_event(ev, label) for ev in all_usd if str(ev.get('date', ''))[:10] == target_date]

    events = filter_usd(today, 'Hari Ini')
    weekend_mode = False
    calendar_note = ''

    if len(events) < 3:
        nbd = _next_business_day(today)
        nbd_events = filter_usd(nbd, f'Besok ({nbd})')
        if nbd_events:
            log.info(f'  Tidak ada event hari ini, pakai besok ({nbd}): {len(nbd_events)} event')
            events.extend(nbd_events)
            weekend_mode = True

    if len(events) < 5:
        lbd = today
        past_events = []
        for _ in range(5):
            lbd = _last_business_day(lbd)
            day_evts = filter_usd(lbd, f'Ringkasan ({lbd})')
            past_events.extend(day_evts)
            if len(past_events) >= 15:
                break
        if past_events:
            events.extend(past_events[:20])
            weekend_mode = True
            calendar_note = (
                'Hari ini adalah akhir pekan — pasar tutup. '
                'Menampilkan ringkasan kalender ekonomi minggu lalu. '
                'Data minggu depan akan tersedia Senin pagi.'
            )

    log.info(f'  Kalender: {len(events)} event | weekend_mode={weekend_mode}')
    return events, weekend_mode, calendar_note

# ─── DATA PREPARATION ─────────────────────────────────────────────────────────
def prepare_kalender(events, weekend_mode=False, calendar_note=''):
    tinggi = sum(1 for e in events if e['dampak'] == 'Tinggi')
    dt = now_wib()
    hari_names = ['Senin','Selasa','Rabu','Kamis','Jumat','Sabtu','Minggu']
    if not calendar_note and weekend_mode:
        calendar_note = (f'Hari ini ({hari_names[dt.weekday()]}) tidak ada event USD baru. '
                         'Menampilkan event hari kerja berikutnya.')
    return {
        'tanggal':        today_str(),
        'hari_ini_label': hari_label(),
        'jam_update':     fmt_wib(),
        'total_event':    len(events),
        'event_tinggi':   tinggi,
        'weekend_mode':   weekend_mode,
        'catatan':        calendar_note,
        'hari_ini':       events,
    }

def _rekomendasi_pasar(avg: float) -> str:
    if avg >= 2.5:
        return 'BELI KUAT — Sentimen sangat bullish. Pertimbangkan posisi long pada setiap pullback ke support.'
    if avg >= 1.5:
        return 'BELI — Sentimen positif. Pantau level resistance sebelum entry, perhatikan volume.'
    if avg >= 0.5:
        return 'HATI-HATI BELI — Sentimen sedikit bullish. Gunakan position sizing kecil, konfirmasi breakout dulu.'
    if avg <= -2.5:
        return 'JUAL/SHORT — Sentimen sangat bearish. Risiko koreksi tinggi, pertimbangkan lindung nilai.'
    if avg <= -1.5:
        return 'KURANGI POSISI — Sentimen negatif. Kurangi eksposur, hindari pembelian baru.'
    if avg <= -0.5:
        return 'NETRAL/HATI-HATI — Sedikit tekanan jual. Tunggu konfirmasi pembalikan sebelum entry baru.'
    return 'NETRAL — Pasar mixed. Tunggu katalis yang jelas; fokus pada saham dengan fundamental kuat.'

def prepare_sentimen(articles):
    scored = []
    for a in articles:
        text    = a['judul'] + ' ' + a.get('judul_id', '') + ' ' + a['ringkasan']
        label, score = analyze_sentiment(text)
        tickers = find_tickers(text)
        scored.append({**a, 'sentimen': label, 'skor': score, 'tickers': tickers})

    total   = len(scored) or 1
    bullish = [x for x in scored if x['sentimen'] == 'Bullish']
    bearish = [x for x in scored if x['sentimen'] == 'Bearish']
    netral  = [x for x in scored if x['sentimen'] == 'Netral']

    avg     = sum(x['skor'] for x in scored) / total
    overall = 'Bullish' if avg >= 0.5 else 'Bearish' if avg <= -0.5 else 'Netral'

    def idx_sent(kw_list):
        arts = [
            x for x in scored
            if any(k in (x['judul'] + ' ' + x.get('judul_id','') + ' ' + x['ringkasan']).lower()
                   for k in kw_list)
        ]
        if not arts:
            return {'sentimen': 'Netral', 'skor': 0.0, 'jumlah_berita': 0}
        s = sum(x['skor'] for x in arts) / len(arts)
        label = 'Bullish' if s >= 0.5 else 'Bearish' if s <= -0.5 else 'Netral'
        return {'sentimen': label, 'skor': round(s, 2), 'jumlah_berita': len(arts)}

    ticker_map: dict = {}
    for a in scored:
        for t in a['tickers']:
            if t not in ticker_map:
                ticker_map[t] = {
                    'skor_total': 0, 'count': 0,
                    'judul': a['judul'],
                    'judul_id': a.get('judul_id', a['judul']),
                }
            ticker_map[t]['skor_total'] += a['skor']
            ticker_map[t]['count']      += 1

    hot_bullish = sorted(
        [{'ticker': t, 'judul': v['judul'], 'judul_id': v.get('judul_id',''), 'skor': v['skor_total'], 'count': v['count']}
         for t, v in ticker_map.items() if v['skor_total'] > 0],
        key=lambda x: x['skor'], reverse=True)[:5]

    hot_bearish = sorted(
        [{'ticker': t, 'judul': v['judul'], 'judul_id': v.get('judul_id',''), 'skor': v['skor_total'], 'count': v['count']}
         for t, v in ticker_map.items() if v['skor_total'] < 0],
        key=lambda x: x['skor'])[:5]

    return {
        'tanggal':    today_str(),
        'jam_update': fmt_wib(),
        'ringkasan': {
            'overall':      overall,
            'skor_rata':    round(avg, 2),
            'bullish_pct':  round(len(bullish) / total * 100),
            'bearish_pct':  round(len(bearish) / total * 100),
            'netral_pct':   round(len(netral)  / total * 100),
            'total_berita': len(scored),
        },
        'rekomendasi_pasar': _rekomendasi_pasar(avg),
        'indeks': {
            'sp500':     idx_sent(['s&p', 'sp500', 's&p 500', 'spx', 'spy', 'stock market', 'equities', 'wall street']),
            'nasdaq':    idx_sent(['nasdaq', 'qqq', 'tech stock', 'technology', 'growth stock', 'ai stock', 'semiconductor']),
            'dow_jones': idx_sent(['dow jones', 'djia', 'dow', 'dia', 'blue chip', 'industrial']),
        },
        'saham_panas': {
            'bullish': hot_bullish,
            'bearish': hot_bearish,
        },
        'berita': scored[:50],
    }

_US_MARKET_KW = [
    'stock', 'market', 'share', 'equity', 'wall street', 'nasdaq',
    's&p', 'dow', 'fed', 'economy', 'earnings', 'revenue', 'profit',
    'invest', 'portfolio', 'fund', 'ipo', 'merger', 'acquisition',
    'dividend', 'buyback', 'analyst', 'forecast', 'outlook', 'sector',
]

def prepare_geopolitik(articles):
    geo   = []
    geo_ids: set = set()

    for a in articles:
        if not is_geopolitical(a):
            continue
        text  = a['judul'] + ' ' + a.get('ringkasan', '')
        label, score = analyze_sentiment(text)
        dampak = 'Positif' if label == 'Bullish' else 'Negatif' if label == 'Bearish' else 'Netral'
        geo.append({**a, 'sentimen': label, 'skor': score, 'kategori': categorize_geo(a), 'dampak_pasar': dampak})
        geo_ids.add(id(a))

    if len(geo) < 30:
        log.info(f'  Geopolitik fase 1: {len(geo)} berita, tambahkan berita pasar AS...')
        for a in articles:
            if id(a) in geo_ids:
                continue
            text = (a['judul'] + ' ' + a.get('ringkasan', '')).lower()
            if any(kw in text for kw in _US_MARKET_KW):
                label, score = analyze_sentiment(a['judul'] + ' ' + a.get('ringkasan', ''))
                dampak = 'Positif' if label == 'Bullish' else 'Negatif' if label == 'Bearish' else 'Netral'
                geo.append({**a, 'sentimen': label, 'skor': score, 'kategori': categorize_geo(a), 'dampak_pasar': dampak})
                geo_ids.add(id(a))
            if len(geo) >= 50:
                break

    geo.sort(key=lambda x: abs(x['skor']), reverse=True)
    log.info(f'  Geopolitik total: {len(geo)} berita')

    return {
        'tanggal':      today_str(),
        'jam_update':   fmt_wib(),
        'total_berita': len(geo),
        'berita':       geo[:50],
    }

# ─── FILE WRITERS ─────────────────────────────────────────────────────────────
def save_json_files(kalender, sentimen, geopolitik):
    for path, data in [
        (KALENDER_FILE,   kalender),
        (SENTIMEN_FILE,   sentimen),
        (GEOPOLITIK_FILE, geopolitik),
    ]:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info(f'  Tersimpan: {os.path.basename(path)}')

def generate_js_data(kalender, sentimen, geopolitik):
    ts = fmt_wib()
    js  = f'// Auto-generated by stock_news_digest.py v2.3 — {ts}\n'
    js += f'// Jangan edit manual — file ini di-overwrite setiap hari jam 07:00 WIB\n'
    js += f'var STOCK_LAST_UPDATE = {json.dumps(ts)};\n'
    js += f'var STOCK_KALENDER   = {json.dumps(kalender,   ensure_ascii=False)};\n'
    js += f'var STOCK_SENTIMEN   = {json.dumps(sentimen,   ensure_ascii=False)};\n'
    js += f'var STOCK_GEOPOLITIK = {json.dumps(geopolitik, ensure_ascii=False)};\n'
    with open(DATA_JS_FILE, 'w', encoding='utf-8') as f:
        f.write(js)
    log.info(f'  JS data: {os.path.basename(DATA_JS_FILE)}')

# ─── EMAIL CSS ────────────────────────────────────────────────────────────────
_CSS = """
body{font-family:'Segoe UI',Arial,sans-serif;background:#0a1628;color:#f0f4f8;margin:0;padding:16px}
.wrap{max-width:680px;margin:0 auto}
.hdr{background:linear-gradient(135deg,#0f2040,#152440);border-radius:12px 12px 0 0;padding:20px 24px;border-bottom:2px solid #10b981}
.htitle{font-size:20px;font-weight:700;color:#f0f4f8;margin:0}
.hsub{font-size:12px;color:#8899aa;margin-top:5px}
.body{background:#0f1e35;padding:20px 24px;border-radius:0 0 12px 12px}
.sec{background:#152440;border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:16px;margin-bottom:14px}
.stitle{font-size:12px;font-weight:700;color:#f0f4f8;margin-bottom:12px;border-bottom:1px solid rgba(255,255,255,.06);padding-bottom:8px;text-transform:uppercase;letter-spacing:.06em}
table{width:100%;border-collapse:collapse}
th{font-size:10px;color:#8899aa;text-transform:uppercase;letter-spacing:.07em;padding:7px 10px;text-align:left;border-bottom:1px solid rgba(255,255,255,.07)}
td{padding:9px 10px;font-size:11px;color:#8899aa;border-bottom:1px solid rgba(255,255,255,.03);vertical-align:top}
.ttxt{color:#f0f4f8;font-weight:600;font-size:12px}
.src{font-size:10px;color:#4a5568;margin-top:3px}
.chip{display:inline-block;padding:2px 9px;border-radius:12px;font-size:10px;font-weight:600}
.bull{background:rgba(16,185,129,.15);color:#10b981}
.bear{background:rgba(244,63,94,.12);color:#f43f5e}
.neut{background:rgba(74,85,104,.25);color:#8899aa}
.high{background:rgba(244,63,94,.15);color:#f43f5e}
.mid{background:rgba(245,158,11,.15);color:#f59e0b}
.low{background:rgba(59,130,246,.12);color:#3b82f6}
.geo{background:rgba(139,92,246,.15);color:#8b5cf6}
.metric{background:rgba(255,255,255,.03);border-radius:8px;padding:12px;text-align:center;display:inline-block;min-width:120px;margin:4px}
.mlbl{font-size:10px;color:#8899aa;text-transform:uppercase;letter-spacing:.07em;margin-bottom:5px}
.mbig{font-size:26px;font-weight:700;font-family:monospace}
.alink{display:inline-block;padding:3px 9px;border-radius:6px;font-size:10px;background:rgba(59,130,246,.15);color:#3b82f6;text-decoration:none}
.footer{text-align:center;font-size:10px;color:#4a5568;margin-top:14px;padding-top:12px;border-top:1px solid rgba(255,255,255,.04)}
.note{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);border-radius:8px;padding:10px 14px;font-size:11px;color:#f59e0b;margin-bottom:12px}
.rekomen{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.2);border-radius:8px;padding:12px 16px;font-size:13px;font-weight:600;color:#10b981;margin-bottom:12px;text-align:center}
"""

def _chip_dampak(d):
    if d == 'Tinggi': return '<span class="chip high">🔴 Tinggi</span>'
    if d == 'Sedang': return '<span class="chip mid">🟡 Sedang</span>'
    return '<span class="chip low">🟢 Rendah</span>'

def _chip_sen(s):
    if s == 'Bullish': return '<span class="chip bull">▲ Bullish</span>'
    if s == 'Bearish': return '<span class="chip bear">▼ Bearish</span>'
    return '<span class="chip neut">→ Netral</span>'

# ─── EMAIL BUILDER 1: KALENDER ────────────────────────────────────────────────
def build_email_kalender(kal):
    events = kal.get('hari_ini', [])
    catatan_html = f'<div class="note">⚠️ {kal["catatan"]}</div>' if kal.get('catatan') else ''

    rows = ''
    for e in events:
        lbl = e.get('tanggal_label', 'Hari Ini')
        lbl_color = '#f59e0b' if lbl != 'Hari Ini' else '#8899aa'
        event_display = e.get('event_id', e['event'])
        event_en = e['event'] if e.get('event_id', '') != e['event'] else ''
        rows += f"""<tr>
<td style="color:#f0f4f8;font-weight:700;white-space:nowrap;font-family:monospace">
  {e['waktu']}<br><span style="font-size:9px;color:{lbl_color}">{lbl}</span>
</td>
<td>
  <div class="ttxt">{event_display}</div>
  {'<div style="font-size:10px;color:#4a5568">'+event_en+'</div>' if event_en else ''}
  <div style="font-size:10px;color:#4a5568;margin-top:3px">{e.get('dampak_saham','')}</div>
</td>
<td>{_chip_dampak(e['dampak'])}</td>
<td style="font-family:monospace;color:#10b981">{e['aktual']}</td>
<td style="font-family:monospace;color:#8899aa">{e['perkiraan']}</td>
<td style="font-family:monospace;color:#8899aa">{e['sebelumnya']}</td>
</tr>"""

    if not rows:
        rows = '<tr><td colspan="6" style="text-align:center;padding:22px;color:#4a5568">Tidak ada event ekonomi USD — pasar lebih tenang</td></tr>'

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>{_CSS}</style></head>
<body><div class="wrap">
<div class="hdr">
  <div class="htitle">📅 Kalender Ekonomi Saham AS</div>
  <div class="hsub">{kal.get('hari_ini_label','')} &nbsp;·&nbsp; Diperbarui: {kal.get('jam_update','')}</div>
</div>
<div class="body">
  {catatan_html}
  <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px">
    <div class="metric"><div class="mlbl">Total Event USD</div><div class="mbig" style="color:#f59e0b">{kal.get('total_event',0)}</div></div>
    <div class="metric"><div class="mlbl">Dampak Tinggi</div><div class="mbig" style="color:#f43f5e">{kal.get('event_tinggi',0)}</div></div>
    <div class="metric"><div class="mlbl">Zona Waktu</div><div style="font-size:15px;font-weight:700;color:#3b82f6;margin-top:4px">ET = WIB−12</div></div>
  </div>
  <div class="sec">
    <div class="stitle">🗓 Event Ekonomi USD (Bahasa Indonesia)</div>
    <table><thead><tr>
      <th>Waktu ET</th><th>Event</th><th>Dampak</th>
      <th>Aktual</th><th>Perkiraan</th><th>Sebelumnya</th>
    </tr></thead><tbody>{rows}</tbody></table>
  </div>
  <div class="sec" style="font-size:11px;color:#8899aa;line-height:1.9">
    <div class="stitle">📌 Panduan Membaca Kalender</div>
    <div>🔴 <b style="color:#f43f5e">Dampak Tinggi</b> — NFP, CPI, FOMC: <em>hindari trade besar sebelum rilis</em></div>
    <div>🟡 <b style="color:#f59e0b">Dampak Sedang</b> — Retail Sales, Jobless Claims: perhatikan arah trend</div>
    <div>🟢 <b style="color:#3b82f6">Dampak Rendah</b> — Data minor: dampak terbatas</div>
    <div style="margin-top:8px;color:#10b981">✅ <b>Aktual &gt; Perkiraan</b> = umumnya bullish untuk S&P 500 &amp; NASDAQ</div>
    <div style="color:#f59e0b">⚠️ <b>Aktual &lt; Perkiraan</b> = umumnya bearish — waspadai volatilitas</div>
  </div>
</div>
<div class="footer">StockJournal Pro v2.3 &nbsp;·&nbsp; Dikirim otomatis jam 07:00 WIB &nbsp;·&nbsp; {kal.get('tanggal','')}</div>
</div></body></html>"""

# ─── EMAIL BUILDER 2: SENTIMEN ────────────────────────────────────────────────
def build_email_sentimen(sen):
    ring   = sen.get('ringkasan', {})
    idx    = sen.get('indeks', {})
    panas  = sen.get('saham_panas', {})
    berita = sen.get('berita', [])
    rekomen = sen.get('rekomendasi_pasar', '')

    overall = ring.get('overall', 'Netral')
    skor    = ring.get('skor_rata', 0)
    ov_col  = '#10b981' if overall == 'Bullish' else '#f43f5e' if overall == 'Bearish' else '#8899aa'
    ov_icon = '▲' if overall == 'Bullish' else '▼' if overall == 'Bearish' else '→'

    idx_rows = ''
    for key, label in [('sp500','S&P 500'),('nasdaq','NASDAQ'),('dow_jones','Dow Jones')]:
        d = idx.get(key, {})
        s = d.get('skor', 0)
        s_col = '#10b981' if s > 0 else '#f43f5e' if s < 0 else '#8899aa'
        idx_rows += f"""<tr>
<td style="color:#f0f4f8;font-weight:700">{label}</td>
<td>{_chip_sen(d.get('sentimen','Netral'))}</td>
<td style="font-family:monospace;color:{s_col}">{'+' if s>0 else ''}{s:.1f}</td>
<td style="color:#8899aa">{d.get('jumlah_berita',0)} berita</td>
</tr>"""

    bull_chips = ''.join(
        f'<span class="chip bull" style="margin:3px;display:inline-block">{s["ticker"]} +{s["skor"]}</span>'
        for s in panas.get('bullish', []))
    bear_chips = ''.join(
        f'<span class="chip bear" style="margin:3px;display:inline-block">{s["ticker"]} {s["skor"]}</span>'
        for s in panas.get('bearish', []))

    news_rows = ''
    for a in berita[:30]:
        s  = a.get('sentimen', 'Netral')
        sk = a.get('skor', 0)
        sk_col = '#10b981' if sk > 0 else '#f43f5e' if sk < 0 else '#8899aa'
        url = a.get('url', '')
        lnk = f'<a href="{url}" class="alink" target="_blank">Baca ↗</a>' if url and url != '#' else ''
        judul_show = a.get('judul_id') or a['judul']
        judul_en   = a['judul'] if a.get('judul_id', '') != a['judul'] else ''
        news_rows += f"""<tr>
<td style="width:75px">{_chip_sen(s)}</td>
<td>
  <div class="ttxt">{judul_show[:130]}</div>
  {'<div style="font-size:10px;color:#4a5568;margin-top:2px">'+judul_en[:110]+'</div>' if judul_en else ''}
  <div class="src">{a['sumber']} · {a['asal']} · {a.get('waktu','')[:10]}</div>
  {lnk}
</td>
<td style="font-family:monospace;color:{sk_col};white-space:nowrap">{'+' if sk>0 else ''}{sk}</td>
</tr>"""

    rekomen_html = ''
    if rekomen:
        col = '#10b981' if 'BELI' in rekomen else '#f43f5e' if 'JUAL' in rekomen else '#f59e0b'
        rekomen_html = f'<div class="rekomen" style="color:{col};border-color:{col}22">🎯 {rekomen}</div>'

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>{_CSS}</style></head>
<body><div class="wrap">
<div class="hdr">
  <div class="htitle">📊 Analisis Sentimen Pasar Saham AS</div>
  <div class="hsub">Diperbarui: {sen.get('jam_update','')} &nbsp;·&nbsp; {ring.get('total_berita',0)} berita dianalisis</div>
</div>
<div class="body">
  {rekomen_html}
  <div class="sec" style="text-align:center">
    <div class="mlbl">Sentimen Pasar Keseluruhan</div>
    <div style="font-size:38px;font-weight:700;color:{ov_col};font-family:monospace;margin:8px 0">{ov_icon} {overall}</div>
    <div style="font-size:12px;color:#8899aa">Skor rata-rata: <b style="color:{ov_col}">{'+' if skor>0 else ''}{skor:.2f}</b></div>
    <div style="display:flex;justify-content:center;flex-wrap:wrap;margin-top:12px">
      <div class="metric"><div class="mlbl">Bullish</div><div class="mbig" style="color:#10b981">{ring.get('bullish_pct',0)}%</div></div>
      <div class="metric"><div class="mlbl">Bearish</div><div class="mbig" style="color:#f43f5e">{ring.get('bearish_pct',0)}%</div></div>
      <div class="metric"><div class="mlbl">Netral</div><div class="mbig" style="color:#8899aa">{ring.get('netral_pct',0)}%</div></div>
    </div>
  </div>
  <div class="sec">
    <div class="stitle">📈 Sentimen Per Indeks Amerika</div>
    <table><thead><tr><th>Indeks</th><th>Sentimen</th><th>Skor</th><th>Berita</th></tr></thead>
    <tbody>{idx_rows}</tbody></table>
  </div>
  <div class="sec">
    <div class="stitle">🔥 Saham Paling Dibicarakan</div>
    <div style="margin-bottom:10px"><div style="font-size:10px;color:#8899aa;margin-bottom:6px">BULLISH ▲</div>{bull_chips or '<span style="color:#4a5568">—</span>'}</div>
    <div><div style="font-size:10px;color:#8899aa;margin-bottom:6px">BEARISH ▼</div>{bear_chips or '<span style="color:#4a5568">—</span>'}</div>
  </div>
  <div class="sec">
    <div class="stitle">📰 30 Berita + Sentimen (Bahasa Indonesia)</div>
    <table><thead><tr><th style="width:80px">Sentimen</th><th>Berita</th><th>Skor</th></tr></thead>
    <tbody>{news_rows}</tbody></table>
  </div>
</div>
<div class="footer">StockJournal Pro v2.3 &nbsp;·&nbsp; Dikirim otomatis jam 07:00 WIB &nbsp;·&nbsp; {sen.get('tanggal','')}</div>
</div></body></html>"""

# ─── EMAIL BUILDER 3: GEOPOLITIK ──────────────────────────────────────────────
def build_email_geopolitik(geo):
    berita = geo.get('berita', [])
    items  = ''
    for a in berita[:30]:
        d_col  = '#10b981' if a['dampak_pasar']=='Positif' else '#f43f5e' if a['dampak_pasar']=='Negatif' else '#8899aa'
        d_icon = '▲' if a['dampak_pasar']=='Positif' else '▼' if a['dampak_pasar']=='Negatif' else '→'
        url    = a.get('url', '')
        lnk    = f'<a href="{url}" class="alink" style="display:inline-block;margin-top:6px" target="_blank">Baca ↗</a>' if url and url != '#' else ''
        judul_show     = a.get('judul_id') or a['judul']
        judul_en       = a['judul'] if a.get('judul_id', '') != a['judul'] else ''
        ringkasan_show = a.get('ringkasan_id') or a.get('ringkasan', '')
        items += f"""<div style="background:#0a1628;border:1px solid rgba(255,255,255,.06);border-radius:9px;padding:12px 14px;margin-bottom:10px">
  <div style="display:flex;gap:8px;align-items:center;margin-bottom:7px;flex-wrap:wrap">
    <span class="chip geo">{a.get('kategori','Pasar Saham AS')}</span>
    <span style="font-size:10px;color:{d_col}">{d_icon} Dampak {a['dampak_pasar']}</span>
    <span style="font-size:10px">{_chip_sen(a.get('sentimen','Netral'))}</span>
  </div>
  <div class="ttxt" style="margin-bottom:4px">{judul_show[:160]}</div>
  {'<div style="font-size:10px;color:#4a5568;margin-bottom:4px">'+judul_en[:140]+'</div>' if judul_en else ''}
  <div style="font-size:11px;color:#8899aa;line-height:1.6;margin-bottom:5px">{ringkasan_show[:240]}</div>
  <div style="font-size:10px;color:#4a5568">{a['sumber']} · {a['asal']} · {a.get('waktu','')[:10]}</div>
  {lnk}
</div>"""

    if not items:
        items = '<div style="text-align:center;padding:24px;color:#4a5568">Tidak ada berita geopolitik/pasar signifikan hari ini</div>'

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>{_CSS}</style></head>
<body><div class="wrap">
<div class="hdr">
  <div class="htitle">🌍 Geopolitik &amp; Pasar Saham Amerika</div>
  <div class="hsub">Diperbarui: {geo.get('jam_update','')} &nbsp;·&nbsp; {geo.get('total_berita',0)} berita teridentifikasi</div>
</div>
<div class="body">
  <div class="sec" style="font-size:11px;color:#8899aa;line-height:1.8">
    ⚠️ Mencakup isu geopolitik dan berita pasar saham AS yang dapat mempengaruhi
    <b style="color:#f0f4f8">S&amp;P 500, NASDAQ, Dow Jones, sektor energi, teknologi, dan keuangan</b>.
  </div>
  <div class="sec">
    <div class="stitle">🌐 Berita Geopolitik &amp; Pasar AS ({min(len(berita),30)} dari {geo.get('total_berita',0)}) — Bahasa Indonesia</div>
    {items}
  </div>
</div>
<div class="footer">StockJournal Pro v2.3 &nbsp;·&nbsp; Dikirim otomatis jam 07:00 WIB &nbsp;·&nbsp; {geo.get('tanggal','')}</div>
</div></body></html>"""

# ─── EMAIL SENDER ─────────────────────────────────────────────────────────────
def send_email(cfg, subject, html_body):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = cfg['sender']
        msg['To']      = cfg['recipient']
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        with smtplib.SMTP(cfg['smtp_host'], cfg['smtp_port'], timeout=30) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(cfg['sender'], cfg['password'])
            srv.sendmail(cfg['sender'], cfg['recipient'], msg.as_string())
        log.info(f'  ✉ Terkirim: {subject}')
        return True
    except smtplib.SMTPAuthenticationError:
        log.error('SMTP Auth gagal! Pastikan pakai Gmail App Password (bukan password biasa).')
    except Exception as e:
        log.error(f'Gagal kirim "{subject}": {e}')
    return False

# ─── MAIN ORCHESTRATOR ────────────────────────────────────────────────────────
def run_digest():
    log.info('═' * 64)
    log.info(f'STOCK DIGEST v2.3 MULAI — {fmt_wib()}')
    log.info('═' * 64)

    cfg = load_config()
    if not cfg:
        log.error('Konfigurasi email tidak valid.')
        return

    articles = fetch_all_news()
    if len(articles) < 5:
        log.warning(f'Hanya {len(articles)} berita — periksa koneksi internet')

    translate_articles(articles)

    cal_events, weekend_mode, cal_note = fetch_economic_calendar()

    log.info('── Menyiapkan analisis ──')
    kalender   = prepare_kalender(cal_events, weekend_mode, cal_note)
    sentimen   = prepare_sentimen(articles)
    geopolitik = prepare_geopolitik(articles)

    log.info(f"  Kalender:    {kalender['total_event']} event USD")
    log.info(f"  Sentimen:    {sentimen['ringkasan']['total_berita']} berita → {sentimen['ringkasan']['overall']}")
    log.info(f"  Geopolitik:  {geopolitik['total_berita']} berita")
    log.info(f"  Rekomendasi: {sentimen['rekomendasi_pasar'][:60]}...")

    log.info('── Menyimpan data ──')
    save_json_files(kalender, sentimen, geopolitik)
    generate_js_data(kalender, sentimen, geopolitik)

    log.info('── Mengirim email ──')
    today = today_str()
    send_email(cfg, f'📅 Kalender Ekonomi Saham AS — {today}',     build_email_kalender(kalender))
    time.sleep(2)
    send_email(cfg, f'📊 Analisis Sentimen Pasar Saham — {today}', build_email_sentimen(sentimen))
    time.sleep(2)
    send_email(cfg, f'🌍 Geopolitik & Pasar Saham AS — {today}',   build_email_geopolitik(geopolitik))

    log.info('═' * 64)
    log.info(f'SELESAI — {fmt_wib()}')
    log.info('═' * 64)

# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
def main():
    import argparse
    p = argparse.ArgumentParser(description='Stock News Digest v2.3 — Analisis Saham Otomatis')
    p.add_argument('--run-now', action='store_true', help='Jalankan digest sekarang (skip jadwal)')
    p.add_argument('--setup',   action='store_true', help='Buat ulang config_email.ini')
    args = p.parse_args()

    if args.setup:
        create_default_config()
        print(f'\nConfig dibuat: {CONFIG_FILE}')
        return

    if args.run_now:
        run_digest()
        return

    schedule.every().day.at('07:00').do(run_digest)
    log.info('Scheduler aktif — menunggu 07:00 setiap hari')
    log.info('Ctrl+C untuk berhenti | --run-now untuk jalankan sekarang\n')
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == '__main__':
    main()
