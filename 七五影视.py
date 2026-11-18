# -*- coding: utf-8 -*-
# 七五网 qwmp4.com  CatVod / TVBox 源
# 结构：/vt/{分类}-{页}.html 列表  /mv/{id}.html 详情  /py/{id}-{线路}-{集}.html 播放
# 取流：播放页内嵌 player_aaaa 配置，url 为直链 m3u8
import sys, re, json, time
from html import unescape
from urllib.parse import quote, urljoin

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    try:
        import requests
    except ImportError:
        requests = None

    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = requests.get(url, headers=headers, timeout=20, **kw)
            r.encoding = 'utf-8'
            return r

HOST = 'https://www.qwmp4.com'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# 列表过滤字段在 /ms/ 路径中的位置
# /ms/{tid}-{地区}-{排序}-{类型}-{语言}-{}-{}-{}-{页码}-{}-{}-{年代}.html
IDX = {'area': 1, 'by': 2, 'class': 3, 'lang': 4, 'page': 8, 'year': 11}


class Spider(Spider):

    def init(self, extend=''):
        self.base = HOST
        self.ua = UA
        self._c = {}
        try:
            h = self._get(self.base + '/', 0)
            if h:
                self._c[self.base + '/'] = [time.time(), h]
        except Exception:
            pass

    def getName(self):
        return '七五影视'

    def isVideoFormat(self, url):
        if not url:
            return False
        return '.m3u8' in url or '.mp4' in url

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self._c = {}

    # ---------------- 基础请求 ----------------

    def _hd(self):
        return {
            'User-Agent': self.ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': self.base + '/',
        }

    def _req(self, url):
        hd = self._hd()
        try:
            r = self.fetch(url, headers=hd, timeout=15000)
        except TypeError:
            r = self.fetch(url, headers=hd)
        t = r.text if hasattr(r, 'text') else r
        if isinstance(t, bytes):
            t = t.decode('utf-8', 'ignore')
        return t or ''

    def _get(self, url, ttl=600):
        if ttl and url in self._c and time.time() - self._c[url][0] < ttl:
            return self._c[url][1]
        u = quote(url, safe=':/?&=%#-._~')
        t = ''
        # 站点偶发读超时，失败再试一次
        for i in range(2):
            try:
                t = self._req(u)
            except Exception:
                t = ''
            if t:
                break
            time.sleep(0.3)
        if t:
            self._c[url] = [time.time(), t]
        return t

    def _abs(self, u):
        if not u:
            return ''
        if u.startswith('http'):
            return u
        return urljoin(self.base + '/', u)

    def _clean(self, s):
        if not s:
            return ''
        s = re.sub(r'<!--[\s\S]*?-->', '', s)
        s = re.sub(r'<[^>]+>', ' ', s)
        return re.sub(r'\s+', ' ', unescape(s)).strip()

    def _body(self, html):
        t = re.sub(r'<!--[\s\S]*?-->', '', html or '')
        return ' '.join(t.split())

    # ---------------- 列表解析 ----------------

    def _items(self, html):
        out = []
        seen = set()
        body = self._body(html)
        for blk in re.findall(r'<li[^>]*>([\s\S]*?)</li>', body):
            m = re.search(r'href="(/mv/\d+\.html)"', blk)
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            name = ''
            nm = re.search(r'<h3[^>]*>\s*<a[^>]*>([\s\S]*?)</a>', blk)
            if nm:
                name = self._clean(nm.group(1))
            if not name:
                tm = re.search(r'title="([^"]*)"', blk)
                name = unescape(tm.group(1)).strip() if tm else ''
            pic = ''
            pm = re.search(r'<img[^>]*src="([^"]+)"', blk)
            if pm:
                pic = self._abs(pm.group(1))
            remark = ''
            rm = re.search(r'class="bottom2">([\s\S]*?)</span>', blk)
            if rm:
                remark = self._clean(rm.group(1))
            year = area = ''
            tm2 = re.search(r'class="tag">([\s\S]*?)</div>', blk)
            if tm2:
                parts = [x.strip() for x in self._clean(tm2.group(1)).split('/')]
                year = parts[0] if parts else ''
                area = parts[1] if len(parts) > 1 else ''
            out.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': remark,
                'vod_year': year,
                'vod_area': area,
            })
        return out

    def _classes(self, html):
        out = []
        seen = set()
        for m in re.finditer(r'<a[^>]*href="/vt/(\d+)\.html"[^>]*>([\s\S]*?)</a>', self._body(html)):
            tid = m.group(1)
            if tid in seen:
                continue
            name = self._clean(m.group(2))
            if not name:
                continue
            seen.add(tid)
            out.append({'type_id': tid, 'type_name': name})
        return out

    def _pagecount(self, html, pg):
        block = ''
        m = re.search(r'class="pages"[^>]*>([\s\S]*?)</div>', self._body(html))
        if m:
            block = m.group(1)
        nums = [int(x) for x in re.findall(r'>\s*(\d+)\s*</a>', block) if x.isdigit()]
        mx = max(nums) if nums else pg
        if '下一页' in block:
            mx = max(mx, pg) + 1
        return max(mx, pg)

    # ---------------- 筛选（内置，避免启动时多页抓取） ----------------
    AREAS = [
        '大陆', '香港', '台湾', '日本', '韩国', '泰国', '美国', '英国', '法国', '德国',
        '印度', '丹麦', '瑞典', '荷兰', '加拿大', '俄罗斯', '意大利', '比利时', '西班牙', '澳大利亚',
        '其他',
    ]

    LANGS = [
        '国语', '粤语', '英语', '法语', '日语', '韩语', '泰语', '德语', '俄语', '闽南语',
        '丹麦语', '波兰语', '瑞典语', '印地语', '挪威语', '意大利语', '西班牙语', '无对白', '其他',
    ]

    YEARS = [
        '2027', '2026', '2025', '2024', '2023', '2022', '2021', '2020', '2019', '2018',
        '2017', '2016', '2015', '2014', '2013', '2012', '2011', '2010',
    ]

    GENRES = {
        '1': ['剧情', '科幻', '动作', '喜剧', '爱情', '冒险', '儿童', '歌舞', '音乐', '奇幻', '动画', '恐怖', '惊悚', '丧尸', '战争', '传记', '纪录', '犯罪', '悬疑', '西部', '灾难', '古装', '武侠', '家庭', '短片', '校园', '文艺', '运动', '青春', '同性', '励志', '人性', '美食', '女性', '治愈', '历史'],
        '2': ['剧情', '科幻', '动作', '喜剧', '爱情', '冒险', '儿童', '歌舞', '音乐', '奇幻', '动画', '恐怖', '惊悚', '丧尸', '战争', '传记', '纪录', '犯罪', '悬疑', '西部', '灾难', '古装', '武侠', '家庭', '短片', '校园', '文艺', '运动', '青春', '同性', '励志', '人性', '美食', '女性', '治愈', '历史'],
        '3': ['真人秀', '脱口秀', '选秀', '情感', '喜剧', '访谈', '播报', '旅游', '音乐', '美食', '纪实', '曲艺', '生活', '游戏', '财经', '求职', '体育', 'MV', '纪录'],
        '4': ['剧情', '萌系', '科幻', '日常', '战斗', '战争', '热血', '机战', '游戏', '搞笑', '恋爱', '后宫', '百合', '基腐', '冒险', '儿童', '歌舞', '音乐', '奇幻', '恐怖', '惊悚', '犯罪', '悬疑', '西部', '灾难', '古装', '武侠', '泡面', '校园', '运动', '体育', '青春', '美食', '治愈', '致郁', '励志', '历史', '其他'],
        '30': ['短剧', '古装', '复仇', '强者', '悬疑', '甜宠', '神豪', '穿越', '虐恋', '逆袭', '重生', '萌宝'],
    }

    def _filters(self, tid):
        tid = str(tid)
        groups = [
            ('class', '类型', self.GENRES.get(tid) or self.GENRES['1']),
            ('year', '年代', self.YEARS),
            ('area', '地区', self.AREAS),
            ('lang', '语言', self.LANGS),
            ('by', '排序', None),
        ]
        out = []
        for key, name, vals in groups:
            if vals is None:
                vs = [{'n': '最近更新', 'v': 'time'}, {'n': '最多播放', 'v': 'hits'},
                      {'n': '最高评分', 'v': 'score'}]
            else:
                vs = [{'n': '全部', 'v': ''}] + [{'n': x, 'v': x} for x in vals]
            out.append({'key': key, 'name': name, 'value': vs})
        return out

    def _msurl(self, tid, pg, extend):
        ext = extend or {}
        if not isinstance(ext, dict):
            ext = {}
        f = [str(tid)] + [''] * 11
        for k in ('area', 'by', 'class', 'lang', 'year'):
            v = ext.get(k) or ''
            if isinstance(v, str):
                v = v.strip()
                if v:
                    f[IDX[k]] = v
        if pg and int(pg) > 1:
            f[IDX['page']] = str(pg)
        return '%s/ms/%s.html' % (self.base, '-'.join(f))

    # ---------------- 标准接口 ----------------

    def homeContent(self, filter=False):
        html = self._get(self.base + '/')
        result = {'class': self._classes(html), 'list': self._items(html)}
        if filter:
            fl = {}
            for c in result['class']:
                f = self._filters(c['type_id'])
                if f:
                    fl[c['type_id']] = f
            result['filters'] = fl
        return result

    def homeVideoContent(self):
        html = self._get(self.base + '/')
        return {'list': self._items(html)}

    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        url = self._msurl(tid, pg, extend)
        html = self._get(url)
        items = self._items(html)
        return {
            'list': items,
            'page': pg,
            'pagecount': self._pagecount(html, pg),
            'limit': 63,
            'total': 999999,
        }

    def detailContent(self, ids):
        if not ids:
            return {'list': []}
        url = self._abs(ids[0] if isinstance(ids, str) else ids[0])
        html = self._body(self._get(url, 300))
        if not html or not re.search(r'<h1[^>]*>', html):
            return {'list': []}
        vod = {'vod_id': url}

        m = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', html)
        name = self._clean(m.group(1)) if m else ''
        ym = re.search(r'<span class="year">\s*\(?(\d{4})\)?\s*</span>', html)
        year = ym.group(1) if ym else ''
        vod['vod_name'] = re.sub(r'\(\d{4}\)\s*$', '', name).strip()
        vod['vod_year'] = year
        vod['vod_sub'] = ''

        pm = re.search(r'<div class="img">[\s\S]{0,300}?<img[^>]*src="([^"]+)"', html)
        vod['vod_pic'] = self._abs(pm.group(1)) if pm else ''

        rm = re.search(r'class="otherbox">([\s\S]*?)</div>', html)
        if rm:
            em = re.search(r'<em>([\s\S]*?)</em>', rm.group(1))
            vod['vod_remarks'] = self._clean(em.group(1)) if em else ''
        else:
            vod['vod_remarks'] = ''

        def field(label):
            mm = re.search(r'<span>\s*' + label + r'\s*[：:]\s*</span>([\s\S]*?)</div>', html)
            return self._clean(mm.group(1)) if mm else ''

        vod['vod_director'] = field('导演')
        vod['vod_actor'] = field('主演')
        vod['vod_area'] = field('地区').replace(' / ', ',')
        vod['vod_lang'] = field('语言').replace(' / ', ',')
        vod['type_name'] = field('类型').replace(' / ', ',')

        sm = re.search(r'豆瓣\s*([\d.]+)', html)
        vod['vod_score'] = sm.group(1) if sm else ''

        cm = re.search(r'<p class="zkjj_a"[^>]*>([\s\S]*?)</p>', html)
        if not cm:
            cm = re.search(r'<p class="sqjj_a"[^>]*>([\s\S]*?)</p>', html)
        vod['vod_content'] = self._clean(cm.group(1)) if cm else ''

        # 线路名
        froms = []
        tm = re.search(r'<ul class="py-tabs">([\s\S]*?)</ul>', html)
        if tm:
            for li in re.findall(r'<li[^>]*>([\s\S]*?)</li>', tm.group(1)):
                head = re.sub(r'<div[\s\S]*$', '', li)
                nm = self._clean(head)
                if nm:
                    froms.append(nm)

        # 每条线路的集数（空线路直接丢弃，线路名与列表顺序一一对应）
        names = []
        lines = []
        for i, blk in enumerate(re.findall(r'<ul class="player[^"]*"[^>]*>([\s\S]*?)</ul>', html)):
            eps = []
            for a in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', blk):
                href = self._abs(a.group(1))
                if not href:
                    continue
                en = self._clean(a.group(2))
                eps.append('%s$%s' % (en or '播放', href))
            if not eps:
                continue
            names.append(froms[i] if i < len(froms) else '线路%d' % (i + 1))
            lines.append('#'.join(eps))

        vod['vod_play_from'] = '$$$'.join(names)
        vod['vod_play_url'] = '$$$'.join(lines)

        return {'list': [vod]}

    def searchContent(self, key, quick=False, pg='1'):
        u = '%s/ajax/suggest?mid=1&wd=%s&limit=50' % (self.base, quote(key or ''))
        txt = self._get(u, 120)
        lst = []
        try:
            d = json.loads(txt)
        except Exception:
            d = {}
        for i in (d.get('list') or []):
            sid = str(i.get('id') or '')
            if not sid:
                continue
            lst.append({
                'vod_id': '/mv/%s.html' % sid,
                'vod_name': unescape(i.get('name') or ''),
                'vod_pic': self._abs((i.get('pic') or '').replace('\\/', '/')),
                'vod_remarks': '',
            })
        return {'list': lst, 'page': 1, 'pagecount': 1, 'limit': 50, 'total': len(lst)}

    def playerContent(self, flag, id, vipFlags=None):
        url = self._abs(id)
        header = {
            'User-Agent': self.ua,
            'Referer': self.base + '/',
            'Origin': self.base,
        }
        html = self._get(url, 60)
        m = re.search(r'var player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', html)
        if m:
            try:
                d = json.loads(m.group(1))
            except Exception:
                d = {}
            pu = (d.get('url') or '').strip()
            enc = str(d.get('encrypt', '0'))
            if pu and enc in ('0', ''):
                if '.m3u8' in pu or '.mp4' in pu:
                    return {'parse': 0, 'playUrl': '', 'url': pu, 'header': header}
            if pu and pu.startswith('http'):
                return {'parse': 1, 'playUrl': '', 'url': url, 'header': header}
        return {'parse': 1, 'playUrl': '', 'url': url, 'header': header}

    def liveContent(self, url=''):
        return {'class': [], 'list': []}

    def localProxy(self, param=None):
        return [200, 'text/plain', '']