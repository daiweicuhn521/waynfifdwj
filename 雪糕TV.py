# -*- coding: utf-8 -*-
# ============================================================
# 刁民免费制作分享，请勿用于商业用途，贩卖，违法必究。
# 请于测试完24小时删除
# ============================================================
# TVBox / OK影视 / 影视仓 / WebHome 标准 Python 爬虫
# 站点: https://www.xgitv.com (苹果CMS v10 + Conch模板)
# ============================================================

import sys
import json
import re
import time
from urllib.parse import quote, unquote, urljoin

sys.path.append('..')

try:
    from base.spider import Spider
except ImportError:
    import requests as rq

    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r


class Spider(Spider):
    host = 'https://www.xgitv.com'

    _backup_hosts = [
        'https://www.pgitv.com',
        'https://kan.pgitv.com',
    ]

    _last_host_check = 0
    _host_cache_ttl = 1800

    _player_names = {
        'lzm3u8': '量子', 'lz': '量子',
        'wjwsym3u8': '无尽无水印', 'wjm3u8': '无尽', 'wj': '无尽',
        'mtm3u8': '茅台', 'mt': '茅台',
        'wolong': '卧龙',
        'ffm3u8': '非凡', 'ff': '非凡',
        'snm3u8': '索尼', 'sn': '索尼',
        'tpm3u8': '淘片', 'tp': '淘片',
    }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://www.xgitv.com/',
    }

    classes = [
        {'type_name': '电影', 'type_id': 'dianying'},
        {'type_name': '剧集', 'type_id': 'dianshiju'},
        {'type_name': '综艺', 'type_id': 'zongyi'},
        {'type_name': '动漫', 'type_id': 'dongman'},
        {'type_name': '动作片', 'type_id': 'zilei1'},
        {'type_name': '喜剧片', 'type_id': 'zilei2'},
        {'type_name': '爱情片', 'type_id': 'zilei3'},
        {'type_name': '科幻片', 'type_id': 'zilei4'},
        {'type_name': '恐怖片', 'type_id': 'zilei5'},
        {'type_name': '剧情片', 'type_id': 'zilei6'},
        {'type_name': '战争片', 'type_id': 'zilei7'},
        {'type_name': '纪录片', 'type_id': 'jilupian'},
        {'type_name': '国产剧', 'type_id': 'zilei8'},
        {'type_name': '港台剧', 'type_id': 'zilei9'},
        {'type_name': '日韩剧', 'type_id': 'zilei10'},
        {'type_name': '欧美剧', 'type_id': 'zilei11'},
        {'type_name': '海外剧', 'type_id': 'haiwaiju'},
        {'type_name': '其他', 'type_id': 'qita'},
    ]

    _area_all = [
        {'n': '全部', 'v': ''},
        {'n': '中国大陆', 'v': '中国大陆'},
        {'n': '香港', 'v': '香港'},
        {'n': '台湾', 'v': '台湾'},
        {'n': '美国', 'v': '美国'},
        {'n': '日本', 'v': '日本'},
        {'n': '韩国', 'v': '韩国'},
        {'n': '英国', 'v': '英国'},
        {'n': '泰国', 'v': '泰国'},
        {'n': '印度', 'v': '印度'},
        {'n': '其他', 'v': '其他'},
    ]

    _area_drama = [
        {'n': '全部', 'v': ''},
        {'n': '中国大陆', 'v': '中国大陆'},
        {'n': '香港', 'v': '香港'},
        {'n': '台湾', 'v': '台湾'},
        {'n': '美国', 'v': '美国'},
        {'n': '日本', 'v': '日本'},
        {'n': '韩国', 'v': '韩国'},
        {'n': '其他', 'v': '其他'},
    ]

    _area_cartoon = [
        {'n': '全部', 'v': ''},
        {'n': '中国大陆', 'v': '中国大陆'},
        {'n': '日本', 'v': '日本'},
        {'n': '美国', 'v': '美国'},
        {'n': '韩国', 'v': '韩国'},
        {'n': '其他', 'v': '其他'},
    ]

    filters = {
        'dianying': [{'key': 'area', 'name': '地区', 'value': _area_all}],
        'dianshiju': [{'key': 'area', 'name': '地区', 'value': _area_drama}],
        'zongyi': [{'key': 'area', 'name': '地区', 'value': [
            {'n': '全部', 'v': ''},
            {'n': '中国大陆', 'v': '中国大陆'},
            {'n': '香港', 'v': '香港'},
            {'n': '台湾', 'v': '台湾'},
            {'n': '美国', 'v': '美国'},
            {'n': '日本', 'v': '日本'},
            {'n': '韩国', 'v': '韩国'},
        ]}],
        'dongman': [{'key': 'area', 'name': '地区', 'value': _area_cartoon}],
    }

    # ==================== 动态域名 ====================

    def _ensure_host(self):
        now = time.time()
        if now - self._last_host_check < self._host_cache_ttl:
            return self.host
        self._last_host_check = now
        for h in [self.host] + self._backup_hosts:
            try:
                r = self.fetch(h, headers=self.headers, timeout=10)
                text = r.text if hasattr(r, 'text') else ''
                if r.status_code == 200 and ('雪糕TV' in text or 'xgitv' in text or 'voddetail' in text):
                    self.host = h
                    self.headers['Referer'] = h + '/'
                    return self.host
            except Exception:
                pass
        return self.host

    def _html(self, url, require_ok=False):
        self._ensure_host()
        full = url if url.startswith('http') else self.host + url
        try:
            r = self.fetch(full, headers=self.headers, timeout=15)
            text = r.text if hasattr(r, 'text') else ''
            if require_ok and r.status_code >= 400:
                self._last_host_check = 0
                self._ensure_host()
                full = url if url.startswith('http') else self.host + url
                r = self.fetch(full, headers=self.headers, timeout=15)
                text = r.text if hasattr(r, 'text') else ''
            return text
        except Exception:
            if require_ok:
                self._last_host_check = 0
                self._ensure_host()
                try:
                    full = url if url.startswith('http') else self.host + url
                    r = self.fetch(full, headers=self.headers, timeout=15)
                    return r.text if hasattr(r, 'text') else ''
                except Exception:
                    pass
            return ''

    # ==================== 基础方法 ====================

    def getName(self):
        return '雪糕TV'

    def init(self, extend=''):
        self.extend = extend or ''
        self._ensure_host()

    def isVideoFormat(self, url):
        return any(x in url for x in ['.m3u8', '.mp4', '.flv', '.avi', '.mkv', '.ts'])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ==================== 首页 ====================

    def homeContent(self, filter):
        result = {'class': self.classes}
        if filter:
            result['filters'] = self.filters
        return result

    def homeVideoContent(self):
        vods = []
        try:
            for tid in ['dianying', 'dianshiju', 'zongyi', 'dongman']:
                html = self._html('/vodshow/%s-----------.html' % tid)
                vods.extend(self._parse_list(html)[:8])
                if len(vods) >= 30:
                    break
        except Exception:
            pass
        return {'list': vods[:30]}

    # ==================== 分类 ====================

    def _build_cat_url(self, tid, area, pg):
        if area:
            return '/vodshow/%s-%s-------%s---.html' % (tid, area, pg) if pg > 1 else '/vodshow/%s-%s----------.html' % (tid, area)
        return '/vodshow/%s--------%s---.html' % (tid, pg) if pg > 1 else '/vodshow/%s-----------.html' % tid

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)
            ext = {}
            if extend:
                try:
                    ext = json.loads(extend) if isinstance(extend, str) else dict(extend)
                except Exception:
                    pass
            html = self._html(self._build_cat_url(tid, ext.get('area', ''), pg), require_ok=True)
            vods = self._parse_list(html)
            return {
                'page': pg,
                'pagecount': pg + 1 if '下一页' in html else pg,
                'limit': len(vods) if vods else 20,
                'total': pg * len(vods),
                'list': vods,
            }
        except Exception as e:
            print('[雪糕TV] 分类异常: %s' % e)
            return {'page': 1, 'pagecount': 1, 'limit': 20, 'total': 20, 'list': []}

    # ==================== 详情 ====================

    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else str(ids)
            vid = re.search(r'(\d+)', vod_id)
            if not vid:
                return {'list': []}
            vid = vid.group(1)

            html = self._html('/voddetail/%s.html' % vid, require_ok=True)
            if not html:
                return {'list': []}

            # 名称
            vod_name = ''
            for tag in [r'<h1[^>]*>(.*?)</h1>', r'<h2[^>]*>(.*?)</h2>']:
                m = re.search(tag, html, re.S)
                if m:
                    vod_name = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    if vod_name:
                        break
            if not vod_name:
                m = re.search(r'<title>《?(.*?)》?[^<]*?</title>', html, re.S)
                if m:
                    vod_name = m.group(1).strip()

            # 图片
            pic = ''
            m = re.search(r'data-original=["\']([^"\']+)["\']', html)
            if m:
                pic = m.group(1)
                if not pic.startswith('http'):
                    pic = urljoin(self.host, pic)

            # 信息提取
            info_map = {'类型': '', '年份': '', '地区': '', '主演': '', '导演': ''}
            info_match = re.search(r'class=["\'][^"\']*(?:detail-info|hl-detail-infos)["\'][^>]*>(.*?)</div>', html, re.S)
            info_text = info_match.group(1) if info_match else html

            for key in info_map:
                if key in ('类型', '年份', '地区'):
                    m = re.search(r'%s[：:]\s*<a[^>]*>(.*?)</a>' % key, info_text, re.S)
                else:
                    m = re.search(r'%s[：:]\s*(.*?)</li>' % key, info_text, re.S)
                if m:
                    info_map[key] = re.sub(r'<[^>]+>', '', m.group(1)).strip()

            m = re.search(r'class=["\'][^"\']*(?:hl-pic-text|pic-text|tag|remarks)["\'][^>]*>.*?(?:<span|<em|<i)[^>]*>(.*?)</(?:span|em|i)>', html, re.S)
            vod_remarks = re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else ''

            m = re.search(r'class=["\'][^"\']*(?:hl-content|content|desc|summary|intro)["\'][^>]*>(.*?)</div>', html, re.S)
            vod_content = re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else ''

            # 播放线路
            play_links = re.findall(r'href=["\'](/vodplay/\d+-\d+-\d+\.html)["\'][^>]*>(.*?)</a>', html, re.S)
            player_map = {}
            for pl_url, pl_name in play_links:
                parts = pl_url.replace('/vodplay/', '').replace('.html', '').split('-')
                if len(parts) == 3:
                    pid, ep = parts[1], parts[2]
                    name = re.sub(r'<[^>]+>', '', pl_name).strip()
                    player_map.setdefault(pid, {'name': '', 'eps': []})
                    if name and name not in [e['name'] for e in player_map[pid]['eps']]:
                        player_map[pid]['eps'].append({'name': name, 'ep': ep})

            # 探测线路名称
            for pid_int in range(1, 13):
                test_html = self._html('/vodplay/%s-%d-1.html' % (vid, pid_int))
                if test_html and 'player_aaaa' in test_html:
                    data = self._player_data(test_html)
                    from_src = data.get('from', '') if data else ''
                    pid = str(pid_int)
                    if from_src:
                        player_map.setdefault(pid, {'name': '', 'eps': []})
                        player_map[pid]['name'] = from_src
                    elif pid not in player_map and pid_int <= 4:
                        player_map[pid] = {'name': '', 'eps': []}

            if not player_map:
                player_map['1'] = {'name': '', 'eps': []}

            play_from_list = []
            play_url_list = []
            for pid in sorted(player_map.keys(), key=int):
                pmap = player_map[pid]
                name = pmap.get('name', '')
                play_from_list.append(self._player_names.get(name, name or '线路%s' % pid))

                eps = pmap.get('eps', [])
                if not eps:
                    play_html = self._html('/vodplay/%s-%s-1.html' % (vid, pid))
                    if play_html:
                        for ep_url, ep_name in re.findall(r'href=["\'](/vodplay/\d+-\d+-\d+\.html)["\'][^>]*>(.*?)</a>', play_html, re.S):
                            ep_parts = ep_url.replace('/vodplay/', '').replace('.html', '').split('-')
                            if len(ep_parts) == 3 and ep_parts[1] == pid:
                                clean = re.sub(r'<[^>]+>', '', ep_name).strip()
                                if clean:
                                    eps.append({'name': clean, 'ep': ep_parts[2]})

                if eps:
                    episodes = ['%s$%s|%s|%s' % (ep['name'], vid, pid, ep['ep']) for ep in eps]
                else:
                    episodes = ['播放$%s|%s|1' % (vid, pid)]
                play_url_list.append('#'.join(episodes))

            return {'list': [{
                'vod_id': vod_id, 'vod_name': vod_name, 'vod_pic': pic,
                'type_name': info_map['类型'], 'vod_year': info_map['年份'], 'vod_area': info_map['地区'],
                'vod_remarks': vod_remarks, 'vod_actor': info_map['主演'],
                'vod_director': info_map['导演'], 'vod_content': vod_content,
                'vod_play_from': '$$$'.join(play_from_list),
                'vod_play_url': '$$$'.join(play_url_list),
            }]}
        except Exception as e:
            print('[雪糕TV] 详情异常: %s' % e)
            return {'list': []}

    # ==================== 搜索 ====================

    def searchContentPage(self, key, quick, pg):
        try:
            pg = int(pg or 1)
            kw = quote(key)
            url = '/vodsearch/%s----------%s---.html' % (kw, pg) if pg > 1 else '/vodsearch/%s-------------.html' % kw
            html = self._html(url, require_ok=True)
            vods = self._parse_list(html)
            return {
                'page': pg,
                'pagecount': pg + 1 if '下一页' in html else pg,
                'limit': len(vods) if vods else 20,
                'total': pg * len(vods),
                'list': vods,
            }
        except Exception as e:
            print('[雪糕TV] 搜索异常: %s' % e)
            return {'page': 1, 'pagecount': 1, 'limit': 20, 'total': 20, 'list': []}

    # ==================== 播放 ====================

    def playerContent(self, flag, id, vipFlags):
        result = {'parse': 0, 'url': '', 'header': ''}
        try:
            play_id = str(id or '')
            if not play_id:
                return result

            parts = play_id.split('|')
            if len(parts) >= 3:
                vid, pid, ep = parts[0], parts[1], parts[2]
            elif len(parts) == 2:
                vid, pid, ep = parts[0], parts[1], '1'
            else:
                vid, pid, ep = play_id, '1', '1'

            html = self._html('/vodplay/%s-%s-%s.html' % (vid, pid, ep), require_ok=True)
            if not html:
                return result

            data = self._player_data(html)
            if not data:
                return result

            enc_url = data.get('url', '')
            if not enc_url:
                return result

            encrypt = data.get('encrypt', 0)
            if encrypt == 1:
                m3u8 = unquote(enc_url)
            elif encrypt == 2:
                import base64
                m3u8 = base64.b64decode(enc_url).decode('utf-8')
            else:
                m3u8 = enc_url

            result['url'] = m3u8
            result['header'] = json.dumps({
                'User-Agent': self.headers['User-Agent'],
                'Referer': self.host + '/',
                'Origin': self.host,
            })
            return result
        except Exception:
            return result

    # ==================== 本地代理 ====================

    def localProxy(self, param):
        return [404, 'text/plain', '', {}]

    # ==================== 工具方法 ====================

    def _parse_list(self, html):
        vods = []
        if not html:
            return vods
        for item in re.findall(
            r'<li[^>]*class=["\'][^"\']*hl-list-item[^"\']*["\'][^>]*>.*?<a[^>]*class=["\'][^"\']*hl-item-thumb[^"\']*["\'][^>]*href=["\'](/voddetail/(\d+)\.html)["\'][^>]*title=["\']([^"\']*)["\'][^>]*data-original=["\']([^"\']*)["\'][^>]*>(.*?)</a>(.*?)</li>',
            html, re.S
        ):
            url, vid, title, pic, thumb_html, rest = item
            remarks = ''
            m = re.search(r'<span[^>]*class=["\'][^"\']*remarks[^"\']*["\'][^>]*>(.*?)</span>', thumb_html, re.S)
            if m:
                remarks = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            sub = ''
            m = re.search(r'<div[^>]*class=["\'][^"\']*hl-item-sub[^"\']*["\'][^>]*>(.*?)</div>', rest, re.S)
            if m:
                sub = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            vods.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic if pic.startswith('http') else urljoin(self.host, pic),
                'vod_remarks': remarks or sub,
            })
        return vods

    def _player_data(self, html):
        try:
            m = re.search(r'var player_aaaa=(\{.*?\})</script>', html, re.S)
            if m:
                return json.loads(m.group(1))
            start = html.find('var player_aaaa=')
            if start == -1:
                return None
            brace = html.find('{', start)
            depth, end = 0, brace
            for i in range(brace, min(brace + 10000, len(html))):
                if html[i] == '{':
                    depth += 1
                elif html[i] == '}':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            return json.loads(html[brace:end + 1])
        except Exception:
            return None
