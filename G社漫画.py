#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""G社漫画(m.g-mh.org) 采集插件 —— CatVod / TVBox Spider 协议实现。

站点为 Astro 服务端渲染，列表/搜索/详情均可直接解析 HTML；
章节列表与章节图片走 JSON API，图片串经过「三段错位 + 分块反转 +
自定义字符表置换 + base64url」混淆，decode_images() 为纯 Python 还原实现。
"""

import base64
import json
import re
import time
import requests
from html import unescape
from urllib.parse import quote

try:  # 运行环境由框架提供 base.spider
    from base.spider import Spider as BaseSpider
except ImportError:  # 离线调试时的占位基类
    class BaseSpider(object):
        def getProxyUrl(self):
            return ""

# ---------------------------------------------------------------- 图片解码常量
# 加密串结构: 前缀 + [p1][标记kD][p2][标记W4s][p3] + 后缀
_IMG_PREFIX = "J7r"
_IMG_SUFFIX = "nQ"
_IMG_MARK_1 = "kD"
_IMG_MARK_2 = "W4s"
_IMG_BLOCK = 7                       # 分块反转的块长度
# 混淆串使用的字符表 -> 标准 base64url 字符表
_ENC_TABLE = "_-9876543210abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_B64_TABLE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_DECODE_MAP = {c: _B64_TABLE[i] for i, c in enumerate(_ENC_TABLE)}

# 图片 CDN：线路 c / 备用线路 t，line 为 2 时走 nd2 节点
_IMG_HOSTS = {
    "c": {2: "https://c-nd2-1.6wm.top", "default": "https://c-nd3-1.6wm.top"},
    "t": {2: "https://t-nd2-1.6wm.top", "default": "https://t-nd3-1.6wm.top"},
}

_GENRES = [
    {"n": "全部", "v": ""},
    {"n": "韩漫", "v": "kr"}, {"n": "热门漫画", "v": "hots"}, {"n": "国漫", "v": "cn"},
    {"n": "其他", "v": "qita"}, {"n": "日漫", "v": "jp"}, {"n": "欧美", "v": "ou-mei"},
]

_TAGS = [
    {"n": "全部", "v": ""},
    {"n": "穿越", "v": "chuanyue"}, {"n": "纯爱", "v": "chunai"}, {"n": "单女主", "v": "danvzhu"},
    {"n": "都市", "v": "doushi"}, {"n": "复仇", "v": "fuchou"}, {"n": "古风", "v": "gufeng"},
    {"n": "剧情", "v": "juqing"}, {"n": "科幻", "v": "kehuan"}, {"n": "恋爱", "v": "lianai"},
    {"n": "猎奇", "v": "lieqi"}, {"n": "灵异", "v": "lingyi"}, {"n": "冒险", "v": "maoxian"},
    {"n": "魔幻", "v": "mohuan"}, {"n": "末日", "v": "mori"}, {"n": "逆袭", "v": "nixi"},
    {"n": "女神", "v": "nvshen"}, {"n": "奇幻", "v": "qihuan"}, {"n": "青春", "v": "qingchun"},
    {"n": "热血", "v": "rexue"}, {"n": "推理", "v": "tuili"}, {"n": "系统", "v": "xitong"},
    {"n": "修仙", "v": "xiuxian"}, {"n": "玄幻", "v": "xuanhuan"}, {"n": "悬疑", "v": "xuanyi"},
    {"n": "异能", "v": "yineng"}, {"n": "异形", "v": "yixing"}, {"n": "宅向", "v": "zhaixiang"},
    {"n": "战斗", "v": "zhandou"}, {"n": "治愈", "v": "zhiyu"}, {"n": "重生", "v": "zhongsheng"},
]


def decode_images(text):
    """把章节接口返回的加密图片串还原为 [{"order": int, "url": str}, ...]。

    还原步骤与站点前端 chapter-decoder.js 完全一致：
    去首尾标记 -> 按 B/C/D 三段切分 -> 重排为 p3+p1+p2 -> 每 7 字符奇数块反转
    -> 字符表置换 -> base64url 解码 -> UTF-8 -> JSON。
    """
    if not isinstance(text, str) or not text.startswith(_IMG_PREFIX) or not text.endswith(_IMG_SUFFIX):
        return []
    body = text[len(_IMG_PREFIX):-len(_IMG_SUFFIX)]
    total = len(body) - len(_IMG_MARK_1) - len(_IMG_MARK_2)
    size_b = total // 3
    size_c = (total - size_b) // 2
    size_d = (total - size_b) - size_c

    part_1 = body[:size_c]
    if body[size_c:size_c + len(_IMG_MARK_1)] != _IMG_MARK_1:
        return []
    offset = size_c + len(_IMG_MARK_1)
    part_2 = body[offset:offset + size_d]
    offset += size_d
    if body[offset:offset + len(_IMG_MARK_2)] != _IMG_MARK_2:
        return []
    part_3 = body[offset + len(_IMG_MARK_2):]
    if len(part_3) != size_b:
        return []

    mixed = part_3 + part_1 + part_2
    buf = []
    for index, start in enumerate(range(0, len(mixed), _IMG_BLOCK)):
        chunk = mixed[start:start + _IMG_BLOCK]
        buf.append(chunk[::-1] if index % 2 else chunk)
    shuffled = "".join(buf)

    translated = "".join(_DECODE_MAP.get(ch, "") for ch in shuffled)
    padding = "=" * (-len(translated) % 4)
    try:
        raw = base64.b64decode(translated.replace("-", "+").replace("_", "/") + padding)
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


class Spider(BaseSpider):
    """G社漫画采集器。"""

    CLASSES = [
        {"type_id": "manga", "type_name": "全部漫畫"},
        {"type_id": "hots", "type_name": "人氣推薦"},
        {"type_id": "dayup", "type_name": "熱門更新"},
        {"type_id": "newss", "type_name": "最新上架"},
    ]
    FILTERS = [
        {"key": "genre", "name": "類型", "value": _GENRES},
        {"key": "tag", "name": "標籤", "value": _TAGS},
    ]
    API_HOST = "https://v2.apikk.top"

    # ------------------------------------------------------------ 基础
    def getName(self):
        return "G社漫畫"

    def init(self, extend=""):
        self.name = "G社漫畫"
        self.host = "https://m.g-mh.org"
        self.headers = {
            "User-Agent": ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,zh-Hant;q=0.8",
            "Referer": self.host + "/",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.api = self.API_HOST
        self.ext = {}
        if isinstance(extend, str) and extend.strip().startswith("{"):
            try:
                self.ext = json.loads(extend)
            except Exception:
                self.ext = {}
        self._home_cache = None

    def _get(self, url, retry=3, timeout=(8, 20)):
        """带重试的 GET，返回文本；失败返回空串。"""
        for i in range(retry):
            try:
                resp = self.session.get(url, timeout=timeout)
                resp.encoding = resp.apparent_encoding or "utf-8"
                if resp.status_code == 200 and resp.text:
                    return resp.text
            except Exception:
                pass
            time.sleep(0.6 * (i + 1))
        return ""

    def _get_json(self, url, retry=3):
        """请求 JSON 接口，返回 dict；失败返回 {}。"""
        for i in range(retry):
            try:
                resp = self.session.get(url, timeout=(8, 20))
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("status"):
                        return data.get("data") or {}
            except Exception:
                pass
            time.sleep(0.6 * (i + 1))
        return {}

    def _abs(self, url):
        """相对路径补全为绝对地址。"""
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.host + url
        return url

    def _pic(self, url):
        """封面/图片转代理地址，代理不可用时回退原图。"""
        if not url or url.startswith("data:"):
            return ""
        try:
            proxy = self.getProxyUrl()
            if proxy:
                token = base64.b64encode(url.encode("utf-8")).decode("utf-8")
                return proxy + "&url=" + quote(token) + "&type=img"
        except Exception:
            pass
        return url

    # ------------------------------------------------------------ 列表解析
    def _parse_cards(self, html):
        """解析漫画卡片列表，按 slug 去重。"""
        items, seen = [], set()
        pattern = r'<a\s+href="/manga/([A-Za-z0-9\-]+)"[^>]*>(.*?)</a>'
        for match in re.finditer(pattern, html or "", re.S):
            slug, block = match.group(1), match.group(2)
            if slug in seen:
                continue
            title = re.search(r'<h3[^>]*class="[^"]*cardtitle[^"]*"[^>]*>(.*?)</h3>', block, re.S)
            if not title:
                continue
            name = unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip()
            if not name:
                continue
            cover = re.search(r'<img[^>]+src="([^"]+)"', block)
            pic = cover.group(1) if cover else ""
            if pic.startswith("data:"):
                pic = ""
            seen.add(slug)
            items.append({
                "vod_id": slug,
                "vod_name": name,
                "vod_pic": self._pic(self._abs(pic)),
                "vod_remarks": "",
            })
        return items

    @staticmethod
    def _pagecount(html, page, fallback=1):
        """从分页链接推断总页数，站点硬上限 100 页。"""
        nums = [int(x) for x in re.findall(r"/page/(\d+)", html or "")]
        top = max(nums) if nums else 0
        return max(top, page, fallback)

    def _list_url(self, path, page):
        """构造列表/搜索分页地址。"""
        base = path if path.startswith("/") else "/" + path
        if page > 1:
            return f"{self.host}{base}/page/{page}"
        return self.host + base

    def _list_result(self, html, page):
        """统一的分页结果；满页且分页器未给出更大页码时，判定仍有下一页。"""
        items = self._parse_cards(html)
        limit = len(items)
        pagecount = self._pagecount(html, page)
        if limit >= 18 and pagecount <= page:
            pagecount = page + 1
        return {
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": limit * pagecount,
            "list": items,
        }

    # ------------------------------------------------------------ 对外接口
    def homeContent(self, filter):
        result = {"class": self.CLASSES, "list": self._home_items()}
        if filter:
            result["filters"] = {item["type_id"]: self.FILTERS for item in self.CLASSES}
        return result

    def _home_items(self):
        if self._home_cache is None:
            self._home_cache = self._parse_cards(self._get(self.host + "/manga"))
        return self._home_cache

    def homeVideoContent(self):
        return {"list": self._home_items()}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        extend = extend if isinstance(extend, dict) else {}
        genre = str(extend.get("genre") or "").strip()
        tag = str(extend.get("tag") or "").strip()
        if tag:
            path = "/manga-tag/" + tag
        elif genre:
            path = "/manga-genre/" + genre
        else:
            path = "/" + str(tid or "manga")
        return self._list_result(self._get(self._list_url(path, page)), page)

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        if str(quick) not in ("", "0"):  # 快捷搜索只取第一页
            page = 1
        path = "/s/" + quote(str(key))
        return self._list_result(self._get(self._list_url(path, page)), page)

    # ------------------------------------------------------------ 详情
    def _meta(self, html):
        """优先取 ld+json(ComicSeries)，回退 meta 标签。"""
        for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html or "", re.S):
            try:
                data = json.loads(block)
            except Exception:
                continue
            if data.get("@type") == "ComicSeries":
                return data
        return {}

    def _manga_id(self, html):
        """从详情页取出站内漫画 ID（章节接口需要）。"""
        match = re.search(r'data-mid="(\d+)"', html or "")
        return match.group(1) if match else ""

    def _chapters(self, mid):
        """调用章节接口，返回 [(标题, mid@cid), ...]。"""
        if not mid:
            return []
        data = self._get_json(f"{self.api}/api/v2/manga/get?mid={mid}&mode=all")
        out = []
        for item in (data.get("chapters") or []):
            attrs = item.get("attributes") or {}
            cid, title = str(item.get("id") or ""), unescape(str(attrs.get("title") or "")).strip()
            if cid and title:
                out.append((title, f"{mid}@{cid}"))
        return out

    def detailContent(self, ids):
        result = {"list": []}
        ids = ids if isinstance(ids, list) else [ids]
        for slug in ids:
            slug = str(slug).split("$")[0].split("#")[0].strip()
            if not slug:
                continue
            html = self._get(f"{self.host}/manga/{slug}")
            if not html:
                continue
            meta = self._meta(html)
            name = unescape(str(meta.get("name") or "")).strip()
            if not name:
                title = re.search(r"<title>(.*?)</title>", html, re.S)
                name = unescape(title.group(1)).strip() if title else slug
            name = re.sub(r"\s*[-|]\s*G社漫畫\s*$", "", name).strip() or slug

            desc = unescape(str(meta.get("description") or "")).strip()
            genres = meta.get("genre") or []
            authors = [a.get("name", "") for a in (meta.get("author") or []) if isinstance(a, dict)]
            parts = []
            if genres:
                parts.append("類型：" + ",".join(str(g) for g in genres))
            if authors:
                parts.append("作者：" + ",".join(a for a in authors if a))
            content = "\n".join([desc] + parts).strip()

            chapters = self._chapters(self._manga_id(html))
            result["list"].append({
                "vod_id": slug,
                "vod_name": name,
                "vod_pic": self._pic(self._abs(str(meta.get("image") or ""))),
                "vod_content": content,
                "vod_play_from": "漫畫",
                "vod_play_url": "#".join(t + "$" + u for t, u in chapters),
                "vod_remarks": f"{len(chapters)}章" if chapters else "章節下架",
            })
        return result

    # ------------------------------------------------------------ 播放/图片
    def _chapter_images(self, mid, cid):
        """取章节图片绝对地址，失败时自动切换备用线路。"""
        data = self._get_json(f"{self.api}/api/v2/chapter/getinfo?m={mid}&c={cid}")
        info = (data.get("info") or {}) if isinstance(data, dict) else {}
        images = info.get("images") or {}
        raw = images.get("images") if isinstance(images, dict) else None
        line = images.get("line") if isinstance(images, dict) else None
        decoded = decode_images(raw) if isinstance(raw, str) else []
        try:
            line = int(line)
        except (TypeError, ValueError):
            line = 1
        urls = []
        for item in decoded:
            path = item.get("url") if isinstance(item, dict) else None
            if path:
                urls.append(str(path))
        return urls, line

    @staticmethod
    def _image_host(line, route):
        hosts = _IMG_HOSTS.get(route) or _IMG_HOSTS["c"]
        return hosts.get(line) or hosts["default"]

    def playerContent(self, flag, id, vipFlags):
        mid, _, cid = str(id or "").strip().partition("@")
        header = json.dumps(self.headers)
        if not (mid.isdigit() and cid.isdigit()):
            return {"parse": 0, "url": "", "header": header}
        urls, line = self._chapter_images(mid, cid)
        if not urls:
            return {"parse": 0, "url": "", "header": header}
        host = self._image_host(line, "c")
        pics = [self._pic(host + u) if u.startswith("/") else self._pic(u) for u in urls]
        return {"parse": 0, "url": "pics://" + "&&".join(pics), "header": header}

    def localProxy(self, param):
        """图片代理：带 Referer 拉取站点图片，主线路失败自动切备用线路。"""
        try:
            data = json.loads(param) if isinstance(param, str) else (param or {})
        except Exception:
            data = {}
        url = data.get("url", "") if isinstance(data, dict) else ""
        if not url.startswith("http"):
            try:
                url = base64.b64decode(url).decode("utf-8")
            except Exception:
                url = ""
        if not url.startswith("http"):
            return [404, "text/plain", "", ""]

        headers = {
            "User-Agent": self.headers["User-Agent"],
            "Referer": self.host + "/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        for route in ("c", "t"):
            target = url
            if route == "t":  # 主线路已失败，替换成备用线路节点
                target = re.sub(r"https://[ct]-nd\d+-1\.6wm\.top", self._image_host(1, "t"), url, count=1)
            try:
                resp = self.session.get(target, headers=headers, timeout=(8, 25))
                body = resp.content if resp.status_code == 200 else b""
                ctype = resp.headers.get("Content-Type", "image/webp")
                resp.close()
                if body:
                    return [200, ctype, body, {}]
            except Exception:
                continue
        return [404, "text/plain", "", ""]
