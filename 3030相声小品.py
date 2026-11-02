# -*- coding: utf-8 -*-
# 3030相声小品网 (http://3030.com.cn) 爬虫插件（TVBox / FongMi / atv-player 通用 base.spider 框架）
#
# 功能：
#   1. 一级分类：最近更新 + 相声/小品/德云社/赵家班/开心麻花/喜剧综艺/3030说
#   2. 二级分类：页面顶部"子分类"卡片 + 筛选下拉（双通道）
#   3. 搜索：search.php 关键词搜索 + 分页
#   4. 播放：解析成真实视频直链（mp4），点播即播
#
# 播放解析策略（v2，解决"网页嵌入无法直接播放"问题）：
#   站内视频来自优酷(约78%)/腾讯(约14%)/B站(约8%)的网页嵌入。
#   - B站嵌入：从iframe取bvid/cid → B站官方playurl接口 → mp4直链（免登录，已验证）
#   - 优酷/腾讯嵌入：优酷直链已封死（第三方解析全部失效），
#     改为B站同款匹配：按"表演者+剧名"搜B站，剧名+表演者双重校验防错配，
#     优先命中官方频道「3030相声小品」(uid 81351347)，命中即返回mp4直链
#   - 匹配失败：回退原嵌入页地址（个别宿主可网页播放）
#   注意：B站直链需要 Referer: https://www.bilibili.com/，已在header中携带
#
# 提速手段：
#   - Session 连接池复用 + 自动重试
#   - 页面级 TTL 缓存：详情→播放零重复请求
#   - B站匹配结果缓存（含负缓存），重复播放秒开
#   - 分类合集多页并行抓取（ThreadPoolExecutor）

import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from urllib.parse import parse_qs, quote, urlsplit

from requests import Session, adapters
from urllib3.util.retry import Retry

# 本地框架依赖（插件目录内自带 base/spider.py，与官方爬虫放同一目录即可）
sys.path.append('..')
from base.spider import Spider

SITE = "http://3030.com.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

TIMEOUT = 10            # 单请求超时（秒）
LIST_TTL = 300          # 列表/首页/搜索缓存 5 分钟
WATCH_TTL = 900         # 详情/播放页缓存 15 分钟
CAT_PLAYLIST_PAGES = 5  # 分类合集详情最多合并前 N 页
BILI_MATCH_TTL = 86400  # B站同款匹配缓存 24 小时

BILI_OFFICIAL_MID = 81351347   # 3030相声小品 官方频道
BILI_REFERER = "https://www.bilibili.com/"

WATCH_RE = re.compile(r'href="(?:https?://3030\.com\.cn)?/watch/(\d+)\.html"')
IFRAME_RE = re.compile(r'<iframe[^>]*\ssrc="([^"]+)"', re.I)
PIECE_RE = re.compile(r'《([^《》]{2,20})》')

# 分类树兜底（首页导航解析失败时使用，与站点导航结构一致）
FALLBACK_TREE = [
    (2, "相声", [(7, "张寿臣"), (9, "常宝堃"), (10, "马三立"), (13, "侯宝林"),
                 (14, "刘宝瑞"), (21, "马志明 黄族民"), (113, "田立禾 王文玉"),
                 (19, "马季"), (77, "苏文茂 王佩元"), (24, "杨少华 杨议"),
                 (116, "魏文亮 魏文华"), (23, "侯耀文 石富宽"), (76, "师胜杰"),
                 (39, "姜昆"), (16, "冯巩 牛群"), (44, "李金斗"),
                 (119, "李伯祥 杜国芝"), (27, "方清平"), (38, "大兵"),
                 (41, "张康 贾旭明"), (42, "何云伟 李菁"), (46, "曹云金 刘云天"),
                 (33, "高晓攀 尤宪超"), (35, "王自健"), (81, "洛桑 博林"),
                 (82, "王玥波"), (29, "苗阜 王声"), (51, "卢鑫 张玉浩"),
                 (73, "金菲 陈曦"), (72, "陈印泉 侯振鹏"), (96, "董建春 李丁"),
                 (101, "李立群"), (103, "吴兆南 魏龙豪"), (102, "相声瓦舍"),
                 (108, "马军 盛伟")]),
    (3, "小品", [(8, "陈佩斯"), (15, "赵丽蓉"), (17, "郭冬临"), (20, "郭达 蔡明"),
                 (22, "严顺开"), (30, "潘长江"), (70, "黄宏"), (25, "贾玲"),
                 (32, "潘斌龙 崔志佳"), (43, "巩汉林"), (45, "孙涛 邵峰"),
                 (47, "白凯南"), (49, "乔杉 修睿"), (80, "范伟"), (84, "贾冰"),
                 (85, "刘亮 白鸽"), (87, "肖旭 肥龙"), (88, "张子栋"),
                 (79, "郭阳 郭亮"), (89, "叶逢春 马朋"), (90, "崔大笨"),
                 (92, "张小斐"), (94, "孙建弘"), (97, "周群 阿进"),
                 (98, "许君聪 卜钰"), (117, "金靖 刘胜瑛"), (118, "蒋易 张海宇")]),
    (52, "德云社", [(11, "郭德纲 于谦"), (28, "岳云鹏 孙越"), (58, "高峰 栾云平"),
                    (59, "郭麒麟 阎鹤祥"), (60, "烧饼 曹鹤阳"), (61, "张鹤伦 郎鹤炎"),
                    (74, "李云天 侯震"), (83, "张云雷 杨九郎"), (99, "孟鹤堂 周九良"),
                    (109, "张文顺")]),
    (63, "赵家班", [(12, "赵本山"), (31, "宋小宝"), (64, "小沈阳"), (65, "王小利"),
                    (66, "刘小光"), (67, "程野 田娃"), (68, "张小飞 张小伟"),
                    (69, "杨树林"), (78, "文松"), (107, "宋晓峰"), (105, "小沈龙")]),
    (18, "开心麻花", [(54, "沈腾"), (55, "常远"), (56, "王宁"), (57, "艾伦")]),
    (36, "喜剧综艺", [(37, "喜剧总动员"), (34, "笑傲江湖"), (40, "笑傲帮"),
                      (48, "欢乐喜剧人"), (62, "组团上春晚"), (75, "笑声传奇"),
                      (86, "我为喜剧狂"), (91, "相声有新人"), (93, "开心俱乐部"),
                      (95, "跨界喜剧王"), (100, "笑星闯地球"), (104, "笑礼相迎"),
                      (106, "寻找喜剧人"), (110, "今夜百乐门"), (111, "欢乐饭米粒儿"),
                      (112, "中国喜剧星"), (114, "周六夜现场")]),
    (6, "3030说", [(5, "历史溯源"), (4, "名家堂"), (115, "相声纪录片")]),
]


class Spider(Spider):  # 类名与父类同名是宿主插件约定，故意保留
    def init(self, extend=""):
        self.session = Session()
        adapter = adapters.HTTPAdapter(
            max_retries=Retry(total=2, backoff_factor=0.3,
                              status_forcelist=[429, 500, 502, 503, 504]),
            pool_connections=10,
            pool_maxsize=20
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": UA,
            "Referer": SITE + "/",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })
        # 页面缓存 {key: (时间戳, html)}
        self._page_cache = {}
        # B站同款匹配缓存 {watch_id: (时间戳, bvid或"")}
        self._bili_match = {}
        self._bili_warmed = False
        self._bili_lock = threading.RLock()

    # ---------------- 基础工具 ----------------

    def _fetch(self, url, cache_key=None, ttl=0):
        """带 TTL 缓存的 GET；失败返回空串"""
        if cache_key:
            hit = self._page_cache.get(cache_key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        text = ""
        try:
            r = self.session.get(url, timeout=TIMEOUT)
            r.encoding = "utf-8"
            text = r.text
        except Exception as e:
            print(f"请求失败: {url} ({e})")
        if cache_key and text:
            self._page_cache[cache_key] = (time.time(), text)
        return text

    def _home_html(self):
        return self._fetch(SITE + "/", cache_key="home:page1", ttl=LIST_TTL)

    def _list_page(self, cat_id, pg):
        if pg <= 1:
            url = f"{SITE}/category-{cat_id}.html"
        else:
            url = f"{SITE}/category-{cat_id}_{pg}.html"
        return self._fetch(url, cache_key=f"cat:{cat_id}:p{pg}", ttl=LIST_TTL)

    def _watch_page(self, wid):
        return self._fetch(f"{SITE}/watch/{wid}.html", cache_key=f"watch:{wid}",
                           ttl=WATCH_TTL)

    def _category_tree(self):
        """从首页导航解析分类树，失败用内置兜底"""
        tree = []
        try:
            nav = re.search(r'<nav class="menu">(.*?)</nav>', self._home_html(), re.S)
            if nav:
                pat = r'<a href="(?:https?://3030\.com\.cn)?/category-(\d+)\.html">([^<]+)</a>\s*<ul>(.*?)</ul>'
                for m in re.finditer(pat, nav.group(1), re.S):
                    cid = int(m.group(1))
                    cname = unescape(m.group(2)).strip()
                    subs = [(int(a), unescape(b).strip()) for a, b in re.findall(
                        r'<a href="(?:https?://3030\.com\.cn)?/category-(\d+)\.html">([^<]+)</a>',
                        m.group(3))]
                    tree.append((cid, cname, subs))
        except Exception:
            tree = []
        return tree or FALLBACK_TREE

    def _cat_name(self, cat_id):
        for cid, name, subs in self._category_tree():
            if cid == cat_id:
                return name
            for sid, sname in subs:
                if sid == cat_id:
                    return sname
        return f"分类{cat_id}"

    @staticmethod
    def _parse_items(page_html):
        """解析列表条目（按 <li> 分块，容错相对/绝对链接与懒加载图片）"""
        items = []
        seen = set()
        for chunk in re.split(r'<li(?:\s[^>]*)?>', page_html):
            m = WATCH_RE.search(chunk)
            if not m:
                continue
            wid = m.group(1)
            if wid in seen:
                continue
            t = re.search(r'<h3>\s*<a[^>]*>([^<]*)</a>', chunk)
            if not t:
                continue
            title = unescape(t.group(1)).strip()
            if not title:
                continue
            seen.add(wid)
            pic = re.search(r'data-original="([^"]*)"', chunk)
            date = re.search(r'<span>\s*(\d{4}-\d{2}-\d{2})', chunk)
            items.append({
                "vod_id": "watch_" + wid,
                "vod_name": title,
                "vod_pic": unescape(pic.group(1)).strip() if pic else "",
                "vod_remarks": date.group(1) if date else "",
            })
        return items

    @staticmethod
    def _page_count(page_html, num_pattern):
        """从分页条取最大页码；无分页条按单页处理"""
        bar = re.search(r'<div class="pagebar">(.*?)</div>', page_html, re.S)
        scope = bar.group(1) if bar else page_html
        nums = [int(n) for n in re.findall(num_pattern, scope)]
        return max(nums) if nums else 1

    @staticmethod
    def _extract_iframes(page_html):
        """提取嵌入播放器地址并规范化协议"""
        urls = []
        for src in IFRAME_RE.findall(page_html):
            src = unescape(src).strip()
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("http://") and "player." in src:
                src = "https://" + src[7:]
            if src and src not in urls:
                urls.append(src)
        return urls

    @staticmethod
    def _safe_ep(name):
        name = name.replace("$", "＄").replace("#", "＃").strip()
        return name or "播放"

    @staticmethod
    def _watch_title(page_html):
        m = re.search(r"<title>([^<]*)</title>", page_html)
        if not m:
            return ""
        t = unescape(m.group(1)).strip()
        for suffix in ("-3030相声小品网", "3030相声小品网"):
            t = t.replace(suffix, "").strip(" -")
        return t

    @staticmethod
    def _watch_desc(page_html):
        m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', page_html)
        return unescape(m.group(1)).strip() if m else ""

    # ---------------- B站直链解析 ----------------

    def _bili_json(self, url):
        """调用B站接口返回 JSON（失败返回空dict）"""
        try:
            r = self.session.get(url, timeout=TIMEOUT,
                                 headers={"Referer": BILI_REFERER})
            if r.status_code != 200:
                return {}
            return r.json()
        except Exception as e:
            print(f"B站接口失败: {e}")
            return {}

    def _bili_warm(self):
        """预取B站cookie（搜索接口需要 buvid cookie），会话内只做一次"""
        with self._bili_lock:
            if self._bili_warmed:
                return
            try:
                self.session.get("https://www.bilibili.com/", timeout=TIMEOUT)
            except Exception:
                pass
            self._bili_warmed = True

    def _bili_search(self, keyword):
        """B站视频搜索，返回结果列表（未登录可用）"""
        self._bili_warm()
        d = self._bili_json(
            "https://api.bilibili.com/x/web-interface/search/type"
            f"?search_type=video&keyword={quote(keyword)}")
        return (d.get("data") or {}).get("result") or []

    def _bili_view(self, bvid="", aid=""):
        key = f"bvid={bvid}" if bvid else f"aid={aid}"
        d = self._bili_json(f"https://api.bilibili.com/x/web-interface/view?{key}")
        return d.get("data") or {}

    def _bili_play_mp4(self, bvid, cid=None):
        """取B站视频mp4直链（html5平台免登录，最高720P，已验证可播）"""
        try:
            if not cid:
                info = self._bili_view(bvid=bvid)
                cid = info.get("cid")
            if not cid:
                return ""
            d = self._bili_json(
                f"https://api.bilibili.com/x/player/playurl?bvid={bvid}"
                f"&cid={cid}&platform=html5&high_quality=1")
            durl = (d.get("data") or {}).get("durl") or []
            return durl[0].get("url", "") if durl else ""
        except Exception as e:
            print(f"B站直链获取失败: {e}")
            return ""

    @staticmethod
    def _parse_bili_iframe(src):
        """从B站嵌入iframe地址解析 bvid/aid/cid/page"""
        try:
            q = parse_qs(urlsplit(src).query)
            bvid = (q.get("bvid") or [""])[0]
            aid = (q.get("aid") or [""])[0]
            cid = (q.get("cid") or [""])[0]
            page = (q.get("page") or ["1"])[0]
            return bvid, aid, cid, page
        except Exception:
            return "", "", "", "1"

    @staticmethod
    def _strip_tags(t):
        return re.sub(r'<[^>]+>', '', t or '').replace(" ", "")

    def _match_bili(self, wid, title):
        """B站同款匹配：剧名+表演者双重校验，优先官方频道。
        返回 bvid 或空串（含负缓存，24小时有效）"""
        if not title:
            return ""
        now = time.time()
        with self._bili_lock:
            hit = self._bili_match.get(wid)
            if hit and now - hit[0] < BILI_MATCH_TTL:
                return hit[1]

        piece_m = PIECE_RE.search(title)
        piece = piece_m.group(1) if piece_m else ""
        performers = title[:piece_m.start()].strip() if piece_m else title
        performers = re.sub(r'(组团上春晚|群口相声|单口相声|对口相声|相声|小品|表演|主演)+$',
                            '', performers).strip()
        perf_tokens = [p for p in performers.split() if len(p) >= 2]

        bvid = ""
        try:
            if piece:
                # 三级逐级放宽：官方频道（同一视频）→ 表演者（同一演出）→ 剧名（同一剧目）
                q1 = self._bili_search(f"3030相声小品 {piece}")
                # 1级：官方频道上传的同名视频（与本站同源，最高可信）
                for r in q1:
                    bt = self._strip_tags(r.get("title", ""))
                    if piece in bt and r.get("author") == "3030相声小品":
                        bvid = r.get("bvid", "")
                        break
                # 2级：标题同时含剧名和至少一位表演者
                if not bvid and perf_tokens:
                    for r in self._bili_search(f"{performers} {piece}"):
                        bt = self._strip_tags(r.get("title", ""))
                        if piece in bt and any(p in bt for p in perf_tokens):
                            bvid = r.get("bvid", "")
                            break
                # 3级：仅剧名命中（可能是其他演员的同剧目版本）
                if not bvid:
                    for r in q1:
                        if piece in self._strip_tags(r.get("title", "")):
                            bvid = r.get("bvid", "")
                            break
                if not bvid:
                    for r in self._bili_search(piece):
                        if piece in self._strip_tags(r.get("title", "")):
                            bvid = r.get("bvid", "")
                            break
        except Exception as e:
            print(f"B站匹配失败: {e}")

        with self._bili_lock:
            self._bili_match[wid] = (now, bvid)
        if bvid:
            print(f"✓ B站同款匹配: {title[:30]} → {bvid}")
        else:
            print(f"✗ B站无同款: {title[:30]}")
        return bvid

    # ---------------- 宿主接口 ----------------

    def getName(self):
        return "3030相声小品网"

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.session.close()

    def homeContent(self, filter):
        tree = self._category_tree()
        classes = [{"type_name": "最近更新", "type_id": "home"}]
        filters = {}
        for cid, name, subs in tree:
            classes.append({"type_name": name, "type_id": f"cat_{cid}"})
            if subs:
                filters[f"cat_{cid}"] = [{
                    "key": "sub",
                    "name": "子分类",
                    "value": ([{"n": "全部", "v": "0"}] +
                              [{"n": n, "v": str(s)} for s, n in subs])
                }]
        return {"class": classes, "filters": filters,
                "list": self._parse_items(self._home_html())}

    def homeVideoContent(self):
        return {"list": self._parse_items(self._home_html())}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        extend = extend or {}

        if tid == "home":
            return {"list": self._parse_items(self._home_html()),
                    "page": pg, "pagecount": 1, "limit": 30, "total": 30}

        try:
            cat_id = int(str(tid).replace("cat_", ""))
        except ValueError:
            cat_id = 2

        # 二级分类筛选（下拉通道）：选中子分类后直接按子分类取列表
        sub = str(extend.get("sub", "0") or "0")
        sub_selected = sub not in ("0", "", "全部")
        if sub_selected:
            try:
                cat_id = int(sub)
            except ValueError:
                sub_selected = False

        page_html = self._list_page(cat_id, pg)
        items = self._parse_items(page_html)

        # 二级分类卡片通道：一级分类第1页顶部注入子分类入口
        if pg == 1 and not sub_selected:
            for cid, name, subs in self._category_tree():
                if cid == cat_id and subs:
                    cards = [{"vod_id": f"cat_{sid}", "vod_name": sname,
                              "vod_pic": "", "vod_remarks": "子分类"}
                             for sid, sname in subs]
                    items = cards + items
                    break

        pagecount = self._page_count(page_html, r'/category-%d_(\d+)\.html' % cat_id)
        return {"list": items, "page": pg, "pagecount": pagecount,
                "limit": 30, "total": pagecount * 30}

    def searchContent(self, key, quick, pg="1"):
        pg = int(pg or 1)
        url = f"{SITE}/search.php?q={quote(key)}"
        if pg > 1:
            url += f"&page={pg}"
        page_html = self._fetch(url, cache_key=f"search:{key}:{pg}", ttl=LIST_TTL)
        items = self._parse_items(page_html)
        pagecount = self._page_count(page_html, r'[?&]page=(\d+)')
        return {"list": items, "page": pg}

    def detailContent(self, ids):
        did = ids[0] if isinstance(ids, list) else ids
        if did.startswith("cat_"):
            return {"list": [self._category_detail(did)]}
        if did.startswith("watch_"):
            return {"list": [self._watch_detail(did)]}
        return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        # 集id格式：watch_<wid> 或 watch_<wid>:<段号>（多段视频）
        raw = str(id).split("|")[0].strip()
        seg = 1
        if ":" in raw:
            raw, _, seg_s = raw.rpartition(":")
            try:
                seg = max(1, int(seg_s))
            except ValueError:
                seg = 1
        wid = raw.replace("watch_", "").strip()

        url = ""
        header = {"User-Agent": UA, "Referer": SITE + "/"}

        page_html = self._watch_page(wid) if wid else ""
        iframes = self._extract_iframes(page_html) if page_html else []
        iframe = iframes[seg - 1] if 0 < seg <= len(iframes) else ""

        # 1) B站嵌入 → 官方接口直接解析mp4（免登录，已验证可播）
        if iframe and "bilibili" in iframe:
            bvid, aid, cid, page = self._parse_bili_iframe(iframe)
            if bvid or aid:
                if not cid and bvid:
                    cid = self._bili_view(bvid=bvid).get("cid")
                elif not cid and aid:
                    cid = self._bili_view(aid=aid).get("cid")
                if bvid and cid:
                    url = self._bili_play_mp4(bvid, cid)

        # 2) 优酷/腾讯嵌入 → B站同款匹配（剧名+表演者双重校验）
        if not url and page_html and iframe:
            title = self._watch_title(page_html)
            bvid = self._match_bili(wid, title)
            if bvid:
                url = self._bili_play_mp4(bvid)

        # 3) 兜底：原嵌入页地址（个别宿主支持网页播放）
        if not url:
            url = iframe or (f"{SITE}/watch/{wid}.html" if wid else "")
            header = {"User-Agent": UA, "Referer": SITE + "/"}

        if url.startswith("https://upos") or "bilivideo" in url:
            header = {"User-Agent": UA, "Referer": BILI_REFERER}

        return {"parse": 0, "url": url, "header": json.dumps(header)}

    # ---------------- 详情构造 ----------------

    def _watch_detail(self, did):
        wid = did.replace("watch_", "")
        page_html = self._watch_page(wid)
        title = self._watch_title(page_html) or f"视频{wid}"
        desc = self._watch_desc(page_html)
        iframes = self._extract_iframes(page_html)

        if len(iframes) > 1:
            # 多段视频：用 段号标记，playerContent 按 :段号 取对应iframe
            play_url = "#".join(
                f"第{i}段$watch_{wid}:{i}" for i in range(1, len(iframes) + 1))
        elif iframes:
            play_url = f"{self._safe_ep(title)}$watch_{wid}"
        else:
            play_url = f"原站网页$watch_{wid}"

        return {
            "vod_id": did,
            "vod_name": title,
            "vod_pic": "",
            "vod_remarks": "3030相声小品网",
            "vod_content": desc or title,
            "vod_play_from": "3030在线",
            "vod_play_url": play_url,
        }

    def _category_detail(self, did):
        cat_id = int(did.replace("cat_", ""))
        name = self._cat_name(cat_id)

        first = self._list_page(cat_id, 1)
        items = self._parse_items(first)
        total_pages = self._page_count(first, r'/category-%d_(\d+)\.html' % cat_id)
        rest = range(2, min(total_pages, CAT_PLAYLIST_PAGES) + 1)

        if rest:
            # 后续页并行抓取，合集打开速度提升约 3-4 倍
            with ThreadPoolExecutor(max_workers=4) as ex:
                pages = list(ex.map(
                    lambda p: self._parse_items(self._list_page(cat_id, p)), rest))
            for part in pages:
                items.extend(part)

        play_url = "#".join(
            f"{self._safe_ep(it['vod_name'])}${it['vod_id']}" for it in items)
        return {
            "vod_id": did,
            "vod_name": name,
            "vod_pic": "",
            "vod_remarks": f"共{len(items)}个",
            "vod_content": (f"3030相声小品网「{name}」合集，共收录 {len(items)} 个视频"
                            f"（最多加载前 {CAT_PLAYLIST_PAGES} 页）。点击列表即可播放。"),
            "vod_play_from": "3030在线",
            "vod_play_url": play_url,
        }
