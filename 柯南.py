# coding=utf-8
"""
柯南影视 TVBox 爬虫 (MacCMS v10)
修复内容：
1. categoryContent: 真正请求分类/筛选列表页，支持翻页和筛选
2. searchContent: 修正返回格式为 {"list": [...]}，兼容多种搜索URL
3. playerContent/_parse_play_page: 增加 encrypt 字段处理、增强解码和容错
4. 修复搜索功能：域名探测顺序改为 www.knvod.com 优先
5. 修复 _fetch 方法：固定UA避免破坏Cloudflare Cookie一致性
6. 重写 _extract_cards 方法：适配当前网站实际DOM结构
7. 修复 API 域名：优先使用 working_domain 而非固定 m.knvod.me
"""

import re
import json
import base64
import zlib
import hashlib
import time
from collections import OrderedDict
from urllib.parse import unquote, quote

import requests
from base.spider import Spider


class Spider(Spider):

    def init(self, extend=""):
        self.extend = extend
        self.default_pic = "https://www.knvod.com/static/img/default.png"
        # 域名探测顺序：www.knvod.com 当前可用，放第一位
        self.domains = [
            "https://www.knvod.com",
            "https://knvod.me",
            "https://www.knvod.me",
            "http://www.knvod.com",
            "https://m.knvod.com",
            "https://m.knvod.me",
        ]
        self.working_domain = ""
        self.ua_list = [
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.159 Mobile Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 13; 2211133C) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
        ]
        self._ua_idx = 0
        self.ua = self.ua_list[0]
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
        self.categories = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "连续剧"},
            {"type_id": "3", "type_name": "动漫"},
            {"type_id": "4", "type_name": "综艺"},
        ]
        self.filter_config = [
            {"key": "class", "name": "类型", "value": [
                {"n":"喜剧","v":"喜剧"},{"n":"爱情","v":"爱情"},{"n":"恐怖","v":"恐怖"},
                {"n":"动作","v":"动作"},{"n":"科幻","v":"科幻"},{"n":"剧情","v":"剧情"},
                {"n":"战争","v":"战争"},{"n":"警匪","v":"警匪"},{"n":"犯罪","v":"犯罪"},
                {"n":"动画","v":"动画"},{"n":"奇幻","v":"奇幻"},{"n":"武侠","v":"武侠"},{"n":"冒险","v":"冒险"},
            ]},
            {"key": "area", "name": "地区", "value": [
                {"n":"内地","v":"内地"},{"n":"港台","v":"港台"},{"n":"美国","v":"美国"},
                {"n":"韩国","v":"韩国"},{"n":"日本","v":"日本"},{"n":"泰国","v":"泰国"},
                {"n":"印度","v":"印度"},{"n":"法国","v":"法国"},{"n":"英国","v":"英国"},
            ]},
            {"key": "year", "name": "年份", "value": [{"n":str(y),"v":str(y)} for y in range(2026,2009,-1)]},
            {"key": "lang", "name": "语言", "value": [
                {"n":"国语","v":"国语"},{"n":"粤语","v":"粤语"},{"n":"韩语","v":"韩语"},
                {"n":"日语","v":"日语"},{"n":"英语","v":"英语"},{"n":"泰语","v":"泰语"},
            ]},
            {"key": "by", "name": "排序", "value": [
                {"n":"最新","v":"time"},{"n":"最热","v":"hits"},{"n":"评分","v":"score"},
            ]},
        ]
        self.filters = {}
        for c in self.categories:
            self.filters[c["type_id"]] = self.filter_config
        self._cache_cards = []
        self._cache_sections = {}
        self._cache_loaded = False
        self._page_size = 24
        self.cookies = ""
        self._probe_domain()

    def getName(self):
        return "柯南影视"

    def isVideoFormat(self, url):
        if not url: return False
        u = url.lower()
        return any(x in u for x in
            [".m3u8",".mp4",".flv",".avi",".mov",".mkv",".wmv",".ts",".rmvb",".webm"])

    def manualWebSearch(self):
        return False

    def _clean(self, text):
        if not text: return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'&[a-z]+;', ' ', text)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _probe_domain(self):
        for domain in self.domains:
            try:
                # 第一次请求首页（可能触发Cloudflare挑战，返回403/短内容）
                r = self.session.get(f"{domain}/", timeout=8)
                if r.status_code == 200 and len(r.text) > 500:
                    self.working_domain = domain
                    self.session.headers["Referer"] = f"{domain}/"
                    return
                # 403或内容过短（Cloudflare验证页），等一秒重试同域名
                if r.status_code == 403 or (r.status_code == 200 and len(r.text) < 200):
                    time.sleep(1)
                    r2 = self.session.get(f"{domain}/", timeout=8)
                    if r2.status_code == 200 and len(r2.text) > 500:
                        self.working_domain = domain
                        self.session.headers["Referer"] = f"{domain}/"
                        return
                    # 还不行，尝试详情页
                    if r2.status_code == 403 or (r2.status_code == 200 and len(r2.text) < 200):
                        time.sleep(1)
                        test = self.session.get(f"{domain}/vdetail/1.html",
                            timeout=8, headers={"Referer": f"{domain}/"})
                        if test.status_code == 200 and len(test.text) > 1000:
                            self.working_domain = domain
                            self.session.headers["Referer"] = f"{domain}/"
                            return
            except:
                continue
        if not self.working_domain:
            self.working_domain = self.domains[0] if self.domains else "http://www.knvod.com"

    def _fetch(self, url, timeout=10, retry=3):
        if url.startswith("/"):
            url = self.working_domain + url
        for i in range(retry):
            try:
                self.session.headers["User-Agent"] = self.ua
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    txt = r.text
                    if len(txt) >= 200:
                        # 内容足够长，或已到最后一轮重试（200-500字节可能是
                        # 正常短页面而非验证页），直接返回，避免最后一轮丢内容
                        return txt
                    # 内容极短（<200字节）可能是Cloudflare验证页
                    # 重试同URL，让requests.Session自动携带已获取的Cookie
                    time.sleep(1)
                    continue
                # 403/429 -> 先访问首页获取Cookie，再重试同URL
                if r.status_code in (403, 429):
                    time.sleep(1.5 * (i + 1))
                    # 访问首页获取Cookie（不换域名）
                    try:
                        self.session.get(f"{self.working_domain}/", timeout=timeout)
                    except:
                        pass
                    continue
            except:
                if i < retry - 1:
                    time.sleep(1)
                    continue
        return ""

    def _fix_url(self, url):
        if not url: return self.default_pic
        if url.startswith("//"): url = "https:" + url
        if url.startswith("/"): url = self.working_domain + url
        if "921080.xyz" in url:
            m = re.search(r'url=([^&]+)', url)
            if m:
                try: url = unquote(m.group(1))
                except: url = m.group(1)
        return url

    # ============================================================
    # 翻页（API 方式，参考第二个文件柯南.py）
    # ============================================================

    UID = "DCC147D11943AF75"

    def _md5(self, s):
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    def _api_post(self, body_dict, referer=""):
        t = int(time.time())
        key = self._md5("DS" + str(t) + self.UID)
        payload = dict(body_dict)
        payload["time"] = str(t)
        payload["key"] = key
        try:
            from urllib.parse import urlencode
            data = urlencode(payload).encode("utf-8")
        except Exception:
            data = ""
        # API 域名优先使用当前 working_domain，失败再回退
        api_domains = [self.working_domain] if self.working_domain else ["https://www.knvod.com"]
        fallback_domains = ["https://www.knvod.com", "https://knvod.me"]
        for fd in fallback_domains:
            if fd not in api_domains:
                api_domains.append(fd)
        last_err = None
        for dom in api_domains:
            url = dom + "/index.php/api/vod"
            headers = {
                "User-Agent": self.ua,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": referer or (dom + "/"),
            }
            for i in range(3):
                try:
                    # 依赖 session 的 cookie jar 自动保留 Set-Cookie；
                    # 不再手动拼 Cookie（首条 Set-Cookie 无 domain 信息，跨域
                    # fallback 到 knvod.me 时会污染请求）
                    r = self.session.post(url, data=data, headers=headers, timeout=10)
                    if r.status_code == 200 and r.text:
                        try:
                            return json.loads(r.text)
                        except Exception:
                            return None
                except Exception as e:
                    last_err = e
                    if i < 2:
                        time.sleep(1)
                        continue
        return None

    def _fmt_list(self, items):
        out = []
        seen = set()
        for it in items or []:
            vid = it.get("vod_id") or it.get("vodid") or ""
            if not vid or vid in seen:
                continue
            seen.add(vid)
            pic = it.get("vod_pic") or it.get("vod_pic_thumb") or ""
            out.append({
                "vod_id": str(vid),
                "vod_name": it.get("vod_name", "") or "",
                "vod_pic": self._fix_url(pic),
                "vod_remarks": it.get("vod_remarks", "") or "",
                "vod_year": it.get("vod_year") or it.get("vod_time") or "",
                "vod_score": it.get("vod_score") or "",
                "vod_actor": it.get("vod_actor", "") or "",
            })
        return out

    def _extract_cards(self, html):
        """抽取首页/搜索页/分类页卡片，适配当前网站实际DOM结构"""
        cards = []

        # 1. 搜索页模式: public-list-box search-box 容器
        # 注意: public-list-prb（备注）在DOM中出现在 thumb-txt（标题）之前
        # 结构: <div class="public-list-box search-box ...">
        #          <a href="/vdetail/81163.html"><img data-src="..." />
        #          <span class="public-list-prb ...">REMARKS</span></a>
        #          <div class="thumb-txt ..."><a>NAME</a></div>
        #        </div>
        # 先尝试严格匹配
        for block in re.finditer(
            r'<div[^>]*class="[^"]*?public-list-box[^"]*?search-box[^"]*?"[^>]*>'
            r'.*?/vdetail/(\d+)\.html'
            r'.*?data-src="([^"]*)"'
            r'.*?public-list-prb[^>]*>([^<]*)<'  # 备注：先出现
            r'.*?thumb-txt[^>]*>\s*<a[^>]*>([^<]+)</a>',  # 标题：后出现
            html, re.DOTALL
        ):
            cards.append({
                "vod_id": block.group(1).strip(),
                "vod_name": block.group(4).strip(),  # thumb-txt（标题）
                "vod_pic": self._fix_url(block.group(2).strip()),  # data-src（图片）
                "vod_remarks": block.group(3).strip(),  # public-list-prb（备注）
            })
        if cards:
            return cards

        # 1b. 搜索页宽松模式：search-box 容器内，逐块提取 vdetail + data-src + 标题
        for block in re.finditer(
            r'<div[^>]*class="[^"]*?public-list-box[^"]*?search-box[^"]*?"[^>]*>'
            r'.*?/vdetail/(\d+)\.html'
            r'.*?</div>\s*</div>',
            html, re.DOTALL
        ):
            block_text = block.group(0)
            vid = block.group(1).strip()
            # 取图片
            img_m = re.search(r'data-src="([^"]*)"', block_text)
            img = img_m.group(1) if img_m else ""
            # 取备注（public-list-prb 或 thumb-txt 中的备注）
            remarks_m = re.search(r'public-list-prb[^>]*>([^<]*)<', block_text)
            remarks = remarks_m.group(1).strip() if remarks_m else ""
            # 取标题：thumb-txt 内的 a 标签，或 a 的 title 属性
            name_m = re.search(r'thumb-txt[^>]*>\s*<a[^>]*>([^<]+)</a>', block_text)
            if not name_m:
                name_m = re.search(r'<a[^>]*title="([^"]*)"', block_text)
            if not name_m:
                name_m = re.search(r'<a[^>]*>([^<]{2,40})</a>', block_text)
            name = name_m.group(1).strip() if name_m else ""
            if vid and name:
                cards.append({
                    "vod_id": vid,
                    "vod_name": name,
                    "vod_pic": self._fix_url(img),
                    "vod_remarks": remarks,
                })
        if cards:
            return cards

        # 2. 首页/分类页模式: div.public-list-box + time-title（实际结构）
        # 结构: <div class="public-list-box ...">
        #          <a href="/vdetail/128396.html" title="御廷谣">
        #            <img data-src="https://..." />
        #          </a>
        #          <div class="public-list-button">
        #            <a class="time-title ..." href="/vdetail/128396.html" title="御廷谣">御廷谣</a>
        #          </div>
        #        </div>
        for block in re.finditer(
            r'<div[^>]*class="[^"]*?public-list-box[^"]*?"[^>]*>'
            r'.*?/vdetail/(\d+)\.html[^>]*title="([^"]*)"'
            r'.*?data-src="([^"]*)"'
            r'.*?</div>\s*</div>',
            html, re.DOTALL
        ):
            vid = block.group(1).strip()
            name = block.group(2).strip()
            img = block.group(3).strip()
            if vid and name:
                cards.append({
                    "vod_id": vid,
                    "vod_name": name,
                    "vod_pic": self._fix_url(img),
                    "vod_remarks": "",
                })

        if not cards:
            # 3. 兜底模式: 扫描所有 vdetail 链接
            for m in re.finditer(r'vdetail/(\d+)\.html[^>]*title="([^"]*)"', html):
                vid = m.group(1)
                name = m.group(2).strip()
                block = html[max(0, m.start()-300):m.end()]
                img_m = re.search(r'data-src="([^"]*)"', block)
                img = img_m.group(1) if img_m else ""
                if vid and name:
                    cards.append({"vod_id": vid, "vod_name": name,
                                  "vod_pic": self._fix_url(img), "vod_remarks": ""})
        # 去重
        seen = set()
        return [c for c in cards if not (c["vod_id"] in seen or seen.add(c["vod_id"]))]

    def _load_homepage(self):
        if self._cache_loaded:
            return self._cache_cards, self._cache_sections
        html = self._fetch(f"{self.working_domain}/")
        if not html or len(html) < 1000:
            self._fetch(f"{self.working_domain}/vdetail/1.html", timeout=8)
            html = self._fetch(f"{self.working_domain}/")
        if not html or len(html) < 1000:
            return [], {}
        sections = []
        for m in re.finditer(r'<h2[^>]*this-name[^>]*>(.*?)</h2>', html, re.DOTALL):
            title = self._clean(m.group(1))
            if title:
                sections.append((m.start(), title))
        all_cards = []
        section_cards = {}
        for i, (pos, title) in enumerate(sections):
            end = sections[i+1][0] if i+1 < len(sections) else len(html)
            cards = self._extract_cards(html[pos:end])
            section_cards[title] = cards
            all_cards.extend(cards)
        if not all_cards:
            all_cards = self._extract_cards(html)
            section_cards["全部"] = all_cards
        self._cache_cards = all_cards
        self._cache_sections = section_cards
        self._cache_loaded = True
        return all_cards, section_cards

    # ============================================================
    # 播放URL解码（增强版）
    # ============================================================

    @staticmethod
    def _unescape_unicode(s):
        # 解码 %uXXXX / \\uXXXX 形式的 unicode 转义。
        # urllib.parse.unquote 只认 %XX，不认 %uXXXX，必须手工转成字符。
        if not s:
            return s
        def _rep(m):
            try:
                return chr(int(m.group(1), 16))
            except ValueError:
                return m.group(0)
        return re.sub(r'(?:%u|\\u)([0-9a-fA-F]{4})', _rep, s)

    def _decode_play_url(self, encoded):
        if not encoded or len(encoded) < 10:
            return ""
        # 尝试直接 base64 + zlib
        try:
            dec = base64.b64decode(encoded)
            for w in [15, -15, 31]:
                try:
                    r = zlib.decompress(dec, w).decode('utf-8', errors='ignore')
                    if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
                except: pass
        except: pass
        # 清理后重试
        cleaned = re.sub(r'[^A-Za-z0-9+/=]', '', encoded)
        if cleaned != encoded:
            try:
                dec = base64.b64decode(cleaned)
                for w in [15, -15, 31]:
                    try:
                        r = zlib.decompress(dec, w).decode('utf-8', errors='ignore')
                        if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
                    except: pass
            except: pass
        # 去除常见干扰字符
        for noise in ['iilil','ollill','ilil','oll','lili','olol','IIII','LLLL','iili','illi']:
            if noise in encoded:
                try:
                    dec = base64.b64decode(encoded.replace(noise, ''))
                    for w in [15, -15, 31]:
                        try:
                            r = zlib.decompress(dec, w).decode('utf-8', errors='ignore')
                            if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
                        except: pass
                except: pass
        # 尝试纯 base64
        try:
            r = base64.b64decode(encoded).decode('utf-8', errors='ignore')
            if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
        except: pass
        # 尝试 unescape（针对 encrypt=1；%uXXXX 需手工转成 unicode 字符）
        try:
            r = unquote(self._unescape_unicode(encoded))
            if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
        except: pass
        # 新增：尝试 base64 解码后直接取 http 链接
        try:
            dec = base64.b64decode(encoded).decode('utf-8', errors='ignore')
            found_urls = re.findall(r'https?://[^\s"\'<>]+', dec)
            if found_urls:
                return found_urls[0]
        except: pass
        # 新增：尝试处理 eval 加密字符串（部分 MacCMS 变种）
        try:
            m = re.search(r"['\"]([A-Za-z0-9+/=]{40,})['\"]", encoded)
            if m:
                return self._decode_play_url(m.group(1))
        except: pass
        # 新增：尝试 URL-safe base64
        try:
            safe = encoded.replace('-', '+').replace('_', '/')
            dec = base64.b64decode(safe)
            for w in [15, -15, 31]:
                try:
                    r = zlib.decompress(dec, w).decode('utf-8', errors='ignore')
                    if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
                except: pass
            r = dec.decode('utf-8', errors='ignore')
            if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
        except: pass
        # 新增：decompressobj 容错解码（处理尾部垃圾字节）
        try:
            dec = base64.b64decode(encoded)
            for w in [15, -15, 31]:
                try:
                    dobj = zlib.decompressobj(w)
                    r = dobj.decompress(dec)
                    # 尝试消费尾部垃圾数据
                    try:
                        r += dobj.flush()
                    except:
                        pass
                    r = r.decode('utf-8', errors='ignore')
                    if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
                except: pass
        except: pass
        # 新增：截断重试（从尾部逐字节截断直到解压成功）
        try:
            dec = base64.b64decode(encoded)
            for w in [15, -15, 31]:
                for tail in range(len(dec), 20, -1):
                    try:
                        r = zlib.decompress(dec[:tail], w).decode('utf-8', errors='ignore')
                        if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
                    except:
                        continue
        except: pass
        # 新增：尝试从尾部截断 base64 字符串
        for tail in range(len(encoded), 20, -1):
            try:
                dec = base64.b64decode(encoded[:tail])
                for w in [15, -15, 31]:
                    try:
                        r = zlib.decompress(dec, w).decode('utf-8', errors='ignore')
                        if r and ('http' in r or '.m3u8' in r or '.mp4' in r): return r
                    except: pass
            except:
                continue
        return ""

    # ============================================================
    # 详情页解析
    # ============================================================

    def _parse_detail(self, vid):
        html = self._fetch(f"{self.working_domain}/vdetail/{vid}.html")
        if not html or len(html) < 500:
            return {"vod_id": vid, "vod_name": "", "vod_pic": self.default_pic,
                    "vod_play_from": "", "vod_play_url": ""}
        info = {"vod_id": vid}
        m = re.search(r'slide-info-title[^>]*>(.*?)<', html, re.DOTALL)
        info["vod_name"] = self._clean(m.group(1)) if m else ""
        m = re.search(r'data-src="([^"]*)"', html)
        info["vod_pic"] = self._fix_url(m.group(1)) if m else self.default_pic
        m = re.search(r'id="height_limit"[^>]*>(.*?)</div>', html, re.DOTALL)
        info["vod_content"] = self._clean(m.group(1)) if m else ""
        for label, key in [("导演","vod_director"),("演员","vod_actor"),
                           ("年份","vod_year"),("地区","vod_area"),
                           ("类型","vod_type"),("语言","vod_lang")]:
            m = re.search(rf'{label}[：:]\s*(?:</strong>)?\s*([^<]+)', html)
            if m: info[key] = self._clean(m.group(1))
        m = re.search(r'slide-info-remarks[^>]*>(.*?)<', html, re.DOTALL)
        info["vod_remarks"] = self._clean(m.group(1)) if m else ""
        info["vod_play_from"], info["vod_play_url"] = self._parse_plays(html, vid)
        return info

    def _parse_plays(self, html, vid):
        # 1. 提取线路名称（swiper-slide 标签）
        tabs = []
        # 直接匹配 swiper-slide 的 a 标签，保留完整内容后清理
        for m in re.finditer(
            r'<a[^>]*class="[^"]*swiper-slide[^"]*"[^>]*>(.*?)</a>',
            html, re.DOTALL
        ):
            name = self._clean(m.group(1))
            if name and name not in tabs:
                tabs.append(name)

        # 2. 提取所有剧集链接（不依赖容器结构，直接扫页面）
        # 格式: /vplay/{vid}-{source}-{ep}.html
        all_eps = re.findall(
            r'/vplay/(\d+)-(\d+)-(\d+)\.html[^>]*>(.*?)</a>',
            html, re.DOTALL
        )
        if not all_eps:
            return "", ""

        # 3. 按 source（第二个数字）分组，每个 source 是一条线路
        source_groups = OrderedDict()
        for v, s, n, ep in all_eps:
            s = s.strip()
            if s not in source_groups:
                source_groups[s] = []
            source_groups[s].append((v, s, n, ep))

        # 4. 构建线路名和剧集列表
        from_list = []
        url_list = []
        source_keys = list(source_groups.keys())

        for idx, s_key in enumerate(source_keys):
            # 线路名：优先用 tab 名称，否则用 "线路N"
            line_name = f"线路{idx+1}"
            if idx < len(tabs):
                line_name = tabs[idx]

            eps = source_groups[s_key]
            # 按集数正序排序（第1集在前）；非纯数字集数（预告/花絮等）排最前
            eps.sort(key=lambda x: int(x[2]) if x[2].isdigit() else 0)
            episodes = []
            for v, s, n, ep in eps:
                ep_name = self._clean(ep)
                episodes.append(f"{ep_name}${self.working_domain}/vplay/{v}-{s}-{n}.html")
            if episodes:
                from_list.append(line_name)
                url_list.append("#".join(episodes))

        if not from_list:
            return "", ""
        return "$$$".join(from_list), "$$$".join(url_list)

    # ============================================================
    # 播放页解析（核心修复）
    # ============================================================

    def _parse_play_page(self, url, headers):
        if url.startswith("/"):
            url = self.working_domain + url
        html = self._fetch(url, timeout=8)
        if not html:
            return {"parse": 1, "url": url, "header": headers}

        # 1. 提取 player_aaaa / player_data / MacPlayer.Config 等变量
        json_str = None
        player_data = None

        # 增加更多可能的变量名
        for var_name in [
            'player_aaaa', 'player_data', 'MacPlayer.Config',
            'playerConfig', 'playerUrl', 'playUrl',
            'woodyPlayer', 'maccmsPlayer', 'vod_player',
            'Mp4Config', 'playerA', 'playerB',
        ]:
            idx = html.find(var_name)
            if idx >= 0:
                # 查找等号或冒号后的第一个 {
                eq = html.find('=', idx)
                colon = html.find(':', idx)
                brace_start = -1
                if eq >= 0 and (colon < 0 or eq < colon):
                    brace_start = html.find('{', eq)
                elif colon >= 0:
                    brace_start = html.find('{', colon)
                else:
                    brace_start = html.find('{', idx)
                if brace_start >= 0:
                    count = 0
                    for i in range(brace_start, len(html)):
                        if html[i] == '{': count += 1
                        elif html[i] == '}': count -= 1
                        if count == 0:
                            json_str = html[brace_start:i+1]
                            break
                if json_str:
                    try:
                        player_data = json.loads(json_str)
                        break
                    except:
                        json_str = None
                        player_data = None

        if player_data:
            pu = player_data.get("url", "")
            encrypt = player_data.get("encrypt", "0")

            # 处理 MacCMS encrypt 字段
            if encrypt == "1" and pu:
                try:
                    pu = unquote(self._unescape_unicode(pu))
                except: pass
            elif encrypt == "2" and pu:
                try:
                    pu = unquote(base64.b64decode(pu).decode('utf-8', errors='ignore'))
                except: pass
            # 新增：encrypt=3 或其他情况，尝试多种解码
            elif encrypt not in ("0", "") and pu:
                dec = self._decode_play_url(pu)
                if dec:
                    pu = dec
            # 统一补全协议相对/站内相对地址，避免返回 //host/x.m3u8 导致播放失败
            pu = self._fix_url(pu)

            if self.isVideoFormat(pu):
                h = dict(headers); h["Referer"] = url
                return {"parse": 0, "url": pu, "header": h}

            # 尝试解码
            dec = self._decode_play_url(pu)
            if dec:
                try:
                    obj = json.loads(dec)
                    if isinstance(obj, dict):
                        real_url = obj.get("url", dec)
                    else:
                        real_url = dec
                except:
                    real_url = dec
                real_url = self._fix_url(real_url)
                if real_url.startswith("http"):
                    h = dict(headers); h["Referer"] = url
                    if self.isVideoFormat(real_url):
                        return {"parse": 0, "url": real_url, "header": h}
                    return {"parse": 1, "url": real_url, "header": h}

            # 特殊处理：encrypt=0 且 url 是加密字符串（非视频地址）
            # 模拟 parse.js 的行为，直接返回第三方解析 iframe 地址
            if encrypt == "0" and pu and not self.isVideoFormat(pu) and not pu.startswith("http"):
                link_next = player_data.get("link_next", "")
                domain = url.split("/vplay/")[0] if "/vplay/" in url else self.working_domain
                if domain.startswith("http") and domain.count("/") > 2:
                    domain = "//" + domain.split("/")[2]
                # 构造第三方解析地址（与 parse.js 一致）
                try:
                    import urllib.parse
                    parse_url = "https://xn--ewr.211997.xyz/ppy.php?url=" + urllib.parse.quote(pu, safe='')
                    if link_next:
                        parse_url += "&next=" + urllib.parse.quote(domain + link_next, safe='')
                    # 提取标题
                    title = ""
                    vod_name = player_data.get("vod_data", {}).get("vod_name", "")
                    if vod_name:
                        title = vod_name
                    if title:
                        parse_url += "&title=" + urllib.parse.quote(title, safe='')
                except:
                    parse_url = "https://xn--ewr.211997.xyz/ppy.php?url=" + pu
                h = dict(headers); h["Referer"] = url
                return {"parse": 1, "url": parse_url, "header": h}

        # 2. 查找 iframe / video / source 标签（递归解析 iframe 嵌套）
        for src in re.findall(r'<iframe[^>]*src="([^"]+)"', html):
            src = self._fix_url(src)
            if self.isVideoFormat(src):
                h = dict(headers); h["Referer"] = url
                return {"parse": 0, "url": src, "header": h}
            if src.startswith("http"):
                # 递归解析 iframe 嵌套（4K/DP播放器等）
                if 'player' in src.lower() or 'play' in src.lower() or 'vod' in src.lower() or 'm3u8' in src.lower():
                    result = self._parse_play_page(src, headers)
                    if result and result.get("url") and result.get("url") != src:
                        return result
                h = dict(headers); h["Referer"] = url
                return {"parse": 1, "url": src, "header": h}

        # 新增：查找 video 标签的 src
        for src in re.findall(r'<video[^>]*src="([^"]+)"', html):
            src = self._fix_url(src)
            h = dict(headers); h["Referer"] = url
            return {"parse": 0, "url": src, "header": h}

        # 新增：查找 source 标签的 src
        for src in re.findall(r'<source[^>]*src="([^"]+)"', html):
            src = self._fix_url(src)
            h = dict(headers); h["Referer"] = url
            return {"parse": 0, "url": src, "header": h}

        # 3. 查找直接视频链接
        for ext in ['.m3u8', '.mp4', '.flv', '.ts', '.webm']:
            vids = re.findall(rf'(https?://[^\s"\'>]+{re.escape(ext)}[^\s"\'>]*)', html)
            if vids:
                h = dict(headers); h["Referer"] = url
                return {"parse": 0, "url": vids[0], "header": h}

        # 4. 查找所有可能的 http 链接作为兜底
        all_links = re.findall(r'(https?://[^\s"\'<>]+)', html)
        for link in all_links:
            if self.isVideoFormat(link):
                h = dict(headers); h["Referer"] = url
                return {"parse": 0, "url": link, "header": h}

        return {"parse": 1, "url": url, "header": headers}

    # ============================================================
    # TVBox接口
    # ============================================================

    def _home_extra(self, cards):
        """首页卡片不足40时，从API拉取最新列表补足（原地去重追加）"""
        if len(cards) >= 40:
            return
        d = self._api_post({"type": "1", "class": "", "area": "", "lang": "", "year": "",
                            "version": "", "state": "", "letter": "", "by": "time", "page": "1"})
        if d and str(d.get("code")) == "1":
            items = self._fmt_list(d.get("list", []))
            seen = {c["vod_id"] for c in cards}
            for it in items:
                if it["vod_id"] not in seen:
                    seen.add(it["vod_id"])
                    cards.append(it)

    def homeContent(self, filter=1):
        cards, sections = self._load_homepage()
        self._home_extra(cards)
        return {
            "class": self.categories,
            "filters": self.filters,
            "list": cards[:80],
        }

    def homeVideoContent(self):
        cards, _ = self._load_homepage()
        self._home_extra(cards)
        return {"list": cards[:80]}

    def categoryContent(self, key, *args):
        """
        兼容不同 TVBox 框架的调用约定：
        - 4参数: categoryContent(tid, pg, filter, extend)  — 标准TVBox
        - 5参数: categoryContent(tid, ok, pg, extend, filter) — 部分衍生版（如默影视）
        """
        # 解析参数：根据 args 数量判断调用约定
        if len(args) >= 4:
            # 5参数约定: (tid, ok, pg, extend, filter)
            pg = args[1]
            extend = args[2] if args[2] else ""
        elif len(args) >= 3:
            # 4参数约定: (tid, pg, filter, extend)
            pg = args[0]
            extend = args[2] if args[2] else ""
        elif len(args) >= 2:
            pg = args[0]
            extend = args[1] if isinstance(args[1], str) else ""
        elif len(args) >= 1:
            pg = args[0]
            extend = ""
        else:
            pg = 1
            extend = ""

        page = int(pg) if pg else 1

        # 解析 extend 筛选参数
        ext = {}
        if extend and isinstance(extend, str):
            try:
                ext = json.loads(extend)
            except:
                ext = {}
        elif isinstance(extend, dict):
            ext = extend

        # 构建 MacCMS v10 筛选 URL
        # 格式: /vodshow/{tid}-{class}-{area}-{year}-{lang}-{by}-{page}---.html
        tid = key if key else "1"
        cls = ext.get("class", "")
        area = ext.get("area", "")
        year = ext.get("year", "")
        lang = ext.get("lang", "")
        by = ext.get("by", "time")

        # 翻页优先走 API，失败再退回 HTML
        # 该站 API 参数名为 type/page（非 MacCMS 标准的 t/pg），year 也由 API 直接过滤
        d = self._api_post({
            "type": tid, "class": cls, "area": area, "lang": lang, "year": year,
            "version": "", "state": "", "letter": "", "by": by, "page": str(page),
        })
        if d and str(d.get("code")) == "1":
            items = d.get("list", [])
            return {
                "list": self._fmt_list(items),
                "page": page,
                "pagecount": d.get("pagecount", 1),
                "limit": d.get("limit", 24),
                "total": d.get("total", 0) or len(items),
            }

        # 构造 URL，空参数用 - 占位
        cat_url = f"{self.working_domain}/vodshow/{tid}-{cls}-{area}-{year}-{lang}-{by}-{page}---.html"
        html = self._fetch(cat_url, timeout=10)

        if html and len(html) > 1000:
            cards = self._extract_cards(html)
            # 尝试从页面提取总页数/总数（如果页面有分页信息）
            total = 0
            pagecount = 1
            # 常见分页格式: /vodshow/...-{page}---.html
            page_links = re.findall(r'/vodshow/[^"]+-(\d+)---\.html', html)
            if page_links:
                try:
                    max_page = max(int(p) for p in page_links)
                    pagecount = max_page
                    total = max_page * self._page_size
                except:
                    pass
            if not cards:
                total = 0
                pagecount = 1
            return {
                "list": cards,
                "page": page,
                "pagecount": pagecount,
                "limit": self._page_size,
                "total": total if total else len(cards),
            }

        # HTML 分类页也拿不到时，返回空（与原柯南.py 一致，不再用首页缓存兜底）
        return {"list": [], "page": page, "pagecount": 1, "limit": self._page_size, "total": 0}

    def searchContent(self, key, *args, **kwargs):
        if not key:
            return {"list": []}

        key_lower = key.lower()
        seen = set()
        results = []

        def _append_cards(cards):
            for c in cards:
                if c["vod_id"] not in seen:
                    seen.add(c["vod_id"])
                    results.append(c)

        # 搜索接口现状（实测 2026-02）：
        #  - 标准 MacCMS API（/api.php/provide/vod、/index.php/api/vod）已被模板作者关闭/伪装
        #    （返回 closed / "本模板作者QQ..."），API 搜索不可用；
        #  - 站内唯一可用的是 HTML 搜索页，但对同一 IP 有较高频次限制：
        #    短时间内多次请求会返回“搜索首页骨架”假空页（含搜索表单但无结果）。
        #    因此：HTML 优先、仅发必要请求、失败间隔冷却后重试，并把 API 留作末位兜底。
        # 实测有效的两个搜索 URL（优先级从高到低）：
        #   /index.php/search/{keyword}-------------.html
        #   /search/-------------.html?wd={keyword}
        search_urls = [
            f"{self.working_domain}/index.php/search/{quote(key)}-------------.html",
            f"{self.working_domain}/search/-------------.html?wd={quote(key)}",
        ]

        # 第一轮：两个 URL 各试一次（未限频时首次请求即可成功）
        for search_url in search_urls:
            html = self._fetch(search_url, timeout=12)
            if html and len(html) > 500:
                cards = self._extract_cards(html)
                if cards:
                    _append_cards(cards)
                    return {"list": results[:20]}

        # 第二轮：可能撞上限频（返回假空页），冷却后重试一轮
        time.sleep(3)
        for search_url in search_urls:
            html = self._fetch(search_url, timeout=12)
            if html and len(html) > 500:
                cards = self._extract_cards(html)
                if cards:
                    _append_cards(cards)
                    return {"list": results[:20]}

        # 末位兜底：API 搜索（签名接口多数模板无效，仅 OSS 模板可用，聊胜于无）
        for pg in range(1, 3):
            d = self._api_post({
                "type": "", "class": "", "area": "", "lang": "", "year": "",
                "version": "", "state": "", "letter": "", "by": "time", "page": str(pg),
                "wd": key,
            })
            if not d or str(d.get("code")) != "1":
                break
            items = d.get("list", [])
            if not items:
                break
            for it in items:
                vid = str(it.get("vod_id", ""))
                if not vid or vid in seen:
                    continue
                name = it.get("vod_name", "") or ""
                if key_lower not in name.lower():
                    continue
                seen.add(vid)
                pic = it.get("vod_pic") or it.get("vod_pic_thumb") or ""
                results.append({
                    "vod_id": vid,
                    "vod_name": name,
                    "vod_pic": self._fix_url(pic),
                    "vod_remarks": it.get("vod_remarks", "") or "",
                    "vod_year": it.get("vod_year") or "",
                    "vod_score": it.get("vod_score") or "",
                    "vod_actor": it.get("vod_actor", "") or "",
                })
                if len(results) >= 20:
                    return {"list": results}

        # 末位兜底：首页全量匹配
        if len(results) < 3:
            cards, _ = self._load_homepage()
            _append_cards([c for c in cards if key_lower in c["vod_name"].lower()])

        return {"list": results[:20]}

    def detailContent(self, array):
        if not array:
            return {"list": []}
        vid = array[0]
        info = self._parse_detail(vid)
        info.setdefault("vod_name", "")
        info.setdefault("vod_pic", self.default_pic)
        info.setdefault("vod_remarks", "")
        info.setdefault("vod_year", "")
        info.setdefault("vod_area", "")
        info.setdefault("vod_type", "")
        info.setdefault("vod_actor", "")
        info.setdefault("vod_director", "")
        info.setdefault("vod_content", "")
        info.setdefault("vod_play_from", "")
        info.setdefault("vod_play_url", "")
        return {"list": [info]}

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": self.ua,
            "Referer": f"{self.working_domain}/",
        }
        if self.isVideoFormat(id):
            return {"parse": 0, "url": id, "header": headers}
        if "/vplay/" in id or (id.startswith("/") and ".html" in id):
            return self._parse_play_page(id, headers)
        if "vplay" in id and id.startswith("http"):
            return self._parse_play_page(id, headers)
        decoded = self._decode_play_url(id)
        if decoded and self.isVideoFormat(decoded):
            return {"parse": 0, "url": decoded, "header": headers}
        if id.startswith("http"):
            return {"parse": 1, "url": id, "header": headers}
        return {"parse": 1, "url": f"{self.working_domain}{id}" if id.startswith("/") else id, "header": headers}
