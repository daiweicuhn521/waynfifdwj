# -*- coding: utf-8 -*-
"""
评书随身听 www.psmp3.com Spider  —— 优化加载速度版
"""
from base.spider import Spider
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:
    Retry = None

try:
    import cloudscraper
    _HAS_CF = True
except Exception:
    _HAS_CF = False


BASE = "https://www.psmp3.com"
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/119.0.0.0 Mobile Safari/537.36")

HEADERS = {
    "User-Agent": DESKTOP_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
}

PLAY_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Referer": "https://www.psmp3.com/",
    "Accept": "*/*",
}

CATEGORIES = [
    {"type_name": "袁阔成", "type_id": "ykc"},
    {"type_name": "单田芳", "type_id": "stf"},
    {"type_name": "田连元", "type_id": "tly"},
    {"type_name": "刘兰芳", "type_id": "llf"},
    {"type_name": "连丽如", "type_id": "llr"},
    {"type_name": "张少佐", "type_id": "zsz"},
    {"type_name": "田战义", "type_id": "tzy"},
]


# ================= 缓存 =================
class TTLCache:
    __slots__ = ("ttl", "maxsize", "_d", "_lock")

    def __init__(self, ttl=300, maxsize=512):
        self.ttl = ttl
        self.maxsize = maxsize
        self._d = {}
        self._lock = threading.Lock()

    def get(self, key):
        item = self._d.get(key)
        if not item:
            return None
        expire, value = item
        if expire < time.time():
            self._d.pop(key, None)
            return None
        return value

    def set(self, key, value, ttl=None):
        with self._lock:
            if len(self._d) >= self.maxsize:
                # 批量清理最早的一半
                for k in list(self._d.keys())[: self.maxsize // 2]:
                    self._d.pop(k, None)
            self._d[key] = (time.time() + (ttl or self.ttl), value)


# ================= 正则（预编译，避免回溯） =================
RE_ITEM       = re.compile(r'<li class="[^"]*post_list_li[^"]*">(.*?)</li>', re.S)
RE_TITLE_A    = re.compile(r'<h2>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>\s*</h2>', re.S)
RE_PIC        = re.compile(r'<img\s+src="([^"]+)"')
RE_LMNAME     = re.compile(r'<div class="fenli">\s*<a[^>]*>(.*?)</a>\s*</div>', re.S)
RE_TAG        = re.compile(r"<[^>]+>")

RE_H1         = re.compile(r'<h1[^>]*class="[^"]*news_title[^"]*"[^>]*>(.*?)</h1>', re.S)
RE_BOOKPIC    = re.compile(r'<img[^>]+src="(https?://[^"]+no\d+\.jpg)"', re.I)

RE_APLAYER    = re.compile(r'const\s+ap\s*=\s*new\s+APlayer\(\s*\{(.*?)\}\s*\)\s*;', re.S)
RE_AUDIO_ITEM = re.compile(
    r'\{\s*name\s*:\s*"([^"]*)"\s*,\s*artist\s*:\s*"([^"]*)"\s*,\s*url\s*:\s*"([^"]+)"',
    re.S,
)

RE_CANON      = re.compile(r'<link\s+rel="canonical"\s+href="([^"]+)"', re.I)
RE_NEXT       = re.compile(r'<link\s+rel="next"\s+href="([^"]+)"', re.I)
RE_PREV       = re.compile(r'<link\s+rel="prev"\s+href="([^"]+)"', re.I)
RE_PAGE_LINKS = re.compile(
    r'href="(https?://www\.psmp3\.com/[a-z0-9\-]+/[a-z0-9\-]+-\d+\.html)"', re.I
)

RE_LIST_TAIL  = re.compile(r'<a\s+href="([^"]+)"\s*>尾页</a>', re.I)
RE_LIST_NEXT  = re.compile(r'<a\s+href="([^"]+)"\s+class="next">下一页</a>', re.I)


def _clean(s):
    return RE_TAG.sub("", s).strip()


def _abs_url(u, base=BASE):
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return urljoin(base, u)
    return u


class Spider(Spider):
    _list_cache   = TTLCache(ttl=600, maxsize=1024)   # 列表 10 分钟
    _detail_cache = TTLCache(ttl=3600, maxsize=512)   # 详情 1 小时
    _play_cache   = TTLCache(ttl=3600, maxsize=2048)  # 播放 1 小时

    def getName(self):
        return "评书随身听"

    def init(self, extend=""):
        if _HAS_CF:
            self.sess = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
        else:
            self.sess = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=64,
                pool_maxsize=128,
                max_retries=Retry(
                    total=2, backoff_factor=0.2,
                    status_forcelist=(500, 502, 503, 504),
                    allowed_methods=frozenset(["GET", "POST"]),
                ) if Retry else 0,
            )
            self.sess.mount("https://", adapter)
            self.sess.mount("http://", adapter)
        self.sess.headers.update(HEADERS)

        # 复用线程池
        self._pool = ThreadPoolExecutor(max_workers=12)

        # 预热：首次访问首页，让 CF cookie 生效
        try:
            self._get(BASE + "/", timeout=(3, 6))
        except Exception:
            pass

    def isVideoFormat(self, url):
        return any(url.lower().endswith(ext) for ext in
                   (".mp3", ".m4a", ".flac", ".aac", ".wav", ".ogg", ".m3u8"))

    def manualVideoCheck(self):
        pass

    # ---------------- 通用 GET ----------------
    def _get(self, url, timeout=(3, 6), cache=None, cache_key=None, headers=None):
        if cache is not None and cache_key is not None:
            hit = cache.get(cache_key)
            if hit is not None:
                return hit
        text = ""
        try:
            h = HEADERS if not headers else {**HEADERS, **headers}
            h.setdefault("Referer", BASE + "/")
            r = self.sess.get(url, timeout=timeout, headers=h)
            if r.status_code == 200:
                r.encoding = r.encoding or "utf-8"
                text = r.text
        except Exception:
            text = ""
        if cache is not None and cache_key is not None and text:
            cache.set(cache_key, text)
        return text

    # ---------------- 首页分类 ----------------
    def homeContent(self, filter):
        return {"class": CATEGORIES}

    def homeVideoContent(self):
        return self.categoryContent("stf", 1, False, {})

    # ---------------- 分类列表 ----------------
    def categoryContent(self, tid, pg, filter, extend):
        result = {"list": []}
        key = f"cat:{tid}:{pg}"
        try:
            url = f"{BASE}/{tid}.html" if str(pg) == "1" else f"{BASE}/{tid}/{pg}.html"
            html = self._get(url, cache=self._list_cache, cache_key=key, timeout=(3, 6))
            if not html:
                return result

            videos = []
            for m in RE_ITEM.finditer(html):
                block = m.group(1)
                tm = RE_TITLE_A.search(block)
                if not tm:
                    continue
                link = tm.group(1)
                title = _clean(tm.group(2))

                pic = ""
                pm = RE_PIC.search(block)
                if pm:
                    pic = _abs_url(pm.group(1))

                remark = ""
                lm = RE_LMNAME.search(block)
                if lm:
                    remark = _clean(lm.group(1))

                videos.append({
                    "vod_id": link,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remark,
                })

            result["list"] = videos
            result["page"] = pg

            # 页数：优先尾页，其次下一页反推，最后单页
            pagecount = pg
            tm = RE_LIST_TAIL.search(html)
            if tm:
                m2 = re.search(r'/(\d+)\.html', tm.group(1))
                if m2:
                    pagecount = int(m2.group(1))
            result["pagecount"] = pagecount
            result["limit"] = len(videos) or 30
            result["total"] = pagecount * (len(videos) or 30)
        except Exception:
            result["list"] = []
        return result

    # ---------------- 详情 + 选集（重点优化） ----------------
    def detailContent(self, ids):
        """ids[0] = 详情页 URL"""
        aid = str(ids[0])
        result = {}

        cached = self._detail_cache.get(f"det:{aid}")
        if cached:
            result["list"] = [cached]
            return result

        try:
            html = self._get(aid, timeout=(3, 6))
            if not html:
                raise RuntimeError("empty detail page")

            name_m = RE_H1.search(html)
            name = _clean(name_m.group(1)) if name_m else "未知评书"

            pic_m = RE_BOOKPIC.search(html)
            pic = pic_m.group(1) if pic_m else ""

            # ---------- 1. 收集所有分页 URL ----------
            page_urls = []
            seen = set()

            canon_m = RE_CANON.search(html)
            if canon_m:
                cur = canon_m.group(1)
                if cur not in seen:
                    seen.add(cur)
                    page_urls.append(cur)
            if aid not in seen:
                seen.add(aid)
                page_urls.append(aid)

            base_dir = aid.rsplit("/", 1)[0] + "/"
            base_name = aid.rsplit("/", 1)[-1].rsplit("-", 1)[0]
            for lm in RE_PAGE_LINKS.finditer(html):
                u = lm.group(1)
                if u.startswith(base_dir) and base_name in u and u not in seen:
                    seen.add(u)
                    page_urls.append(u)

            # 兜底：如果只找到 1 页，尝试链式推导 next
            if len(page_urls) <= 1:
                next_url = aid
                for _ in range(30):
                    nxt_m = RE_NEXT.search(html)
                    if not nxt_m:
                        break
                    next_url = nxt_m.group(1)
                    if next_url in seen:
                        break
                    seen.add(next_url)
                    page_urls.append(next_url)
                    html = self._get(next_url, timeout=(3, 6))
                    if not html:
                        break

            # ---------- 2. 并发抓取所有分页音频 ----------
            ep_seen = set()
            play_arr = []

            def fetch_and_parse(u, first_html=None):
                h = first_html if first_html else self._get(u, timeout=(3, 6))
                if not h:
                    return []
                ap_m = RE_APLAYER.search(h)
                if not ap_m:
                    return []
                local = []
                for am in RE_AUDIO_ITEM.finditer(ap_m.group(1)):
                    title = _clean(am.group(1))
                    url = _abs_url(am.group(3))
                    num_m = re.search(r'(\d+)\s*回', title)
                    num = int(num_m.group(1)) if num_m else len(local) + 1
                    local.append((num, title, url))
                return local

            # 首页已抓，复用
            first_html = html
            futures = {}
            for u in page_urls:
                fh = first_html if u == aid else None
                futures[self._pool.submit(fetch_and_parse, u, fh)] = u

            for fut in as_completed(futures):
                try:
                    for num, title, url in fut.result():
                        if url in ep_seen:
                            continue
                        ep_seen.add(url)
                        play_arr.append((num, f"{title}${url}"))
                except Exception:
                    continue

            play_arr.sort(key=lambda x: x[0])
            play_urls = [p[1] for p in play_arr]

            vod = {
                "vod_id": aid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_content": f"共 {len(play_urls)} 集",
                "vod_actor": "",
                "vod_director": "",
                "vod_remarks": f"共 {len(play_urls)} 集",
                "vod_play_from": "评书随身听",
                "vod_play_url": "#".join(play_urls),
            }
            self._detail_cache.set(f"det:{aid}", vod)
            result["list"] = [vod]
        except Exception as e:
            result["list"] = [{
                "vod_id": aid,
                "vod_name": "加载失败",
                "vod_content": f"加载失败: {e}",
                "vod_play_from": "评书随身听",
                "vod_play_url": "",
            }]
        return result

    # ---------------- 播放（秒开） ----------------
    def playerContent(self, flag, id, vipFlags):
        result = {"parse": 0, "playUrl": "", "url": "", "header": PLAY_HEADERS}
        try:
            url = _abs_url(id.strip())
            if url.startswith("http"):
                result["url"] = url
                result["playUrl"] = url
                # 缓存播放地址
                self._play_cache.set(f"play:{id}", url)
        except Exception:
            pass
        return result

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick, pg=1):
        result = {"list": []}
        ck = f"se:{key}:{pg}"
        hit = self._list_cache.get(ck)
        if hit:
            return hit
        try:
            # 先试 POST（Z-Blog 默认）
            html = ""
            try:
                r = self.sess.post(
                    f"{BASE}/zb_system/cmd.php?act=search",
                    data={"q": key},
                    headers={**HEADERS, "Referer": BASE + "/"},
                    timeout=(3, 6),
                )
                if r.status_code == 200:
                    r.encoding = r.encoding or "utf-8"
                    html = r.text
            except Exception:
                pass

            # 兜底 GET
            if not html or "post_list_li" not in html:
                html = self._get(
                    f"{BASE}/zb_system/cmd.php?act=search&q={key}",
                    timeout=(3, 6),
                )

            videos = []
            for m in RE_ITEM.finditer(html or ""):
                block = m.group(1)
                tm = RE_TITLE_A.search(block)
                if not tm:
                    continue
                link = tm.group(1)
                title = _clean(tm.group(2))
                pic = ""
                pm = RE_PIC.search(block)
                if pm:
                    pic = _abs_url(pm.group(1))
                remark = ""
                lm = RE_LMNAME.search(block)
                if lm:
                    remark = _clean(lm.group(1))
                videos.append({
                    "vod_id": link,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remark,
                })

            result["list"] = videos
            result["page"] = pg
            result["pagecount"] = 1
            result["limit"] = len(videos)
            result["total"] = len(videos)
            self._list_cache.set(ck, result)
        except Exception:
            result["list"] = []
        return result

    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick, pg)

    def localProxy(self, param):
        return None