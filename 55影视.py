# coding=utf-8
"""
目标站: 55影视 (www.55ys8.com)
模板: 55影视 苹果CMS V10 stui(kankan) 适配版
站点类型: 影视聚合（电影/电视剧/综艺/动漫/短剧）
核心逻辑:
  1. MacCMS V10 stui 模板, 卡片 class="stui-vodlist__thumb"
  2. 播放页 player_aaaa JSON 的 url 字段即真实 m3u8 (encrypt:0 明文, 已实测可直接请求)
  3. 搜索走 /index.php/ajax/suggest JSON 接口（站内 search.html 已被禁用返回 500）

页面结构（已实测 2026-08-27）：
  - 首页/列表/筛选: <a class="stui-vodlist__thumb lazyload" href="/vod/<id>.html"
                    title="标题" data-original="图片">
                    <span class="pic-text text-right">更新至6集</span>
  - 分类导航:  /list/<tid>.html 电影=1 电视剧=2 综艺=3 动漫=4 短剧=5
  - 分类分页:  /list/<tid>-<page>.html （每页 36 条, 尾页链接含最大页码）
  - 筛选路由:  /show/<tid>-<area>-<by>-<class>----<page>---<year>.html
               12 段制, 实测有效段位: 段2=area 段3=by(time/hits/score)
               段4=class 段9=page 段12=year, 其余段恒为空
               （例: /show/5-大陆----------.html /show/5--hits---------.html
                     /show/1---剧情--------.html /show/5-----------2026.html）
               筛选页分页尾页示例: /show/5-大陆-------174---.html（174 即段9）
  - 搜索:     /index.php/ajax/suggest?mid=1&wd=<关键词>
               返回 {code:1, pagecount:13, limit:20, list:[{id,name,pic,en}]}
               （search.html 已禁用返回 500; suggest 无 remarks 字段）
  - 详情:     /vod/<id>.html
               - 标题:   <h1 class="title">醒来2026 0.0</h1>（尾部为评分需截掉）
               - 封面:   <div class="stui-content__thumb"> 内 img data-original
                         （部分详情页为 "/" 无效值, 需兜底）
               - 备注:   <span class="pic-text text-right">更新至6集</span>
               - 数据行: <p class="data">类型/地区/年份/主演/导演</p>
                         （类型值常为"未知", 地区走<a>标签, 年份纯文本）
               - 线路名: <h3 class="title"><img .../>播放线路 N</h3>
                         与 stui-content__playlist 区块按出现顺序一一对应
               - 选集:   <ul class="stui-content__playlist">
                           <a href="/play/<vid>-<sid>-<ep>.html">01</a>
               - 简介:   "剧情简介"</h3> 后的 <p class="col-pd">正文</p>
  - 播放:     /play/<vid>-<sid>-<ep>.html
               - HTML 内 player_aaaa = {"flag":"play","encrypt":0,
                 "url":"https://vv.jisuzyv.com/play/xxx/index.m3u8",
                 "from":"dplayer","id":"54950","sid":1,"nid":1}
               - url 即明文 m3u8（AES-128 标准 HLS, 播放器原生支持）
"""
import re
import sys
import json
import urllib.parse
import urllib.request

sys.path.append('..')
try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    # 本地测试桩：mock TVBox 框架基类
    class _BaseSpider(object):
        def fetch(self, url, headers=None):
            return None

        def post(self, url, headers=None, data=None):
            return None
    import types
    # 让 isinstance 之类不报错
    sys.modules.setdefault('base', types.ModuleType('base'))
    sys.modules['base'].spider = types.ModuleType('base.spider')
    sys.modules['base'].spider.Spider = _BaseSpider


class Spider(_BaseSpider):

    # 分类 id -> 名称（实测自站点导航）
    CATEGORIES = [
        ("1", "电影"), ("2", "电视剧"), ("3", "综艺"), ("4", "动漫"), ("5", "短剧"),
    ]

    def init(self, extend=""):
        self.site_url = "https://www.55ys8.com"
        self.ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        self.headers = {
            'User-Agent': self.ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.site_url + "/",
        }
        self.default_pic = "https://pic.rmb.bdstatic.com/bjh/user/default.png"
        self.timeout = 15

    # ========== 工具方法 ==========

    def _fix_url(self, url):
        if not url or url.strip() in ("", "/"):
            return ""
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urllib.parse.urljoin(self.site_url, url)
        return url

    def _get(self, url):
        try:
            req = urllib.request.Request(url, headers=self.headers, method='GET')
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        except Exception:
            return ""

    def _strip_tags(self, s):
        if not s:
            return ""
        s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
        s = re.sub(r'<[^>]+>', '', s)
        s = s.replace('&nbsp;', ' ').replace('&amp;', '&')
        s = s.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    # ========== 列表解析 ==========

    def _extract_videos(self, html):
        """首页/分类/筛选页通用：stui-vodlist__thumb 卡片结构"""
        videos = []
        pattern = re.compile(
            r'<a\s+class="stui-vodlist__thumb[^"]*"\s+href="/vod/(\d+)\.html"\s+'
            r'title="([^"]*)"[^>]*data-original="([^"]*)"[^>]*>.*?'
            r'<span class="pic-text[^"]*">([^<]*)</span>',
            re.DOTALL
        )
        seen = set()
        for vid, name, pic, remark in pattern.findall(html):
            if vid in seen:
                continue
            seen.add(vid)
            videos.append({
                "vod_id": vid,
                "vod_name": name.strip() if name.strip() else vid,
                "vod_pic": self._fix_url(pic) or self.default_pic,
                "vod_remarks": remark.strip()
            })
        return videos

    def _extract_pagecount(self, html):
        """从"尾页"锚文本链接提取最大页码（避免误取年份等数字段）"""
        tail = re.findall(r'href="(/(?:list|show)/[^"]+)"[^>]*>\s*尾页', html)
        pagecount = 1
        for link in tail:
            # list 尾页: /list/{tid}-{page}.html
            m = re.search(r'/list/\d+-(\d+)\.html', link)
            if m:
                pagecount = max(pagecount, int(m.group(1)))
                continue
            # show 尾页: /show/{12段}.html -> 段9 为页码
            seg = link[len('/show/'):].replace('.html', '').split('-')
            if len(seg) >= 9 and seg[8].isdigit():
                pagecount = max(pagecount, int(seg[8]))
        return min(pagecount, 9999) if pagecount > 0 else 1

    # ========== 筛选配置 ==========

    def _get_filters(self):
        """MacCMS V10 12 段筛选路由: /show/{tid}-{area}-{by}-{class}----{page}----{year}.html"""
        areas = [
            {"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "日本", "v": "日本"},
            {"n": "韩国", "v": "韩国"}, {"n": "英国", "v": "英国"}, {"n": "法国", "v": "法国"},
            {"n": "泰国", "v": "泰国"},
        ]
        years = [
            {"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"},
        ]
        sorts = [
            {"n": "按时间", "v": "time"}, {"n": "按人气", "v": "hits"}, {"n": "按评分", "v": "score"},
        ]
        movie_genres = [
            {"n": "全部", "v": ""}, {"n": "剧情", "v": "剧情"}, {"n": "喜剧", "v": "喜剧"},
            {"n": "爱情", "v": "爱情"}, {"n": "科幻", "v": "科幻"}, {"n": "动作", "v": "动作"},
            {"n": "悬疑", "v": "悬疑"}, {"n": "恐怖", "v": "恐怖"}, {"n": "犯罪", "v": "犯罪"},
            {"n": "战争", "v": "战争"}, {"n": "动画", "v": "动画"},
        ]
        tv_genres = [
            {"n": "全部", "v": ""}, {"n": "国产剧", "v": "国产"}, {"n": "港台剧", "v": "港台"},
            {"n": "日韩剧", "v": "日韩"}, {"n": "欧美剧", "v": "欧美"},
        ]

        def make(genres):
            return [
                {"key": "class", "name": "类型", "value": genres},
                {"key": "area", "name": "地区", "value": areas},
                {"key": "year", "name": "年份", "value": years},
                {"key": "sort", "name": "排序", "value": sorts},
            ]

        return {
            "1": make(movie_genres),
            "2": make(tv_genres),
            "3": make(movie_genres),
            "4": make(movie_genres),
            "5": make(movie_genres),
        }

    # ========== 首页 ==========

    def homeContent(self, filter):
        categories = [{"type_id": tid, "type_name": name} for tid, name in self.CATEGORIES]
        html = self._get(self.site_url + "/")
        videos = self._extract_videos(html) if html else []
        return {
            "class": categories,
            "list": videos[:36],
            "filters": self._get_filters()
        }

    def homeVideoContent(self):
        html = self._get(self.site_url + "/")
        videos = self._extract_videos(html) if html else []
        return {"list": videos[:36]}

    # ========== 分类 ==========

    def categoryContent(self, tid, pg, filter, extend):
        """
        分类列表:
          无筛选 -> /list/<tid>-<page>.html （每页 36 条）
          有筛选 -> /show/ 12 段路由, 有效段位:
                    段2=area 段3=by 段4=class 段8=page 段12=year
        """
        page = int(pg) if str(pg).isdigit() and int(pg) > 0 else 1
        extend = extend or {}
        genre = extend.get("class", "")
        area = extend.get("area", "")
        year = extend.get("year", "")
        sort = extend.get("sort", "")

        if genre or area or year or sort:
            # 12 段: tid-area-by-class-x-x-x-x-page-x-x-year
            seg = [tid, area, sort, genre, "", "", "", "", str(page), "", "", year]
            path = "/show/" + "-".join(urllib.parse.quote(s) if s else "" for s in seg) + ".html"
            url = self.site_url + path
        else:
            url = f"{self.site_url}/list/{tid}-{page}.html"

        html = self._get(url)
        videos = self._extract_videos(html) if html else []
        pagecount = self._extract_pagecount(html) if html else 1

        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": len(videos) or 36,
            "total": pagecount * 36
        }

    # ========== 搜索 ==========

    def searchContent(self, key, quick, pg="1"):
        """
        搜索走 suggest JSON 接口（站内 search.html 已禁用返回 500）:
          GET /index.php/ajax/suggest?mid=1&wd=<关键词>
          返回 {code, pagecount, limit, list:[{id, name, pic, en}]}
        接口不认 page 参数（实测 page=2 仍返回第一页），单页 20 条
        """
        encoded = urllib.parse.quote(key)
        url = f"{self.site_url}/index.php/ajax/suggest?mid=1&wd={encoded}"
        html = self._get(url)
        videos = []
        pagecount = 1
        if html:
            try:
                data = json.loads(html)
                if data.get("code") == 1:
                    pagecount = int(data.get("pagecount", 1)) or 1
                    for item in data.get("list", []):
                        vid = str(item.get("id", ""))
                        if not vid:
                            continue
                        videos.append({
                            "vod_id": vid,
                            "vod_name": item.get("name", "") or vid,
                            "vod_pic": self._fix_url(item.get("pic", "")) or self.default_pic,
                            "vod_remarks": ""
                        })
            except Exception:
                pass

        return {
            "list": videos,
            "page": 1,
            "pagecount": 1,
            "limit": len(videos) or 20,
            "total": pagecount * 20
        }

    # ========== 详情 ==========

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vid = str(ids[0])
        url = f"{self.site_url}/vod/{vid}.html"
        html = self._get(url)
        if not html:
            return {"list": []}

        # ---- 标题（H1 内 score span 是评分，先剔除再取文本）----
        name = vid
        title_m = re.search(r'<h1[^>]*class="title"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if not title_m:
            title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
        if title_m:
            raw = re.sub(r'<span[^>]*class="[^"]*score[^"]*"[^>]*>.*?</span>', '',
                         title_m.group(1), flags=re.DOTALL)
            name = self._strip_tags(raw) or vid
            # 兜底：纯文本尾巴带评分（如"标题 8.5"）
            name = re.sub(r'\s*(?:10|[0-9])\.\d+\s*$', '', name).strip() or vid

        # ---- 封面（详情页 data-original 可能为无效值 "/"）----
        pic = self.default_pic
        pic_m = re.search(
            r'<div class="stui-content__thumb">.*?<img[^>]*data-original="([^"]+)"',
            html, re.DOTALL
        )
        if pic_m:
            pic = self._fix_url(pic_m.group(1)) or self.default_pic

        # ---- 备注 ----
        remark = ""
        rm = re.search(r'<span class="pic-text[^"]*">([^<]*)</span>', html)
        if rm:
            remark = rm.group(1).strip()

        # ---- 数据行: 类型/地区/年份/主演/导演 ----
        type_name = area = year = director = actor = ""
        for block in re.findall(r'<p class="data"[^>]*>(.*?)</p>', html, re.DOTALL):
            text = self._strip_tags(block)
            if not text:
                continue
            if "地区" in text and not area:
                m = re.search(r'地区[:：]\s*(\S+)', text)
                if m:
                    area = m.group(1)
            elif "年份" in text and not year:
                m = re.search(r'年份[:：]\s*(\d{4})', text)
                if m:
                    year = m.group(1)
            elif "主演" in text and not actor:
                m = re.search(r'主演[:：]\s*(.*)', text)
                if m:
                    actor = re.sub(r'\s+', ' ', m.group(1)).strip(' &;/')
            elif "导演" in text and not director:
                m = re.search(r'导演[:：]\s*(.*)', text)
                if m:
                    director = re.sub(r'\s+', ' ', m.group(1)).strip(' &;/')
            elif "类型" in text and not type_name:
                m = re.search(r'类型[:：]\s*(\S+)', text)
                if m and m.group(1) not in ("未知", ""):
                    type_name = m.group(1)

        # ---- 简介 ----
        content = ""
        syn_m = re.search(
            r'剧情简介</h3>.*?<p class="col-pd">(.*?)</p>', html, re.DOTALL)
        if syn_m:
            content = self._strip_tags(syn_m.group(1))

        # ---- 播放数据 ----
        play_from, play_url = self._parse_play_data(html, vid)
        if not play_url:
            play_from = ["默认线路"]
            play_url = [f"播放${vid}-1-1"]

        result = [{
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": remark,
            "vod_content": content,
            "vod_actor": actor,
            "vod_director": director,
            "vod_year": year,
            "vod_area": area,
            "vod_type": type_name,
            "vod_play_from": '$$$'.join(play_from),
            "vod_play_url": '$$$'.join(play_url)
        }]
        return {"list": result}

    def _parse_play_data(self, html, vid):
        """
        解析详情页播放线路与选集
        结构:
          <h3 class="title"><img .../>播放线路 1</h3>
          ...
          <ul class="stui-content__playlist clearfix">
            <li><a href="/play/<vid>-<sid>-<ep>.html">01</a></li>
        线路 h3 与 playlist 区块按出现顺序一一对应（线路 h3 恒位于列表前 6 个）
        """
        tab_names = re.findall(
            r'<h3 class="title"><img[^>]*/>([^<]+)</h3>', html)
        blocks = re.findall(
            r'<ul class="stui-content__playlist[^"]*">(.*?)</ul>', html, re.DOTALL)

        play_from = []
        play_url = []
        for idx, body in enumerate(blocks):
            items = re.findall(
                r'<a\s+href="/play/(\d+)-(\d+)-(\d+)\.html"[^>]*>([^<]*)</a>', body)
            if not items:
                continue
            ep_list = []
            for _vid, sid, ep, ep_name in items:
                play_id = f"{_vid}-{sid}-{ep}"
                title = ep_name.strip() or f"第{ep}集"
                ep_list.append(f"{title}${play_id}")
            if ep_list:
                line_name = (tab_names[idx].strip()
                             if idx < len(tab_names) and tab_names[idx].strip()
                             else f"线路{idx + 1}")
                play_from.append(line_name)
                play_url.append("#".join(ep_list))
        return play_from, play_url

    # ========== 播放 ==========

    def playerContent(self, flag, id, vipFlags):
        """
        id 形如: <vid>-<sid>-<ep>
        访问 /play/<vid>-<sid>-<ep>.html 提取 player_aaaa.url = 明文 m3u8
        """
        vid, sid, ep = "", "1", "1"
        parts = str(id).replace(".html", "").split("-")
        if parts:
            vid = parts[0]
        if len(parts) > 1 and parts[1]:
            sid = parts[1]
        if len(parts) > 2 and parts[2]:
            ep = parts[2]
        if not vid:
            return {"parse": 1, "url": self.site_url, "header": self.headers}

        play_url = f"{self.site_url}/play/{vid}-{sid}-{ep}.html"
        html = self._get(play_url)
        if not html:
            return {
                "parse": 1,
                "url": play_url,
                "header": self.headers
            }

        m3u8 = self._extract_play_url(html)
        if m3u8:
            return {
                "parse": 0,
                "url": m3u8,
                "header": {"User-Agent": self.ua}
            }

        # 兜底：交给框架解析
        return {
            "parse": 1,
            "url": play_url,
            "header": self.headers
        }

    def _extract_play_url(self, html):
        """从播放页提取 player_aaaa JSON 的 url 字段（encrypt:0 明文 m3u8）"""
        m = re.search(r'player_aaaa\s*=\s*(\{.*?\})\s*[,;]', html, re.DOTALL)
        if not m:
            m = re.search(r'player_aaaa\s*=\s*(\{.*?\})', html, re.DOTALL)
        if not m:
            return ""
        try:
            cfg = json.loads(m.group(1))
        except Exception:
            # 兜底：逐字段提取
            um = re.search(r'"url"\s*:\s*"([^"]+)"', m.group(1))
            return self._fix_url(um.group(1)) if um else ""
        url = cfg.get("url", "")
        if url and url.startswith("http"):
            return url
        # 相对路径拼接
        return self._fix_url(url)

    # ========== 辅助 ==========

    def isVideoFormat(self, url):
        return '.m3u8' in url or '.mp4' in url

    def manualVideoCheck(self):
        return False


# ========== 本地测试入口 ==========
if __name__ == '__main__':
    s = Spider()
    s.init()
    print("===== 首页 =====")
    home = s.homeContent(True)
    print(f"分类数: {len(home.get('class', []))}, 视频数: {len(home.get('list', []))}")
    if home.get('list'):
        sample = home['list'][0]
        print(f"样本: {sample['vod_name']} | {sample['vod_id']} | {sample['vod_remarks']}")

        print("\n===== 详情 =====")
        detail = s.detailContent([sample['vod_id']])
        if detail.get('list'):
            d = detail['list'][0]
            print(f"标题: {d['vod_name']} ({d['vod_year']})")
            print(f"类型: {d['vod_type']} | 地区: {d['vod_area']} | 备注: {d['vod_remarks']}")
            print(f"导演: {d['vod_director']}")
            print(f"主演: {d['vod_actor'][:60]}")
            print(f"线路: {d['vod_play_from']}")
            print(f"选集: {d['vod_play_url'][:100]}")

            print("\n===== 播放 =====")
            first_play = d['vod_play_url'].split('$$$')[0].split('#')[0]
            if '$' in first_play:
                play_id = first_play.split('$')[-1]
                result = s.playerContent("", play_id, [])
                print(f"parse={result.get('parse')}, url={result.get('url', '')[:80]}")

    print("\n===== 分类（短剧第1页）=====")
    cat = s.categoryContent("5", "1", True, {})
    print(f"视频数: {len(cat.get('list', []))}, 总页数: {cat.get('pagecount')}")

    print("\n===== 筛选（短剧+大陆地区）=====")
    cat2 = s.categoryContent("5", "1", True, {"area": "大陆"})
    print(f"视频数: {len(cat2.get('list', []))}, 总页数: {cat2.get('pagecount')}")

    print("\n===== 筛选（电影+剧情+人气）=====")
    cat3 = s.categoryContent("1", "1", True, {"class": "剧情", "sort": "hits"})
    print(f"视频数: {len(cat3.get('list', []))}, 总页数: {cat3.get('pagecount')}")

    print("\n===== 分类分页（短剧第2页）=====")
    cat4 = s.categoryContent("5", "2", True, {})
    print(f"视频数: {len(cat4.get('list', []))}")

    print("\n===== 搜索（重生）=====")
    search = s.searchContent("重生", "")
    print(f"结果数: {len(search.get('list', []))}")
    for v in search.get('list', [])[:3]:
        print(f"  {v['vod_name']} | {v['vod_id']}")
