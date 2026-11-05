# -*- coding: utf-8 -*-
"""
青橙影视 Python Spider — https://www.51packing.com
"""

import sys
import re
import json
import time
from urllib.parse import quote, unquote, urljoin

sys.path.append("..")

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
                timeout = kw.pop("timeout", 15)
                r = _rq.get(url, headers=headers, timeout=timeout, verify=False, **kw)
                r.encoding = "utf-8"
                return r
    except ImportError:
        import urllib.request as _ur

        class _Resp:
            def __init__(self, raw):
                self.text = raw.decode("utf-8", errors="ignore")
                self.encoding = "utf-8"

        class Spider:
            def fetch(self, url, headers=None, **kw):
                timeout = kw.pop("timeout", 15)
                req = _ur.Request(url, headers=headers or {})
                return _Resp(_ur.urlopen(req, timeout=timeout).read())


HOST = "https://www.51packing.com"
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

CLASSES = [
    {"type_name": "电影", "type_id": "1"},
    {"type_name": "电视剧", "type_id": "2"},
    {"type_name": "综艺", "type_id": "3"},
    {"type_name": "动漫", "type_id": "4"},
    {"type_name": "网红短剧", "type_id": "34"},
]

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
        {"n": "动画片", "v": "24"},
        {"n": "纪录片", "v": "23"},
    ]}],
    "2": [{"key": "cate", "name": "分类", "value": [
        {"n": "全部", "v": "2"},
        {"n": "国产剧", "v": "13"},
        {"n": "香港剧", "v": "14"},
        {"n": "韩国剧", "v": "15"},
        {"n": "欧美剧", "v": "16"},
        {"n": "台湾剧", "v": "20"},
        {"n": "日本剧", "v": "21"},
        {"n": "其它剧", "v": "22"},
    ]}],
    "3": [{"key": "cate", "name": "分类", "value": [
        {"n": "全部", "v": "3"},
        {"n": "大陆综艺", "v": "25"},
        {"n": "日韩综艺", "v": "26"},
        {"n": "港台综艺", "v": "27"},
        {"n": "欧美综艺", "v": "28"},
    ]}],
    "4": [{"key": "cate", "name": "分类", "value": [
        {"n": "全部", "v": "4"},
        {"n": "国产动漫", "v": "29"},
        {"n": "日韩动漫", "v": "30"},
        {"n": "欧美动漫", "v": "31"},
        {"n": "其它动漫", "v": "32"},
    ]}],
    "34": [{"key": "cate", "name": "分类", "value": [
        {"n": "全部", "v": "34"},
        {"n": "网红短剧", "v": "34"},
    ]}],
}


class Spider(Spider):

    def getName(self):
        return "青橙影视"

    def init(self, extend=""):
        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        try:
            import requests as _rq
            try:
                import urllib3
                urllib3.disable_warnings()
            except Exception:
                pass
            self.session = _rq.Session()
            self.session.headers.update(self.header)
            adapter = _rq.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=0)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
        except ImportError:
            self.session = None

    def isVideoFormat(self, url):
        u = (url or "").lower()
        return any(ext in u for ext in [".m3u8", ".mp4", ".flv", ".ts"])

    def _get(self, url, timeout=10, retries=2):
        for i in range(retries):
            try:
                if self.session is not None:
                    rsp = self.session.get(url, timeout=timeout, verify=False)
                    rsp.encoding = "utf-8"
                    txt = rsp.text
                else:
                    rsp = self.fetch(url, headers=self.header, timeout=timeout)
                    txt = rsp.text if rsp else ""
                if txt and len(txt) > 200:
                    return txt
                time.sleep(0.1 * (i + 1))
            except Exception:
                time.sleep(0.15 * (i + 1))
        return ""

    def _abs_url(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return HOST + url
        if not url.startswith("http"):
            return urljoin(HOST + "/", url)
        return url

    @staticmethod
    def _strip(txt):
        return re.sub(r"\s+", " ", (txt or "")).strip()

    def _parse_vod(self, html):
        items, seen = [], set()
        blocks = re.findall(r'<li class="col8">([\s\S]*?)</li>', html)
        for block in blocks:
            hm = re.search(r'href="/cd/(\d+)\.html"', block)
            if not hm:
                continue
            vod_id = hm.group(1)
            if vod_id in seen:
                continue
            t_m = re.search(r'title="([^"]*)"', block)
            title = self._strip(t_m.group(1)) if t_m else ""
            pic_m = re.search(r'data-original="([^"]+)"', block)
            pic = self._abs_url(pic_m.group(1).strip()) if pic_m else ""
            n_m = re.search(r'<p class="text">([^<]+)</p>', block)
            remarks = self._strip(n_m.group(1)) if n_m else ""
            seen.add(vod_id)
            items.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
            })
        return items

    def homeContent(self, filter):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        html = self._get(HOST + "/", timeout=6, retries=2)
        if not html:
            return {"list": []}
        items = self._parse_vod(html)
        return {"list": items[:30]}

    def _parse_pagecount(self, html):
        m = re.search(r"共\s*(\d+)\s*页", html)
        if m:
            return int(m.group(1))
        m = re.search(r'href="/vodshow/[^"]*-(\d+)---\.html"[^>]*>尾页', html)
        if m:
            return int(m.group(1))
        pages = re.findall(r'/vodshow/[^"]*-(\d+)---\.html', html)
        if pages:
            return max(int(p) for p in pages)
        return 1

    def categoryContent(self, tid, pg, filter, extend):
        try:
            cate = (extend or {}).get("cate") if extend else None
            page = int(pg or 1)
            if page < 1:
                page = 1
            use_tid = cate if cate else tid
            if page == 1:
                url = HOST + "/vodshow/" + use_tid + "-----------.html"
            else:
                url = HOST + "/vodshow/" + use_tid + "--------" + str(page) + "---.html"
            html = self._get(url, timeout=10)
            if not html:
                return {"page": page, "pagecount": 1, "limit": 24, "total": 0, "list": []}
            videos = self._parse_vod(html)
            pagecount = self._parse_pagecount(html)
            if page > pagecount:
                page = pagecount
            limit = len(videos) or 24
            return {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": limit,
                "total": pagecount * limit,
            }
        except Exception as e:
            print("[青橙] categoryContent 异常: " + str(e))
            return {"page": 1, "pagecount": 1, "limit": 24, "total": 0, "list": []}

    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)):
            ids = ids[0]
        vod_id = str(ids)
        url = HOST + "/cd/" + vod_id + ".html"
        html = self._get(url, timeout=10)
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
            m = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
            if m:
                vod["vod_name"] = self._strip(m.group(1))
            else:
                m = re.search(r"<title>《([^》]+)》", html)
                if m:
                    vod["vod_name"] = self._strip(m.group(1))
            m = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', html)
            if m:
                vod["vod_pic"] = self._abs_url(m.group(1).strip())
            if not vod["vod_pic"]:
                m = re.search(r'data-original="([^"]+)"', html)
                if m:
                    vod["vod_pic"] = self._abs_url(m.group(1).strip())
            info_map = {
                "分类": "vod_class",
                "地区": "vod_area",
                "年份": "vod_year",
                "主演": "vod_actor",
                "导演": "vod_director",
                "备注": "vod_remarks",
            }
            for dt, dd in re.findall(r"<dt>([^<]+)</dt>\s*<dd>([^<]+)</dd>", html):
                k = dt.strip().replace("：", "").replace(":", "")
                if k in info_map:
                    vod[info_map[k]] = self._strip(dd)
            for kw, key in [("主演", "vod_actor"), ("导演", "vod_director"), ("地区", "vod_area"), ("年份", "vod_year"), ("分类", "vod_class")]:
                pattern_a = kw + "[：:]\\s*</span>([^<]+)"
                m = re.search(pattern_a, html)
                if m:
                    vod[key] = self._strip(m.group(1))
                else:
                    pattern_b = kw + "[：:]\\s*([^<\\n]+)"
                    m = re.search(pattern_b, html)
                    if m:
                        vod[key] = self._strip(m.group(1))
            m = re.search(r"剧情介绍[\s\S]*?<p[^>]*>([\s\S]*?)</p>", html)
            if m:
                txt = re.sub(r"<[^>]+>", "", m.group(1))
                vod["vod_content"] = self._strip(txt)[:500]
            else:
                m = re.search(r'class="[^"]*desc[^"]*"[^>]*>([\s\S]*?)</div>', html)
                if m:
                    txt = re.sub(r"<[^>]+>", "", m.group(1))
                    vod["vod_content"] = self._strip(txt)[:500]
            play_from, play_url = self._collect_playlist(html)
            if play_from:
                vod["vod_play_from"] = "$$$".join(play_from)
                vod["vod_play_url"] = "$$$".join(play_url)
            return {"list": [vod]}
        except Exception as e:
            print("[青橙] detailContent 异常: " + str(e))
            return {"list": []}

    def _collect_playlist(self, html):
        play_from, play_url = [], []
        by_sid, order = {}, []
        line_names = {}
        # 优先从 <!-- 播放地址 --> 区块提取
        play_area = re.search(r"<!--\s*播放地址\s*-->([\s\S]*?)<!--\s*end 播放地址\s*-->", html)
        if play_area:
            area = play_area.group(1)
            # 提取线路名: 每个 panel 的 h3
            panels = re.findall(r'<div[^>]*class="[^"]*panel[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>', area)
            for panel in panels:
                h3_m = re.search(r"<h3[^>]*>([^<]+)</h3>", panel)
                if h3_m:
                    name = self._strip(h3_m.group(1))
                    if name in ["播放记录", "同主演推荐", "同年代推荐", "同类型推荐"]:
                        continue
                    sids = re.findall(r"/do/\d+/(\d+)/", panel)
                    if sids:
                        line_names[sids[0]] = name
            # 在播放区内提取所有播放链接
            links = re.findall(r'<a[^>]+href="/do/(\d+)/(\d+)/(\d+)\.html"[^>]*>([^<]+)</a>', area)
            for vid, sid, nid, name in links:
                ep_name = self._strip(name)
                if not ep_name:
                    ep_name = "第" + str(int(nid)).zfill(2) + "集"
                if sid not in by_sid:
                    by_sid[sid] = []
                    order.append(sid)
                by_sid[sid].append((int(nid), ep_name, vid, sid, nid))
        # fallback: 从整个页面提取
        if not by_sid:
            seen = set()
            links = re.findall(r'<a[^>]+href="/do/(\d+)/(\d+)/(\d+)\.html"[^>]*>([^<]+)</a>', html)
            for vid, sid, nid, name in links:
                if (sid, nid) in seen:
                    continue
                seen.add((sid, nid))
                ep_name = self._strip(name)
                if not ep_name:
                    ep_name = "第" + str(int(nid)).zfill(2) + "集"
                if sid not in by_sid:
                    by_sid[sid] = []
                    order.append(sid)
                by_sid[sid].append((int(nid), ep_name, vid, sid, nid))
        for sid in order:
            eps = sorted(by_sid[sid], key=lambda x: x[0])
            line_name = line_names.get(sid, "")
            if not line_name:
                line_name = "线路" + sid
            play_from.append(line_name)
            play_url.append("#".join(
                e + "$/do/" + vid + "/" + s + "/" + n + ".html"
                for _, e, vid, s, n in eps
            ))
        return play_from, play_url

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1
            encoded = quote(str(key))
            if page == 1:
                url = HOST + "/search/" + encoded + "-------------.html"
            else:
                url = HOST + "/search/" + encoded + "----------" + str(page) + "---.html"
            html = self._get(url, timeout=10)
            if not html:
                return {"list": []}
            if "暂无" in html and "col8" not in html:
                return {"list": []}
            items = self._parse_vod(html)
            pagecount = self._parse_pagecount(html)
            limit = len(items) or 24
            return {
                "list": items,
                "page": page,
                "pagecount": pagecount,
                "limit": limit,
                "total": pagecount * limit,
            }
        except Exception as e:
            print("[青橙] searchContent 异常: " + str(e))
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        play_url = str(id or "")
        if not play_url:
            return {"parse": 0, "url": ""}
        if self.isVideoFormat(play_url):
            return {
                "parse": 0,
                "url": play_url,
                "header": {"User-Agent": UA, "Referer": HOST + "/"},
            }
        url = self._abs_url(play_url)
        html = self._get(url, timeout=12)
        if html:
            obj = _extract_player_obj(html)
            if obj and obj.get("url"):
                real = obj["url"]
                enc = obj.get("encrypt", 0)
                if enc == 1:
                    real = unquote(real)
                return {
                    "parse": 0,
                    "url": real,
                    "header": {"User-Agent": UA, "Referer": HOST + "/"},
                }
        return {
            "parse": 0,
            "url": play_url,
            "header": {"User-Agent": UA, "Referer": HOST + "/"},
        }

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    def destroy(self):
        pass


def _extract_player_obj(html):
    m = re.search(r"var\s+player_\w+\s*=\s*", html)
    if not m:
        return None
    i = m.end()
    if i >= len(html) or html[i] != "{":
        return None
    depth, start = 0, i
    while i < len(html):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        elif c == chr(34):
            i += 1
            while i < len(html) and html[i] != chr(34):
                if html[i] == chr(92):
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
            return json.loads(raw.replace(chr(39), chr(34)))
        except Exception:
            return None


if __name__ == "__main__":
    s = Spider()
    s.init()
    import json as _json

    print("==== homeContent ====")
    print(_json.dumps(s.homeContent(1), ensure_ascii=False)[:300])

    print("\n==== homeVideoContent ====")
    hv = s.homeVideoContent()
    print("count:", len(hv["list"]))
    for it in hv["list"][:3]:
        print(it["vod_name"], "|", it["vod_remarks"], "|", it["vod_pic"][:50])

    print("\n==== categoryContent p1 (电影/动作片) ====")
    cc = s.categoryContent("1", "1", 1, {"cate": "6"})
    print("count:", len(cc["list"]), "pagecount:", cc.get("pagecount"), "page:", cc.get("page"))
    for it in cc["list"][:3]:
        print(" ", it["vod_name"], "|", it["vod_remarks"])

    print("\n==== searchContent (九门2) ====")
    sc = s.searchContent("九门2", 0, "1")
    print("count:", len(sc["list"]))
    for it in sc["list"][:5]:
        print(it["vod_id"], it["vod_name"])

    print("\n==== detailContent (173285) ====")
    dc = s.detailContent("173285")
    if dc["list"]:
        v = dc["list"][0]
        print("name:", v["vod_name"])
        print("play_from:", v["vod_play_from"])
        if v["vod_play_url"]:
            pf = v["vod_play_url"].split("$$$")
            print("ep count per line:", [len(x.split("#")) for x in pf])

    print("\n==== playerContent ====")
    pc = s.playerContent("线路1", "/do/173285/1/1.html", [])
    print("url:", pc.get("url")[:200] if pc.get("url") else "")
    print("parse:", pc.get("parse"))