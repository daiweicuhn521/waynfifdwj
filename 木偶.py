# -*- coding: utf-8 -*-
"""
木偶网（666.666291.xyz）网盘影视源

六个入口全在本文件：分类/首页推荐/分类列表/搜索/详情/播放。
网盘规则在 netdisk.py（与官方 game-live-py 同构的多文件结构）：
  · getDependence() 返回 ["netdisk"]，宿主会预先把 netdisk.py 准备好
  · init() 里 loadModule("netdisk") 取模块，再 Netdisk(self.net) 建实例
  · 取不到模块时退化为「有详情、无可播线路」，不会崩
  · 别的源声明同一个依赖，即可复用这套网盘规则

Cookie 全部填在 netdisk.py 顶部，本文件不碰任何 Cookie。
依赖 self.net（宿主注入），Python 3.10（FongMi 5.8.6）。
"""
from base.spider import Spider as BaseSpider
import os
import re
import json
import time
import urllib.parse

# ======================== 站点与 UA ========================
SITE = "https://666.666291.xyz"
UA_PC = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 网盘依赖模块名：对应同目录的 netdisk.py
DEP_MODULE = "netdisk"

# ======================== 分类与筛选 ========================
CATEGORIES = [
    {"type_id": "25", "type_name": "115臻享"},
    {"type_id": "1",  "type_name": "木偶电影"},
    {"type_id": "2",  "type_name": "木偶剧集"},
    {"type_id": "3",  "type_name": "木偶动漫"},
    {"type_id": "29", "type_name": "木偶综艺"},
    {"type_id": "4",  "type_name": "木偶纪录片"},
]

# 下面是「面板解析失败」时的兜底；正常情况下每个分类的选项从站点实时解析（见 _filter_panel）
YEARS = [{"n": "全部", "v": ""}] + [{"n": str(y), "v": str(y)} for y in range(2026, 2009, -1)]
SORTS = [{"n": "时间", "v": "time"}, {"n": "人气", "v": "hits"}, {"n": "评分", "v": "score"}]
FILTERS = {"__default__": [{"key": "year", "name": "年份", "value": YEARS},
                           {"key": "by", "name": "排序", "value": SORTS}]}
SORT_NAMES = {"time": "时间", "hits": "人气", "score": "评分"}

# ======================== 缓存 TTL（毫秒） ========================
TTL_HTML = 5 * 60 * 1000


class Spider(BaseSpider):

    # 站点被限流时返回约 1KB 短页（正常首页 600KB+、搜索 30KB+），_site_get 据此退避重试
    SITE_PAGE_MIN = 20000

    # ======================== 初始化 ========================
    def init(self, extend=""):
        # 网盘依赖模块与实例（单例，必须每次重置）
        self._ndMod = None
        self._ndObj = None

        # 站点缓存（带容量上限，防盒子长期运行内存增长）
        self._detailHtmlCache = {}
        self._catCache = None
        self._cfWarmed = False
        self._homeHtmlCache = {}
        self._searchCache = {}
        self._filterCache = {}

        # 依赖模块在这里取一次；取不到就退化（详情仍可看，只是没有可播线路）
        self._ndMod = self._load_module(DEP_MODULE)
        self._ndObj = self._make_netdisk()
        if self._ndObj is None:
            try:
                log = getattr(self, "log", None)
                if callable(log):
                    log("网盘模块 %s 未加载，网盘线路不可用" % DEP_MODULE)
            except Exception:
                pass
        return ""

    # ======================== 网盘模块加载 ========================
    def getDependence(self):
        """向宿主声明依赖模块（名字 = 相对路径去后缀）。"""
        return [DEP_MODULE]

    def _load_module(self, name):
        """三路加载依赖模块，任意一路成功即可。"""
        # 1) 宿主 API：config.json + getDependence 正常部署时走这条
        fn = getattr(self, "loadModule", None)
        if callable(fn):
            try:
                m = fn(name)
                if m is not None and hasattr(m, "Netdisk"):
                    return m
            except Exception:
                pass
        # 2) 与主模块同目录的 <name>.py（不实现 loadModule 的壳 / 本地调试）
        try:
            import importlib.util
            base = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(base, name + ".py")
            if os.path.isfile(path):
                spec = importlib.util.spec_from_file_location("muou_dep_" + name, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
        except Exception:
            pass
        # 3) 已在 sys.path 里（被别的源 import 过）
        try:
            import importlib
            return importlib.import_module(name)
        except Exception:
            return None

    def _make_netdisk(self):
        mod = getattr(self, "_ndMod", None)
        if mod is None or not hasattr(mod, "Netdisk"):
            return None
        try:
            # Cookie 由 netdisk 模块自带（填在该文件顶部），这里一个都不传
            return mod.Netdisk(self.net, log=getattr(self, "log", None))
        except Exception:
            return None

    def _nd(self):
        """取网盘实例；宿主晚注入 net 时顺手接上（个别壳先 init 再赋 net）。"""
        nd = getattr(self, "_ndObj", None)
        if nd is not None and getattr(nd, "net", None) is not self.net:
            nd.net = self.net
        return nd

    # ======================== 基础工具 ========================
    @staticmethod
    def _strip(s):
        s = str(s or "")
        s = re.sub(r"<[^>]+>", "", s)
        s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
              .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
        s = re.sub(r"\s+", " ", s)
        return s.strip()

    @staticmethod
    def _pick(pattern, s):
        if not s:
            return ""
        m = re.search(pattern, s)
        if not m:
            return ""
        try:
            return (m.group(1) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _abs(u):
        if not u:
            return ""
        u = str(u).replace("&amp;", "&")
        if re.match(r"^https?://", u, re.I):
            return u
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("/"):
            return SITE + u
        return SITE + "/" + u

    @staticmethod
    def _json(s):
        try:
            return json.loads(s) if s else None
        except Exception:
            return None

    @staticmethod
    def _decode(c):
        if c is None:
            return ""
        if isinstance(c, str):
            return c
        try:
            return c.decode("utf-8")
        except Exception:
            try:
                return c.decode("gbk", "ignore")
            except Exception:
                return ""

    @staticmethod
    def _cache_get(cache, key, ttl):
        v = cache.get(key)
        if v is not None and (time.time() * 1000 - v["t"] < ttl):
            return v["v"]
        return None

    @staticmethod
    def _cache_set(cache, key, val, cap=0):
        """写入缓存；cap>0 时超限淘汰最旧条目（防 TV 端长期运行内存持续增长）。"""
        cache[key] = {"t": time.time() * 1000, "v": val}
        if cap and len(cache) > cap:
            try:
                oldest = min(cache.items(), key=lambda kv: kv[1].get("t", 0))[0]
                if oldest != key:
                    cache.pop(oldest, None)
            except Exception:
                pass

    # ======================== 网络层（只服务站点，网盘的请求在 netdisk 里） ========================
    def _request(self, url, opt=None):
        opt = opt or {}
        headers = {"User-Agent": UA_PC}
        headers.update(opt.get("headers") or {})
        o = {"headers": headers, "timeout": 15000}
        method = (opt.get("method") or "get").lower()
        if method == "post":
            o["method"] = "POST"
            pt = opt.get("postType")
            if not pt:
                ct = str(headers.get("Content-Type", "")).lower()
                pt = "json" if "json" in ct else "form"
            o["postType"] = pt
            if opt.get("data") is not None:
                o["data"] = opt.get("data")
        try:
            resp = self.net.req(url, o)
        except Exception as ex:
            return "", {"error": str(ex), "headers": {}}
        if not resp:
            return "", {"error": "noresp", "headers": {}}
        if resp.get("error"):
            return "", resp
        return self._decode(resp.get("content")), resp

    def _get(self, url, headers=None):
        return self._request(url, {"headers": headers})[0]

    def _site_get(self, url, tries=2):
        html = ""
        for i in range(max(1, tries)):
            if i:
                time.sleep(0.8)
            html = self._get(url, {"User-Agent": UA_PC, "Referer": SITE + "/"})
            if html and len(html) >= self.SITE_PAGE_MIN:
                return html
            if self._is_rate_limited(html):
                # 站点限流提示页，短时间重试也没用，直接返回交给调用方判断
                return html
        return html

    @staticmethod
    def _is_rate_limited(html):
        if not html or len(html) > 8000:
            return False
        return ("请不要频繁操作" in html) or ("时间间隔" in html) or ("系统提示" in html)

    def _post_json(self, url, obj, headers=None):
        h = {"Content-Type": "application/json;charset=UTF-8"}
        h.update(headers or {})
        return self._request(url, {"method": "post", "headers": h, "postType": "json", "data": obj})[0]

    def _http(self):
        return self._site_get(SITE + "/")


    # ======================== 列表解析 ========================
    def _parse_list(self, html):
        out = []
        if not html:
            return out
        parts = re.split(r'<div\s+class="module-(?:search-)?item"[^>]*>', html)
        for item in parts[1:]:
            idm = re.search(r"/index\.php/vod/detail/id/(\d+)\.html", item)
            if not idm:
                continue
            vid = idm.group(1)
            name = (self._pick(r'class="module-item-title"[^>]*title=["\']([^"\']+)["\']', item)
                    or self._pick(r'<h3>\s*<a[^>]+title=["\']([^"\']+)["\']', item)
                    or self._pick(r'<a[^>]+href="[^"]*/vod/detail/id/\d+\.html"[^>]+title=["\']([^"\']+)["\']', item))
            pic = (self._pick(r'data-original=["\']([^"\']+)["\']', item)
                   or self._pick(r'data-src=["\']([^"\']+)["\']', item)
                   or self._pick(r'<img[^>]+\bsrc=["\']([^"\']+\.(?:jpg|jpeg|png|webp|gif)[^"\']*)["\']', item))
            if not pic:
                sm = re.search(r"background(?:-image)?\s*:\s*url\(([^)]+)\)", item)
                if sm:
                    pic = sm.group(1).replace('"', "").replace("'", "").strip()
            year = (self._pick(r"module-item-caption[\s\S]*?<span[^>]*>([^<]+)</span>", item)
                    or self._pick(r"/vod/search/year/(\d{4})\.html", item))
            remark = (self._pick(r"module-item-text[^>]*>([\s\S]*?)<", item)
                      or self._pick(r'class="video-serial"[^>]*>([\s\S]*?)</a>', item)
                      or self._pick(r'class="video-serial"[^>]*>([\s\S]*?)<', item))
            out.append({
                "vod_id": vid,
                "vod_name": self._strip(name),
                "vod_pic": self._abs(pic),
                "vod_year": (year or "").strip(),
                "vod_remarks": self._strip(remark) or (year or "").strip(),
            })
        seen = set()
        uniq = []
        for it in out:
            if it["vod_id"] and it["vod_id"] not in seen:
                seen.add(it["vod_id"])
                uniq.append(it)
        return uniq

    @staticmethod
    def _page_count(html):
        # 分页参数插在筛选条件中间（page/2/year/2024.html），只认 page/N.html 会漏，导致恒为 1 页
        arr = re.findall(r"page/(\d+)(?:\.html|/)", html or "")
        mx = 1
        for s in arr:
            try:
                v = int(s)
                if v > mx:
                    mx = v
            except Exception:
                pass
        return mx

    @staticmethod
    def _cat_url(tid, pg, extend):
        """分类页地址。

        只用 /vod/show/：/vod/type/ 是全库列表、不认 page（1/2/3 页条数不同但首条相同）。
        page 必须放在 id 之后，否则页面生成的分页链接解析不到页数。
        """
        e = extend or {}
        if isinstance(e, str):
            # 个别壳把 extend 当 JSON 字符串传，直接 .get 会崩
            try:
                e = json.loads(e)
            except Exception:
                e = {}
        if not isinstance(e, dict):
            e = {}
        cls = str(e.get("class") or "").strip()
        area = str(e.get("area") or "").strip()
        year = str(e.get("year") or "").strip()
        by = str(e.get("by") or "").strip()
        u = SITE + "/index.php/vod/show/"
        if cls:
            u += "class/" + urllib.parse.quote(cls) + "/"
        if area:
            u += "area/" + urllib.parse.quote(area) + "/"
        u += "id/" + str(tid) + "/page/" + str(pg or 1)
        if year:
            u += "/year/" + year
        if by:
            u += "/by/" + by
        return u + ".html"

    def _share_links(self, html):
        if not html:
            return []
        seg = html.split('id="download-list"', 1)[1] if 'id="download-list"' in html else ""
        block = re.split(r"相关影片|<!--\s*下载列表\s*-->", seg)[0] if seg else seg
        out = []
        seen = set()
        for m in re.finditer(r'data-clipboard-text=["\'](https?://[^"\']+)["\']', block):
            u = m.group(1)
            if u not in seen:
                seen.add(u)
                out.append(u)
        if not out:
            for m in re.finditer(r'(https?://(?:pan\.quark\.cn|drive\.uc\.cn|pan\.baidu\.com)/[^\s"\'<>]+)', html):
                u = m.group(1)
                if u not in seen:
                    seen.add(u)
                    out.append(u)
        return out

    def _parse_cats(self, html):
        if not html:
            return []
        seen = set()
        out = []
        for m in re.finditer(
                r'<a[^>]+href=["\'][^"\']*/index\.php/vod/(?:type|show)/id/(\d+)[^"\']*["\']'
                r'[^>]*\btitle=["\']([^"\']+)["\']', html):
            cid = m.group(1)
            name = self._strip(m.group(2))
            if not name or cid in seen or re.search(r"^更多|^全部|资讯|专题|留言|排行|APP|下载|首页", name):
                continue
            seen.add(cid)
            out.append({"type_id": cid, "type_name": name})
        return out

    def _parse_filter_panel(self, html, tid):
        """解析 /vod/show/id/{tid}.html 自带的筛选面板。
        各分类面板不同（电影有剧情/地区，动漫等只有年份/排序），按 tid 各自解析。
        """
        if not html:
            return []
        cls, area, years, sorts = [], [], [], []
        seen_c, seen_a, seen_y, seen_s = set(), set(), set(), set()
        tid_re = re.escape(str(tid))
        for attrs, text in re.findall(r"<a\b([^>]*)>([\s\S]*?)</a>", html):
            href = self._pick(r'href=["\']([^"\']+)["\']', attrs) or ""
            if not href:
                continue
            title = self._strip(self._pick(r'title=["\']([^"\']*)["\']', attrs))
            m = re.search(r"/vod/show/(class|area)/([^/\"\']+)/id/" + tid_re + r"\.html", href)
            if m:
                v = urllib.parse.unquote(m.group(2)).strip()
                if not v:
                    continue
                if m.group(1) == "class":
                    if v not in seen_c:
                        seen_c.add(v)
                        cls.append({"n": title or v, "v": v})
                else:
                    if v not in seen_a:
                        seen_a.add(v)
                        area.append({"n": title or v, "v": v})
                continue
            m = re.search(r"/year/(\d{4})\.html", href)
            if m:
                y = m.group(1)
                if y not in seen_y:
                    seen_y.add(y)
                    years.append({"n": y, "v": y})
                continue
            m = re.search(r"/vod/show/by/([a-z]+)/id/" + tid_re + r"\.html", href)
            if m:
                v = m.group(1)
                if v not in seen_s:
                    seen_s.add(v)
                    sorts.append({"n": SORT_NAMES.get(v, v), "v": v})

        groups = []
        if cls:
            groups.append({"key": "class", "name": "剧情", "value": [{"n": "全部", "v": ""}] + cls})
        if area:
            groups.append({"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}] + area})
        groups.append({"key": "year", "name": "年份",
                       "value": [{"n": "全部", "v": ""}] + (years or YEARS[1:])})
        groups.append({"key": "by", "name": "排序", "value": sorts or SORTS})
        return groups

    def _filter_panel(self, tid):
        """每个分类的筛选面板（30 分钟缓存）。网络异常时返回空，由调用方兜底。"""
        key = "fp|" + str(tid)
        cached = self._cache_get(self._filterCache, key, 30 * 60 * 1000)
        if cached is not None:
            return cached
        try:
            html = self._get(SITE + "/index.php/vod/show/id/" + str(tid) + ".html",
                             {"User-Agent": UA_PC, "Referer": SITE + "/"})
            groups = self._parse_filter_panel(html, tid)
        except Exception:
            groups = []
        if groups:
            self._cache_set(self._filterCache, key, groups, 32)
        return groups

    def _build_filters(self, cats):
        """并发抓各分类的筛选面板（实测 6 个分类并发约 0.3s，之后走 30 分钟缓存）。"""
        tids = [c["type_id"] for c in cats]
        panels = {}
        if tids:
            try:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=min(6, len(tids))) as ex:
                    for tid, g in zip(tids, ex.map(self._filter_panel, tids)):
                        panels[tid] = g or []
            except Exception:
                panels = {}
        out = {}
        for tid in tids:
            g = panels.get(tid)
            out[tid] = g if g else [dict(x) for x in FILTERS["__default__"]]
        return out

    # ======================== 入口：首页/分类/搜索 ========================
    def _cleanup_all(self):
        """木偶在每个入口开头都清一次上一批转存文件；保护期与互斥在 netdisk 内部。"""
        nd = self._nd()
        if nd is None:
            return
        try:
            nd.cleanup()
        except Exception:
            pass

    def _home_html(self):
        """首页 HTML 短缓存：进首页会连调 homeContent + homeVideoContent，不缓存等于拉两遍 600KB。"""
        html = self._cache_get(self._homeHtmlCache, "home", 60 * 1000)
        if html is None:
            html = self._http() or ""
            if html:
                self._cache_set(self._homeHtmlCache, "home", html, 1)
        return html

    def _ensure_cf(self):
        """进 category/search/detail 前先摸一次首页，让宿主会话拿到 CF cookie（首页有 60s 缓存）。"""
        if getattr(self, "_cfWarmed", False):
            return
        try:
            if self._home_html():
                self._cfWarmed = True
        except Exception:
            pass

    def homeContent(self, filter):
        self._cleanup_all()
        if not self._catCache:
            cats = self._parse_cats(self._home_html())
            self._catCache = cats or [dict(c) for c in CATEGORIES]
        return {"class": self._catCache, "filters": self._build_filters(self._catCache)}

    def homeVideoContent(self):
        self._cleanup_all()
        html = self._home_html()
        return {"list": self._parse_list(html)[:24]}

    def categoryContent(self, tid, pg, filter, extend):
        self._cleanup_all()
        self._ensure_cf()
        p = int(pg) if str(pg).isdigit() else 1
        url = self._cat_url(tid, p, extend or {})
        html = self._site_get(url)
        items = self._parse_list(html)
        pc = max(self._page_count(html), p)
        return {"list": items, "page": p, "pagecount": pc,
                "limit": len(items) or 24, "total": (len(items) or 24) * pc}

    def searchContent(self, key, quick, pg="1"):
        self._cleanup_all()
        self._ensure_cf()
        p = int(pg) if str(pg).isdigit() else 1
        kw = urllib.parse.quote(key or "")
        ck = kw + "::" + str(p)
        cached = self._cache_get(self._searchCache, ck, 3 * 60 * 1000)
        if cached is not None:
            return cached

        # 1) 优先 ajax/suggest：JSON、无限流、id 与详情页一致，秒出结果
        sug = self._search_suggest(key or "")
        if sug is not None:
            res = {"list": sug, "page": 1, "pagecount": 1,
                   "limit": len(sug) or 24, "total": len(sug)}
            self._cache_set(self._searchCache, ck, res, 100)
            return res

        # 2) suggest 不可用时退回 HTML 搜索页；站点限制「搜索间隔 8 秒」，被限流就等一轮再试
        hdr = {"User-Agent": UA_PC, "Referer": SITE + "/"}
        urls = [
            SITE + "/index.php/vod/search/page/" + str(p) + "/wd/" + kw + ".html",
            SITE + "/index.php/vod/search.html?wd=" + kw + "&page=" + str(p),
        ]
        html = ""
        items = []
        for attempt in range(2):
            if attempt:
                time.sleep(8.2)
            for i, u in enumerate(urls):
                if i:
                    time.sleep(0.8)
                html = self._get(u, hdr)
                if self._is_rate_limited(html):
                    items = []
                    break            # 限流：换地址也没用，直接进入下一轮等待
                items = self._parse_list(html)
                if items:
                    break
                # 页面完整却没有结果 = 真的搜不到，不必再试
                if html and len(html) >= self.SITE_PAGE_MIN:
                    break
            if items or (html and not self._is_rate_limited(html) and len(html) >= self.SITE_PAGE_MIN):
                break
        res = {"list": items, "page": p, "pagecount": self._page_count(html),
               "limit": len(items) or 24, "total": len(items) or 24}
        if items:
            self._cache_set(self._searchCache, ck, res, 100)
        return res

    def _search_suggest(self, key):
        """站点 suggest 接口。返回 list（可能为空=确实没结果）；接口不可用时返回 None 表示需兜底。"""
        url = SITE + "/index.php/ajax/suggest?mid=1&wd=" + urllib.parse.quote(key or "")
        raw = self._get(url, {"User-Agent": UA_PC, "Referer": SITE + "/",
                              "X-Requested-With": "XMLHttpRequest"})
        j = self._json(raw)
        if not isinstance(j, dict) or "list" not in j:
            return None
        out = []
        for it in (j.get("list") or []):
            it = it or {}
            vid = str(it.get("id") or "")
            name = self._strip(it.get("name"))
            if not vid or not name:
                continue
            out.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": self._abs(it.get("pic")),
                "vod_year": "",
                "vod_remarks": "",
            })
        return out


    # ======================== 入口：详情 ========================
    def _tag_val(self, html, label):
        pat = (r'<span[^>]*class="[^"]*video-info-itemtitle[^"]*"[^>]*>\s*' + re.escape(label) +
               r'\s*[:：]?\s*</span>[\s\S]{0,80}?<div[^>]*class="[^"]*video-info-item[^"]*"[^>]*>'
               r'([\s\S]*?)</div>')
        return self._strip(self._pick(pat, html))

    @staticmethod
    def _names(s):
        """把「/ 张三/李四/」这类多值字段清理成「张三 李四」。"""
        return re.sub(r"[/\s]+", " ", str(s or "")).strip()

    def detailContent(self, ids):
        self._cleanup_all()
        self._ensure_cf()
        if not ids:
            return {"list": []}
        raws = ids if isinstance(ids, list) else [ids]
        out = []
        # FongMi 正常只传 1 个 id；若宿主批量传，限制条数避免云盘 API 串行拖到超时
        for raw in raws[:5]:
            try:
                item = self._detail_one(raw)
            except Exception:
                item = None
            if item:
                out.append(item)
        return {"list": out}

    def _detail_one(self, raw):
        vid = str(raw).split(",")[0].split("|")[0]
        key = "index.php/vod/detail/id/" + vid + ".html"
        html = self._cache_get(self._detailHtmlCache, key, TTL_HTML)
        if html is None:
            html = self._site_get(SITE + "/" + key)
            if html and len(html) >= self.SITE_PAGE_MIN:
                self._cache_set(self._detailHtmlCache, key, html, 20)  # 详情页 HTML 约 600KB/条，限 20 条
        if not html:
            return None

        name = self._strip(self._pick(r'<h1[^>]*class="[^"]*page-title[^"]*"[^>]*>([\s\S]*?)</h1>', html))
        pic = (self._pick(r'<div[^>]*class="[^"]*video-cover[^"]*"[\s\S]*?<img[^>]*\bdata-src=["\']([^"\']+)["\']', html)
               or self._pick(r'<div[^>]*class="[^"]*video-cover[^"]*"[\s\S]*?<img[^>]*\bdata-original=["\']([^"\']+)["\']', html)
               or self._pick(r'<div[^>]*class="[^"]*video-cover[^"]*"[\s\S]*?<img[^>]*\bsrc=["\']([^"\']+)["\']', html)
               or self._pick(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html))
        pic = self._abs(pic)
        director = self._names(self._tag_val(html, "导演"))
        actor = self._names(self._tag_val(html, "主演"))
        year = self._tag_val(html, "年代")
        remarks = (self._tag_val(html, "备注") or self._tag_val(html, "连载")
                   or self._tag_val(html, "更新") or self._tag_val(html, "状态"))
        area = self._strip(self._pick(
            r'<a[^>]+class="tag-link"[^>]+href="[^"]*/vod/show/area/[^"]+"[^>]*>([\s\S]*?)</a>', html))
        # 类型：限定 tag-link 锚点，否则会误取到顶部导航的首个分类
        type_name = ""
        for m in re.finditer(r"<a\b[^>]*>([\s\S]*?)</a>", html):
            tag = m.group(0)
            if "/vod/type/id/" in tag and "tag-link" in tag:
                type_name = self._strip(m.group(1))
                break
        desc = self._strip(self._pick(r'<p[^>]*class="[^"]*zkjj_a[^"]*"[^>]*>([\s\S]*?)</p>', html))
        desc = desc.replace("[展开全部]", "").replace("[收起部分]", "")

        # 分享链接 → 过滤可用网盘 → 去重（网盘规则全在 netdisk 模块里）
        nd = self._nd()
        share_urls = []
        seen_share = set()
        for u in self._share_links(html):
            if not u or u in seen_share:
                continue
            info0 = nd.parse_share(u) if nd is not None else None
            if not info0 or not nd.ALLOWED_KINDS.get(info0.get("kind")):
                continue
            seen_share.add(u)
            share_urls.append(u)

        # 既无标题又无网盘分享：视为无效/已删除页面，返回空（避免产出空白条目）
        if not name and not share_urls:
            return None

        # 按网盘分组构建分集
        labels_spec = []      # [(label, kind, share_url)]
        kind_seq = {}
        for u in share_urls:
            info = nd.parse_share(u)
            if not info or not nd.ALLOWED_KINDS.get(info.get("kind")):
                continue
            kind = info["kind"]
            base = nd.DRIVE_NAMES.get(kind, kind)
            seq = kind_seq.get(kind, 0)
            kind_seq[kind] = seq + 1
            label = base if seq == 0 else (base + str(seq + 1))
            labels_spec.append((label, kind, u))

        # 并行拉各线路分集（模块内线程池，对应木偶的 Promise.all）
        eps_map = nd.episodes_many(labels_spec) if nd is not None else {}

        groups = {}
        order = []
        kind_of = {}
        for label, kind, u in labels_spec:
            if label not in groups:
                groups[label] = []
                order.append(label)
            kind_of[label] = kind
            groups[label].extend(eps_map.get(label) or [])

        labels = sorted(order, key=lambda l: (nd.KIND_ORDER.get(kind_of.get(l), 99) if nd else 99, l))
        from_arr = []
        url_arr = []
        for l in labels:
            eps = groups.get(l) or []
            if not eps:
                continue
            from_arr.append(l)
            url_arr.append("#".join("%s$%s" % (e["name"], e["id"]) for e in eps))

        content = desc
        if not from_arr:
            if nd is None:
                # 依赖没加载：明确告诉用户缺什么，而不是显示「无分享」
                content = "缺少 netdisk.py 网盘模块：请把它与 spider.py 放在同一目录后重启源"
            else:
                content = "本片暂无可解析的网盘分享（夸克/UC/百度）"
            if desc:
                content += "\n" + desc

        vod = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_year": year,
            "vod_area": area,
            "vod_remarks": remarks,
            "vod_actor": actor,
            "vod_director": director,
            "vod_content": content,
            "type_name": type_name,
            "vod_play_from": "$$$".join(from_arr),
            "vod_play_url": "$$$".join(url_arr),
        }
        return vod


    # ======================== 入口：播放 ========================
    def playerContent(self, flag, id, vipFlags):
        parts = str(id or "").split("|")
        kind = parts[0] if parts else ""
        share_url = parts[1] if len(parts) > 1 else ""
        fid = parts[2] if len(parts) > 2 else ""
        hint = parts[3] if len(parts) > 3 else ""

        nd = self._nd()
        if nd is not None:
            try:
                r = nd.resolve(kind, share_url, fid, hint)
            except Exception:
                r = None
            if r:
                direct, header, hls = r
                res = {"parse": 0, "url": direct, "header": header, "jx": 0}
                # 只有夸克会给 m3u8；UC/百度直链是 MP4，一律不设 format（设错直接黑屏）
                if hls:
                    res["format"] = "application/x-mpegURL"
                return res

        # 无有效直链：回退分享链接（parse:1 交云盘 App）
        return {"parse": 1, "url": share_url or id, "jx": 0}

    # ======================== 释放 ========================
    def destroy(self):
        """会话结束：清掉待删队列里的转存文件（best-effort）。实例保留，destroy 后仍可播放。"""
        nd = getattr(self, "_ndObj", None)
        if nd is not None:
            try:
                nd.destroy()
            except Exception:
                pass

    # ======================== 宿主可选接口（与木偶.js 对齐） ========================
    def proxy(self, segments, headers):
        return {}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        return ""
