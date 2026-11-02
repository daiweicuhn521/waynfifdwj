"""
@header({
  searchable: 1,
  filterable: 1,
  quickSearch: 1,
  title: '水晶DJ网',
  lang: 'hipy'
})
"""
import re
import json
import urllib.parse
try:
    import requests
    from requests.adapters import HTTPAdapter
    try:
        from urllib3.util.retry import Retry
    except Exception:
        from requests.packages.urllib3.util.retry import Retry
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
    _HAS_RQ = True
except Exception:
    _HAS_RQ = False
try:
    from base.spider import Spider
except Exception:
    class Spider:
        pass
PIC_PROXY = "https://wsrv.nl/?url="
SORTS = [
    ("id", "最近更新"),
    ("reco", "精品推荐"),
    ("hits", "人气最高"),
    ("shits", "网友推荐"),
    ("rhits", "今日Top"),
    ("zhits", "本周Top"),
    ("yhits", "本月Top"),
    ("xhits", "下载榜"),
]
VALID_SORT = {k for k, _ in SORTS}
def _norm_extend(extend):
    """兼容 TVBox 传 extend 的各种形态: dict / None / '{}' / JSON串 / URL编码 / query串。"""
    if not extend:
        return {}
    if isinstance(extend, dict):
        return extend
    s = str(extend).strip()
    if not s:
        return {}
    try:
        if s.startswith("{"):
            d = json.loads(s)
            return d if isinstance(d, dict) else {}
        d = {}
        for kv in s.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                d[urllib.parse.unquote(k)] = urllib.parse.unquote(v)
        if d:
            return d
        d = json.loads(urllib.parse.unquote(s))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}
class Spider(Spider):
    def getName(self):
        return "水晶DJ网"
    def init(self, extend=""):
        try:
            super().init(extend)
        except Exception:
            pass
        self.site_url = "https://www.40dj.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
            "Referer": self.site_url + "/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.sess = None
        if _HAS_RQ:
            try:
                self.sess = requests.Session()
                self.sess.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])))
                self.sess.mount("http://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])))
            except Exception:
                self.sess = requests.Session()
        self.page_size = 30
        self.total = 9999
    def fetch(self, url, timeout=10):
        try:
            if self.sess:
                return self.sess.get(url, headers=self.headers, timeout=timeout, verify=False)
            import urllib.request
            req = urllib.request.Request(url, headers=self.headers)
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        except Exception:
            return None
    def fetch_text(self, url, timeout=10):
        r = self.fetch(url, timeout)
        if r is None:
            return ""
        return r.text if hasattr(r, "text") else str(r)
    def post_json(self, url, data, timeout=10):
        try:
            if self.sess:
                h = dict(self.headers)
                h["X-Requested-With"] = "XMLHttpRequest"
                r = self.sess.post(url, data=data, headers=h, timeout=timeout, verify=False)
                return r.json()
            import urllib.request
            req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                         headers=dict(self.headers, **{"X-Requested-With": "XMLHttpRequest"}))
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore"))
        except Exception:
            return {}
    @staticmethod
    def _txt(s):
        if not s:
            return ""
        s = re.sub(r"<[^>]+>", " ", s)
        return re.sub(r"\s+", " ", s).strip()
    def _abs(self, u):
        if not u:
            return ""
        u = u.strip()
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        return self.site_url + (u if u.startswith("/") else "/" + u)
    def _pic(self, u):

        u = self._abs(u)
        if not u:
            return ""
        if u.startswith(PIC_PROXY):
            return u
        hostpath = re.sub(r'^https?://', '', u)
        return PIC_PROXY + urllib.parse.quote(hostpath, safe="")
    def _parse_cards(self, html, limit=0):

        out, seen = [], set()
        li_pat = re.compile(
            r'<li\b[^>]*class\s*=\s*["\'][^"\']*'
            r'(?:single-item|info-item|radio-item|song-item|album-item|'
            r'music-item|playlist-item|list-item|single-item__)'
            r'[^"\']*["\'][^>]*>([\s\S]*?)</li>',
            re.I)
        for m in li_pat.finditer(html or ""):
            li = m.group(0)
            vid = ""
            dm = re.search(r'data-url\s*=\s*["\']([^"\']+)["\']', li)
            if dm:
                vid = dm.group(1).strip()
            else:
                lm = re.search(r'/music/(info|radio|topic)-([0-9]+)', li) or \
                     re.search(r'/(info|radio|topic)-([0-9]+)', li)
                if lm:
                    vid = lm.group(1) + "-" + lm.group(2)
            if not vid:
                continue
            if vid.isdigit():
                vod_id_out = "info-" + vid
            elif re.match(r'^(?:info|radio|topic)-\d+$', vid):
                vod_id_out = vid
            else:
                # data-url 形如 "radio-123" 以外的异常值, 保守转为 info-
                num = re.search(r'(\d+)', vid)
                vod_id_out = "info-" + num.group(1) if num else ""
                if not vod_id_out:
                    continue
            if vod_id_out in seen:
                continue
            nm = (re.search(r'data-title\s*=\s*["\']([^"\']+)["\']', li)
                  or re.search(r'lay-tips\s*=\s*["\']([^"\']+)["\']', li)
                  or re.search(r'class\s*=\s*["\'][^"\']*sname[^"\']*["\'][^>]*>([^<]+)<', li)
                  or re.search(r'<h[34][^>]*>\s*<a[^>]*>([^<]+)</a>', li)
                  or re.search(r'<h[34][^>]*>([^<]+)</h[34]>', li)
                  or re.search(r'<a[^>]*lay-tips[^>]*>([^<]+)</a>', li))
            name = self._txt(nm.group(1)) if nm else ""
            if not name:
                continue
            pm = (re.search(r'data-img\s*=\s*["\']([^"\']+)["\']', li)
                  or re.search(r'<img[^>]+src\s*=\s*["\']([^"\']+)["\']', li))
            pic = self._pic(pm.group(1)) if pm else ""
            rmk = re.search(r'<span>\s*<a[^>]*>([^<]+)</a>\s*\|\s*([^<]+?)\s*</span>', li)
            remark = f"{rmk.group(1).strip()} | {rmk.group(2).strip()}" if rmk else ""
            seen.add(vod_id_out)
            out.append({
                "vod_id": vod_id_out,
                "vod_name": name[:80],
                "vod_pic": pic,
                "vod_remarks": remark,
                "style": {"type": "rect", "ratio": 1},
            })
            if limit and len(out) >= limit:
                break
        return out
    def _parse_radio(self, html, limit=0):

        out, seen = [], set()
        text = html or ""
        # 每张卡片以 <div class="song_list"> ... </div> 为单元
        for m in re.finditer(r'<div[^>]*class\s*=\s*["\'][^"\']*\bsong_list\b[^"\']*["\'][^>]*>([\s\S]*?)</div>\s*</div>',
                             text, re.I):
            card = m.group(1)
            hm = re.search(r'href\s*=\s*["\'][^"\']*?/music/radio-(\d+)["\']', card)
            if not hm:
                continue
            rid = hm.group(1)
            if rid in seen:
                continue
            nm = (re.search(r'title\s*=\s*["\']([^"\']+)["\']', card)
                  or re.search(r'class\s*=\s*["\'][^"\']*item-info[^"\']*["\'][^>]*>\s*<a[^>]*>([^<]+)</a>', card)
                  or re.search(r'<img[^>]+alt\s*=\s*["\']([^"\']+)["\']', card))
            name = self._txt(nm.group(1)) if nm else ""
            if not name:
                continue
            pm = (re.search(r'<img[^>]+class\s*=\s*["\'][^"\']*radio[^"\']*["\'][^>]+src\s*=\s*["\']([^"\']+)["\']', card)
                  or re.search(r'<img[^>]+src\s*=\s*["\']([^"\']+)["\']', card))
            dm = re.search(r'class\s*=\s*["\'][^"\']*update-time[^"\']*["\'][^>]*>([^<]+)<', card)
            remark = dm.group(1).strip() if dm else ""
            seen.add(rid)
            out.append({
                "vod_id": "radio-" + rid,
                "vod_name": name[:80],
                "vod_pic": self._pic(pm.group(1)) if pm else "",
                "vod_remarks": remark,
                "style": {"type": "rect", "ratio": 1},
            })
            if limit and len(out) >= limit:
                break
        return out
    def _pagecount(self, html, tid):
        """从分页区提取最大页码。分页链接形如 /music/list-{sort}-{id}-{pg}，sort 段可变。"""
        pgs = [int(x) for x in re.findall(r'/list-[a-z]+-%s-(\d+)' % re.escape(str(tid)), html or "")]
        return max(pgs) if pgs else 1
    # 大类本身(list-1/2/3/5/6/7)也是站点真实页面, 作为默认"全部"视图。
    CAT_TREE = [
        ("串烧舞曲", "list-1", [("现场串烧", "list-8"), ("慢摇串烧", "list-4"),
                                ("酒吧慢摇", "list-17"), ("车载串烧", "list-23"),
                                ("MC现场", "list-24")]),
        ("中文舞曲", "list-2", [("中文Funky/House", "list-12"), ("中文Electro/House", "list-10"),
                                ("中文咚鼓/越鼓", "list-11"), ("中文House/Prog", "list-19"),
                                ("流行金曲", "list-25"), ("发烧经典", "list-26")]),
        ("慢歌连版", "list-5", []),
        ("纯音乐车载", "list-7", [("车载电子琴", "list-20"), ("葫芦丝演奏", "list-21"),
                                  ("电吹管演奏", "list-22")]),
        ("外文舞曲", "list-3", [("Electro/House", "list-13"), ("FunkyHouse/Prog", "list-14"),
                                ("Trap/HipHop/Rnb", "list-15"), ("Hardstyle/Techno", "list-16"),
                                ("Hard/Big/Trance", "list-43"), ("Dubstep/Bounce/Deep", "list-44"),
                                ("Bass/FUTURE", "list-45"), ("反差/榜单/私改", "list-46")]),
        ("交谊舞曲", "list-6", [("快四", "list-27"), ("快三", "list-28"), ("慢四", "list-29"),
                                ("中四", "list-30"), ("平四", "list-31"), ("贴面", "list-32"),
                                ("伦巴", "list-33"), ("桑巴", "list-34")]),
    ]
    def homeContent(self, filter):
        cate_list = [
            {"type_name": "DJ歌单", "type_id": "radio"},
        ]
        for name, tid, subs in self.CAT_TREE:
            cate_list.append({"type_name": name, "type_id": tid})
        cate_list += [
            {"type_name": "排行榜", "type_id": "rank"},
        ]
        sort_values = [{"n": name, "v": key} for key, name in SORTS]
        filters = {}
        for name, tid, subs in self.CAT_TREE:
            fs = []
            if subs:
                cat_values = [{"n": "全部" + name, "v": tid}] + \
                             [{"n": sn, "v": stid} for sn, stid in subs]
                fs.append({"key": "cat", "name": "子分类", "value": cat_values})
            fs.append({"key": "sort", "name": "榜单", "value": sort_values})
            filters[tid] = fs
        video_list = []
        res = self.fetch_text(self.site_url + "/music")
        if res:
            video_list = self._parse_cards(res)
        return {"class": cate_list, "filters": filters, "list": video_list}
    def homeVideoContent(self):
        res = self.fetch_text(self.site_url + "/music")
        return {"list": self._parse_cards(res) if res else []}
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        t = str(tid)
        ext = _norm_extend(extend)
        cat_id = None
        if t.startswith("list-"):
            cat_id = t.split("-")[1]
        # 子分类: 筛选栏选中的子分类覆盖当前分类 (extend: {"cat":"list-8"})
        sub = str(ext.get("cat") or "").strip()
        if sub.startswith("list-") and sub.split("-")[1].isdigit():
            cat_id = sub.split("-")[1]
            t = sub
        sort = str(ext.get("sort") or "id").strip()
        if sort not in VALID_SORT:
            sort = "id"
        if t == "music":
            url = self.site_url + "/music"
        elif t == "radio":
            url = self.site_url + "/music/radio-id-1"
        elif t == "video":
            url = self.site_url + "/video"
        elif t == "ring":
            url = self.site_url + "/ring"
        elif t == "rank":
            url = self.site_url + "/dance/opt/index"
        elif t == "user":
            url = self.site_url + "/user"
        elif t == "playsong":
            url = self.site_url + "/music/playsong"
        elif cat_id:
            url = f"{self.site_url}/music/list-{sort}-{cat_id}-{pg}"
        else:
            url = self.site_url + "/music"
        html = self.fetch_text(url)
        video_list = self._parse_cards(html)
        if not video_list and t in ("radio",):
            video_list = self._parse_radio(html)
        if not video_list:
            video_list = self._parse_radio(html)
        if cat_id and not video_list and not ext.get("sort"):
            url = f"{self.site_url}/music/list-reco-{cat_id}-{pg}"
            html = self.fetch_text(url)
            video_list = self._parse_cards(html)
            if not video_list:
                video_list = self._parse_radio(html)
        if t in ("music", "radio", "video", "ring", "rank", "user", "playsong"):
            pagecount = 1
        elif cat_id:
            pagecount = self._pagecount(html, cat_id)
        else:
            pagecount = pg + 1 if len(video_list) >= self.page_size else pg
        return {"list": video_list, "page": pg, "pagecount": pagecount,
                "limit": self.page_size, "total": self.total}
    def detailContent(self, ids):
        vod_id = ids[0] if ids else ""
        if not vod_id:
            return {"list": []}
        if vod_id.startswith("radio-"):
            rid = vod_id.split("-", 1)[1]
            html = self.fetch_text(self.site_url + "/music/radio-" + rid)
            tm = re.search(r"<title>([^<]+)</title>", html)
            name = self._txt(tm.group(1)) if tm else "电台" + rid
            name = re.split(r"[-_|｜—~·]", name)[0].strip()
            return {"list": [{"vod_id": vod_id, "vod_name": name,
                              "vod_play_from": "水晶DJ网", "vod_play_url": "第1集$" + rid}]}
        mid = vod_id.split("-", 1)[1] if "-" in vod_id else vod_id
        url = f"{self.site_url}/music/info-{mid}"
        html = self.fetch_text(url)
        if not html:
            return {"list": [{"vod_id": vod_id, "vod_name": "详情解析失败"}]}
        tm = re.search(r"<h1[^>]*>([\s\S]{0,120}?)</h1>", html) or re.search(r"<title>([\s\S]{0,120}?)</title>", html)
        name = self._txt(tm.group(1)) if tm else "曲目" + mid
        name = re.split(r"[-_|｜—~·]", name)[0].strip()
        pic_raw = ""
        for pat in (
            r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
            r'class="[^"]*(?:info|detail|cover)[^"]*"[^>]*>\s*<img[^>]+src="([^"]+)"',
            r'<img[^>]+data-img="([^"]+)"',
            r'<img[^>]+src="([^"]*(?:cover|picdata)[^"]*)"',
        ):
            pm = re.search(pat, html, re.I)
            if pm and pm.group(1).strip():
                pic_raw = pm.group(1)
                break
        pic = self._pic(pic_raw) if pic_raw else ""
        play_url = ""
        audio_m = re.search(r'<audio[^>]+src="([^"]+)"', html)
        if audio_m:
            play_url = audio_m.group(1)
        if not play_url:
            j = self.post_json(self.site_url + "/index.php/dance/play/json", {"id": mid})
            play_url = (j or {}).get("url") or ""
        if not play_url:
            play_url = mid  # 交给 playerContent 处理
        return {"list": [{"vod_id": vod_id, "vod_name": name, "vod_pic": pic,
                          "vod_play_from": "水晶DJ网", "vod_play_url": "第1集$" + play_url}]}
    def searchContent(self, key, quick, pg="1"):
        pg = int(pg) if str(pg).isdigit() else 1
        url = self.site_url + "/music/search?key=" + urllib.parse.quote(key)
        if pg > 1:
            url += "&page=%d" % pg
        html = self.fetch_text(url)
        video_list = self._parse_cards(html)
        return {"list": video_list, "page": pg,
                "pagecount": pg + 1 if len(video_list) >= self.page_size else pg,
                "limit": self.page_size, "total": len(video_list)}
    def playerContent(self, flag, id, vipFlags):
        play_url = id.split("$", 1)[1] if "$" in id else id
        req_headers = {"User-Agent": self.headers["User-Agent"], "Referer": self.site_url + "/"}
        if not play_url:
            return {"parse": 0, "url": "", "header": req_headers}
        if re.fullmatch(r"\d+", play_url):
            j = self.post_json(self.site_url + "/index.php/dance/play/json", {"id": play_url})
            play_url = (j or {}).get("url") or ""
            if not play_url:
                return {"parse": 0, "url": "", "header": req_headers}
        return {"parse": 0, "url": play_url, "header": req_headers}