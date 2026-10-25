# -*- coding: utf-8 -*-
# 文件名：82dj.py
# 站点：82DJ舞曲网 (https://www.82dj.com & https://m.82dj.com)
# 版本：全功能稳定最终版（完美播放、正确封面版）

import sys
import re
import json
import requests
from urllib.parse import urljoin, quote

sys.path.append('..')

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        pass

class Spider(BaseSpider):

    def __init__(self):
        self.host = "https://www.82dj.com"
        self.m_host = "https://m.82dj.com"
        
        # 获取网页列表用的移动端 UA
        self.web_headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        
        # 交给播放器用的 PC 端 UA（防止 CDN 拦截移动端）
        self.play_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.82dj.com/"
        }
        
        self.session = requests.Session()
        self.session.headers.update(self.web_headers)

    def init(self, extend=""):
        pass

    def getName(self):
        return "82DJ舞曲网"

    def homeContent(self, filter):
        # 车载MV第1个，其余按图序
        return {
            "class": [
                {"type_id": "video_list/30",  "type_name": "车载MV"},
                {"type_id": "video_list/18",  "type_name": "夜店视频"},
                {"type_id": "video_list/17",  "type_name": "热舞视频"},
                {"type_id": "video_list/24",  "type_name": "写真视频"},
                {"type_id": "video_list/29",  "type_name": "酒吧背景"},
            ],
            "filters": {}
        }

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        result = {"list": [], "page": int(pg), "pagecount": 9999, "limit": 30, "total": 9999}
        try:
            if tid == "top":
                url = f"{self.host}/top"
                r = self.session.get(url, timeout=15)
                result["list"] = self.parse_dance_list(r.text)
                result["pagecount"] = 1
                return result

            if tid.startswith("video_list/"):
                sub = tid.split("/")[1]
                url = f"{self.m_host}/video_list/{sub}-0-0-{pg}"
                r = self.session.get(url, timeout=15)
                videos = self.parse_video_list_mobile(r.text)
                
                if not videos:
                    pc_url = f"{self.host}/video_list/{sub}-0-0-{pg}"
                    r_pc = self.session.get(pc_url, timeout=15)
                    videos = self.parse_video_list_pc(r_pc.text)

                result["list"] = videos
                
                m = re.search(r'/video_list/[^"\' ]*-(\d+)["\']', r.text)
                if m:
                    result["pagecount"] = max(int(pg) + 1, int(m.group(1)))
                return result
        except Exception as e:
            print(f"[82DJ] categoryContent error: {e}")
        return result

    # =================== 列表解析模块 ===================
    
    def parse_dance_list(self, html):
        videos = []
        blocks = re.split(r'(?=<div[^>]*class="[^"]*isgood_list)', html)
        for block in blocks:
            if 'isgood_list' not in block: continue
            try:
                vid_m = re.search(r'data-bs-id="(\d+)"', block) or re.search(r'/(?:play|down/dance)-?(\d+)', block)
                if not vid_m: continue
                vid = vid_m.group(1)

                pic = ""
                pic_m = re.search(r'<img[^>]+(?:data-original|src)="([^"]+)"', block)
                if pic_m:
                    pic = pic_m.group(1)
                    if not pic.startswith("http"): pic = urljoin(self.host, pic)

                name = ""
                name_m = re.search(r'class=["\']t1[^"\']*["\'][^>]*>\s*<a[^>]*>(.*?)</a>', block, re.S)
                if name_m: name = re.sub(r'<[^>]+>', '', name_m.group(1)).strip()
                
                remark = ""
                tm_m = re.search(r'TIME[:：]\s*([0-9分秒]+)', block)
                sz_m = re.search(r'SIZE[:：]\s*([\d.]+\s*MB)', block)
                if tm_m: remark += tm_m.group(1).strip() + " "
                if sz_m: remark += sz_m.group(1).strip()

                videos.append({
                    "vod_id": vid, "vod_name": name or f"舞曲-{vid}", 
                    "vod_pic": pic, "vod_remarks": remark.strip()
                })
            except Exception:
                pass
        return videos

    def parse_video_list_pc(self, html):
        videos = []
        blocks = re.split(r'(?=<div[^>]*class="[^"]*isgood_list)', html)
        for block in blocks:
            if 'isgood_list' not in block: continue
            try:
                vid_m = re.search(r'/video/(\d+)', block)
                if not vid_m: continue
                vid = vid_m.group(1)

                pic = ""
                pic_m = re.search(r'<img[^>]+(?:data-original|src)="([^"]+)"', block)
                if pic_m:
                    pic = pic_m.group(1)
                    if not pic.startswith("http"): pic = urljoin(self.host, pic)

                name = ""
                name_m = re.search(r'class=["\']t1[^"\']*["\'][^>]*>\s*<a[^>]*>(.*?)</a>', block, re.S)
                if name_m: name = re.sub(r'<[^>]+>', '', name_m.group(1)).strip()

                remark = ""
                tm_m = re.search(r'TIME[:：]\s*([0-9分秒]+)', block)
                sz_m = re.search(r'SIZE[:：]\s*([\d.]+\s*MB)', block)
                if tm_m: remark += tm_m.group(1).strip() + " "
                if sz_m: remark += sz_m.group(1).strip()

                videos.append({
                    "vod_id": vid, "vod_name": name or f"视频-{vid}", 
                    "vod_pic": pic, "vod_remarks": remark.strip()
                })
            except Exception:
                pass
        return videos

    def parse_video_list_mobile(self, html):
        videos = []
        blocks = re.split(r'(?=<li[^>]*class="[^"]*td2)', html)
        if len(blocks) <= 1:
            blocks = [html] 
            
        for block in blocks:
            try:
                vid_m = re.search(r'/(?:video|play)/(\d+)', block)
                if not vid_m: continue
                vid = vid_m.group(1)
                
                items = re.split(r'(?=<div[^>]*class="[^"]*bt")', block)
                for item in items:
                    if f'/{vid}' not in item and 'video' not in item: continue
                    
                    pic = ""
                    pic_m = re.search(r'(?:data-original|src)=["\']([^"\']+)["\']', item)
                    if pic_m:
                        pic = pic_m.group(1)
                        if not pic.startswith("http"): pic = urljoin(self.m_host, pic)

                    name = ""
                    name_m = re.search(r'<a[^>]*>(.*?)</a>', item, re.S)
                    if name_m:
                        name = re.sub(r'<[^>]+>', '', name_m.group(1)).strip()
                        name = re.sub(r'^\d+', '', name).strip() 
                    
                    if not name: continue

                    videos.append({
                        "vod_id": vid, 
                        "vod_name": name, 
                        "vod_pic": pic, 
                        "vod_remarks": ""
                    })
                    break
            except Exception:
                pass
        return videos

    # =================== 详情页与播放解析 ===================

    def detailContent(self, ids):
        result = {"list": []}
        try:
            vid = str(ids[0]) if isinstance(ids, list) else str(ids)
            url = f"{self.m_host}/video/{vid}"
            r = self.session.get(url, timeout=15)
            html = r.text

            # 1. 提取完整标题
            title = f"视频-{vid}"
            title_m = re.search(r'<h3[^>]*class="m_title"[^>]*>(.*?)</h3>', html, re.S)
            if title_m:
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
            else:
                title_m = re.search(r'<title>(.*?)</title>', html, re.S)
                if title_m:
                    title = title_m.group(1).split('- 82DJ')[0].strip()

            # 2. 提取封面 (彻底避开 97.gif 广告图，只认 uploads/images 下的图片)
            pic = ""
            pic_m = re.search(r'(https?://[^"\']*?/uploads/images/[^"\']+\.(?:jpg|png|jpeg|webp))', html)
            if pic_m:
                pic = pic_m.group(1)
            else:
                pc_url = f"{self.host}/video/{vid}"
                r_pc = self.session.get(pc_url, timeout=15)
                pic_m2 = re.search(r'(https?://[^"\']*?/uploads/images/[^"\']+\.(?:jpg|png|jpeg|webp))', r_pc.text)
                if pic_m2:
                    pic = pic_m2.group(1)

            # 3. 提取播放地址并转码
            play_url = vid
            source_m = re.search(r'<source\s+src="([^"]+)"', html)
            if source_m:
                raw_url = source_m.group(1)
                if raw_url.startswith("http"):
                    parts = raw_url.split("/", 3)
                    if len(parts) == 4:
                        safe_path = quote(parts[3], safe="/")
                        play_url = f"{parts[0]}//{parts[2]}/{safe_path}"
                    else:
                        play_url = quote(raw_url, safe=":/")
            
            result["list"] = [{
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_content": title,
                "type_name": "车载视频",
                "vod_play_from": "82DJ",
                "vod_play_url": f"正片${play_url}",
            }]
        except Exception as e:
            print(f"[82DJ] detailContent error: {e}")
        return result

    def searchContent(self, key, quick, pg=1):
        result = {"list": []}
        try:
            clean_key = re.sub(r'[\[\]\(\)]', '', key).strip()
            url = f"{self.host}/search?search={quote(clean_key)}"
            r = self.session.get(url, timeout=15)
            html = r.text
            
            videos = self.parse_video_list_pc(html)
            if not videos:
                videos = self.parse_dance_list(html)
            if not videos:
                m_url = f"{self.m_host}/search?search={quote(clean_key)}"
                r_m = self.session.get(m_url, timeout=15)
                videos = self.parse_video_list_mobile(r_m.text)
                
            result["list"] = videos
        except Exception as e:
            print(f"[82DJ] searchContent error: {e}")
        return result

    def playerContent(self, flag, id, vipFlags):
        # 如果 id 是 http 开头，说明 detailContent 里已经成功抓到了直链
        if id.startswith("http"):
            # 这里的 header 必须使用 PC 端 UA，才能避开 CDN 的反盗链拦截
            return {
                "parse": 0, 
                "playUrl": "", 
                "url": id, 
                "header": json.dumps(self.play_headers)
            }
        return {"parse": 0, "playUrl": "", "url": "", "header": ""}