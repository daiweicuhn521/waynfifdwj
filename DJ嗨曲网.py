# -*- coding: utf-8 -*-
# DJ嗨曲网 - FongMi/影视壳 Python 爬虫
# 站点: http://www.djhaiqu.com/

import requests
import re
from bs4 import BeautifulSoup
import json
import codecs

from base.spider import Spider as BaseSpider


SITE = "http://www.djhaiqu.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Referer": SITE + "/",
}

# 分类映射
CATEGORY_MAP = {
    "wqu": {
        "type_name": "舞曲分类",
        "children": [
            ("1", "串烧舞曲"),
            ("2", "慢摇串烧"),
            ("3", "劲爆串烧"),
            ("4", "喊麦串烧"),
            ("5", "连版串烧"),
            ("6", "中文舞曲"),
            ("7", "英文舞曲"),
        ]
    },
    "bangdan": {
        "type_name": "榜单推荐",
        "children": [
            ("6", "精品推荐"),
            ("7", "昨日榜单"),
            ("8", "本周榜单"),
            ("9", "本月榜单"),
            ("10", "年度榜单"),
            ("11", "下载榜单"),
            ("12", "收藏榜单"),
        ]
    },
}


def _build_filters(tid):
    children = CATEGORY_MAP.get(tid, {}).get("children", [])
    values = [{"n": "全部", "v": ""}]
    for cid, cname in children:
        values.append({"n": cname, "v": cid})
    return [{"key": "class", "name": "类型", "value": values}]


ALL_FILTERS = {tid: _build_filters(tid) for tid in CATEGORY_MAP}


def _duration_to_seconds(s):
    """将 '00:59:42' 或 '06:09' 转为秒数"""
    if not s:
        return 0
    parts = str(s).strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        pass
    return 0


class Spider(BaseSpider):
    def getName(self):
        return "DJ嗨曲网"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    # ---------- homeContent ----------
    def homeContent(self, filter):
        classes = []
        for tid, info in CATEGORY_MAP.items():
            classes.append({
                "type_id": tid,
                "type_name": info["type_name"],
            })
        result = {"class": classes}
        if filter:
            result["filters"] = ALL_FILTERS
        return result

    def homeVideoContent(self):
        return {"list": []}

    # ---------- categoryContent ----------
    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or "1")

        # 解析筛选参数
        sub_id = ""
        if extend and isinstance(extend, dict):
            sub_id = str(extend.get("class", "")).strip()

        # 确定实际请求的分类 ID 和 URL 格式
        children = CATEGORY_MAP.get(tid, {}).get("children", [])
        if sub_id:
            target_cid = sub_id
        elif children:
            target_cid = children[0][0]
        else:
            target_cid = "1"

        # 区分舞曲类(0_X)和榜单类(X_1)
        try:
            cid_int = int(target_cid)
        except Exception:
            cid_int = 1

        if tid == "wqu" or (tid == "bangdan" and cid_int >= 1 and cid_int <= 5):
            # 舞曲类格式: /dj/0_{cid}_{page}.html
            list_url = f"{SITE}/dj/0_{target_cid}_{page}.html"
        else:
            # 榜单类格式: /dj/{cid}_1_{page}.html
            list_url = f"{SITE}/dj/{target_cid}_1_{page}.html"

        try:
            r = requests.get(list_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 25, "total": 0}

        soup = BeautifulSoup(r.text, "html.parser")
        section = soup.find("section", class_="list-page")
        if not section:
            return {"list": [], "page": page, "pagecount": 1, "limit": 25, "total": 0}

        ul = section.find("ul")
        if not ul:
            return {"list": [], "page": page, "pagecount": 1, "limit": 25, "total": 0}

        videos = []
        for li in ul.find_all("li", recursive=False):
            spans = li.find_all("span", recursive=False)
            if len(spans) < 2:
                continue
            a = spans[1].find("a", href=re.compile(r"/dj/1_\d+\.html"))
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            m = re.search(r"/dj/1_(\d+)\.html", href)
            if not m:
                continue
            vid = m.group(1)

            duration = spans[2].get_text(strip=True) if len(spans) > 2 else ""
            bitrate = spans[3].get_text(strip=True) if len(spans) > 3 else ""
            date_str = spans[4].get_text(strip=True) if len(spans) > 4 else ""
            size_str = spans[5].get_text(strip=True) if len(spans) > 5 else ""

            remark = ""
            if duration:
                remark = duration
            if bitrate:
                remark = f"{remark} {bitrate}".strip()

            videos.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": "",
                "vod_remarks": remark,
                "vod_tag": date_str,
                "vod_content": f"上传时间: {date_str}  大小: {size_str}" if (date_str or size_str) else "",
            })

        # 简单分页: 如果有下一页链接则总页数+1
        pagecount = page
        next_link = soup.find("a", text="下一页")
        if next_link:
            pagecount = page + 1

        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": 25,
            "total": pagecount * 25,
        }

    # ---------- detailContent ----------
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vid = str(ids[0]).strip()

        detail_url = f"{SITE}/dj/1_{vid}.html"
        try:
            r = requests.get(detail_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
        except Exception:
            return {"list": []}

        text = r.text

        # 提取歌曲名 var n = "..."
        name = ""
        m = re.search(r'var\s+n\s*=\s*["\']([^"\']+)["\']', text)
        if m:
            name = m.group(1)

        # 提取动态 script URL 并获取 playurl
        playurl = ""
        m_script = re.search(r'src=["\'](/t/[^"\'/]+/)', text)
        if m_script:
            script_url = SITE + m_script.group(1)
            try:
                sr = requests.get(script_url, headers=HEADERS, timeout=15)
                sr.raise_for_status()
                m_pu = re.search(r"playurl\s*=\s*['\"]([^'\"]+)['\"]", sr.text)
                if m_pu:
                    playurl = codecs.decode(m_pu.group(1).replace("\\/", "/"), 'unicode_escape')
            except Exception:
                pass

        # 提取时长
        duration = ""
        m_dur = re.search(r'舞曲时长[^\d]*(\d{1,2}:\d{2}(?::\d{2})?)', text)
        if m_dur:
            duration = m_dur.group(1)

        # 提取封面图（详情页没有真实歌曲封面，只有默认播放器图片）
        pic = ""
        soup = BeautifulSoup(text, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src and ("cover" in src or "pic" in src or "upload" in src or "photo" in src):
                if not src.startswith("http"):
                    src = SITE + src
                pic = src
                break

        # 提取分类信息
        type_name = ""
        type_links = soup.find_all("a", href=re.compile(r"/dj/0_\d+_1\.html"))
        for a in type_links:
            txt = a.get_text(strip=True)
            if txt and txt not in ["所属类型", "最新发布", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]:
                type_name = txt
                break

        # 构造播放串
        play_from = "DJ嗨曲网"
        play_url = ""
        if name and playurl:
            play_url = f"{name}${playurl}"
        elif playurl:
            play_url = f"DJ嗨曲网${playurl}"

        return {
            "list": [{
                "vod_id": vid,
                "vod_name": name or f"DJ嗨曲网-{vid}",
                "vod_pic": pic,
                "vod_remarks": duration,
                "vod_year": "",
                "vod_area": "",
                "vod_director": "",
                "vod_actor": "",
                "type_name": type_name or "DJ",
                "vod_content": duration,
                "vod_play_from": play_from,
                "vod_play_url": play_url,
            }]
        }

    # ---------- playerContent ----------
    def playerContent(self, flag, id, vipFlags):
        play_url = str(id or "").strip()

        if "$" in play_url:
            play_url = play_url.split("$", 1)[1]

        if play_url and play_url.startswith("http"):
            return {
                "parse": 0,
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": SITE + "/",
                }
            }

        # 如果 id 不是 URL 而是 vid
        if play_url and play_url.isdigit():
            detail = self.detailContent([play_url])
            if detail.get("list"):
                real_url = detail["list"][0].get("vod_play_url", "")
                if real_url and "$" in real_url:
                    real_url = real_url.split("$", 1)[1]
                if real_url:
                    return {
                        "parse": 0,
                        "url": real_url,
                        "header": {
                            "User-Agent": UA,
                            "Referer": SITE + "/",
                        }
                    }

        return {
            "parse": 1,
            "url": play_url or SITE,
            "header": {
                "User-Agent": UA,
                "Referer": SITE + "/",
            }
        }

    # ---------- searchContent ----------
    def searchContent(self, key, quick):
        return {"list": []}

    def searchContentPage(self, key, quick, pg):
        return {"list": [], "page": int(pg or 1), "pagecount": 1, "limit": 25, "total": 0}

    # ---------- localProxy ----------
    def localProxy(self, param):
        return [200, "text/plain; charset=utf-8", "localProxy not implemented"]
