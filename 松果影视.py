# -*- coding: utf-8 -*-
"""
松果影院(bibi01.cc) TVBox/T4 Spider
- 纯 HTML 解析，无 JSON API
- 完整二级分类（已精简）
- 真实多线路：详情页自动探测播放页线路（线路A/线路B）
- 搜索支持分页
- 播放页 data-player-token base64 解码直链 m3u8，parse=0 极速播放
- 全链路缓存 + 短超时，加载速度优化
"""

import sys
import json
import re
import time
import base64

sys.path.append('..')

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
            timeout = kw.pop('timeout', 10)
            r = _rq.get(url, headers=headers, timeout=timeout, verify=False, **kw)
            r.encoding = 'utf-8'
            return r

# ============================================================
# 常量
# ============================================================

HOST = "https://www.bibi01.cc"
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

CLASS_MAP = {
    "1": {"name": "电影", "path": "dianyingad"},
    "2": {"name": "电视剧", "path": "dianshig"},
    "3": {"name": "动漫", "path": "dongmang"},
    "4": {"name": "综艺", "path": "zongyig"},
    "5": {"name": "短剧", "path": "duanjug"},
    "6": {"name": "AI剧场", "path": "juchangg"},
    "7": {"name": "影视解说", "path": "yingshih"},
}

# 已删除用户指定的分类
SUB_CLASSES = {
    "1": [
        {"n": "全部", "v": ""},
        {"n": "动作片", "v": "dongzuog"},
        {"n": "喜剧片", "v": "xijug"},
        {"n": "爱情片", "v": "aiqingg"},
        {"n": "科幻片", "v": "kehuang"},
        {"n": "恐怖片", "v": "kongbug"},
        {"n": "剧情片", "v": "juqingq"},
        {"n": "战争片", "v": "zhanzhengg"},
        {"n": "悬疑片", "v": "xuanyig"},
        {"n": "犯罪片", "v": "fanzuig"},
        {"n": "奇幻片", "v": "qihuang"},
        {"n": "灾难片", "v": "zainang"},
        {"n": "动画片", "v": "donghuao"},
        {"n": "纪录片", "v": "jilug"},
        {"n": "伦理片", "v": "lunlin"},
    ],
    "2": [
        {"n": "全部", "v": ""},
        {"n": "国产剧", "v": "guochann"},
        {"n": "香港剧", "v": "xianggangg"},
        {"n": "台湾剧", "v": "taiwang"},
        {"n": "韩国剧", "v": "hanguoo"},
        {"n": "日本剧", "v": "ribenv"},
        {"n": "欧美剧", "v": "oumeiu"},
        {"n": "泰国剧", "v": "taiguog"},
    ],
    "3": [
        {"n": "全部", "v": ""},
        {"n": "国产动漫", "v": "guochano"},
        {"n": "日本动漫", "v": "ribenw"},
        {"n": "欧美动漫", "v": "oumeiw"},
    ],
    "4": [
        {"n": "全部", "v": ""},
        {"n": "大陆综艺", "v": "dalug"},
        {"n": "港台综艺", "v": "gangtaiv"},
        {"n": "日韩综艺", "v": "rihang"},
        {"n": "欧美综艺", "v": "oumeiv"},
    ],
    "5": [
        {"n": "全部", "v": ""},
        {"n": "现代都市", "v": "xiandaig"},
        {"n": "女频恋爱", "v": "nvping"},
        {"n": "反转爽剧", "v": "fanzhuang"},
        {"n": "古装仙侠", "v": "guzhuango"},
        {"n": "年代穿越", "v": "niandaig"},
        {"n": "脑洞悬疑", "v": "naodongg"},
    ],
    "6": [
        {"n": "全部", "v": ""},
        {"n": "AI漫剧", "v": "manjuo"},
    ],
    "7": [
        {"n": "全部", "v": ""},
        {"n": "预告片", "v": "yugaos"},
    ],
}

_YEAR_FILTER = {
    "key": "year",
    "name": "年份",
    "value": [
        {"n": "全部", "v": ""},
        {"n": "2026", "v": "2026"},
        {"n": "2025", "v": "2025"},
        {"n": "2024", "v": "2024"},
        {"n": "2023", "v": "2023"},
        {"n": "2022", "v": "2022"},
        {"n": "2021", "v": "2021"},
        {"n": "2020", "v": "2020"},
        {"n": "2019", "v": "2019"},
        {"n": "2018", "v": "2018"},
    ],
}

_BY_FILTER = {
    "key": "by",
    "name": "排序",
    "value": [
        {"n": "最新", "v": "time"},
        {"n": "最热", "v": "hits"},
        {"n": "评分", "v": "score"},
    ],
}

FILTERS = {}
for tid, info in CLASS_MAP.items():
    subs = SUB_CLASSES.get(tid, [{"n": "全部", "v": ""}])
    FILTERS[tid] = [
        {"key": "class", "name": "类型", "value": subs},
        _YEAR_FILTER,
        _BY_FILTER,
    ]

CLASSES = [{"type_name": info["name"], "type_id": tid} for tid, info in CLASS_MAP.items()]


# ============================================================
# Spider
# ============================================================

class Spider(Spider):

    def getName(self):
        return "松果影院"

    def init(self, extend=""):
        self.extend = extend if not isinstance(extend, list) else ""
        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self._home_cache = []
        self._home_cache_time = 0
        self._detail_cache = {}
        self._line_cache = {}

    def _text(self, rsp):
        try:
            return rsp.text
        except Exception:
            try:
                return rsp.content.decode('utf-8', 'ignore')
            except Exception:
                return ""

    def _fetch(self, url, timeout=10):
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            return self._text(rsp)
        except Exception:
            return ""

    def _match(self, pat, txt, flags=0):
        m = re.search(pat, txt, flags)
        return m.group(1) if m else ""

    # ===== 列表解析 =====
    def _extract_vod_list(self, html):
        items = []
        if not html:
            return items

        articles = re.findall(
            r"<article[^>]*class=[\"']wu-poster-card[\"'][^>]*>(.*?)</article>",
            html, re.S
        )

        seen = set()
        for art in articles:
            href = self._match(
                r"<a[^>]*class=[\"']wu-poster-card__cover[\"'][^>]*href=[\"']([^\"']+)[\"']", art
            )
            if not href:
                href = self._match(
                    r"<a[^>]*href=[\"'](/film/[^\"']+\.html)[\"'][^>]*class=[\"']wu-poster-card__cover", art
                )

            pic = self._match(r"data-cover-src=[\"']([^\"']+)[\"']", art)
            if not pic:
                pic = self._match(r"src=[\"']([^\"']+)[\"']", art)

            name = self._match(r"<h3>.*?<a[^>]*>([^<]+)</a>.*?</h3>", art, re.S)
            if not name:
                name = self._match(r"alt=[\"']([^\"']+)[\"']", art)

            remark = ""
            p_text = self._match(r"<p>([^<]+)</p>", art)
            small_text = self._match(r"<small>([^<]+)</small>", art)
            if p_text and small_text:
                remark = f"{small_text} &middot; {p_text.strip()}"
            elif small_text:
                remark = small_text
            elif p_text:
                remark = p_text.strip()

            if not href or not name:
                continue
            if href in seen:
                continue
            seen.add(href)

            if pic.startswith("//"):
                pic = "https:" + pic
            elif pic.startswith("/"):
                pic = HOST + pic

            items.append({
                "vod_id": href,
                "vod_name": name.strip(),
                "vod_pic": pic,
                "vod_remarks": remark or "HD",
            })

        return items

    def _extract_page_info(self, html):
        pages = re.findall(r"[?&]page=(\d+)", html)
        if pages:
            return max(int(p) for p in pages)
        pages = re.findall(r"/page/(\d+)\.html", html)
        if pages:
            return max(int(p) for p in pages)
        if "下一页" in html:
            return 999
        return 1

    # ===== 首页 =====
    def homeContent(self, filter):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < 180:
            return {"list": self._home_cache}

        html = self._fetch(HOST + "/", timeout=10)
        vods = self._extract_vod_list(html)
        self._home_cache = vods[:60]
        self._home_cache_time = now
        return {"list": self._home_cache}

    # ===== 分类 =====
    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            ext = {}
            if extend:
                ext = extend if isinstance(extend, dict) else json.loads(extend)

            base_path = CLASS_MAP.get(str(tid), {}).get("path", "dianyingad")
            sub_path = ext.get("class", "")
            year = ext.get("year", "")
            by = ext.get("by", "")

            if sub_path:
                url_path = f"/film/{base_path}/{sub_path}/"
            else:
                url_path = f"/film/{base_path}/"

            qs = []
            if year:
                qs.append(f"year={year}")
            if by:
                order_map = {"time": "最新更新", "hits": "最热", "score": "评分"}
                qs.append(f"order={order_map.get(by, '最新更新')}")
            if page > 1:
                qs.append(f"page={page}")

            if qs:
                url_path += "?" + "&".join(qs)

            url = HOST + url_path
            html = self._fetch(url, timeout=12)
            vods = self._extract_vod_list(html)

            total_page = self._extract_page_info(html)
            if total_page < page:
                total_page = page if vods else page

            return {
                "list": vods,
                "page": page,
                "pagecount": total_page,
                "limit": 24,
                "total": total_page * 24,
            }
        except Exception:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 24, "total": 0}

    # ===== 详情（含真实线路探测） =====
    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vid = ids[0]

        if vid in self._detail_cache:
            return self._detail_cache[vid]

        url = HOST + vid if vid.startswith("/") else vid
        html = self._fetch(url, timeout=12)
        if not html:
            return {"list": []}

        try:
            name = self._match(r"<h1[^>]*itemprop=[\"']name[\"'][^>]*>([^<]+)</h1>", html)
            if not name:
                name = self._match(r"<title>([^<|]+)", html)
                if name:
                    name = name.split("|")[0].strip()

            pic = self._match(
                r"<img[^>]*class=[\"']wu-detail-poster[\"'][^>]*data-cover-src=[\"']([^\"']+)[\"']",
                html, re.I
            )
            if not pic:
                pic = self._match(
                    r"<meta[^>]*property=[\"']og:image[\"'][^>]*content=[\"']([^\"']+)[\"']",
                    html, re.I
                )
            if pic and pic.startswith("//"):
                pic = "https:" + pic
            elif pic and pic.startswith("/"):
                pic = HOST + pic

            meta_line = self._match(r"<p[^>]*class=[\"']wu-detail-meta[\"'][^>]*>([^<]+)</p>", html)
            year = area = type_name = ""
            if meta_line:
                parts = [p.strip() for p in meta_line.replace("　", " ").replace("/", " ").split() if p.strip()]
                for p in parts:
                    if p.isdigit() and len(p) == 4:
                        year = p
                    elif "剧" in p or "片" in p or "综艺" in p or "动漫" in p:
                        type_name = p
                    elif len(p) <= 4 and p not in ["HD", "完结"]:
                        area = p

            content = self._match(
                r"<p[^>]*class=[\"']wu-detail-summary[\"'][^>]*itemprop=[\"']description[\"'][^>]*>(.*?)</p>",
                html, re.S
            )
            content = re.sub(r"<[^>]+>", "", content or "").strip()

            director = self._match(r"导演[：:]\s*([^<]+)", html) or ""
            actor = self._match(r"主演[：:]\s*([^<]+)", html) or ""

            ep_section = self._match(
                r"<section[^>]*class=[\"']wu-episode-panel[^\"']*[\"'][^>]*>(.*?)</section>",
                html, re.S
            )
            ep_list = []
            if ep_section:
                eps = re.findall(
                    r"<a[^>]*href=[\"'](/play/[^\"']+\.html)[\"'][^>]*>([^<]+)</a>",
                    ep_section, re.S
                )
                for ep_href, ep_name in eps:
                    ep_name = ep_name.strip()
                    ep_list.append(f"{ep_name}${ep_href}")

            if not ep_list:
                immediate = self._match(
                    r"<a[^>]*href=[\"'](/play/[^\"']+\.html)[\"'][^>]*>立即播放</a>", html
                )
                if immediate:
                    ep_list.append(f"正片${immediate}")

            if not ep_list:
                return {"list": []}

            play_from = []
            play_url = []
            first_play = ep_list[0].split("$")[1]

            if vid in self._line_cache:
                line_names = self._line_cache[vid]
            else:
                line_names = self._detect_lines(first_play)
                self._line_cache[vid] = line_names

            if line_names and len(line_names) > 1:
                for line in line_names:
                    play_from.append(line)
                    play_url.append("#".join(ep_list))
            else:
                play_from.append("松果影视")
                play_url.append("#".join(ep_list))

            vod = {
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "type_name": type_name,
                "vod_year": year,
                "vod_area": area,
                "vod_actor": actor,
                "vod_director": director,
                "vod_content": content,
                "vod_remarks": "HD",
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url),
            }

            self._detail_cache[vid] = {"list": [vod]}
            return self._detail_cache[vid]

        except Exception:
            return {"list": []}

    def _detect_lines(self, play_path):
        url = HOST + play_path if play_path.startswith("/") else play_path
        html = self._fetch(url, timeout=8)
        if not html:
            return []

        buttons = re.findall(r"<button[^>]*data-player-switch[^>]*>(.*?)</button>", html, re.S)
        lines = []
        for b in buttons:
            text = re.sub(r"<[^>]+>", "", b).strip()
            if text and text not in lines:
                lines.append(text)
        return lines

    # ===== 搜索 =====
    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            kw = key.replace(" ", "+")
            url = f"{HOST}/film/search={kw}"
            if page > 1:
                url += f"?page={page}"

            html = self._fetch(url, timeout=12)
            vods = self._extract_vod_list(html)

            total_page = self._extract_page_info(html)
            if total_page < page:
                total_page = page if vods else page

            return {
                "list": vods,
                "page": page,
                "pagecount": total_page,
                "limit": 24,
                "total": total_page * 24,
            }
        except Exception:
            return {"list": []}

    # ===== 播放 =====
    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "playUrl": "", "url": ""}

        play_url = str(id).replace("\\/", "/")
        if not play_url.startswith("http"):
            play_url = HOST + play_url if play_url.startswith("/") else play_url

        if self._is_direct_media(play_url):
            return self._direct_response(play_url)

        if "/play/" in play_url:
            html = self._fetch(play_url, timeout=10)
            if html:
                token = ""
                m = re.search(
                    r"<button[^>]*data-player-code=[\"']jsm3u8[\"'][^>]*data-player-token=[\"']([^\"']+)[\"']",
                    html, re.S
                )
                if m:
                    token = m.group(1)
                else:
                    token = self._match(r"data-player-token=[\"']([A-Za-z0-9+/=]+)[\"']", html)

                if token:
                    try:
                        decoded = base64.b64decode(token).decode("utf-8", "ignore")
                        if decoded and self._is_direct_media(decoded):
                            return self._direct_response(decoded)
                    except Exception:
                        pass

                for pat in [r"[\"']([^\"']*\.m3u8[^\"']*)[\"']", r"[\"']([^\"']*\.mp4[^\"']*)[\"']"]:
                    m = self._match(pat, html)
                    if m:
                        return self._direct_response(m)

        return {
            "parse": 1,
            "playUrl": "",
            "url": play_url,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
            },
        }

    def _is_direct_media(self, url):
        url = (url or "").lower()
        return any(ext in url for ext in [".m3u8", ".mp4", ".flv", ".mkv", ".ts"])

    def _direct_response(self, url):
        is_m3u8 = ".m3u8" in url.lower()
        ref = self._extract_referer(url)
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": {
                "User-Agent": UA,
                "Referer": ref,
            },
            "format": "application/x-mpegURL" if is_m3u8 else "",
            "contentType": "application/x-mpegURL" if is_m3u8 else "",
        }

    def _extract_referer(self, url):
        try:
            if "://" in url:
                return url.split("://")[0] + "://" + url.split("://")[1].split("/")[0] + "/"
        except Exception:
            pass
        return HOST + "/"

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    def destroy(self):
        pass

    def close(self):
        self.destroy()
