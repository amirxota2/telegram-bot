import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


class GameUPProvider:
    BASE_URL = "https://gameup.ir"

    GENRE_LABELS = ("ژانر", "ژانرها", "سبک", "genre", "genres")
    DEVELOPER_LABELS = ("سازنده", "توسعه دهنده", "توسعه‌دهنده", "استودیو")
    PUBLISHER_LABELS = ("ناشر",)
    DATE_LABELS = ("تاریخ انتشار", "تاریخ عرضه", "تاریخ ریلیز", "انتشار")

    GENRE_MAP = {
        "استراتژیک": "strategic",
        "اکشن": "action",
        "ماجراجویی": "adventure",
        "مخفی کاری": "stealth",
        "نقش آفرینی": "rpg",
        "تیراندازی - شوتر": "shooter",
        "پلتفرمر": "platformer",
        "پازل": "puzzle",
        "مترویدوانیا": "metroidvania",
        "ترسناک": "horror",
        "رانندگی": "racing",
        "شبیه سازی": "simulation",
        "علمی تخیلی": "science_fiction",
        "بازی مستقل": "indie",
        "بقا": "survival",
        "تاکتیکال": "tactical",
        "پارتی گیمز": "Party_Games",
        "اکشن ماجراجویی": "action_adventure",
        "ورزشی": "sport",
        "جهان باز": "open_world",
    }

    # فقط بازی‌های PC. اگر macOS/Linux هم می‌خواهید اضافه کنید.
    PC_PLATFORMS = {"Windows"}

    PLATFORM_MAP = {
        "بازی اندروید": "Android",
        "اندروید": "Android",
        "android": "Android",
        "بازی ویندوز": "Windows",
        "ویندوز": "Windows",
        "windows": "Windows",
        "بازی آیفون": "iOS",
        "آیفون": "iOS",
        "ios": "iOS",
        "macos": "macOS",
        "linux": "Linux",
        "پلی استیشن": "PlayStation",
        "playstation": "PlayStation",
        "xbox": "Xbox",
        "نینتندو": "Nintendo",
        "nintendo": "Nintendo",
    }

    def __init__(self, timeout=15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    # ---------------------------------------------------------
    # HTTP
    # ---------------------------------------------------------

    def _get(self, url):
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response

    # ---------------------------------------------------------
    # Text / URL helpers
    # ---------------------------------------------------------

    def _clean_text(self, value):
        if not value:
            return ""
        value = str(value)
        for ch in ("\u200c", "\u200b", "\ufeff"):
            value = value.replace(ch, "")
        value = value.replace("\xa0", " ")
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _norm_label(self, value):
        """برای مقایسه label ها: بدون نقطه‌دو‌نقطه، فاصله و حروف بزرگ."""
        value = self._clean_text(value).strip(" :：")
        return value.casefold()

    def _is_label(self, text, labels):
        return self._norm_label(text) in {self._norm_label(x) for x in labels}

    def _normalize_game_url(self, url):
        if not url:
            return ""
        url = urljoin(self.BASE_URL, url)
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{path}".lower()

    def _split_values(self, text):
        parts = re.split(r"[،,/|؛;]+", text)
        return [self._clean_text(p) for p in parts if self._clean_text(p)]

    # ---------------------------------------------------------
    # Labeled fields (aside.gametag)
    # ---------------------------------------------------------

    def _extract_info_fields(self, soup):
        """
        همه‌ی li های aside.gametag را به صورت
        {"label": ..., "value": ..., "links": [...]} برمی‌گرداند.
        """
        fields = []

        for li in soup.select("aside.gametag li"):
            full = self._clean_text(li.get_text(" ", strip=True))
            if not full:
                continue

            attr = self._clean_text(li.get("data-attr", ""))
            links = [
                self._clean_text(a.get_text(" ", strip=True))
                for a in li.select("a")
            ]
            links = [x for x in links if x]

            label = ""
            value = full

            if attr:
                label = attr
                if full.startswith(attr):
                    value = self._clean_text(full[len(attr):].lstrip(" :："))
            elif re.search(r"[:：]", full):
                left, right = re.split(r"[:：]", full, maxsplit=1)
                label = self._clean_text(left)
                value = self._clean_text(right)

            fields.append({"label": label, "value": value, "links": links})

        return fields

    def _find_field(self, fields, labels):
        for field in fields:
            if field["label"] and self._is_label(field["label"], labels):
                return field
        return None

    def _field_values(self, field, labels):
        if not field:
            return []
        raw = field["links"] or self._split_values(field["value"])
        return [
            v for v in raw
            if v and not self._is_label(v, labels)
        ]

    # ---------------------------------------------------------
    # Description
    # ---------------------------------------------------------

    def _extract_description(self, soup):
        for selector in (".gamecontent", "#overview"):
            element = soup.select_one(selector)
            if element:
                return self._clean_text(element.get_text(" ", strip=True))
        return ""

    # ---------------------------------------------------------
    # Rating
    # ---------------------------------------------------------

    def _extract_rating(self, soup):
        for selector in (
            ".reviewcount i",
            ".bigreview i",
            ".reviewcount",
            ".bigreview",
        ):
            element = soup.select_one(selector)
            if not element:
                continue
            text = self._clean_text(element.get_text(" ", strip=True))
            match = re.search(r"(\d+(?:\.\d+)?)", text)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass

        meta = soup.select_one('meta[itemprop="ratingValue"]')
        if meta:
            try:
                return float(meta.get("content"))
            except (ValueError, TypeError):
                pass

        return None

    # ---------------------------------------------------------
    # Platforms
    # ---------------------------------------------------------

    def _match_platform(self, text):
        normalized = self._clean_text(text).casefold()
        for key, value in self.PLATFORM_MAP.items():
            if key.casefold() in normalized:
                return value
        return None

    def _extract_platforms(self, soup):
        platforms = []

        for element in soup.select("aside.gametag li.plat label.devices"):
            found = self._match_platform(element.get_text(" ", strip=True))
            if found and found not in platforms:
                platforms.append(found)

        if not platforms:
            for element in soup.select('li.plat[data-attr="پلتفرم"]'):
                found = self._match_platform(
                    element.get_text(" ", strip=True)
                )
                if found and found not in platforms:
                    platforms.append(found)

        return platforms

    # ---------------------------------------------------------
    # Genres (فقط از خود صفحه بازی - بدون درخواست اضافی)
    # ---------------------------------------------------------

    def _extract_direct_genres(self, soup, fields=None):
        """
        برمی‌گرداند: (genres, source)
        source یکی از: "gametag" | "label_sibling" | "links" | "jsonld" | "none"
        label «ژانر» هرگز به عنوان مقدار ذخیره نمی‌شود.
        """
        if fields is None:
            fields = self._extract_info_fields(soup)

        genres = []

        def add(text):
            text = self._clean_text(text)
            if not text or self._is_label(text, self.GENRE_LABELS):
                return
            if text not in genres:
                genres.append(text)

        # روش 1: li با label ژانر در aside.gametag
        field = self._find_field(fields, self.GENRE_LABELS)
        for value in self._field_values(field, self.GENRE_LABELS):
            add(value)
        if genres:
            return genres, "gametag"

        # روش 2: المانی که متنش دقیقا «ژانر» است (مثل div.tagbox > b)
        # مقدار ممکن است داخل همان container یا در المان بعدی باشد.
        # منوی ژانرهای بالای سایت (dropdown) نادیده گرفته می‌شود.
        def collect(el, any_link=False):
            if not hasattr(el, "select"):
                return
            sel = "a" if any_link else (
                'a[href*="genre="], a[href*="/genres/"]'
            )
            for link in el.select(sel):
                add(link.get_text(" ", strip=True))

        for node in soup.find_all(
            string=lambda s: s and self._is_label(s, self.GENRE_LABELS)
        ):
            label_el = node.parent
            if (
                not label_el
                or label_el.find_parent(["nav", "footer", "header"])
                or label_el.find_parent(class_=re.compile("dropdown"))
            ):
                continue

            container = label_el.parent
            if not container:
                continue

            collect(container, any_link=True)

            if not genres:
                for sib in label_el.next_siblings:
                    text = (
                        sib.get_text(" ", strip=True)
                        if hasattr(sib, "get_text")
                        else str(sib)
                    )
                    for part in self._split_values(text):
                        add(part)
                    if genres:
                        break

            if not genres:
                checked = 0
                for sib in container.next_siblings:
                    if getattr(sib, "name", None) is None:
                        continue
                    collect(sib)
                    checked += 1
                    if genres or checked >= 2:
                        break

            if genres:
                return genres, "label_sibling"

        # روش 3: لینک ژانر داخل ناحیه اصلی بازی (نه منو/فوتر)
        area = soup.select_one("#overview") or soup.select_one("aside.gametag")
        if area:
            for a in area.select(
                'a[href*="/genres/"], a[href*="genre="]'
            ):
                if a.find_parent(["nav", "footer", "header"]):
                    continue
                add(a.get_text(" ", strip=True))
            if genres:
                return genres, "links"

        # روش 4: JSON-LD
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
            except (ValueError, TypeError):
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                g = item.get("genre")
                if isinstance(g, str):
                    for part in self._split_values(g):
                        add(part)
                elif isinstance(g, list):
                    for x in g:
                        add(str(x))
            if genres:
                return genres, "jsonld"

        return [], "none"

    # ---------------------------------------------------------
    # Genre index (فقط برای Sync - هرگز در درخواست کاربر صدا نزنید)
    # ---------------------------------------------------------

    def fetch_genre_list(self):
        """
        لیست واقعی ژانرها را از منوی صفحه اصلی می‌خواند:
        [(نام فارسی, slug), ...]. اگر نشد از GENRE_MAP استفاده می‌کند.
        """
        genres = []
        try:
            soup = BeautifulSoup(self._get(self.BASE_URL + "/").text,
                                 "html.parser")
            for a in soup.select('a[href*="/search?genre="]'):
                m = re.search(r"genre=([^&#]+)", a["href"])
                name = self._clean_text(a.get_text(" ", strip=True))
                if m and name and (name, m.group(1)) not in genres:
                    genres.append((name, m.group(1)))
        except requests.RequestException:
            pass

        return genres or list(self.GENRE_MAP.items())

    def build_genre_index(self, max_pages_per_genre=5, delay=0.3):
        """
        فقط برای Sync (هرگز موقع درخواست کاربر صدا نزنید).
        هر ژانر را با /search?genre=<slug> (و pagination) یک بار اسکن
        می‌کند و {normalized_game_url: [genre_name, ...]} می‌سازد.
        الگوی pagination (&page=N) حدسی است؛ اگر صفحه دوم همان نتایج
        صفحه اول را داد، خودش متوقف می‌شود.
        """
        index = {}

        for genre_name, slug in self.fetch_genre_list():
            seen_in_genre = set()

            for page in range(1, max_pages_per_genre + 1):
                url = f"{self.BASE_URL}/search?genre={slug}"
                if page > 1:
                    url += f"&page={page}"

                try:
                    soup = BeautifulSoup(self._get(url).text, "html.parser")
                except requests.RequestException:
                    break

                links = set()
                for a in soup.select('a[href*="/game/"]'):
                    if a.find_parent(["nav", "footer", "header"]):
                        continue
                    norm = self._normalize_game_url(a["href"])
                    if norm:
                        links.add(norm)

                new_links = links - seen_in_genre
                if not new_links:
                    break

                seen_in_genre |= new_links
                for link in new_links:
                    lst = index.setdefault(link, [])
                    if genre_name not in lst:
                        lst.append(genre_name)

                print(
                    f"[GameUP][sync] {genre_name} p{page}: "
                    f"{len(new_links)} games",
                    flush=True,
                )
                time.sleep(delay)

        return index

    def genres_from_index(self, url, index):
        return list(index.get(self._normalize_game_url(url), []))

    # ---------------------------------------------------------
    # Image
    # ---------------------------------------------------------

    def _extract_image(self, soup):
        for selector in (
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
        ):
            element = soup.select_one(selector)
            if element:
                content = element.get("content")
                if content:
                    return urljoin(self.BASE_URL, content)

        image = soup.select_one(".fullgamebox img")
        if image:
            src = image.get("src") or image.get("data-src")
            if src:
                return urljoin(self.BASE_URL, src)

        return ""

    # ---------------------------------------------------------
    # Release date
    # ---------------------------------------------------------

    def _extract_release_date(self, soup, fields):
        field = self._find_field(fields, self.DATE_LABELS)
        if field and field["value"]:
            return field["value"]

        for selector in (
            '[itemprop="datePublished"]',
            'meta[property="article:published_time"]',
        ):
            element = soup.select_one(selector)
            if not element:
                continue
            value = self._clean_text(
                element.get("content") or element.get_text(" ", strip=True)
            )
            if value:
                return value

        return ""

    # ---------------------------------------------------------
    # Company
    # ---------------------------------------------------------

    def _extract_company(self, soup, fields):
        developer = ""
        publisher = ""

        dev_field = self._find_field(fields, self.DEVELOPER_LABELS)
        if dev_field:
            developer = (
                ", ".join(dev_field["links"]) if dev_field["links"]
                else dev_field["value"]
            )

        pub_field = self._find_field(fields, self.PUBLISHER_LABELS)
        if pub_field:
            publisher = (
                ", ".join(pub_field["links"]) if pub_field["links"]
                else pub_field["value"]
            )

        # fallback: فقط اگر label ای پیدا نشد، ناحیه گیم را با regex بگرد
        if not developer or not publisher:
            area = soup.select_one("aside.gametag") or soup.select_one(
                "#overview"
            )
            text = self._clean_text(
                area.get_text(" ", strip=True) if area else ""
            )

            if not developer:
                m = re.search(
                    r"(?:سازنده|توسعه دهنده)\s*[:：]\s*([^|،:：]+)", text
                )
                if m:
                    developer = self._clean_text(m.group(1))

            if not publisher:
                m = re.search(r"ناشر\s*[:：]\s*([^|،:：]+)", text)
                if m:
                    publisher = self._clean_text(m.group(1))

        return developer, publisher

    # ---------------------------------------------------------
    # Debug
    # ---------------------------------------------------------

    def debug_fields(self, url):
        soup = BeautifulSoup(self._get(url).text, "html.parser")
        aside = soup.select_one("aside.gametag")
        print("aside.gametag:", "FOUND" if aside else "NOT FOUND")
        if aside:
            print(aside.prettify())
        print("\n--- parsed fields ---")
        for f in self._extract_info_fields(soup):
            print(f)

        # هر جای صفحه که این کلمات آمده، HTML اطرافش را چاپ کن
        keywords = (
            list(self.GENRE_LABELS)
            + list(self.DEVELOPER_LABELS)
            + list(self.PUBLISHER_LABELS)
            + list(self.DATE_LABELS)
        )
        print("\n--- keyword context ---")
        shown = set()
        for kw in keywords:
            for node in soup.find_all(
                string=lambda t, kw=kw: t and kw in t
            ):
                parent = node.parent
                if not parent or parent.name in ("script", "style", "title"):
                    continue
                box = parent.parent or parent
                key = id(box)
                if key in shown:
                    continue
                shown.add(key)
                html = box.prettify()
                print(f"\n[keyword: {kw}] <{parent.name}> in <{box.name}>")
                print(html[:1200])
        if not shown:
            print("هیچ کلمه کلیدی پیدا نشد.")

    # ---------------------------------------------------------
    # Game details
    # ---------------------------------------------------------

    def get_game_details(
        self,
        url,
        use_genre_fallback=False,
        pc_only=False,
    ):
        # use_genre_fallback فقط برای سازگاری با کد قدیمی است و نادیده
        # گرفته می‌شود: اسکن ژانر هرگز در زمان درخواست انجام نمی‌شود.
        #
        # pc_only=True (پیش‌فرض: False): اگر بازی پلتفرم PC نداشته باشد، None برمی‌گردد
        # (در Sync باید این بازی‌ها ذخیره نشوند).
        print(f"[GameUP] Fetching: {url}", flush=True)

        soup = BeautifulSoup(self._get(url).text, "html.parser")

        name = ""
        h1 = soup.select_one("h1")
        if h1:
            name = self._clean_text(h1.get_text(" ", strip=True))

        if not name:
            title = soup.select_one("title")
            if title:
                name = self._clean_text(title.get_text(" ", strip=True))
                name = re.sub(
                    r"^GameUP\s*[›|]\s*", "", name, flags=re.IGNORECASE
                )

        fields = self._extract_info_fields(soup)

        description = self._extract_description(soup)
        rating = self._extract_rating(soup)
        platforms = self._extract_platforms(soup)
        is_pc = bool(set(platforms) & self.PC_PLATFORMS)

        if pc_only and not is_pc:
            print(
                f"[GameUP] Skipped (not a PC game, platforms={platforms}): "
                f"{url}",
                flush=True,
            )
            return None

        genres, genre_source = self._extract_direct_genres(soup, fields)
        image = self._extract_image(soup)
        release_date = self._extract_release_date(soup, fields)
        developer, publisher = self._extract_company(soup, fields)

        if genres:
            print(
                f"[GameUP] Genres ({genre_source}): {genres}", flush=True
            )
        else:
            print(
                "[GameUP] No genre on game page "
                "(will be filled by sync if available).",
                flush=True,
            )

        return {
            "id": url,
            "game_id": url,
            "name": name,
            "title": name,

            "description": description,
            "summary": description,
            "short_description": description[:500],

            "genres": genres,
            "genre": genres,
            "genre_source": genre_source,

            "platforms": platforms,
            "platform": platforms,
            "is_pc": is_pc,

            "rating": rating,

            "cover_url": image,
            "thumbnail": image,
            "image": image,

            "release_date": release_date,

            "developer": developer,
            "publisher": publisher,

            "url": url,
            "game_url": url,
            "gameup_url": url,

            "source": "gameup",
            "provider": "GameUPProvider",
        }

    def get_game(self, url, use_genre_fallback=False, pc_only=False):
        return self.get_game_details(url, pc_only=pc_only)


# -------------------------------------------------------------
# Test
# -------------------------------------------------------------

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    provider = GameUPProvider()

    # استفاده:
    #   python parvit\gameup.py [آدرس بازی]
    #   python parvit\gameup.py [آدرس بازی] --debug
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    url = (
        args[0] if args
        else "https://gameup.ir/game/net.kdt.pojavlaunch.debug/"
    )

    if "--debug" in sys.argv:
        provider.debug_fields(url)
        sys.exit(0)

    if "--index" in sys.argv:
        idx = provider.build_genre_index(max_pages_per_genre=1)
        print("games in index:", len(idx))
        print("this game:", provider.genres_from_index(url, idx))
        sys.exit(0)

    game = provider.get_game_details(url)

    if game is None:
        print("این صفحه بازی PC نیست (یا پلتفرم ویندوز پیدا نشد).")
        print("برای دیدن ساختار صفحه: همین دستور را با --debug اجرا کنید.")
        sys.exit(2)

    print("\n==============================")
    print("NAME:", game["name"])
    print("RATING:", game["rating"])
    print("GENRES:", game["genres"], f"(source: {game['genre_source']})")
    print("PLATFORMS:", game["platforms"])
    print("COVER:", game["cover_url"])
    print("RELEASE DATE:", game["release_date"])
    print("DEVELOPER:", game["developer"])
    print("PUBLISHER:", game["publisher"])
    print("URL:", game["url"])
    print("\nDESCRIPTION:")
    print(game["description"][:1000])
    print("==============================")