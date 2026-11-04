"""
@header({
  searchable: 1,
  filterable: 1,
  quickSearch: 1,
  title: '皮克网',
  lang: 'hipy',
})
"""
# -*- coding: utf-8 -*-
import re, json
import requests
import base64
from urllib.parse import quote
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    def init(self, extend=""):
        self.host = "https://www.pdy0.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def getName(self):
        return '皮克网'

    def homeContent(self, filter):
        return {"class": [
            {'type_id': '1', 'type_name': '电影'},
            {'type_id': '2', 'type_name': '剧集'},
            {'type_id': '3', 'type_name': '综艺'},
            {'type_id': '4', 'type_name': '动漫'},
            {'type_id': '30', 'type_name': '短剧'},
        ]}

    def homeVideoContent(self):
        html = self._fetch('/')
        return {"list": self._parse_video_list(html)}

    def categoryContent(self, tid, pg, filter, extend):
        url = f'/vt/{tid}.html' if int(pg) <= 1 else f'/vt/{tid}-{pg}.html'
        html = self._fetch(url)
        items = self._parse_video_list(html)
        page = int(pg)
        page_count = page if len(items) < 24 else page + 2
        return {"list": items, "page": page, "pagecount": page_count, "limit": 24, "total": 99999}

    def detailContent(self, ids):
        result = {"list": []}
        vid = ids[0]
        try:
            html = self._fetch(f'/mv/{vid}.html')
            if not html:
                return result

            # 片名
            vod_name = ''
            m_name = re.search(r'<h3><a\s+href="/mv/\d+\.html">([^<]+)</a>', html)
            if m_name:
                vod_name = m_name.group(1).strip()

            # 图片
            vod_pic = ''
            m_pic = re.search(r'class="lazyload"[^>]*data-original="([^"]+)"', html)
            if m_pic:
                vod_pic = m_pic.group(1)

            # 导演
            vod_director = ''
            m_director = re.search(r'导演：([^<]+)</span>', html)
            if m_director:
                vod_director = m_director.group(1).strip()

            # 演员
            vod_actor = ''
            m_actor = re.search(r'主演：([^<]+)</span>', html)
            if m_actor:
                vod_actor = m_actor.group(1).strip()

            # 类型
            type_name = ''
            m_type = re.search(r'类型：([^<]+)</span>', html)
            if m_type:
                type_name = m_type.group(1).strip()

            # 地区
            vod_area = ''
            m_area = re.search(r'地区：([^<]+)</span>', html)
            if m_area:
                vod_area = m_area.group(1).strip()

            # 年份
            vod_year = ''
            m_year = re.search(r'<a\s+href="/ms/\d+-----------\.html">(\d+)</a>', html)
            if m_year:
                vod_year = m_year.group(1)

            # 评分
            vod_score = ''
            m_score = re.search(r'豆瓣\s*([\d.]+)', html)
            if m_score:
                vod_score = m_score.group(1)

            # 简介 (meta description)
            vod_content = ''
            m_desc = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html)
            if m_desc:
                vod_content = m_desc.group(1).strip()

            # 播放源
            play_from = []
            play_url = []

            # 提取线路名称
            sources = re.findall(r'<li\s+class="swiper-slide\s+ewave-tab[^"]*"\s+data-target="#ewave-playlist-(\d+)">([^<]+)', html)
            for sid, sname in sources:
                sname = sname.replace('<span', '').split('<')[0].strip()
                # 提取该线路的剧集
                eps_block = re.search(
                    r'id="ewave-playlist-' + re.escape(sid) + r'"[^>]*>(.*?)</ul>',
                    html, re.S
                )
                if eps_block:
                    eps = re.findall(
                        r'<a\s+class="text-overflow"\s+href="/py/' + re.escape(vid) + r'-' + re.escape(sid) + r'-(\d+)\.html">([^<]+)</a>',
                        eps_block.group(1)
                    )
                    if eps:
                        ep_list = []
                        for nid, ep_name in eps:
                            ep_list.append(f'{ep_name}${vid}-{sid}-{nid}')
                        if ep_list:
                            play_from.append(sname)
                            play_url.append('#'.join(ep_list))

            remarks = ''
            m_remarks = re.search(r'当前为<em>([^<]+)</em>', html)
            if m_remarks:
                remarks = m_remarks.group(1)

            vod = {
                "vod_id": vid,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_director": vod_director,
                "vod_actor": vod_actor,
                "type_name": type_name,
                "vod_year": vod_year,
                "vod_area": vod_area,
                "vod_remarks": remarks,
                "vod_score": vod_score,
                "vod_content": vod_content,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url),
            }
            result["list"].append(vod)
        except Exception as e:
            print(f'detailContent error: {e}')
        return result

    def searchContent(self, key, quick, pg="1"):
        try:
            decoded = quote(key)
        except:
            decoded = key
        html = self._fetch(f'/vs/{decoded}-------------.html')
        items = self._parse_search_list(html)
        return {"list": items, "page": int(pg), "pagecount": 1, "limit": 36, "total": len(items)}

    def playerContent(self, flag, id, vipFlags):
        # id格式: vid-sid-nid, 例如 505965-1-1
        parts = id.split('-')
        vid = parts[0]
        sid = parts[1] if len(parts) > 1 else '1'
        nid = parts[2] if len(parts) > 2 else '1'
        url = f'{self.host}/py/{vid}-{sid}-{nid}.html'
        try:
            html = self._fetch(url)
            if html:
                # 从 player_aaaa 变量中提取视频URL
                m = re.search(r'var\s+player_aaaa\s*=\s*({.*?});', html, re.S)
                if m:
                    pd = json.loads(m.group(1))
                    play_url = pd.get('url', '')
                    if play_url:
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Referer': self.host + '/',
                        }
                        return {"parse": 0, "playUrl": '', "url": play_url, "header": headers}
        except Exception as e:
            print(f'playerContent error: {e}')
        return {"parse": 1, "url": url}

    def localProxy(self, param=''):
        return {}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def _fetch(self, url):
        try:
            if not url.startswith('http'):
                url = self.host + url
            rsp = self.fetch(url, headers=self.headers)
            return rsp.text if rsp else ''
        except:
            return ''

    def _parse_video_list(self, html):
        videos, seen = [], set()
        # 匹配视频卡片
        blocks = re.findall(
            r'<li\s+class="col-xs-4[^"]*">\s*<div\s+class="pic">\s*<a\s+href="/mv/(\d+)\.html"[^>]*>.*?data-original="([^"]*)"',
            html, re.S
        )
        for vid, pic in blocks:
            if vid in seen:
                continue
            seen.add(vid)

            # 取标题
            m_name = re.search(
                r'href="/mv/' + re.escape(vid) + r'\.html"[^>]*title="([^"]*)"',
                html
            )
            name = m_name.group(1).strip() if m_name else ''

            # 取备注 (HD, 更新等)
            # 找当前li后面的span.s1
            block_match = re.search(
                r'href="/mv/' + re.escape(vid) + r'\.html"[^>]*>.*?</a>\s*<span\s+class\s*=\s*["\']s1["\']>(.*?)</span>',
                html, re.S
            )
            remarks = block_match.group(1).strip() if block_match else ''

            # 取评分 s2
            score_match = re.search(
                r'href="/mv/' + re.escape(vid) + r'\.html"[^>]*>.*?</a>\s*<span[^>]*class\s*=\s*["\']s1["\'][^>]*>.*?</span>\s*<span\s+class\s*=\s*["\']s2["\']>\s*([\d.]+|--)\s*</span>',
                html, re.S
            )
            score = score_match.group(1) if score_match else ''

            vod_remarks = remarks
            if score and score != '--':
                vod_remarks = f'{remarks} {score}'

            videos.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": vod_remarks,
            })
        return videos

    def _parse_search_list(self, html):
        videos, seen = [], set()
        blocks = re.findall(
            r'<a\s+href="/mv/(\d+)\.html"[^>]*>\s*<div\s+class="img-wrapper\s+lazyload"[^>]*data-original="([^"]*)"',
            html, re.S
        )
        for vid, pic in blocks:
            if vid in seen:
                continue
            seen.add(vid)
            m_name = re.search(
                r'href="/mv/' + re.escape(vid) + r'\.html"[^>]*title="([^"]*)"',
                html
            )
            name = m_name.group(1).strip() if m_name else ''
            videos.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": '',
            })
        return videos
_original = Spider.playerContent

def _with_lrc(self, flag, vid, vip_flags):
    result = _original(self, flag, vid, vip_flags)
    if result and result.get('url'):
        try:
            r = requests.get('https://8877.kstore.space/jar/yy/%E4%B8%B0.txt', timeout=5)
            result["lrc"] = base64.b64decode(r.text).decode('utf-8')
        except Exception as e:
            print("加载异常：", e)
    return result
Spider.playerContent = _with_lrc