# -*- coding: utf-8 -*-
"""
绮梦短剧 (shorttv.online) - TVBox Python 爬虫源 (v5 代理优化版)

本次重点修复:
  ★ 保证全集: 详情页多端点合并 (API 主/备 + HTML RSC), 取并集去重
  ★ 代理分流: API/HTML 走代理加速, 播放 CDN 走直连 (返回给 TVBox 自己处理)
  ★ 播放提速: 播放地址 4 分钟缓存, 观看页 RSC 快速提取
  ★ 超时优化: 主请求 12s, 探测请求 4s

已确认 API:
  域名: https://production.nodenear.shorttv.online
  路径: /api/v3/public/...
"""

import sys
import re
import json
import time
import threading
from urllib.parse import quote, unquote, urljoin

sys.path.append('..')

try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    _BaseSpider = object


class Spider(_BaseSpider):

    HOST     = 'https://shorttv.online'
    API_HOST = 'https://production.nodenear.shorttv.online'
    API      = API_HOST + '/api/v3/public'

    # ============================================================
    # ★★★ 代理配置
    # ============================================================
    # 配了走代理, 留空直连
    PROXY = 'http://nas6688.f3322.net:7896'

    UA = ('Mozilla/5.0 (Linux; Android 13; Pixel 7) '
          'AppleWebKit/537.36 (KHTML, like Gecko) '
          'Chrome/120.0.0.0 Mobile Safari/537.36')

    HEADERS = {
        'User-Agent': UA,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://shorttv.online/',
        'Origin':  'https://shorttv.online',
    }

    CATEGORIES = [
        {'id': 'home',        'name': '首页推荐', 'sort': 'hot'},
        {'id': 'rank_hot',    'name': '热播榜',   'sort': 'hot'},
        {'id': 'rank_new',    'name': '新剧榜',   'sort': 'new'},
        {'id': 'rank_follow', 'name': '追剧榜',   'sort': 'follow'},
        {'id': 'updates',     'name': '今日更新', 'sort': 'update'},
    ]

    # ---- 超时参数 ----
    TIMEOUT       = 12    # 主请求
    TIMEOUT_PROBE = 4     # 探测/次要请求

    # ---- 缓存参数 ----
    CACHE_TTL    = 300    # 列表/详情 5 分钟
    PLAY_TTL     = 240    # 播放地址 4 分钟
    CACHE_MAX    = 300

    DEBUG = True

    _CACHE       = {}
    _PLAY_CACHE  = {}
    _LOCK        = threading.Lock()
    _PLAY_LOCK   = threading.Lock()

    def _cget(self, key):
        with self._LOCK:
            item = self._CACHE.get(key)
            if item and time.time() - item[1] < self.CACHE_TTL:
                return item[0]
            if item:
                del self._CACHE[key]
        return None

    def _cset(self, key, value):
        with self._LOCK:
            if len(self._CACHE) >= self.CACHE_MAX:
                items = sorted(self._CACHE.items(), key=lambda x: x[1][1])
                for k, _ in items[:self.CACHE_MAX // 5]:
                    del self._CACHE[k]
            self._CACHE[key] = (value, time.time())

    def _play_get(self, key):
        with self._PLAY_LOCK:
            item = self._PLAY_CACHE.get(key)
            if item and time.time() - item[1] < self.PLAY_TTL:
                return item[0]
            if item:
                del self._PLAY_CACHE[key]
        return None

    def _play_set(self, key, value):
        with self._PLAY_LOCK:
            if len(self._PLAY_CACHE) >= 500:
                items = sorted(self._PLAY_CACHE.items(), key=lambda x: x[1][1])
                for k, _ in items[:100]:
                    del self._PLAY_CACHE[k]
            self._PLAY_CACHE[key] = (value, time.time())

    # ============================================================
    def getName(self):
        return '绮梦短剧'

    def init(self, cfg=''):
        self.session = None
        if _requests is not None:
            self.session = _requests.Session()
            self.session.headers.update(self.HEADERS)
            self.session.verify = False

            # ★★★ 应用代理 (API/HTML 走代理, TVBox 视频播放器自己处理 CDN)
            if self.PROXY:
                self.session.proxies = {
                    'http':  self.PROXY,
                    'https': self.PROXY,
                }
                if self.DEBUG:
                    print('[Init] API/HTML 走代理: %s' % self.PROXY)
            else:
                if self.DEBUG:
                    print('[Init] 直连模式')

            adapter = _requests.adapters.HTTPAdapter(
                pool_connections=30, pool_maxsize=30, max_retries=0)
            self.session.mount('https://', adapter)
            self.session.mount('http://', adapter)
            try:
                import urllib3
                urllib3.disable_warnings()
            except Exception:
                pass
        return self

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    # ============================================================
    # 网络
    # ============================================================
    def _get(self, url, params=None, timeout=None):
        if not url or self.session is None:
            return None
        t = timeout or self.TIMEOUT
        try:
            r = self.session.get(url, params=params, timeout=t)
            if r.status_code == 429:
                time.sleep(0.8)
                return None
            if r.status_code >= 400:
                if self.DEBUG:
                    print('[HTTP %d] %s' % (r.status_code, url[:120]))
                return None
            return r
        except Exception as e:
            if self.DEBUG:
                print('[GET fail] %s -> %s' % (url[:100], e))
            return None

    def _get_json(self, url, params=None, cache_key=None, timeout=None):
        if cache_key:
            cached = self._cget(cache_key)
            if cached is not None:
                return cached
        r = self._get(url, params=params, timeout=timeout)
        if not r:
            return None
        try:
            data = r.json()
        except Exception:
            return None
        if cache_key and data:
            self._cset(cache_key, data)
        return data

    def _get_text(self, url, cache_key=None, timeout=None):
        if cache_key:
            cached = self._cget(cache_key)
            if cached is not None:
                return cached
        r = self._get(url, timeout=timeout)
        if not r:
            return ''
        try:
            r.encoding = 'utf-8'
            txt = r.text
        except Exception:
            return ''
        if cache_key and txt:
            self._cset(cache_key, txt)
        return txt

    # ============================================================
    # JSON 遍历
    # ============================================================
    def _iter_dicts(self, obj, depth=0):
        if depth > 10:
            return
        if isinstance(obj, dict):
            yield obj
            for v in obj.values():
                for d in self._iter_dicts(v, depth + 1):
                    yield d
        elif isinstance(obj, list):
            for v in obj:
                for d in self._iter_dicts(v, depth + 1):
                    yield d

    def _is_drama(self, obj):
        if not isinstance(obj, dict):
            return False
        if obj.get('drama_id') or obj.get('dramaId'):
            return True
        if (obj.get('poster_url') or obj.get('posterUrl') or obj.get('cover')) and \
           (obj.get('title') or obj.get('drama_name') or obj.get('name')):
            return True
        return False

    def _norm_pic(self, pic):
        if not pic:
            return ''
        pic = str(pic).strip()
        if pic.startswith('//'):
            return 'https:' + pic
        if pic.startswith('http'):
            return pic
        if pic.startswith('/'):
            return self.HOST + pic
        return pic

    def _norm_drama(self, obj):
        vid = str(obj.get('drama_id') or obj.get('dramaId') or obj.get('id') or '')
        title = (obj.get('title') or obj.get('drama_name') or
                 obj.get('dramaName') or obj.get('name') or '')
        poster = self._norm_pic(
            obj.get('poster_url') or obj.get('posterUrl') or
            obj.get('cover') or obj.get('poster') or '')
        remark = ''
        ep = (obj.get('episode_count') or obj.get('episodeCount') or
              obj.get('total_episodes') or obj.get('episodes_count'))
        if ep:
            remark = '共%s集' % ep
        return {
            'vod_id': 'shorttv://' + vid,
            'vod_name': str(title),
            'vod_pic': poster,
            'vod_remarks': str(remark),
        }

    def _extract_dramas(self, data):
        if not data:
            return []
        out, seen = [], set()
        for d in self._iter_dicts(data):
            if self._is_drama(d):
                vid = str(d.get('drama_id') or d.get('dramaId') or d.get('id') or '')
                if vid and vid not in seen:
                    seen.add(vid)
                    out.append(self._norm_drama(d))
        return out

    # ============================================================
    # 列表 (主端点优先)
    # ============================================================
    def _fetch_list(self, sort='hot', limit=30, page=1):
        ckey = 'list:%s:%s:%s' % (sort, limit, page)
        cached = self._cget(ckey)
        if cached is not None:
            return cached

        params = {'limit': limit, 'sort': sort, 'surface': 'webpc'}
        if page > 1:
            params['page'] = page

        items = []

        # 主端点: catalog/dramas
        data = self._get_json(self.API + '/catalog/dramas', params=params)
        items = self._extract_dramas(data)

        # 备端点: dramas
        if not items:
            data = self._get_json(self.API + '/dramas', params=params)
            items = self._extract_dramas(data)

        # 兜底: feed/initial
        if not items:
            for k in ('sort', 'board'):
                p2 = {'limit': limit, 'surface': 'webpc', k: sort}
                data = self._get_json(self.API + '/feed/initial', params=p2)
                items = self._extract_dramas(data)
                if items:
                    break

        self._cset(ckey, items)
        return items

    # ============================================================
    # TVBox 接口
    # ============================================================
    def homeContent(self, filter=False):
        return {
            'class': [{'type_id': c['id'], 'type_name': c['name']}
                      for c in self.CATEGORIES]
        }

    def homeVideoContent(self):
        return {'list': self._fetch_list(sort='hot', limit=30)}

    def categoryContent(self, tid, pg, filter, extend):
        page = max(1, int(pg or 1))
        ckey = 'cat:%s:%s' % (tid, page)
        cached = self._cget(ckey)
        if cached is not None:
            return cached

        cat = next((c for c in self.CATEGORIES if c['id'] == tid), None)
        if not cat:
            return {'list': [], 'page': page, 'pagecount': 1, 'limit': 0, 'total': 0}

        items = self._fetch_list(sort=cat.get('sort', 'hot'), limit=30, page=page)

        result = {
            'list': items,
            'page': page,
            'pagecount': 9999 if items else page,
            'limit': 30,
            'total': 999999 if items else 0,
        }
        self._cset(ckey, result)
        return result

    # ============================================================
    # 详情 ★ 核心: 多端点合并, 保证全集
    # ============================================================
    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        raw = str(ids[0]).strip()
        vid = raw.replace('shorttv://', '') if raw.startswith('shorttv://') else raw
        if not vid:
            return {'list': []}

        ckey = 'detail:' + vid
        cached = self._cget(ckey)
        if cached is not None:
            return cached

        # 合并容器: 收集所有来源的数据
        merged = {
            'name': '', 'pic': '', 'content': '', 'ep_count': 0,
            'episodes': {},   # ep_no -> play_url (可能为空, 播放时再取)
        }

        # 来源 1: /catalog/dramas/{id}/detail
        data = self._get_json(
            self.API + '/catalog/dramas/%s/detail' % vid,
            params={'surface': 'webpc'})
        if data:
            self._merge_detail_json(merged, data, vid)

        # 来源 2: /catalog/dramas/{id}
        if not merged['name'] or not merged['episodes']:
            data = self._get_json(
                self.API + '/catalog/dramas/%s' % vid,
                params={'surface': 'webpc'})
            if data:
                self._merge_detail_json(merged, data, vid)

        # 来源 3: /dramas/batch?ids=xxx
        if not merged['name'] or not merged['episodes']:
            data = self._get_json(
                self.API + '/dramas/batch',
                params={'ids': vid, 'surface': 'webpc'})
            if data:
                self._merge_detail_json(merged, data, vid)

        # 来源 4: HTML 兜底 (RSC)
        if not merged['name'] or not merged['episodes']:
            html = self._get_text(self.HOST + '/webpc/d/' + vid,
                                   timeout=self.TIMEOUT_PROBE + 3)
            if html:
                self._merge_detail_html(merged, html, vid)

        # 构造最终结果
        if not merged['name']:
            result = {'list': []}
            self._cset(ckey, result)
            return result

        detail = self._make_detail(vid, merged)
        result = {'list': [detail]}
        self._cset(ckey, result)

        if self.DEBUG:
            print('[Detail] vid=%s name=%s eps=%d' %
                  (vid, merged['name'], len(merged['episodes'])))

        return result

    def _merge_detail_json(self, merged, data, vid):
        """从 JSON 结构中提取并合并剧集信息"""
        for obj in self._iter_dicts(data):
            obj_id = str(obj.get('drama_id') or obj.get('dramaId') or obj.get('id') or '')
            # 匹配当前剧集 或 尚未获取到元数据
            if obj_id == vid or not merged['name']:
                merged['name'] = merged['name'] or str(
                    obj.get('title') or obj.get('drama_name') or
                    obj.get('dramaName') or obj.get('name') or '')
                merged['pic'] = merged['pic'] or self._norm_pic(
                    obj.get('poster_url') or obj.get('posterUrl') or
                    obj.get('cover') or '')
                merged['content'] = merged['content'] or str(
                    obj.get('description') or obj.get('synopsis') or
                    obj.get('summary') or '')
                ec = (obj.get('episode_count') or obj.get('episodeCount') or
                      obj.get('total_episodes') or 0)
                if ec and not merged['ep_count']:
                    try:
                        merged['ep_count'] = int(ec)
                    except Exception:
                        pass

            # 收集 episodes
            eps = (obj.get('episodes') or obj.get('episode_list') or
                   obj.get('episodeList'))
            if isinstance(eps, list):
                for e in eps:
                    if not isinstance(e, dict):
                        continue
                    ep_no = (e.get('episode_no') or e.get('episodeNo') or
                             e.get('index') or e.get('sort') or e.get('number') or 0)
                    if not ep_no:
                        continue
                    try:
                        ep_no = int(ep_no)
                    except Exception:
                        continue
                    # 尝试提取该集的播放地址
                    play = self._find_m3u8_in_obj(e)
                    if ep_no not in merged['episodes'] or not merged['episodes'][ep_no]:
                        merged['episodes'][ep_no] = play or ''

    def _merge_detail_html(self, merged, html, vid):
        """从 HTML RSC 中提取并合并剧集信息"""
        rsc = self._extract_rsc(html)
        text = rsc + '\n' + html
        for obj in self._safe_load_all(text):
            obj_id = str(obj.get('drama_id') or obj.get('dramaId') or obj.get('id') or '')
            if obj_id == vid or not merged['name']:
                merged['name'] = merged['name'] or str(
                    obj.get('title') or obj.get('drama_name') or
                    obj.get('dramaName') or obj.get('name') or '')
                merged['pic'] = merged['pic'] or self._norm_pic(
                    obj.get('poster_url') or obj.get('posterUrl') or
                    obj.get('cover') or '')
                merged['content'] = merged['content'] or str(
                    obj.get('description') or obj.get('synopsis') or
                    obj.get('summary') or '')
                ec = (obj.get('episode_count') or obj.get('episodeCount') or
                      obj.get('total_episodes') or 0)
                if ec and not merged['ep_count']:
                    try:
                        merged['ep_count'] = int(ec)
                    except Exception:
                        pass

            eps = (obj.get('episodes') or obj.get('episode_list') or
                   obj.get('episodeList'))
            if isinstance(eps, list):
                for e in eps:
                    if not isinstance(e, dict):
                        continue
                    ep_no = (e.get('episode_no') or e.get('episodeNo') or
                             e.get('index') or e.get('sort') or e.get('number') or 0)
                    if not ep_no:
                        continue
                    try:
                        ep_no = int(ep_no)
                    except Exception:
                        continue
                    play = self._find_m3u8_in_obj(e)
                    if ep_no not in merged['episodes'] or not merged['episodes'][ep_no]:
                        merged['episodes'][ep_no] = play or ''

    def _make_detail(self, vid, merged):
        """组装最终详情 (★ 保证全集)"""
        # 确定集数: 优先用 episodes 字典, 若为空则用 ep_count 生成序号
        ep_nos = set(merged['episodes'].keys())
        if not ep_nos and merged['ep_count']:
            ep_nos = set(range(1, merged['ep_count'] + 1))
        if not ep_nos:
            ep_nos = {1}

        # 取并集的最大集数 (防止 ep_count 和 episodes 不一致)
        if merged['ep_count']:
            ep_nos |= set(range(1, merged['ep_count'] + 1))

        ep_nos = sorted(ep_nos)

        play_items = []
        for ep_no in ep_nos:
            # 若有直链 m3u8 就直通, 否则用观看页
            direct = merged['episodes'].get(ep_no)
            if direct and '.m3u8' in direct:
                play_items.append('第%d集$%s' % (ep_no, direct))
            else:
                watch_url = '%s/webpc/watch/%s/%d' % (self.HOST, vid, ep_no)
                play_items.append('第%d集$%s' % (ep_no, watch_url))

        return {
            'vod_id': 'shorttv://' + vid,
            'vod_name': merged['name'] or ('短剧 ' + vid),
            'vod_pic': merged['pic'],
            'vod_content': (merged['content'] or '')[:500],
            'vod_remarks': ('共%d集' % len(ep_nos)) if len(ep_nos) > 1 else '',
            'vod_play_from': '绮梦短剧',
            'vod_play_url': '#'.join(play_items),
        }

    # ============================================================
    # 搜索
    # ============================================================
    def searchContent(self, key, quick, pg=1):
        kw = (key or '').strip()
        if not kw:
            return {'list': [], 'msg': '请输入关键词'}

        ckey = 'search:' + kw
        cached = self._cget(ckey)
        if cached is not None:
            return cached

        items = []
        params = {'q': kw, 'keyword': kw, 'limit': 30, 'surface': 'webpc'}
        for ep in ('/search', '/catalog/search', '/dramas/search'):
            data = self._get_json(self.API + ep, params=params,
                                   timeout=self.TIMEOUT_PROBE)
            if data:
                items = self._extract_dramas(data)
                if items:
                    break

        result = {'list': items, 'msg': '' if items else '未找到相关内容'}
        self._cset(ckey, result)
        return result

    # ============================================================
    # 播放 (核心: 短缓存 + 快速提取)
    # ============================================================
    def playerContent(self, flag, id, vipFlags):
        u = unquote(str(id or '').strip())
        if not u:
            return {'parse': 0, 'url': ''}

        play_header = {
            'User-Agent': self.UA,
            'Referer': self.HOST + '/',
            'Origin':  self.HOST,
        }

        # 已经是 m3u8/mp4 直链, 直接返回
        if '.m3u8' in u.lower() or '.mp4' in u.lower():
            return {'parse': 0, 'url': u, 'header': json.dumps(play_header)}

        # 观看页 URL
        if '/webpc/watch/' in u:
            m = re.search(r'/webpc/watch/([^/]+)/(\d+)', u)
            if not m:
                return {'parse': 1, 'url': u, 'header': json.dumps(play_header)}

            drama_id, ep_no = m.group(1), m.group(2)
            ck = 'play:%s:%s' % (drama_id, ep_no)

            # 命中缓存直接返回
            cached_url = self._play_get(ck)
            if cached_url:
                if self.DEBUG:
                    print('[Play] cache hit: %s' % cached_url[:100])
                return {'parse': 0, 'url': cached_url, 'header': json.dumps(play_header)}

            # 1) bootstrap (超时 4s)
            m3u8 = self._try_bootstrap(drama_id, ep_no)

            # 2) 详情 API 里的 episodes
            if not m3u8:
                m3u8 = self._try_drama_detail_m3u8(drama_id, ep_no)

            # 3) 观看页 HTML/RSC
            if not m3u8:
                html = self._get_text(u, timeout=self.TIMEOUT_PROBE + 3)
                m3u8 = self._extract_m3u8(html)
                if not m3u8:
                    rsc = self._extract_rsc(html)
                    m3u8 = self._extract_m3u8(rsc)
                if not m3u8:
                    for obj in self._safe_load_all(html):
                        m3u8 = self._find_m3u8_in_obj(obj)
                        if m3u8:
                            break

            if m3u8:
                self._play_set(ck, m3u8)
                if self.DEBUG:
                    print('[Play] OK: %s' % m3u8[:120])
                return {'parse': 0, 'url': m3u8, 'header': json.dumps(play_header)}

            if self.DEBUG:
                print('[Play] all failed, sniff mode')
            return {'parse': 1, 'url': u, 'header': json.dumps(play_header)}

        if u.startswith('http'):
            return {'parse': 1, 'url': u, 'header': json.dumps(play_header)}

        return {'parse': 1, 'url': self.HOST + u, 'header': json.dumps(play_header)}

    def _try_bootstrap(self, drama_id, ep_no):
        """bootstrap 端点, 3 组参数快速失败"""
        url = self.API + '/bootstrap'
        param_sets = [
            {'drama_id': drama_id, 'episode': ep_no},
            {'drama_id': drama_id, 'episode_no': ep_no},
            {'drama_id': drama_id, 'episode': ep_no, 'surface': 'webpc'},
        ]
        for params in param_sets:
            data = self._get_json(url, params=params, timeout=self.TIMEOUT_PROBE)
            if not data:
                continue
            m3u8 = self._find_m3u8_in_obj(data)
            if m3u8:
                return m3u8
        return ''

    def _try_drama_detail_m3u8(self, drama_id, ep_no):
        for ep in ('/catalog/dramas/%s/detail' % drama_id,
                   '/catalog/dramas/%s' % drama_id):
            data = self._get_json(self.API + ep,
                                   params={'surface': 'webpc'},
                                   timeout=self.TIMEOUT_PROBE)
            if not data:
                continue
            for obj in self._iter_dicts(data):
                eps = (obj.get('episodes') or obj.get('episode_list') or
                       obj.get('episodeList'))
                if not isinstance(eps, list):
                    continue
                for e in eps:
                    if not isinstance(e, dict):
                        continue
                    e_no = (e.get('episode_no') or e.get('episodeNo') or
                            e.get('index') or e.get('number'))
                    try:
                        if int(e_no) == int(ep_no):
                            m3u8 = self._find_m3u8_in_obj(e)
                            if m3u8:
                                return m3u8
                    except Exception:
                        pass
        return ''

    def _find_m3u8_in_obj(self, obj, depth=0):
        if depth > 10 or not obj:
            return ''
        if isinstance(obj, str):
            if '.m3u8' in obj and obj.startswith('http'):
                return obj
            return ''
        if isinstance(obj, dict):
            for k in ('url', 'play_url', 'playUrl', 'video_url', 'videoUrl',
                      'src', 'source', 'hls', 'm3u8', 'playback_url',
                      'playbackUrl', 'master_url', 'manifest',
                      'video_url_hls', 'videoUrlHls', 'hls_url'):
                v = obj.get(k)
                if isinstance(v, str) and '.m3u8' in v and v.startswith('http'):
                    return v
            for v in obj.values():
                r = self._find_m3u8_in_obj(v, depth + 1)
                if r:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = self._find_m3u8_in_obj(v, depth + 1)
                if r:
                    return r
        return ''

    def _extract_m3u8(self, text):
        if not text:
            return ''
        t = text.replace('\\/', '/').replace('\\u0026', '&').replace('&amp;', '&')
        patterns = [
            r'"url"\s*:\s*"(https?://[^"]+?\.m3u8[^"]*)"',
            r'"(?:playUrl|play_url|videoUrl|video_url|src|source|hls|master_url|manifest)"\s*:\s*"(https?://[^"]+?\.m3u8[^"]*)"',
            r'"(https?://[^"]+?\.m3u8[^"]*)"',
            r"'(https?://[^']+?\.m3u8[^']*)'",
            r'(https?://[^\s"\'<>\\)]+?\.m3u8[^\s"\'<>\\)]*)',
        ]
        for pat in patterns:
            m = re.search(pat, t)
            if m:
                url = m.group(1).rstrip('\\"\'')
                if url.startswith('//'):
                    url = 'https:' + url
                if '.m3u8' in url:
                    return url
        return ''

    # ============================================================
    # RSC 解析
    # ============================================================
    def _extract_rsc(self, html):
        if not html:
            return ''
        chunks = re.findall(
            r'self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*"((?:[^"\\]|\\.)*)"\s*\]',
            html, re.S)
        parts = []
        for c in chunks:
            try:
                parts.append(json.loads('"' + c + '"'))
            except Exception:
                parts.append(c.replace('\\"', '"').replace('\\\\', '\\'))
        text = '\n'.join(parts)
        return text.replace('\\/', '/').replace('\\u0026', '&')

    def _match_brace(self, text, start):
        n = len(text)
        if start >= n or text[start] != '{':
            return -1
        depth, i = 0, start
        in_str, esc = False, False
        while i < n:
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        return i
            i += 1
        return -1

    def _safe_load_all(self, text):
        result = []
        if not text:
            return result
        i, n = 0, len(text)
        while i < n:
            if text[i] != '{':
                i += 1
                continue
            end = self._match_brace(text, i)
            if end < 0:
                i += 1
                continue
            try:
                result.append(json.loads(text[i:end + 1]))
            except Exception:
                pass
            i = end + 1
        return result

    # ============================================================
    def localProxy(self, params):
        return None

    def destroy(self):
        try:
            if self.session:
                self.session.close()
        except Exception:
            pass

    def close(self):
        self.destroy()


# ============================================================
# 自测
# ============================================================
if __name__ == '__main__':
    s = Spider().init()

    t0 = time.time()
    home = s.homeVideoContent()
    t1 = time.time()
    print('\n=== 列表 === 耗时 %.2fs, 条数 %d' % (t1 - t0, len(home.get('list', []))))
    for it in home.get('list', [])[:3]:
        print('  ', it)

    if home.get('list'):
        vid = home['list'][0]['vod_id']

        t0 = time.time()
        d = s.detailContent([vid])
        t1 = time.time()
        print('\n=== 详情 === 耗时 %.2fs' % (t1 - t0))
        if d.get('list'):
            detail = d['list'][0]
            print('  名称:', detail.get('vod_name'))
            ep_list = detail.get('vod_play_url', '').split('#')
            print('  集数:', len(ep_list))
            print('  前3集:')
            for ep in ep_list[:3]:
                print('    ', ep[:100])

            if ep_list:
                first = ep_list[0]
                if '$' in first:
                    watch_page = first.split('$')[1]
                    print('\n=== 播放 ===')
                    print('  观看页:', watch_page)
                    t0 = time.time()
                    pc = s.playerContent('', watch_page, None)
                    t1 = time.time()
                    print('  耗时 %.2fs, parse=%s' % (t1 - t0, pc.get('parse')))
                    print('  url:', (pc.get('url') or '')[:200])