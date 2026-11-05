# -*- coding: utf-8 -*-
"""
拾光影视 Python Spider — 兼容 FongMi/TV (T3) 与 WebHomeTV / PeekPro (T4)
站点: https://tv.time1080.xyz/

特性:
  - 聚合多采集源（官采蓝光/360资源/4k60帧/非凡/电影天堂/豆瓣）
  - 全 GET 接口，无需加密
  - 首页推荐 + 关键词分类浏览 + 全源搜索
  - 直链 m3u8 直接播放 / 官源走 BFQ 解析（AES-CBC 解密）
  - 详情页自动补充其他源的直连线路（解决官源播放失败问题）
  - 详情页 3 次重试（解决间歇性"未找到数据"）
  - 自动过滤坏 CDN 线路，跨源补充可用直连（dytt/mj）
  - 分类与网站首页一致（国产剧/喜剧片/动作片/悬疑片/爱情片/动漫/综艺）
  - 分类并发多源搜索，自动合并去重，解决间歇性无内容
  - 首页 5 分钟缓存，全链路短超时，SSL 禁验证
"""

import sys
import json
import re
import time
import base64
import threading

sys.path.append('..')

# ===== 兼容导入 =====
try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass

    class Spider:
        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            kw.pop('verify', None)
            r = _rq.get(url, headers=headers, timeout=timeout, verify=False, **kw)
            r.encoding = 'utf-8'
            return r

from urllib.parse import quote, urlencode


# ============================================================
# 常量
# ============================================================

HOST = "https://tv.time1080.xyz"
API = HOST + "/api/proxy.php"
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

# 数据源显示名称
SOURCE_NAMES = {
    "qilin": "官采蓝光",
    "360zy": "360资源",
    "mj": "4k60帧",
    "ff": "非凡",
    "dytt": "电影天堂",
}

# 分类列表（type_name = 显示名称与网站一致, type_id = 搜索关键词）
# 注意: "喜剧片"等带"片"的关键词搜索返回0结果，用短词代替
# "国产剧"搜索仅1条结果，改用"电视剧"(26条)
CLASSES = [
    {"type_name": "国产剧", "type_id": "国产剧"},
    {"type_name": "喜剧片", "type_id": "喜剧"},
    {"type_name": "动作片", "type_id": "动作"},
    {"type_name": "悬疑片", "type_id": "悬疑"},
    {"type_name": "爱情片", "type_id": "爱情"},
    {"type_name": "动漫", "type_id": "动漫"},
    {"type_name": "综艺", "type_id": "综艺"},
]

# 分类配置：type_id → {home_cat: 首页API分类名, search_kw: 搜索关键词}
# home_cat 用于第1页从首页API获取内容（与网站一致）
# search_kw 用于搜索获取更多内容（第1页合并 + 第2页起专用）
CATEGORY_CONFIG = {
    "国产剧": {"home_cat": "国产剧", "search_kw": "电视剧"},
    "喜剧":   {"home_cat": "喜剧片", "search_kw": "喜剧"},
    "动作":   {"home_cat": "动作片", "search_kw": "动作"},
    "悬疑":   {"home_cat": "悬疑片", "search_kw": "悬疑"},
    "爱情":   {"home_cat": None,     "search_kw": "爱情"},
    "动漫":   {"home_cat": "动漫",   "search_kw": "动漫"},
    "综艺":   {"home_cat": None,     "search_kw": "综艺"},
}

# 通用数据源筛选器（所有分类共用）
_SOURCE_FILTER = [
    {"key": "source", "name": "数据源", "value": [
        {"n": "全部源", "v": "all"},
        {"n": "官采蓝光", "v": "qilin"},
        {"n": "360资源", "v": "360zy"},
        {"n": "4k60帧", "v": "mj"},
    ]},
]

FILTERS = {c["type_id"]: _SOURCE_FILTER for c in CLASSES}

# 搜索默认源
SEARCH_DEFAULT_SOURCES = "qilin,360zy,mj"


# ============================================================
# Spider 主类
# ============================================================

class Spider(Spider):

    def getName(self):
        return "拾光影视"

    # ===== 初始化 =====
    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ""
        else:
            self.extend = extend or ""

        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "application/json, text/plain, */*",
        }

        # 首页推荐缓存（5 分钟）
        self._home_cache = []
        self._home_cache_time = 0

        # 首页 API 原始数据缓存（供分类页第1页使用，5 分钟）
        self._home_data = None
        self._home_data_time = 0

        # 搜索频率控制（避免触发验证码）
        self._last_search_time = 0

    def _get_home_data(self):
        """获取首页 API 数据（带缓存）"""
        now = int(time.time())
        if self._home_data and now - self._home_data_time < 300:
            return self._home_data
        data = self._get_json(API + "?action=home", timeout=10)
        if data and data.get("success"):
            self._home_data = data
            self._home_data_time = now
        return data

    # ===== 网络工具 =====
    def _rsp_text(self, rsp):
        try:
            return rsp.text
        except Exception:
            try:
                return rsp.content.decode('utf-8', 'ignore')
            except Exception:
                return ""

    def _get_json(self, url, timeout=12):
        """GET 请求返回 JSON dict，异常返回 None"""
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            text = self._rsp_text(rsp)
            if not text:
                return None
            return json.loads(text)
        except Exception:
            return None

    def _txt(self, url, referer=None, timeout=12):
        """GET 文本，异常返回空"""
        headers = dict(self.header)
        if referer:
            headers["Referer"] = referer
        try:
            rsp = self.fetch(url, headers=headers, timeout=timeout)
            return self._rsp_text(rsp)
        except Exception:
            return ""

    def _match(self, pattern, text, flags=0):
        m = re.search(pattern, text, flags)
        return m.group(1) if m else ""

    # 已知不可用的 CDN 域名（SSL/服务挂了）
    _BROKEN_CDN_DOMAINS = [
        "vod.guoluche.com",    # 360zy CDN - SSL EOF
        "vod.360zyx.vip",      # 360zy CDN - SSL EOF
    ]

    # ===== 媒体判断 =====
    def _is_direct_media(self, url):
        url = (url or "").lower()
        return ".m3u8" in url or ".mp4" in url or ".flv" in url or ".mkv" in url

    def _is_broken_cdn(self, url):
        """检查 URL 是否指向已知挂掉的 CDN"""
        url_lower = (url or "").lower()
        return any(d in url_lower for d in self._BROKEN_CDN_DOMAINS)

    def _extract_referer(self, url):
        """从 URL 提取 origin 作为 Referer（比固定 Referer 更兼容）"""
        try:
            if "://" in url:
                scheme = url.split("://")[0]
                host = url.split("://")[1].split("/")[0]
                return scheme + "://" + host + "/"
        except Exception:
            pass
        return HOST + "/"

    def _is_official_source(self, url):
        url = (url or "").lower()
        keys = (
            "mgtv.com", "youku.com", "iqiyi.com", "qiyi.com",
            "v.qq.com", "qq.com", "bilibili.com", "le.com",
            "sohu.com", "pptv.com", "1905.com",
        )
        return any(k in url for k in keys) and not self._is_direct_media(url)

    # ===== BFQ 官源解析 =====
    def _aes_cbc_decrypt_text(self, cipher_text):
        try:
            from Crypto.Cipher import AES
            key = cipher_text[-32:-16].encode("utf-8")
            iv = cipher_text[-16:].encode("utf-8")
            data = base64.b64decode(cipher_text[:-32])
            raw = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
            pad = raw[-1] if raw else 0
            if 0 < pad <= 16:
                raw = raw[:-pad]
            return raw.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _resolve_official_to_media(self, src_url):
        """用 bfq.txnp.cn 解析官源地址"""
        if not src_url or not self._is_official_source(src_url):
            return ""
        try:
            page_url = "https://bfq.txnp.cn/player?url=" + quote(src_url, safe="")
            referer = "https://bfq.txnp.cn/excessive?url=" + quote(src_url, safe="")
            html = self._txt(page_url, referer=referer, timeout=12)
            result = self._match(r'let\s+result\s*=\s*"([^"]+)"', html, re.S)
            if not result:
                return ""
            text = self._aes_cbc_decrypt_text(result)
            if not text:
                return ""
            data = json.loads(text)
            video = ((data.get("video_info") or {}).get("video") or {})
            media = (video.get("url") or "").replace("\\/", "/")
            if media and self._is_direct_media(media):
                return media
        except Exception:
            pass
        return ""

    # ===== 内容字段处理 =====
    def _get_content(self, d):
        """处理 content 字段，兼容字符串和 {p: "..."} 对象格式"""
        content = d.get("content", "")
        if isinstance(content, dict):
            return content.get("p", "") or content.get("content", "") or ""
        return str(content) if content else ""

    def _get_str_field(self, d, field):
        """处理 actor/director 字段，兼容字符串和数组格式"""
        val = d.get(field, "")
        if isinstance(val, list):
            return ", ".join(str(v) for v in val if v)
        return str(val) if val else ""

    # ===== 其他工具 =====
    def _pic(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return HOST + url
        return url

    def _strip_tags(self, s):
        return re.sub(r'<[^>]+>', '', s or '').strip()

    def _card(self, v):
        """API 视频卡片 -> TVBox 格式，vod_id 编码为 source_id"""
        src = v.get("source", "")
        vid = v.get("id", "")
        return {
            "vod_id": "%s_%s" % (src, vid),
            "vod_name": v.get("name", ""),
            "vod_pic": self._pic(v.get("pic", "")),
            "vod_remarks": v.get("remarks", "") or v.get("year", "") or "HD",
        }

    # ===== 解析 play_url 为线路列表 =====
    def _parse_play_url(self, play_url_raw, episodes=None):
        """解析 play_url 字符串为 (play_from_list, play_url_list)"""
        if not play_url_raw and episodes:
            # 从 episodes 结构构建
            lines = []
            for eg in episodes:
                eps = eg.get("episodes", []) or []
                ep_strs = ["%s$%s" % (e.get("name", str(i+1)), e.get("url", "")) for i, e in enumerate(eps)]
                if ep_strs:
                    lines.append("#".join(ep_strs))
            play_url_raw = "$$$".join(lines)

        if not play_url_raw:
            return [], []

        lines = play_url_raw.split("$$$")
        play_from_parts = []
        play_url_parts = []

        for i, line in enumerate(lines):
            eps = line.split("#")
            ep_list = []
            for ep in eps:
                if "$" in ep:
                    ep_name, ep_url = ep.split("$", 1)
                    ep_list.append("%s$%s" % (ep_name, ep_url))
                elif ep.strip():
                    ep_list.append("第%s集$%s" % (len(ep_list)+1, ep.strip()))

            if ep_list:
                group_name = ""
                if episodes and i < len(episodes):
                    group_name = episodes[i].get("group", "") or ""
                if not group_name:
                    group_name = "线路%d" % (i + 1)
                play_from_parts.append(group_name)
                play_url_parts.append("#".join(ep_list))

        return play_from_parts, play_url_parts

    # ===== 跨源补充直连线路 =====
    def _fetch_cross_source_lines(self, movie_name, exclude_source=""):
        """
        并发搜索同名影片在其他源中的直连 m3u8 线路。
        只保留有直链 m3u8 且 CDN 可用的源。
        返回 (play_from_list, play_url_list)
        """
        if not movie_name:
            return [], []

        results = {}
        threads = []

        def _search_one_source(src):
            try:
                search_url = API + "?action=search&wd=%s&source=%s&page=1" % (quote(movie_name), src)
                data = self._get_json(search_url, timeout=8)
                if not data or not data.get("success"):
                    return
                search_results = data.get("results", []) or []
                if not search_results:
                    return

                # 精确匹配名称，否则取第一个
                matched = None
                for r in search_results:
                    if r.get("name") == movie_name:
                        matched = r
                        break
                if not matched:
                    matched = search_results[0]

                vid = matched.get("id")
                if not vid:
                    return

                detail_url = API + "?action=detail&source=%s&id=%s" % (src, vid)
                detail_data = self._get_json(detail_url, timeout=10)
                if not detail_data or not detail_data.get("success"):
                    return
                details = detail_data.get("details", []) or []
                if not details:
                    return

                d = details[0]
                play_url_raw = d.get("play_url", "") or ""
                eps = d.get("episodes", []) or []
                pf, pu = self._parse_play_url(play_url_raw, eps)

                # 只保留直链 m3u8 且 CDN 可用的线路
                if pu:
                    first_ep = pu[0].split("#")[0] if pu[0] else ""
                    first_url = first_ep.split("$", 1)[1] if "$" in first_ep else ""
                    if self._is_direct_media(first_url) and not self._is_broken_cdn(first_url):
                        source_display = SOURCE_NAMES.get(src, src)
                        results[src] = (source_display, pu[0])
            except Exception:
                pass

        # 只搜索有直链 m3u8 的源（dytt 最稳定，mj 次之）
        # 360zy CDN 已挂，ff 返回 share URL 非直链，均不使用
        cross_sources = ["dytt", "mj"]
        for src in cross_sources:
            if src == exclude_source:
                continue
            t = threading.Thread(target=_search_one_source, args=(src,))
            threads.append(t)
            t.start()

        # 等待所有线程完成（最多 12 秒）
        for t in threads:
            t.join(timeout=12)

        play_from = []
        play_url = []
        for src in cross_sources:
            if src in results:
                pf, pu = results[src]
                play_from.append(pf)
                play_url.append(pu)

        return play_from, play_url

    # ============================================================
    # 首页
    # ============================================================

    def homeContent(self, filter):
        return {
            "class": CLASSES,
            "filters": FILTERS,
        }

    def homeVideoContent(self):
        """首页推荐：从首页 API 聚合，带 5 分钟缓存"""
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < 300:
            return {"list": self._home_cache[:72]}

        data = self._get_home_data()
        videos = []
        seen = set()
        if data and data.get("success"):
            cats = data.get("categories", {}) or {}
            for cat_name, items in cats.items():
                if not isinstance(items, list):
                    continue
                for v in items:
                    vid = v.get("id")
                    src = v.get("source", "")
                    key = "%s_%s" % (src, vid)
                    if key not in seen:
                        seen.add(key)
                        videos.append(self._card(v))

        self._home_cache = videos[:72]
        self._home_cache_time = now
        return {"list": self._home_cache}

    # ============================================================
    # 分类列表
    # ============================================================

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            # 解析 extend
            ext = {}
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                elif isinstance(extend, str):
                    try:
                        ext = json.loads(extend)
                    except Exception:
                        ext = {}

            user_source = ext.get("source", "all")
            cfg = CATEGORY_CONFIG.get(tid, {})
            search_kw = cfg.get("search_kw", tid)
            home_cat = cfg.get("home_cat")

            # 搜索策略：
            # 第一波：并发请求 3 个快速单源（360zy/mj/qilin），合并结果
            # 第二波：如果第一波全部无结果，依次尝试 all → ff → dytt
            # 避免一次并发太多请求导致 API 限流
            fast_sources = ["360zy", "mj", "qilin"]
            if user_source != "all" and user_source not in fast_sources:
                fast_sources.insert(0, user_source)

            merged = {}          # name -> result（按片名去重）
            state = {"max_total": 0, "paginated_total": 0, "has_paginated": False}
            lock = threading.Lock()

            def _try_source(src):
                params = {
                    "action": "search",
                    "wd": search_kw,
                    "page": str(page),
                    "source": src,
                }
                url = API + "?" + urlencode(params)
                data = self._get_json(url, timeout=8)
                if data and data.get("success"):
                    r = data.get("results", []) or []
                    if r:
                        with lock:
                            for v in r:
                                name = v.get("name", "")
                                if name and name not in merged:
                                    merged[name] = v
                            t = int(data.get("total", len(r)))
                            if t > state["max_total"]:
                                state["max_total"] = t
                            # 返回 <= 20 条的源按页分页，用其 total 计算 pagecount
                            # 返回 > 20 条的源一次返回全部，不参与翻页计算
                            if len(r) <= 20:
                                state["has_paginated"] = True
                                if t > state["paginated_total"]:
                                    state["paginated_total"] = t

            # 第一波：并发请求快速源（3-4 个线程）
            threads = []
            for src in fast_sources:
                t = threading.Thread(target=_try_source, args=(src,))
                threads.append(t)
                t.start()
            for t in threads:
                t.join(timeout=8)

            # 第二波：如果快速源都没有结果，依次尝试 all / ff / dytt
            if not merged:
                fallback = ["all"]
                if page == 1:
                    fallback += ["ff", "dytt"]
                for src in fallback:
                    if merged:
                        break
                    _try_source(src)

            results = list(merged.values())
            search_total = state["max_total"] if state["max_total"] > 0 else len(results)

            if not results:
                return {"page": page, "pagecount": 1, "limit": 20, "total": 0, "list": []}

            search_vods = [self._card(v) for v in results]

            # 第 1 页：合并首页 API 内容（与网站一致）+ 搜索结果
            if page == 1 and home_cat:
                home_data = self._get_home_data()
                if home_data and home_data.get("success"):
                    cats = home_data.get("categories", {}) or {}
                    home_items = cats.get(home_cat, []) or []
                    home_vods = [self._card(v) for v in home_items]
                    seen_ids = set()
                    merged_vods = []
                    for v in home_vods + search_vods:
                        vid = v.get("vod_id", "")
                        if vid not in seen_ids:
                            seen_ids.add(vid)
                            merged_vods.append(v)
                    search_vods = merged_vods
                    # 首页内容是第1页额外补充，不影响翻页数

            # pagecount 计算：
            # - 有分页源（<= 20条/页）：基于分页源的最大 total
            # - 无分页源（全部一次返回 > 20 条）：pagecount=1
            if state["has_paginated"]:
                pagecount = max(1, (state["paginated_total"] + 19) // 20)
            else:
                pagecount = 1

            return {
                "list": search_vods,
                "page": page,
                "pagecount": pagecount,
                "limit": 20,
                "total": search_total,
            }
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": 20, "total": 0, "list": []}

    # ============================================================
    # 详情页
    # ============================================================

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = ids[0]

        # vod_id 格式: "source_id"
        parts = str(vod_id).split("_", 1)
        if len(parts) != 2:
            return {"list": []}
        source, vid = parts[0], parts[1]

        # 带重试逻辑（3 次尝试，间隔 1 秒）
        d = None
        for attempt in range(3):
            url = API + "?action=detail&source=%s&id=%s" % (source, vid)
            data = self._get_json(url, timeout=15)
            if data and data.get("success"):
                details = data.get("details", []) or []
                if details:
                    d = details[0]
                    break
            if attempt < 2:
                time.sleep(1)

        if not d:
            return {"list": []}

        # 解析播放地址
        play_url_raw = d.get("play_url", "") or ""
        eps = d.get("episodes", []) or []
        play_from_parts, play_url_parts = self._parse_play_url(play_url_raw, eps)

        if not play_url_parts:
            return {"list": []}

        # 检测是否包含官源链接（需要 BFQ 解析）或坏 CDN（需要跨源备选）
        has_official = False
        has_broken_cdn = False
        for pu in play_url_parts:
            for ep in pu.split("#"):
                if "$" in ep:
                    _, ep_url = ep.split("$", 1)
                    if self._is_official_source(ep_url):
                        has_official = True
                    if self._is_direct_media(ep_url) and self._is_broken_cdn(ep_url):
                        has_broken_cdn = True

        # 跨源补充直连线路：
        # - 官源链接（qilin 的 qq/iqiyi）需要直连备选
        # - 坏 CDN（360zy 全挂）需要可用源备选
        if has_official or has_broken_cdn:
            movie_name = d.get("name", "")
            cross_from, cross_url = self._fetch_cross_source_lines(movie_name, exclude_source=source)
            if cross_url:
                play_from_parts.extend(cross_from)
                play_url_parts.extend(cross_url)

        # 线路排序与过滤：
        # - 直连 m3u8 且 CDN 可用 → 放前面（优先播放）
        # - 坏 CDN 的直链 → 丢弃（播放不了）
        # - 官源链接（qq/iqiyi）→ 放后面（可能有限或解析失败）
        direct_from = []
        direct_url = []
        official_from = []
        official_url = []
        for pf, pu in zip(play_from_parts, play_url_parts):
            # 检查该线路第一个 URL 是否是直连媒体
            first_ep = pu.split("#")[0] if pu else ""
            first_url = first_ep.split("$", 1)[1] if "$" in first_ep else ""
            if self._is_direct_media(first_url):
                if self._is_broken_cdn(first_url):
                    continue  # 跳过坏 CDN 线路
                direct_from.append(pf)
                direct_url.append(pu)
            else:
                official_from.append(pf)
                official_url.append(pu)

        # 直连线路优先，官源线路垫后
        play_from_parts = direct_from + official_from
        play_url_parts = direct_url + official_url

        vod = {
            "vod_id": vod_id,
            "vod_name": d.get("name", ""),
            "vod_pic": self._pic(d.get("pic", "")),
            "type_name": d.get("type", ""),
            "vod_year": d.get("year", ""),
            "vod_area": d.get("area", ""),
            "vod_remarks": d.get("remarks", "") or "HD",
            "vod_actor": self._get_str_field(d, "actor"),
            "vod_director": self._get_str_field(d, "director"),
            "vod_content": self._strip_tags(self._get_content(d))[:500],
            "vod_play_from": "$$$".join(play_from_parts) if play_from_parts else "拾光影视",
            "vod_play_url": "$$$".join(play_url_parts) if play_url_parts else "",
        }
        return {"list": [vod]}

    # ============================================================
    # 搜索
    # ============================================================

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            # 搜索频率控制：两次搜索间隔至少 1 秒
            now = time.time()
            if now - self._last_search_time < 1:
                time.sleep(1.5)
            self._last_search_time = time.time()

            params = {
                "action": "search",
                "wd": key,
                "page": str(page),
                "source": SEARCH_DEFAULT_SOURCES,
            }
            url = API + "?" + urlencode(params)
            data = self._get_json(url, timeout=12)

            if data and data.get("success"):
                results = data.get("results", []) or []
                if results:
                    vods = [self._card(v) for v in results]
                    return {"list": vods}

            # 精确搜索无结果 → 尝试缩短关键词（处理标点符号差异，如逗号/书名号/感叹号）
            # API 搜索要求连续字符匹配，标点符号会打断匹配，所以逐步缩短
            if page == 1 and len(key) > 4:
                # 用前3字搜索（足够精确，又能跳过标点差异）
                short_key = key[:3]
                params["wd"] = short_key
                params["source"] = SEARCH_DEFAULT_SOURCES
                url2 = API + "?" + urlencode(params)
                data2 = self._get_json(url2, timeout=10)
                if data2 and data2.get("success"):
                    results2 = data2.get("results", []) or []
                    # 过滤：只返回名称前3字与搜索关键词前3字匹配的
                    prefix = key[:3]
                    filtered = [v for v in results2 if v.get("name", "")[:3] == prefix]
                    if filtered:
                        vods = [self._card(v) for v in filtered[:20]]
                        return {"list": vods}

            # 仍无结果 → 尝试 source=all 全源搜索
            if page == 1:
                params["wd"] = key
                params["source"] = "all"
                url3 = API + "?" + urlencode(params)
                data3 = self._get_json(url3, timeout=12)
                if data3 and data3.get("success"):
                    results3 = data3.get("results", []) or []
                    if results3:
                        vods = [self._card(v) for v in results3]
                        return {"list": vods}

            return {"list": []}
        except Exception:
            return {"list": []}

    # ============================================================
    # 播放解析
    # ============================================================

    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "playUrl": "", "url": ""}

        play_url = str(id).replace("\\/", "/")

        # 1. 直链媒体（m3u8/mp4）→ 直接播放
        if self._is_direct_media(play_url):
            # 坏 CDN 直接返回 parse=1 交给壳子嗅探
            if self._is_broken_cdn(play_url):
                parse_url = "https://svip.qlplayer.cyou/?url=" + quote(play_url, safe="")
                return {
                    "parse": 1,
                    "playUrl": "",
                    "url": parse_url,
                    "header": {"User-Agent": UA, "Referer": HOST + "/"},
                }
            is_m3u8 = ".m3u8" in play_url.lower()
            # Referer 用 m3u8 自身域名，兼容 CDN 的防盗链检查
            media_referer = self._extract_referer(play_url)
            return {
                "parse": 0,
                "playUrl": "",
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": media_referer,
                },
                "format": "application/x-mpegURL" if is_m3u8 else "",
                "contentType": "application/x-mpegURL" if is_m3u8 else "",
            }

        # 2. 官源（iqiyi/youku/qq/mgtv 等）→ BFQ 解析出真实直链
        if self._is_official_source(play_url):
            resolved = self._resolve_official_to_media(play_url)
            if resolved and self._is_direct_media(resolved):
                is_m3u8 = ".m3u8" in resolved.lower()
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": resolved,
                    "header": {
                        "User-Agent": UA,
                        "Referer": "https://bfq.txnp.cn/",
                    },
                    "format": "application/x-mpegURL" if is_m3u8 else "",
                    "contentType": "application/x-mpegURL" if is_m3u8 else "",
                }
            # BFQ 解析失败 → 交给壳子用解析线路嗅探
            parse_url = "https://svip.qlplayer.cyou/?url=" + quote(play_url, safe="")
            return {
                "parse": 1,
                "playUrl": "",
                "url": parse_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": HOST + "/",
                },
            }

        # 3. 既不是直链也不是官源 → 返回原 URL
        return {
            "parse": 0,
            "playUrl": "",
            "url": play_url,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
            },
        }

    # ===== 本地代理 =====
    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    # ===== 清理 =====
    def destroy(self):
        pass

    def close(self):
        self.destroy()
