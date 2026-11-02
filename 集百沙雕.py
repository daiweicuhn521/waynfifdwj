#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gzip
import http.client
import json
import re
import socket
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
import zlib

# ---------------------------------------------------------------------------
# 导入 App 注入的基类
# ---------------------------------------------------------------------------
try:
    sys.path.append("..")
    from base.spider import Spider as BaseSpider
except ImportError:
    # 本地无 base 模块时使用的空基类，保证脚本可独立运行调试
    class BaseSpider(object):
        def __init__(self):
            self.extend = ""

try:
    from concurrent.futures import ThreadPoolExecutor
except ImportError:      # 极少数阉割版 Python 环境退化成串行
    ThreadPoolExecutor = None


SITE = "http://www.duanjux.com"
# 站点唯一的正片分类（沙雕番）；“最近更新”首页翻页实际也走该分类分页
MAIN_TID = "22"

UA = ("Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",   # 优化点 1
    "Connection": "keep-alive",           # 优化点 2
    "Referer": SITE + "/",
}

# 超时：连接更短、读取够用即可，失败时不再长时间空等
TIMEOUT_CONN = 5
TIMEOUT_READ = 10
PAGE_SIZE = 18          # 站点每页条数
PREHEAT_PAGES = 6       # 首屏预热页数
MAX_PAGES = 500         # 全量抓取上限
POOL_WORKERS = 8        # 并发抓页线程数

# 缓存 TTL（秒）
TTL_HTML = 120          # 普通页面
TTL_HOME = 60           # 首页
TTL_DETAIL = 600        # 详情
TTL_SEARCH = 60         # 搜索
TTL_ALL = 900           # 全量列表（筛选用）
TTL_FILTERS = 1800      # 筛选定义
TTL_PLAY = 1800         # 播放直链
CACHE_MAX = 400         # 缓存条目上限，防止内存膨胀

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# ---------------------------------------------------------------------------
# 预编译正则（优化点 7）
# ---------------------------------------------------------------------------
_RE_ITEM_A = re.compile(
    r'<a[^>]*?href="(/voddetail/(\d+)\.html)"[^>]*?class="post-item-title"[^>]*>(.*?)</a>',
    re.S)
_RE_ITEM_A2 = re.compile(
    r'<a[^>]*?class="post-item-title"[^>]*?href="(/voddetail/(\d+)\.html)"[^>]*>(.*?)</a>',
    re.S)
_RE_IMG = re.compile(r'class="post-item-img"[^>]*>.*?<img[^>]+>', re.S)
_RE_SRC = re.compile(r'src="([^"]+)"')
_RE_ONERR = re.compile(r"onerror[^>]*?src=[\"']([^\"']+)[\"']")
_RE_ONERR2 = re.compile(r'onerror=src=["\']([^"\']+)["\']')
_RE_TAGS = re.compile(r'<div class="tag-wrap"[^>]*>(.*?)</div>', re.S)
_RE_SUMMARY = re.compile(r'class="post-item-summary"[^>]*>(.*?)</p>', re.S)
_RE_PLAY_A = re.compile(
    r'<a[^>]*href="/vodplay/(\d+-(\d+)-\d+)\.html"[^>]*>(.*?)</a>', re.S)
_RE_IFRAME = re.compile(r'<iframe[^>]*src="([^"]+)"', re.S)
_RE_MEDIA = re.compile(
    r'(https?:)?//[^"\'\s<>\\]+?\.(?:m3u8|mp4|flv|mkv)(?:[^\s"\'<>\\]*)', re.I)
_RE_PAGER = re.compile(r'/vodtype/%s-(\d+)\.html' % MAIN_TID)
_RE_YEAR = re.compile(r"^(19|20)\d{2}$")
_RE_CHARSET = re.compile(r'charset=([\w-]+)', re.I)
_RE_META_CS = re.compile(r'<meta[^>]+charset=["\']?([\w-]+)', re.I)


# ---------------------------------------------------------------------------
# 缓存（优化点 4）
# ---------------------------------------------------------------------------
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key, ttl):
    with _CACHE_LOCK:
        item = _CACHE.get(key)
    if item and (time.time() - item[0]) < ttl:
        return item[1]
    return None


def _cache_set(key, val):
    with _CACHE_LOCK:
        if len(_CACHE) > CACHE_MAX:          # 简易清理：丢掉最旧的一半
            for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:CACHE_MAX // 2]:
                _CACHE.pop(k, None)
        _CACHE[key] = (time.time(), val)
    return val


# ---------------------------------------------------------------------------
# HTTP 层：keep-alive 连接池 + gzip（优化点 1、2）
# ---------------------------------------------------------------------------
class _ConnPool(object):
    """极简同域长连接池；任何异常都向外抛，由调用方回退 urllib。"""

    def __init__(self, max_per_host=4):
        self._max = max_per_host
        self._lock = threading.Lock()
        self._free = {}

    def _new(self, scheme, host, port, timeout):
        if scheme == "https":
            return http.client.HTTPSConnection(
                host, port, context=_SSL_CTX, timeout=timeout)
        return http.client.HTTPConnection(host, port, timeout=timeout)

    def _take(self, key):
        with self._lock:
            lst = self._free.get(key)
            if lst:
                return lst.pop()
        return None

    def _give(self, key, conn, keep):
        if not keep:
            try:
                conn.close()
            except Exception:
                pass
            return
        with self._lock:
            lst = self._free.setdefault(key, [])
            if len(lst) < self._max:
                lst.append(conn)
                return
        try:
            conn.close()
        except Exception:
            pass

    def request(self, url, data=None, timeout=TIMEOUT_READ, headers=None,
                redirects=3):
        parts = urllib.parse.urlsplit(url)
        scheme = parts.scheme or "http"
        host = parts.hostname
        port = parts.port or (443 if scheme == "https" else 80)
        key = (scheme, host, port)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")

        hdr = dict(HEADERS)
        if headers:
            hdr.update(headers)
        hdr["Host"] = host
        if body is not None:
            hdr["Content-Type"] = "application/x-www-form-urlencoded"
            hdr["Content-Length"] = str(len(body))

        conn = None
        for attempt in (0, 1):
            try:
                if conn is None:
                    conn = self._take(key) or self._new(
                        scheme, host, port, TIMEOUT_CONN)
                conn.request("POST" if body is not None else "GET", path,
                             body=body, headers=hdr)
                resp = conn.getresponse()
                raw = resp.read()
                status = resp.status
                loc = resp.getheader("Location")
                ctype = resp.getheader("Content-Type") or ""
                enc = (resp.getheader("Content-Encoding") or "").lower()
                keep_alive = ("close" not in (resp.getheader("Connection") or "").lower())

                if status in (301, 302, 303, 307, 308) and loc and redirects > 0:
                    self._give(key, conn, keep_alive)
                    nxt = urllib.parse.urljoin(url, loc)
                    nd = None if status in (302, 303) else data
                    return self.request(nxt, data=nd, timeout=timeout,
                                        headers=headers, redirects=redirects - 1)

                self._give(key, conn, keep_alive)
                return _decode(raw, enc, ctype)
            except Exception:
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass
                conn = None
                if attempt == 1:
                    raise
        return ""


def _decode(raw, enc, ctype):
    """按 Content-Encoding 解压（gzip/deflate），再按编码转字符串。"""
    try:
        if "gzip" in enc:
            raw = gzip.decompress(raw)
        elif "deflate" in enc:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                raw = zlib.decompress(raw)
    except Exception:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass

    charset = ""
    m = _RE_CHARSET.search(ctype or "")
    if m:
        charset = m.group(1)
    if not charset:
        head = raw[:2048]
        try:
            head = head.decode("ascii", "ignore")
        except Exception:
            head = ""
        m = _RE_META_CS.search(head)
        if m:
            charset = m.group(1)
    try:
        return raw.decode(charset or "utf-8", "ignore")
    except LookupError:
        return raw.decode("utf-8", "ignore")


_POOL = _ConnPool()


def _urllib_get(url, data=None, timeout=TIMEOUT_READ, headers=None):
    """兜底抓取：连接池不可用 / 被 App 环境限制时使用。"""
    try:
        h = dict(HEADERS)
        h.pop("Accept-Encoding", None)      # urllib 不会自动解压，别要压缩流
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        if data is not None:
            req.data = urllib.parse.urlencode(data).encode("utf-8")
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=_SSL_CTX) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, "ignore")
    except Exception:
        return ""


def _get(url, data=None, timeout=TIMEOUT_READ, cache=True, headers=None):
    """统一抓取入口：命中缓存直接返回，否则走连接池，失败回退 urllib。"""
    key = "html:" + url
    if data is None and cache:
        hit = _cache_get(key, TTL_HTML)
        if hit is not None:
            return hit
    html = ""
    try:
        html = _POOL.request(url, data=data, timeout=timeout, headers=headers)
    except Exception:
        html = _urllib_get(url, data=data, timeout=timeout, headers=headers)
    if data is None and cache:
        _cache_set(key, html)
    return html


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _pic(node):
    """从 img 片段里取封面：优先 src，其次 onerror 里的地址。"""
    m = _RE_SRC.search(node)
    if m and m.group(1).startswith("http"):
        return m.group(1)
    m = _RE_ONERR.search(node)
    if m:
        return m.group(1)
    m = _RE_ONERR2.search(node)
    return m.group(1) if m else ""


def _parse_items(html):
    """解析列表页的 .post-item 条目，返回 vod 数组。
    只解析 class="post-item" 的列表条目；
    顶部轮播位（class="photo-item"）不属于列表，刻意忽略。
    """
    vods = []
    if not html or "post-item" not in html:
        return vods
    blocks = html.split('<div class="post-item">')[1:]
    for blk in blocks:
        m = _RE_ITEM_A.search(blk)
        if not m:      # 兼容 class 在前、href 在后的写法
            m = _RE_ITEM_A2.search(blk)
        if not m:
            continue
        vod_id = m.group(2)
        name = _strip_tags(m.group(3))
        pic = ""
        mp = _RE_IMG.search(blk)
        if mp:
            pic = _pic(mp.group(0))
        tags = [_strip_tags(t) for t in _RE_TAGS.findall(blk)]
        ms = _RE_SUMMARY.search(blk)
        summary = _strip_tags(ms.group(1)) if ms else ""
        vods.append({
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": "·".join([t for t in tags if t]),
            "vod_content": summary,
        })
    return vods


def _parse_episodes(html):
    """解析详情页，返回 (线路名字符串, 各线路集数字符串)，以 $$$ 分隔。"""
    groups = {}   # src -> [(name, play_id)]
    for m in _RE_PLAY_A.finditer(html):
        play_id, src, text = m.group(1), m.group(2), m.group(3)
        name = _strip_tags(text) or ("第%s集" % play_id.split("-")[-1])
        groups.setdefault(src, []).append((name, play_id))
    if not groups:
        return "", "", 0
    total = max(len(v) for v in groups.values())
    play_from = "$$$".join("集百·线路%s" % s for s in groups)
    play_url = "$$$".join(
        "#".join("%s$%s" % (n, pid) for n, pid in eps)
        for eps in groups.values())
    return play_from, play_url, total


def _year_of(vod):
    """从条目 vod_remarks（如 “2025·汉语普通话”）里提取 4 位年份。"""
    for t in str(vod.get("vod_remarks", "")).split("·"):
        t = t.strip()
        if _RE_YEAR.match(t):
            return t
    return ""


def _page_url(tid, pg):
    return ("%s/vodtype/%s.html" % (SITE, tid) if pg <= 1
            else "%s/vodtype/%s-%d.html" % (SITE, tid, pg))


def _crawl(tid, pages):
    """并发抓取指定页码区间的列表页，返回按页序拼接的条目（去重）。"""
    pgs = list(pages)
    if not pgs:
        return []
    urls = [_page_url(tid, p) for p in pgs]
    if ThreadPoolExecutor is not None:
        try:
            with ThreadPoolExecutor(max_workers=POOL_WORKERS) as ex:
                htmls = list(ex.map(lambda u: _get(u, timeout=TIMEOUT_READ), urls))
        except Exception:
            htmls = [_get(u, timeout=TIMEOUT_READ) for u in urls]
    else:
        htmls = [_get(u, timeout=TIMEOUT_READ) for u in urls]

    vods, seen = [], set()
    last_ok = 0
    for i, html in enumerate(htmls):
        items = _parse_items(html)
        if not items:
            break                      # 空页即到底，早停（优化点 3）
        last_ok = i + 1
        for v in items:
            if v["vod_id"] not in seen:
                seen.add(v["vod_id"])
                vods.append(v)
    return vods, last_ok


def _fetch_all(tid=MAIN_TID, mode="auto", wait=3.0):
    """抓取分类全部列表页并缓存，供本地筛选使用。

    mode:
      quick —— 只抓前 PREHEAT_PAGES 页，用于首屏秒出（筛选年份用）
      full  —— 抓到空页为止（并发分批，8 线程）
      auto  —— 有全量缓存直接返回；否则先用 quick，并后台起线程补全量，
               最多等 wait 秒，超时就用 quick 数据先出结果
    """
    full_key = "all:%s:full" % tid
    quick_key = "all:%s:quick" % tid

    if mode == "quick":
        hit = _cache_get(quick_key, TTL_ALL)
        return hit if hit is not None else _cache_set(
            quick_key, _crawl(tid, range(1, PREHEAT_PAGES + 1))[0])

    hit = _cache_get(full_key, TTL_ALL)
    if hit is not None:
        return hit
    if mode == "full":
        return _cache_set(full_key, _crawl(tid, range(1, MAX_PAGES))[0])

    # auto：先 quick，再后台补全量
    quick = _cache_get(quick_key, TTL_ALL)
    if quick is None:
        quick = _cache_set(quick_key, _crawl(tid, range(1, PREHEAT_PAGES + 1))[0])
    _ensure_full(tid, wait)
    return _cache_get(full_key, TTL_ALL) or quick


_FULL_STATE = {}
_FULL_LOCK = threading.Lock()


def _ensure_full(tid, wait=3.0):
    """后台线程抓取全量，最多等 wait 秒（优化点 5：首屏不等全量）。"""
    with _FULL_LOCK:
        st = _FULL_STATE.get(tid)
        if st is None:
            st = {"ev": threading.Event(), "started": False}
            _FULL_STATE[tid] = st
    if not st["started"]:
        st["started"] = True

        def worker():
            try:
                vods = _crawl(tid, range(1, MAX_PAGES))[0]
                if vods:
                    _cache_set("all:%s:full" % tid, vods)
                    _cache_set("all:%s:quick" % tid, vods[:len(vods)])
            finally:
                st["ev"].set()

        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
    st["ev"].wait(wait)


def _build_filters():
    """按站点实际数据动态生成筛选定义，返回 filters dict。"""
    key = "filters"
    hit = _cache_get(key, TTL_FILTERS)
    if hit is not None:
        return hit
    years = []
    for v in _fetch_all(MAIN_TID, mode="quick"):     # 首屏不抓全量
        y = _year_of(v)
        if y and y not in years:
            years.append(y)
    years.sort(reverse=True)
    filt = [
        {"key": "year", "name": "年份",
         "value": [{"n": "全部", "v": ""}] + [{"n": y, "v": y} for y in years]},
        {"key": "by", "name": "排序",
         "value": [{"n": "最新", "v": "time"},
                   {"n": "最早", "v": "time_asc"}]},
    ]
    # “最近更新”与“沙雕番”共用同一份本地筛选
    return _cache_set(key, {"home": filt, MAIN_TID: filt})


def _apply_filter(vods, year, by):
    """本地过滤 + 排序。站点默认顺序即“最新在前”。"""
    result = vods
    if year:
        result = [v for v in result if _year_of(v) == year]
    if by == "time_asc":
        result = list(reversed(result))
    return result


def _pagecount_of(html, tid, fallback=99):
    """从分页控件里取真实总页数（优化点 6），取不到再用兜底值。"""
    nums = [int(n) for n in _RE_PAGER.findall(html or "")]
    return max(nums) if nums else fallback


# ---------------------------------------------------------------------------
# 播放直链解析（优化点 8、9、10）
# ---------------------------------------------------------------------------
def _abs(u, base=SITE):
    if u.startswith("//"):
        return "http:" + u
    if u.startswith("/"):
        return base + u
    return u


def _pick_media(html):
    """优先取 .m3u8 / .mp4 直链；取不到再退回 iframe。"""
    for m in _RE_MEDIA.finditer(html or ""):
        u = _abs(m.group(0))
        if ".m3u8" in u or ".mp4" in u or ".flv" in u:
            return u
    m = _RE_IFRAME.search(html or "")
    return _abs(m.group(1).strip()) if m else ""


def _resolve_play(play_id):
    """播放页 -> 真实直链。带缓存，重复点开同一集零请求。"""
    key = "play:" + play_id
    hit = _cache_get(key, TTL_PLAY)
    if hit is not None:
        return hit

    page_url = "%s/vodplay/%s.html" % (SITE, play_id)
    html = _get(page_url, headers={"Referer": SITE + "/"})
    url = _pick_media(html)

    # 只有 iframe 且不是直链：源内先抓一次 iframe 页，挖出真实 m3u8/mp4，
    # 让播放器直接拿到直链，少一次跳转与 HTML 加载。
    if url and not re.search(r"\.(m3u8|mp4|flv|mkv)(\?|$)", url, re.I):
        inner = _get(url, timeout=6, headers={"Referer": page_url})
        if inner:
            direct = _pick_media(inner)
            if direct and re.search(r"\.(m3u8|mp4|flv|mkv)(\?|$)", direct, re.I):
                url = direct
    return _cache_set(key, url)


# ---------------------------------------------------------------------------
# 源实现（继承基类）
# ---------------------------------------------------------------------------
class Spider(BaseSpider):
    """影视壳 Python 源标准接口（基类格式）。"""

    # ---------------- 基本信息 ----------------
    def getName(self):
        return "集百"

    def init(self, extend=""):
        self.extend = extend
        return ""

    # ---------------- 首页 ----------------
    def homeContent(self, filter):
        # 后台预热全量列表，首页本身不等待（优化点 5）
        _ensure_full(MAIN_TID, 0)
        return {
            "class": [
                {"type_id": "home", "type_name": "最近更新"},
                {"type_id": MAIN_TID, "type_name": "沙雕番"},
            ],
            "filters": _build_filters(),
        }

    def homeVideoContent(self):
        key = "home"
        hit = _cache_get(key, TTL_HOME)
        if hit is not None:
            return {"list": hit}
        return {"list": _cache_set(key, _parse_items(_get(SITE + "/")))}

    # ---------------- 分类 ----------------
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        # extend 兼容 dict / json 字符串两种传参方式
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend else {}
            except ValueError:
                extend = {}
        extend = extend or {}
        year = str(extend.get("year", "") or "")
        by = str(extend.get("by", "") or "")

        # ---- 有筛选：全量（并发抓取 + 缓存）-> 本地过滤/排序 -> 本地分页 ----
        if year or by:
            vods = _apply_filter(_fetch_all(MAIN_TID, mode="auto"), year, by)
            pagecount = max(1, (len(vods) + PAGE_SIZE - 1) // PAGE_SIZE)
            pg = max(1, min(pg, pagecount))
            start = (pg - 1) * PAGE_SIZE
            return {
                "list": vods[start:start + PAGE_SIZE],
                "total": len(vods),
                "page": pg,
                "pagecount": pagecount,
                "limit": PAGE_SIZE,
            }

        # ---- 无筛选：走站点原生分页 ----
        # 注意：站点 /index-{pg}.html 与首页内容完全相同（伪分页），
        # “最近更新”翻页改走沙雕番分类的真实分页。
        if tid == "home" and pg <= 1:
            url = SITE + "/"
        else:
            url = _page_url(MAIN_TID if tid == "home" else tid, pg)
        html = _get(url)
        vods = _parse_items(html)
        total = len(vods)
        return {
            "list": vods,
            "total": total,
            "page": pg,
            "pagecount": _pagecount_of(html, tid),   # 真实总页数
            "limit": total or PAGE_SIZE,
        }

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        vid = str(ids[0])
        key = "detail:" + vid
        hit = _cache_get(key, TTL_DETAIL)
        if hit is not None:
            return {"list": [hit]}

        html = _get("%s/voddetail/%s.html" % (SITE, vid))
        if not html:
            return {"list": []}

        name = ""
        m = re.search(r'<meta property="og:title" content="([^"]*)"', html)
        if m:
            name = m.group(1).strip()
        if not name:
            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if m:
                name = _strip_tags(m.group(1)).split("_")[0]

        pic = ""
        m = re.search(r'<img[^>]+class="[^"]*photo-item-img[^"]*"[^>]*>', html, re.S)
        if m:
            pic = _pic(m.group(0))

        content = ""
        m = re.search(r'<meta name="description" content="([^"]*)"', html)
        if m:
            content = m.group(1).strip()

        year = ""
        m = re.search(r'class="tag-wrap">(\d{4})</div>', html)
        if m:
            year = m.group(1)

        play_from, play_url, total = _parse_episodes(html)   # 集数直接复用
        vod = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": "沙雕番",
            "vod_year": year,
            "vod_area": "中国大陆",
            "vod_lang": "汉语普通话",
            "vod_remarks": "共%d集" % total,
            "vod_content": content,
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        }
        _cache_set(key, vod)
        return {"list": [vod]}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick, pg="1"):
        ck = "search:" + str(key)
        hit = _cache_get(ck, TTL_SEARCH)
        if hit is not None:
            return {"list": hit}
        html = _get("%s/vodsearch/-------------.html" % SITE,
                    data={"wd": key}, cache=False)
        return {"list": _cache_set(ck, _parse_items(html))}

    # ---------------- 播放 ----------------
    def playerContent(self, flag, id, vipFlags):
        play_id = str(id)                 # 形如 465-2-1
        real_url = _resolve_play(play_id)  # 直链优先 + 缓存
        page_referer = "%s/vodplay/%s.html" % (SITE, play_id)
        header = {
            "User-Agent": UA,
            "Referer": page_referer,       # 第三方源多认播放页 referer
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        return {
            "parse": 0 if real_url else 1,  # 解析不出直链才走解析
            "playUrl": "",
            "url": real_url,
            "header": header,
        }

    # ---------------- 杂项 ----------------
    def localProxy(self, param):
        return [200, "text/plain", "", ""]

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass


# ---------------------------------------------------------------------------
# 本地调试：python3 集百.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    s = Spider()
    s.init()
    print("== name ==")
    print(s.getName())
    print("== home ==")
    print(json.dumps(s.homeVideoContent(), ensure_ascii=False)[:300])
    print("== filters ==")
    print(json.dumps(s.homeContent(1).get("filters"), ensure_ascii=False)[:500])
    print("== category ==")
    print(json.dumps(s.categoryContent("22", 1, 0, {}), ensure_ascii=False)[:300])
    print("== category filter: 2025 ==")
    r = s.categoryContent("22", 1, 1, {"year": "2025"})
    print("total=%s pagecount=%s got=%s" % (r["total"], r["pagecount"], len(r["list"])))
    print("== category filter: 2025 + time_asc ==")
    r = s.categoryContent("22", 1, 1, {"year": "2025", "by": "time_asc"})
    print("total=%s pagecount=%s got=%s" % (r["total"], r["pagecount"], len(r["list"])))
    print("== category filter: extend(json str) ==")
    r = s.categoryContent("22", 1, 1, json.dumps({"year": "2025"}, ensure_ascii=False))
    print("total=%s pagecount=%s got=%s" % (r["total"], r["pagecount"], len(r["list"])))
    print("== search ==")
    print(json.dumps(s.searchContent("诡界", 0), ensure_ascii=False)[:300])
    print("== detail ==")
    print(json.dumps(s.detailContent(["465"]), ensure_ascii=False)[:600])
    print("== player ==")
    print(json.dumps(s.playerContent("集百·线路2", "465-2-1", 0), ensure_ascii=False))
