import streamlit as st
import feedparser
import requests
import re
import time
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ──────────────────────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ──────────────────────────────────────────────────────────

st.set_page_config(
    page_title="RegionFlow — Хроника дня",
    layout="wide",
    page_icon="📰"
)

MSK = timezone(timedelta(hours=3))

FRESH_WINDOW = 1 * 3600       # 1 час
TOTAL_WINDOW = 12 * 3600      # 12 часов

AUTO_REFRESH = 600            # 10 минут
CACHE_TTL = 600               # кэш на 10 минут

VK_TOKEN = st.secrets.get("VK_TOKEN", "")
APP_URL = "https://regionflow-public.streamlit.app/"

# ──────────────────────────────────────────────────────────
# ИСТОЧНИКИ
# ──────────────────────────────────────────────────────────

OREL_RSS = {
    "МЧС Орловской области": "https://57.mchs.gov.ru/deyatelnost/press-centr/novosti/rss",
    "Прокуратура Орловской области": "https://epp.genproc.gov.ru/web/proc_57/rss",
    "Вести-Орёл": "https://vestiorel.ru/rss.xml",
    "Вечерний Орёл": "https://vechor.ru/rss",
    "Истоки": "https://istoki.tv/rss",
    "Орёлград": "https://orelgrad.ru/feed",
    "Орёл Times": "https://oreltimes.ru/feed",
    "Уездный город (Ливны)": "https://www.uezdny-gorod.ru/rss/",
}

HTML_SOURCES = {
    "Абирег": "https://abireg.ru/orel/news/",
}

VK_CHANNELS = {
    "УМВД по Орловской области": {"screen": "mvd57", "owner_id": -123456},
    "Жесть Орёл в ВК": {"screen": "zhest_orel_57", "owner_id": -123456},
    "Инцидент | Орёл в ВК": {"screen": "orel_onlain", "owner_id": -123456},
    "Интересный город Орел | Орловчане!": {"screen": "interesting_orel", "owner_id": -123456},
    "Орловский областной суд": {"screen": "oreloblsud", "owner_id": -123456},
    "Официальная ВК-страница администрации губернатора и правительства Орловской области": {"screen": "obl_adm_orel", "owner_id": -123456},
    "Правительство Орловской области": {"screen": "orelregion_government", "owner_id": -123456},
    "Мэрия Орла": {"screen": "oreladm", "owner_id": -123456},
    "Орловский областной совет народных депутатов": {"screen": "oblsovet57", "owner_id": -123456},
    "Орловский городской совет народных депутатов": {"screen": "club207317956", "owner_id": -123456},
    "Орловские новости": {"screen": "newsorel", "owner_id": -123456},
    "Орловский вестник | новости Орла": {"screen": "orl_vestnik", "owner_id": -123456},
    "Телеканал «Первый Областной»": {"screen": "1oblastnoi", "owner_id": -123456},
    "ИнфоОрёл": {"screen": "infoorel", "owner_id": -123456},
}

OREL_KEYWORDS = [
    "орёл", "орел", "орлов", "орёл", "орловская область",
    "орловщина", "ливны", "мценск", "орловский", "орловские",
    "орловчан", "орловцам", "орловцев", "орла", "орлу", "орлом", "орле"
]

# ──────────────────────────────────────────────────────────
# ФУНКЦИИ-ПОМОЩНИКИ (очистка заголовков)
# ──────────────────────────────────────────────────────────

EMOJI_PATTERN = re.compile(
    r"[" "\U0001F600-\U0001F64F" "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF" "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0" "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF" "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF" "\U00002600-\U000026FF"
    "\U0000FE00-\U0000FE0F" "]+", flags=re.UNICODE
)

CALL_TO_ACTION_PATTERNS = [
    "подпис", "ставь лайк", "поставь лайк", "лайкни", "лайкните",
    "делай репост", "сделай репост", "репостни",
    "прислать новость", "присылайте новость", "предлагайте новость",
    "читайте нас", "читай нас", "читайте в нашем",
    "жми ", "жмите ", "нажми ", "кликай", "кликните",
    "переходи", "переходите", "ссылка в описании", "ссылка в шапке",
    "расскажите друзьям", "расскажи друзьям", "делись", "делитесь",
    "комментируй", "комментируйте",
    "ставьте ", "ставь ", "голосуй", "голосуйте",
    "не пропусти", "не пропустите", "узнай первым",
    "британские учёные", "эксперты назвали", "эксперты предупредили",
    "реклама", "реклама:", "по вопросам рекламы",
    "💰", "📸", "📹", "📷",
    "скидка", "скидки", "только сегодня", "распродажа", "бесплатно",
    "купить", "купите", "заказать", "закажите",
    "балконы", "остекление", "ремонт квартир", "натяжные потолки",
    "пластиковые окна", "шиномонтаж", "автосервис",
    "маникюр", "педикюр", "шугаринг", "эпиляция",
    "брови", "ресницы", "татуаж",
    "фитнес", "йога", "тренировки", "похудение",
    "гадание", "приворот", "снятие порчи", "экстрасенс",
    "юрист", "адвокат", "бухгалтерские услуги",
    "работа в", "вакансия", "требуются",
    "продам", "продаётся", "куплю",
    "банкротство", "банкрот", "списание долгов",
    "кредитные каникулы", "бесплатная консультация",
    "аванс", "задаток", "предоплата", "рассрочка",
    "лицензия", "сертифицированный",
    "подолог", "стоматолог", "стоматология", "имплантация",
    "косметолог", "косметология", "чистка лица", "пилинг",
    "мезотерапия", "ботокс", "филлеры",
    "массаж", "массажист", "остеопат", "мануальный терапевт",
    "парикмахер", "парикмахерская", "стрижка",
    "окрашивание", "мелирование", "колорист",
    "визажист", "визаж", "макияж", "makeup",
    "ногтевой сервис", "ногтевая студия", "гель-лак", "шеллак",
    "наращивание ногтей", "дизайн ногтей",
    "бровист", "lashmaker", "ламинирование",
    "барбер", "барбершоп",
    "спа", "салон красоты", "студия красоты",
    "predloga_orel_bot",
    "predloga",
]

FEDERAL_MARKERS = [
    "в россии", "в рф", "в госдуме", "госдума", "путин", "президент рф",
    "правительство рф", "минфин", "центробанк", "совет федерации",
    "россияне считают", "россияне стали",
    "вциом", "по данным росстата", "сборная россии", "чемпионат мира", "олимпиада",
    "в мире", "мировой рекорд", "международный", "за рубежом",
    "сша", "китай", "евросоюз", "нато", "оон",
    "курс доллара", "курс евро", "индекс мосбиржи",
]

REGIONAL_FAKE_PATTERNS = [
    "жителям орла рассказали", "жителям орла объяснили",
    "орловцам рассказали", "орловцам объяснили",
    "в орле рассказали", "в орле объяснили",
]

def strip_emoji(text):
    return EMOJI_PATTERN.sub('', text).strip()

def clean_title_display(title):
    title = re.sub(r'\[id\d+\|[^\]]+\]', '', title)
    title = re.sub(r'\[club\d+\|[^\]]+\]', '', title)
    title = re.sub(r'\*\*', '', title)
    title = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', title)
    title = title.replace("[", "").replace("]", "")
    title = re.sub(r'\s+', ' ', title)
    title = strip_emoji(title)
    title = re.sub(r'\.+\s*$', '', title).strip()
    return title

def is_garbage_title(title):
    if not title or len(title.strip()) < 5:
        return True
    clean = strip_emoji(title).lower()
    if not clean or len(clean) < 12:
        return True
    if title.count("!") >= 4:
        return True
    if re.search(r'[\+\s]*[78][\s\-\(]*\d{3}', clean):
        return True
    if re.search(r'\d{10,}', clean):
        return True
    for p in REGIONAL_FAKE_PATTERNS:
        if p in clean:
            return True
    for marker in FEDERAL_MARKERS:
        if marker in clean:
            return True
    for pattern in CALL_TO_ACTION_PATTERNS:
        if pattern in clean:
            return True
    return False

def format_time(timestamp):
    if not timestamp:
        return ""
    try:
        dt = datetime.fromtimestamp(int(timestamp), tz=MSK)
        now_msk = datetime.now(MSK)
        delta_days = (now_msk.date() - dt.date()).days
        months = [
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ]
        if delta_days == 0:
            return dt.strftime("%H:%M")
        elif delta_days == 1:
            return f"вчера {dt.strftime('%H:%M')}"
        else:
            return f"{dt.day} {months[dt.month - 1]} {dt.strftime('%H:%M')}"
    except:
        return ""

# ──────────────────────────────────────────────────────────
# ФУНКЦИИ СБОРА НОВОСТЕЙ
# ──────────────────────────────────────────────────────────

def parse_rss_items(name, url):
    items = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:3]:
            title = entry.get("title", "").strip()
            if title:  # Собираем всё, фильтруем позже
                pub_ts = None
                pub_time = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    pub_ts = pub_dt.timestamp()
                    pub_time = format_time(pub_ts)
                items.append({
                    "title": clean_title_display(title),
                    "link": entry.get("link", ""),
                    "source": name,
                    "time": pub_time,
                    "timestamp": pub_ts
                })
    except:
        pass
    return items

def fetch_vk_channel(screen_name, name, owner_id, session=None):
    items = []
    try:
        url = "https://api.vk.com/method/wall.get"
        params = {
            "owner_id": owner_id,
            "count": 15,
            "access_token": VK_TOKEN,
            "v": "5.131"
        }
        if session:
            response = session.get(url, params=params, timeout=10)
        else:
            response = requests.get(url, params=params, timeout=10)
        wall = response.json()
        if "error" in wall or "response" not in wall or "items" not in wall["response"]:
            return items
        for post in wall["response"]["items"]:
            if post.get("is_pinned") == 1 or post.get("marked_as_ads") == 1:
                continue
            text = post.get("text", "").strip()
            if not text:
                continue
            if "#реклама" in text.lower():
                continue
            lines = text.split("\n")
            raw_title = lines[0].strip() if lines else text[:120]
            if not raw_title:  # Собираем всё, фильтруем позже
                continue
            link = f"https://vk.com/{screen_name}?w=wall{owner_id}_{post['id']}"
            pub_ts = post.get("date", 0)
            pub_time = format_time(pub_ts)
            items.append({
                "title": clean_title_display(raw_title),
                "link": link,
                "source": name,
                "time": pub_time,
                "timestamp": pub_ts
            })
    except:
        pass
    return items

def parse_abireg_html(name, url):
    items = []
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code != 200:
            return items
        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("article")
        if not articles:
            articles = soup.find_all("div", class_=re.compile("news"))
        for article in articles[:5]:
            title_tag = article.find("h2") or article.find("h3") or article.find("a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if not title:
                continue
            if not any(kw in title.lower() for kw in OREL_KEYWORDS):
                continue
            link_tag = article.find("a", href=True)
            link = link_tag["href"] if link_tag else url
            if link and not link.startswith("http"):
                link = "https://abireg.ru" + link
            time_tag = article.find("time")
            pub_ts = None
            pub_time = ""
            if time_tag and time_tag.get("datetime"):
                try:
                    pub_dt = datetime.fromisoformat(time_tag["datetime"].replace("Z", "+00:00"))
                    pub_ts = pub_dt.timestamp()
                    pub_time = format_time(pub_ts)
                except:
                    pass
            if title:  # Собираем всё, фильтруем позже
                items.append({
                    "title": clean_title_display(title),
                    "link": link,
                    "source": name,
                    "time": pub_time,
                    "timestamp": pub_ts
                })
    except:
        pass
    return items

def parse_ksp_news(name, url, session=None):
    items = []
    try:
        months = {
            "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
            "мая": "05", "июня": "06", "июля": "07", "августа": "08",
            "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12"
        }
        for page_num in range(1, 2):  # Только первая страница
            page_url = url if page_num == 1 else f"{url}page{page_num}"
            if session:
                response = session.get(page_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            else:
                response = requests.get(page_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                break
            soup = BeautifulSoup(response.text, "html.parser")
            news_container = soup.find("div", class_="news new")
            if not news_container:
                break
            for li in news_container.find_all("li"):
                news_preview = li.find("div", class_="news-preview")
                if not news_preview:
                    continue
                date_div = news_preview.find("div", class_="date")
                if not date_div:
                    continue
                day_span = date_div.find("span")
                day = day_span.get_text(strip=True) if day_span else ""
                month_year = date_div.get_text(strip=True).replace(day, "").strip()
                date_text = f"{day} {month_year}".strip()
                desc_new = news_preview.find("div", class_="desc-new")
                if not desc_new:
                    continue
                t_new = desc_new.find("div", class_="t-new")
                if not t_new:
                    continue
                link_tag = t_new.find("a", href=True)
                if not link_tag:
                    continue
                title = link_tag.get_text(strip=True)
                link = link_tag["href"]
                if link.startswith("/"):
                    link = "https://ksp-orel.ru" + link
                if not title or len(title) < 10:
                    continue
                sort_date = ""
                if date_text:
                    match = re.search(r'(\d{1,2})\s+([а-я]+)\s+(\d{4})', date_text)
                    if match:
                        sort_date = f"{match.group(3)}-{months.get(match.group(2), '01')}-{match.group(1).zfill(2)}"
                if title:  # Собираем всё, фильтруем позже
                    items.append({
                        "title": clean_title_display(title),
                        "link": link,
                        "source": name,
                        "time": date_text,
                        "timestamp": None,
                        "sort_date": sort_date
                    })
            if len(items) < 3:
                break
    except:
        pass
    return items

# ──────────────────────────────────────────────────────────
# ДЕДУПЛИКАЦИЯ (двухпроходная)
# ──────────────────────────────────────────────────────────

def levenshtein(s1, s2):
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]

def normalize_for_dedup(title):
    title = title.lower().replace("ё", "е")
    title = re.sub(r'[^а-яa-z0-9\s]', ' ', title)
    words = [w for w in title.split() if len(w) >= 3]
    stop = {"в", "на", "по", "под", "из", "для", "к", "у", "о", "и", "или", "а", "но", "об", "обо"}
    words = [w for w in words if w not in stop]
    words.sort()
    return " ".join(words)

def extract_entities(title):
    entities = set()
    numbers = re.findall(r'\d+', title)
    entities.update(numbers)
    words = title.split()
    for word in words:
        if word and word[0].isupper() and len(word) > 1:
            entities.add(word.lower())
    abbreviations = re.findall(r'\b[А-ЯЁA-Z]{2,}\b', title)
    entities.update(a.lower() for a in abbreviations)
    return entities

def entities_intersect(entities1, entities2):
    if not entities1 or not entities2:
        return False
    return bool(entities1 & entities2)

def deduplicate(items, max_diff_minutes_first=60, max_diff_minutes_second=720, max_levenshtein_first=2, max_levenshtein_second=3):
    if not items:
        return items

    sorted_items = sorted(items, key=lambda x: x.get("timestamp", 0) or 0, reverse=True)

    result_first = []
    seen_first = []
    for item in sorted_items:
        title = item.get("title", "")
        ts = item.get("timestamp")
        if not title:
            result_first.append(item)
            continue
        norm = normalize_for_dedup(title)
        is_dup = False
        for seen_title, seen_ts in seen_first:
            if levenshtein(norm, seen_title) <= max_levenshtein_first:
                if ts and seen_ts and abs(ts - seen_ts) <= max_diff_minutes_first * 60:
                    is_dup = True
                    break
        if not is_dup:
            result_first.append(item)
            seen_first.append((norm, ts))

    result_second = []
    seen_second = []
    for item in result_first:
        title = item.get("title", "")
        ts = item.get("timestamp")
        if not title:
            result_second.append(item)
            continue
        norm = normalize_for_dedup(title)
        entities = extract_entities(title)
        is_dup = False
        for seen_title, seen_ts, seen_entities in seen_second:
            if levenshtein(norm, seen_title) <= max_levenshtein_second:
                if ts and seen_ts and abs(ts - seen_ts) <= max_diff_minutes_second * 60:
                    if entities and seen_entities and entities_intersect(entities, seen_entities):
                        is_dup = True
                        break
        if not is_dup:
            result_second.append(item)
            seen_second.append((norm, ts, entities))

    return result_second

# ──────────────────────────────────────────────────────────
# ЗАГРУЗКА НОВОСТЕЙ (с кэшем на 10 минут)
# ──────────────────────────────────────────────────────────

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_news():
    all_items = []
    source_status = {}
    
    session = requests.Session()
    session.headers.update({"User-Agent": "RegionFlow/1.0"})

    def fetch_rss(name, url):
        try:
            items = parse_rss_items(name, url)
            return name, items, "Работает" if items else "Недоступен"
        except:
            return name, [], "Недоступен"

    def fetch_html(name, url):
        try:
            items = parse_abireg_html(name, url)
            return name, items, "Работает" if items else "Недоступен"
        except:
            return name, [], "Недоступен"

    def fetch_ksp():
        try:
            items = parse_ksp_news(
                "Контрольно-счётная палата Орловской области",
                "https://ksp-orel.ru/news/",
                session=session
            )
            return "Контрольно-счётная палата Орловской области", items, "Работает" if items else "Недоступен"
        except:
            return "Контрольно-счётная палата Орловской области", [], "Недоступен"

    def fetch_vk(name, config):
        try:
            items = fetch_vk_channel(
                config["screen"], name, config["owner_id"], session=session
            )
            status = "Работает" if items else "Свежих новостей нет"
            return name, items, status
        except:
            return name, [], "Недоступен"

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = []
        
        for name, url in OREL_RSS.items():
            futures.append(executor.submit(fetch_rss, name, url))
            
        for name, url in HTML_SOURCES.items():
            futures.append(executor.submit(fetch_html, name, url))
            
        futures.append(executor.submit(fetch_ksp))
        
        for name, config in VK_CHANNELS.items():
            futures.append(executor.submit(fetch_vk, name, config))

        for future in as_completed(futures):
            name, items, status = future.result()
            all_items.extend(items)
            source_status[name] = status

    total_raw = len(all_items)
    all_items = [item for item in all_items if not is_garbage_title(item.get("title", ""))]
    all_items = deduplicate(all_items)
    total_clean = len(all_items)

    def sort_key(item):
        ts = item.get("timestamp")
        if ts and isinstance(ts, (int, float)):
            return (ts, "")
        sd = item.get("sort_date", "")
        if sd:
            try:
                dt = datetime.strptime(sd, "%Y-%m-%d").replace(tzinfo=MSK)
                return (dt.timestamp(), "")
            except:
                return (0, "")
        return (0, "")

    all_items.sort(key=sort_key, reverse=True)

    now_ts = datetime.now(MSK).timestamp()
    fresh_cutoff = now_ts - FRESH_WINDOW
    total_cutoff = now_ts - TOTAL_WINDOW

    fresh_count = 0
    total_count = 0
    chrono_items = []

    for item in all_items:
        ts = item.get("timestamp")
        if ts and isinstance(ts, (int, float)):
            if ts >= total_cutoff:
                chrono_items.append(item)
                total_count += 1
                if ts >= fresh_cutoff:
                    fresh_count += 1
        elif item.get("sort_date"):
            try:
                dt = datetime.strptime(item["sort_date"], "%Y-%m-%d").replace(tzinfo=MSK)
                if dt.timestamp() >= total_cutoff:
                    chrono_items.append(item)
                    total_count += 1
            except:
                chrono_items.append(item)
                total_count += 1
        else:
            chrono_items.append(item)
            total_count += 1

    return {
        "chrono_items": chrono_items,
        "total_count": total_clean,
        "fresh_count": fresh_count,
        "total_raw": total_raw,
        "total_clean": total_clean,
        "source_status": source_status,
        "timestamp": datetime.now(MSK).strftime("%d %B %Y, %H:%M MSK")
    }

# ──────────────────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────────────────

if "last_auto_refresh" not in st.session_state:
    st.session_state.last_auto_refresh = time.time()

if time.time() - st.session_state.last_auto_refresh > AUTO_REFRESH:
    st.cache_data.clear()
    st.session_state.last_auto_refresh = time.time()
    st.rerun()

st.title("RegionFlow — Хроника дня")
st.markdown("<p style='font-size: 1.1rem; color: #666;'>Новости Орловской области в хронологическом порядке</p>", unsafe_allow_html=True)

col_btn, col_share = st.columns([1, 1])
with col_btn:
    if st.button("Обновить", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with col_share:
    st.button(
        "Поделиться приложением",
        use_container_width=True,
        on_click=lambda: st.write(f"Ссылка: {APP_URL}")
    )

data = load_news()

st.markdown("""
<style>
.metrics-row {
    display: flex;
    gap: 1rem;
    margin: 1rem 0;
}
.metric-box {
    flex: 1;
    padding: 0.6rem 0.5rem;
    border-radius: 0.5rem;
    background: #f0f2f6;
    text-align: center;
}
.metric-number {
    font-size: 1.2rem;
    font-weight: bold;
    color: #1a1a1a;
}
.metric-label {
    font-size: 0.8rem;
    color: #666;
}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="metrics-row">
    <div class="metric-box">
        <div class="metric-number">{data['fresh_count']}</div>
        <div class="metric-label">Свежих новостей (за час)</div>
    </div>
    <div class="metric-box">
        <div class="metric-number">{data['total_count']}</div>
        <div class="metric-label">Всего за 12 часов</div>
    </div>
    <div class="metric-box">
        <div class="metric-number">{data['total_raw']}</div>
        <div class="metric-label">До фильтрации</div>
    </div>
</div>
""", unsafe_allow_html=True)

st.divider()

if data["chrono_items"]:
    for item in data["chrono_items"]:
        time_str = f"`{item['time']}` " if item.get("time") else ""
        st.markdown(f"{time_str}[{item['title']}]({item['link']}) — *{item['source']}*")
else:
    st.info("Нет новостей за последние 12 часов")

st.divider()
st.caption(f"RegionFlow • (c) Denis Yakovlev, 2026 • Обновлено: {data['timestamp']}")
