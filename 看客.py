# -*- coding: utf-8 -*-
"""
兼容 FongMi/TV (T3) 和 WebHomeTV/PeekPro (T4) 的 Python Spider
站点: 看客 (see95.seesee.sbs / see98.seesee.sbs / see96.seesee.sbs /
       kk123.seesee.sbs / kk122.seesee.sbs / kk121.seesee.sbs)
CMS: 苹果CMS (Maccms) + 多域名镜像
播放源: dytt(电影天堂,直链m3u8) + qq/qiyi/youku/bilibili(官源,xmflv解析)
"""
import sys
import re
import json
import time
import hashlib
import base64
import urllib.parse
import requests as rq

sys.path.append('..')

# ===== AES 加密支持 =====
try:
    from Crypto.Cipher import AES as _AES
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

# ===== 兼容导入 =====
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r


class Spider(Spider):

    # 多域名镜像(按优先级)
    DOMAINS = [
        'https://see95.seesee.sbs',
        'https://see98.seesee.sbs',
        'https://see96.seesee.sbs',
        'https://kk123.seesee.sbs',
        'https://kk122.seesee.sbs',
        'https://kk121.seesee.sbs',
    ]

    # 父分类(只放顶层)
    CLASSES = [
        {'type_name': '电影', 'type_id': '20'},
        {'type_name': '连续剧', 'type_id': '37'},
        {'type_name': '动漫', 'type_id': '44'},
        {'type_name': '综艺', 'type_id': '46'},
        {'type_name': 'B站', 'type_id': '47'},
        {'type_name': 'Netflix', 'type_id': '52'},
    ]

    # 子分类筛选器(新规范第15节)
    FILTERS = {
        '20': [
            {'key': 'type', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '动作片', 'v': '21'},
                {'n': '喜剧片', 'v': '22'},
                {'n': '爱情片', 'v': '23'},
                {'n': '科幻片', 'v': '24'},
                {'n': '恐怖片', 'v': '25'},
                {'n': '剧情片', 'v': '26'},
                {'n': '战争片', 'v': '27'},
                {'n': '惊悚片', 'v': '28'},
                {'n': '犯罪片', 'v': '29'},
                {'n': '冒险篇', 'v': '30'},
                {'n': '动画片', 'v': '31'},
                {'n': '悬疑片', 'v': '32'},
                {'n': '武侠片', 'v': '33'},
                {'n': '奇幻片', 'v': '34'},
                {'n': '纪录片', 'v': '35'},
                {'n': '其他片', 'v': '36'},
            ]},
            {'key': 'by', 'name': '排序', 'value': [
                {'n': '最新', 'v': 'time'},
                {'n': '最热', 'v': 'hits'},
                {'n': '评分', 'v': 'score'},
            ]},
        ],
        '37': [
            {'key': 'type', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '国产剧', 'v': '38'},
                {'n': '港台剧', 'v': '39'},
                {'n': '欧美剧', 'v': '40'},
                {'n': '日韩剧', 'v': '41'},
                {'n': '其他剧', 'v': '42'},
            ]},
            {'key': 'by', 'name': '排序', 'value': [
                {'n': '最新', 'v': 'time'},
                {'n': '最热', 'v': 'hits'},
                {'n': '评分', 'v': 'score'},
            ]},
        ],
        '47': [
            {'key': 'type', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '番剧', 'v': '48'},
                {'n': '国创', 'v': '49'},
                {'n': '电影', 'v': '50'},
                {'n': '电视剧', 'v': '51'},
            ]},
        ],
        '52': [
            {'key': 'type', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': 'Netflix电影', 'v': '53'},
                {'n': 'Netflix自制剧', 'v': '54'},
            ]},
        ],
        '44': [
            {'key': 'by', 'name': '排序', 'value': [
                {'n': '最新', 'v': 'time'},
                {'n': '最热', 'v': 'hits'},
                {'n': '评分', 'v': 'score'},
            ]},
        ],
        '46': [
            {'key': 'by', 'name': '排序', 'value': [
                {'n': '最新', 'v': 'time'},
                {'n': '最热', 'v': 'hits'},
                {'n': '评分', 'v': 'score'},
            ]},
        ],
    }

    # 官源列表(需要 xmflv 解析)
    OFFICIAL_SOURCES = {'qq', 'qiyi', 'youku', 'bilibili'}
    # 直链源列表(可提取m3u8)
    DIRECT_SOURCES = {'dytt'}
    # 父分类无直接内容时的默认子分类兜底(新规范15.4)
    DEFAULT_SUBTYPE = {
        '20': '21',   # 电影 -> 动作片
        '37': '38',   # 连续剧 -> 国产剧
        '47': '48',   # B站 -> 番剧
        '52': '53',   # Netflix -> Netflix电影
    }

    # xmflv 解析配置
    XMFLV_API = 'https://cache.0567890.xyz:4433/Api'
    XMFLV_PAGE = 'https://jx.xmflv.com/?url='
    XMFLV_SIGN_IV = b'fUU9eRmkYzsgbkEK'

    def getName(self):
        return "看客"

    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ''
        else:
            self.extend = extend or ''
        self.ua = 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
        self.header = {
            'User-Agent': self.ua,
            'Referer': '',
        }
        self._host = None
        self._session = rq.Session()
        self._session.verify = False
        self._probe_host()

    # ========== 多域名探测 ==========
    def _probe_host(self):
        for domain in self.DOMAINS:
            try:
                r = rq.get(domain, headers={'User-Agent': self.ua}, timeout=8, verify=False)
                if r.status_code == 200 and len(r.text) > 500:
                    self._host = domain
                    self.header['Referer'] = domain + '/'
                    return
            except Exception:
                continue
        self._host = self.DOMAINS[0]
        self.header['Referer'] = self._host + '/'

    def _get_host(self):
        if self._host:
            return self._host
        self._probe_host()
        return self._host

    def _url(self, path):
        if path.startswith('http'):
            return path
        host = self._get_host()
        if path.startswith('/'):
            return host + path
        return host + '/' + path

    # ========== 网络请求 ==========
    def _fetch(self, url, headers=None, timeout=15):
        h = headers or self.header
        try:
            r = self._session.get(url, headers=h, timeout=timeout)
            return r
        except Exception:
            # 尝试切换域名
            old_host = self._host
            for domain in self.DOMAINS:
                if domain == old_host:
                    continue
                try:
                    new_url = url.replace(old_host, domain)
                    r = self._session.get(new_url, headers=h, timeout=timeout)
                    if r.status_code == 200:
                        self._host = domain
                        self.header['Referer'] = domain + '/'
                        return r
                except Exception:
                    continue
            return None

    def _api(self, params):
        """调用苹果CMS API"""
        url = self._url('/api.php/provide/vod/')
        params = {k: v for k, v in params.items() if v is not None and v != ''}
        try:
            r = self._fetch(url + '?' + '&'.join(f'{k}={rq.utils.quote(str(v), safe="")}' for k, v in params.items()))
            if r and r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {}

    def _api_post(self, params):
        """备用: POST方式调用"""
        url = self._url('/api.php/provide/vod/')
        try:
            r = self._session.post(url, data=params, headers=self.header, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {}

    # ========== 首页 ==========
    def homeContent(self, filter):
        result = {
            'class': self.CLASSES,
            'filters': self.FILTERS,
        }
        result['list'] = self._home_list()
        return result

    def _home_list(self):
        j = self._api({'ac': 'detail', 'pg': 1})
        return self._parse_vod_list(j.get('list', []))

    def homeVideoContent(self):
        return {"list": self._home_list()}

    # ========== 分类列表 ==========
    def categoryContent(self, tid, pg, filter, extend):
        # 解析 extend(新规范15.4:兼容 dict 和 JSON 字符串)
        ext = {}
        if extend:
            if isinstance(extend, dict):
                ext = extend
            elif isinstance(extend, str):
                try:
                    ext = json.loads(extend)
                except Exception:
                    ext = {}
        try:
            pg = int(pg or 1)
        except (ValueError, TypeError):
            pg = 1

        # 读取子分类筛选
        sub_type = ext.get('type', '')
        sort_by = ext.get('by', '')

        # 确定查询用的 type_id
        query_type = sub_type if sub_type else tid

        # 父分类选"全部"时无直接内容:用默认子分类兜底(新规范15.4)
        if not sub_type and query_type in self.DEFAULT_SUBTYPE:
            query_type = self.DEFAULT_SUBTYPE[query_type]

        # 调用 API
        params = {'ac': 'detail', 'pg': pg, 't': query_type}
        if sort_by:
            params['by'] = sort_by

        j = self._api(params)
        vods = self._parse_vod_list(j.get('list', []))
        pagecount = int(j.get('pagecount', 1) or 1)
        total = int(j.get('total', len(vods)) or 0)
        limit = int(j.get('limit', 20) or 20)
        return {
            "list": vods,
            "page": pg,
            "pagecount": pagecount,
            "limit": limit,
            "total": total,
        }

    # ========== 详情 ==========
    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = ids[0]

        j = self._api({'ac': 'detail', 'ids': vod_id})
        d_list = j.get('list', [])
        if not d_list:
            return {"list": []}
        d = d_list[0]

        vod = {
            "vod_id": str(vod_id),
            "vod_name": d.get('vod_name', ''),
            "vod_pic": d.get('vod_pic', ''),
            "type_name": d.get('vod_class', ''),
            "vod_year": d.get('vod_year', ''),
            "vod_area": d.get('vod_area', ''),
            "vod_remarks": d.get('vod_remarks', ''),
            "vod_actor": d.get('vod_actor', ''),
            "vod_director": d.get('vod_director', ''),
            "vod_content": d.get('vod_content', ''),
            "vod_play_from": d.get('vod_play_from', ''),
            "vod_play_url": d.get('vod_play_url', ''),
        }
        return {"list": [vod]}

    # ========== 搜索 ==========
    def searchContent(self, key, quick):
        return self.searchContentPage(key, quick, "1")

    def searchContentPage(self, key, quick, pg):
        try:
            pg = int(pg or 1)
        except (ValueError, TypeError):
            pg = 1
        j = self._api({'ac': 'detail', 'wd': key, 'pg': pg})
        vods = self._parse_vod_list(j.get('list', []))
        pagecount = int(j.get('pagecount', 1) or 1)
        return {
            "list": vods,
            "page": pg,
            "pagecount": pagecount,
            "limit": 20,
            "total": len(vods),
        }

    # ========== 播放 ==========
    def playerContent(self, flag, id, vipFlags):
        play_url = id

        # dytt 源: 直链解析,提取 m3u8
        if 'dytt' in flag.lower():
            m3u8 = self._resolve_dytt(play_url)
            if m3u8:
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": m3u8,
                    "header": {
                        "User-Agent": self.ua,
                        "Referer": self._get_host() + '/',
                    },
                }
            # 解析失败,交给壳子嗅探
            return {
                "parse": 1,
                "playUrl": "",
                "url": play_url,
                "header": {
                    "User-Agent": self.ua,
                    "Referer": self._get_host() + '/',
                },
            }

        # 官源(qq/qiyi/youku/bilibili): 使用 xmflv 解析
        play_url = play_url.strip()
        if play_url and (play_url.startswith('http://') or play_url.startswith('https://')):
            parsed = self._parse_xmflv(play_url)
            if parsed and parsed.get('url'):
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": parsed['url'],
                    "header": {
                        "User-Agent": self.ua,
                        "Referer": "https://jx.xmflv.com/",
                    },
                }

        # xmflv 解析失败: 交给壳子用 xmflv 页面嗅探
        if play_url and (play_url.startswith('http://') or play_url.startswith('https://')):
            sniff_url = self.XMFLV_PAGE + urllib.parse.quote(play_url, safe='')
            return {
                "parse": 1,
                "playUrl": "",
                "url": sniff_url,
                "header": {
                    "User-Agent": self.ua,
                    "Referer": "https://jx.xmflv.com/",
                },
            }

        # 兜底
        return {
            "parse": 1,
            "playUrl": "",
            "url": play_url,
            "header": {
                "User-Agent": self.ua,
                "Referer": self._get_host() + '/',
            },
        }

    # ========== xmflv 解析器 ==========
    def _xmflv_md5(self, s):
        """标准 MD5 返回 hex 字符串"""
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def _xmflv_sign(self, key):
        """
        xmflv sign 函数 (逆向自官网JS):
        1. b = MD5(key) -> 32字符 hex 字符串
        2. AES-256-CBC 加密 key, 密钥=b(32字节), IV=固定值, ZeroPadding
        3. 返回 Base64
        """
        if not _HAS_CRYPTO:
            return ''
        b = self._xmflv_md5(key)
        aes_key = b.encode('utf-8')  # 32 bytes = AES-256
        iv = self.XMFLV_SIGN_IV  # 16 bytes
        plaintext = key.encode('utf-8')

        # CryptoJS ZeroPadding: 仅当不是块整数倍时补零
        block_size = 16
        pad_len = block_size - (len(plaintext) % block_size)
        if pad_len == block_size:
            pad_len = 0
        padded = plaintext + b'\x00' * pad_len

        cipher = _AES.new(aes_key, _AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(padded)
        return base64.b64encode(encrypted).decode('utf-8')

    def _xmflv_decrypt(self, data_b64, key_str, iv_str):
        """AES-128-CBC 解密, PKCS7 padding"""
        if not _HAS_CRYPTO:
            return ''
        aes_key = key_str.encode('utf-8')
        iv = iv_str.encode('utf-8')
        ciphertext = base64.b64decode(data_b64)

        cipher = _AES.new(aes_key, _AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(ciphertext)

        # PKCS7 unpadding
        pad_len = decrypted[-1]
        if 0 < pad_len <= 16:
            decrypted = decrypted[:-pad_len]

        return decrypted.decode('utf-8')

    def _parse_xmflv(self, video_url):
        """
        调用 xmflv API 解析官源视频URL
        返回 dict: {url: m3u8/mp4地址, type: hls/mp4, ...}
        失败返回 None
        """
        if not _HAS_CRYPTO:
            return None
        try:
            # 1. 生成时间戳
            tm = str(int(time.time() * 1000))
            # 2. URL编码 (与 JS encodeURIComponent 一致)
            url_encoded = urllib.parse.quote(video_url, safe='')
            # 3. key = md5(tm + url)
            key = self._xmflv_md5(tm + url_encoded)
            # 4. sign
            sig = self._xmflv_sign(key)
            if not sig:
                return None

            # 5. POST 请求
            data = {
                'tm': tm,
                'url': url_encoded,
                'key': key,
                'sign': sig,
            }
            headers = {
                'User-Agent': self.ua,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://jx.xmflv.com',
                'Referer': 'https://jx.xmflv.com/',
            }

            r = rq.post(self.XMFLV_API, data=data, headers=headers, timeout=15, verify=False)
            resp = r.json()

            if resp.get('code') != 200:
                return None

            # 6. 解密响应
            decrypted = self._xmflv_decrypt(resp['data'], resp['key'], resp['iv'])
            # 7. 清理 tg:@xmflv 前缀
            clean = decrypted.replace('tg:@xmflv', '')
            # 8. 解析JSON
            parsed = json.loads(clean)

            return parsed

        except Exception:
            return None

    def _resolve_dytt(self, share_url):
        """从 dytt 分享页提取 m3u8 直链"""
        try:
            r = self._fetch(share_url, timeout=10)
            if r and r.status_code == 200:
                m = re.search(r'const url\s*=\s*"([^"]+)"', r.text)
                if m:
                    path = m.group(1)
                    if path.startswith('/'):
                        # 提取域名
                        from urllib.parse import urlparse
                        parsed = urlparse(share_url)
                        return f'{parsed.scheme}://{parsed.netloc}{path}'
                    elif path.startswith('http'):
                        return path
        except Exception:
            pass
        return None

    # ========== 辅助 ==========
    def _parse_vod_list(self, vod_list):
        """解析视频列表"""
        result = []
        for d in vod_list:
            if not isinstance(d, dict):
                continue
            result.append({
                'vod_id': str(d.get('vod_id', '')),
                'vod_name': d.get('vod_name', ''),
                'vod_pic': d.get('vod_pic', ''),
                'vod_remarks': d.get('vod_remarks', ''),
            })
        return result

    # ========== 清理 ==========
    def destroy(self):
        if self._session:
            self._session.close()

    def close(self):
        self.destroy()


if __name__ == '__main__':
    spider = Spider()
    spider.init()
