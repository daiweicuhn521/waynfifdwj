# -*- coding: utf-8 -*-
"""绿果短剧 (www.lvguodj.com) TVBox / CatVod Python 蜘蛛。

已实测打通的链路：

    首页推荐 GET  /api/v1/feed/home?limit=
    榜单排行 GET  /api/v1/rankings/{hot|new|fav}?limit=
    分类筛选 GET  /api/v1/dramas?tag_ids=&sort=&within_days=&page=&limit=
    筛选维度 GET  /api/v1/dramas/filters        （一级体裁 + 二级主题/设定/背景/受众）
    剧集详情 GET  /api/v1/dramas/{id}
    剧集列表 GET  /api/v1/dramas/{id}/episodes  （详情内联的集号是乱序，以此为准）
    关键词搜 GET  /api/v1/dramas?q=&page=&limit=
    播放地址 GET  /api/v1/dramas/{id}/episodes/{ep}/play-url

播放前置条件：先 POST /api/v1/age/confirm 换取年龄令牌，随 X-Age-Token 头提交；
令牌有效期 30 天、播放地址有效期 2 小时，两者均缓存复用，避免重复请求。

提速要点见文件末尾 SPEED_NOTES。
"""

import json
import os
import re
import sys
import time
import uuid
from urllib.parse import urlencode

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from base.spider import Spider  # noqa: E402

try:
    import requests
except ImportError:
    requests = None


class Spider(Spider):
    """与基类同名是 CatVod 生态约定：用子类覆盖导入进来的基类符号。

    继承在类定义时已完成，方法内零参 super() 仍指向基类；
    但切勿在方法里按名调用 ``Spider.xxx``，那会命中本类并递归。
    """

    HOST = 'https://www.lvguodj.com'
    API = HOST + '/api/v1'
    UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    LIMIT = 30
    TIMEOUT = (4, 10)          # (连接, 读取) 秒，快失败快重试
    RETRY = 1

    # 缓存有效期（秒）
    TTL_AGE = 25 * 24 * 3600   # 年龄令牌实际 30 天，留 5 天余量
    TTL_PLAY = 2 * 3600 - 300  # 播放地址实际 7200 秒，提前 5 分钟过期
    TTL_FILTER = 6 * 3600      # 筛选维度
    TTL_HOME = 300             # 首页推荐

    FLAG_HD = '绿果高清'
    FLAG_FAST = '绿果极速'

    # 兜底体裁：filters 接口不可用时仍能出一级分类
    FALLBACK_GENRES = (
        {'slug': 'tag-82617', 'name': '漫剧', 'tag_id': 8},
        {'slug': 'mochuang', 'name': '魔创', 'tag_id': 3586},
        {'slug': 'mogai', 'name': '魔改', 'tag_id': 3717},
        {'slug': 'reye', 'name': '热夜', 'tag_id': 3589},
    )

    def init(self, extend=""):
        self.host = self.HOST
        self.api = self.API
        self.headers = {
            'User-Agent': self.UA,
            'Accept': 'application/json, text/plain, */*',
            'Origin': self.HOST,
            'Referer': self.HOST + '/',
        }
        self.device_id = str(uuid.uuid4())
        self.debug = False

        self._session = self._build_session()
        self._age = {'token': '', 'expire': 0}
        self._play_cache = {}
        self._filters = {'data': None, 'expire': 0}
        self._home_cache = {'list': None, 'expire': 0}

    def getName(self):
        return "绿果短剧"

    def isVideoFormat(self, url):
        return bool(url and ('.m3u8' in url or '.mp4' in url))

    def manualVideoCheck(self):
        pass

    def destroy(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass

    # ---------- 首页分类 + 二级筛选 ----------
    def homeContent(self, filter):
        """一级分类放 class，二级筛选按 type_id 逐个定制。

        二级选项依据 tag 的 parent_id 归属到对应体裁，
        所以在一级「魔创」下只会看到魔创自己的主题/设定/背景。
        """
        fdata = self._load_filters()
        genres = self._genres(fdata)
        classes = [
            {'type_name': '热播榜', 'type_id': 'hot'},
            {'type_name': '新剧榜', 'type_id': 'new'},
            {'type_name': '收藏榜', 'type_id': 'fav'},
        ]
        classes += [{'type_name': g['name'], 'type_id': g['slug']} for g in genres]
        classes.append({'type_name': '全部', 'type_id': 'all'})

        filters = {}
        for g in genres:
            filters[g['slug']] = self._build_filters(fdata, g['tag_id'])
        filters['all'] = self._build_filters(fdata, None)
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        cached = self._home_cache
        if cached['list'] is not None and cached['expire'] > time.time():
            return {'list': cached['list']}

        data = self._get_json('/feed/home', {'limit': self.LIMIT, 'mode': 'hot'})
        rows = data.get('data') or []
        vods = []
        for row in rows:
            drama = row.get('drama') or row
            vod = self._parse_vod(drama)
            if vod:
                vods.append(vod)
        if not vods:
            vods = self._dramas({})

        cached['list'] = vods
        cached['expire'] = time.time() + self.TTL_HOME
        return {'list': vods}

    # ---------- 分类列表 ----------
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        result = {
            'list': [], 'page': pg, 'pagecount': 1,
            'limit': self.LIMIT, 'total': 0,
        }
        tid = str(tid or 'all')

        if tid in ('hot', 'new', 'fav'):
            data = self._get_json('/rankings/%s' % tid, {'limit': self.LIMIT})
            items = (data.get('data') or {}).get('items') or []
            result['list'] = self._parse_vods(items)
            result['total'] = len(result['list'])
            result['pagecount'] = 1
            return result

        params = {'page': pg, 'limit': self.LIMIT, 'sort': 'new'}
        tag_ids = []
        if tid != 'all':
            gid = self._genre_tag_id(tid)
            if gid:
                tag_ids.append(gid)
        tag_ids += self._extend_tag_ids(extend)

        sort = (extend or {}).get('sort')
        if sort in ('new', 'hot', 'fav'):
            params['sort'] = sort
        within = (extend or {}).get('within')
        if str(within) in ('7', '14', '30', '90'):
            params['within_days'] = str(within)
        if tag_ids:
            params['tag_ids'] = ','.join(str(i) for i in tag_ids)

        data = self._get_json('/dramas', params)
        total = int(data.get('total') or 0)
        result['list'] = self._parse_vods(data.get('data') or [])
        result['total'] = total
        result['page'] = int(data.get('page') or pg)
        result['limit'] = int(data.get('limit') or self.LIMIT)
        result['pagecount'] = max(1, (total + result['limit'] - 1) // result['limit'])
        return result

    # ---------- 详情（集数） ----------
    def detailContent(self, ids):
        vid = str((ids or [''])[0]).strip()
        if not vid:
            return {'list': []}
        data = self._get_json('/dramas/%s' % vid)
        drama = data.get('data') or {}
        if not drama.get('id'):
            return {'list': []}

        episodes = self._episodes(vid, drama.get('episodes'))

        did = drama['id']
        play_urls = []
        for ep in episodes:
            eid = ep.get('id')
            if not eid:
                continue
            play_urls.append('%s$%s-%s'
                             % (self._ep_title(ep), did, eid))

        play_str = '#'.join(play_urls)
        vod = {
            'vod_id': str(did),
            'vod_name': drama.get('title') or '',
            'vod_pic': drama.get('cover_url') or '',
            'vod_remarks': self._remarks(drama, len(play_urls)),
            'type_name': drama.get('category') or '',
            'vod_year': (drama.get('created_at') or '')[:10],
            'vod_area': '',
            'vod_actor': drama.get('cast_names') or '',
            'vod_director': drama.get('creator_nickname') or '',
            'vod_content': drama.get('description') or '',
            # 两个播放源共用同一套 id，由 playerContent 按 flag 切换码率
            'vod_play_from': '%s$$$%s' % (self.FLAG_HD, self.FLAG_FAST),
            'vod_play_url': '%s$$$%s' % (play_str, play_str),
        }
        return {'list': [vod]}

    # ---------- 集数处理 ----------
    def _episodes(self, vid, inline):
        """取一份集号严格升序的剧集列表。

        详情接口内联的 episodes 是按 episode id 升序返回的，集号是乱的
        （100 集的剧会排成 88, 96, 18, 2, 30 ...）；独立接口 /episodes
        则按 episode_number 排好序。所以：
          * 内联为空或集号非升序 → 拉独立接口；
          * 内联已经是升序 → 直接复用，省掉一次请求；
          * 独立接口也失败 → 退回内联，但仍强制排序，保证顺序正确。
        """
        inline = list(inline or [])
        if inline and self._is_ascending(inline):
            return self._sort_episodes(inline)

        sub = self._get_json('/dramas/%s/episodes' % vid)
        rows = sub.get('data') or []
        if rows:
            return self._sort_episodes(rows)
        return self._sort_episodes(inline)

    @staticmethod
    def _is_ascending(episodes):
        nums = []
        for ep in episodes:
            num = ep.get('episode_number')
            try:
                nums.append(int(num))
            except (TypeError, ValueError):
                return False
        return all(a <= b for a, b in zip(nums, nums[1:]))

    @staticmethod
    def _sort_episodes(episodes):
        """按集号升序去重；集号缺失时退回标题里的数字，再退回 id。"""
        seen = {}
        for idx, ep in enumerate(episodes or []):
            eid = ep.get('id')
            if not eid:
                continue
            num = ep.get('episode_number')
            try:
                num = int(num)
            except (TypeError, ValueError):
                num = None
            if num is None:
                match = re.search(r'\d+', str(ep.get('title') or ''))
                num = int(match.group()) if match else 10 ** 7
            key = str(eid)
            if key not in seen or num < seen[key][0]:
                seen[key] = (num, idx, ep)
        return [item[2] for item in sorted(seen.values(), key=lambda x: (x[0], x[1]))]

    @staticmethod
    def _ep_title(ep):
        """集标题统一带集号前缀。

        相当一部分剧的 episode.title 是每集副标题（如「母狗叫爸爸」）
        不含集号，列表里看不出先后，因此统一拼成「第N集 副标题」。
        """
        num = ep.get('episode_number')
        label = '第%s集' % num if num else ''
        raw = (ep.get('title') or '').strip()
        if not label:
            return raw
        if not raw or label in raw:
            return raw or label
        return '%s %s' % (label, raw)

    @staticmethod
    def _remarks(drama, playable):
        """集数备注以「可播集数」为准，避免标注 15 集却只放出 1 集。"""
        total = drama.get('total_episodes')
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = 0
        if total and playable < total:
            return '更新至%d集' % playable
        return '共%d集' % playable

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg="1"):
        pg = int(pg or 1)
        result = {
            'list': [], 'page': pg, 'pagecount': 1,
            'limit': self.LIMIT, 'total': 0,
        }
        key = (key or '').strip()
        if not key:
            return result

        data = self._get_json(
            '/dramas', {'q': key, 'page': pg, 'limit': self.LIMIT}
        )
        total = int(data.get('total') or 0)
        result['list'] = self._parse_vods(data.get('data') or [])
        result['total'] = total
        result['page'] = int(data.get('page') or pg)
        result['limit'] = int(data.get('limit') or self.LIMIT)
        result['pagecount'] = max(1, (total + result['limit'] - 1) // result['limit'])
        return result

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        try:
            did, _, eid = str(id).partition('-')
            url = self._play_url(did, eid)
            if not url:
                return {'parse': 0, 'url': '', 'msg': '无播放地址'}

            # 极速源直取 480p（1.6 Mbps），起播快；高清源给 master 自适应
            if flag == self.FLAG_FAST:
                url = self._downgrade(url)

            header = {
                'User-Agent': self.UA,
                'Referer': self.HOST + '/',
                'Origin': self.HOST,
            }
            return {'parse': 0, 'url': url, 'header': header}
        except Exception as e:
            self._log('playerContent %s: %s' % (id, e))
            return {'parse': 0, 'url': '', 'msg': str(e)}

    # ---------- 筛选维度 ----------
    def _load_filters(self):
        """拉取 /dramas/filters，带 TTL 缓存；失败返回 None 由兜底接管。"""
        cache = self._filters
        if cache['data'] and cache['expire'] > time.time():
            return cache['data']
        data = self._get_json('/dramas/filters')
        dims = (data.get('data') or {}).get('dimensions')
        if not dims:
            self._log('filters 拉取失败，走兜底分类')
            return None
        cache['data'] = data['data']
        cache['expire'] = time.time() + self.TTL_FILTER
        return cache['data']

    def _genres(self, fdata):
        """一级体裁：优先来自 filters 的 genre 维度，失败用硬编码兜底。"""
        out = []
        for dim in (fdata or {}).get('dimensions') or []:
            if dim.get('code') == 'genre':
                for tag in dim.get('tags') or []:
                    if tag.get('slug') and tag.get('id'):
                        out.append({
                            'slug': tag['slug'],
                            'name': tag.get('name') or tag['slug'],
                            'tag_id': tag['id'],
                        })
        return out or [dict(g) for g in self.FALLBACK_GENRES]

    def _genre_tag_id(self, slug):
        for g in self._genres(self._filters['data']):
            if g['slug'] == slug:
                return g['tag_id']
        for g in self.FALLBACK_GENRES:
            if g['slug'] == slug:
                return g['tag_id']
        return None

    def _build_filters(self, fdata, genre_id):
        """把维度拼成 CatVod 筛选组：体裁内只保留归属自己的二级 tag。"""
        fdata = fdata or {}
        groups = []
        for dim in fdata.get('dimensions') or []:
            code = dim.get('code')
            if code == 'genre':
                continue
            values = [{'n': '全部', 'v': ''}]
            for tag in dim.get('tags') or []:
                parent = tag.get('parent_id')
                if genre_id and parent and int(parent) != int(genre_id):
                    continue
                if tag.get('id'):
                    values.append({
                        'n': tag.get('name') or str(tag['id']),
                        'v': str(tag['id']),
                    })
            if len(values) > 1:
                groups.append({
                    'key': code,
                    'name': dim.get('name') or code,
                    'value': values,
                })

        sorts = fdata.get('sorts')
        if sorts:
            groups.append({
                'key': 'sort',
                'name': '排序',
                'value': [{'n': '默认', 'v': ''}] + [
                    {'n': s.get('name') or s.get('code'), 'v': s.get('code')}
                    for s in sorts if s.get('code')
                ],
            })
        within = fdata.get('within')
        if within:
            groups.append({
                'key': 'within',
                'name': '上新',
                'value': [{'n': '不限', 'v': ''}] + [
                    {'n': w.get('name') or '%s天' % w.get('days'),
                     'v': str(w.get('code') or w.get('days'))}
                    for w in within
                ],
            })
        if not groups:
            groups = [
                {'key': 'sort', 'name': '排序', 'value': [
                    {'n': '默认', 'v': ''},
                    {'n': '最新上架', 'v': 'new'},
                    {'n': '最高热度', 'v': 'hot'},
                    {'n': '最高收藏', 'v': 'fav'},
                ]},
                {'key': 'within', 'name': '上新', 'value': [
                    {'n': '不限', 'v': ''},
                    {'n': '7天内上新', 'v': '7'},
                    {'n': '30天内上新', 'v': '30'},
                ]},
            ]
        return groups

    def _extend_tag_ids(self, extend):
        """把二级筛选项（tag id 字符串）收集成 tag_ids 列表。"""
        ids = []
        for key, val in (extend or {}).items():
            if key in ('sort', 'within') or not val:
                continue
            for part in str(val).split(','):
                part = part.strip()
                if part.isdigit():
                    ids.append(int(part))
        return ids

    # ---------- 播放地址与年龄令牌 ----------
    def _age_token(self):
        if self._age['token'] and self._age['expire'] > time.time():
            return self._age['token']
        data = self._post_json('/age/confirm', {})
        info = data.get('data') or {}
        token = info.get('token') or ''
        if token:
            self._age['token'] = token
            self._age['expire'] = time.time() + min(
                self.TTL_AGE, int(info.get('expires_in') or self.TTL_AGE)
            )
        return token

    def _play_url(self, drama_id, episode_id):
        if not drama_id or not episode_id:
            return ''
        key = str(episode_id)
        hit = self._play_cache.get(key)
        if hit and hit[1] > time.time():
            return hit[0]

        token = self._age_token()
        headers = {'X-Age-Token': token} if token else None
        path = '/dramas/%s/episodes/%s/play-url' % (drama_id, episode_id)
        data = self._get_json(path, headers=headers)
        url = (data.get('data') or {}).get('url') or ''
        if not url:
            code = data.get('error') or data.get('error_code') or '未知错误'
            self._log('play-url 失败 %s: %s' % (path, code))
            return ''
        self._play_cache[key] = (url, time.time() + self.TTL_PLAY)
        return url

    @staticmethod
    def _downgrade(url):
        """master.m3u8 → 480p/index.m3u8；结构不符时原样返回。"""
        if 'master.m3u8' in url:
            return url.replace('master.m3u8', '480p/index.m3u8')
        return url

    # ---------- 数据解析 ----------
    def _parse_vods(self, items):
        vods = []
        for item in items or []:
            vod = self._parse_vod(item)
            if vod:
                vods.append(vod)
        return vods

    @staticmethod
    def _parse_vod(item):
        if not item or not item.get('id'):
            return None
        remarks = ''
        total = item.get('total_episodes')
        if total:
            done = item.get('episode_count')
            remarks = ('全%d集' % total) if done and done >= total \
                else ('更新至%d集' % (done or total))
        views = item.get('total_views')
        if views:
            remarks = ('%s · %d次观看' % (remarks, views)) if remarks \
                else ('%d次观看' % views)
        return {
            'vod_id': str(item['id']),
            'vod_name': item.get('title') or '',
            'vod_pic': item.get('cover_url') or '',
            'vod_remarks': remarks,
            'vod_year': (item.get('created_at') or '')[:10],
        }

    def _dramas(self, params):
        data = self._get_json('/dramas', params or {'limit': self.LIMIT})
        return self._parse_vods(data.get('data') or [])

    # ---------- 传输层 ----------
    def _build_session(self):
        """requests 可用时建连接池，复用 TCP/TLS 握手。"""
        if requests is None:
            return None
        try:
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=8, pool_maxsize=16, max_retries=0
            )
            session.mount('https://', adapter)
            session.mount('http://', adapter)
            session.headers.update({'User-Agent': self.UA})
            return session
        except Exception:
            return None

    def _get_json(self, path, params=None, headers=None, retry=None):
        url = self.api + path
        if params:
            url += '?' + urlencode(params, encoding='utf-8')
        retry = self.RETRY if retry is None else retry
        hdrs = dict(self.headers)
        if headers:
            hdrs.update(headers)
        for attempt in range(retry + 1):
            try:
                return self._json(self._fetch(url, hdrs))
            except Exception as e:
                if attempt >= retry:
                    self._log('GET 失败 %s: %s' % (url, e))
                else:
                    time.sleep(0.3)
        return {}

    def _post_json(self, path, body):
        url = self.api + path
        hdrs = dict(self.headers)
        hdrs['Content-Type'] = 'application/json'
        payload = json.dumps(body or {}).encode('utf-8')
        try:
            return self._json(self._post(url, hdrs, payload))
        except Exception as e:
            self._log('POST 失败 %s: %s' % (url, e))
        return {}

    def _fetch(self, url, headers):
        if self._session is not None:
            return self._session.get(url, headers=headers, timeout=self.TIMEOUT)
        return self._fallback(url, headers, None)

    def _post(self, url, headers, payload):
        if self._session is not None:
            return self._session.post(
                url, data=payload, headers=headers, timeout=self.TIMEOUT
            )
        return self._fallback(url, headers, payload)

    def _fallback(self, url, headers, payload):
        """无 requests 时降级：优先基类 fetch，其次标准库 urllib。"""
        fetch = getattr(self, 'fetch', None)
        if callable(fetch):
            try:
                if payload is None:
                    return fetch(url, headers=headers)
                return fetch(url, headers=headers, data=payload, method='POST')
            except TypeError:
                pass
        from urllib.request import Request, urlopen
        req = Request(url, data=payload, headers=headers,
                      method='POST' if payload is not None else 'GET')
        return urlopen(req, timeout=self.TIMEOUT[1]).read().decode('utf-8', 'ignore')

    @staticmethod
    def _json(resp):
        """把 str / bytes / 响应对象统一转成 dict。"""
        if isinstance(resp, dict):
            return resp
        if isinstance(resp, (bytes, bytearray)):
            resp = bytes(resp).decode('utf-8', 'ignore')
        if not isinstance(resp, str):
            text = getattr(resp, 'text', None)
            if text is None:
                text = getattr(resp, 'content', b'').decode('utf-8', 'ignore')
            resp = text
        try:
            return json.loads(resp)
        except Exception:
            return {}

    def _log(self, msg):
        if self.debug:
            print('[绿果短剧] %s' % msg)


# SPEED_NOTES
# 1. 连接复用：requests.Session + HTTPAdapter 连接池，避免每页重建 TLS。
# 2. 令牌缓存：年龄令牌 30 天、播放地址 2 小时，命中缓存时播放零额外请求。
# 3. 维度缓存：/dramas/filters 结果缓存 6 小时，筛选页不再每次拉取。
# 4. 首页缓存：feed/home 缓存 5 分钟，来回切页不重复请求。
# 5. 详情按需请求：内联 episodes 已是集号升序就直接用（省一次请求），
#    否则再拉 /dramas/{id}/episodes —— 内联是按 episode id 排序的，
#    100 集的剧会乱排成 88, 96, 18, 2, 30 ...，不能直接用。
# 6. 极速源：480p/index.m3u8（1.6 Mbps）与 master（最高 3.1 Mbps）并存，按需选。
# 7. 快失败：连接 4 秒 / 读取 10 秒超时 + 1 次重试，弱网下不长时间空转。
