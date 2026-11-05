# -*- coding: utf-8 -*-
"""
Zsbodi + 搜剧AI 混合线路 (全API版)
内容源: 搜剧AI API (souju.ai) — 首页/分类/搜索/详情/播放
分类ID兼容原zsbodi: 1=电影 2=电视剧 3=综艺 4=动漫 5=短剧
"""

import sys
import json
import time
import hmac
import hashlib
import os
from urllib.parse import quote

sys.path.append('..')

try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass

    class Spider:
        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = _rq.get(url, headers=headers, timeout=timeout, verify=False, **kw)
            r.encoding = 'utf-8'
            return r


SOUJU_HOST = "https://souju.ai"
UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Mobile Safari/537.36")

LINE_TAG = "\u2699\ufe0f\u7ebf\u8def"

# zsbodi分类ID -> 搜剧AI kind
CATE_MAP = {
    "1": "movie",
    "2": "series",
    "3": "variety",
    "4": "anime",
    "5": "short_drama",
}

# 地区映射: zsbodi值 -> 搜剧AI值
REGION_MAP = {
    "\u5927\u9646": "\u4e2d\u56fd\u5927\u9646",
    "\u9999\u6e2f": "\u4e2d\u56fd\u9999\u6e2f",
    "\u53f0\u6e7e": "\u4e2d\u56fd\u53f0\u6e7e",
    "\u7f8e\u56fd": "\u7f8e\u56fd",
    "\u65e5\u672c": "\u65e5\u672c",
    "\u97e9\u56fd": "\u97e9\u56fd",
    "\u5370\u5ea6": "\u5370\u5ea6",
    "\u6cf0\u56fd": "\u6cf0\u56fd",
    "\u82f1\u56fd": "\u82f1\u56fd",
    "\u6b27\u7f8e": "\u6b27\u7f8e",
    "\u5176\u4ed6": "\u5176\u4ed6",
}

# 排序映射
SORT_MAP = {
    "time": "newest",
    "hits": "hottest",
    "score": "rating",
}

SOUJU_SECRET = "f39d73aa7a6426203cdee1ef17b31d3b7ea8c23f4c59c62a3a8aa0f39ee5e79d"

# ============================================================
# 分类配置 (兼容zsbodi ID)
# ============================================================

CLASSES = [
    {"type_name": "\u7535\u5f71",   "type_id": "1"},
    {"type_name": "\u8fde\u7eed\u5267", "type_id": "2"},
    {"type_name": "\u7efc\u827a",   "type_id": "3"},
    {"type_name": "\u52a8\u6f2b",   "type_id": "4"},
    {"type_name": "\u77ed\u5267",   "type_id": "5"},
]

def _year_opts(start=2015, end=2026):
    opts = [{"n": "\u5168\u90e8", "v": ""}]
    for y in range(end, start - 1, -1):
        opts.append({"n": str(y), "v": str(y)})
    opts.append({"n": "\u66f4\u65e9", "v": "older"})
    return opts

_SORT_OPTS = [
    {"n": "\u6700\u65b0", "v": "time"},
    {"n": "\u6700\u70ed", "v": "hits"},
    {"n": "\u8bc4\u5206", "v": "score"},
]

_AREA_OPTS = [
    {"n": "\u5168\u90e8", "v": ""},
    {"n": "\u5927\u9646", "v": "\u5927\u9646"}, {"n": "\u9999\u6e2f", "v": "\u9999\u6e2f"},
    {"n": "\u53f0\u6e7e", "v": "\u53f0\u6e7e"}, {"n": "\u7f8e\u56fd", "v": "\u7f8e\u56fd"},
    {"n": "\u65e5\u672c", "v": "\u65e5\u672c"}, {"n": "\u97e9\u56fd", "v": "\u97e9\u56fd"},
    {"n": "\u5370\u5ea6", "v": "\u5370\u5ea6"}, {"n": "\u6cf0\u56fd", "v": "\u6cf0\u56fd"},
    {"n": "\u82f1\u56fd", "v": "\u82f1\u56fd"}, {"n": "\u6b27\u7f8e", "v": "\u6b27\u7f8e"},
    {"n": "\u5176\u4ed6", "v": "\u5176\u4ed6"},
]

_FILTER_CONFIG = {
    "1": [
        {"key": "genre", "name": "\u7c7b\u578b", "value": [
            {"n": "\u5168\u90e8", "v": ""}, {"n": "\u52a8\u4f5c", "v": "\u52a8\u4f5c"}, {"n": "\u559c\u5267", "v": "\u559c\u5267"},
            {"n": "\u7231\u60c5", "v": "\u7231\u60c5"}, {"n": "\u79d1\u5e7b", "v": "\u79d1\u5e7b"},
            {"n": "\u6050\u6016", "v": "\u6050\u6016"}, {"n": "\u5267\u60c5", "v": "\u5267\u60c5"},
            {"n": "\u6218\u4e89", "v": "\u6218\u4e89"}, {"n": "\u52a8\u753b", "v": "\u52a8\u753b"},
            {"n": "\u60ac\u7591", "v": "\u60ac\u7591"}, {"n": "\u72af\u7f6a", "v": "\u72af\u7f6a"},
            {"n": "\u5947\u5e7b", "v": "\u5947\u5e7b"}, {"n": "\u5192\u9669", "v": "\u5192\u9669"},
        ]},
        {"key": "region", "name": "\u5730\u533a", "value": _AREA_OPTS},
        {"key": "year", "name": "\u5e74\u4efd", "value": _year_opts()},
        {"key": "sort", "name": "\u6392\u5e8f", "value": _SORT_OPTS},
    ],
    "2": [
        {"key": "genre", "name": "\u7c7b\u578b", "value": [
            {"n": "\u5168\u90e8", "v": ""}, {"n": "\u53e4\u88c5", "v": "\u53e4\u88c5"}, {"n": "\u90fd\u5e02", "v": "\u90fd\u5e02"},
            {"n": "\u60ac\u7591", "v": "\u60ac\u7591"}, {"n": "\u6b66\u4fa0", "v": "\u6b66\u4fa0"},
            {"n": "\u79d1\u5e7b", "v": "\u79d1\u5e7b"}, {"n": "\u6218\u4e89", "v": "\u6218\u4e89"},
            {"n": "\u559c\u5267", "v": "\u559c\u5267"}, {"n": "\u7231\u60c5", "v": "\u7231\u60c5"},
            {"n": "\u5bb6\u5ead", "v": "\u5bb6\u5ead"}, {"n": "\u5386\u53f2", "v": "\u5386\u53f2"}, {"n": "\u8c0d\u6218", "v": "\u8c0d\u6218"},
        ]},
        {"key": "region", "name": "\u5730\u533a", "value": _AREA_OPTS},
        {"key": "year", "name": "\u5e74\u4efd", "value": _year_opts()},
        {"key": "sort", "name": "\u6392\u5e8f", "value": _SORT_OPTS},
        {"key": "status", "name": "\u72b6\u6001", "value": [
            {"n": "\u5168\u90e8", "v": ""}, {"n": "\u8fde\u8f7d", "v": "ongoing"}, {"n": "\u5b8c\u7ed3", "v": "completed"},
        ]},
    ],
    "3": [
        {"key": "region", "name": "\u5730\u533a", "value": _AREA_OPTS},
        {"key": "year", "name": "\u5e74\u4efd", "value": _year_opts()},
        {"key": "sort", "name": "\u6392\u5e8f", "value": _SORT_OPTS},
    ],
    "4": [
        {"key": "genre", "name": "\u7c7b\u578b", "value": [
            {"n": "\u5168\u90e8", "v": ""}, {"n": "\u70ed\u8840", "v": "\u70ed\u8840"}, {"n": "\u604b\u7231", "v": "\u604b\u7231"},
            {"n": "\u6821\u56ed", "v": "\u6821\u56ed"}, {"n": "\u5947\u5e7b", "v": "\u5947\u5e7b"}, {"n": "\u79d1\u5e7b", "v": "\u79d1\u5e7b"},
            {"n": "\u641e\u7b11", "v": "\u641e\u7b11"}, {"n": "\u5192\u9669", "v": "\u5192\u9669"}, {"n": "\u8fd0\u52a8", "v": "\u8fd0\u52a8"},
        ]},
        {"key": "region", "name": "\u5730\u533a", "value": [
            {"n": "\u5168\u90e8", "v": ""}, {"n": "\u65e5\u672c", "v": "\u65e5\u672c"}, {"n": "\u4e2d\u56fd", "v": "\u4e2d\u56fd"},
            {"n": "\u6b27\u7f8e", "v": "\u6b27\u7f8e"}, {"n": "\u97e9\u56fd", "v": "\u97e9\u56fd"},
        ]},
        {"key": "year", "name": "\u5e74\u4efd", "value": _year_opts()},
        {"key": "sort", "name": "\u6392\u5e8f", "value": _SORT_OPTS},
    ],
    "5": [
        {"key": "genre", "name": "\u7c7b\u578b", "value": [
            {"n": "\u5168\u90e8", "v": ""}, {"n": "\u90fd\u5e02", "v": "\u90fd\u5e02"}, {"n": "\u53e4\u88c5", "v": "\u53e4\u88c5"},
            {"n": "\u9006\u88ad", "v": "\u9006\u88ad"}, {"n": "\u751c\u5ba0", "v": "\u751c\u5ba0"}, {"n": "\u8d5e\u5a7f", "v": "\u8d5e\u5a7f"},
        ]},
        {"key": "year", "name": "\u5e74\u4efd", "value": _year_opts()},
        {"key": "sort", "name": "\u6392\u5e8f", "value": _SORT_OPTS},
    ],
}

FILTERS = {c["type_id"]: _FILTER_CONFIG[c["type_id"]]
           for c in CLASSES if c["type_id"] in _FILTER_CONFIG}


# ============================================================
# 搜剧AI API 封装
# ============================================================

class SoujuAPI:
    def __init__(self, spider):
        self.spider = spider
        self.site_url = SOUJU_HOST
        self.secret = SOUJU_SECRET
        self.headers = {
            'User-Agent': UA,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.site_url + '/',
            'Origin': self.site_url,
        }
        self.default_pic = 'https://pic.rmb.bdstatic.com/bjh/user/default.png'

    def _sign_headers(self, method, path_with_search):
        ts = str(int(time.time() * 1000))
        nonce = os.urandom(16).hex()
        msg = '{0}\n{1}\n{2}\n{3}'.format(method, path_with_search, ts, nonce)
        sig = hmac.new(self.secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()
        return {
            **self.headers,
            'x-ai-movie-timestamp': ts,
            'x-ai-movie-nonce': nonce,
            'x-ai-movie-signature': sig,
        }

    def _get(self, path):
        url = self.site_url + path
        headers = self._sign_headers('GET', path)
        try:
            resp = self.spider.fetch(url, headers=headers)
            if not resp:
                return {}
            return json.loads(resp.text)
        except Exception:
            return {}

    def _post(self, path, payload):
        url = self.site_url + path
        headers = self._sign_headers('POST', path)
        headers['Content-Type'] = 'application/json'
        try:
            resp = self.spider.fetch(url, headers=headers, data=json.dumps(payload, ensure_ascii=False))
            if not resp:
                return {}
            return json.loads(resp.text)
        except Exception:
            return {}

    def home(self):
        return self._get('/v1/feed/home')

    def catalog(self, kind, page=1, limit=30, genre='', region='', year='', sort='newest', status=''):
        params = ['kind={0}'.format(kind), 'page={0}'.format(page), 'limit={0}'.format(limit)]
        if genre:
            params.append('genre={0}'.format(quote(genre)))
        if region:
            params.append('region={0}'.format(quote(region)))
        if year:
            if '_' in year:
                parts = year.split('_')
                params.append('year_from={0}&year_to={1}'.format(parts[0], parts[1]))
            else:
                params.append('year={0}'.format(year))
        if sort:
            params.append('sort={0}'.format(sort))
        if status:
            params.append('status={0}'.format(status))
        path = '/v1/browse/catalog?' + '&'.join(params)
        return self._get(path)

    def search(self, keyword, page=1, limit=30):
        encoded = quote(keyword)
        path = '/v1/browse/catalog?q={0}&page={1}&limit={2}'.format(encoded, page, limit)
        return self._get(path)

    def detail(self, vid):
        return self._get('/v1/catalog/{0}'.format(vid))

    def episodes(self, vid):
        return self._get('/v1/catalog/{0}/episodes'.format(vid))

    def resolve(self, token):
        return self._get('/v1/playback/resolve/{0}'.format(quote(token)))

    def resolve_line(self, ticket, line, provider_id, play_from):
        payload = {
            'ticket': ticket,
            'line': line,
            'provider_id': provider_id,
            'play_from': play_from,
        }
        return self._post('/v1/playback/resolve-line', payload)

    def parse_card(self, card):
        vid = card.get('id', '') or ''
        name = card.get('title', '') or ''
        pic = card.get('poster_url', '') or ''
        remark = card.get('remarks', '') or ''
        year = str(card.get('year', '')) if card.get('year') else ''
        area = card.get('area', '') or ''
        genres = card.get('genres', [])
        type_name = ' / '.join(genres[:3]) if genres else ''
        return {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': pic if pic else self.default_pic,
            'vod_remarks': remark,
            'vod_year': year,
            'vod_area': area,
            'vod_type': type_name,
        }


# ============================================================
# Spider
# ============================================================

class Spider(Spider):

    def getName(self):
        return "Zsbodi"

    def init(self, extend=""):
        self.extend = "" if isinstance(extend, list) else (extend or "")
        self._souju = SoujuAPI(self)
        self._detail_cache = {}
        self._detail_ts = {}

    def _parse_extend(self, extend):
        ext = {}
        if extend:
            if isinstance(extend, dict):
                ext = extend
            elif isinstance(extend, str):
                try:
                    ext = json.loads(extend)
                except Exception:
                    pass
        return ext

    def _map_filter(self, ext):
        """把zsbodi的filter参数映射到搜剧AI参数"""
        result = {}
        # 类型
        genre = ext.get('genre', '') or ext.get('class', '')
        if genre:
            result['genre'] = genre
        # 地区
        region = ext.get('region', '') or ext.get('area', '')
        if region:
            result['region'] = REGION_MAP.get(region, region)
        # 年份
        year = ext.get('year', '')
        if year:
            if year == 'older':
                result['year'] = '2010_2017'
            else:
                result['year'] = year
        # 排序
        sort = ext.get('sort', '') or ext.get('by', '')
        if sort:
            result['sort'] = SORT_MAP.get(sort, sort)
        # 状态
        status = ext.get('status', '')
        if status:
            result['status'] = status
        return result

    # ---------- 首页 ----------

    def homeContent(self, filter):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        data = self._souju.home()
        videos = []
        seen = set()
        for sec in data.get('sections', []):
            for card in sec.get('cards', []):
                vid = card.get('id', '')
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                videos.append(self._souju.parse_card(card))
        return {'list': videos[:30]}

    # ---------- 分类 (全走搜剧AI API) ----------

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(int(pg or 1), 1)
            kind = CATE_MAP.get(str(tid), 'movie')
            ext = self._parse_extend(extend)
            mapped = self._map_filter(ext)

            limit = 30
            data = self._souju.catalog(
                kind=kind,
                page=page,
                limit=limit,
                genre=mapped.get('genre', ''),
                region=mapped.get('region', ''),
                year=mapped.get('year', ''),
                sort=mapped.get('sort', 'newest'),
                status=mapped.get('status', ''),
            )

            cards = data.get('cards', []) or []
            videos = [self._souju.parse_card(c) for c in cards if c.get('id')]
            pag = data.get('pagination', {}) or {}
            total = pag.get('total', 0) or len(videos)
            has_more = pag.get('has_more', False)
            pagecount = page + 1 if has_more else page
            if total and limit:
                pagecount = (total + limit - 1) // limit

            return {
                'list': videos,
                'page': page,
                'pagecount': pagecount,
                'limit': limit,
                'total': total,
            }
        except Exception as e:
            print(f"Error in categoryContent: {e}")
            return {"page": 1, "pagecount": 1, "limit": 30, "total": 0, "list": []}

    # ---------- 搜索 (全走搜剧AI API) ----------

    def searchContent(self, key, quick, pg="1"):
        try:
            page = max(int(pg or 1), 1)
            limit = 30
            data = self._souju.search(key, page=page, limit=limit)
            cards = data.get('cards', []) or []
            videos = [self._souju.parse_card(c) for c in cards if c.get('id')]
            pag = data.get('pagination', {}) or {}
            total = pag.get('total', 0) or len(videos)
            has_more = pag.get('has_more', False)
            pagecount = page + 1 if has_more else page
            if total and limit:
                pagecount = (total + limit - 1) // limit
            return {
                'list': videos,
                'page': page,
                'pagecount': pagecount,
                'limit': limit,
                'total': total,
            }
        except Exception as e:
            print(f"Error in searchContent: {e}")
            return {"list": [], "page": 1, "pagecount": 1, "limit": 30, "total": 0}

    # ---------- 详情 (全走搜剧AI API) ----------

    def detailContent(self, ids):
        if not ids:
            return {'list': []}
        vid = ids[0] if isinstance(ids, list) else ids
        vid = str(vid).strip()

        now = int(time.time())
        cache = self._detail_cache.get(vid)
        if cache and now - self._detail_ts.get(vid, 0) < 600:
            return cache

        try:
            data = self._souju.detail(vid)
            if not data or 'id' not in data:
                return {'list': []}

            title = data.get('title', '') or ''
            pic = data.get('poster_url', '') or self._souju.default_pic
            content = data.get('description', '') or ''
            actors = data.get('actors', [])
            actor = ' / '.join(actors[:20]) if actors else ''
            directors = data.get('directors', [])
            director = ' / '.join(directors[:10]) if directors else ''
            year = str(data.get('year', '')) if data.get('year') else ''
            area = data.get('area', '') or ''
            genres = data.get('genres', [])
            type_name = ' / '.join(genres[:5]) if genres else ''

            play_from = []
            play_url = []

            def extract_episodes(episodes, provider_id=''):
                ep_list = []
                suffix = '@@{0}'.format(provider_id) if provider_id else ''
                for ep in episodes:
                    ep_title = ep.get('title', '') or ''
                    if not ep_title:
                        num = ep.get('number')
                        if num is not None:
                            ep_title = '第{0}集'.format(num)
                        else:
                            ep_title = '播放'
                    token = ep.get('token', '')
                    if not token:
                        continue
                    ep_list.append('{0}${1}{2}'.format(ep_title, token, suffix))
                return ep_list

            episodes = data.get('episodes', [])
            if not episodes:
                ep_data = self._souju.episodes(vid)
                episodes = ep_data.get('episodes', [])

            if episodes:
                first_token = ''
                for ep in episodes:
                    if ep.get('token'):
                        first_token = ep.get('token')
                        break

                valid_lines = []
                if first_token:
                    resolve_data = self._souju.resolve(first_token)
                    line_options = resolve_data.get('line_options', []) or []
                    seen_providers = set()
                    for opt in line_options:
                        if not opt.get('url'):
                            continue
                        pid = opt.get('provider_id')
                        if pid in seen_providers:
                            continue
                        seen_providers.add(pid)
                        valid_lines.append(opt)

                    def line_rank(opt):
                        kind = opt.get('url_kind', '')
                        name = (opt.get('provider_name') or '').lower()
                        if kind == 'resolve_ticket':
                            return 2
                        if '\u8d44\u6e90' in name:
                            return 0
                        return 1

                    valid_lines.sort(key=lambda x: (-line_rank(x), -x.get('preference_weight', 0)))
                    valid_lines = valid_lines[:12]

                if valid_lines:
                    for line in valid_lines:
                        provider_name = line.get('provider_name') or line.get('label') or '\u9ed8\u8ba4\u7ebf\u8def'
                        provider_id = line.get('provider_id') or ''
                        play_from.append(provider_name)
                        ep_list = extract_episodes(episodes, provider_id)
                        if ep_list:
                            play_url.append('#'.join(ep_list))

                if not play_from:
                    play_from.append('\u9ed8\u8ba4\u7ebf\u8def')
                    ep_list = extract_episodes(episodes)
                    if ep_list:
                        play_url.append('#'.join(ep_list))
            else:
                play_from.append('\u9ed8\u8ba4\u7ebf\u8def')
                play_url.append('\u64ad\u653e${0}'.format(vid))

            result = {
                'list': [{
                    'vod_id': vid,
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_content': content,
                    'vod_actor': actor,
                    'vod_director': director,
                    'vod_year': year,
                    'vod_area': area,
                    'vod_type': type_name,
                    'vod_play_from': '$$$'.join(play_from),
                    'vod_play_url': '$$$'.join(play_url),
                }]
            }
            self._detail_cache[vid] = result
            self._detail_ts[vid] = now
            return result
        except Exception as e:
            print(f"Error in detailContent: {e}")
            return {'list': []}

    # ---------- 播放 (全走搜剧AI API) ----------

    def playerContent(self, flag, id, vipFlags):
        try:
            raw_id = id
            if '$' in raw_id:
                raw_id = raw_id.split('$')[-1]
            raw_id = raw_id.strip()
            token = raw_id
            selected_provider = ''
            if '@@' in token:
                token, selected_provider = token.split('@@', 1)
            token = token.strip()
            if not token:
                return {'parse': 1, 'url': id, 'header': self._souju.headers}
            if token.startswith('http') and ('.m3u8' in token or '.mp4' in token):
                return {
                    'parse': 0,
                    'url': token,
                    'header': {
                        'User-Agent': UA,
                        'Referer': SOUJU_HOST + '/',
                    }
                }
            if not token.startswith('YJ-'):
                return {'parse': 1, 'url': token, 'header': self._souju.headers}

            resolve_data = self._souju.resolve(token)
            line_options = resolve_data.get('line_options', [])
            if not line_options:
                return {'parse': 1, 'url': id, 'header': self._souju.headers}

            def is_selected(opt):
                if selected_provider and opt.get('provider_id') == selected_provider:
                    return True
                if selected_provider and opt.get('play_from') == selected_provider:
                    return True
                if flag and opt.get('provider_name') == flag:
                    return True
                return False

            sorted_lines = sorted(
                line_options,
                key=lambda x: (not is_selected(x), -x.get('preference_weight', 0))
            )

            for line in sorted_lines:
                raw_url = line.get('url', '')
                if not raw_url:
                    continue
                url_kind = line.get('url_kind', '')
                if url_kind in ['m3u8', 'mp4', 'hls'] and raw_url.startswith('http'):
                    return {
                        'parse': 0,
                        'url': raw_url,
                        'header': {
                            'User-Agent': UA,
                            'Referer': SOUJU_HOST + '/',
                        }
                    }
                if url_kind == 'resolve_ticket':
                    ticket = raw_url.replace('resolve://', '')
                    if not ticket:
                        continue
                    line_data = self._souju.resolve_line(
                        ticket,
                        line.get('playback_source_id', ''),
                        line.get('provider_id', ''),
                        line.get('play_from', ''),
                    )
                    line_info = line_data.get('line', {})
                    real_url = line_info.get('url', '')
                    if real_url:
                        return {
                            'parse': 0,
                            'url': real_url,
                            'header': {
                                'User-Agent': UA,
                                'Referer': SOUJU_HOST + '/',
                            }
                        }

            return {
                'parse': 1,
                'url': '{0}/yj/{1}'.format(SOUJU_HOST, token.replace('YJ-', '')),
                'header': self._souju.headers
            }
        except Exception as e:
            print(f"Error in playerContent: {e}")
            return {
                'parse': 1,
                'url': id,
                'header': self._souju.headers
            }

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    def destroy(self):
        pass

    def close(self):
        self.destroy()
