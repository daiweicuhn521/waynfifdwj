# -*- coding: utf-8 -*-

# jqqzx.one（极速影视 / 剧圈圈）py 源 v1

# 站点: https://www.jqqzx.one  多镜像站群，桌面 UA 全 404，必须使用手机 UA

# CMS: AppleCMS + module 模板 / 路由 rewrite

# 结构:

#   分类   /vodshow/id/{tid}/page/{pg}.html  (每页40条)

#          ⚠ 旧格式 /type/{tid}-{pg}.html 为假分页（仅 title 变页号，列表内容恒为第1页）

#   详情   /vod/{vid}.html

#   播放   /play/{vid}-{sid}-{nid}.html  (播放页 player_aaaa JSON 内含 448 位加密串)

#   搜索   /vodsearch.html?wd=xx 触发 maccms 验证码 -> 兜底 /index.php/ajax/suggest?wd=&mid=1

# 播放解密:

#   1) POST https://www.jqqzx.one/jx/api.php  {vid: 加密串} -> {code:200, data:{url: 二级加密}}

#   2) sign(): Base64解码 -> md5('test')逐字节异或 -> Base64解码

#      -> split('/') 跳前2段拼接 -> Base64解码 -> 两字母表字符映射 -> 真实 m3u8/mp4 签名直链

import re, json

# ---- 兼容 Py2/Py3 ----

try:

    from urllib import quote

    from urllib2 import Request, urlopen, HTTPError

except ImportError:

    from urllib.parse import quote

    from urllib.request import Request, urlopen

    from urllib.error import HTTPError

try:

    import hashlib as _hashlib

except Exception:

    _hashlib = None

try:

    import base64 as _b64

except Exception:

    _b64 = None

# ---- 兼容 OK影视 引擎基类；粘贴/独立加载无 base 包时回退空基类 ----

try:

    from base.spider import Spider as _EngineSpider

except Exception:

    class _EngineSpider(object):

        _instance = None

        def __new__(cls, *args, **kwargs):

            if cls._instance:

                return cls._instance

            cls._instance = super(_EngineSpider, cls).__new__(cls)

            return cls._instance

        def __init__(self):

            self.extend = ''

        def init(self, extend=""):

            pass

        def fetch(self, url, *a, **k):

            return _http(url)

        def log(self, msg):

            print(msg)


SITE = {

    'name': 'jqqzx.one',

    'hosts': ["jqqzx.one", "www.jqqzx.one", "jqqzx.com", "www.jqqzx.com"],

    'base': 'https://www.jqqzx.one',

    'cms': 'applemac',

    'template': 'module',

    'route': 'rewrite',

    'home_path': '/',

    'list_path': '/vodshow/id/{tid}/page/{pg}.html',

    'detail_path': '/vod/{vid}.html',

    'play_path': '/play/{vid}-{sid}-{nid}.html',

    'search_path': '/vodsearch.html',

    'search_key': 'wd',

    'api_path': '/jx/api.php',

    'class': [

        ["dianying", "电影"],

        ["juji", "电视剧"],

        ["dongman", "动漫"],

        ["zongyi", "综艺"],

        ["duanju", "短剧"],

    ],

    # 列表项：<a href=/vod/{id}.html title=片名 class="module-poster-item module-item">，块内 data-original 封面、module-item-note 备注

    'vod_re': [

        r"<a[^>]*href=\"(/vod/(\d+)\.html)\"[^>]*title=\"([^\"]*)\"[^>]*class=\"[^\"]*module-poster-item[^\"]*\"[^>]*>(.*?)</a>",

        r"<a[^>]*class=\"[^\"]*module-poster-item[^\"]*\"[^>]*href=\"(/vod/(\d+)\.html)\"[^>]*title=\"([^\"]*)\"[^>]*>(.*?)</a>",

    ],

}

UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'


# ---------- 基础工具 ----------

def _decode(data, content_type=''):

    enc = content_type or ''

    cs = 'utf-8'

    if 'charset=' in enc:

        cs = enc.split('charset=')[-1].split(';')[0].strip()

    try:

        return data.decode(cs, 'ignore')

    except Exception:

        return data.decode('utf-8', 'ignore')


def _http(url, referer=None, timeout=10, retries=3, method='GET', data=None):

    """带手机 UA 的抓取；jqqzx 桌面 UA 全 404，必须手机 UA"""

    for _ in range(retries):

        h = {'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9',

             'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}

        if referer:

            h['Referer'] = referer

        try:

            req = Request(url, headers=h, data=data)

            if method.upper() == 'POST':

                req.get_method = lambda: 'POST'

            r = urlopen(req, timeout=timeout)

            return _decode(r.read(), r.headers.get('content-type', '')), r.getcode()

        except HTTPError as e:

            try:

                return _decode(e.read()), e.code

            except Exception:

                return '', e.code

        except Exception:

            continue

    return '', 0


def _post_json(url, fields, referer=None, timeout=12):

    body = '&'.join('%s=%s' % (quote(str(k)), quote(str(v))) for k, v in fields.items())

    html, code = _http(url, referer=referer, timeout=timeout, method='POST', data=body.encode('utf-8'))

    try:

        return json.loads(html), code

    except Exception:

        return None, code


def _url(base, path):

    if not path:

        return ''

    if path.startswith('http'):

        return path

    if path.startswith('//'):

        return 'http:' + path

    return base.rstrip('/') + ('' if path.startswith('/') else '/') + path


def _hdec(s):

    if not s:

        return s

    try:

        from html import unescape as _u

        return _u(s)

    except Exception:

        try:

            import HTMLParser

            return HTMLParser.HTMLParser().unescape(s)

        except Exception:

            return s


def _clean(s):

    if not s:

        return ''

    s = re.sub(r'<[^>]+>', '', s)

    s = s.replace('\xa0', ' ').strip()

    return _hdec(s).strip()


def _is_direct(u):

    return bool(re.search(r'\.(m3u8|mp4|flv|ts|m4s)(?=\?|#|$|%|\s|[">\'])', u, re.I))


# ---------- 播放地址二次解密（复刻 /jx/player.php 内 sign()） ----------

def _b64d(s):

    """标准 Base64 解码为 utf-8 字符串"""

    if not s:

        return ''

    try:

        return _b64.b64decode(s).decode('utf-8', 'ignore')

    except Exception:

        return ''


def _sign(url):

    """对 api.php 返回的二级加密串解密，得到真实 m3u8/mp4 直链"""

    if not url or not _hashlib or not _b64:

        return url

    try:

        # 1) Base64 解码 -> 与 md5('test') 逐字节异或 -> Base64 解码

        d = _b64d(url)

        key = _hashlib.md5(b'test').hexdigest()

        code = ''.join(chr(ord(d[i]) ^ ord(key[i % len(key)])) for i in range(len(d)))

        s = _b64d(code)

        parts = s.split('/')

        if len(parts) < 3:

            return url

        # 2) 跳前两段，其余拼接后 Base64 解码

        joined = ''.join(parts[i] + ('/' if i + 1 != len(parts) else '') for i in range(2, len(parts)))

        str3 = _b64d(joined)

        # 3) 两字母表字符映射

        arr_a = json.loads(_b64d(parts[1]))

        arr_b = json.loads(_b64d(parts[0]))

        out = []

        for ch in str3:

            if ch.isalpha() and ch in arr_b:

                out.append(arr_b[arr_a.index(ch)])

            else:

                out.append(ch)

        real = ''.join(out)

        if real.startswith('http'):

            return real

        return url

    except Exception:

        return url


# ---------- 列表解析 ----------

def _vod_list(html):

    out, seen = [], set()

    for pat in SITE['vod_re']:

        if not pat:

            continue

        try:

            ms = re.finditer(pat, html, re.S)

        except re.error:

            continue

        any_hit = False

        for m in ms:

            try:

                href, vid, title, inner = m.groups()

            except Exception:

                continue

            if not href or not title:

                continue

            any_hit = True

            if vid in seen:

                continue

            seen.add(vid)

            pm = re.search(r'(?:data-original|src)="([^"]+)"', inner)

            pic = pm.group(1) if pm else ''

            rm = re.search(r'module-item-note[^>]*>\s*([^<]*?)\s*<', inner)

            remarks = _clean(rm.group(1)) if rm else ''

            out.append({

                'vod_id': vid,

                'vod_name': _hdec(title.strip()),

                'vod_pic': _url(SITE['base'], pic) if pic else '',

                'type_name': '',

                'vod_remarks': remarks,

            })

        if any_hit:

            break

    return out


def home():

    html, _ = _http(SITE['base'] + SITE['home_path'])

    return _vod_list(html)


def list_page(tid, page=1):

    url = _url(SITE['base'], SITE['list_path'].format(tid=tid, pg=page))

    html, _ = _http(url)

    return _vod_list(html)


# ---------- 详情解析 ----------

def _field(html, name):

    m = re.search(r'module-info-item-title">\s*%s：\s*</span>\s*<div class="module-info-item-content">\s*(.*?)\s*</div>' % name, html, re.S)

    if m:

        return _clean(m.group(1)).rstrip('/')

    return ''


def detail(vid):

    url = _url(SITE['base'], SITE['detail_path'].format(vid=vid))

    html, _ = _http(url)

    if not html:

        return None

    m = re.search(r'<h1[^>]*>\s*([^<]*?)\s*</h1>', html)

    title = _clean(m.group(1)) if m else vid

    pm = re.search(r'module-info-poster[^>]*>\s*<div[^>]*>\s*<div[^>]*>\s*<img[^>]*(?:data-original|src)="([^"]+)"', html)

    if not pm:

        pm = re.search(r'<img[^>]*class="[^"]*module-item-pic[^"]*"[^>]*(?:data-original|src)="([^"]+)"', html)

    pic = pm.group(1) if pm else ''

    dm = re.search(r'module-info-introduction[^>]*>\s*<p[^>]*>(.*?)</p>', html, re.S)

    desc = _clean(dm.group(1)) if dm else ''

    vod = {

        'vod_id': vid,

        'vod_name': title or vid,

        'vod_pic': _url(SITE['base'], pic) if pic else '',

        'type_name': _field(html, '类型'),

        'vod_actor': _field(html, '主演'),

        'vod_director': _field(html, '导演'),

        'vod_area': _field(html, '地区'),

        'vod_lang': _field(html, '语言'),

        'vod_year': _field(html, '年份'),

        'vod_remarks': _field(html, '更新') or _field(html, '集数'),

        'vod_content': desc,

    }

    # 线路名（tab 顺序）与播放列表块一一对应

    tabs = re.findall(r'data-dropdown-value="([^"]+)"', html)

    blocks = re.split(r'<div class="module-play-list">', html)[1:]

    play_from, play_url = [], []

    for i, b in enumerate(blocks):

        eps = re.findall(r'href="/play/(\d+-\d+-\d+\.html)"[^>]*>\s*<span>([^<]*?)</span>', b)

        if not eps:

            continue

        eps_urls = []

        for e in eps:

            name = _clean(e[1]) or ('第%d集' % (len(eps_urls) + 1))

            eps_urls.append((name, _url(SITE['base'], '/play/' + e[0])))

        fname = tabs[i] if i < len(tabs) and tabs[i] else '线路%d' % (len(play_from) + 1)

        play_from.append(fname)

        play_url.append('#'.join('%s$%s' % (e[0], e[1]) for e in eps_urls))

    vod['vod_play_from'] = '$$$'.join(play_from)

    vod['vod_play_url'] = '$$$'.join(play_url)

    return vod


# ---------- 播放解析 ----------

def _extract_player_json(html):

    """平衡括号提取 player_aaaa JSON 文本"""

    start = html.find('player_aaaa')

    if start < 0:

        return None

    jstart = html.find('{', start)

    if jstart < 0:

        return None

    depth = 0

    i = jstart

    while i < len(html):

        c = html[i]

        if c == '{':

            depth += 1

        elif c == '}':

            depth -= 1

            if depth == 0:

                break

        i += 1

    raw = html[jstart:i + 1]

    try:

        return json.loads(raw)

    except Exception:

        return None


def play(url):

    html, _ = _http(url, referer=SITE['base'])

    if not html:

        return {'parse': 1, 'url': url}

    j = _extract_player_json(html)

    if j:

        enc = j.get('url', '') or ''

        enc = enc.replace('\\/', '/')

        if enc:

            # 调解析接口拿二级加密串

            jr, _ = _post_json(_url(SITE['base'], SITE['api_path']), {'vid': enc}, referer=url)

            if jr and isinstance(jr, dict) and jr.get('code') == 200:

                d = jr.get('data') or {}

                enc2 = d.get('url', '')

                if enc2:

                    real = _sign(enc2)

                    if real.startswith('http') and _is_direct(real):

                        return {'parse': 0, 'url': real}

                    # 非直链则嗅探 m3u8/mp4，失败兜底 WebView

                    h2, _ = _http(real, referer=url, timeout=8, retries=2)

                    for pat in [r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', r'(https?://[^"\'\s]+\.(?:mp4|flv|ts)[^"\'\s]*)']:

                        mm = re.search(pat, h2)

                        if mm:

                            return {'parse': 0, 'url': mm.group(1)}

                    return {'parse': 1, 'url': real}

    # 兜底：播放页内任意直链

    m3 = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', html)

    if m3:

        return {'parse': 0, 'url': m3.group(1)}

    m4 = re.search(r'(https?://[^"\'\s]+\.(?:mp4|flv)[^"\'\s]*)', html)

    if m4:

        return {'parse': 0, 'url': m4.group(1)}

    return {'parse': 1, 'url': url}


# ---------- 搜索 ----------

def _search_suggest(wd):

    """maccms 联想接口兜底（搜索页被验证码保护）"""

    url = _url(SITE['base'], '/index.php/ajax/suggest') + '?wd=' + quote(wd) + '&mid=1'

    html, _ = _http(url)

    if not html:

        return []

    try:

        j = json.loads(html)

    except Exception:

        return []

    if not isinstance(j, dict) or j.get('code') != 1:

        return []

    out = []

    for it in j.get('list') or []:

        out.append({

            'vod_id': str(it.get('id', '')),

            'vod_name': it.get('name', ''),

            'vod_pic': it.get('pic', ''),

            'type_name': '',

            'vod_remarks': '',

        })

    return out


def search(key):

    wd = quote(key)

    url = _url(SITE['base'], SITE['search_path']) + '?' + SITE['search_key'] + '=' + wd

    html, _ = _http(url)

    if html and '系统安全验证' not in html:

        lst = _vod_list(html)

        if lst:

            return lst

    # 验证码或空结果 -> 联想接口兜底

    return _search_suggest(key)


# ============ OK影视 / TVBox 顶层标准接口 ============

def _class_list():

    return [{'type_id': tid, 'type_name': name} for tid, name in SITE['class']]


def _pick_vid(raw):

    m = re.search(r'(\d+)', str(raw))

    return m.group(1) if m else str(raw)


class Spider(_EngineSpider):

    def init(self, extend=""):

        pass

    def homeContent(self, filter=False):

        return {'class': _class_list(), 'list': home()}

    def homeVideoContent(self):

        return {'list': home()}

    def categoryContent(self, tid, pg, filter=False, extend=""):

        pg = int(pg) if str(pg).isdigit() else 1

        vlist = list_page(tid, pg)

        return {'page': pg, 'pagecount': 9999, 'limit': 40, 'total': 99999, 'list': vlist}

    def detailContent(self, ids):

        raw = ids[0] if isinstance(ids, list) and ids else ids

        vid = _pick_vid(raw)

        vod = detail(vid)

        return {'list': [vod]} if vod else {'list': []}

    def searchContent(self, key, quick=False, pg="1"):

        return {'list': search(key)}

    def playerContent(self, flag, id, vipFlags):

        s = str(id).strip()

        if s.startswith('http'):

            return play(s)

        nums = re.findall(r'\d+', s)

        if len(nums) >= 3:

            u = _url(SITE['base'], SITE['play_path'].format(vid=nums[0], sid=nums[1], nid=nums[2]))

            return play(u)

        if nums:

            u = _url(SITE['base'], SITE['detail_path'].format(vid=nums[0]))

            return {'parse': 1, 'url': u}

        return {'parse': 1, 'url': s}


# 老式 catvod 兼容入口

def homeContent(filter=False):

    return Spider().homeContent(filter)


def homeVideoContent():

    return Spider().homeVideoContent()


def categoryContent(tid, pg, filter=False, extend=""):

    return Spider().categoryContent(tid, pg, filter, extend)


def detailContent(ids):

    return Spider().detailContent(ids)


def searchContent(key, quick=False, pg="1"):

    return Spider().searchContent(key, quick, pg)


def playerContent(flag, id, vipFlags):

    return Spider().playerContent(flag, id, vipFlags)
