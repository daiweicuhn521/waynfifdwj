# -*- coding: utf-8 -*-

import sys
import re
import os
import json
import time
import gzip
import ssl
import base64
import shutil
import subprocess
import urllib.parse
import urllib.request

try:
    from html import unescape as _html_unescape
except Exception:  # pragma: no cover
    def _html_unescape(s):
        return s

sys.path.append('..')
try:
    from base.spider import Spider as _Base
except Exception:  # 本地/非影视仓环境下的兜底，便于单测
    class _Base(object):
        def init(self, extend=''):
            pass

SITE = 'https://www.l9dy.com'
SITE_NAME = '永乐电影网'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

# 影视仓分类。tid 直接使用站点的 vodshow  slug。
CATEGORIES = [
    {'type_id': 'dianying', 'type_name': '电影'},
    {'type_id': 'lianxuju', 'type_name': '连续剧'},
    {'type_id': 'zongyi', 'type_name': '综艺'},
    {'type_id': 'dongman', 'type_name': '动漫'},
    {'type_id': 'yingshijieshuo', 'type_name': '影视解说'},
    {'type_id': 'shuangwenduanju', 'type_name': '短剧'},
    {'type_id': 'xijupian', 'type_name': '喜剧片'},
    {'type_id': 'aiqingpian', 'type_name': '爱情片'},
    {'type_id': 'kehuanpian', 'type_name': '科幻片'},
    {'type_id': 'kongbupian', 'type_name': '恐怖片'},
    {'type_id': 'juqingpian', 'type_name': '剧情片'},
    {'type_id': 'zhanzhengpian', 'type_name': '战争片'},
    {'type_id': 'dongzuopian', 'type_name': '动作片'},
    {'type_id': 'xuanyipian', 'type_name': '悬疑片'},
    {'type_id': 'fanzuipian', 'type_name': '犯罪片'},
    {'type_id': 'qihuanpian', 'type_name': '奇幻片'},
    {'type_id': 'guzhuangpian', 'type_name': '古装片'},
    {'type_id': 'zainanpian', 'type_name': '灾难片'},
    {'type_id': 'lunlipian', 'type_name': '伦理片'},
    {'type_id': 'jilupian', 'type_name': '记录片'},
    {'type_id': 'lishipian', 'type_name': '历史片'},
    {'type_id': 'shaoshidianying', 'type_name': '邵氏电影'},
    {'type_id': 'guochanju', 'type_name': '国产剧'},
    {'type_id': 'gangtaiju', 'type_name': '港台剧'},
    {'type_id': 'rihanju', 'type_name': '日韩剧'},
    {'type_id': 'oumeiju', 'type_name': '欧美剧'},
    {'type_id': 'taiguoju', 'type_name': '泰国剧'},
    {'type_id': 'haiwaiju', 'type_name': '海外剧'},
    {'type_id': 'guochandongman', 'type_name': '国产动漫'},
    {'type_id': 'oumeidongman', 'type_name': '欧美动漫'},
    {'type_id': 'rihandongman', 'type_name': '日韩动漫'},
    {'type_id': 'zonghedongman', 'type_name': '综合动漫'},
    {'type_id': 'gangaotaidongman', 'type_name': '港澳台动漫'},
    {'type_id': 'daluzongyi', 'type_name': '大陆综艺'},
    {'type_id': 'rihanzongyi', 'type_name': '日韩综艺'},
    {'type_id': 'gangtaizongyi', 'type_name': '港台综艺'},
    {'type_id': 'oumeizongyi', 'type_name': '欧美综艺'},
]

RE_ITEM = re.compile(
    r'<a\b([^>]*\bclass="[^"]*stui-vodlist__thumb[^"]*"[^>]*)>(.*?)</a>',
    re.S | re.I)
RE_PIC_TEXT = re.compile(
    r'<span[^>]*\bclass="[^"]*pic-text[^"]*"[^>]*>(.*?)</span>', re.S | re.I)
RE_EP = re.compile(
    r'<a[^>]*\bhref="(/vplay/(\d+)-(\d+)-(\d+)/)"[^>]*>(.*?)</a>',
    re.S | re.I)
RE_PLAYER = re.compile(
    r'player_aaaa\s*=\s*(\{.*?\})\s*</script>', re.S)
RE_M3U8 = re.compile(r'https?:\\?/\\?/[^"\'\s<>]+?\.m3u8[^"\'\s<>]*', re.I)
RE_VID = re.compile(r'/varticle/(\d+)/')
RE_PAGE_TAIL = re.compile(r'/page/(\d+)/"[^>]*>\s*尾页')


class Spider(_Base):
    def getName(self):
        return SITE_NAME

    def init(self, extend=''):
        # init 只做本地初始化，不联网、不抛异常（借鉴橘汁视频）。
        try:
            try:
                super(Spider, self).init(extend)
            except Exception:
                pass
            self.extend = extend or ''
            self.site = SITE.rstrip('/')
            self.timeout = 15
            self.headers = {
                'User-Agent': UA,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip',
                'Referer': self.site + '/',
            }
            self._ctx = None
            try:
                self._ctx = ssl._create_unverified_context()
            except Exception:
                self._ctx = None
        except Exception:
            self.extend = ''
            self.site = SITE.rstrip('/')
            self.timeout = 15
            self.headers = {'User-Agent': UA}
            self._ctx = None

    # ---------------------------------------------------------------- HTTP
    def _attr(self, tag, name):
        m = re.search(r'\b' + re.escape(name) + r'\s*=\s*"([^"]*)"', tag, re.I)
        return _html_unescape(m.group(1)).strip() if m else ''

    def _clean(self, text):
        if not text:
            return ''
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.S | re.I)
        text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.S | re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = _html_unescape(text)
        text = text.replace('\xa0', ' ')
        return re.sub(r'\s+', ' ', text).strip()

    def _curl(self, url, headers, timeout):
        # 借鉴多多影视：urllib 失败后用 curl 兜底。
        if not shutil.which('curl'):
            return None
        try:
            cmd = ['curl', '-L', '-sS', '--max-time', str(timeout)]
            for k, v in (headers or {}).items():
                if k.lower() == 'accept-encoding':
                    continue
                cmd.extend(['-H', '%s: %s' % (k, v)])
            cmd.append(url)
            r = subprocess.run(cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=timeout + 5)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        return None

    def _request(self, url, headers=None, timeout=None):
        timeout = timeout or self.timeout
        headers = headers or self.headers
        last = None
        for _ in range(2):
            try:
                req = urllib.request.Request(url, headers=headers)
                if self._ctx is not None:
                    resp = urllib.request.urlopen(req, timeout=timeout, context=self._ctx)
                else:
                    resp = urllib.request.urlopen(req, timeout=timeout)
                raw = resp.read()
                enc = (resp.headers.get('Content-Encoding') or '').lower()
                if 'gzip' in enc:
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass
                return raw
            except Exception as e:
                last = e
                time.sleep(0.3)
        raw = self._curl(url, headers, timeout)
        if raw:
            return raw
        return None

    def _get(self, url, referer=None, timeout=None):
        headers = dict(self.headers)
        if referer:
            headers['Referer'] = referer
        raw = self._request(url, headers, timeout)
        if raw is None and referer:
            headers['Referer'] = self.site + '/'
            raw = self._request(url, headers, timeout)
        if raw is None:
            return ''
        for enc in ('utf-8', 'gb18030'):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode('utf-8', 'replace')

    # ---------------------------------------------------------------- 列表
    def _abs(self, url):
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.site + url
        return url

    def _parse_list(self, html):
        out, seen = [], set()
        if not html:
            return out
        for m in RE_ITEM.finditer(html):
            tag, inner = m.group(1), m.group(2)
            href = self._attr(tag, 'href')
            vm = RE_VID.search(href)
            if not vm:
                continue
            vid = vm.group(1)
            if vid in seen:
                continue
            name = self._attr(tag, 'title') or self._clean(inner)
            if not name:
                continue
            pic = (self._attr(tag, 'data-original') or
                   self._attr(tag, 'data-src') or
                   self._attr(tag, 'src'))
            if pic and ('load.gif' in pic or pic.startswith('data:')):
                pic = ''
            note = ''
            nm = RE_PIC_TEXT.search(inner)
            if nm:
                note = self._clean(nm.group(1))
            seen.add(vid)
            out.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': self._abs(pic),
                'vod_remarks': note,
            })
        return out

    def _pagecount(self, html, pg, has_items):
        m = RE_PAGE_TAIL.search(html or '')
        if m:
            try:
                return max(int(m.group(1)), pg)
            except Exception:
                pass
        nums = [int(x) for x in re.findall(r'/page/(\d+)/"', html or '')]
        if nums:
            return max(max(nums), pg)
        return pg + 1 if has_items else pg

    # ---------------------------------------------------------------- 首页
    def homeContent(self, filter=False):
        try:
            html = self._get(self.site + '/')
            return {'class': [dict(c) for c in CATEGORIES],
                    'list': self._parse_list(html)}
        except Exception:
            return {'class': [dict(c) for c in CATEGORIES], 'list': []}

    def homeVideoContent(self):
        try:
            return {'list': self._parse_list(self._get(self.site + '/'))}
        except Exception:
            return {'list': []}

    # ---------------------------------------------------------------- 分类
    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        slug = re.sub(r'[^a-zA-Z0-9_-]', '', str(tid or '')) or 'dianying'
        url = '%s/vodshow/%s/page/%d/' % (self.site, slug, pg)
        html = self._get(url)
        videos = self._parse_list(html)
        return {
            'list': videos,
            'page': pg,
            'pagecount': self._pagecount(html, pg, bool(videos)),
            'limit': len(videos) or 36,
            'total': 999999,
        }

    # ---------------------------------------------------------------- 详情
    def _info(self, html, label):
        m = re.search(
            r'<span[^>]*class="[^"]*text-muted[^"]*"[^>]*>\s*' + label +
            r'\s*[：:]\s*</span>(.*?)(?:<span[^>]*class="[^"]*split-line|<p\b|</p>)',
            html, re.S)
        return self._clean(m.group(1)) if m else ''

    def _parse_lines(self, html, vid):
        heads = []
        for m in re.finditer(r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h3>',
                             html, re.S | re.I):
            heads.append((m.start(), self._clean(m.group(1))))
        lines, order = {}, []
        for m in re.finditer(
                r'<ul[^>]*class="[^"]*stui-content__playlist[^"]*"[^>]*>(.*?)</ul>',
                html, re.S | re.I):
            pos, ul = m.start(), m.group(1)
            name = ''
            for hp, hn in heads:
                if hp < pos:
                    name = hn
                else:
                    break
            name = re.sub(r'\s*播放地址\s*$', '', name).strip()
            eps, seen = [], set()
            for em in RE_EP.finditer(ul):
                href, evid, sid, nid, epname = em.groups()
                if evid != vid:
                    continue
                key = (sid, nid)
                if key in seen:
                    continue
                seen.add(key)
                epname = self._clean(epname) or ('第%s集' % nid)
                eps.append({
                    'name': epname.replace('$', '＄').replace('#', '＃'),
                    'url': self.site + href,
                })
            if not eps:
                continue
            if not name:
                name = '线路%s' % sid
            name = name.replace('$', '＄').replace('#', '＃').strip()
            if name in lines:
                suffix = 2
                while ('%s-%d' % (name, suffix)) in lines:
                    suffix += 1
                name = '%s-%d' % (name, suffix)
            lines[name] = eps
            order.append(name)
        return [(n, lines[n]) for n in order]

    def detailContent(self, ids):
        try:
            ids = list(ids or [])
            if not ids:
                return {'list': []}
        except Exception:
            return {'list': []}
        raw = str(ids[0] or '').strip()
        vm = RE_VID.search(raw)
        vid = vm.group(1) if vm else re.sub(r'\D', '', raw)
        if not vid:
            return {'list': []}
        html = self._get('%s/varticle/%s/' % (self.site, vid),
                         referer=self.site + '/')
        if not html:
            return {'list': []}
        out = {'vod_id': vid}
        tm = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>',
                       html, re.S)
        out['vod_name'] = self._clean(tm.group(1)) if tm else ''
        pm = re.search(
            r'<div[^>]*class="[^"]*stui-content__thumb[^"]*"[^>]*>.*?'
            r'(?:data-original|data-src|src)="([^"]+)"', html, re.S)
        if pm:
            out['vod_pic'] = self._abs(pm.group(1))
        else:
            out['vod_pic'] = ''
        for label, key in (('类型', 'vod_class'), ('地区', 'vod_area'),
                           ('年份', 'vod_year'), ('导演', 'vod_director'),
                           ('主演', 'vod_actor')):
            val = self._info(html, label)
            if val:
                out[key] = val
        dm = re.search(r'<p[^>]*class="[^"]*desc[^"]*"[^>]*>(.*?)</p>',
                       html, re.S)
        if dm:
            desc = self._clean(dm.group(1))
            desc = re.sub(r'^简介\s*[：:]\s*', '', desc)
            desc = re.sub(r'\s*详情\s*$', '', desc)
            out['vod_content'] = desc
        um = re.search(r'更新\s*[：:]\s*</span>\s*([^<]+)', html)
        if um:
            out['vod_remarks'] = '更新 ' + self._clean(um.group(1))
        lines = self._parse_lines(html, vid)
        if lines:
            out['vod_play_from'] = '$$$'.join(n for n, _ in lines)
            out['vod_play_url'] = '$$$'.join(
                '#'.join('%s$%s' % (e['name'], e['url']) for e in eps)
                for _, eps in lines)
            out['vod_remarks'] = out.get('vod_remarks') or '共%d条线路' % len(lines)
        else:
            out['vod_play_from'] = ''
            out['vod_play_url'] = ''
        return {'list': [out]}

    # ---------------------------------------------------------------- 搜索
    def searchContent(self, key, quick=False, pg='1'):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        key = (key or '').strip()
        if not key:
            return {'list': [], 'page': pg}
        q = urllib.parse.quote(key)
        urls = [
            '%s/vodsearch/%s/page/%d/' % (self.site, q, pg),
            '%s/vodsearch/%s/' % (self.site, q),
            '%s/index.php/vod/search/page/%d/wd/%s.html' % (self.site, pg, q),
            '%s/index.php/vod/search.html?wd=%s' % (self.site, q),
        ]
        for url in urls:
            html = self._get(url, referer=self.site + '/')
            videos = self._parse_list(html)
            if videos:
                return {'list': videos, 'page': pg}
        return {'list': [], 'page': pg}

    # ---------------------------------------------------------------- 播放
    def _extract_player(self, html):
        if not html:
            return ''
        m = RE_PLAYER.search(html)
        if not m:
            m = re.search(r'player_aaaa\s*=\s*(\{.*?\});', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                url = data.get('url') or ''
                enc = str(data.get('encrypt') or '0')
                if url and enc == '1':
                    try:
                        pad = '=' * (-len(url) % 4)
                        url = base64.b64decode(url + pad).decode('utf-8', 'replace')
                    except Exception:
                        pass
                elif url and enc == '2':
                    url = urllib.parse.unquote(url)
                url = url.replace('\\/', '/').strip()
                if url.startswith('//'):
                    url = 'https:' + url
                if url.startswith('http'):
                    return url
            except Exception:
                pass
        mm = RE_M3U8.search(html)
        if mm:
            return mm.group(0).replace('\\/', '/')
        return ''

    def _play_result(self, url, parse=0):
        return {
            'parse': parse,
            'playUrl': '',
            'url': url,
            'header': {
                'User-Agent': UA,
                'Referer': self.site + '/',
            },
        }

    def playerContent(self, flag, id, vipFlags=None):
        raw = urllib.parse.unquote((id or '').strip())
        if not raw:
            return self._play_result(self.site + '/', 1)
        # 已经是直链：直接交给播放器（借鉴多多影视）。
        if re.match(r'^https?://', raw, re.I) and not re.search(r'/vplay/', raw):
            return self._play_result(raw, 0)
        if raw.startswith('//'):
            raw = 'https:' + raw
        if not raw.startswith('http'):
            if raw.startswith('/'):
                raw = self.site + raw
            elif re.search(r'^\d+[-_$]\d+[-_$]\d+$', raw):
                p = re.split(r'[-_$]', raw)
                raw = '%s/vplay/%s-%s-%s/' % (self.site, p[0], p[1], p[2])
            else:
                return self._play_result(self.site + '/', 1)
        html = self._get(raw, referer=self.site + '/')
        url = self._extract_player(html)
        if url:
            return self._play_result(url, 0)
        # 解析失败时把播放页交给客户端解析，保留最后一次可用兜底。
        return self._play_result(raw, 1)

    def localProxy(self, param):
        return None

    def liveContent(self, filter=False):
        return {'list': []}

    def isVideoFormat(self, url):
        return bool(re.search(
            r'\.(m3u8|mp4|flv|mkv|avi|ts|mov|mpd|m4a|wmv)(\?|$)', url or '', re.I))

    def isTextFormat(self, url):
        return False

    def manualVideoCheck(self):
        return True

    def destroy(self):
        try:
            self._ctx = None
        except Exception:
            pass