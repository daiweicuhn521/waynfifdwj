# coding=utf-8
#!/usr/bin/env python3
"""TVBox Python 源：DJ秀伴奏 (com.kuaiyuhudong.djshow v4.7.7)
仅作 Python 爬虫/插件开发学习用途，所有音频版权归原平台及原作者所有。

.acbz 音频解密：libacdec.so tkmDec 流加密
  - 128 字节 XOR 基础表（从 so 中通过已知明文攻击还原）
  - keystream 每 32767 字节循环左移 1 字节
  - 解密公式: plain[i] = cipher[i] ^ T[(i + i//32767) mod 128]
  - 验证：多首不同 mid 解密后 ffprobe HE-AAC 44.1kHz 立体声、probe_score=100
"""

import json
import re
import threading
import urllib.parse

import requests

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        def getProxyUrl(self, local=False):
            # 本地自测 fallback
            return './proxy?do=py'


class Spider(BaseSpider):
    site = 'https://qnapi.djshow.cn'
    CDN_UA = 'okhttp/4.9.3'
    PAGE_SIZE = 30
    PROXY_CHUNK = 65536
    SHIFT_PERIOD = 32767

    all_tags = ['抖音', '车载', '广场舞', '喊麦', '对唱', 'DJ', '老歌', '粤语']

    # ---- tkmDec：128 字节 XOR 基础表 ----
    acbz_tbl = bytes.fromhex(
        'f81e57d5959baa14afbe92bb03cfe811'
        'f8636a1a03e4d5bfafd8062a95b84e5d'
        'f8a84edd953a0601af24d5fe03606aec'
        'f86fe833036c9269af95aa4595c2578c'
        'f88c57c29545aa95af69926c0333e86f'
        'f8ec6a6003fed524af01063a95dd4ea8'
        'f85d4eb8952a06d8afbfd5e4031a6a63'
        'f811e8cf03bb92beaf14aa9b95d5571e'
    )

    # 完整设备参数（detail.php 必须带这些参数才返回音频路径）
    DEVICE_PARAMS = {
        'device_id': '655826fc-0e47-4beb-9cdd-343ff8dd56d7',
        'brand': 'HUAWEI', 'sdk_version': '29', 'system_version': '10',
        'product': 'ELE-AL00', 'model': 'ELE-AL00', 'hardware': 'kirin980',
        'system_id': 'HUAWEIELE-AL00', 'manufacturer': 'HUAWEI',
        'version_code': '112', 'ver': '4.7.7', 'market': 'huawei',
        'package_name': 'com.kuaiyuhudong.djshow',
        'guid': '0cad046c197d40b684b1c711d0253805', 'guidts': '1791854395',
        'os': 'android', 'base_play': '39', 'base_playCount': '8',
    }

    def __init__(self):
        try:
            super().__init__()
        except TypeError:
            pass
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.CDN_UA,
            'Accept': '*/*',
            'Accept-Encoding': 'identity',
            'Connection': 'keep-alive',
        })
        self.cdn_session = requests.Session()
        self.cdn_session.headers.update({
            'User-Agent': self.CDN_UA,
            'Accept': '*/*',
            'Accept-Encoding': 'identity',
            'Connection': 'close',
        })
        self._list_cache = {}
        self._detail_cache = {}
        self._size_cache = {}
        self._plain_cache = {}
        self._lock = threading.Lock()

    # ---------- 基础接口（TVBox 要求）----------
    def init(self, extend=''):
        pass

    def getName(self):
        return 'DJ秀伴奏'

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(?:m4a|mp3|aac)(?:\?|$)', url or '', re.I))

    def manualVideoCheck(self):
        return False

    # ---------- tkmDec 流式解密 ----------
    def _tkm_decrypt_chunk(self, data, file_offset):
        T = self.acbz_tbl
        TL = len(T)
        P = self.SHIFT_PERIOD
        out = bytearray(len(data))
        for k in range(len(data)):
            i = file_offset + k
            out[k] = data[k] ^ T[(i + i // P) % TL]
        return bytes(out)

    # ---------- 网络 ----------
    def _api(self, path, params=None):
        p = dict(self.DEVICE_PARAMS)
        if params:
            p.update(params)
        try:
            r = self.session.get(self.site + path, params=p, timeout=20)
            return r.json()
        except Exception as e:
            print('api error:', path, e)
            return {}

    def _cdn_size(self, url):
        if url in self._size_cache:
            return self._size_cache[url]
        total = 0
        try:
            r = self.cdn_session.get(url, headers={'Range': 'bytes=0-0'},
                                     timeout=15, stream=True)
            cr = r.headers.get('Content-Range', '')
            if '/' in cr:
                try:
                    total = int(cr.rsplit('/', 1)[-1])
                except Exception:
                    total = 0
            r.close()
        except Exception:
            total = 0
        if total <= 0:
            try:
                r = self.cdn_session.get(url, stream=True, timeout=20)
                total = int(r.headers.get('Content-Length', 0) or 0)
                r.close()
            except Exception:
                total = 0
        self._size_cache[url] = total
        return total

    def _cdn_range(self, url, start, end):
        r = self.cdn_session.get(url,
                                 headers={'Range': 'bytes=%d-%d' % (start, end)},
                                 timeout=30)
        return r.content

    def _fetch_tag(self, kw):
        with self._lock:
            if kw in self._list_cache:
                return self._list_cache[kw]
        obj = self._api('/api/banzou/search.php',
                        params={'type': 'song', 'keyword': kw})
        songs = ((obj.get('song') or {}).get('songs')) or []
        with self._lock:
            self._list_cache[kw] = songs
        return songs

    # ---------- TVBox 接口 ----------
    def homeContent(self, filter):
        classes = [{'type_id': str(i + 1), 'type_name': self.all_tags[i]}
                   for i in range(len(self.all_tags))]
        rec = []
        try:
            songs = self._fetch_tag('抖音')[:self.PAGE_SIZE]
            for s in songs:
                rec.append({
                    'vod_id': s.get('mid', ''),
                    'vod_name': s.get('name', ''),
                    'vod_pic': s.get('videocover') or s.get('album_cover') or '',
                    'vod_remarks': 'DJ秀',
                })
        except Exception as e:
            print('homeContent error:', e)
        return {'class': classes, 'filters': {}, 'list': rec, 'parse': 0, 'jx': 0}

    def homeVideoContent(self):
        return self.homeContent(False)

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if str(pg).isdigit() else 1
        if page < 1:
            page = 1
        result = {'list': [], 'parse': 0, 'jx': 0,
                  'page': page, 'pagecount': 1, 'limit': self.PAGE_SIZE, 'total': 0}
        idx = int(tid) - 1 if str(tid).isdigit() else -1
        if idx < 0 or idx >= len(self.all_tags):
            return result
        kw = self.all_tags[idx]
        try:
            songs = self._fetch_tag(kw)
        except Exception as e:
            print('categoryContent error:', e)
            return result
        total = len(songs)
        pagecount = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if page > pagecount:
            page = pagecount
        paged = songs[(page - 1) * self.PAGE_SIZE:page * self.PAGE_SIZE]
        out = []
        for s in paged:
            out.append({
                'vod_id': s.get('mid', ''),
                'vod_name': s.get('name', ''),
                'vod_pic': s.get('videocover') or s.get('album_cover') or '',
                'vod_remarks': 'DJ秀伴奏',
            })
        result.update({'list': out, 'page': page, 'pagecount': pagecount,
                       'total': total, 'limit': self.PAGE_SIZE})
        return result

    def detailContent(self, ids):
        result = {'list': [], 'parse': 0, 'jx': 0}
        mid = (ids[0] if ids else '').strip()
        if not mid:
            return result
        # 优先从列表缓存里取（搜索/分类接口直接返回 path/mpath/hpath/videopath 等全量字段）
        item = None
        for arr in self._list_cache.values():
            for s in arr:
                if s.get('mid') == mid:
                    item = dict(s)
                    break
            if item:
                break
        # 兜底：再试一次 detail.php（某些歌曲 detail 返回的音质更全）
        try:
            import time as _t
            obj = self._api('/api/banzou/detail.php',
                            params={'type': 'song', 'mid': mid, 'ts': str(int(_t.time()))})
            res = obj.get('result')
            if res and res.get('path'):
                if item:
                    item.update({k: v for k, v in res.items() if v})
                else:
                    item = res
        except Exception as e:
            print('detailContent error:', e)
        if not item or not (item.get('path') or item.get('mpath') or item.get('hpath')):
            return result

        name = item.get('name') or '歌曲'
        cover = item.get('videocover') or item.get('album_cover') or ''
        singer = item.get('singer') or ''
        songtime = int(item.get('songtime') or 0)
        m, s = divmod(songtime, 60) if songtime else (0, 0)
        desc = 'DJ秀伴奏｜时长 %d:%02d' % (m, s) if songtime else 'DJ秀伴奏'

        episodes = []
        # 按音质高低顺序添加（hpath/mpath/path）。搜索列表仅返回 path；详情接口对部分 mid 会返回全部三档。
        for k, label in (('hpath', '高音质伴奏'),
                         ('mpath', '标准音质'),
                         ('path',  '伴奏')):
            u = item.get(k)
            if u and '.acbz' in u:
                q = urllib.parse.quote(u, safe='')
                episodes.append('%s${type:acbz,url:%s}' % (label, q))
        if not episodes:
            return result

        result['list'] = [{
            'vod_id': mid,
            'vod_name': name,
            'vod_pic': cover,
            'vod_actor': singer,
            'vod_content': desc,
            'vod_play_from': 'DJ秀',
            'vod_play_url': '#'.join(episodes),
        }]
        return result

    def searchContent(self, key, quick=False):
        result = {'list': [], 'parse': 0, 'jx': 0}
        kw = (key or '').strip()
        if not kw:
            return result
        try:
            obj = self._api('/api/banzou/search.php',
                            params={'type': 'song', 'keyword': kw})
            songs = ((obj.get('song') or {}).get('songs')) or []
        except Exception as e:
            print('searchContent error:', e)
            songs = []
        out = []
        for s in songs:
            out.append({
                'vod_id': s.get('mid', ''),
                'vod_name': s.get('name', ''),
                'vod_pic': s.get('videocover') or s.get('album_cover') or '',
                'vod_remarks': 'DJ秀伴奏',
            })
        result['list'] = out
        return result

    # ---------- 播放 / 本地解密代理（与参考源同款 getProxyUrl 拼接方式）----------
    def playerContent(self, flag, id, vipFlags=None):
        """id 形如 '高音质伴奏${type:acbz,url:<urlencoded_acbz_url>}'
        返回时用 self.getProxyUrl(local=True) + '&action=acbz&src=<url>' 拼接本地代理地址，
        与参考 demo（量子 m3u8 清洗代理）保持一致的调用约定。"""
        m = re.match(r'^.*\{type:(\w+),url:(.+)\}$', id or '')
        if not m:
            return {'parse': 0, 'jx': 0, 'url': id or '', 'header': json.dumps({})}
        typ = m.group(1)
        real = urllib.parse.unquote(m.group(2))
        if typ == 'acbz':
            # 参考源写法：proxy_url = self.getProxyUrl(local=True) + f'&action=xxx&src=...'
            proxy_url = self.getProxyUrl(local=True) + '&action=acbz&src=' + urllib.parse.quote(real, safe='')
            return {
                'parse': 0,
                'jx': 0,
                'url': proxy_url,
                'header': json.dumps({'User-Agent': self.CDN_UA}),
            }
        return {'parse': 0, 'jx': 0, 'url': real, 'header': json.dumps({'User-Agent': self.CDN_UA})}

    # ---------- 基础工具：Range 解析 ----------
    @staticmethod
    def _parse_range(range_hdr, total):
        """解析 HTTP Range: bytes=start-end，返回 (start, end, status)。
        end 为闭区间（包含）。无 Range 时返回 (0, total-1, 200)。"""
        start, end, status = 0, total - 1 if total > 0 else 0, 200
        if range_hdr and range_hdr.startswith('bytes=') and '-' in range_hdr[6:]:
            a, b = range_hdr[6:].split('-', 1)
            try:
                if a:
                    start = int(a)
                if b:
                    end = int(b)
            except Exception:
                pass
            if total > 0:
                if start >= total:
                    start, end = total - 1, total - 1
                if end >= total or end < start:
                    end = total - 1
            else:
                if end < start:
                    end = start + 65535
            status = 206
        return start, end, status

    def _load_full(self, src):
        """一次性拉取 + 解密整个 acbz 文件，内存缓存。
        伴奏文件通常 3~10MB，完全装得下；播放器拖动靠本地 Range，
        不再逐块请求上游。"""
        with self._lock:
            if src in self._plain_cache:
                return self._plain_cache[src]
        try:
            raw = self.cdn_session.get(src,
                headers={'User-Agent': self.CDN_UA}, timeout=60).content
        except Exception as e:
            print('load_full error:', e)
            return None
        plain = self._tkm_decrypt_chunk(raw, 0)
        with self._lock:
            self._plain_cache[src] = plain
        return plain

    @staticmethod
    def _mp3_sync_pos(plain, pos):
        """MP3 流：把 pos 对齐到最近的帧同步字（0xFFFB/0xFFF3/0xFFFA/0xFFF2）。
        从 pos 起向前向后最多搜 2KiB，保证拖动后从完整帧开始解码。"""
        n = len(plain)
        # 向前搜（含当前位置）
        for k in range(min(pos, 2048) + 1):
            i = pos - k
            if i + 1 >= n:
                continue
            if plain[i] == 0xFF and plain[i + 1] in (0xFB, 0xF3, 0xFA, 0xF2):
                return i
        # 向后搜
        for i in range(pos, min(pos + 2048, n - 1)):
            if plain[i] == 0xFF and plain[i + 1] in (0xFB, 0xF3, 0xFA, 0xF2):
                return i
        return pos

    def localProxy(self, param):
        """返回 [status, content_type, body, headers_dict]。
        策略：首请求全量拉取+解密+内存缓存；后续 Range 直接在缓存切片；
        MP3 非零起点自动对齐到同步帧，保证拖动进度条能正常解码。"""
        action = param.get('action', '')
        if action != 'acbz':
            return [404, 'text/plain', 'unknown action', {}]

        src = param.get('src', '')
        if isinstance(src, list):
            src = src[0] if src else ''
        if not src:
            return [400, 'text/plain', 'missing src', {}]

        # Range 头（TVBox 框架会透传）
        range_hdr = ''
        for k in ('range', 'Range'):
            v = param.get(k, '')
            if isinstance(v, list):
                v = v[0] if v else ''
            if v:
                range_hdr = v
                break

        plain = self._load_full(src)
        if plain is None:
            return [502, 'text/plain', b'upstream error',
                    {'Access-Control-Allow-Origin': '*'}]
        total = len(plain)

        start, end, status = self._parse_range(range_hdr, total)

        # MP3 非零起点：对齐到最近同步字，否则拖动后帧不对齐会解不出声音
        is_mp3 = (plain[:3] == b'ID3' or
                  (total > 1 and plain[0] == 0xFF
                   and plain[1] in (0xFB, 0xF3, 0xFA, 0xF2)))
        if is_mp3 and start > 0:
            start = self._mp3_sync_pos(plain, start)
            if start > end:
                end = min(total - 1, start + 65535)

        chunk = plain[start:end + 1]

        ctype = 'audio/mp4'
        if plain[:3] == b'ID3' or (total > 1 and plain[0] == 0xFF
                and plain[1] in (0xFB, 0xF3, 0xFA, 0xF2)):
            ctype = 'audio/mpeg'
        elif plain[4:8] == b'ftyp':
            ctype = 'audio/mp4'

        resp_headers = {
            'Content-Type': ctype,
            'Accept-Ranges': 'bytes',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'public, max-age=86400',
            'Content-Length': str(len(chunk)),
        }
        if status == 206 and total > 0:
            resp_headers['Content-Range'] = 'bytes %d-%d/%d' % (start, end, total)
        return [status, ctype, chunk, resp_headers]


# 本地启动：python djshow_spider.py [port]  默认 9999
# 启动后：
#   curl -v 'http://127.0.0.1:9999/proxy?do=py&action=acbz&src=<urlencoded_acbz_url>'
# 会流式解密并返回 m4a/mp3 音频，可直接丢给 ffplay 验证。
if __name__ == '__main__':
    import http.server
    import socketserver
    import sys
    sp = Spider()
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9999

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            p = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(p.query, keep_blank_values=True)
            # 本地代理请求时 self.getProxyUrl 返回 './proxy?do=py'，再拼 action/src
            # 走本地 http server 路径 /proxy?do=py&action=acbz&src=...
            qs['range'] = [self.headers.get('Range', '')]
            # localProxy 返回 [code, content_type, body, headers_dict]
            code, ctype, body, headers = sp.localProxy(qs)
            if isinstance(ctype, bytes):
                body = ctype
                ctype = 'application/octet-stream'
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            for hk, hv in headers.items():
                if hk.lower() == 'content-type':
                    continue
                self.send_header(hk, hv)
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def log_message(self, fmt, *args):
            return

    with socketserver.ThreadingTCPServer(('0.0.0.0', PORT), Handler) as httpd:
        print('djshow proxy listening on http://0.0.0.0:%d' % PORT)
        httpd.serve_forever()
