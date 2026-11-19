# coding=utf-8
r"""

酷狗MV (独立插件)

只做一件事：搜索并播放酷狗音乐的 MV。与「裤佬音乐(酷我)」无任何依赖。

接口:
  搜索: https://songsearch.kugou.com/song_search_v2?keyword=xxx  (筛 MvType=2 / MvHash)
  封面: 搜索结果 Image 字段，把 {size} 替换为 240
  解链: https://m.kugou.com/app/i/mv.php?cmd=100&hash={MvHash}
        -> mvdata.hd / mvdata.sd / mvdata.sq 的 downurl (真实 mkv/mp4 直链)
  说明: 解链为纯 GET，无签名、无 csrf。hd 优先，sd 兜底。

vod_id 编码: {MvHash}#{SongName}#{SingerName}#{ImageUrl}
"""

import sys
import re
import json
import time
import urllib.parse
import urllib.request

sys.path.append('..')
from base.spider import Spider as BaseSpider


# ============================================================
# 搜索结果质量优化（相关度过滤 / 打分排序 / 去重 / 歌手清洗）
# 纯工具函数，无网络。接口裸结果 -> 归一化去重 + 关键词相关度
# 过滤 + 打分排序，翻唱/live/伴奏等噪声降权。
# ============================================================
_PUNC = re.compile(
    r'''[\s\u3000\-–—/\\|·:：,，.。!！?？()（）\[\]【】"'\u201c\u201d\u2018\u2019~～+＋&＆'''
    r'''@＠#＃*＊%％$￥^＾`｀;；<>＞《》〈〉「」『』]+''')
_KWCHAR = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff\uff00-\uffefA-Za-z0-9]')
_SPLIT = re.compile(r'[\s\u3000·•,，、+＋]+')
MUSIC_NOISE = re.compile(
    r'(live|翻唱|cover|伴奏|演奏|纯音乐|纯音樂|现场|現場|演唱会|演場會|演場会|demo|片段|铃声|鈴聲|'
    r'加速|慢速|dj|remix|完整版|inst\.?|instrumental|女声版|男声版|钢琴|鋼琴|古筝|古箏|吉他|'
    r'升key|降key|伴奏版|原唱|MV版|mv版)', re.I)


def _norm(value):
    return _PUNC.sub('', '' if value is None else str(value)).lower()


def _kw_cover(kw, text):
    seen, chars = set(), []
    for c in _norm(kw):
        if c in seen:
            continue
        seen.add(c)
        if _KWCHAR.match(c):
            chars.append(c)
    if not chars:
        return 0.0
    t = _norm(text)
    return sum(1 for c in chars if c in t) / float(len(chars))


def _rel_score(it, kw):
    parts = [_norm(p) for p in _SPLIT.split(str(kw or ''))]
    parts = [p for p in parts if len(p) >= 2]
    nt, na = _norm(it.get('title')), _norm(it.get('artist'))
    score = 0
    for p in parts:
        if p in nt:
            score += 20
        if p in na:
            score += 30
    hay = str(it.get('title') or '') + ' ' + str(it.get('artist') or '')
    score += _kw_cover(kw, hay) * 10
    # MV 专用插件：MV 结果不应因「现场」等词被误杀太多，噪声权重减半
    if MUSIC_NOISE.search(hay):
        score -= 12
    return score


def _rel_filter_rank(items, kw):
    nkw = _norm(kw)
    if not nkw or not items:
        return items or []
    seen, dedup = set(), []
    for it in items:
        key = _norm(it.get('title')) + '|' + _norm(it.get('artist'))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(it)
    if len(nkw) <= 1:
        return dedup
    kept = []
    for it in dedup:
        hay = str(it.get('title') or '') + ' ' + str(it.get('artist') or '')
        if nkw in _norm(it.get('title')) or nkw in _norm(it.get('artist')):
            kept.append(it)
        elif _kw_cover(kw, hay) >= 0.5:
            kept.append(it)
    ranked = sorted(enumerate(kept), key=lambda kv: (-_rel_score(kv[1], kw), kv[0]))
    return [it for _, it in ranked]


def _clean_artists(artist):
    s = str(artist or '').strip(' .。')
    if not s:
        return ''
    parts = [p.strip(' .。') for p in re.split(r'[/、,，]', s) if p.strip(' .。')]
    return ' / '.join(parts)


class Spider(BaseSpider):

    def init(self, extend=""):
        self.search_api = "https://songsearch.kugou.com/song_search_v2"
        self.mv_api = "https://m.kugou.com/app/i/mv.php"
        self.headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'),
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9'
        }
        self.mv_headers = {
            'User-Agent': ('Mozilla/5.0 (Linux; Android 10) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'),
            'Referer': 'https://www.kugou.com/',
            'Accept': '*/*',
        }
        self._cache = {}  # MvHash -> 解链结果缓存

    def _fetch(self, url, headers=None, timeout=15):
        try:
            req = urllib.request.Request(url, headers=headers or self.headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception:
            return ''

    def _cover(self, image):
        """封面优化：大图 + 强制 https（对齐裤佬音乐的封面处理）"""
        if not image:
            return ''
        # 酷狗图床实测支持 240/480/800/1000 多档真实大图，取 800 兼顾清晰度与体积
        image = image.replace('{size}', '800')
        # 原图为 http，App/电视端可能被当混合内容拦截，升级为 https
        if image.startswith('http://'):
            image = 'https://' + image[len('http://'):]
        return image

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg="1"):
        kw = ('' if key is None else str(key)).strip()
        if re.search(r'%[0-9A-Fa-f]{2}', kw):
            try:
                kw = urllib.parse.unquote(kw)
            except Exception:
                pass
        page = int(pg) if pg else 1
        if not kw:
            return {"list": [], "page": 1, "pagecount": 1}
        params = {
            'keyword': kw, 'page': page, 'pagesize': 30,
            'platform': 'WebFilter', 'userid': '0'
        }
        # 空结果自动重试
        result = None
        for delay in (0.0, 0.6, 0.9):
            if delay:
                time.sleep(delay)
            text = self._search_text(params)
            result = self._parse(text, page, kw)
            if result.get('list'):
                break
        return result

    def _search_text(self, params):
        """取搜索原始文本：宿主 net.req 优先，失败用 urllib 兜底"""
        try:
            resp = self.net.req(self.search_api, {
                "headers": dict(self.headers), "params": params, "timeout": 15000
            })
            if resp and not resp.get("error") and 200 <= resp.get("code", 0) < 300:
                c = resp.get("content", "")
                text = c.decode('utf-8', 'replace') if isinstance(c, bytes) else c
                if text:
                    return text
        except Exception:
            pass
        return self._fetch(self.search_api + '?' + urllib.parse.urlencode(params))

    def _parse(self, text, page, kw=''):
        if not text:
            return {"list": [], "page": page, "pagecount": 1}
        try:
            data = json.loads(text)
        except Exception:
            return {"list": [], "page": page, "pagecount": 1}
        d = data.get('data', {}) or {}

        raw = []
        for it in d.get('lists', []):
            mvhash = str(it.get('MvHash') or '').strip()
            # 只保留有 MV 的歌曲
            if not mvhash or str(it.get('MvType', '0')) not in ('1', '2', '3'):
                continue
            name = it.get('SongName') or it.get('OriSongName') or ''
            singer = it.get('SingerName') or ''
            if it.get('Singers'):
                singer = singer or ','.join(s.get('name', '') for s in it['Singers'])
            image = self._cover(it.get('Image', ''))
            quality = str(it.get('MvHashMark') or '').strip()
            raw.append({
                'title': name, 'artist': singer, 'mvhash': mvhash,
                'image': image, 'quality': quality,
            })

        # 同一 MvHash（原版/DJ版/现场版实为同一个视频）只保留相关度最高的一条，
        # 避免搜索列表里出现多个一模一样的 MV
        by_hash = {}
        order = []
        for it in raw:
            h = it['mvhash']
            if h not in by_hash:
                by_hash[h] = it
                order.append(h)
            elif _rel_score(it, kw) > _rel_score(by_hash[h], kw):
                by_hash[h] = it
        raw = [by_hash[h] for h in order]

        # 相关度过滤、去重、打分排序
        ranked = _rel_filter_rank(raw, kw)
        songs = []
        for it in ranked:
            name = it['title']
            singer_disp = _clean_artists(it['artist'])
            title = f'{name} - {singer_disp}' if singer_disp else name
            vid = (f"{it['mvhash']}#{urllib.parse.quote(name)}#"
                   f"{urllib.parse.quote(it['artist'])}#{urllib.parse.quote(it['image'])}")
            songs.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': it['image'],
                'vod_remarks': ('MV ' + it['quality']).strip(),
            })
        total = len(songs)
        pagecount = max(1, (total + 29) // 30)
        return {
            "list": songs, "page": page, "pagecount": pagecount,
            "limit": len(songs), "total": total
        }

    # ---------- 详情 ----------
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        parts = str(ids[0]).split('#')
        mvhash = parts[0]
        name = urllib.parse.unquote(parts[1]) if len(parts) > 1 else mvhash
        singer = urllib.parse.unquote(parts[2]) if len(parts) > 2 else ''
        image = urllib.parse.unquote(parts[3]) if len(parts) > 3 else ''
        title = f'{name} - {singer}' if singer else name
        # 高清 / 标清 双线路；URL 里带 q 标记，播放时据此选档（缺档自动兜底）
        base = f'{self.mv_api}?hash={mvhash}&name={urllib.parse.quote(name)}'
        play_url = (f'在线播放${base}&q=hd$$$'
                    f'在线播放${base}&q=sd')
        return {"list": [{
            'vod_id': mvhash,
            'vod_name': title,
            'vod_pic': image,
            'vod_content': '',
            'vod_play_from': '高清$$$标清',
            'vod_play_url': play_url,
        }]}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
        m = re.search(r'[?&]hash=([0-9A-Fa-f]+)', id or '')
        mvhash = m.group(1) if m else (id or '').strip()
        # 线路标记：q=hd/sd；无标记时按线路名兜底（高清->hd，否则 sd）
        qm = re.search(r'[?&]q=(hd|sd)', id or '')
        quality = qm.group(1) if qm else ('hd' if '高清' in str(flag or '') else 'sd')
        play_url = self._resolve(mvhash, quality)
        result = {
            'parse': 0,
            'jx': 0,
            'url': play_url or id,
            'header': {
                'User-Agent': self.mv_headers['User-Agent'],
                'Referer': 'https://www.kugou.com/'
            }
        }
        return result

    def _resolve(self, mvhash, quality='hd'):
        """用 MvHash 解链，按 quality 取档（缺档自动兜底），返回真实播放地址"""
        if not mvhash:
            return ''
        cache_key = f'{mvhash}_{quality}'
        if cache_key in self._cache:
            return self._cache[cache_key]
        url = self.mv_api + '?' + urllib.parse.urlencode({'cmd': 100, 'hash': mvhash})
        text = ''
        try:
            resp = self.net.req(url, {"headers": dict(self.mv_headers), "timeout": 15000})
            if resp and not resp.get("error") and 200 <= resp.get("code", 0) < 300:
                c = resp.get("content", "")
                text = c.decode('utf-8', 'replace') if isinstance(c, bytes) else c
        except Exception:
            pass
        if not text:
            text = self._fetch(url, headers=self.mv_headers)
        if not text:
            return ''
        try:
            data = json.loads(text)
        except Exception:
            return ''
        mv = data.get('mvdata', {}) or {}
        result = ''
        # 优先取目标档，缺档时按 hd > sd > sq > rq 兜底
        order = [quality] + [q for q in ('hd', 'sd', 'sq', 'rq') if q != quality]
        for q in order:
            info = mv.get(q) or {}
            u = info.get('downurl') or ''
            if not u:
                for b in (info.get('backupdownurl') or []):
                    if b:
                        u = b
                        break
            if u:
                result = u
                break
        if result:
            self._cache[cache_key] = result
        return result

    # ---------- 框架要求的空实现 ----------
    def proxy(self, params):
        return [404, 'text/plain; charset=utf-8', 'not found', {}]

    def homeContent(self, filter):
        return {"class": [], "list": [], "filters": {}}

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        return {"list": [], "page": int(pg) if pg else 1, "pagecount": 1}

    def isVideoFormat(self, url):
        return True

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self._cache.clear()

    def liveContent(self, url):
        return ""

    def action(self, action):
        return ""
