# -*- coding: utf-8 -*-
# V视影院 - by AI
import json
import re
import sys
import threading
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import quote, unquote
sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    """
    配置示例：
    {
        "key": "vsiol",
        "name": "V视影院",
        "type": 3,
        "api": ".所在路径/vsiol.py",
        "searchable": 1,
        "quickSearch": 1,
        "filterable": 1,
        "changeable": 1,
        "ext": {
            "site": "https://www.vsiol.com"
        }
    }
    """

    # ===== 预编译正则，类级别只编译一次 =====
    RE_VID = re.compile(r'href="/info/(\d+)"')
    RE_TITLE = re.compile(r'title="([^"]*)"')
    RE_PIC = re.compile(r'data-src="([^"]*)"')
    RE_REMARK = re.compile(r'public-list-prb[^>]*>\s*([^<]*)')
    RE_PLAYER = re.compile(r'var player_aaaa=(\{.*?\})</script>', re.S)
    RE_PLAY_LINK = re.compile(r'href="/play/(\d+-\d+-\d+)"[^>]*>([^<]*)')
    RE_PLAY_TAB = re.compile(r'class="swiper-slide"[^>]*>(?:<i[^>]*></i>)?&nbsp;([^<]*)')
    RE_PAGE_COUNT = re.compile(r'href="/show/[^"]*/page/(\d+)"[^>]*title="尾页"')
    RE_JSONLD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
    # 一次性匹配视频卡片的 vid+title，兼容各页面布局
    RE_LIST_CARD = re.compile(
        r'class="public-list-exp"[^>]*href="/info/(\d+)"[^>]*>.*?'
        r'data-src="([^"]*)".*?'
        r'public-list-prb[^>]*>\s*([^<]*)',
        re.S
    )
    RE_CARD_TITLE = re.compile(r'title="([^"]*)"')
    RE_YEAR = re.compile(r'href="/search/year/(\d+)"')
    RE_AREA = re.compile(r'href="/search/area/([^"]*)"')
    RE_CLASS = re.compile(r'href="/show/\d+/class/([^"]*)"')
    RE_REMARK_DT = re.compile(r'<strong[^>]*>备注\s*:</strong>([^<]*)')
    RE_TAB_BLOCK = re.compile(
        r'<div class="anthology-list-box[^"]*">(.*?)</div>\s*</div>', re.S
    )

    HOST = "https://www.vsiol.com"
    UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.61 Safari/537.36'

    # 类级别缓存
    _filter_cache = None
    _class_cache = None

    def init(self, extend=""):
        self.host = self.HOST
        if extend:
            try:
                ext = json.loads(extend)
                if 'site' in ext:
                    hosts = ext['site'].split(',')
                    self.host = self.host_late(hosts)
            except Exception:
                pass
        self.headers = {
            'User-Agent': self.UA,
            'Referer': f'{self.host}/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate',  # 启用压缩，减少传输量
            'Connection': 'keep-alive',
        }
        # 高性能连接池：大连接池 + 自动重试 + 长连接复用
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        adapter = HTTPAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=Retry(total=2, backoff_factor=0.3,
                              status_forcelist=[500, 502, 503, 504]),
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

    def getName(self):
        return "V视影院"

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    # ======================== 首页 ========================

    def homeContent(self, filter):
        # 缓存分类和筛选器，避免每次重建
        if self._class_cache is None:
            self._class_cache = [
                {'type_name': '电影', 'type_id': 'dianying'},
                {'type_name': '电视剧', 'type_id': 'dianshiju'},
                {'type_name': '综艺', 'type_id': 'zongyi'},
                {'type_name': '动漫', 'type_id': 'dongman'},
                {'type_name': '短剧', 'type_id': 'duanju'},
            ]
        if self._filter_cache is None:
            self._filter_cache = self._build_filters()
        return {'class': self._class_cache, 'filters': self._filter_cache}

    def homeVideoContent(self):
        html = self._fetch_html(f"{self.host}/")
        vods = self._parse_list(html)
        return {'list': vods}

    # ======================== 分类列表 ========================

    def categoryContent(self, tid, pg, filter, extend):
        extend = extend or {}
        page = pg if pg else '1'

        cate = extend.get('cate', '')
        base = cate if cate else tid

        parts = [self.host, 'show', base]
        area = extend.get('area', '')
        year = extend.get('year', '')
        lang = extend.get('lang', '')
        by = extend.get('by', '')

        if area:
            parts.extend(['area', area])
        if year:
            parts.extend(['year', year])
        if lang:
            parts.extend(['lang', lang])
        if by:
            parts.extend(['by', by])
        parts.extend(['page', str(page)])

        url = '/'.join(parts)
        html = self._fetch_html(url)
        vods = self._parse_list(html)

        pagecount = 1
        m = self.RE_PAGE_COUNT.search(html)
        if m:
            pagecount = int(m.group(1))

        return {
            'list': vods,
            'page': int(page),
            'pagecount': pagecount,
            'limit': 30,
            'total': pagecount * 30,
        }

    # ======================== 详情页 ========================

    def detailContent(self, ids):
        vid = ids[0]
        html = self._fetch_html(f"{self.host}/info/{vid}")
        vod = self._parse_detail(html, vid)
        return {'list': [vod]}

    # ======================== 搜索 ========================

    def searchContent(self, key, quick, pg="1"):
        page = pg if pg else '1'
        kw = quote(key)
        if page == '1':
            url = f"{self.host}/search?wd={kw}"
        else:
            url = f"{self.host}/search/page/{page}/wd/{kw}"

        html = self._fetch_html(url)
        vods = self._parse_list(html)

        # quick 模式只返回前 10 条，加速快速搜索
        if quick and len(vods) > 10:
            vods = vods[:10]

        return {'list': vods, 'page': int(page)}

    # ======================== 播放 ========================

    def playerContent(self, flag, id, vipFlags):
        play_url = f"{self.host}/play/{id}"
        html = self._fetch_html(play_url)

        header = {
            'User-Agent': self.UA,
            'Referer': f'{self.host}/',
            'Origin': self.host,
        }
        m = self.RE_PLAYER.search(html)
        if m:
            try:
                data = json.loads(m.group(1))
                url = data.get('url', '')
                encrypt = data.get('encrypt', 0)
                if encrypt == 0:
                    return {'parse': 0, 'url': url, 'header': header}
                elif encrypt == 1:
                    import base64
                    url = base64.b64decode(url).decode('utf-8')
                    return {'parse': 0, 'url': url, 'header': header}
                elif encrypt == 2:
                    try:
                        from Crypto.Cipher import AES
                        from Crypto.Util.Padding import unpad
                        key = b'VlxTdpG0p5jPr+VAV7f5gw=='
                        cipher = AES.new(key, AES.MODE_ECB)
                        url = unpad(cipher.decrypt(base64.b64decode(url)), 16).decode('utf-8')
                        return {'parse': 0, 'url': url, 'header': header}
                    except Exception:
                        pass
            except Exception:
                pass

        # 兜底嗅探
        return {'parse': 1, 'url': play_url, 'header': header}

    def localProxy(self, param):
        pass

    # ======================== 工具方法 ========================

    def _fetch_html(self, url):
        """高性能 HTML 抓取：连接池 + gzip + 跳过慢编码检测"""
        try:
            resp = self.session.get(url, timeout=8, allow_redirects=True)
            # 直接用 utf-8，跳过 apparent_encoding 的 chardet 检测（慢）
            resp.encoding = 'utf-8'
            return resp.text
        except Exception:
            try:
                resp = requests.get(url, headers=self.headers,
                                   timeout=8, allow_redirects=True)
                resp.encoding = 'utf-8'
                return resp.text
            except Exception:
                return ''

    def _parse_list(self, html):
        """一次正则扫描提取 vid+pic+remark，再从卡片块取 title，兼容各页面"""
        vods = []
        cards = self.RE_LIST_CARD.findall(html)
        if cards:
            # 找到视频卡片区域后，按卡片块提取 title
            blocks = html.split('public-list-box')
            title_map = {}
            for block in blocks:
                mid = self.RE_VID.search(block)
                if mid:
                    tm = self.RE_CARD_TITLE.search(block)
                    if tm:
                        title_map[mid.group(1)] = tm.group(1)
            for vid, pic, remark in cards:
                vods.append({
                    'vod_id': vid,
                    'vod_name': title_map.get(vid, ''),
                    'vod_pic': pic,
                    'vod_remarks': remark.strip(),
                })
            return vods
        # 兜底：逐块 split
        for block in html.split('public-list-box'):
            if 'href="/info/' not in block:
                continue
            mid = self.RE_VID.search(block)
            if not mid:
                continue
            tm = self.RE_TITLE.search(block)
            pm = self.RE_PIC.search(block)
            rm = self.RE_REMARK.search(block)
            vods.append({
                'vod_id': mid.group(1),
                'vod_name': tm.group(1) if tm else '',
                'vod_pic': pm.group(1) if pm else '',
                'vod_remarks': rm.group(1).strip() if rm else '',
            })
        return vods

    def _parse_detail(self, html, vid):
        """解析详情页"""
        vod = {'vod_id': vid}

        # JSON-LD 结构化数据
        jld = self.RE_JSONLD.search(html)
        if jld:
            try:
                data = json.loads(jld.group(1).strip())
                graph = data.get('@graph', [])
                if graph:
                    movie = graph[0]
                    vod['vod_name'] = movie.get('name', '')
                    vod['vod_pic'] = movie.get('image', '')
                    vod['vod_content'] = movie.get('description', '')
                    director = movie.get('director', {})
                    if isinstance(director, dict):
                        vod['vod_director'] = director.get('name', '')
                    else:
                        vod['vod_director'] = ''
                    actors = movie.get('actor', [])
                    if isinstance(actors, list):
                        vod['vod_actor'] = ','.join(a.get('name', '') for a in actors)
                    elif isinstance(actors, dict):
                        vod['vod_actor'] = actors.get('name', '')
            except Exception:
                pass

        # HTML 元数据补充
        ym = self.RE_YEAR.search(html)
        if ym:
            vod['vod_year'] = ym.group(1)
        am = self.RE_AREA.search(html)
        if am:
            vod['vod_area'] = unquote(am.group(1))
        cm = self.RE_CLASS.search(html)
        if cm:
            vod['vod_class'] = unquote(cm.group(1))
        rm = self.RE_REMARK_DT.search(html)
        if rm:
            vod['vod_remarks'] = rm.group(1).strip()

        # 播放线路
        tab_names = self.RE_PLAY_TAB.findall(html)
        tab_blocks = self.RE_TAB_BLOCK.findall(html)

        play_from_list = []
        play_url_list = []
        for i, block in enumerate(tab_blocks):
            name = tab_names[i] if i < len(tab_names) else f'线路{i + 1}'
            episodes = self.RE_PLAY_LINK.findall(block)
            if not episodes:
                continue
            play_from_list.append(name)
            url_parts = [f"{ep.strip()}${pid}" for pid, ep in episodes]
            play_url_list.append('#'.join(url_parts))

        vod['vod_play_from'] = '$$$'.join(play_from_list)
        vod['vod_play_url'] = '$$$'.join(play_url_list)

        return vod

    def _build_filters(self):
        """构建筛选器"""
        sort_values = [
            {"n": "按最新", "v": "time"},
            {"n": "按最热", "v": "hits"},
            {"n": "按评分", "v": "score"},
        ]
        year_values = [{"n": str(y), "v": str(y)} for y in range(2026, 2009, -1)]
        year_values.insert(0, {"n": "全部", "v": ""})
        lang_values = [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"},
            {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"},
            {"n": "闽南语", "v": "闽南语"},
            {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"},
            {"n": "法语", "v": "法语"},
            {"n": "德语", "v": "德语"},
            {"n": "其它", "v": "其它"},
        ]

        filters = {}

        filters['dianying'] = [
            {"key": "cate", "name": "类型", "value": [
                {"n": "全部", "v": "dianying"},
                {"n": "喜剧片", "v": "xijupian"},
                {"n": "动作片", "v": "dongzuopian"},
                {"n": "爱情片", "v": "aiqingpian"},
                {"n": "科幻片", "v": "kehuanpian"},
                {"n": "恐怖片", "v": "kongbupian"},
                {"n": "剧情片", "v": "juqingpian"},
                {"n": "战争片", "v": "zhanzhengpian"},
                {"n": "动画片", "v": "donghuapian"},
            ]},
            {"key": "area", "name": "地区", "value": [
                {"n": "全部", "v": ""},
                {"n": "大陆", "v": "大陆"},
                {"n": "香港", "v": "香港"},
                {"n": "台湾", "v": "台湾"},
                {"n": "美国", "v": "美国"},
                {"n": "法国", "v": "法国"},
                {"n": "英国", "v": "英国"},
                {"n": "日本", "v": "日本"},
                {"n": "韩国", "v": "韩国"},
                {"n": "德国", "v": "德国"},
                {"n": "泰国", "v": "泰国"},
                {"n": "印度", "v": "印度"},
                {"n": "意大利", "v": "意大利"},
                {"n": "西班牙", "v": "西班牙"},
                {"n": "加拿大", "v": "加拿大"},
                {"n": "其他", "v": "其他"},
            ]},
            {"key": "year", "name": "年份", "value": year_values},
            {"key": "lang", "name": "语言", "value": lang_values},
            {"key": "by", "name": "排序", "value": sort_values},
        ]

        filters['dianshiju'] = [
            {"key": "cate", "name": "类型", "value": [
                {"n": "全部", "v": "dianshiju"},
                {"n": "国产剧", "v": "guochangju"},
                {"n": "欧美剧", "v": "oumeiju"},
                {"n": "日本剧", "v": "ribenju"},
                {"n": "韩国剧", "v": "hanguoju"},
                {"n": "海外剧", "v": "haiwaiju"},
            ]},
            {"key": "area", "name": "地区", "value": [
                {"n": "全部", "v": ""},
                {"n": "大陆", "v": "大陆"},
                {"n": "香港", "v": "香港"},
                {"n": "台湾", "v": "台湾"},
                {"n": "美国", "v": "美国"},
                {"n": "法国", "v": "法国"},
                {"n": "英国", "v": "英国"},
                {"n": "日本", "v": "日本"},
                {"n": "韩国", "v": "韩国"},
                {"n": "德国", "v": "德国"},
                {"n": "泰国", "v": "泰国"},
                {"n": "印度", "v": "印度"},
                {"n": "意大利", "v": "意大利"},
                {"n": "西班牙", "v": "西班牙"},
                {"n": "加拿大", "v": "加拿大"},
                {"n": "其他", "v": "其他"},
            ]},
            {"key": "year", "name": "年份", "value": year_values},
            {"key": "lang", "name": "语言", "value": lang_values},
            {"key": "by", "name": "排序", "value": sort_values},
        ]

        filters['zongyi'] = [
            {"key": "cate", "name": "类型", "value": [
                {"n": "全部", "v": "zongyi"},
                {"n": "大陆综艺", "v": "daluzongyi"},
                {"n": "欧美综艺", "v": "oumeizongyi"},
                {"n": "日韩综艺", "v": "rihanzongyi"},
            ]},
            {"key": "area", "name": "地区", "value": [
                {"n": "全部", "v": ""},
                {"n": "内地", "v": "内地"},
                {"n": "港台", "v": "港台"},
                {"n": "日韩", "v": "日韩"},
                {"n": "欧美", "v": "欧美"},
            ]},
            {"key": "year", "name": "年份", "value": year_values},
            {"key": "lang", "name": "语言", "value": lang_values},
            {"key": "by", "name": "排序", "value": sort_values},
        ]

        filters['dongman'] = [
            {"key": "cate", "name": "类型", "value": [
                {"n": "全部", "v": "dongman"},
                {"n": "国产动漫", "v": "guochandongman"},
                {"n": "日韩动漫", "v": "rihandongman"},
                {"n": "欧美动漫", "v": "oumeidongman"},
                {"n": "海外动漫", "v": "haiwaidongman"},
            ]},
            {"key": "area", "name": "地区", "value": [
                {"n": "全部", "v": ""},
                {"n": "国产", "v": "国产"},
                {"n": "日本", "v": "日本"},
                {"n": "欧美", "v": "欧美"},
                {"n": "其他", "v": "其他"},
            ]},
            {"key": "year", "name": "年份", "value": year_values},
            {"key": "lang", "name": "语言", "value": lang_values},
            {"key": "by", "name": "排序", "value": sort_values},
        ]

        filters['duanju'] = [
            {"key": "cate", "name": "类型", "value": [
                {"n": "全部", "v": "duanju"},
                {"n": "神豪短剧", "v": "shenhaoduanju"},
                {"n": "重生短剧", "v": "chongshengduanju"},
                {"n": "复仇短剧", "v": "fuchouduanju"},
                {"n": "穿越短剧", "v": "chuanyueduanju"},
            ]},
            {"key": "by", "name": "排序", "value": sort_values},
        ]

        return filters

    def host_late(self, url_list):
        """多线程测速，返回最快的域名"""
        if isinstance(url_list, str):
            urls = [u.strip() for u in url_list.split(',')]
        else:
            urls = list(url_list)
        if len(urls) <= 1:
            return urls[0] if urls else self.HOST

        results = {}
        threads = []

        def test_host(url):
            try:
                start = time.time()
                requests.head(url, timeout=1.5, allow_redirects=False,
                              headers={'User-Agent': self.UA})
                results[url] = time.time() - start
            except Exception:
                results[url] = float('inf')

        for url in urls:
            t = threading.Thread(target=test_host, args=(url,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        return min(results.items(), key=lambda x: x[1])[0]

    def convert_field_name(self, field):
        """字段名转换"""
        field = field.lower()
        if field.startswith('vod') and len(field) > 3:
            field = field.replace('vod', 'vod_', 1)
        if field.startswith('type') and len(field) > 4:
            field = field.replace('type', 'type_', 1)
        return field
