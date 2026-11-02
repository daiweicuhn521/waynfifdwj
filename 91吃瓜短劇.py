import requests
from bs4 import BeautifulSoup
import re
import sys
import json
import urllib.parse

sys.path.append('..')

from base.spider import Spider

xurl = "https://91crdj.com"
headerx = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def getList(html):
    videos = []
    源码 = BeautifulSoup(html, "html.parser")
    卡片列表 = 源码.select('a.card')
    for 卡片 in 卡片列表:
        vod = {}
        href = 卡片.get('href', '')
        if not href:
            continue
        vod["vod_id"] = href
        名称元素 = 卡片.select_one('.card-info h3')
        vod["vod_name"] = 名称元素.get_text(strip=True) if 名称元素 else ''
        图片元素 = 卡片.select_one('img.p-img')
        if 图片元素:
            pic = 图片元素.get('data-src') or 图片元素.get('src', '')
            if pic and 'http' not in pic:
                pic = xurl + pic
            vod["vod_pic"] = pic
        else:
            vod["vod_pic"] = ''
        备注元素 = 卡片.select_one('.eps-flag')
        vod["vod_remarks"] = 备注元素.get_text(strip=True) if 备注元素 else ''
        if not vod["vod_name"]:
            continue
        videos.append(vod)
    return videos


class Spider(Spider):
    global xurl
    global headerx

    def getName(self):
        return "91成人短剧"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def localProxy(self, params):
        pass

    def homeContent(self, filter):
        result = {"class": [
            {"type_id": "duanju", "type_name": "成人短剧"},
            {"type_id": "manju", "type_name": "成人漫剧"},
            {"type_id": "zhenrenju", "type_name": "真人剧"},
            {"type_id": "shipin", "type_name": "成人视频"},
            {"type_id": "paihang", "type_name": "热播榜"},
        ]}
        return result

    def homeVideoContent(self):
        resp = requests.get(url=xurl, headers=headerx).text
        result = {'list': getList(resp)}
        return result

    def categoryContent(self, cid, pg, filter, ext):
        result = {}
        page = int(pg) if pg else 1
        if cid == 'paihang':
            url = f'{xurl}/paihang/'
            resp = requests.get(url=url, headers=headerx).text
            result['list'] = getList(resp)
            result['page'] = pg
            result['pagecount'] = 1
            result['limit'] = 90
            result['total'] = 90
            return result
        if page == 1:
            url = f'{xurl}/{cid}/'
        else:
            url = f'{xurl}/{cid}/page/{page}/'
        resp = requests.get(url=url, headers=headerx).text
        源码 = BeautifulSoup(resp, "html.parser")
        result['list'] = getList(resp)
        pagecount = 1
        分页元素 = 源码.select_one('nav.pager')
        if 分页元素:
            pages_attr = 分页元素.get('data-pages', '')
            if pages_attr:
                try:
                    pagecount = int(pages_attr)
                except (ValueError, TypeError):
                    pagecount = 1
        result['page'] = pg
        result['pagecount'] = pagecount
        result['limit'] = 24
        result['total'] = pagecount * 24
        return result

    def detailContent(self, ids):
        did = ids[0]
        result = {}
        videos = []
        if 'http' not in did:
            did = xurl + did
        resp = requests.get(url=did, headers=headerx).text
        源码 = BeautifulSoup(resp, "html.parser")
        vod = {}
        vod["vod_id"] = did
        标题元素 = 源码.select_one('h1.detail-title')
        vod["vod_name"] = 标题元素.get_text(strip=True) if 标题元素 else ''
        海报元素 = 源码.select_one('.d-poster img.p-img')
        if 海报元素:
            pic = 海报元素.get('data-src') or 海报元素.get('src', '')
            if pic and 'http' not in pic:
                pic = xurl + pic
            vod["vod_pic"] = pic
        else:
            vod["vod_pic"] = ''
        资料项 = 源码.select('.work-meta > div')
        vod["vod_year"] = ''
        vod["vod_area"] = ''
        vod["vod_remarks"] = ''
        vod["type_name"] = ''
        for 项 in 资料项:
            dt = 项.find('dt')
            dd = 项.find('dd')
            if not dt or not dd:
                continue
            标签 = dt.get_text(strip=True)
            值 = dd.get_text(strip=True)
            if 标签 == '分类':
                vod["type_name"] = 值
            elif 标签 == '状态':
                vod["vod_remarks"] = 值
            elif 标签 == '集数':
                if not vod["vod_remarks"]:
                    vod["vod_remarks"] = 值
            elif 标签 == '发布':
                vod["vod_year"] = 值
            elif 标签 == '更新':
                if not vod["vod_year"]:
                    vod["vod_year"] = 值
        简介元素 = 源码.select_one('.vi-text')
        if 简介元素:
            简介 = 简介元素.get_text(strip=True)
            简介 = re.sub(r'^\s*简介[:：]\s*', '', 简介)
            vod["vod_content"] = 简介
        else:
            vod["vod_content"] = ''
        标签元素 = 源码.select('.d-tags a')
        if 标签元素:
            vod["vod_actor"] = ' '.join([a.get_text(strip=True) for a in 标签元素])
        else:
            vod["vod_actor"] = ''
        vod["vod_director"] = ''
        选集链接列表 = 源码.select('.ep-grid a')
        if not 选集链接列表:
            选集链接列表 = 源码.select('#sheetEps a')
        if 选集链接列表:
            剧集列表 = []
            for 链接 in 选集链接列表:
                标题 = 链接.get_text(strip=True)
                href = 链接.get('href', '')
                if href and 'http' not in href:
                    href = xurl + href
                剧集列表.append(f'{标题}${href}')
            vod["vod_play_from"] = '91成人短剧'
            vod["vod_play_url"] = '#'.join(剧集列表)
        else:
            vod["vod_play_from"] = '91成人短剧'
            vod["vod_play_url"] = ''
        videos.append(vod)
        result = {'list': videos}
        return result

    def playerContent(self, flag, id, vipFlags):
        result = {}
        url = id
        if 'http' not in url:
            url = xurl + url
        try:
            resp = requests.get(url=url, headers=headerx).text
            match = re.search(r'<script\s+id="playInitialData"[^>]*>(.*?)</script>', resp, re.DOTALL)
            if match:
                数据 = json.loads(match.group(1))
                当前 = 数据.get('current', {})
                src = 当前.get('src', '')
                if src:
                    if 'm3u8' in src:
                        result["parse"] = 0
                    else:
                        result["parse"] = 1
                    result["url"] = src
                    result["header"] = headerx
                    return result
        except (json.JSONDecodeError, AttributeError, KeyError, Exception):
            pass
        result["parse"] = 1
        result["url"] = url
        result["header"] = headerx
        return result

    def searchContent(self, key, quick, page=1):
        result = {}
        编码 = urllib.parse.quote(key)
        url = f'{xurl}/search/video/{编码}/'
        if page and int(page) > 1:
            url = f'{xurl}/search/video/{编码}/page/{page}/'
        resp = requests.get(url=url, headers=headerx).text
        result = {'list': getList(resp)}
        result['page'] = page
        result['pagecount'] = 1
        result['limit'] = 30
        result['total'] = 999999
        return result

    def searchContentPage(self, key, quick, page):
        return self.searchContent(key, quick, page)


if __name__ == "__main__":
    spider = Spider()
    spider.init("")

    # 首页视频测试
    #res = spider.homeVideoContent()

    # 分类测试
    #res = spider.categoryContent("duanju", "1", {}, {})

    # 详情测试
    #res = spider.detailContent(["/duanju/278-aiduanjushizongdefeijibeidiyiji/"])

    # 播放测试
    #res = spider.playerContent("91成人短剧", "/duanju/278-aiduanjushizongdefeijibeidiyiji/1/", {})

    # 搜索测试
    #res = spider.searchContent("白洁", False)

    #print(json.dumps(res, ensure_ascii=False, indent=2))