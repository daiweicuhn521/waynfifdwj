# -*- coding: utf-8 -*-
"""
lsjys11 源（SA视频 / lsjys11.com）
Spider 接口与《金牌影视.py》保持一致，可直接放入 py 源目录使用。

站点为 Nuxt3 前端 + 私有 JSON 接口（/api/*），接口请求体与响应体均为
AES-256-CBC(PKCS7) + gzip + base64 封装，密钥由客户端生成的 requestId 与
站点内置字符串经 HMAC-SHA256 派生，本文件已按该方案实现收发。

依赖：requests、pycryptodome（与《金牌影视.py》一致），其余全部标准库。
"""
import base64
import gzip
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import uuid

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    '''
    配置示例：
    {
        "key": "lsjys11",
        "name": "SA视频",
        "type": 3,
        "api": ".所在路径/lsjys11_源.py",
        "searchable": 1,
        "quickSearch": 1,
        "filterable": 1,
        "changeable": 1,
        "ext": {
            "site": "https://www.lsjys11.com",
            "img": "auto"
        }
        // img 可选 auto(默认)/direct/i0.wp.com/i1.wp.com/weserv，
        // 封面图床 cdn.g3ejjm8m.com 在部分网络被 DNS 污染，auto 会自己挑能出图的线路
    }
    '''

    # ---- 站点常量 ----
    API_PREFIX = '/api'
    API_SECRET = b'x3t8rvtaescfe38s'   # 站点前端内置的派生口令
    API_VERSION = '1.0.0'
    UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
    PAGE_SIZE = '24'
    # 封面图床候选：站点封面全部在 cdn.g3ejjm8m.com（Cloudflare），
    # 该域名在部分网络下被 DNS 污染，因此这里备了可透传任意图片的代理线路。
    IMG_ROUTES = (
        ('direct', ''),                                   # 原图，直连
        ('i0.wp.com', 'https://i0.wp.com/'),              # WordPress Photon，按 host/path 透传
        ('i1.wp.com', 'https://i1.wp.com/'),
        ('weserv', 'https://images.weserv.nl/?url='),     # 需整体 urlencode
    )

    # ---- 缓存（提速）----
    _CACHE = {}
    _LOCK = threading.RLock()

    def init(self, extend=""):
        hosts = "https://www.lsjys11.com"
        self.img_option = 'auto'      # auto / direct / i0.wp.com / i1.wp.com / weserv
        self.img_route = None         # 探测结果，None 表示还没探测
        self.img_probe_url = ''
        self.img_route_at = 0
        self._img_lock = threading.Lock()
        if extend:
            try:
                cfg = json.loads(extend)
                hosts = cfg.get('site') or hosts
                self.img_option = cfg.get('img') or self.img_option
            except Exception:
                pass
        self.host = self.host_late(hosts).rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.UA,
            'Accept': 'text/plain, */*',
            'deviceType': 'web',
            'version': self.API_VERSION,
            'language': 'zh-cn',
        })

    def getName(self):
        return 'SA视频'

    def isVideoFormat(self, url):
        return bool(url) and ('.m3u8' in url or '.mp4' in url)

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ================= 加解密与请求 =================
    def _aes_key(self, rid):
        # 站点前端：CryptoJS.HmacSHA256(requestId(hex), 内置口令)
        return hmac.new(self.API_SECRET, bytes.fromhex(rid.replace('-', '')),
                        hashlib.sha256).digest()

    def _encrypt(self, payload, rid):
        raw = gzip.compress(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
        iv = os.urandom(16)
        body = AES.new(self._aes_key(rid), AES.MODE_CBC, iv).encrypt(pad(raw, 16))
        return base64.b64encode(iv + body).decode()

    def _decrypt(self, text, rid):
        data = base64.b64decode(text)
        iv, body = data[:16], data[16:]
        raw = unpad(AES.new(self._aes_key(rid), AES.MODE_CBC, iv).decrypt(body), 16)
        if raw[:2] == b'\x1f\x8b':
            raw = gzip.decompress(raw)
        return json.loads(raw.decode('utf-8'))

    def _api(self, path, data=None, retry=2):
        """调用站点私有接口，返回 data 段；失败返回 {}。"""
        last = None
        for i in range(retry + 1):
            rid = str(uuid.uuid4())
            try:
                resp = self.session.post(
                    self.host + self.API_PREFIX + path,
                    data=self._encrypt({'data': data or {}, 'token': '', 'deviceId': rid}, rid),
                    headers={
                        'requestId': rid,
                        'time': str(int(time.time() * 1000))[:11],
                        'Content-Type': 'text/plain',
                    },
                    timeout=8)
                txt = (resp.text or '').strip()
                if resp.status_code != 200 or not txt:
                    last = 'http %s' % resp.status_code
                    time.sleep(0.3)
                    continue
                if txt.startswith('404'):    # 站点对未知子路径回 404-N 纯文本
                    return {}
                obj = self._decrypt(resp.text, rid)
                if obj.get('status') == 'y':
                    return obj.get('data') or {}
                last = obj.get('error')
                break
            except Exception as e:      # 网络抖动 / 解密异常都重试
                last = repr(e)
                time.sleep(0.3 * (i + 1))
        self._error = last
        return {}

    # ================= 缓存工具 =================
    def _cache_get(self, key):
        with self._LOCK:
            item = self._CACHE.get(key)
        if item and item[0] > time.time():
            return item[1]
        return None

    def _cache_set(self, key, val, ttl):
        with self._LOCK:
            self._CACHE[key] = (time.time() + ttl, val)
            if len(self._CACHE) > 400:      # 简单容量控制
                for k in list(self._CACHE)[:100]:
                    self._CACHE.pop(k, None)
        return val

    # ================= 数据转换 =================
    @staticmethod
    def _clean(text):
        """去掉搜索结果里 <span class="highlight"> 之类的高亮标记。"""
        if not text:
            return ''
        return re.sub(r'<[^>]+>', '', str(text)).replace('&amp;', '&').strip()

    def _probe_route(self, name, url, out):
        """单条封面线路探针：拿真实图片地址去取，校验返回的确实是图片字节。"""
        try:
            resp = self.session.get(url, stream=True, timeout=(2.0, 3.0))
            if resp.status_code != 200:
                resp.close()
                return
            head = resp.raw.read(16) or b''
            resp.close()
            # 只认真正的图片文件头，避免代理返回 HTML 错误页被当成成功
            if head[:3] == b'\xff\xd8\xff' or head[:8] == b'\x89PNG\r\n\x1a\n' \
                    or head[:6] in (b'GIF87a', b'GIF89a') or head[:4] == b'RIFF' \
                    or head[:4] == b'\x00\x00\x01\x00':
                out.append(name)
        except Exception:
            pass

    def _resolve_img_route(self, sample):
        """并发探测可用封面线路，取最先成功的线路；全失败则回原图直连。"""
        with self._img_lock:
            if self.img_route and time.time() - self.img_route_at < 1800:
                return self.img_route
            if self.img_option != 'auto':
                self.img_route = self.img_option
                return self.img_route
            self.img_probe_url = sample
            out = []
            for name, prefix in self.IMG_ROUTES:
                u = self._img_with(prefix, name, sample)
                if not u:
                    continue
                if name.startswith('i0') or name.startswith('i1'):
                    u += ('&' if '?' in u else '?') + 'w=48'   # 探针只要缩略图，快十倍
                elif name == 'weserv':
                    u += '&w=48'
                threading.Thread(target=self._probe_route,
                                 args=(name, u, out), daemon=True).start()
            # 整体只等 2.5 秒：谁先拿到真图片就先用谁，全部失败再退回原图
            deadline = time.time() + 2.5
            while time.time() < deadline and not out:
                time.sleep(0.05)
            self.img_route = out[0] if out else 'direct'
            self.img_route_at = time.time()
            return self.img_route

    @staticmethod
    def _img_with(prefix, name, url):
        if not url:
            return ''
        if name == 'direct':
            return url
        if name == 'weserv':
            return prefix + urllib.parse.quote(url, safe='')
        return prefix + url.split('://', 1)[-1]

    def _img(self, url):
        """把站点封面地址改写成当前可用线路；取不到就返回空，不拿别的图顶替。"""
        if not url:
            return ''
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            url = self.host + url
        route = self.img_route or self._resolve_img_route(url)
        for name, prefix in self.IMG_ROUTES:
            if name == route:
                return self._img_with(prefix, name, url)
        return url

    def _vod(self, item, host=None):
        host = host or self.host
        pic = self._img(item.get('img') or '')
        remarks = item.get('duration') or item.get('update_status_text') or ''
        if item.get('today_update_count'):
            remarks = '今日更新%s' % item['today_update_count'] if not remarks else remarks
        vod = {
            'vod_id': item.get('id', ''),
            'vod_name': self._clean(item.get('name')),
            'vod_pic': pic,
            'vod_remarks': remarks,
            'vod_year': str(item.get('issue_year') or ''),
            'vod_area': item.get('area') or '',
            'vod_actor': item.get('actor') or '',
            'vod_director': item.get('director') or '',
            'vod_content': self._clean(item.get('description')),
            'type_name': item.get('category') or '',
        }
        if item.get('score'):
            vod['vod_douban_score'] = str(item['score'])
        return vod

    # ================= 首页 =================
    def homeContent(self, filter):
        """分类 + 二级筛选全部取自站点 /movie/filter，运行时抓，不写死。"""
        result = {'class': [], 'filters': {}}
        data = self._cache_get('filter')
        if data is None:
            data = self._cache_set('filter', self._api('/movie/filter', {}), 1800)
        if not data:
            # 兜底：接口挂了才用内置分类
            for tid, name in (('13', '电影'), ('12', '连续剧'), ('11', '综艺'),
                              ('16', '短剧'), ('14', '动漫'), ('15', '纪录片')):
                result['class'].append({'type_id': tid, 'type_name': name})
            return result

        cat = data.get('category') or {}
        area = data.get('area') or {}
        lang = data.get('language') or {}
        year = data.get('year') or {}
        status = data.get('series_status') or {}
        sort = data.get('sort') or {}

        base_filters = []
        if area.get('items'):
            base_filters.append({'key': 'area', 'name': '地区',
                                 'value': [{'n': i['name'], 'v': i['value']} for i in area['items']]})
        if lang.get('items'):
            base_filters.append({'key': 'language', 'name': '语言',
                                 'value': [{'n': i['name'], 'v': i['value']} for i in lang['items']]})
        if year.get('items'):
            base_filters.append({'key': 'year', 'name': '年份',
                                 'value': [{'n': i['name'], 'v': i['value']} for i in year['items']]})
        if status.get('items'):
            base_filters.append({'key': 'update_status', 'name': '状态',
                                 'value': [{'n': i['name'], 'v': i['value']} for i in status['items']]})
        if sort.get('items'):
            base_filters.append({'key': 'order', 'name': '排序',
                                 'value': [{'n': i['name'], 'v': i['value']} for i in sort['items']]})

        for item in cat.get('items', []):
            if not item.get('value'):
                continue          # 跳过「全部分类」
            result['class'].append({'type_id': str(item['value']), 'type_name': item['name']})
            fl = []
            tags = (item.get('filters') or {}).get('items') or []
            if tags:
                fl.append({'key': 'tag_id', 'name': '类型',
                           'value': [{'n': t['name'], 'v': t['value']} for t in tags if t['value']]})
            fl.extend(base_filters)
            result['filters'][str(item['value'])] = fl
        return result

    def homeVideoContent(self):
        data = self._cache_get('home')
        if data is None:
            data = self._cache_set('home', self._api('/movie/home', {}), 600)
        vods, seen = [], set()
        for block in (data.get('home_recommends') or []):
            for item in (block.get('items') or []):
                if item.get('id') in seen:
                    continue
                seen.add(item.get('id'))
                vods.append(self._vod(item))
        for block in (data.get('middle_home_recommends') or []):
            for item in (block.get('items') or []):
                if item.get('id') in seen:
                    continue
                seen.add(item.get('id'))
                vods.append(self._vod(item))
        if not vods:      # 首页接口异常时退回最新列表
            fallback, _ = self._list_page('13', 1, {})
            vods = [self._vod(i) for i in ((fallback or {}).get('data') or [])]
        return {'list': vods}

    # ================= 列表 =================
    def _list_page(self, tid, pg, extend):
        params = {
            'ad_code': 'app_data_list',
            'cat_id': str(tid),
            'page': int(pg),
            'page_size': self.PAGE_SIZE,
            'order': extend.get('order') or 'new',
            'order_direction': 'desc',
        }
        for k in ('tag_id', 'area', 'language', 'year', 'update_status'):
            v = extend.get(k)
            if v:
                params[k] = v
        data = self._api('/search/movie', params)
        return data, params

    def categoryContent(self, tid, pg, filter, extend):
        extend = extend or {}
        cache_key = 'list:%s:%s:%s' % (tid, pg, json.dumps(extend, sort_keys=True))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        data, params = self._list_page(tid, pg, extend)
        if not isinstance(data, dict):
            data = {}
        vods = [self._vod(i) for i in (data.get('data') or [])]
        result = {
            'list': vods,
            'page': int(pg),
            'pagecount': int(data.get('last_page') or 9999),
            'limit': int(data.get('page_size') or self.PAGE_SIZE),
            'total': int(data.get('total') or 0),
        }
        return self._cache_set(cache_key, result, 300)

    # ================= 详情 =================
    def detailContent(self, ids):
        vid = str(ids[0])
        data = self._cache_get('detail:%s' % vid)
        if data is None:
            data = self._cache_set('detail:%s' % vid, self._api('/movie/detail', {'id': vid}), 900)
        if not data or not data.get('data'):
            return {'list': []}
        mv = data['data']
        vod = self._vod(mv)

        # 线路：详情给的 play_links 即该片的全部线路（line1/line2/line3…）
        links = mv.get('play_links') or []
        episodes = []      # [(分组名, [(集名, lid)])]
        for grp in (mv.get('links') or []):
            items = [(it.get('name') or '', it.get('id') or '') for it in (grp.get('items') or []) if it.get('id')]
            if items:
                episodes.append((grp.get('name') or '', items))
        flat = [e for _, items in episodes for e in items]

        if not links:
            links = [{'code': 'line1', 'name': '线路1'}]
        froms, urls = [], []
        for ln in links:
            code = ln.get('code') or 'line1'
            froms.append(ln.get('name') or code)
            if flat:
                urls.append('#'.join('%s$%s@@%s@@%s' % (name, vid, lid, code) for name, lid in flat))
            else:
                # 单片电影也至少有 1 集（lid 用详情里的 lid 兜底）
                urls.append('%s$%s@@%s@@%s' % (vod['vod_name'], vid, mv.get('lid') or '', code))
        vod['vod_play_from'] = '$$$'.join(froms)
        vod['vod_play_url'] = '$$$'.join(urls)
        vod['vod_total'] = len(flat)
        vod['vod_remarks'] = mv.get('update_status_text') or vod.get('vod_remarks') or ''
        if mv.get('links_tips'):
            vod['vod_remarks'] = vod['vod_remarks'] or mv['links_tips']

        # 预取首集线路地址，点开即播（不阻塞返回）
        if flat:
            threading.Thread(target=self._prefetch, args=(vid, [flat[0][1]]), daemon=True).start()
        return {'list': [vod]}

    def _episode_links(self, vid, lid):
        key = 'ep:%s:%s' % (vid, lid)
        data = self._cache_get(key)
        if data is None:
            data = self._cache_set(key, self._api('/movie/detail', {'id': vid, 'lid': lid}), 900)
        if not data:
            return []
        return (data.get('data') or {}).get('play_links') or []

    def _prefetch(self, vid, lids):
        """并发预取若干集的播放线路，选集切换不用再等接口。"""
        threads = []
        for lid in lids:
            t = threading.Thread(target=self._episode_links, args=(vid, lid), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=8)

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        key = (key or '').strip()
        if not key:
            return {'list': [], 'page': 1}
        cache_key = 'search:%s:%s' % (key, pg)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        data = self._api('/search/movie', {
            'ad_code': 'app_data_list',
            'keywords': key,
            'page': int(pg),
            'page_size': self.PAGE_SIZE,
            'order_direction': 'desc',
        })
        vods = [self._vod(i) for i in ((data or {}).get('data') or [])]
        # 只保留真正命中关键词的条目：站点在关键词无效时会退化成整站默认列表，
        # 那种回执的 total 是几万级，必须当成 0 条，不能拿来冒充搜索结果。
        kw = key.lower()
        hit = [v for v in vods if kw in (v['vod_name'] or '').lower()]
        total = int((data or {}).get('total') or 0)
        if not hit and total > 2000:
            hit = []
        result = {'list': hit, 'page': int(pg)}
        if (data or {}).get('last_page'):
            result['pagecount'] = int(data['last_page'])
        return self._cache_set(cache_key, result, 300)

    # ================= 播放 =================
    def playerContent(self, flag, id, vipFlags):
        header = {'User-Agent': self.UA, 'Referer': self.host + '/'}
        parts = str(id).split('@@')
        vid = parts[0]
        lid = parts[1] if len(parts) > 1 else ''
        code = parts[2] if len(parts) > 2 else 'line1'

        links = self._episode_links(vid, lid)
        url = ''
        for ln in links:
            if ln.get('code') == code and ln.get('m3u8_url'):
                url = ln['m3u8_url']
                break
        if not url and links:      # 线路对不上就用第一条可用的
            for ln in links:
                if ln.get('m3u8_url'):
                    url = ln['m3u8_url']
                    break
        if not url:
            return {'parse': 0, 'url': '', 'header': header, 'error': '未取到播放地址'}
        if url.startswith('/'):
            url = self.host + url
        # 站点直出 m3u8（AES-128 分片），无需嗅探
        return {'parse': 0, 'url': url, 'header': header}

    def localProxy(self, param):
        pass

    # ================= 多域名测速（沿用金牌写法）=================
    def host_late(self, url_list):
        if isinstance(url_list, str):
            urls = [u.strip() for u in url_list.split(',') if u.strip()]
        else:
            urls = list(url_list)
        if len(urls) <= 1:
            return urls[0] if urls else ''
        results = {}
        threads = []

        def test_host(url):
            try:
                start_time = time.time()
                requests.head(url, timeout=2.0, allow_redirects=False,
                              headers={'User-Agent': self.UA})
                results[url] = (time.time() - start_time) * 1000
            except Exception:
                results[url] = float('inf')

        for url in urls:
            t = threading.Thread(target=test_host, args=(url,), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        ok = {k: v for k, v in results.items() if v != float('inf')}
        if not ok:
            return urls[0]
        return min(ok.items(), key=lambda x: x[1])[0]
