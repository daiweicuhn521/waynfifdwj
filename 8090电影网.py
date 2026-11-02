# -*- coding: utf-8 -*-
"""
8090电影网 Python Spider — http://bocaiyingshi.hnmjks.com
自定义 Bootstrap 模板(非 maccms mxpro),播放页 /bf/<id>.html 里
真实 m3u8 藏在 <iframe src="https://api.cssstatic.com/?url=<URL编码m3u8>"> 中。
"""

import sys
import re
import json
import time
import threading
from urllib.parse import quote, unquote, urljoin

sys.path.append('..')

try:
    from base.spider import Spider
except ImportError:
    try:
        import requests as _rq
        try:
            import urllib3
            urllib3.disable_warnings()
        except Exception:
            pass

        class Spider:
            def fetch(self, url, headers=None, **kw):
                timeout = kw.pop('timeout', 15)
                r = _rq.get(url, headers=headers, timeout=timeout, verify=False, **kw)
                r.encoding = 'utf-8'
                return r
    except ImportError:
        # 连 requests 都没有,纯 urllib 兜底
        import urllib.request as _ur

        class _Resp:
            def __init__(self, raw):
                self.text = raw.decode('utf-8', errors='ignore')
                self.encoding = 'utf-8'

        class Spider:
            def fetch(self, url, headers=None, **kw):
                timeout = kw.pop('timeout', 15)
                req = _ur.Request(url, headers=headers or {})
                return _Resp(_ur.urlopen(req, timeout=timeout).read())


# ============================================================
# 常量
# ============================================================
HOST = "http://bocaiyingshi.hnmjks.com"
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

# 顶级分类
CLASSES = [
    {"type_name": "电影", "type_id": "1"},
    {"type_name": "连续剧", "type_id": "2"},
    {"type_name": "综艺", "type_id": "3"},
    {"type_name": "动漫", "type_id": "4"},
]

# 二级分类(筛选) —— value 即真实 category id
FILTERS = {
    "1": [{"key": "cate", "name": "分类", "value": [
        {"n": "全部", "v": "1"},
        {"n": "动作片", "v": "6"},
        {"n": "喜剧片", "v": "7"},
        {"n": "爱情片", "v": "8"},
        {"n": "科幻片", "v": "9"},
        {"n": "恐怖片", "v": "10"},
        {"n": "剧情片", "v": "11"},
        {"n": "战争片", "v": "12"},
        {"n": "动画片", "v": "19"},
        {"n": "奇幻片", "v": "20"},
        {"n": "悬疑片", "v": "21"},
        {"n": "纪录片", "v": "22"},
    ]}],
    "2": [{"key": "cate", "name": "分类", "value": [
        {"n": "全部", "v": "2"},
        {"n": "国产剧", "v": "13"},
        {"n": "港台剧", "v": "14"},
        {"n": "日韩剧", "v": "15"},
        {"n": "欧美剧", "v": "16"},
        {"n": "泰剧", "v": "37"},
        {"n": "短剧", "v": "23"},
    ]}],
    "3": [{"key": "cate", "name": "分类", "value": [
        {"n": "全部", "v": "3"},
        {"n": "大陆综艺", "v": "24"},
        {"n": "日韩综艺", "v": "25"},
        {"n": "港台综艺", "v": "26"},
        {"n": "欧美综艺", "v": "27"},
    ]}],
    "4": [{"key": "cate", "name": "分类", "value": [
        {"n": "全部", "v": "4"},
        {"n": "国产动漫", "v": "28"},
        {"n": "日韩动漫", "v": "29"},
        {"n": "港台动漫", "v": "30"},
        {"n": "欧美动漫", "v": "31"},
    ]}],
}

# ============================================================
# 搜索相关常量
# 说明: 站点 /search/<key>.html 返回的是与关键词无关的随机列表,
#       无法用于真实搜索。改为抓取分类列表建立本地片名索引再过滤。
# ============================================================
SEARCH_CRAWL_CATS = ["1", "2", "3", "4"]   # 抓取的一级分类(已涵盖其全部子分类)
SEARCH_CRAWL_PAGES = 20                    # 每个分类抓取的页数
SEARCH_CACHE_TTL = 12 * 3600               # 索引缓存时长(秒)
SEARCH_PAGE_SIZE = 20                      # 搜索结果每页条数


# ============================================================
# Spider 主类
# ============================================================
class Spider(Spider):

    def getName(self):
        return "8090电影网"

    def init(self, extend=""):
        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def isVideoFormat(self, url):
        u = (url or "").lower()
        return any(ext in u for ext in [".m3u8", ".mp4", ".flv", ".ts"])

    # ===== 网络工具 =====
    def _get_html(self, url, timeout=15):
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            return rsp.text if rsp else ""
        except Exception as e:
            print(f"[8090] 请求失败 {url}: {e}")
            return ""

    def _abs_url(self, url):
        if not url:
            return ""
        if url.startswith('//'):
            return "https:" + url
        if url.startswith('/'):
            return HOST + url
        if not url.startswith('http'):
            return urljoin(HOST + '/', url)
        return url

    @staticmethod
    def _strip(txt):
        return re.sub(r'\s+', ' ', (txt or '')).strip()

    def _parse_vod(self, html):
        """通用解析影片卡片。
        站点三种布局统一规律:<a href="/detail/<id>.html"><img src=.. alt=..></a>
        标题优先取 alt,fallback 到 .movie-title / .movie-info 内文本。
        """
        items = []
        for m in re.finditer(
            r'<a[^>]+href="/detail/(\d+)\.html"[^>]*>'
            r'([\s\S]*?)</a>',
            html,
        ):
            vod_id = m.group(1)
            block = m.group(2)

            # 封面 + alt 标题(匹配整个 <img ...> 标签后单独取 src/alt,
            # 这样无论 alt 在 src 前还是后都能正确提取)
            img_m = re.search(r'<img\b([^>]*)>', block)
            if not img_m:
                continue
            img_attrs = img_m.group(1)
            src_m = re.search(r'src="([^"]+)"', img_attrs)
            if not src_m:
                continue
            pic = self._abs_url(src_m.group(1).strip())
            alt_m = re.search(r'alt="([^"]*)"', img_attrs)
            title = self._strip(alt_m.group(1)) if alt_m else ""

            # alt 缺失时回退到 .movie-title / .small.fw-bold(分类页卡片) / .movie-info
            if not title:
                t = re.search(r'class="[^"]*movie-title[^"]*"[^>]*>([^<]+)<', block)
                if t:
                    title = t.group(1).strip()
            if not title:
                t = re.search(r'class="[^"]*small[^"]*fw-bold[^"]*"[^>]*>([^<]+)<', block)
                if t:
                    title = t.group(1).strip()
            if not title:
                t = re.search(r'class="[^"]*movie-info[^"]*"[^>]*>[\s\S]*?<a[^>]*>([^<]+)<', block)
                if t:
                    title = t.group(1).strip()

            # 备注(站点卡片基本没有,留空)
            note_m = re.search(r'class="[^"]*(?:note|remarks|tag|badge)[^"]*"[^>]*>([^<]+)<', block)
            remarks = self._strip(note_m.group(1)) if note_m else ""

            items.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
            })

        # 按页面出现顺序去重
        seen, uniq = set(), []
        for it in items:
            if it['vod_id'] in seen:
                continue
            seen.add(it['vod_id'])
            uniq.append(it)
        return uniq

    # ===== 首页 =====
    def homeContent(self, filter):
        result = {"class": CLASSES}
        if filter:
            result["filters"] = FILTERS
        return result

    def homeVideoContent(self):
        """首页推荐:抓取首页所有 /detail/ 卡片。"""
        html = self._get_html(HOST + "/", timeout=12)
        if not html:
            return {"list": []}
        items = self._parse_vod(html)
        return {"list": items[:30]}

    # ===== 分类列表 =====
    def categoryContent(self, tid, pg, filter, extend):
        try:
            # 支持二级分类筛选
            cate = (extend or {}).get('cate') if extend else None
            use_tid = cate if cate else tid

            page = int(pg or 1)
            if page < 1:
                page = 1
            if page == 1:
                url = f"{HOST}/category/{use_tid}.html"
            else:
                url = f"{HOST}/category/{use_tid}/{page}.html"

            html = self._get_html(url, timeout=15)
            if not html:
                return {"page": page, "pagecount": 1, "limit": 24, "total": 0, "list": []}

            videos = self._parse_vod(html)

            # 解析总页数: <a class="page-link" href=".../category/<tid>/<n>.html">N</a>
            pagecount = page
            for pm in re.finditer(r'href="[^"]*/category/\d+/(\d+)\.html"', html):
                n = int(pm.group(1))
                if n > pagecount:
                    pagecount = n
            # 末页:当前页无数据则回退
            if not videos:
                pagecount = max(1, page - 1)

            return {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": len(videos) or 24,
                "total": pagecount * 24,
            }
        except Exception as e:
            print(f"[8090] categoryContent 异常: {e}")
            return {"page": 1, "pagecount": 1, "limit": 24, "total": 0, "list": []}

    # ===== 详情页 =====
    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)):
            ids = ids[0]
        vod_id = str(ids)

        url = f"{HOST}/detail/{vod_id}.html"
        html = self._get_html(url, timeout=15)
        if not html:
            return {"list": []}

        try:
            vod = {
                "vod_id": vod_id,
                "vod_name": "",
                "vod_pic": "",
                "vod_year": "",
                "vod_area": "",
                "vod_remarks": "",
                "vod_actor": "",
                "vod_director": "",
                "vod_class": "",
                "vod_content": "",
                "vod_play_from": "",
                "vod_play_url": "",
            }

            # 标题
            m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
            if m:
                vod["vod_name"] = self._strip(m.group(1))

            # 信息行: 分类：战争片/ 年代：2026/ 地区：英国/ 语言：英语
            info_m = re.search(
                r'分类[：:]\s*([^/]*)/\s*(?:年代|年份)[：:]\s*(\d{4})?\s*/?\s*地区[：:]\s*([^/]*)',
                html)
            if info_m:
                vod["vod_class"] = self._strip(info_m.group(1))
                vod["vod_year"] = info_m.group(2) or ""
                vod["vod_area"] = self._strip(info_m.group(3))

            # 封面
            m = re.search(r'<img[^>]+class="[^"]*poster[^"]*"[^>]+src="([^"]+)"', html) or \
                re.search(r'<img[^>]+src="([^"]+)"[^>]+class="[^"]*poster[^"]*"', html)
            if m:
                vod["vod_pic"] = self._abs_url(m.group(1).strip())

            # 导演 / 主演 / 标签 / 简介
            for kw, key in [
                ('导演', 'vod_director'),
                ('主演', 'vod_actor'),
                ('分类标签', 'vod_class'),
                ('类型', 'vod_class'),
            ]:
                m = re.search(rf'<strong>{kw}[：:]</strong>([\s\S]*?)</p>', html)
                if m and not (key == 'vod_class' and vod.get('vod_class')):
                    txt = re.sub(r'<[^>]+>', '', m.group(1))
                    val = self._strip(txt)
                    if val:
                        vod[key] = val

            # 简介
            m = re.search(r'<strong>简介[：:]</strong>([\s\S]*?)</p>', html)
            if m:
                txt = re.sub(r'<[^>]+>', '', m.group(1))
                vod["vod_content"] = self._strip(txt)[:500]

            # 播放列表
            play_from, play_url = self._collect_playlist(html)
            if play_from:
                vod["vod_play_from"] = "$$$".join(play_from)
                vod["vod_play_url"] = "$$$".join(play_url)

            return {"list": [vod]}
        except Exception as e:
            print(f"[8090] detailContent 异常: {e}")
            return {"list": []}

    def _collect_playlist(self, html):
        """解析播放源 + 剧集。
        结构:
          <h5 class="text-primary">播放源：无尽</h5>
          <div class="d-flex flex-wrap gap-2">
            <a href="/bf/130569.html" class="btn ...">第01集</a>      ← 第1集(无后缀)
            <a href="/bf/130569-1-2.html" class="btn ...">第02集</a>  ← 多集(id-源号-集号)
          </div>
        """
        play_from, play_url = [], []

        # 切分: 每个 播放源:xxx 之后到下一个 播放源 或 section-title 之间
        blocks = re.split(r'<h5[^>]*class="[^"]*text-primary[^"]*"[^>]*>\s*播放源[：:]([^<]+)</h5>',
                          html)
        # split 结果: [前段, 源名1, 块1, 源名2, 块2, ...]
        for i in range(1, len(blocks), 2):
            src_name = self._strip(blocks[i])
            chunk = blocks[i + 1] if i + 1 < len(blocks) else ""
            # 截到下一个 section-title 防止串到热播区
            st = chunk.find('section-title')
            if st != -1:
                chunk = chunk[:st]

            eps = []
            # 同时匹配第1集 /bf/<id>.html 和多集 /bf/<id>-<sid>-<nid>.html
            for em in re.finditer(
                r'<a[^>]+href="(/bf/\d+(?:-\d+-\d+)?\.html)"[^>]*>([\s\S]*?)</a>',
                chunk,
            ):
                bf_path = em.group(1)
                name = self._strip(re.sub(r'<[^>]+>', '', em.group(2))) or "正片"
                eps.append(f"{name}${bf_path}")

            if eps:
                play_from.append(src_name or f"线路{len(play_from) + 1}")
                play_url.append("#".join(eps))

        return play_from, play_url

    # ===== 搜索 =====
    # 说明: 站点 /search/<key>.html 接口返回的是与关键词无关的随机列表
    #       (实测搜“凡人修仙传”返回的是深宵闪避球、亚洲犯罪网等随机影片),
    #       无法用于真实搜索。这里改为抓取各分类列表建立本地片名索引,
    #       再按关键词过滤,保证搜索结果准确。索引带缓存,仅首次搜索较慢。
    def _build_search_index(self):
        """并发抓取各分类前 N 页,建立 {vod_id: item} 索引并缓存。"""
        cached = getattr(self, "_search_index", None)
        ts = getattr(self, "_search_index_ts", 0)
        if cached is not None and time.time() - ts < SEARCH_CACHE_TTL:
            return cached

        results = {}
        lock = threading.Lock()

        def _fetch_and_store(cat, pg):
            url = f"{HOST}/category/{cat}.html" if pg == 1 else f"{HOST}/category/{cat}/{pg}.html"
            try:
                html = self._get_html(url, timeout=10)
                items = self._parse_vod(html) if html else []
            except Exception:
                items = []
            with lock:
                results[(cat, pg)] = items

        # 并发抓取,控制并发数避免被站点限流
        sem = threading.Semaphore(10)
        threads = []

        def _worker(cat, pg):
            with sem:
                _fetch_and_store(cat, pg)

        for cat in SEARCH_CRAWL_CATS:
            for pg in range(1, SEARCH_CRAWL_PAGES + 1):
                t = threading.Thread(target=_worker, args=(cat, pg))
                threads.append(t)
                t.start()
        for t in threads:
            t.join(timeout=30)

        # 并发全部失败(如运行环境 fetch 非线程安全)时,串行兜底重试前几页
        if not any(results.values()):
            for cat in SEARCH_CRAWL_CATS:
                for pg in range(1, 6):
                    _fetch_and_store(cat, pg)

        index = {}
        for items in results.values():
            for it in items:
                index.setdefault(it["vod_id"], it)

        self._search_index = list(index.values())
        self._search_index_ts = time.time()
        print(f"[8090] 搜索索引构建完成,共 {len(self._search_index)} 条")
        return self._search_index

    def searchContent(self, key, quick, pg="1"):
        try:
            kw = self._strip(str(key or "")).lower()
            if not kw:
                return {"list": []}

            page = int(pg or 1)
            if page < 1:
                page = 1

            index = self._build_search_index()

            # 关键词过滤:片名包含关键词即命中
            matched = [
                it for it in index
                if kw in (it.get("vod_name") or "").lower()
            ]

            start = (page - 1) * SEARCH_PAGE_SIZE
            page_items = matched[start:start + SEARCH_PAGE_SIZE]
            total = len(matched)
            pagecount = max(1, (total + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE)

            return {
                "list": page_items,
                "page": page,
                "pagecount": pagecount,
                "limit": SEARCH_PAGE_SIZE,
                "total": total,
            }
        except Exception as e:
            print(f"[8090] searchContent 异常: {e}")
            return {"list": []}

    # ===== 播放 =====
    def playerContent(self, flag, id, vipFlags):
        """拿到 /bf/<id>.html 后,从 iframe 的 api.cssstatic.com/?url=<URL编码m3u8> 取真实地址。"""
        play_url = str(id or "")
        if not play_url:
            return {"parse": 0, "url": ""}

        # 已是直链直接返回
        if self.isVideoFormat(play_url):
            return {
                "parse": 0,
                "url": play_url,
                "header": {"User-Agent": UA, "Referer": HOST + "/"},
            }

        if "/bf/" in play_url or "bf" in play_url:
            if not play_url.startswith("http"):
                play_url = HOST + play_url
            html = self._get_html(play_url, timeout=12)
            if html:
                real = self._extract_m3u8(html)
                if real:
                    return {
                        "parse": 0,
                        "url": real,
                        "header": {"User-Agent": UA, "Referer": play_url},
                    }

        # 兜底:透传
        return {
            "parse": 0,
            "url": play_url,
            "header": {"User-Agent": UA, "Referer": HOST + "/"},
        }

    @staticmethod
    def _extract_m3u8(html):
        """从播放页提取真实 m3u8。
        优先: <iframe src="https://api.cssstatic.com/?url=<URL编码m3u8>"> → 解码
        其次: src/data-url 里直接含 .m3u8 / .mp4
        最后: var player_xxxx = {...} 兜底
        """
        # 1) api.cssstatic.com/?url=<encoded>
        m = re.search(r'src="(https?://[^"]*cssstatic[^"]*\?url=([^"&]+))"', html)
        if m:
            enc = m.group(2)
            real = unquote(enc)
            if real:
                return real
            # 兜底:用整个 query
            q = re.search(r'\?url=(.+)$', m.group(1))
            if q:
                return unquote(q.group(1))

        # 2) 直接 m3u8/mp4 链接
        m = re.search(r'(?:src|data-url|url)\s*=\s*["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', html)
        if m:
            return m.group(1)

        # 3) player_xxxx 对象兜底
        obj = _extract_player_obj(html)
        if obj and obj.get('url'):
            return obj['url']
        return ""

    # ===== 其他 =====
    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    def destroy(self):
        pass


# ============================================================
# 模块级辅助函数
# ============================================================
def _extract_player_obj(html):
    """从播放页提取 var player_xxxx = {...}; 的对象(对嵌套大括号安全)。"""
    m = re.search(r'var\s+player_\w+\s*=\s*', html)
    if not m:
        return None
    i = m.end()
    if i >= len(html) or html[i] != '{':
        return None
    depth, start = 0, i
    while i < len(html):
        c = html[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                break
        elif c == '"':
            i += 1
            while i < len(html) and html[i] != '"':
                if html[i] == '\\':
                    i += 2
                    continue
                i += 1
        i += 1
    if depth != 0:
        return None
    raw = html[start:i + 1]
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(raw.replace("'", '"'))
        except Exception:
            return None
