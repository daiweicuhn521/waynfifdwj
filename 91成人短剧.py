import sys
import re
import json
import urllib.request
import urllib.parse

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        pass


class Spider(SpiderBase):
    def init(self, extend=""):
        self.siteName = "91成人短剧"
        self.siteUrl = "https://91crdj.com"
        self._ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36")

        # 支持 extend 传域名：init("host=https://新域名.com")
        ext = (extend or "").strip()
        for kv in ext.split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                if k.strip().lower() == "host" and v.strip():
                    h = v.strip()
                    if "://" not in h:
                        h = "https://" + h
                    self.siteUrl = h.rstrip("/")

        # 分类（按站点实际栏目调整 type_id）
        self.categories = [
            {"type_id": "duanju",    "type_name": "成人短剧"},
            {"type_id": "manju",     "type_name": "成人漫剧"},
            {"type_id": "zhenrenju", "type_name": "真人剧"},
            {"type_id": "shipin",    "type_name": "成人视频"},
            {"type_id": "manhua",    "type_name": "成人漫画"},
            {"type_id": "xiaoshuo",  "type_name": "成人小说"},
        ]

    def getName(self):
        return self.siteName

    def isVideoFormat(self, url):
        low = (url or "").lower()
        return any(k in low for k in (".m3u8", ".mp4", ".flv", ".ts"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ==================== HTTP ====================

    def _http_get(self, url, referer=None):
        headers = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": referer or (self.siteUrl + "/"),
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"[{self.siteName}] 请求失败 {url}: {e}")
            return ""

    # ==================== TVBox 接口 ====================

    def homeContent(self, filter):
        return {"class": self.categories, "filters": {}}

    def homeVideoContent(self):
        html = self._http_get(self.siteUrl)
        items = self._parse_list(html)
        return {"list": items[:20]}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        if page > 1:
            url = f"{self.siteUrl}/{tid}/page/{page}/"
        else:
            url = f"{self.siteUrl}/{tid}/"

        print(f"[{self.siteName}] 分类URL: {url}")
        html = self._http_get(url, referer=self.siteUrl + "/")
        items = self._parse_list(html)

        # 从 HTML 里尝试拿最大页
        pagecount = page + 1 if items else page
        mx = 1
        for m in re.finditer(r'/page/(\d+)/', html):
            try:
                v = int(m.group(1))
                if v > mx:
                    mx = v
            except Exception:
                pass
        if mx > 1:
            pagecount = mx

        return {
            "list": items,
            "page": page,
            "pagecount": pagecount,
            "limit": 20,
            "total": 999,
        }

    def searchContent(self, key, quick, pg="1"):
        page = int(pg or 1)
        kw = str(key or "").strip()
        if not kw:
            return {"list": [], "page": page, "pagecount": 1}

        url = f"{self.siteUrl}/search/?q={urllib.parse.quote(kw)}"
        if page > 1:
            url += f"&page={page}"

        html = self._http_get(url)
        items = self._parse_list(html)

        return {
            "list": items,
            "page": page,
            "pagecount": page + 1 if items else page,
            "limit": 20,
            "total": len(items),
        }

    def detailContent(self, ids):
        raw = str(ids[0] if isinstance(ids, (list, tuple)) else ids).strip()
        if not raw:
            return {"list": []}

        # vod_id 形如 "duanju|/duanju/1337-slug/"
        if "|" in raw:
            channel, path = raw.split("|", 1)
        else:
            channel, path = "", raw

        url = path if path.startswith("http") else (self.siteUrl + path)
        html = self._http_get(url, referer=self.siteUrl + "/")
        if not html:
            return {"list": []}

        # 标题
        title = ""
        t_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
        if t_m:
            title = re.sub(r'<[^>]+>', '', t_m.group(1)).strip()
        if not title:
            t_m = re.search(r'<title>(.*?)</title>', html, re.S)
            if t_m:
                title = re.split(r'[-_|]', t_m.group(1))[0].strip()

        # 封面：优先 data-original / data-src / og:image
        pic = ""
        for attr in ("data-original", "data-src", "data-echo", "data-url"):
            m = re.search(attr + r'\s*=\s*["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']', html, re.I)
            if m:
                pic = m.group(1).strip()
                break
        if not pic:
            m = re.search(r'<meta[^>]+og:image[^>]+content=["\']([^"\']+)["\']', html, re.I)
            if m:
                pic = m.group(1).strip()
        if pic.startswith('//'):
            pic = 'https:' + pic
        elif pic.startswith('/'):
            pic = self.siteUrl + pic

        # 简介
        intro = ""
        for pat in (
            r'<meta[^>]+og:description[^>]+content=["\']([^"\']*)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
            r'<div[^>]+class=["\'][^"\']*detail-content[^"\']*["\'][^>]*>(.*?)</div>',
        ):
            m = re.search(pat, html, re.S | re.I)
            if m:
                intro = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                if intro:
                    break

        # 播放列表：抓详情页里所有 /{channel}/{id}-{slug}/{ep}/ 或 /play/ 链接
        play_urls = []
        seen = set()

        # 方式1：ep-grid / playlist 里的集数链接
        ep_block = re.search(
            r'<div[^>]+class=["\'][^"\']*(?:ep-grid|playlist|ep-list)[^"\']*["\'][^>]*>(.*?)</div>',
            html, re.S | re.I
        )
        scan_html = ep_block.group(1) if ep_block else html

        # 匹配详情链接下一级的集数链接
        base_path = path.rstrip('/')
        for m in re.finditer(r'href=["\']([^"\']+)["\'][^>]*>\s*(\d+)\s*<', scan_html):
            href = m.group(1).strip()
            ep_no = m.group(2).strip()
            # 集数链接应该以 base_path 开头，或者包含 -1- 这样的播放页特征
            if base_path and base_path in href:
                if href.startswith('/'):
                    href = self.siteUrl + href
                if href in seen:
                    continue
                seen.add(href)
                play_urls.append(f"第{ep_no}集${href}")

        # 方式2：整页扫集数链接
        if not play_urls:
            for m in re.finditer(r'href=["\']([^"\']+)["\'][^>]*>\s*(\d+)\s*<', html):
                href = m.group(1).strip()
                ep_no = m.group(2).strip()
                if base_path and base_path in href and href not in seen:
                    if href.startswith('/'):
                        href = self.siteUrl + href
                    seen.add(href)
                    play_urls.append(f"第{ep_no}集${href}")

        # 方式3：兜底，找 /play/ 或 -1-1 这样的播放页
        if not play_urls:
            for m in re.finditer(r'href=["\']([^"\']*(?:/play/|-\d+-\d+\.html)[^"\']*)["\']', html):
                href = m.group(1).strip()
                if href.startswith('/'):
                    href = self.siteUrl + href
                elif not href.startswith('http'):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                play_urls.append(f"播放${href}")

        return {
            "list": [{
                "vod_id": raw,
                "vod_name": title,
                "vod_pic": pic,
                "vod_content": intro,
                "vod_remarks": f"共{len(play_urls)}集" if play_urls else "",
                "vod_play_from": self.siteName if play_urls else "",
                "vod_play_url": "#".join(play_urls),
            }]
        }

    def playerContent(self, flag, id, vipFlags):
        raw = str(id or "").strip()
        if not raw:
            return {"parse": 1, "url": raw}

        # 已经是 mp4/m3u8 直接返回
        if self.isVideoFormat(raw):
            return {
                "parse": 0,
                "url": raw,
                "header": {
                    "User-Agent": self._ua,
                    "Referer": self.siteUrl + "/",
                }
            }

        # 播放页 → 抓真实 m3u8/mp4
        html = self._http_get(raw, referer=self.siteUrl + "/")
        if not html:
            return {"parse": 1, "url": raw}

        m3u8_url = ""

        # 1) "current": {"src": "..."}
        m = re.search(r'"current"\s*:\s*\{[^{}]*"src"\s*:\s*"([^"]+)"', html)
        if m:
            m3u8_url = m.group(1)
            m3u8_url = m3u8_url.replace("\\/", "/").replace("\\u0026", "&")

        # 2) player_aaaa / player_data
        if not m3u8_url:
            for var in ("player_aaaa", "player_data"):
                m = re.search(var + r'\s*=\s*(\{[^;]*\})', html)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        m3u8_url = data.get("url") or data.get("link") or ""
                        if m3u8_url:
                            break
                    except Exception:
                        pass

        # 3) 任意 m3u8 / mp4 链接
        if not m3u8_url:
            m = re.search(r'(https?://[^\s"\'<>\\]+?\.(?:m3u8|mp4)[^\s"\'<>\\]*)', html)
            if m:
                m3u8_url = m.group(1)

        if m3u8_url:
            if m3u8_url.startswith('//'):
                m3u8_url = 'https:' + m3u8_url
            elif m3u8_url.startswith('/'):
                m3u8_url = self.siteUrl + m3u8_url
            return {
                "parse": 0,
                "url": m3u8_url,
                "header": {
                    "User-Agent": self._ua,
                    "Referer": raw,
                }
            }

        return {
            "parse": 1,
            "url": raw,
            "header": {
                "User-Agent": self._ua,
                "Referer": self.siteUrl + "/",
            }
        }

    # ==================== 列表解析 ====================

    def _parse_list(self, html):
        """匹配 class 含 card 的 <a> 卡片"""
        if not html:
            return []

        items = []
        seen = set()

        # 兼容单双引号、属性顺序
        card_re = re.compile(
            r'''<a[^>]*\bclass\s*=\s*["'][^"']*\bcard\b[^"']*["'][^>]*>(.*?)</a>''',
            re.S | re.I
        )

        for m in card_re.finditer(html):
            tag = m.group(0)
            block = m.group(1)

            # 详情链接
            hm = re.search(r'''href\s*=\s*["']([^"']+)["']''', tag, re.I)
            if not hm:
                continue
            href = hm.group(1).strip()

            # 从路径里提取 channel 和 id
            try:
                p = urllib.parse.urlparse(href).path
            except Exception:
                p = href
            seg = [s for s in p.split('/') if s]
            if len(seg) < 2:
                continue
            channel = seg[0]
            vid = seg[1]

            if vid in seen:
                continue

            # 标题：data-track-item-name / alt / title
            title = ""
            for attr in ("data-track-item-name", "alt", "title"):
                tm = re.search(attr + r'''\s*=\s*["']([^"']*)["']''', tag + block, re.I)
                if tm:
                    title = tm.group(1).strip()
                    if title:
                        break
            if not title:
                tm = re.search(r'<span[^>]*class="[^"]*p-title[^"]*"[^>]*>(.*?)</span>', block, re.S)
                if tm:
                    title = re.sub(r'<[^>]+>', '', tm.group(1)).strip()
            if not title:
                title = vid

            # 封面
            cover = ""
            for attr in ("data-original", "data-src", "data-echo", "data-url"):
                im = re.search(attr + r'''\s*=\s*["']([^"']+)["']''', block, re.I)
                if im:
                    cover = im.group(1).strip()
                    break
            if not cover:
                im = re.search(r'''<img[^>]*\bsrc\s*=\s*["']([^"']+)["']''', block, re.I)
                if im:
                    cover = im.group(1).strip()

            low = cover.lower()
            if any(bad in low for bad in ("data:", "load.gif", "loading.gif", "placeholder", "eisees")):
                cover = ""

            if cover.startswith('//'):
                cover = 'https:' + cover
            elif cover.startswith('/'):
                cover = self.siteUrl + cover

            # 备注：badge 或 eps-flag
            remarks = ""
            rm = re.search(r'<span[^>]*class="[^"]*(?:badge|eps-flag)[^"]*"[^>]*>(.*?)</span>', block, re.S)
            if rm:
                remarks = re.sub(r'<[^>]+>', '', rm.group(1)).strip()

            seen.add(vid)
            items.append({
                "vod_id": channel + "|" + p,
                "vod_name": title,
                "vod_pic": cover,
                "vod_remarks": remarks,
            })

        return items

    def localProxy(self, params):
        return [404, "text/plain; charset=utf-8", "disabled"]

    def liveContent(self):
        return ""

    def action(self, action):
        return {"msg": "ok"}