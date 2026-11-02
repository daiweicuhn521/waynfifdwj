# -*- coding: utf-8 -*-
# 绿色影视 lsysw.top 爬虫
import base64
import json
import re
import sys
from urllib.parse import quote

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):

    def init(self, extend=""):
        hosts = "https://lsysw.top"
        if extend:
            try:
                hosts = json.loads(extend).get('site', hosts)
            except Exception:
                pass
        self.host = self.host_late(hosts).rstrip('/')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Mobile Safari/537.36',
            'Referer': f'{self.host}/'
        }
        self.timeout = 10

    def getName(self):
        return "绿色影视"

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def homeContent(self, filter):
        classes = [
            {"type_name": "电影", "type_id": "1"},
            {"type_name": "电视剧", "type_id": "2"},
            {"type_name": "综艺", "type_id": "3"},
            {"type_name": "动漫", "type_id": "4"},
            {"type_name": "短剧", "type_id": "26"},
            {"type_name": "动作片", "type_id": "5"},
            {"type_name": "喜剧片", "type_id": "10"},
            {"type_name": "爱情片", "type_id": "6"},
            {"type_name": "科幻片", "type_id": "7"},
            {"type_name": "恐怖片", "type_id": "8"},
            {"type_name": "剧情片", "type_id": "12"},
            {"type_name": "战争片", "type_id": "9"},
            {"type_name": "纪录片", "type_id": "11"},
            {"type_name": "国产剧", "type_id": "13"},
            {"type_name": "港台剧", "type_id": "14"},
            {"type_name": "欧美剧", "type_id": "15"},
            {"type_name": "日韩剧", "type_id": "16"},
            {"type_name": "泰剧", "type_id": "27"},
        ]
        filters = {}
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        """首页热门推荐（优先取轮播区，避免混入顶部搜索热榜）"""
        url = f"{self.host}/index.html"
        try:
            html = self.fetch(url, headers=self.headers, timeout=self.timeout).text
            m = re.search(r'<div class="flickity[^"]*"[^>]*>(.*?)<div class="container"', html, re.S)
            body = m.group(1) if m else html
            vod_list = self._parse_vod_list(body)
            if not vod_list:
                vod_list = self._parse_vod_list(html)
            return {"list": vod_list[:30]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        # 站点的第 N 页是 frim/{tid}-{N}.html，第 1 页是 frim/{tid}.html
        # （frim/{tid}-1.html 会返回第 1 页，不能用来翻页）
        if pg <= 1:
            url = f"{self.host}/frim/{tid}.html"
        else:
            url = f"{self.host}/frim/{tid}-{pg}.html"
        try:
            html = self.fetch(url, headers=self.headers, timeout=self.timeout).text
            vod_list = self._parse_vod_list(html)
            pagecount = self._parse_page_count(html)
            return {
                "list": vod_list,
                "page": pg,
                "pagecount": pagecount,
                "limit": len(vod_list) or 20,
                "total": pagecount * 20
            }
        except Exception:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

    def searchContent(self, key, quick, pg="1"):
        pg = int(pg or 1)
        # 注意：不能带 searchtype=5，那是“筛选列表”模式，会返回全站列表而不是搜索结果
        url = f"{self.host}/search.php?searchword={quote(key, encoding='utf-8')}&page={pg}"
        try:
            html = self.fetch(url, headers=self.headers, timeout=self.timeout).text
            vod_list = self._parse_vod_list(html)
            # 如果搜索没结果，POST 再试一次
            if not vod_list:
                data = f"searchword={quote(key, encoding='utf-8')}"
                headers = dict(self.headers)
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
                resp = self.fetch(f"{self.host}/search.php", headers=headers, data=data.encode('utf-8'), timeout=self.timeout)
                html = resp.text
                vod_list = self._parse_vod_list(html)
            pagecount = self._parse_page_count(html)
            return {"list": vod_list, "page": pg, "pagecount": pagecount}
        except Exception:
            return {"list": [], "page": pg, "pagecount": 1}

    def detailContent(self, ids):
        vid = ids[0] if ids else ""
        if not vid:
            return {"list": []}
        url = f"{self.host}/movie/{vid}.html"
        vod = {
            "vod_id": vid,
            "vod_name": "",
            "vod_pic": "",
            "vod_content": "",
            "vod_year": "",
            "vod_area": "",
            "vod_actor": "",
            "vod_director": "",
            "type_name": "",
            "vod_remarks": "",
            "vod_play_from": "",
            "vod_play_url": ""
        }
        try:
            html = self.fetch(url, headers=self.headers, timeout=self.timeout).text

            # 片名
            m = re.search(r'<h1[^>]*class="title[^"]*"[^>]*>(.*?)</h1>', html, re.S)
            if not m:
                m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
            if m:
                h1_raw = m.group(1)
                # 备注（已完结 / 更新至xx / HD）
                rmk = re.search(r'<font[^>]*>(.*?)</font>', h1_raw, re.S)
                if rmk:
                    vod["vod_remarks"] = re.sub(r'<[^>]+>', '', rmk.group(1)).strip()
                    h1_raw = re.sub(r'<font[^>]*>.*?</font>', '', h1_raw, flags=re.S)
                vod["vod_name"] = re.sub(r'<[^>]+>', '', h1_raw).strip()

            # 封面：data-original 优先，其次 style 背景图
            m = re.search(r'<div class="myui-content__thumb".*?</a>', html, re.S)
            thumb = m.group(0) if m else html
            pic = ""
            pm = re.search(r'data-original="([^"]+)"', thumb)
            if pm:
                pic = pm.group(1)
            if not pic:
                pm = re.search(r"background:\s*url\(([^)]+)\)", thumb)
                if pm:
                    pic = pm.group(1).strip("'\" ")
            vod["vod_pic"] = self._fix_pic(pic)

            # 主演 / 导演
            actors = re.findall(r'<span class="text-muted">主演：</span>(.*?)</p>', html, re.S)
            if actors:
                vod["vod_actor"] = self._names(actors[0])
            directors = re.findall(r'<span class="text-muted">导演：</span>(.*?)</p>', html, re.S)
            if directors:
                vod["vod_director"] = self._names(directors[0])

            # 简介：优先完整剧情介绍
            summary = re.findall(r'id="jq".*?<div class="tab-content myui-panel_bd">(.*?)</div>', html, re.S)
            if summary:
                vod["vod_content"] = re.sub(r'<[^>]+>', '', summary[0]).strip()
            if not vod["vod_content"]:
                summary = re.findall(r'<span class="sketch[^"]*">(.*?)<a href="#jq"', html, re.S)
                if summary:
                    vod["vod_content"] = re.sub(r'<[^>]+>', '', summary[0]).strip().rstrip('.．')

            # 分类 / 地区 / 年份
            cat = re.findall(r'<span class="text-muted[^"]*">分类：</span><a[^>]*>(.*?)</a>', html, re.S)
            if cat:
                vod["type_name"] = cat[0].strip()
            area = re.findall(r'<span class="text-muted[^"]*">地区：</span><a[^>]*>(.*?)</a>', html, re.S)
            if area:
                vod["vod_area"] = area[0].strip()
            year = re.findall(r'<span class="text-muted[^"]*">年份：</span><a[^>]*>(.*?)</a>', html, re.S)
            if year:
                vod["vod_year"] = year[0].strip()

            # 线路标签：#playlistN -> 名称
            tab_names = {}
            for mm in re.finditer(r'<a\s+href="#playlist(\d+)"[^>]*>(.*?)</a>', html, re.S):
                nm = re.sub(r'<[^>]+>', '', mm.group(2)).strip()
                if nm:
                    tab_names[mm.group(1)] = nm

            # 逐线路解析，vfrom 用 playlistN 的 N，保证标签与线路一一对应
            groups = []
            url_arr = []
            for mm in re.finditer(r'<div id="playlist(\d+)"[^>]*>(.*?)</ul>', html, re.S):
                vfrom = mm.group(1)
                block = mm.group(2)
                eps = re.findall(r'<a[^>]*title="([^"]*)"[^>]*href="(/play/[^"]+)"', block)
                if not eps:
                    eps = [(t, p) for p, t in re.findall(r'href="(/play/[^"]+)"[^>]*>(.*?)</a>', block, re.S)]
                    eps = [(re.sub(r'<[^>]+>', '', t).strip(), p) for t, p in eps]
                if not eps:
                    continue
                groups.append(tab_names.get(vfrom, f"线路{vfrom}"))
                url_arr.append("#".join(f"{t}${p}" for t, p in eps if t))

            if groups:
                vod["vod_play_from"] = "$$$".join(groups)
                vod["vod_play_url"] = "$$$".join(url_arr)
            else:
                # 兜底：立即播放按钮
                bt = re.search(r'href="(/play/[^"]+\.html)"[^>]*>\s*<i class="fa fa-film"></i>', html)
                if bt:
                    vod["vod_play_from"] = "绿色影视"
                    vod["vod_play_url"] = f"正片${bt.group(1)}"
        except Exception as e:
            print(f"[绿色影视] detail error: {e}")

        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "url": "", "header": self.headers}
        play_url = id if id.startswith("http") else self.host + id
        try:
            html = self.fetch(play_url, headers=self.headers, timeout=self.timeout).text
            real = self._pick_url(html)
            if real:
                if re.search(r'\.(m3u8|mp4)', real):
                    return {"parse": 0, "url": real, "header": self.headers}
                return {"parse": 1, "url": real, "header": self.headers}

            # 当前线路无源（now 为空），改用同片其它线路
            mv = re.search(r'var\s+vid="(\d+)"', html)
            if mv:
                vid = mv.group(1)
                vp = re.search(r'var\s+vpart="(\d+)"', html)
                part = vp.group(1) if vp else "0"
                cur = re.search(r'var\s+vfrom="(\d+)"', html)
                cur_f = cur.group(1) if cur else ""
                for f in ["0", "1", "2", "3"]:
                    if f == cur_f:
                        continue
                    try:
                        h2 = self.fetch(f"{self.host}/play/{vid}-{f}-{part}.html",
                                        headers=self.headers, timeout=6).text
                        alt = self._pick_url(h2)
                        if alt:
                            # 直链走 parse=0；分享页也接受，交给壳子解析
                            if re.search(r'\.(m3u8|mp4)', alt):
                                return {"parse": 0, "url": alt, "header": self.headers}
                            return {"parse": 1, "url": alt, "header": self.headers}
                    except Exception:
                        continue
        except Exception as e:
            print(f"[绿色影视] player error: {e}")
        return {"parse": 1, "url": play_url, "header": self.headers}

    def localProxy(self, param):
        pass

    # ========== 工具方法 ==========

    def _pick_url(self, html):
        """从播放页取出真实地址：base64(now) -> m3u8/mp4 直链"""
        m = re.search(r'var\s+now\s*=\s*base64decode\("([^"]*)"\)', html)
        if m and m.group(1).strip():
            try:
                b64 = m.group(1).strip()
                b64 += "=" * (-len(b64) % 4)
                u = base64.b64decode(b64).decode('utf-8', 'ignore').strip()
                if u.startswith("http"):
                    return u
            except Exception:
                pass
        m = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', html)
        if not m:
            m = re.search(r'(https?://[^"\'\s]+\.mp4[^"\'\s]*)', html)
        if m:
            return m.group(1)
        return ""

    def _parse_vod_list(self, html):
        """从列表页 HTML 中解析影片信息（分类页 / 首页轮播 / 搜索结果通用）"""
        result = []
        seen = set()
        # 只取主列表，避开顶部搜索热榜的小列表
        m = re.search(r'<!-- 筛选 -->.*?<ul class="myui-vodlist[^"]*">(.*?)</ul>', html, re.S)
        if m:
            html = m.group(0)
        else:
            m = re.search(r'id="searchList"[^>]*>(.*?)</ul>', html, re.S)
            if m:
                html = m.group(0)

        for blk in re.split(r'<li[^>]*>|<div class="col-lg-\d+', html):
            mm = re.search(r'href="(/movie/(\d+)\.html)"[^>]*title="([^"]+)"', blk)
            if not mm:
                mm = re.search(r'class="myui-vodlist__thumb[^"]*"[^>]*href="/movie/(\d+)\.html"[^>]*title="([^"]+)"', blk)
                if mm:
                    mm = (None, mm.group(1), mm.group(2))
            if not mm:
                continue
            vid = mm.group(2)
            title = re.sub(r'<[^>]+>', '', mm.group(3)).strip()
            if not vid or not title or vid in seen:
                continue
            seen.add(vid)

            pic = ""
            pm = re.search(r'data-original="([^"]+)"', blk)
            if pm:
                pic = pm.group(1)
            if not pic:
                pm = re.search(r"background:\s*url\(([^)]+)\)", blk)
                if pm:
                    pic = pm.group(1).strip("'\" ")
            pic = self._fix_pic(pic)

            remark = ""
            rm = re.search(r'<span class="pic-text[^"]*">(.*?)</span>', blk, re.S)
            if rm:
                remark = re.sub(r'<[^>]+>', '', rm.group(1)).strip()
            if not remark:
                rm = re.search(r'>(更新至[^<]*|已完结|HD[^<]*)<', blk)
                if rm:
                    remark = rm.group(1).strip()

            result.append({"vod_id": vid, "vod_name": title, "vod_pic": pic, "vod_remarks": remark})
        return result

    def _parse_page_count(self, html):
        """页数：分类页 frim/x-N.html，搜索页 ?page=N"""
        nums = [int(x) for x in re.findall(r'/frim/\d+-(\d+)\.html', html)]
        nums += [int(x) for x in re.findall(r'[?&]page=(\d+)', html)]
        if nums:
            return max(nums)
        return 1

    def _fix_pic(self, pic):
        pic = (pic or "").strip()
        if not pic:
            return ""
        if pic.startswith("//"):
            return "https:" + pic
        if pic.startswith("/img.php?url="):
            return self.host + pic
        if pic.startswith("/"):
            return self.host + pic
        return pic

    def _names(self, block):
        names = re.findall(r'searchword=[^"]*">(.*?)</a>', block)
        if not names:
            names = re.findall(r'>([^<]+?)<', block)
        out = []
        for n in names:
            n = re.sub(r'&nbsp;+', '', n).strip()
            if n and n not in ("内详", "..", "...", "/") and len(n) > 1:
                out.append(n)
        return ",".join(out)

    def host_late(self, url_list):
        if isinstance(url_list, str):
            urls = [u.strip() for u in url_list.split(',') if u.strip()]
        else:
            urls = [u for u in url_list if u]
        if not urls:
            return ""
        if len(urls) == 1:
            return urls[0]
        import time
        import threading
        res = {}

        def test(u):
            try:
                st = time.time()
                import requests
                requests.get(u, timeout=2, allow_redirects=False, headers={"User-Agent": "Mozilla/5.0"})
                res[u] = (time.time() - st) * 1000
            except Exception:
                res[u] = float('inf')

        ths = []
        for u in urls:
            t = threading.Thread(target=test, args=(u,))
            t.daemon = True
            t.start()
            ths.append(t)
        for t in ths:
            t.join(3)
        if not res:
            return urls[0]
        return min(res.items(), key=lambda x: x[1])[0]

    def fetch(self, url, headers=None, **kwargs):
        import requests
        if headers is None:
            headers = self.headers

        class FakeResp:
            def __init__(self):
                self.text = ""
                self.content = b""
                self.status_code = 0
                self.headers = {}
                self.ok = False

            def json(self):
                return {}
        try:
            return requests.get(url, headers=headers, **kwargs)
        except Exception as e:
            print(f"[绿色影视] fetch error {url} -> {e}")
            return FakeResp()
