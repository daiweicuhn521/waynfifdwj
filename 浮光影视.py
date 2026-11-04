# coding=utf-8
"""
目标站: 浮光影视 (juyifan.com)
模板: 影视聚合 / HTML 静态解析
站点类型: 综合影视内容站（单线路播放）
支持: 首页, 分类(含二级筛选), 搜索, 详情, 播放(m3u8直链)
说明: 该站为内容聚合站，聚合电影/电视剧/综艺/动漫/短剧等，播放页仅提供单条m3u8直链
"""

import sys
import re
import base64
import json
import urllib.parse

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    def init(self, extend=""):
        self.site_url = "https://juyifan.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.site_url + '/',
        }
        self.default_pic = 'https://pic.rmb.bdstatic.com/bjh/user/default.png'

        # 主分类
        self.categories = {
            'dianyingad': '电影',
            'dianshig': '电视剧',
            'zongyig': '综艺',
            'dongmang': '动漫',
            'juchangg': 'AI剧场',
            'duanjug': '短剧',
            'yingshih': '影视解说',
        }

        # 二级分类筛选
        self.filters = {
            'dianyingad': [
                {'key': 'genre', 'name': '类型', 'value': [
                    {'n': '全部', 'v': ''},
                    {'n': '动作片', 'v': 'dongzuog'},
                    {'n': '喜剧片', 'v': 'xijug'},
                    {'n': '爱情片', 'v': 'aiqingg'},
                    {'n': '科幻片', 'v': 'kehuang'},
                    {'n': '恐怖片', 'v': 'kongbug'},
                    {'n': '剧情片', 'v': 'juqingq'},
                    {'n': '战争片', 'v': 'zhanzhengg'},
                    {'n': '悬疑片', 'v': 'xuanyig'},
                    {'n': '犯罪片', 'v': 'fanzuig'},
                    {'n': '惊悚片', 'v': 'jingsongg'},
                    {'n': '奇幻片', 'v': 'qihuang'},
                    {'n': '冒险片', 'v': 'maoxiang'},
                    {'n': '灾难片', 'v': 'zainang'},
                    {'n': '武侠片', 'v': 'wuxiag'},
                    {'n': '古装片', 'v': 'guzhuangn'},
                    {'n': '动画电影', 'v': 'donghuan'},
                    {'n': '动画片', 'v': 'donghuao'},
                    {'n': '纪录片', 'v': 'jilug'},
                    {'n': '短片', 'v': 'duanpiang'},
                    {'n': '西部片', 'v': 'xibug'},
                    {'n': '历史片', 'v': 'lishig'},
                    {'n': '家庭片', 'v': 'jiatingg'},
                    {'n': '邵氏电影', 'v': 'shaoshig'},
                    {'n': '4K电影', 'v': 'dianyingae'},
                    {'n': 'Netflix电影', 'v': 'dianyingaf'},
                    {'n': '伦理片', 'v': 'lunlin'},
                ]},
            ],
            'dianshig': [
                {'key': 'genre', 'name': '地区', 'value': [
                    {'n': '全部', 'v': ''},
                    {'n': '国产剧', 'v': 'guochann'},
                    {'n': '香港剧', 'v': 'xianggangg'},
                    {'n': '台湾剧', 'v': 'taiwang'},
                    {'n': '韩国剧', 'v': 'hanguoo'},
                    {'n': '日本剧', 'v': 'ribenv'},
                    {'n': '欧美剧', 'v': 'oumeiu'},
                    {'n': '泰国剧', 'v': 'taiguog'},
                    {'n': '海外剧', 'v': 'haiwain'},
                    {'n': 'Netflix自制剧', 'v': 'zizhig'},
                ]},
            ],
            'zongyig': [
                {'key': 'genre', 'name': '地区', 'value': [
                    {'n': '全部', 'v': ''},
                    {'n': '大陆综艺', 'v': 'dalug'},
                    {'n': '港台综艺', 'v': 'gangtaiv'},
                    {'n': '日韩综艺', 'v': 'rihang'},
                    {'n': '欧美综艺', 'v': 'oumeiv'},
                ]},
            ],
            'dongmang': [
                {'key': 'genre', 'name': '地区', 'value': [
                    {'n': '全部', 'v': ''},
                    {'n': '国产动漫', 'v': 'guochano'},
                    {'n': '日本动漫', 'v': 'ribenw'},
                    {'n': '欧美动漫', 'v': 'oumeiw'},
                    {'n': '港台动漫', 'v': 'gangtaiw'},
                    {'n': '海外动漫', 'v': 'haiwaio'},
                    {'n': '里番动漫', 'v': 'lifang'},
                ]},
            ],
            'juchangg': [
                {'key': 'genre', 'name': '类型', 'value': [
                    {'n': '全部', 'v': ''},
                    {'n': '有声动漫', 'v': 'youshengg'},
                    {'n': '漫剧', 'v': 'manjun'},
                    {'n': 'AI漫剧', 'v': 'manjuo'},
                ]},
            ],
            'duanjug': [
                {'key': 'genre', 'name': '类型', 'value': [
                    {'n': '全部', 'v': ''},
                    {'n': '现代都市', 'v': 'xiandaig'},
                    {'n': '女频恋爱', 'v': 'nvping'},
                    {'n': '反转爽剧', 'v': 'fanzhuang'},
                    {'n': '古装仙侠', 'v': 'guzhuango'},
                    {'n': '年代穿越', 'v': 'niandaig'},
                    {'n': '脑洞悬疑', 'v': 'naodongg'},
                    {'n': '成长逆袭', 'v': 'chengzhangh'},
                    {'n': '战神', 'v': 'zhanshenh'},
                    {'n': '豪门', 'v': 'haomenh'},
                    {'n': '擦边短剧', 'v': 'cabianh'},
                ]},
            ],
            'yingshih': [
                {'key': 'genre', 'name': '类型', 'value': [
                    {'n': '全部', 'v': ''},
                    {'n': '电影解说', 'v': 'dianyingag'},
                    {'n': '预告解说', 'v': 'yugaor'},
                    {'n': '预告片', 'v': 'yugaos'},
                    {'n': '剧情介绍', 'v': 'juqingr'},
                ]},
            ],
        }

    def _fetch(self, url):
        """统一请求，兼容各种 TVBox fetch 实现"""
        resp = None
        # 尝试多种调用方式
        try:
            resp = self.fetch(url, headers=self.headers, timeout=10)
        except TypeError:
            # 某些 TVBox 版本 fetch 不支持 timeout 参数
            try:
                resp = self.fetch(url, headers=self.headers)
            except Exception:
                return ''
        except Exception:
            return ''

        if resp is None:
            return ''
        # TVBox fetch 可能直接返回字符串
        if isinstance(resp, str):
            return resp
        # 可能返回 bytes
        if isinstance(resp, bytes):
            return resp.decode('utf-8')
        # 标准 Response 对象
        if hasattr(resp, 'text'):
            return resp.text
        return str(resp)

    def _parse_extend(self, extend):
        """解析 extend 参数，兼容 dict / json字符串 / 空值"""
        if extend is None:
            return {}
        if isinstance(extend, dict):
            return extend
        if isinstance(extend, str):
            extend = extend.strip()
            if not extend:
                return {}
            try:
                return json.loads(extend)
            except Exception:
                return {}
        return {}

    def _normalize_tid(self, tid):
        """标准化分类ID，兼容中文名称传入"""
        tid = str(tid).strip() if tid else ''
        # 如果传入的是中文分类名，映射为 type_id
        if tid in self.categories.values():
            for k, v in self.categories.items():
                if v == tid:
                    return k
        return tid

    def _parse_cards(self, html):
        """解析影片卡片列表"""
        videos = []
        if not html:
            return videos
        # 兼容 article 标签中可能存在的其他属性
        cards = re.findall(
            r'<article\b[^>]*class="wu-poster-card"[^>]*>(.*?)</article>',
            html, re.DOTALL
        )
        for card in cards:
            m_id = re.search(r'href="/watch/([^"/]+)\.html"', card)
            if not m_id:
                continue
            vid = m_id.group(1)
            if any(v['vod_id'] == vid for v in videos):
                continue
            m_name = re.search(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>.*?</h3>', card, re.DOTALL)
            name = re.sub(r'<[^>]+>', '', m_name.group(1)).strip() if m_name else ''
            pic = ''
            m_pic = re.search(r'data-cover-src="(/cdn-uploads/[^"]+)"', card)
            if m_pic:
                pic = self.site_url + m_pic.group(1)
            else:
                m_pic2 = re.search(r'src="(/cdn-uploads/[^"]+)"', card)
                if m_pic2:
                    pic = self.site_url + m_pic2.group(1)
            m_remark = re.search(r'<p>(.*?)</p>', card, re.DOTALL)
            remark = re.sub(r'<[^>]+>', '', m_remark.group(1)).strip() if m_remark else ''
            videos.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic if pic else self.default_pic,
                'vod_remarks': remark,
            })
        return videos

    def homeContent(self, filter):
        html = self._fetch(self.site_url + '/')
        videos = self._parse_cards(html)[:30]
        classes = [{'type_id': k, 'type_name': v} for k, v in self.categories.items()]
        filters = {k: v for k, v in self.filters.items()}
        return {'class': classes, 'list': videos, 'filters': filters}

    def homeVideoContent(self):
        html = self._fetch(self.site_url + '/')
        videos = self._parse_cards(html)[:30]
        return {'list': videos}

    def categoryContent(self, tid, pg, filter, extend):
        # 解析页码
        try:
            page = int(float(pg)) if pg else 1
        except Exception:
            page = 1
        page = max(1, page)

        tid = self._normalize_tid(tid)
        ext = self._parse_extend(extend)

        # 兼容 TVBox 标准筛选键名（genre / class）
        genre = ext.get('genre', '') or ext.get('class', '')
        if genre and isinstance(genre, str):
            genre = genre.strip()

        path = '/watch/' + tid
        if genre:
            path += '/' + genre
        if page > 1:
            path += '?page=' + str(page)

        url = self.site_url + path
        html = self._fetch(url)
        videos = self._parse_cards(html)

        # 分页判断
        has_next = False
        pag_match = re.search(
            r'<nav[^>]*class="pagination"[^>]*>(.*?)</nav>',
            html, re.DOTALL | re.I
        )
        if pag_match:
            pag_html = pag_match.group(1)
            next_match = re.search(
                r'<a[^>]*href="([^"]*)"[^>]*>下一页</a>',
                pag_html
            )
            if next_match and next_match.group(1):
                has_next = True

        pagecount = page + 1 if has_next else page
        return {
            'list': videos,
            'page': page,
            'pagecount': pagecount,
            'limit': 24,
            'total': page * 24 + (1 if has_next else 0),
        }

    def searchContent(self, key, quick, pg='1'):
        try:
            page = int(float(pg)) if pg else 1
        except Exception:
            page = 1
        page = max(1, page)

        encoded = urllib.parse.quote(key)
        url = self.site_url + '/watch/search=' + encoded
        if page > 1:
            url += '?page=' + str(page)
        html = self._fetch(url)
        videos = self._parse_cards(html)

        has_next = False
        pag_match = re.search(
            r'<nav[^>]*class="pagination"[^>]*>(.*?)</nav>',
            html, re.DOTALL | re.I
        )
        if pag_match:
            pag_html = pag_match.group(1)
            next_match = re.search(
                r'<a[^>]*href="([^"]*)"[^>]*>下一页</a>',
                pag_html
            )
            if next_match and next_match.group(1):
                has_next = True

        pagecount = page + 1 if has_next else page
        return {
            'list': videos,
            'page': page,
            'pagecount': pagecount,
            'limit': 24,
            'total': page * 24 + (1 if has_next else 0),
        }

    def detailContent(self, ids):
        if not ids:
            return {'list': []}
        vid = ids[0]
        url = self.site_url + '/watch/' + vid + '.html'
        html = self._fetch(url)
        if not html:
            return {'list': []}

        m_title = re.search(r'<h1[^>]*itemprop="name"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if not m_title:
            m_title = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', m_title.group(1)).strip() if m_title else ''

        pic = ''
        m_pic = re.search(r'<img class="wu-detail-backdrop" src="(/cdn-uploads/[^"]+)"', html)
        if m_pic:
            pic = self.site_url + m_pic.group(1)
        else:
            m_pic = re.search(r'data-cover-src="(/cdn-uploads/[^"]+)"', html)
            if m_pic:
                pic = self.site_url + m_pic.group(1)

        meta_lines = re.findall(r'<p class="wu-detail-meta"[^>]*>(.*?)</p>', html, re.DOTALL)
        type_name = year = area = ''
        director = actor = ''
        content = ''

        for line in meta_lines:
            txt = re.sub(r'<[^>]+>', '', line).strip()
            if txt.startswith('导演：'):
                director = txt.replace('导演：', '').strip()
            elif txt.startswith('主演：'):
                actor = txt.replace('主演：', '').strip()
            elif '　/　' in txt or ' / ' in txt:
                parts = [p.strip() for p in re.split(r'[/／]', txt)]
                if len(parts) >= 3:
                    type_name = parts[0]
                    year = parts[1]
                    area = parts[2]

        m_summary = re.search(r'<p class="wu-detail-summary"[^>]*>(.*?)</p>', html, re.DOTALL)
        if m_summary:
            content = re.sub(r'<[^>]+>', '', m_summary.group(1)).strip()

        play_from = ['浮光影视']
        play_url = []

        ep_list = []
        m_ep_div = re.search(r'<div class="wu-episode-list"[^>]*>(.*?)</div>', html, re.DOTALL)
        if m_ep_div:
            ep_div = m_ep_div.group(1)
            eps = re.findall(r'<a[^>]*href="(/play/[^"]+)"[^>]*>(.*?)</a>', ep_div, re.DOTALL)
            for href, txt in eps:
                ep_name = re.sub(r'<[^>]+>', '', txt).strip()
                ep_list.append(ep_name + '$' + href)
        else:
            m_play = re.search(r'<a[^>]*href="(/play/[^"]+)"[^>]*>(立即播放|正片)</a>', html, re.DOTALL)
            if m_play:
                ep_list.append('正片$' + m_play.group(1))

        if ep_list:
            play_url.append('#'.join(ep_list))
        else:
            play_url.append('正片$' + url)

        result = [{
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': pic if pic else self.default_pic,
            'vod_content': content,
            'vod_actor': actor,
            'vod_director': director,
            'vod_year': year,
            'vod_area': area,
            'vod_type': type_name,
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }]
        return {'list': result}

    def playerContent(self, flag, id, vipFlags):
        if not id.startswith('/play/'):
            return {'parse': 1, 'url': id, 'header': self.headers}

        url = self.site_url + id
        html = self._fetch(url)
        if not html:
            return {'parse': 1, 'url': id, 'header': self.headers}

        m_token = re.search(r'data-player-token="([^"]+)"', html)
        if not m_token:
            m_token = re.search(r'data-video-token="([^"]+)"', html)

        if m_token:
            try:
                decoded = base64.b64decode(m_token.group(1)).decode('utf-8')
                if decoded.startswith('http') and ('.m3u8' in decoded or '.mp4' in decoded):
                    return {
                        'parse': 0,
                        'url': decoded,
                        'header': {
                            'User-Agent': self.headers['User-Agent'],
                            'Referer': self.site_url + '/',
                        }
                    }
            except Exception:
                pass

        return {
            'parse': 1,
            'url': url,
            'header': self.headers
        }
