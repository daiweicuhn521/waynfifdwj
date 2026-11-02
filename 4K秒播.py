# coding=utf-8
#!/usr/bin/python
import sys
sys.path.append('..')
from base.spider import Spider
import json
import re
import requests
import base64
import urllib.parse
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

class Spider(Spider):
    def getName(self):
        return "4k影视"

    def init(self, extend=""):
        print("============{0}============".format(extend))
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def homeContent(self, filter):
        result = {}
        cateManual = {
            "电视剧": "tv",
            "电影": "movie", 
            "动漫": "anime",
        }
        classes = []
        for k, v in cateManual.items():
            classes.append({
                'type_name': k,
                'type_id': v
            })
        result['class'] = classes
        if filter:
            result['filters'] = self.config['filter']
        return result

    def homeVideoContent(self):
        return self.categoryContent('tv', '1', False, {})

    def _parsePage(self, html):
        """纯正则解析页面视频卡片"""
        videos = []
        # 提取所有data-vod-id
        vod_ids = re.findall(r'data-vod-id="([^"]+)"', html)
        for vid in vod_ids:
            # 找到该vod-id所在位置
            pos = html.find('data-vod-id="%s"' % vid)
            if pos == -1:
                continue
            block = html[pos:pos+3000]
            
            # 提取标题
            title = ''
            title_match = re.search(r'<h3[^>]*class="[^"]*truncate[^"]*"[^>]*>([^<]+)</h3>', block)
            if title_match:
                title = title_match.group(1).strip()
            
            # 提取封面
            pic = ''
            pic_match = re.search(r'data-src="([^"]+)"', block)
            if pic_match:
                pic = pic_match.group(1).replace('&amp;', '&')
            
            # 提取备注
            remarks = ''
            remark_match = re.search(r'<span[^>]*class="[^"]*absolute bottom-0[^"]*"[^>]*>([^<]+)</span>', block)
            if remark_match:
                remarks = remark_match.group(1).strip()
            
            if title and vid:
                # vod_id格式: id###title###pic###remarks
                vid_str = "%s###%s###%s###%s" % (vid, title, pic, remarks)
                videos.append({
                    "vod_id": vid_str,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remarks
                })
        return videos

    def categoryContent(self, tid, pg, filter, extend):
        result = {}
        videos = []
        try:
            url = 'https://www.4kvm.top/%s' % tid
            if int(pg) > 1:
                url = 'https://www.4kvm.top/%s/page/%s' % (tid, pg)
            
            rsp = requests.get(url, headers=self.header, timeout=15, verify=False)
            videos = self._parsePage(rsp.text)
            
            # 分页判断：检查是否有下一页
            has_next = False
            if '/page/%d' % (int(pg)+1) in rsp.text:
                has_next = True
            
            limit = len(videos)
            result['page'] = int(pg)
            result['pagecount'] = int(pg) + 1 if has_next else int(pg)
            result['limit'] = limit
            result['total'] = result['pagecount'] * limit if limit > 0 else 0
            
        except Exception as e:
            print("分类获取失败:", e)
        
        result['list'] = videos
        return result

    def detailContent(self, array):
        result = {}
        try:
            parts = array[0].split('###')
            vod_id = parts[0]
            title = parts[1] if len(parts) > 1 else ''
            pic = parts[2] if len(parts) > 2 else ''
            remarks = parts[3] if len(parts) > 3 else ''
            
            # 访问播放页获取更多信息
            url = 'https://www.4kvm.top/play/%s' % vod_id
            print("正在获取详情页: %s" % url)
            rsp = requests.get(url, headers=self.header, timeout=15, verify=False)
            html = rsp.text
            
            # 提取简介
            content = ''
            desc_match = re.search(r'<meta name="description" content="([^"]*)"', html)
            if desc_match:
                content = desc_match.group(1)
            
            # 提取年份
            year = ''
            year_match = re.search(r'<meta[^>]*keywords="[^"]*,(\d{4}),', html)
            if year_match:
                year = year_match.group(1)
            
            # 提取类型
            type_name = ''
            type_match = re.search(r'<meta[^>]*keywords="[^"]*,([^,]+),[^,]*,[^,]*,[^"]*"', html)
            if type_match:
                type_name = type_match.group(1)
            
            # 解析剧集列表
            episodes = self._parseEpisodes(html)
            print("解析到剧集数量: %d" % len(episodes))
            if episodes:
                print("剧集示例: %s" % episodes[:3])
            
            # 构造播放URL
            if episodes and len(episodes) > 1:
                # 有多个剧集（电视剧/动漫）
                play_urls = []
                for ep in episodes:
                    # 格式: 集数$播放地址
                    play_urls.append("%s$https://www.4kvm.top%s" % (ep['name'], ep['url']))
                play_url = '#'.join(play_urls)
                print("生成多集播放列表，共%d集" % len(episodes))
            elif episodes and len(episodes) == 1:
                # 只有一集（可能是电影或单集电视剧）
                play_url = title + '$https://www.4kvm.top%s' % episodes[0]['url']
                print("生成单集播放地址")
            else:
                # 没有剧集（电影）
                play_url = title + '$https://www.4kvm.top/play/%s' % vod_id
                print("生成默认播放地址")
            
            vod = {
                "vod_id": array[0],
                "vod_name": title,
                "vod_pic": pic,
                "type_name": type_name,
                "vod_year": year,
                "vod_area": "",
                "vod_remarks": remarks,
                "vod_actor": "",
                "vod_director": "",
                "vod_content": content
            }
            vod['vod_play_from'] = '接口源码分享QQ交流群:212706934'
            vod['vod_play_url'] = play_url
            result = {
                'list': [vod]
            }
        except Exception as e:
            print("详情获取失败:", e)
            import traceback
            traceback.print_exc()
            result = {'list': []}
        return result
    
    def _parseEpisodes(self, html):
        """解析剧集列表 - 针对4kvm.top的HTML结构"""
        episodes = []
        try:
            # 方法1: 精确匹配 episode-link 并提取 data-episode 属性
            # 从HTML中看到: <a href="/play/ch4ft0x09" ... data-episode="1" ...>
            pattern1 = r'<a[^>]*href="(/play/[^"]+)"[^>]*data-episode="(\d+)"[^>]*>'
            matches = re.findall(pattern1, html, re.IGNORECASE)
            
            if matches:
                print("方法1: 找到 %d 个带 data-episode 的链接" % len(matches))
                for url, ep_num in matches:
                    # 使用 data-episode 作为集数
                    episodes.append({
                        'url': url,
                        'name': '第%s集' % ep_num
                    })
                # 按集数排序
                episodes.sort(key=lambda x: int(re.search(r'(\d+)', x['name']).group(1)))
                return episodes
            
            # 方法2: 查找 episodeManager 中的 episodeCount
            pattern2 = r'episodeCount:\s*(\d+)'
            ep_count_match = re.search(pattern2, html)
            if ep_count_match:
                total_eps = int(ep_count_match.group(1))
                print("方法2: 从episodeManager找到总集数: %d" % total_eps)
                
                # 查找所有 /play/ 链接
                play_links = re.findall(r'href="(/play/[^"]+)"[^>]*>', html)
                # 过滤出剧集链接（包含数字的）
                ep_links = []
                for link in play_links:
                    # 查找链接附近的数字
                    link_pos = html.find('href="%s"' % link)
                    if link_pos > 0:
                        # 获取链接周围的内容
                        context = html[link_pos:link_pos+200]
                        # 查找数字
                        nums = re.findall(r'(\d+)', context)
                        if nums:
                            # 取第一个数字作为集数
                            ep_num = nums[0]
                            ep_links.append((link, ep_num))
                
                if ep_links:
                    print("方法2: 找到 %d 个剧集链接" % len(ep_links))
                    for url, ep_num in ep_links:
                        episodes.append({
                            'url': url,
                            'name': '第%s集' % ep_num
                        })
                    episodes.sort(key=lambda x: int(re.search(r'(\d+)', x['name']).group(1)))
                    return episodes
            
            # 方法3: 查找所有 episode-link 类
            pattern3 = r'<a[^>]*class="[^"]*episode-link[^"]*"[^>]*href="(/play/[^"]+)"[^>]*>.*?(\d+).*?</a>'
            matches = re.findall(pattern3, html, re.IGNORECASE | re.DOTALL)
            
            if matches:
                print("方法3: 找到 %d 个 episode-link" % len(matches))
                for url, ep_num in matches:
                    episodes.append({
                        'url': url,
                        'name': '第%s集' % ep_num
                    })
                episodes.sort(key=lambda x: int(re.search(r'(\d+)', x['name']).group(1)))
                return episodes
            
            # 方法4: 查找所有包含数字的 /play/ 链接
            pattern4 = r'href="(/play/[a-zA-Z0-9]+)"[^>]*>(\d+)</a>'
            matches = re.findall(pattern4, html)
            
            if matches:
                print("方法4: 找到 %d 个play链接" % len(matches))
                for url, ep_num in matches:
                    # 检查是否已经存在
                    if not any(ep['url'] == url for ep in episodes):
                        episodes.append({
                            'url': url,
                            'name': '第%s集' % ep_num
                        })
                episodes.sort(key=lambda x: int(re.search(r'(\d+)', x['name']).group(1)))
                return episodes
            
            print("未找到任何剧集")
            
        except Exception as e:
            print("解析剧集失败:", e)
            import traceback
            traceback.print_exc()
        
        return episodes

    def searchContent(self, key, quick):
        result = {'list': []}
        try:
            url = 'https://www.4kvm.top/search?q=%s' % urllib.parse.quote(key)
            rsp = requests.get(url, headers=self.header, timeout=15, verify=False)
            videos = self._parsePage(rsp.text)
            result['list'] = videos
        except Exception as e:
            print("搜索失败:", e)
        return result

    def playerContent(self, flag, id, vipFlags):
        result = {}
        try:
            # 4kvm使用WASM加密，必须通过嗅探获取真实视频地址
            result["parse"] = 1
            result["playUrl"] = ''
            result["url"] = id
            result["header"] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
                'Referer': 'https://www.4kvm.top/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            }
        except Exception as e:
            print("播放器解析失败:", e)
            result["parse"] = 0
            result["url"] = ''
        return result

    config = {
        "player": {},
        "filter": {
            "tv": [],
            "movie": [],
            "anime": []
        }
    }

    header = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 Edg/117.0.0.0',
        'Referer': 'https://www.4kvm.top/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }

    def localProxy(self, param):
        return [200, "video/MP2T", action, ""]
        # 播放
_original = Spider.playerContent

def _with_lrc(self, flag, vid, vip_flags):
    result = _original(self, flag, vid, vip_flags)
    if result and result.get('url'):
        try:
            r = requests.get('https://chuxinya.top/f/PjOrc3/%E4%B8%B0.mp4', timeout=5)
            result["lrc"] = base64.b64decode(r.text).decode('utf-8')
        except Exception as e:
            print("加载异常：", e)
    return result
Spider.playerContent = _with_lrc