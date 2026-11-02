# coding=utf-8
# !/usr/bin/python
"""
1905影院
www.1905.com 有防护：requests/完整Chrome UA 常 403。
优先用标准库 urllib + 简单 UA（盒子无需 curl_cffi）。
"""

from base.spider import Spider
from bs4 import BeautifulSoup
from urllib.parse import quote, urlencode
import gzip
import hashlib
import json
import re
import ssl
import sys
import time
import uuid
import urllib.error
import urllib.request

sys.path.append("..")

try:
    from curl_cffi import requests as cffi_requests

    HAS_CFFI = True
except Exception:
    HAS_CFFI = False

try:
    import requests as std_requests
except Exception:
    std_requests = None

xurl = "https://www.1905.com"
xurl1 = "https://profile.m1905.com"
APP_ID = "dde3d61a0411511d"

# 故意用短 UA：完整 Chrome UA 会被 1905 拦
SAFE_UA = "Mozilla/5.0"
headerx = {
    "User-Agent": SAFE_UA,
    "Referer": "https://www.1905.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class _Resp:
    def __init__(self, code=0, text="", url=""):
        self.status_code = code
        self.text = text or ""
        self.url = url
        self.encoding = "utf-8"

    def json(self):
        return json.loads(self.text)


class Spider(Spider):
    def getName(self):
        return "1905影院"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def _soup(self, html):
        try:
            return BeautifulSoup(html, "lxml")
        except Exception:
            return BeautifulSoup(html, "html.parser")

    def _urllib_get(self, url, timeout=20):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": SAFE_UA,
                "Referer": "https://www.1905.com/",
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        try:
            ctx = ssl.create_default_context()
            opener = lambda: urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except Exception:
            opener = lambda: urllib.request.urlopen(req, timeout=timeout)
        with opener() as r:
            raw = r.read()
            enc = (r.headers.get("Content-Encoding") or "").lower()
            if enc == "gzip" or raw[:2] == b"\x1f\x8b":
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            # charset
            ctype = r.headers.get("Content-Type") or ""
            charset = "utf-8"
            m = re.search(r"charset=([\w-]+)", ctype, re.I)
            if m:
                charset = m.group(1)
            text = raw.decode(charset, "ignore")
            return _Resp(getattr(r, "status", 200) or 200, text, url)

    def _is_ok(self, resp):
        if not resp or resp.status_code != 200:
            return False
        t = resp.text or ""
        if "_jsc_ch_conf" in t or "ws_sec_page.js" in t:
            return False
        return True

    def _get(self, url, headers=None, timeout=20):
        # 1) urllib（标准库，盒子可用）
        try:
            r = self._urllib_get(url, timeout=timeout)
            if self._is_ok(r):
                return r
        except Exception:
            pass

        # 2) 壳自带 fetch（若有）
        try:
            if hasattr(self, "fetch"):
                r0 = self.fetch(url, headers={"User-Agent": SAFE_UA, "Referer": "https://www.1905.com/"})
                text = getattr(r0, "text", None) or getattr(r0, "content", "") or ""
                if isinstance(text, bytes):
                    text = text.decode("utf-8", "ignore")
                code = getattr(r0, "status_code", None) or getattr(r0, "status", 200) or 200
                r = _Resp(int(code), text, url)
                if self._is_ok(r):
                    return r
        except Exception:
            pass

        # 3) curl_cffi（有则用，勿覆盖 UA）
        if HAS_CFFI:
            try:
                r0 = cffi_requests.get(url, timeout=timeout, impersonate="chrome131")
                r = _Resp(r0.status_code, r0.text or "", url)
                if self._is_ok(r):
                    return r
            except Exception:
                pass

        # 4) requests 兜底（多半 403，但 profile 接口可用）
        if std_requests is not None:
            try:
                r0 = std_requests.get(url, headers=headers or headerx, timeout=timeout)
                return _Resp(r0.status_code, r0.text or "", url)
            except Exception:
                pass
        return _Resp(0, "", url)

    def _html(self, resp):
        return (resp.text if resp else "") or ""

    def extract_video(self, vods):
        videos = []
        for vod in vods:
            img = vod.find("img")
            if not img:
                continue
            name = img.get("alt") or img.get("title") or ""
            ids = vod.find("a", class_="pic-pack-outer")
            if ids is None:
                ids = vod.find("a", href=re.compile(r"/vod/play/\d+"))
            if ids is None or not ids.get("href"):
                continue
            href = ids["href"]
            m = re.search(r"/vod/play/(\d+)", href)
            if not m:
                continue
            pic = img.get("src") or img.get("data-src") or img.get("data-lazysrc") or ""
            if pic.startswith("//"):
                pic = "https:" + pic
            remarks = vod.find("i", class_="score")
            remark = "评分" + remarks.text.strip() if remarks else ""
            videos.append(
                {
                    "vod_id": m.group(1),
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": remark,
                }
            )
        return videos

    def extract_middle_text(self, text, start_str, end_str, pl, start_index1: str = "", end_index2: str = ""):
        if pl == 3:
            return ""
        start_index = text.find(start_str)
        if start_index == -1:
            return ""
        end_index = text.find(end_str, start_index + len(start_str))
        if end_index == -1:
            return ""
        if pl == 0:
            return text[start_index + len(start_str) : end_index].replace("\\", "")
        if pl == 1:
            middle_text = text[start_index + len(start_str) : end_index]
            matches = re.findall(start_index1, middle_text)
            if matches:
                return " ".join(matches)
        if pl == 2:
            middle_text = text[start_index + len(start_str) : end_index]
            matches = re.findall(start_index1, middle_text)
            if matches:
                return "$$$".join([f"{item}" for item in matches])
        return ""

    def homeContent(self, filter):
        result = {
            "class": [
                {"type_id": "n_1", "type_name": "电影"},
                {"type_id": "n_1_c_922", "type_name": "微电影"},
                {"type_id": "n_2", "type_name": "系列电影"},
                {"type_id": "c_927", "type_name": "纪录片"},
                {"type_id": "n_1_c_586", "type_name": "晚会"},
                {"type_id": "n_1_c_178", "type_name": "独家"},
                {"type_id": "n_1_c_1024", "type_name": "综艺"},
            ],
            "list": [],
            "filters": self._filters(),
        }
        # 部分壳只读 homeContent.list，顺带塞首页推荐
        try:
            result["list"] = self.categoryContent("n_1", "1", False, {}).get("list") or []
        except Exception:
            result["list"] = []
        return result

    def _filters(self):
        type_vals = [
            {"n": "全部", "v": ""},
            {"n": "爱情", "v": "_t_1"},
            {"n": "动作", "v": "_t_5"},
            {"n": "喜剧", "v": "_t_25"},
            {"n": "惊悚", "v": "_t_14"},
            {"n": "恐怖", "v": "_t_17"},
            {"n": "悬疑", "v": "_t_27"},
            {"n": "科幻", "v": "_t_16"},
            {"n": "奇幻", "v": "_t_20"},
            {"n": "历史", "v": "_t_18"},
            {"n": "灾难", "v": "_t_37"},
            {"n": "冒险", "v": "_t_19"},
            {"n": "励志", "v": "_t_38"},
            {"n": "青春", "v": "_t_39"},
            {"n": "动画", "v": "_t_4"},
            {"n": "儿童", "v": "_t_7"},
            {"n": "家庭", "v": "_t_13"},
        ]
        area_vals = [
            {"n": "全部", "v": ""},
            {"n": "内地", "v": "_a_1"},
            {"n": "港台", "v": "_a_2"},
            {"n": "欧美", "v": "_a_4"},
        ]
        gene_vals = [
            {"n": "全部", "v": ""},
            {"n": "抗日", "v": "_g_1783"},
            {"n": "间谍", "v": "_g_436"},
            {"n": "硬汉", "v": "_g_675"},
            {"n": "枪战", "v": "_g_1866"},
            {"n": "杀手", "v": "_g_584"},
            {"n": "夫妻", "v": "_g_1820"},
            {"n": "恶搞", "v": "_g_572"},
            {"n": "穿越", "v": "_g_552"},
        ]
        full = [
            {"key": "类型", "name": "类型", "value": type_vals},
            {"key": "地区", "name": "地区", "value": area_vals},
            {"key": "基因", "name": "基因", "value": gene_vals},
        ]
        mid = [
            {"key": "类型", "name": "类型", "value": type_vals},
            {"key": "地区", "name": "地区", "value": area_vals},
        ]
        return {
            "n_1": full,
            "n_1_c_922": full,
            "n_2": mid,
            "c_927": full,
            "n_1_c_586": full,
            "n_1_c_178": full,
            "n_1_c_1024": full,
        }

    def homeVideoContent(self):
        try:
            return self.categoryContent("n_1", "1", False, {})
        except Exception:
            return {"list": []}

    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        videos = []
        page = int(pg) if pg else 1
        if not isinstance(ext, dict):
            ext = {}
        lx = ext.get("类型", "")
        dq = ext.get("地区", "")
        jy = ext.get("基因", "")

        url = f"{xurl}/vod/list/{cid}{lx}{dq}{jy}/o3p{page}.html"
        detail = self._get(url)
        doc = self._soup(self._html(detail))

        if "n_2" not in str(cid):
            for soup in doc.find_all("section", class_="mod row search-list"):
                videos.extend(self.extract_video(soup.find_all("div", class_="grid-2x")))
            if not videos:
                videos.extend(self.extract_video(doc.find_all("div", class_="grid-2x")))
        else:
            for soup in doc.find_all("div", class_="mod"):
                videos.extend(self.extract_video(soup.find_all("div", class_="grid-4x")))

        result["list"] = videos
        result["page"] = page
        result["pagecount"] = 9999
        result["limit"] = 90
        result["total"] = 99999
        return result

    def detailContent(self, ids):
        did = ids[0]
        videos = []
        xianlu = "滴稳影视"
        bofang = did

        url = f"{xurl}/vod/play/{did}.shtml"
        html = self._html(self._get(url))

        content = "为您介绍剧情📢" + self.extract_middle_text(html, 'id="playerBoxIntroCon">', "<", 0)
        director = self.extract_middle_text(html, "导演", "</span>", 1, 'title="(.*?)"')
        actor = self.extract_middle_text(html, "主演", "</span>", 1, 'title="(.*?)"')
        remarks = self.extract_middle_text(html, "类型", "</span>", 1, 'title="(.*?)"').replace(" ", "")
        area = self.extract_middle_text(html, "地区", "</span>", 1, 'title="(.*?)"')

        api = f"{xurl}/api/content/?m=Vod&a=getVodSidebar&id={did}&fomat=json"
        detail = self._get(api)
        if detail.status_code == 200:
            try:
                data = detail.json()
            except Exception:
                try:
                    data = json.loads(self._html(detail))
                except Exception:
                    data = {}
            setup = (data.get("info") or {}).get("series_data") if isinstance(data, dict) else None
            if setup:
                name1 = data.get("title") or "正片"
                id1 = str(data.get("contentid") or did)
                parts = [f"{name1}${id1}"]
                for sou in setup:
                    sid = sou.get("contentid")
                    sname = (sou.get("title") or "").strip() or str(sid)
                    if sid:
                        parts.append(f"{sname}${sid}")
                bofang = "#".join(parts)

        videos.append(
            {
                "vod_id": did,
                "vod_director": director,
                "vod_actor": actor,
                "vod_remarks": remarks,
                "vod_area": area,
                "vod_content": content,
                "vod_play_from": xianlu,
                "vod_play_url": bofang,
            }
        )
        return {"list": videos}

    @staticmethod
    def _sign(params):
        ks = sorted(params.keys())
        q = "&".join(k + "=" + quote(str(params[k]), safe="") for k in ks if k != "signature")
        return hashlib.sha1((q + "." + APP_ID).encode()).hexdigest()

    @staticmethod
    def _parse_jsonp(text):
        if not text:
            return {}
        text = text.strip()
        m = re.search(r"\((\{.*\})\)\s*$", text, re.S)
        if m:
            return json.loads(m.group(1))
        if text.startswith("{"):
            return json.loads(text)
        return {}

    def playerContent(self, flag, id, vipFlags):
        nonce = int(time.time())
        expiretime = nonce + 600
        raw_uuid = str(uuid.uuid4())
        playerid = raw_uuid.replace("-", "")[5:20]
        page = f"https://www.1905.com/vod/play/{id}.shtml"
        params = {
            "cid": id,
            "expiretime": expiretime,
            "nonce": nonce,
            "page": page,
            "playerid": playerid,
            "type": "hls",
            "uuid": raw_uuid,
        }
        params["signature"] = self._sign(params)
        # profile 接口用 urllib/requests 均可；签名参数与 query 保持一致
        qs = urlencode(
            {
                "nonce": nonce,
                "expiretime": expiretime,
                "cid": id,
                "uuid": raw_uuid,
                "playerid": playerid,
                "page": page,
                "type": "hls",
                "signature": params["signature"],
                "callback": "",
            }
        )
        detail = self._get(f"{xurl1}/mvod/getVideoinfo.php?{qs}")
        play_url = ""
        if detail.status_code == 200:
            data = self._parse_jsonp(self._html(detail))
            body = data.get("data") if isinstance(data, dict) else None
            if isinstance(body, dict):
                path_map = body.get("path") or {}
                quality = body.get("quality") or {}
                sign_map = body.get("sign") or {}
                for cand in ("uhd", "hd", "sd"):
                    if cand in path_map and cand in quality:
                        sign = (sign_map.get(cand) or {}).get("sign") or ""
                        host = (quality.get(cand) or {}).get("host") or ""
                        path = (path_map.get(cand) or {}).get("path") or ""
                        play_url = (host + sign + path).replace("\\", "")
                        break
        return {"parse": 0, "playUrl": "", "url": play_url, "header": headerx}

    def searchContentPage(self, key, quick, pg):
        result = {}
        videos = []
        page = int(pg) if pg else 1
        q = quote(key)
        if page <= 1:
            url = f"{xurl}/search/index-p-type-all-q-{q}.html"
        else:
            url = f"{xurl}/search/index-p-type-all-q-{q}.html?page={page}"

        detail = self._get(url)
        doc = self._soup(self._html(detail))
        seen = set()
        for vod in doc.find_all("div", class_="new_content"):
            play = vod.find("a", class_="btn-play")
            href = play.get("href") if play else ""
            vid = ""
            if href:
                m = re.search(r"/vod/play/(\d+)", href)
                if m:
                    vid = m.group(1)
                elif re.search(r"vip\.1905\.com/play/(\d+)", href):
                    continue
            if not vid or vid in seen:
                continue
            seen.add(vid)
            img = vod.find("img")
            title_a = vod.select_one("h2.title-mv a") or vod.find("a", class_="img-a")
            name = ""
            if img:
                name = img.get("alt") or img.get("title") or ""
            if not name and title_a:
                name = title_a.get("title") or title_a.get_text(strip=True)
            name = re.sub(r"\s+", " ", name or "").strip()
            pic = (img.get("src") or "") if img else ""
            if pic.startswith("//"):
                pic = "https:" + pic
            videos.append({"vod_id": vid, "vod_name": name, "vod_pic": pic})

        result["list"] = videos
        result["page"] = page
        result["pagecount"] = 9999
        result["limit"] = 90
        result["total"] = 999999
        return result

    def searchContent(self, key, quick, pg="1"):
        return self.searchContentPage(key, quick, pg)

    def localProxy(self, params):
        if params["type"] == "m3u8":
            return self.proxyM3u8(params)
        elif params["type"] == "media":
            return self.proxyMedia(params)
        elif params["type"] == "ts":
            return self.proxyTs(params)
        return None
