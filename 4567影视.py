# coding=utf-8
"""
目标站: 4567影视 (www.4567dyy.com)
模板: MACCMS HTML 解析
核心: 分类(含二级筛选), 搜索(AJAX), 详情(多线路), 播放(m3u8直链)
优化: 预编译正则, 首页缓存, 减少冗余请求
"""

import sys
import json
import re
import time
import urllib.parse

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    # ---------- 预编译正则 ----------
    _re_vod_card = re.compile(
        r'<a[^>]*class=["\']\s*stui-vodlist__thumb[^"\']*["\']'
        r'\s*href=["\']/vod/(\d+)\.html["\']'
        r'\s*title=["\']([^"\']*)["\']'
        r'\s*data-original=["\']([^"\']*)["\']',
    )
    _re_remark = re.compile(
        r'<span[^>]*class=["\'][^"\']*pic-text[^"\']*["\'][^>]*>([^<]+)</span>'
    )
    _re_h1 = re.compile(r'<h1[^>]*>(.*?)</h1>', re.DOTALL)
    _re_h3_line = re.compile(r'<h3[^>]*>(?:<[^>]+>)*([^<]+)</h3>')
    _re_data_p = re.compile(
        r'<p[^>]*class=["\'][^"\']*data[^"\']*["\'][^>]*>(.*?)</p>', re.DOTALL
    )
    _re_playlist = re.compile(
        r'<ul[^>]*class=["\'][^"\']*stui-content__playlist[^"\']*["\'][^>]*>(.*?)</ul>',
        re.DOTALL,
    )
    _re_episode = re.compile(
        r'<a[^>]*href=["\'](/play/[^"\']+)["\'][^>]*>([^<]+)</a>'
    )
    _re_player = re.compile(r'var player_aaaa=(\{[^;]+\})')
    _re_page_num = re.compile(
        r'/show/[^"\']*?---(\d+)---[^"\']*["\'][^>]*>(\d+)</a>'
    )
    _re_tag = re.compile(r'<[^>]+>')

    def init(self, extend=""):
        self.site_url = "https://www.4567dyy.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self.default_pic = 'https://pic.rmb.bdstatic.com/bjh/user/default.png'

        # 主分类
        self.categories = {
            '1': '电影', '2': '电视剧', '3': '综艺',
            '4': '动漫', '5': '短剧',
        }
        # 二级分类 (电视剧子分类)
        self.sub_categories = {
            '13': '国产剧', '14': '港台剧', '15': '日韩剧', '16': '欧美剧',
        }

        # ---------- 二级筛选 ----------
        self.filters = {
            '1': [
                {'key': 'genre', 'name': '剧情', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '喜剧', 'v': '喜剧'}, {'n': '爱情', 'v': '爱情'},
                    {'n': '恐怖', 'v': '恐怖'}, {'n': '动作', 'v': '动作'}, {'n': '科幻', 'v': '科幻'},
                    {'n': '剧情', 'v': '剧情'}, {'n': '战争', 'v': '战争'}, {'n': '警匪', 'v': '警匪'},
                    {'n': '犯罪', 'v': '犯罪'}, {'n': '动画', 'v': '动画'}, {'n': '奇幻', 'v': '奇幻'},
                    {'n': '武侠', 'v': '武侠'}, {'n': '冒险', 'v': '冒险'}, {'n': '枪战', 'v': '枪战'},
                ]},
                {'key': 'area', 'name': '地区', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'}, {'n': '香港', 'v': '香港'},
                    {'n': '台湾', 'v': '台湾'}, {'n': '美国', 'v': '美国'}, {'n': '法国', 'v': '法国'},
                    {'n': '英国', 'v': '英国'}, {'n': '日本', 'v': '日本'}, {'n': '韩国', 'v': '韩国'},
                    {'n': '德国', 'v': '德国'}, {'n': '泰国', 'v': '泰国'}, {'n': '印度', 'v': '印度'},
                    {'n': '意大利', 'v': '意大利'}, {'n': '西班牙', 'v': '西班牙'},
                    {'n': '加拿大', 'v': '加拿大'}, {'n': '其他', 'v': '其他'},
                ]},
                {'key': 'year', 'name': '年份', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '2026', 'v': '2026'}, {'n': '2025', 'v': '2025'},
                    {'n': '2024', 'v': '2024'}, {'n': '2023', 'v': '2023'}, {'n': '2022', 'v': '2022'},
                    {'n': '2021', 'v': '2021'}, {'n': '2020', 'v': '2020'}, {'n': '2019', 'v': '2019'},
                    {'n': '2018', 'v': '2018'}, {'n': '2017', 'v': '2017'}, {'n': '2016', 'v': '2016'},
                ]},
            ],
            '2': [
                {'key': 'genre', 'name': '剧情', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '剧情', 'v': '剧情'}, {'n': '古装', 'v': '古装'},
                    {'n': '武侠', 'v': '武侠'}, {'n': '爱情', 'v': '爱情'}, {'n': '喜剧', 'v': '喜剧'},
                    {'n': '家庭', 'v': '家庭'}, {'n': '犯罪', 'v': '犯罪'}, {'n': '动作', 'v': '动作'},
                    {'n': '奇幻', 'v': '奇幻'}, {'n': '历史', 'v': '历史'}, {'n': '战争', 'v': '战争'},
                    {'n': '经典', 'v': '经典'}, {'n': '乡村', 'v': '乡村'}, {'n': '情景', 'v': '情景'},
                ]},
                {'key': 'area', 'name': '地区', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'}, {'n': '韩国', 'v': '韩国'},
                    {'n': '香港', 'v': '香港'}, {'n': '台湾', 'v': '台湾'}, {'n': '日本', 'v': '日本'},
                    {'n': '美国', 'v': '美国'}, {'n': '泰国', 'v': '泰国'}, {'n': '英国', 'v': '英国'},
                    {'n': '新加坡', 'v': '新加坡'}, {'n': '其他', 'v': '其他'},
                ]},
                {'key': 'year', 'name': '年份', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '2026', 'v': '2026'}, {'n': '2025', 'v': '2025'},
                    {'n': '2024', 'v': '2024'}, {'n': '2023', 'v': '2023'}, {'n': '2022', 'v': '2022'},
                    {'n': '2021', 'v': '2021'}, {'n': '2020', 'v': '2020'}, {'n': '2019', 'v': '2019'},
                    {'n': '2018', 'v': '2018'}, {'n': '2017', 'v': '2017'}, {'n': '2016', 'v': '2016'},
                ]},
            ],
            '3': [
                {'key': 'genre', 'name': '剧情', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '真人秀', 'v': '真人秀'}, {'n': '音乐', 'v': '音乐'},
                    {'n': '爱情', 'v': '爱情'}, {'n': '家庭', 'v': '家庭'}, {'n': '悬疑', 'v': '悬疑'},
                    {'n': '喜剧', 'v': '喜剧'}, {'n': '旅游', 'v': '旅游'}, {'n': '访谈', 'v': '访谈'},
                    {'n': '情感', 'v': '情感'},
                ]},
                {'key': 'area', 'name': '地区', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'}, {'n': '香港', 'v': '香港'},
                    {'n': '台湾', 'v': '台湾'}, {'n': '韩国', 'v': '韩国'}, {'n': '日本', 'v': '日本'},
                    {'n': '美国', 'v': '美国'},
                ]},
                {'key': 'year', 'name': '年份', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '2026', 'v': '2026'}, {'n': '2025', 'v': '2025'},
                    {'n': '2024', 'v': '2024'}, {'n': '2023', 'v': '2023'}, {'n': '2022', 'v': '2022'},
                    {'n': '2021', 'v': '2021'}, {'n': '2020', 'v': '2020'}, {'n': '2019', 'v': '2019'},
                    {'n': '2018', 'v': '2018'}, {'n': '2017', 'v': '2017'},
                ]},
            ],
            '4': [
                {'key': 'genre', 'name': '剧情', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '剧情', 'v': '剧情'}, {'n': '奇幻', 'v': '奇幻'},
                    {'n': '冒险', 'v': '冒险'}, {'n': '爱情', 'v': '爱情'}, {'n': '动作', 'v': '动作'},
                    {'n': '古装', 'v': '古装'}, {'n': '悬疑', 'v': '悬疑'}, {'n': '惊悚', 'v': '惊悚'},
                ]},
                {'key': 'area', 'name': '地区', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'}, {'n': '日本', 'v': '日本'},
                    {'n': '韩国', 'v': '韩国'}, {'n': '美国', 'v': '美国'}, {'n': '其他', 'v': '其他'},
                ]},
                {'key': 'year', 'name': '年份', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '2026', 'v': '2026'}, {'n': '2025', 'v': '2025'},
                    {'n': '2024', 'v': '2024'}, {'n': '2023', 'v': '2023'}, {'n': '2022', 'v': '2022'},
                    {'n': '2021', 'v': '2021'}, {'n': '2020', 'v': '2020'}, {'n': '2019', 'v': '2019'},
                    {'n': '2018', 'v': '2018'}, {'n': '2017', 'v': '2017'},
                ]},
            ],
            '5': [
                {'key': 'genre', 'name': '剧情', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '剧情', 'v': '剧情'}, {'n': '喜剧', 'v': '喜剧'},
                    {'n': '爱情', 'v': '爱情'}, {'n': '穿越', 'v': '穿越'},
                ]},
                {'key': 'area', 'name': '地区', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'},
                ]},
                {'key': 'year', 'name': '年份', 'value': [
                    {'n': '全部', 'v': ''}, {'n': '2026', 'v': '2026'}, {'n': '2025', 'v': '2025'},
                    {'n': '2024', 'v': '2024'}, {'n': '2023', 'v': '2023'}, {'n': '2022', 'v': '2022'},
                    {'n': '2021', 'v': '2021'}, {'n': '2020', 'v': '2020'},
                ]},
            ],
        }

        # ---------- 缓存 ----------
        self._home_cache = None
        self._home_ts = 0

    # ==================== 工具方法 ====================

    def _fix_pic(self, pic):
        if not pic or pic == '/':
            return self.default_pic
        if pic.startswith('http'):
            return pic
        return self.site_url + pic

    def _strip(self, text):
        return self._re_tag.sub('', text).strip()

    def _get_html(self, path):
        url = self.site_url + path
        try:
            resp = self.fetch(url, headers=self.headers)
            if resp:
                return resp.text
        except Exception:
            pass
        return ''

    def _parse_cards(self, html):
        """解析视频卡片列表"""
        videos = []
        seen = set()
        for m in self._re_vod_card.finditer(html):
            vid, title, pic = m.group(1), m.group(2), m.group(3)
            if vid in seen:
                continue
            seen.add(vid)
            videos.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': self._fix_pic(pic),
                'vod_remarks': '',
            })
        # 提取remark
        remarks = self._re_remark.findall(html)
        for i, v in enumerate(videos):
            if i < len(remarks):
                v['vod_remarks'] = self._strip(remarks[i])
        return videos

    # ==================== 接口方法 ====================

    def homeContent(self, filter):
        # 分类列表: 主分类 + 二级分类
        classes = []
        for tid, name in self.categories.items():
            classes.append({'type_id': tid, 'type_name': name})
        for tid, name in self.sub_categories.items():
            classes.append({'type_id': tid, 'type_name': name})

        # 首页推荐 (带缓存, 减少重复请求)
        now = time.time()
        if self._home_cache and (now - self._home_ts) < 300:
            videos = self._home_cache
        else:
            html = self._get_html('/')
            videos = self._parse_cards(html)[:30] if html else []
            self._home_cache = videos
            self._home_ts = now

        filters = {}
        for k in self.categories:
            if k in self.filters:
                filters[k] = self.filters[k]

        return {'class': classes, 'list': videos, 'filters': filters}

    def homeVideoContent(self):
        now = time.time()
        if self._home_cache and (now - self._home_ts) < 300:
            return {'list': self._home_cache}
        html = self._get_html('/')
        videos = self._parse_cards(html)[:30] if html else []
        self._home_cache = videos
        self._home_ts = now
        return {'list': videos}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        area = ''
        genre = ''
        year = ''
        if extend:
            area = extend.get('area', '')
            genre = extend.get('genre', '')
            year = extend.get('year', '')

        # URL: tid-area-genre--------page---year
        # 无area/genre: /show/{tid}--------{page}---{year}.html
        # 有area/genre: /show/{tid}-{area}-{genre}--------{page}---{year}.html
        if area or genre:
            path = '/show/{0}-{1}-{2}--------{3}---{4}.html'.format(
                tid, area, genre, page, year
            )
        else:
            path = '/show/{0}--------{1}---{2}.html'.format(
                tid, page, year
            )
        html = self._get_html(path)
        if not html:
            return {'list': [], 'page': page, 'pagecount': page, 'limit': 36, 'total': 0}

        videos = self._parse_cards(html)

        # 解析分页
        pagecount = page
        for m in self._re_page_num.finditer(html):
            n = int(m.group(2))
            if n > pagecount:
                pagecount = n

        return {
            'list': videos,
            'page': page,
            'pagecount': pagecount,
            'limit': 36,
            'total': len(videos) * pagecount,
        }

    def searchContent(self, key, quick, pg='1'):
        # 使用 AJAX suggest API, 速度快
        encoded = urllib.parse.quote(key)
        path = '/index.php/ajax/suggest?mid=1&wd={0}&limit=30'.format(encoded)

        data_str = self._get_html(path)
        if not data_str:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 30, 'total': 0}

        try:
            data = json.loads(data_str)
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 30, 'total': 0}

        videos = []
        for item in data.get('list', []):
            vid = str(item.get('id', ''))
            name = item.get('name', '')
            pic = item.get('pic', '')
            videos.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': self._fix_pic(pic),
                'vod_remarks': '',
            })

        return {
            'list': videos,
            'page': data.get('page', 1),
            'pagecount': data.get('pagecount', 1),
            'limit': 30,
            'total': data.get('total', 0),
        }

    def detailContent(self, ids):
        if not ids:
            return {'list': []}

        vid = ids[0]
        html = self._get_html('/vod/{0}.html'.format(vid))
        if not html:
            return {'list': []}

        # 标题 (H1, 去掉评分数字)
        title = ''
        h1 = self._re_h1.search(html)
        if h1:
            title = self._strip(h1.group(1))
            title = re.sub(r'[\d.]+$', '', title).strip()

        # 封面
        pic_match = self._re_vod_card.search(html)
        pic = self._fix_pic(pic_match.group(3)) if pic_match else self.default_pic

        # 信息字段 (从 <p class="data"> 提取)
        vod_type = vod_area = vod_year = ''
        vod_actor = vod_director = vod_content = ''
        for p in self._re_data_p.findall(html):
            text = self._strip(p).replace('\xa0', ' ').replace('&nbsp;', ' ')
            if text.startswith('类型'):
                vod_type = text.split('：', 1)[-1].strip() if '：' in text else ''
            elif text.startswith('地区'):
                vod_area = text.split('：', 1)[-1].strip() if '：' in text else ''
            elif text.startswith('年份'):
                vod_year = text.split('：', 1)[-1].strip() if '：' in text else ''
            elif text.startswith('主演'):
                vod_actor = text.split('：', 1)[-1].strip() if '：' in text else ''
            elif text.startswith('导演'):
                vod_director = text.split('：', 1)[-1].strip() if '：' in text else ''
            elif text.startswith('更新'):
                pass

        # 简介
        desc_match = re.search(r'简介：([^<]+)', html)
        if desc_match:
            vod_content = desc_match.group(1).strip()

        # 播放线路: H3标题 + 对应的 playlist ul
        h3_names = [self._strip(n) for n in self._re_h3_line.findall(html)]
        playlist_bodies = self._re_playlist.findall(html)

        play_from = []
        play_url = []
        line_idx = 0
        for name in h3_names:
            if not name.startswith('播放线路'):
                continue
            if line_idx >= len(playlist_bodies):
                break
            body = playlist_bodies[line_idx]
            line_idx += 1
            episodes = self._re_episode.findall(body)
            if episodes:
                play_from.append(name)
                play_url.append('#'.join('{0}${1}'.format(t, h) for h, t in episodes))

        if not play_from:
            play_from.append('默认线路')
            play_url.append('')

        return {'list': [{
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': pic,
            'vod_type': vod_type,
            'vod_year': vod_year,
            'vod_area': vod_area,
            'vod_actor': vod_actor,
            'vod_director': vod_director,
            'vod_content': vod_content,
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }]}

    def playerContent(self, flag, id, vipFlags):
        # id 格式: /play/{vid}-{source}-{episode}.html
        path = id if id.startswith('/') else '/' + id
        html = self._get_html(path)
        if not html:
            return {'parse': 1, 'url': self.site_url + path, 'header': self.headers}

        m = self._re_player.search(html)
        if not m:
            return {'parse': 1, 'url': self.site_url + path, 'header': self.headers}

        try:
            player = json.loads(m.group(1))
        except Exception:
            return {'parse': 1, 'url': self.site_url + path, 'header': self.headers}

        play_url = player.get('url', '')
        if not play_url:
            return {'parse': 1, 'url': self.site_url + path, 'header': self.headers}

        # m3u8/mp4 直链直接返回
        if play_url.startswith('http') and ('.m3u8' in play_url or '.mp4' in play_url):
            return {
                'parse': 0,
                'url': play_url,
                'header': {
                    'User-Agent': self.headers['User-Agent'],
                    'Referer': self.site_url + '/',
                },
            }

        # 加密或需要解析的链接
        encrypt = player.get('encrypt', 0)
        if encrypt == 1:
            play_url = urllib.parse.unquote(play_url)
        elif encrypt == 2:
            try:
                import base64
                play_url = base64.b64decode(play_url).decode('utf-8')
            except Exception:
                pass

        if play_url.startswith('http') and ('.m3u8' in play_url or '.mp4' in play_url):
            return {
                'parse': 0,
                'url': play_url,
                'header': {
                    'User-Agent': self.headers['User-Agent'],
                    'Referer': self.site_url + '/',
                },
            }

        return {
            'parse': 1,
            'url': play_url if play_url.startswith('http') else self.site_url + path,
            'header': self.headers,
        }
