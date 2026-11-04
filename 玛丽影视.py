# -*- coding: utf-8 -*-
# 玛丽影视 v2.0 · 二级分类 + 图片代理（修复版）

import sys
import re
import traceback
from urllib.parse import quote

sys.path.append('..')
from base.spider import Spider as BaseSpider

HOST = "https://www.maliys.com"

# ===== 图片模式开关 =====
# True = 走 weserv 代理（绕防盗链，推荐）
# False = 直连原图（部分CDN有防盗链会加载失败）
USE_PROXY = True

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": HOST + "/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 一级分类: (名称, sort_id)
CATES = [
    ("电影", "1"),
    ("电视剧", "2"),
    ("动漫", "3"),
    ("综艺", "4"),
    ("短剧", "29"),
]

# 二级分类配置
FILTERS = {
    "1": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "动作", "v": "5"}, {"n": "喜剧", "v": "6"}, {"n": "恐怖", "v": "7"},
            {"n": "科幻", "v": "8"}, {"n": "爱情", "v": "9"}, {"n": "剧情", "v": "10"},
            {"n": "战争", "v": "11"}, {"n": "灾难", "v": "12"}, {"n": "奇幻", "v": "13"},
            {"n": "犯罪", "v": "14"}, {"n": "悬疑", "v": "15"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"}, {"n": "法国", "v": "法国"}, {"n": "英国", "v": "英国"},
            {"n": "日本", "v": "日本"}, {"n": "韩国", "v": "韩国"}, {"n": "德国", "v": "德国"},
            {"n": "泰国", "v": "泰国"}, {"n": "印度", "v": "印度"}, {"n": "意大利", "v": "意大利"},
            {"n": "西班牙", "v": "西班牙"}, {"n": "加拿大", "v": "加拿大"}, {"n": "俄罗斯", "v": "俄罗斯"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
            {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"},
        ]},
    ],
    "2": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "国产剧", "v": "16"}, {"n": "欧美剧", "v": "17"}, {"n": "香港剧", "v": "18"},
            {"n": "台湾剧", "v": "20"}, {"n": "韩国剧", "v": "21"}, {"n": "日本剧", "v": "22"},
            {"n": "海外剧", "v": "23"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"}, {"n": "法国", "v": "法国"}, {"n": "英国", "v": "英国"},
            {"n": "日本", "v": "日本"}, {"n": "韩国", "v": "韩国"}, {"n": "德国", "v": "德国"},
            {"n": "泰国", "v": "泰国"}, {"n": "印度", "v": "印度"}, {"n": "意大利", "v": "意大利"},
            {"n": "西班牙", "v": "西班牙"}, {"n": "加拿大", "v": "加拿大"}, {"n": "俄罗斯", "v": "俄罗斯"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
            {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"},
        ]},
    ],
    "3": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "动画电影", "v": "24"}, {"n": "动漫剧集", "v": "25"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"}, {"n": "日本", "v": "日本"}, {"n": "韩国", "v": "韩国"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
        ]},
    ],
    "4": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "综艺节目", "v": "26"}, {"n": "纪录片", "v": "27"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"}, {"n": "日本", "v": "日本"}, {"n": "韩国", "v": "韩国"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
        ]},
    ],
    "29": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "反转", "v": "30"}, {"n": "恋爱", "v": "31"}, {"n": "古装", "v": "32"},
            {"n": "穿越", "v": "33"}, {"n": "悬疑", "v": "34"}, {"n": "都市", "v": "35"},
        ]},
    ],
}


class Spider(BaseSpider):
    name = "玛丽影视"
    host = HOST
    header = HEADERS
    config = {"player": {}, "filter": FILTERS}

    def init(self, extend=""):
        self.name = "玛丽影视"
        self.host = HOST
        self.header = dict(HEADERS)

    def getName(self):
        return "玛丽影视"

    def isVideoFormat(self, url):
        return any(ext in url.lower() for ext in ['.m3u8', '.mp4', '.flv', '.mkv'])

    # ---------- 图片处理（修复） ----------
    def _pic(self, url):
        if not url:
            return ""
        url = url.strip()
        if url.startswith('//'):
            url = 'https:' + url
        elif url and not url.startswith('http'):
            url = self.host + url

        if not USE_PROXY:
            return url

        # weserv 只需去掉协议头，不做百分号编码（旧版 quote 会导致加载失败）
        raw = re.sub(r'^https?://', '', url)
        return "https://wsrv.nl/?url=" + raw + "&w=400&output=webp"

    # ---------- fetch 兼容 ----------
    def _text(self, rsp):
        if isinstance(rsp, str):
            return rsp
        if isinstance(rsp, dict):
            for k in ('body', 'html', 'text', 'content', 'data'):
                v = rsp.get(k)
                if isinstance(v, str) and v:
                    return v
            return ""
        try:
            return rsp.text
        except Exception:
            pass
        try:
            return rsp.content.decode('utf-8', 'ignore')
        except Exception:
            return ""

    def _fetch(self, url):
        try:
            rsp = self.fetch(url, headers=self.header)
        except Exception:
            try:
                rsp = self.fetch(url)
            except Exception:
                traceback.print_exc()
                return ""
        return self._text(rsp)

    # ---------- 构建分类URL ----------
    def _build_class_url(self, tid, area="", year="", pg="1"):
        parts = [""] * 12
        parts[0] = str(tid)
        if area:
            parts[1] = quote(area)
        if year:
            parts[11] = str(year)
        if pg and str(pg) != "1":
            parts[8] = str(pg)
        return "%s/class/%s.html" % (self.host, "-".join(parts))

    # ---------- 列表解析（兼容 data-src） ----------
    def _parse_list(self, html):
        videos = []
        if not html:
            return videos
        seen = set()
        p1 = r'<a[^>]*href="/html/(\d+)\.html"[^>]*title="([^"]*)"[^>]*(?:data-original|data-src|src)="([^"]*)"'
        for vid, title, pic in re.findall(p1, html, re.DOTALL):
            if vid in seen or not title:
                continue
            seen.add(vid)
            remark = ""
            idx = html.find('/html/%s.html' % vid)
            if idx != -1:
                seg = html[idx: idx + 600]
                m = re.search(r'class="pic-text[^"]*"[^>]*>([^<]+)<', seg)
                if m:
                    remark = m.group(1).strip()
            videos.append({"vod_id": vid, "vod_name": title.strip(), "vod_pic": self._pic(pic), "vod_remarks": remark})

        if not videos:
            p2 = r'<a[^>]*href="/html/(\d+)\.html"[^>]*title="([^"]*)"'
            for vid, title in re.findall(p2, html):
                if vid in seen or not title:
                    continue
                seen.add(vid)
                videos.append({"vod_id": vid, "vod_name": title.strip(), "vod_pic": "", "vod_remarks": ""})
        return videos

    # ---------- 首页分类 ----------
    def homeContent(self, filter):
        result = {"class": []}
        for name, tid in CATES:
            result["class"].append({"type_name": name, "type_id": tid})
        return result

    def homeVideoContent(self):
        try:
            html = self._fetch(self.host + "/")
            return {"list": self._parse_list(html)}
        except Exception:
            traceback.print_exc()
            return {"list": []}

    # ---------- 分类列表 ----------
    def categoryContent(self, tid, pg, filter, extend):
        pg = str(pg) if pg else "1"
        try:
            ext_type = ""
            ext_area = ""
            ext_year = ""
            if extend and isinstance(extend, dict):
                ext_type = extend.get("type", "") or ""
                ext_area = extend.get("area", "") or ""
                ext_year = extend.get("year", "") or ""

            base_tid = ext_type if ext_type else tid

            if not ext_type and not ext_area and not ext_year:
                if pg == "1":
                    url = "%s/sort/%s.html" % (self.host, tid)
                else:
                    url = "%s/sort/%s/page/%s.html" % (self.host, tid, pg)
            else:
                url = self._build_class_url(base_tid, ext_area, ext_year, pg)

            html = self._fetch(url)
            videos = self._parse_list(html)
            pagecount = 9999
            if html:
                m = re.search(r'/class/\d+[^>]*>\s*(?:尾页|末页)', html)
                if m:
                    m2 = re.search(r'/class/(\d+)[^\d]*(\d+)---\.html[^>]*>\s*(?:尾页|末页)', html)
                    if m2:
                        pagecount = int(m2.group(2))
                if pagecount == 9999:
                    m = re.search(r'/page/(\d+)\.html[^>]*>\s*(?:尾页|末页)', html)
                    if m:
                        pagecount = int(m.group(1))
                if pagecount == 9999:
                    nums = re.findall(r'/page/(\d+)\.html', html)
                    if not nums:
                        nums = re.findall(r'/class/\d+[^"]*?(\d+)---\.html', html)
                    if nums:
                        pagecount = max(int(n) for n in nums if n.isdigit())

            return {"list": videos, "page": int(pg), "pagecount": pagecount, "limit": len(videos) or 24, "total": 999999}
        except Exception:
            traceback.print_exc()
            return {"list": [], "page": int(pg), "pagecount": 1, "limit": 24, "total": 0}

    # ---------- 详情 ----------
    def detailContent(self, array):
        try:
            tid = array[0]
            html = self._fetch("%s/html/%s.html" % (self.host, tid))
            if not html:
                return {"list": []}
            m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
            if not m:
                m = re.search(r'<title>([^<_-]+)', html)
            title = m.group(1).strip() if m else "未知"
            m = re.search(r'<img[^>]*(?:data-original|data-src|src)="([^"]*)"', html)
            pic = m.group(1) if m else ""
            desc = ""
            m = re.search(r'<div[^>]*class="[^"]*(?:desc|detail|sk)[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
            if m:
                desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if not desc:
                m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
                if m:
                    desc = m.group(1).strip()

            play_from, play_url = [], []
            uls = re.findall(r'<ul[^>]*class="[^"]*(?:stui-content__playlist|playlist)[^"]*"[^>]*>(.*?)</ul>', html, re.DOTALL)
            tabs = re.findall(r'<(?:a|li)[^>]*data-toggle[^>]*>([^<]{1,20})</(?:a|li)>', html)
            for i, ul in enumerate(uls):
                links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', ul)
                eps = []
                for href, ep in links:
                    ep = ep.strip()
                    if not ep or '播放' in ep:
                        continue
                    if href.startswith('//'):
                        href = 'https:' + href
                    elif href.startswith('/'):
                        href = self.host + href
                    eps.append(ep + '$' + href)
                if eps:
                    name = tabs[i].strip() if i < len(tabs) else "线路%d" % (i + 1)
                    play_from.append(name)
                    play_url.append('#'.join(eps))

            if not play_from:
                links = re.findall(r'<a[^>]*href="(/play/[^"]+)"[^>]*>([^<]+)</a>', html)
                if links:
                    eps = [ep.strip() + '$' + self.host + h for h, ep in links if ep.strip()]
                    play_from = ["默认线路"]
                    play_url = ['#'.join(eps)]

            vod = {"vod_id": tid, "vod_name": title, "vod_pic": self._pic(pic), "vod_content": desc,
                   "vod_play_from": '$$$'.join(play_from) if play_from else "默认线路",
                   "vod_play_url": '$$$'.join(play_url) if play_url else ""}
            return {"list": [vod]}
        except Exception:
            traceback.print_exc()
            return {"list": []}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg="1"):
        try:
            pg = str(pg) if pg else "1"
            if pg == "1":
                url = "%s/sou/%s-------------.html" % (self.host, quote(key))
            else:
                url = "%s/sou/%s------------%s.html" % (self.host, quote(key), pg)
            html = self._fetch(url)
            return {"list": self._parse_list(html)}
        except Exception:
            traceback.print_exc()
            return {"list": []}

    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick, pg)

    # ---------- 播放解析 ----------
    def playerContent(self, flag, id, vipFlags):
        try:
            if id.startswith('http') and any(x in id.lower() for x in ['.m3u8', '.mp4', '.flv']):
                return {"parse": 0, "url": id}
            url = id if id.startswith('http') else self.host + id
            html = self._fetch(url)
            m = re.search(r'<iframe[^>]*src="([^"]*)"', html)
            if m:
                real = m.group(1)
                if real.startswith('//'):
                    real = 'https:' + real
                elif not real.startswith('http'):
                    real = self.host + real
                if any(x in real.lower() for x in ['.m3u8', '.mp4', '.flv']):
                    return {"parse": 0, "url": real}
                if '.html' in real:
                    return self.playerContent(flag, real, vipFlags)
                return {"parse": 0, "url": real}
            m = re.search(r'<video[^>]*src="([^"]*)"', html)
            if m:
                return {"parse": 0, "url": m.group(1)}
            for p in [r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
                      r'["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
                      r'url\s*[:=]\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                      r'now\s*[:=]\s*["\']([^"\']+)["\']']:
                m = re.search(p, html, re.IGNORECASE)
                if m:
                    real = m.group(1)
                    if real.startswith('//'):
                        real = 'https:' + real
                    return {"parse": 0, "url": real}
            m = re.search(r'location\.(?:href|replace)\s*[=(]\s*["\']([^"\']+)["\']', html)
            if m:
                real = m.group(1)
                if real.startswith('/'):
                    real = self.host + real
                if '.html' in real:
                    return self.playerContent(flag, real, vipFlags)
                return {"parse": 0, "url": real}
            return {"parse": 1, "url": url}
        except Exception:
            traceback.print_exc()
            return {"parse": 1, "url": id}


def get_spider():
    return Spider()
