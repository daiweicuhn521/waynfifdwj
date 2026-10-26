# coding=utf-8
import sys
import json
import re
import urllib.request
from bs4 import BeautifulSoup

sys.path.append('..')
from base.spider import Spider

class Spider(Spider):

    def init(self, extend=""):
        self.site_url = "https://www.4kdyws.top"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': self.site_url,
        }
        self.categories = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "3", "type_name": "动漫"},
            {"type_id": "4", "type_name": "综艺"}
        ]
        self.original_line_names = ['极速二', '极速三', '极速四']
        self.display_line_names = ['丰之玲', 'QQ交流群:212706934', '源码交流群']
        self.line_codes = {'极速二': '1', '极速三': '3', '极速四': '2'}

    def homeContent(self, filter):
        return {"class": self.categories}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        if page == 1:
            url = f"{self.site_url}/vodcate/{tid}.html"
        else:
            url = f"{self.site_url}/vodcate/{tid}-{page}.html"

        try:
            req = urllib.request.Request(url, headers=self.headers)
            resp = urllib.request.urlopen(req, timeout=10)
            html = resp.read().decode('utf-8', errors='ignore')
            resp.close()
        except:
            return {"list": [], "page": page, "pagecount": 1}

        soup = BeautifulSoup(html, 'html.parser')
        video_list = []

        for item in soup.select('.stui-vodlist__box'):
            a = item.select_one('a.stui-vodlist__thumb')
            if not a:
                continue
            href = a.get('href', '')
            if '/voddetail/' not in href:
                continue
            vod_id = href.replace('/voddetail/', '').replace('.html', '')
            name = a.get('title', '')
            img = item.select_one('img')
            pic = img.get('data-original', '') or img.get('src', '') if img else ''
            remark = item.select_one('.pic-text')
            remarks = remark.text.strip() if remark else ''
            video_list.append({
                "vod_id": vod_id,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remarks
            })

        return {"list": video_list, "page": page, "pagecount": 10}

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = ids[0]

        play_from_list = []
        play_url_list = []
        vod_name = ""
        vod_pic = ""
        vod_director = ""
        vod_actor = ""
        vod_content = ""
        vod_remarks = ""

        try:
            url = f"{self.site_url}/voddetail/{vod_id}.html"
            req = urllib.request.Request(url, headers=self.headers)
            resp = urllib.request.urlopen(req, timeout=10)
            html = resp.read().decode('utf-8', errors='ignore')
            resp.close()

            soup = BeautifulSoup(html, 'html.parser')
            title_tag = soup.select_one('h1')
            if title_tag:
                vod_name = title_tag.text.strip()
            img_tag = soup.select_one('.stui-content__thumb img')
            if img_tag:
                vod_pic = img_tag.get('data-original', '') or img_tag.get('src', '')
            for li in soup.select('.stui-content__detail li'):
                text = li.text.strip()
                if '导演：' in text:
                    vod_director = text.replace('导演：', '').strip()
                elif '主演：' in text:
                    vod_actor = text.replace('主演：', '').strip()
                elif '状态：' in text:
                    vod_remarks = text.replace('状态：', '').strip()
            desc = soup.select_one('.stui-content__detail .desc')
            if desc:
                vod_content = desc.text.strip()

            json_match = re.search(r'<script id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
                def find_vod_play(obj):
                    if isinstance(obj, dict):
                        if 'vod_play' in obj and isinstance(obj['vod_play'], list):
                            return obj['vod_play']
                        for v in obj.values():
                            result = find_vod_play(v)
                            if result:
                                return result
                    elif isinstance(obj, list):
                        for item in obj:
                            result = find_vod_play(item)
                            if result:
                                return result
                    return None
                vod_play = find_vod_play(data)
                if vod_play:
                    for item in vod_play:
                        line_name = '未知'
                        if 'collectSource' in item and isinstance(item['collectSource'], dict):
                            line_name = item['collectSource'].get('webName', '未知')
                        play_url = item.get('vodPlayUrl', '')
                        if play_url:
                            play_from_list.append(line_name)
                            play_url_list.append(play_url)
        except:
            pass

        if not play_from_list:
            total_episodes = 1
            if vod_remarks:
                match = re.search(r'(\d+)', vod_remarks)
                if match:
                    total_episodes = int(match.group(1))

            if total_episodes > 30:
                total_episodes = 30

            for idx, line_name in enumerate(self.original_line_names):
                display_name = self.display_line_names[idx] if idx < len(self.display_line_names) else line_name
                line_code = self.line_codes.get(line_name, '1')
                episodes = []
                for i in range(1, total_episodes + 1):
                    play_url = f"{self.site_url}/vodplay/{vod_id}-{line_code}-{i}.html"
                    episodes.append(f"第{i:02d}集${play_url}")
                play_from_list.append(display_name)
                play_url_list.append('#'.join(episodes))

        if not play_from_list:
            play_from_list.append('播放')
            play_url_list.append(f"第1集${self.site_url}/vodplay/{vod_id}-1-1.html")

        result = [{
            "vod_id": vod_id,
            "vod_name": vod_name or f"视频_{vod_id}",
            "vod_pic": vod_pic,
            "vod_content": vod_content,
            "vod_actor": vod_actor,
            "vod_director": vod_director,
            "vod_area": "",
            "vod_year": "",
            "vod_remarks": vod_remarks,
            "vod_play_from": '$$$'.join(play_from_list),
            "vod_play_url": '$$$'.join(play_url_list)
        }]

        return {"list": result}

    def playerContent(self, flag, id, vipFlags):
        if id.startswith('http'):
            url = id
        elif id.startswith('/'):
            url = self.site_url + id
        else:
            url = self.site_url + '/vodplay/' + id
        return {"parse": 1, "url": url, "header": self.headers}

    def searchContent(self, key, quick, pg="1"):
        return {"list": [], "page": 1, "pagecount": 1}