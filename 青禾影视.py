# -*- coding: utf-8 -*-
import sys
import re
import json
import requests
import base64
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            import requests as rq
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r

HOST = "https://qh3.movie1080.online/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

CLASS_MAP = {
    "20": "电影",
    "37": "电视剧",
    "43": "动漫",
    "45": "综艺",
    "55": "短剧",
    "56": "下饭剧",
    "47": "B站",
}

class Spider(Spider):

    def init(self, extend=""):
        pass

    def getName(self):
        return "juok3"

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url or ".flv" in url

    def manualVideoCheck(self):
        return True

    def _cover(self, raw):
        if not raw:
            return ""
        if raw.startswith("//"):
            return "https:" + raw
        return raw

    def homeContent(self, filter=False):
        classes = []
        for tid, name in CLASS_MAP.items():
            classes.append({"type_id": tid, "type_name": name})
        return {"class": classes}

    def homeVideoContent(self):
        try:
            url = f"{HOST}/"
            r = self.fetch(url, headers={"User-Agent": UA}, timeout=15000)
            soup = BeautifulSoup(r.text, 'html.parser')
            
            items = []
            for li in soup.find_all('div', class_='public-list-box'):
                a = li.find('a', class_='public-list-exp')
                if a:
                    href = a.get('href', '')
                    title = a.get('title', '')
                    img = a.find('img')
                    img_src = img.get('data-src', '') if img else ''
                    remarks_span = li.find('span', class_='public-list-prb')
                    remarks = remarks_span.text.strip() if remarks_span else ''
                    
                    match = re.search(r'/vod(?:play|detail)/(\d+)', href)
                    if match:
                        vid = f"detail:37:{match.group(1)}"
                        items.append({
                            "vod_id": vid,
                            "vod_name": title,
                            "vod_pic": self._cover(img_src),
                            "vod_remarks": remarks,
                        })
            return {"list": items[:30]}
        except:
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        try:
            pn = max(int(pg), 1)
            url = f"{HOST}/vodtype/{tid}-{pn}.html"
            r = self.fetch(url, headers={"User-Agent": UA}, timeout=30000)
            soup = BeautifulSoup(r.text, 'html.parser')
            
            items = []
            for li in soup.find_all('div', class_='public-list-box'):
                a = li.find('a', class_='public-list-exp')
                if a:
                    href = a.get('href', '')
                    title = a.get('title', '')
                    img = a.find('img')
                    img_src = img.get('data-src', '') if img else ''
                    remarks_span = li.find('span', class_='public-list-prb')
                    remarks = remarks_span.text.strip() if remarks_span else ''
                    
                    match = re.search(r'/vod(?:play|detail)/(\d+)', href)
                    if match:
                        vid = f"detail:{tid}:{match.group(1)}"
                        items.append({
                            "vod_id": vid,
                            "vod_name": title,
                            "vod_pic": self._cover(img_src),
                            "vod_remarks": remarks,
                        })
            
            page_html = soup.find('div', class_='page')
            pagecount = 1
            if page_html:
                pages = page_html.find_all('a')
                if pages:
                    nums = []
                    for p in pages:
                        if p.text.isdigit():
                            nums.append(int(p.text))
                    if nums:
                        pagecount = max(nums)
            
            return {
                "list": items,
                "page": pn,
                "pagecount": pagecount,
                "limit": 24,
                "total": 0,
            }
        except:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 24, "total": 0}

    def detailContent(self, ids):
        try:
            vid = str(ids[0])
            if not vid.startswith("detail:"):
                return {"list": []}
            
            parts = vid.split(":", 2)
            if len(parts) != 3:
                return {"list": []}
            
            cat_id, vod_id = parts[1], parts[2]
            url = f"{HOST}/voddetail/{vod_id}.html"
            r = self.fetch(url, headers={"User-Agent": UA}, timeout=30000)
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # 1. 影片名称 - 从h2获取
            title = ""
            h2 = soup.find('h2', class_='title-h')
            if h2:
                title = h2.text.strip()
            
            # 2. 封面
            cover = ""
            img = soup.find('img', class_='lazy')
            if img:
                cover = img.get('data-src', '') or img.get('src', '')
            
            # 3. 分类标签 - this-desc-labels里面的this-tag
            type_label = ""
            labels_div = soup.find('div', class_='this-desc-labels')
            if labels_div:
                tag = labels_div.find('span', class_='this-tag')
                if tag:
                    type_label = tag.text.strip()
            
            # 4. 年份、地区、备注 - this-desc-info里的span
            year = ""
            area = ""
            remarks = ""
            info_div = soup.find('div', class_='this-desc-info')
            if info_div:
                spans = info_div.find_all('span')
                for span in spans:
                    text = span.text.strip()
                    if not text or text == '0.0' or '收藏' in text:
                        continue
                    if text.isdigit() and len(text) == 4:
                        year = text
                    elif '集' in text or '全' in text or '更新' in text:
                        remarks = text
                    elif not area:
                        area = text
            
            # 5. 类型标签 - this-desc-tags里的span
            tags = []
            tags_div = soup.find('div', class_='this-desc-tags')
            if tags_div:
                for span in tags_div.find_all('span'):
                    tags.append(span.text.strip())
            type_name = " ".join(tags) if tags else type_label
            
            # 6. 导演和演员 - 从this-text中提取
            director = ""
            actor = ""
            year_text = ""
            
            for p in soup.find_all('p', class_='this-text'):
                em = p.find('em')
                if not em:
                    continue
                em_text = em.text.strip()
                
                if '导演' in em_text:
                    names = []
                    for a in p.find_all('a'):
                        names.append(a.text.strip())
                    director = " ".join(names)
                elif '主演' in em_text:
                    names = []
                    for a in p.find_all('a'):
                        names.append(a.text.strip())
                    actor = " ".join(names)
                elif '年份' in em_text:
                    for a in p.find_all('a'):
                        year_text = a.text.strip()
                        if year_text.isdigit() and len(year_text) == 4:
                            year = year_text
            
            # 7. 简介 - this-desc里的text
            content = ""
            desc_div = soup.find('div', class_='this-desc')
            if desc_div:
                text_div = desc_div.find('div', class_='text')
                if text_div:
                    content = text_div.text.strip()
                    content = re.sub(r'^描述：', '', content).strip()
            
            # 8. 播放列表
            pf_list = []
            pu_list = []
            
            tab_divs = soup.find_all('div', class_='anthology-list-box')
            tab_links = soup.find_all('a', class_='vod-playerUrl')
            
            for idx, tab in enumerate(tab_divs):
                source_name = f"线路{idx+1}"
                if idx < len(tab_links):
                    source_name = tab_links[idx].text.strip()
                    source_name = re.sub(r'[]', '', source_name).strip()
                    if not source_name:
                        source_name = f"线路{idx+1}"
                
                ep_list = []
                for li in tab.find_all('li'):
                    a = li.find('a')
                    if a:
                        href = a.get('href', '')
                        ep_name = a.text.strip()
                        if href:
                            full_url = urljoin(HOST, href)
                            ep_list.append(f"{ep_name}${full_url}")
                
                if ep_list:
                    pf_list.append(source_name)
                    pu_list.append("#".join(ep_list))
            
            if not pf_list:
                play_list = soup.find('ul', class_='anthology-list-play')
                if play_list:
                    ep_list = []
                    for li in play_list.find_all('li'):
                        a = li.find('a')
                        if a:
                            href = a.get('href', '')
                            ep_name = a.text.strip()
                            if href:
                                full_url = urljoin(HOST, href)
                                ep_list.append(f"{ep_name}${full_url}")
                    if ep_list:
                        pf_list.append("播放源")
                        pu_list.append("#".join(ep_list))
            
            if not pf_list:
                return {"list": []}
            
            vod_data = {
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": self._cover(cover),
                "vod_year": year,
                "vod_area": area,
                "vod_class": type_name,
                "vod_director": director,
                "vod_actor": actor,
                "vod_content": content,
                "vod_remarks": remarks,
                "vod_play_from": "$$$".join(pf_list),
                "vod_play_url": "$$$".join(pu_list),
            }
            
            return {"list": [vod_data]}
        except Exception as e:
            return {"list": []}

    def searchContent(self, key, quick=False, pg=1):
        try:
            pn = max(int(pg), 1)
            url = f"{HOST}/vodsearch/-------------.html?wd={quote(key)}&page={pn}"
            r = self.fetch(url, headers={"User-Agent": UA}, timeout=30000)
            soup = BeautifulSoup(r.text, 'html.parser')
            
            items = []
            for li in soup.find_all('div', class_='public-list-box'):
                a = li.find('a', class_='public-list-exp')
                if a:
                    href = a.get('href', '')
                    title = a.get('title', '')
                    img = a.find('img')
                    img_src = img.get('data-src', '') if img else ''
                    remarks_span = li.find('span', class_='public-list-prb')
                    remarks = remarks_span.text.strip() if remarks_span else ''
                    
                    match = re.search(r'/vod(?:play|detail)/(\d+)', href)
                    if match:
                        vid = f"detail:37:{match.group(1)}"
                        items.append({
                            "vod_id": vid,
                            "vod_name": title,
                            "vod_pic": self._cover(img_src),
                            "vod_remarks": remarks,
                        })
            return {"list": items, "page": pn}
        except:
            return {"list": [], "page": 1}

    def playerContent(self, flag, id, vipFlags=None):
        url = str(id) if id else str(flag)
        if "$" in url:
            parts = url.split("$", 1)
            url = parts[1]
        return {"url": url, "parse": 1, "header": {"User-Agent": UA}}

    def localProxy(self, param):
        pass