# -*- coding: utf-8 -*-
# =============================================================================
# 蚂蚁影视 91mayitv —— dr3.js 规则的 Python 基类移植版
# =============================================================================
# 【说明】
# - 站点为 maccms + stui 模板，纯 HTML + GET，无签名无加密
# - 播放两跳：
#     1) /vodplay/{id}-{sid}-{nid}.html → var player_data={url:'mayi_XXX', from:'hnm3u8', ...}
#     2) GET https://zj.sp-flv.com:8443?url={mayi_令牌} → var video_url='https://.../index.m3u8'
#   爱奇艺/腾讯等官方平台线路（from=iqiyi/qq/youku/mgtv...）走 vip.sp-flv 且需浏览器端 JS 签名，
#   壳内拿不到 → 整线跳过预解析并排到最后，点播时交 parse:1 嗅探兜底
# - 线路可用性用「探路」动态判定：每条线路先解析第 1 集，成功的排前、失败的排后
# - 站点 CDN 对并发突发会掐连接（socket hang up）：探路/预解析并发压到 2，失败自动重试一次
# - 二级分类：站点用 maccms vodshow 12 槽筛选路由
#     /vodshow/{id}-{s0}-{area}-{by}-{class}-{lang}-{letter}-{s6}-{s7}-{page}-{s9}-{s10}-{year}.html
# =============================================================================

import sys
import re
import json
import time
from urllib.parse import quote, unquote

import requests

try:
    from concurrent.futures import ThreadPoolExecutor, as_completed
except Exception:
    ThreadPoolExecutor = None
    as_completed = None

sys.path.append('..')
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

try:
    requests.packages.urllib3.disable_warnings()
except Exception:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# 模块级工具 & 筛选常量
# ─────────────────────────────────────────────────────────────────────────────
def _opt(arr):
    """[全部] + 选项列表"""
    return [{'n': '全部', 'v': ''}] + [{'n': x, 'v': x} for x in arr]


F_AREA = {'key': 'area', 'name': '地区', 'value': _opt([
    '大陆', '香港', '台湾', '美国', '法国', '英国', '日本', '韩国', '德国',
    '泰国', '印度', '意大利', '西班牙', '加拿大', '新加坡', '其他'])}

F_LANG = {'key': 'lang', 'name': '语言', 'value': _opt([
    '国语', '英语', '粤语', '闽南语', '韩语', '日语', '法语', '德语', '其它'])}

F_YEAR = {'key': 'year', 'name': '年份', 'value': _opt([
    '2026', '2025', '2024', '2023', '2022', '2021', '2020', '2019', '2018',
    '2017', '2016', '2015', '2014', '2013', '2012', '2011', '2010', '2009',
    '2008', '2007', '2006', '2005', '2004'])}

F_LETTER = {'key': 'letter', 'name': '字母', 'value': _opt([
    'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M',
    'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', '0-9'])}

F_SORT = {'key': 'by', 'name': '排序', 'value': [
    {'n': '默认', 'v': ''}, {'n': '最新', 'v': 'time'},
    {'n': '人气', 'v': 'hits'}, {'n': '评分', 'v': 'score'}]}

FILTERS = {
    '1': [  # 电影
        {'key': 'class', 'name': '类型', 'value': _opt([
            '喜剧', '爱情', '恐怖', '动作', '科幻', '剧情', '战争'])},
        F_AREA, F_LANG, F_YEAR, F_LETTER, F_SORT,
    ],
    '2': [  # 连续剧
        {'key': 'class', 'name': '类型', 'value': _opt([
            '欧美', '国产', '日本', '台湾', '香港', '韩国'])},
        F_AREA, F_LANG, F_YEAR, F_LETTER, F_SORT,
    ],
    '3': [  # 综艺
        {'key': 'class', 'name': '类型', 'value': _opt(['综艺'])},
        F_AREA, F_LANG, F_YEAR, F_LETTER, F_SORT,
    ],
    '4': [  # 动漫
        {'key': 'class', 'name': '类型', 'value': _opt(['动漫'])},
        F_AREA, F_LANG, F_YEAR, F_LETTER, F_SORT,
    ],
}

CLASSES = [
    {'type_id': '1', 'type_name': '电影'},
    {'type_id': '2', 'type_name': '连续剧'},
    {'type_id': '3', 'type_name': '综艺'},
    {'type_id': '4', 'type_name': '动漫'},
]


# ═════════════════════════════════════════════════════════════════════════════
class Spider(_BaseSpider):

    # ─── 站点常量 ───
    HOST = 'https://www.91mayitv.com'
    TIMEOUT = 10
    JX_BASE = 'https://zj.sp-flv.com:8443?url='

    # 官方平台线路 from 集合：要走 vip.sp-flv + 浏览器端签名，壳内解析不了，探路时直接降权
    VIP_FROMS = {
        'iqiyi', 'qq', 'youku', 'mgtv', 'sohu', 'pptv',
        'xigua', 'migu', 'letv', 'baidu', 'link', 'dplayer',
    }
    # 官方平台线路「名字」关键字：FAST_DETAIL 不探活时，靠名字把这类线垫底
    VIP_NAME = re.compile(
        r'爱奇艺|腾讯|优酷|芒果|搜狐|pptv|咪咕|乐视|哔哩|西瓜|韩剧|人人影视|1905',
        re.I)

    HEADERS = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://www.91mayitv.com/',
    }

    # ─── 播放加速配置 ───
    PRE_ALL = False            # True=预解析全部可播集 / False=只预解析每线前 PRE_EPISODES 集
    PRE_EPISODES = 2           # 每线预解析集数
    PRE_CONCURRENCY = 2        # 预解析并发数（站点怕突发，2 最稳）
    PRE_TIMEOUT = 8            # 单集单跳超时(秒)
    PRE_MAX_PER_LINE = 24      # 单线最多预解析集数
    PROBE_CONCURRENCY = 2      # 探路并发数
    RETRY_DELAY = 0.6          # 请求失败/空返回后的重试间隔(秒)
    FAST_DETAIL = True         # True=详情页只探主推资源线，秒开 / False=全量探路

    CACHE_LIST_TTL = 300       # 列表/详情缓存 5 分钟
    CACHE_PLAY_TTL = 1200      # 播放直链缓存 20 分钟（只缓存成功结果）

    # =========================================================================
    # 生命周期
    # =========================================================================
    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._memo = {}

    def getName(self):
        return '蚂蚁影视'

    def init(self, extend=''):
        try:
            self.session.headers.update(self.HEADERS)
        except Exception:
            pass
        return self

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|mkv|flv)(\?|$)', str(url or ''), re.I))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None

    # =========================================================================
    # 工具函数
    # =========================================================================
    @staticmethod
    def _to_path(p):
        """统一成 path：绝对 URL 只取 pathname+search"""
        s = str(p or '/')
        if re.match(r'^https?://', s, re.I):
            m = re.match(r'^https?://[^/]*(\/[\s\S]*)$', s, re.I)
            return m.group(1) if (m and m.group(1)) else '/'
        return s if s.startswith('/') else '/' + s

    def _abs(self, p, base=None):
        if not p:
            return ''
        p = str(p)
        if re.match(r'^https?:', p, re.I):
            return p
        if p.startswith('//'):
            return 'https:' + p
        b = (base or self.HOST).rstrip('/')
        return b + (p if p.startswith('/') else '/' + p)

    @staticmethod
    def _decode_entities(s):
        s = str(s or '')
        s = re.sub(r'&nbsp;', ' ', s, flags=re.I)
        s = s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        s = s.replace('&quot;', '"').replace('&#39;', "'")
        return s

    @staticmethod
    def _clean(s):
        s = str(s or '')
        s = s.replace('\n', '').replace('\t', '').replace('\r', '')
        return re.sub(r'\s+', ' ', s).strip()

    def _tag_text(self, s):
        s = re.sub(r'<(script|style)[\s\S]*?</\1>', ' ', str(s or ''), flags=re.I)
        s = re.sub(r'<[^>]*>', ' ', s)
        return self._clean(self._decode_entities(s))

    @staticmethod
    def _attr_of(s, name):
        m = re.search(r'\b' + re.escape(name) + r'\s*=\s*["\']([^"\']*)["\']',
                      str(s or ''), re.I)
        return m.group(1) if m else ''

    @staticmethod
    def _enc(s):
        try:
            return quote(str(s or ''), safe='')
        except Exception:
            return str(s or '')

    # ─── 轻量缓存（只缓存成功结果，失败不写） ───
    def _cache_get(self, key, ttl):
        v = self._memo.get(key)
        if v and (time.time() - v['t']) < ttl:
            return v['v']
        return None

    def _cache_set(self, key, val, ttl=None):
        self._memo[key] = {'t': time.time(), 'v': val}

    # ─── 限制并发的异步队列 ───
    def _map_limit(self, items, limit, fn):
        if not items:
            return []
        n = max(1, min(int(limit or 1), len(items)))
        if ThreadPoolExecutor is None or n == 1:
            out = []
            for it in items:
                try:
                    out.append(fn(it))
                except Exception:
                    out.append(None)
            return out
        out = [None] * len(items)
        with ThreadPoolExecutor(max_workers=n) as ex:
            fut_map = {}
            for i, it in enumerate(items):
                fut_map[ex.submit(fn, it)] = i
            for fu in as_completed(fut_map):
                i = fut_map[fu]
                try:
                    out[i] = fu.result()
                except Exception:
                    out[i] = None
        return out

    # ─── 网络请求：失败隔 RETRY_DELAY 重试一次 ───
    def _get(self, url, timeout=None):
        to = timeout or self.TIMEOUT
        for attempt in range(2):
            if attempt > 0:
                time.sleep(self.RETRY_DELAY)
            try:
                r = self.session.get(url, headers=self.HEADERS, timeout=to, verify=False)
                if r is not None and r.status_code == 200 and r.text:
                    return r.text
            except Exception:
                pass
        return ''

    # =========================================================================
    # 列表解析
    # =========================================================================
    def _pick_pic(self, frag):
        """图片地址：data-original → img src → 正则直取（站点是 lazyload）"""
        m = re.search(r'data-original\s*=\s*["\']([^"\']+)["\']', frag or '', re.I)
        if m and 'load.gif' not in m.group(1).lower():
            return self._abs(m.group(1))
        m = re.search(r'<img[^>]+src\s*=\s*["\']([^"\']+)["\']', frag or '', re.I)
        if m and 'load.gif' not in m.group(1).lower():
            return self._abs(m.group(1))
        return ''

    @staticmethod
    def _pick_remarks(frag):
        m = re.search(
            r'<span[^>]*class="[^"]*pic-text[^"]*"[^>]*>([\s\S]*?)</span>',
            frag or '', re.I)
        if m:
            return Spider._clean(Spider._decode_entities(re.sub(r'<[^>]*>', ' ', m.group(1))))
        return ''

    def _split_blocks(self, html, marker, window=3000):
        """按 marker 出现位置切块（避免正则处理嵌套 div 的麻烦）"""
        blocks = []
        if not html:
            return blocks
        positions = []
        idx = 0
        while True:
            i = html.find(marker, idx)
            if i < 0:
                break
            positions.append(i)
            idx = i + len(marker)
        for k, pos in enumerate(positions):
            end = positions[k + 1] if (k + 1) < len(positions) else min(len(html), pos + window)
            blocks.append(html[pos:end])
        return blocks

    def _parse_card_block(self, frag, seen, name_from_h3=False):
        """从单个卡片 HTML 片段提取一条记录"""
        m = re.search(r'href\s*=\s*["\']([^"\']*?/voddetail/(\d+)\.html)["\']',
                      frag or '', re.I)
        if not m:
            return None
        vid = m.group(2)
        if vid in seen:
            return None
        seen.add(vid)

        # 标题
        name = ''
        if name_from_h3:
            mh = re.search(r'<h3[^>]*>([\s\S]*?)</h3>', frag, re.I)
            if mh:
                name = self._tag_text(mh.group(1))
        if not name:
            # 取包裹该 href 的 <a ...> 标签上的 title
            tag_start = frag.rfind('<a', 0, m.start())
            tag_end = frag.find('>', m.end())
            if tag_start >= 0 and tag_end > 0:
                tag = frag[tag_start:tag_end + 1]
                name = self._attr_of(tag, 'title')
                if not name:
                    close = frag.find('</a>', tag_end)
                    if close > 0:
                        name = self._tag_text(frag[tag_end + 1:close])
        if not name:
            mh = re.search(r'<h4[^>]*>([\s\S]*?)</h4>', frag, re.I)
            if mh:
                name = self._tag_text(mh.group(1))
        if not name:
            return None

        return {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': self._pick_pic(frag),
            'vod_remarks': self._pick_remarks(frag),
        }

    def _parse_cards(self, html):
        """列表卡片：.stui-vodlist__box"""
        out = []
        seen = set()
        for frag in self._split_blocks(html, 'stui-vodlist__box'):
            item = self._parse_card_block(frag, seen)
            if item:
                out.append(item)
        if out:
            return out
        # 兜底：按 voddetail 链接全量扫
        return self._parse_by_links(html)

    def _parse_search_cards(self, html):
        """搜索卡片：.stui-vodlist__media li 横排，标题在 h3 里"""
        out = []
        seen = set()
        for frag in self._split_blocks(html, 'stui-vodlist__media'):
            item = self._parse_card_block(frag, seen, name_from_h3=True)
            if item:
                out.append(item)
        if out:
            return out
        # 兜底：按 li 切
        for frag in self._split_blocks(html, '<li'):
            item = self._parse_card_block(frag, seen, name_from_h3=True)
            if item:
                out.append(item)
        if out:
            return out
        return self._parse_by_links(html)

    def _parse_by_links(self, html):
        """最终兜底：按 /voddetail/{id}.html 逐个扫"""
        out = []
        seen = set()
        for m in re.finditer(r'href\s*=\s*["\']([^"\']*?/voddetail/(\d+)\.html)["\']',
                             str(html or ''), re.I):
            vid = m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            start = max(0, m.start() - 1500)
            end = min(len(html), m.end() + 1500)
            frag = html[start:end]
            tag_start = html.rfind('<a', 0, m.start())
            tag_end = html.find('>', m.end())
            name = ''
            if tag_start >= 0 and tag_end > 0:
                name = self._attr_of(html[tag_start:tag_end + 1], 'title')
            if not name:
                mh = re.search(r'<h[34][^>]*>([\s\S]*?)</h[34]>', frag, re.I)
                if mh:
                    name = self._tag_text(mh.group(1))
            if not name:
                continue
            out.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': self._pick_pic(frag),
                'vod_remarks': self._pick_remarks(frag),
            })
        return out

    # ─── 总页数：优先取页脚「当前/总页」，兜底扫 vodtype 分页链 ───
    @staticmethod
    def _max_page(html, tid):
        m = re.search(r'class="num"[^>]*>\s*(\d+)\s*/\s*(\d+)', str(html or ''))
        if m and int(m.group(2)) > 0:
            return int(m.group(2))
        mx = 0
        for x in re.finditer(r'vodtype/' + re.escape(str(tid)) + r'-(\d+)\.html',
                             str(html or '')):
            n = int(x.group(1))
            if n > mx:
                mx = n
        return mx or 1

    # ─── vodshow 12 槽筛选路由 ───
    def _build_show(self, tid, f, pg):
        s = [''] * 12
        f = f or {}
        if f.get('area'):
            s[1] = self._enc(f['area'])
        if f.get('by'):
            s[2] = str(f['by'])
        if f.get('class'):
            s[3] = self._enc(f['class'])
        if f.get('lang'):
            s[4] = self._enc(f['lang'])
        if f.get('letter'):
            s[5] = self._enc(f['letter'])
        if pg and int(pg) > 1:
            s[8] = str(pg)
        if f.get('year'):
            s[11] = str(f['year'])
        return '/vodshow/' + str(tid) + '-'.join(s) + '.html'

    # =========================================================================
    # 播放解析（两跳）
    # =========================================================================
    @staticmethod
    def _read_player(html):
        """截 player_data 的 JSON：按花括号配对扫（带字符串感知），比非贪婪正则稳"""
        s = str(html or '')
        m = re.search(r'var\s+player_data\s*=', s)
        if not m:
            m = re.search(r'player_data\s*=', s)
        if not m:
            return None
        start = s.find('{', m.end())
        if start < 0:
            return None
        depth = 0
        in_str = False
        quote_ch = ''
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == quote_ch:
                    in_str = False
                continue
            if c in ('"', "'"):
                in_str = True
                quote_ch = c
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    block = s[start:i + 1]
                    try:
                        return json.loads(block)
                    except Exception:
                        # 单引号 / 尾逗号等非标 JSON 兜底
                        d = {}
                        mf = re.search(r"from\s*:\s*['\"]([^'\"]*)['\"]", block)
                        mu = re.search(r"url\s*:\s*['\"]([^'\"]*)['\"]", block)
                        me = re.search(r"encrypt\s*:\s*(\d+)", block)
                        if mf:
                            d['from'] = mf.group(1)
                        if mu:
                            d['url'] = mu.group(1)
                        if me:
                            d['encrypt'] = int(me.group(1))
                        return d if d else None
        return None

    @staticmethod
    def _b64(s):
        try:
            import base64
            return base64.b64decode(str(s or '')).decode('utf-8', 'ignore')
        except Exception:
            return str(s or '')

    def _jx_resolve(self, raw, timeout=None):
        """云解析一跳：令牌/URL → m3u8 直链"""
        s = str(raw or '').strip()
        if not s:
            return ''
        if re.match(r'^https?://\S+\.(m3u8|mp4|mkv|flv)(\?|$)', s, re.I):
            return s
        if not re.match(r'^https?:', s, re.I):
            if s.startswith('//'):
                s = 'https:' + s
            else:
                s = self.JX_BASE + (s if '%' in s else self._enc(s))
        html = self._get(s, timeout)
        m = re.search(r"var\s+video_url\s*=\s*['\"]([^'\"]*)['\"]", str(html or ''))
        u = m.group(1) if m else ''
        if u.startswith('//'):
            u = 'https:' + u
        return u if re.match(r'^https?://', u, re.I) else ''

    def _resolve_core(self, path, timeout=None):
        """播放页 path → {from, direct}，只缓存成功结果"""
        path = self._to_path(path)
        key = 'p:' + path
        hit = self._cache_get(key, self.CACHE_PLAY_TTL)
        if hit:
            return {'from': '', 'direct': hit}

        html = self._get(self.HOST + path, timeout)
        data = self._read_player(html)
        if not data:
            return {'from': '', 'direct': ''}

        frm = str(data.get('from', '') or '')
        if frm in self.VIP_FROMS:
            return {'from': frm, 'direct': ''}   # 官方平台线路，壳内解析不了

        u = str(data.get('url', '') or '')
        enc = data.get('encrypt', 0)
        try:
            enc = int(enc)
        except Exception:
            enc = 0
        if enc == 1:
            u = unquote(u)
        elif enc == 2:
            u = unquote(self._b64(u))

        direct = self._jx_resolve(u, timeout)
        if direct:
            self._cache_set(key, direct)
        return {'from': frm, 'direct': direct}

    def _resolve_play(self, raw, timeout=None):
        s = str(raw or '')
        if re.match(r'^https?://\S+\.(m3u8|mp4|mkv|flv)(\?|$)', s, re.I):
            return s
        return self._resolve_core(self._to_path(s), timeout).get('direct', '')

    # =========================================================================
    # 首页
    # =========================================================================
    def homeVideoContent(self):
        ck = 'home'
        cached = self._cache_get(ck, self.CACHE_LIST_TTL)
        if cached is not None:
            return cached
        html = self._get(self.HOST + '/')
        res = {'list': self._parse_cards(html)}
        self._cache_set(ck, res, self.CACHE_LIST_TTL)
        return res

    def homeContent(self, filter):
        try:
            lst = self.homeVideoContent().get('list', [])
        except Exception:
            lst = []
        return {
            'class': CLASSES,
            'filters': FILTERS,
            'list': lst,
        }

    # =========================================================================
    # 分类
    # =========================================================================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1

        f = {}
        if isinstance(extend, dict):
            for k, v in extend.items():
                if v:
                    f[k] = v
        elif isinstance(extend, str) and extend:
            try:
                d = json.loads(extend)
                if isinstance(d, dict):
                    for k, v in d.items():
                        if v:
                            f[k] = v
            except Exception:
                pass
        if isinstance(filter, dict):
            for k, v in filter.items():
                if v and k not in f:
                    f[k] = v

        has_filter = any(f.get(k) for k in ('class', 'area', 'lang', 'year', 'letter', 'by'))
        ck = ('catf:%s:%s:%d' % (tid, json.dumps(f, sort_keys=True, ensure_ascii=False), page)
              if has_filter else ('cat:%s:%d' % (tid, page)))
        cached = self._cache_get(ck, self.CACHE_LIST_TTL)
        if cached is not None:
            return cached

        if has_filter:
            path = self._build_show(tid, f, page)
        else:
            path = ('/vodtype/%s.html' % tid) if page <= 1 else ('/vodtype/%s-%d.html' % (tid, page))

        html = self._get(self.HOST + path)
        lst = self._parse_cards(html)
        res = {
            'page': page,
            'pagecount': self._max_page(html, tid),
            'limit': 36,
            'total': 0,
            'list': lst,
        }
        self._cache_set(ck, res, self.CACHE_LIST_TTL)
        return res

    # =========================================================================
    # 搜索
    # =========================================================================
    def searchContent(self, key, quick, pg='1'):
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        ck = 's:%s:%d' % (str(key), page)
        cached = self._cache_get(ck, self.CACHE_LIST_TTL)
        if cached is not None:
            return cached

        path = '/vodsearch/-------------.html?wd=' + self._enc(key)
        html = self._get(self.HOST + path)
        lst = self._parse_search_cards(html)
        res = {'page': 1, 'pagecount': 1, 'limit': len(lst), 'total': len(lst), 'list': lst}
        self._cache_set(ck, res, self.CACHE_LIST_TTL)
        return res

    # =========================================================================
    # 详情
    # =========================================================================
    def detailContent(self, ids):
        vid = ''
        if isinstance(ids, (list, tuple)):
            vid = str(ids[0]) if ids else ''
        else:
            vid = str(ids or '')
        vid = vid.split('$')[-1]
        vid = re.sub(r'\D+', '', vid)
        if not vid:
            return {'list': []}

        ck = 'd:' + vid
        cached = self._cache_get(ck, self.CACHE_LIST_TTL)
        if cached is not None:
            return cached

        res = self._build_detail(vid)
        self._cache_set(ck, res, self.CACHE_LIST_TTL)
        return res

    def _build_detail(self, vid):
        html = self._get(self.HOST + '/voddetail/%s.html' % vid)
        if not html:
            return {'list': []}

        # ── 标题 ──
        title = ''
        m = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', html, re.I)
        if m:
            title = self._tag_text(m.group(1))

        # ── 封面：定位 stui-content__thumb 区域后取 data-original ──
        pic = ''
        pm = re.search(r'stui-content__thumb', html)
        seg = html[pm.start():pm.start() + 3000] if pm else html[:6000]
        mp = re.search(r'data-original\s*=\s*["\']([^"\']+)["\']', seg, re.I)
        if mp and 'load.gif' not in mp.group(1).lower():
            pic = self._abs(mp.group(1))

        # ── 主演/导演/类型 三行 p.data ──
        data_lines = re.findall(
            r'<p\s+class="[^"]*\bdata\b[^"]*"[^>]*>([\s\S]*?)</p>', html, re.I)
        line0 = self._tag_text(data_lines[0]) if len(data_lines) > 0 else ''
        line1 = self._tag_text(data_lines[1]) if len(data_lines) > 1 else ''
        line2 = self._tag_text(data_lines[2]) if len(data_lines) > 2 else ''

        type_name = area = year = ''
        mt = re.search(r'类型[:：]([\s\S]*?)(?:地区[:：]|$)', line2)
        ma = re.search(r'地区[:：]([\s\S]*?)(?:年份[:：]|$)', line2)
        my = re.search(r'年份[:：]\s*(\d{4})', line2) or re.search(r'(\d{4})\s*$', line2)
        if mt:
            type_name = self._clean(mt.group(1))
        if ma:
            area = self._clean(ma.group(1))
        if my:
            year = self._clean(my.group(1))

        # ── 简介 ──
        content = ''
        m = re.search(r'<p\s+class="[^"]*desc[^"]*"[^>]*>([\s\S]*?)</p>', html, re.I)
        if m:
            content = self._tag_text(m.group(1))
        if not content:
            m = re.search(r'<div[^>]*class="[^"]*detail-content[^"]*"[^>]*>([\s\S]*?)</div>',
                          html, re.I)
            if m:
                content = self._tag_text(m.group(1))
        content = re.sub(r'^简介[:：]', '', content)

        # ── 线路名：a.btn.title[data-mid] ──
        tabs = {}
        tab_order = []
        for am in re.finditer(r'<a\s([^>]*)>([\s\S]*?)</a>', html, re.I):
            attrs = am.group(1)
            mid = self._attr_of(attrs, 'data-mid')
            if not mid or mid in tabs:
                continue
            cls = self._attr_of(attrs, 'class')
            if ('btn' not in cls) or ('title' not in cls):
                continue
            nm = self._tag_text(am.group(2))
            if not nm:
                continue
            tabs[mid] = nm
            tab_order.append(mid)

        # ── 选集：ul.stui-content__playlist[data-mid]，按 mid 配对 ──
        pairs = []
        seen_mid = set()
        for um in re.finditer(r'<ul\b([^>]*)>([\s\S]*?)</ul>', html, re.I):
            attrs = um.group(1)
            if 'stui-content__playlist' not in attrs:
                continue
            mid = self._attr_of(attrs, 'data-mid') or str(len(pairs) + 1)
            if mid in seen_mid:
                continue
            seen_mid.add(mid)

            eps = []
            inner = um.group(2)
            for a2 in re.finditer(r'<a\s([^>]*)>([\s\S]*?)</a>', inner, re.I):
                aattrs = a2.group(1)
                href = self._attr_of(aattrs, 'href')
                if not href or href.lower().startswith('javascript:'):
                    continue
                nm = self._tag_text(a2.group(2))
                if not nm:
                    nm = '第%d集' % (len(eps) + 1)
                eps.append(nm + '$' + self._abs(href))
            if not eps:
                continue
            pairs.append({
                'mid': mid,
                'name': tabs.get(mid, '线路' + str(mid)),
                'eps': eps,
            })

        # ── 排序 + 起播加速 ──
        ordered = []
        targets = []

        if self.FAST_DETAIL and pairs:
            # 只探「主推资源线」第 1 集并预解析前几集 → 详情秒开
            res_list = [p for p in pairs if not self.VIP_NAME.search(p['name'])]
            vip_list = [p for p in pairs if self.VIP_NAME.search(p['name'])]
            ordered = res_list + vip_list
            primary = res_list[0] if res_list else (pairs[0] if pairs else None)
            if primary:
                seg = primary['eps'][0] if primary['eps'] else ''
                d = seg.rfind('$')
                url = seg[d + 1:] if d >= 0 else ''
                if url and not re.match(r'^https?://\S+\.(m3u8|mp4|mkv|flv)(\?|$)', url, re.I):
                    r = self._resolve_core(self._to_path(url), self.PRE_TIMEOUT)
                    if r.get('direct') and d >= 0:
                        primary['eps'][0] = seg[:d + 1] + r['direct']
                targets.append(primary)
        else:
            # 全量探路：每条线路解析第 1 集 → 成功的排前、VIP/失败的排后
            def _probe(p):
                try:
                    seg = p['eps'][0] if p['eps'] else ''
                    d = seg.rfind('$')
                    url = seg[d + 1:] if d >= 0 else ''
                    if not url:
                        return (p, 5)
                    if re.match(r'^https?://\S+\.(m3u8|mp4|mkv|flv)(\?|$)', url, re.I):
                        return (p, 0)
                    r = self._resolve_core(self._to_path(url), self.PRE_TIMEOUT)
                    if r.get('direct') and d >= 0:
                        p['eps'][0] = seg[:d + 1] + r['direct']
                    if r.get('from') in self.VIP_FROMS:
                        rank = 9
                    elif r.get('direct'):
                        rank = 0
                    else:
                        rank = 5
                    return (p, rank)
                except Exception:
                    return (p, 5)

            probed = [x for x in self._map_limit(pairs, self.PROBE_CONCURRENCY, _probe) if x]
            probed.sort(key=lambda x: x[1])   # 稳定排序，同 rank 保持页面原顺序
            ordered = [x[0] for x in probed]
            for p, rank in probed:
                if rank == 0:
                    targets.append(p)

        # ── 预解析可播线路的 m3u8 直链，写回选集 ──
        if targets:
            jobs = []
            seen_path = set()
            for p in targets:
                limit = (min(len(p['eps']), self.PRE_MAX_PER_LINE) if self.PRE_ALL
                         else min(len(p['eps']), self.PRE_EPISODES))
                for j in range(limit):
                    seg = p['eps'][j]
                    d = seg.rfind('$')
                    url = seg[d + 1:] if d >= 0 else ''
                    if url and not re.match(r'^https?://\S+\.(m3u8|mp4|mkv|flv)(\?|$)', url, re.I):
                        pth = self._to_path(url)
                        if pth not in seen_path:
                            seen_path.add(pth)
                            jobs.append(pth)

            resolved = self._map_limit(
                jobs, self.PRE_CONCURRENCY,
                lambda pth: self._resolve_core(pth, self.PRE_TIMEOUT))

            path_map = {}
            for i, pth in enumerate(jobs):
                r = resolved[i] if i < len(resolved) else None
                if r and r.get('direct'):
                    path_map[pth] = r['direct']

            for p in targets:
                new_eps = []
                for seg in p['eps']:
                    d = seg.rfind('$')
                    pth = self._to_path(seg[d + 1:]) if d >= 0 else ''
                    if pth in path_map:
                        new_eps.append(seg[:d + 1] + path_map[pth])
                    else:
                        new_eps.append(seg)
                p['eps'] = new_eps

        play_from = '$$$'.join([p['name'] for p in ordered]) or '线路'
        play_url = '$$$'.join(['#'.join(p['eps']) for p in ordered]) or ''

        vod = {
            'vod_id': vid,
            'vod_name': title or vid,
            'vod_pic': pic,
            'type_name': type_name,
            'vod_year': year,
            'vod_area': area,
            'vod_remarks': '',
            'vod_actor': re.sub(r'^主演[:：]', '', self._clean(line0)),
            'vod_director': re.sub(r'^导演[:：]', '', self._clean(line1)),
            'vod_content': content,
            'vod_play_from': play_from,
            'vod_play_url': play_url,
        }
        return {'list': [vod]}

    # =========================================================================
    # 播放
    # =========================================================================
    def playerContent(self, flag, pid, vipFlags):
        direct = ''
        try:
            direct = self._resolve_play(pid)
        except Exception:
            direct = ''

        if direct:
            return {
                'parse': 0,
                'playUrl': '',
                'url': direct,
                'header': self.HEADERS,
            }
        # 没取到直链（含 VIP 平台线路）：交播放器嗅探该播放页
        return {
            'parse': 1,
            'playUrl': '',
            'url': self.HOST + self._to_path(pid),
            'header': self.HEADERS,
        }