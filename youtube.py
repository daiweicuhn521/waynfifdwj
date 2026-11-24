# -*- coding: utf-8 -*-
#!/usr/bin/python
#by多弗朗明哥改合并过滤版，适配大部分壳子
import re
import sys
import json
import html
import time
from urllib.parse import quote, unquote, parse_qs, urlencode, urlparse, urlunparse, urljoin

import requests
from base.spider import Spider

sys.path.append('..')

# ==================== 分类 ====================
YOUTUBE_CLASSES = [
            {"type_id":"短劇","type_name":"短剧"},
            {"type_id":"DJ串烧","type_name":"音乐"},
            {"type_id":"电影","type_name":"电影"},
            {"type_id": "动画 国漫", "type_name": "动画片"},
            {"type_id": "YouTube 新聞 Live","type_name": "直播"},
            {"type_id":"动画片直播","type_name":"动画片直播"},
            {"type_id":"电影直播","type_name":"电影直播"},
            {"type_id":"电视剧直播","type_name":"电视剧直播"},
            {"type_id":"沙雕动漫","type_name":"动漫"},
            {"type_id": "4K风景", "type_name": "4K风景"}
]

# ==================== 完整筛选器 ====================
CATEGORY_FILTERS = {
    "YouTube 新聞 Live": [
        {"key": "tid", "name": "中文", "value": [
            {"n": "默认", "v": "中天新闻24小時 大事發生看鳳凰 鳳凰 鳳凰衛視 @phoenixtv 三立LIVE新闻 台視新聞 東森新聞 TVBSNEWS"},
            {"n": "鳳凰衛視", "v": "大事發生看鳳凰 鳳凰 鳳凰衛視 @phoenixtv"},
            {"n": "中天新闻", "v": "直播 中天新闻"},
            {"n": "TVBSNEWS", "v": "直播 TVBSNEWS"},
            {"n": "東森新聞", "v": "直播 東森新聞 CH51"},
            {"n": "三立LIVE", "v": "直播 三立LIVE新闻 @setnews"},
            {"n": "台視新聞", "v": "直播 台視新聞 TTV NEWS"},
            {"n": "中視新聞", "v": "直播 Taiwan CTV news HD Live"},
            {"n": "港台", "v": "直播 港台"},
            {"n": "赛事", "v": "直播 赛事"},
            {"n": "CCTV", "v": "直播 CCTV"},
            {"n": "CNA", "v": "@channelnewsasia"}
        ]},
        {"key": "tid", "name": "中文", "value": [
            {"n": "默认", "v": "News"},
            {"n": "News", "v": "news"},
            {"n": "时政", "v": "时政 新闻"},
            {"n": "体育", "v": "体育 新闻"},
            {"n": "大陆", "v": "大陆 新闻"},
            {"n": "HKTVB", "v": "@tvbnewsofficial"},
            {"n": "少康戰情室", "v": "@tvbssituationroom"},
            {"n": "政经龙凤配", "v": "@觀點"},
            {"n": "FOCUS全球", "v": "@TVBSNEWS FOCUS全球新闻"},
            {"n": "新闻大白话", "v": "@TVBSNEWS 新闻大白话"},
            {"n": "东森新闻", "v": "关键时刻新闻"},
            {"n": "港台", "v": "港台 新闻"}
        ]},
        {"key": "tid", "name": "English", "value": [
            {"n": "科技", "v": "閱兵 奧運會 航母 航空母艦 潛水艇 核武器 坦克 武器 卫星 火箭 輪船 飛機"},
            {"n": "法治社会", "v": "法治 法制 社会 卖淫 淫秽 污蔑 赌博 毒品 裸聊 诈骗 拐卖 强奸 勒索"},
            {"n": "News", "v": "News"},
            {"n": "CNN", "v": "CNN news"},
            {"n": "BBC", "v": "BBC news"}
        ]}
    ],
    "沙雕动漫": [
        {"key": "tid", "name": "频道", "value": [
            {"n": "虾仁动画", "v": "PL虾仁"},
            {"n": "沙雕动画", "v": "PL沙雕动画"}
        ]},
        {"key": "date", "name": "排序", "value": [
            {"n": "默认", "v": ""}, {"n": "最新", "v": "latest"},
            {"n": "最热", "v": "hottest"}, {"n": "评分最高", "v": "favorite"},
            {"n": "当天", "v": "day"}, {"n": "本周", "v": "week"}, {"n": "本月", "v": "month"}
        ]}
    ],
    "动画 国漫": [
        {"key": "time", "name": "時間", "value": [
            {"n": "全選", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}
        ]},
        {"key": "tid", "name": "类型", "value": [
            {"n": "默认", "v": "國漫 劇集 3D"},
            {"n": "儿童早教", "v": "儿童早教"}, {"n": "儿童歌曲", "v": "儿童歌曲"},
            {"n": "宝宝巴士", "v": "宝宝巴士"}, {"n": "儿歌多多", "v": "儿歌多多"},
            {"n": "英语启蒙", "v": "儿童英语启蒙"}, {"n": "启蒙故事", "v": "儿童启蒙故事"},
            {"n": "安全教育", "v": "儿童安全教育"}
        ]},
        {"key": "date", "name": "排序", "value": [
            {"n": "默认", "v": ""}, {"n": "最新", "v": "latest"}, {"n": "最热", "v": "hottest"},
            {"n": "评分最高", "v": "favorite"}, {"n": "当天", "v": "day"}, {"n": "本周", "v": "week"}, {"n": "本月", "v": "month"}
        ]}
    ],
    "短劇": [
        {"key": "time", "name": "時間", "value": [
            {"n": "全選", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}
        ]},
        {"key": "tid", "name": "平台", "value": [
            {"n": "抖音", "v": "PL抖音 短剧"}, {"n": "快手", "v": "PL快手 短剧"},
            {"n": "大陆", "v": "PL大陆短剧"}, {"n": "香港", "v": "PL香港短剧"},
            {"n": "腾讯", "v": "PL腾讯短剧"}, {"n": "爱奇艺", "v": "PL爱奇艺短剧"},
            {"n": "优酷", "v": "PL优酷短剧"}, {"n": "芒果", "v": "PL芒果TV短剧"}
        ]},
        {"key": "tid2", "name": "类型", "value": [
            {"n": "擦边", "v": "PL擦边短剧"}, {"n": "都市", "v": "PL都市短剧"},
            {"n": "爱情", "v": "PL爱情短剧"}, {"n": "复仇", "v": "PL复仇短剧"},
            {"n": "穿越", "v": "PL穿越短剧"}, {"n": "喜剧", "v": "PL喜剧短剧"},
            {"n": "奇幻", "v": "PL奇幻短剧"},
            {"n": "九酱", "v": "PD@NineSauceDramaTV"}, {"n": "百万", "v": "PD@1-pw5ox"},
            {"n": "咖啡", "v": "PD@coffeedrama605"}, {"n": "斗罗", "v": "PD@DouluoDrama123"},
            {"n": "嘟嘟", "v": "PD@DUDUJUCHANG"}, {"n": "牛牛", "v": "PD@niuniuduanju"}
        ]},
        {"key": "date", "name": "排序", "value": [
            {"n": "默认", "v": ""}, {"n": "最新", "v": "latest"}, {"n": "最热", "v": "hottest"},
            {"n": "评分最高", "v": "favorite"}, {"n": "当天", "v": "day"}, {"n": "本周", "v": "week"}, {"n": "本月", "v": "month"}
        ]}
    ],
    "电影": [
        {"key": "time", "name": "時間", "value": [
            {"n": "全選", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}
        ]},
        {"key": "tid", "name": "地区", "value": [
            {"n": "默认", "v": ""}, {"n": "大陆", "v": "PL大陆 电影"}, {"n": "腾讯", "v": "PL腾讯 电影"},
            {"n": "爱奇艺", "v": "PL爱奇艺 电影"}, {"n": "优酷", "v": "PL优酷 电影"},
            {"n": "芒果", "v": "PL芒果TV 电影"}, {"n": "搜狐", "v": "PL搜狐 电影"},
            {"n": "港台", "v": "PL港台 电影"}, {"n": "动画", "v": "PL电影 动画"}
        ]},
        {"key": "date", "name": "排序", "value": [
            {"n": "默认", "v": ""}, {"n": "最新", "v": "latest"}, {"n": "最热", "v": "hottest"},
            {"n": "评分最高", "v": "favorite"}, {"n": "当天", "v": "day"}, {"n": "本周", "v": "week"}, {"n": "本月", "v": "month"}
        ]}
    ],
    "DJ串烧": [
        {"key": "tid", "name": "地区", "value": [
            {"n": "华语音乐", "v": "PL华语音乐"}, {"n": "华语MV", "v": "PL华语MV"},
            {"n": "环球视听", "v": "PL环球视听"}, {"n": "点阅率最高", "v": "点阅率最高华语歌曲"},
            {"n": "海外抖音", "v": "PL抖音"}, {"n": "粤语", "v": "PL粤语音乐"},
            {"n": "国语", "v": "PL国语音乐"}, {"n": "大陆", "v": "PL大陆音乐"},
            {"n": "香港", "v": "香港音乐"}, {"n": "台湾", "v": "台湾音乐"}
        ]},
        {"key": "tid2", "name": "风格", "value": [
            {"n": "舞曲", "v": "慢摇"}, {"n": "老歌", "v": "经典老歌"},
            {"n": "80-90", "v": "80音乐"}, {"n": "重低音DJ", "v": "重低音"},
            {"n": "车载舞曲", "v": "车载慢摇"}, {"n": "超级女声", "v": "超级女声"}
        ]},
        {"key": "date", "name": "排序", "value": [
            {"n": "默认", "v": ""}, {"n": "最新", "v": "latest"}, {"n": "最热", "v": "hottest"},
            {"n": "评分最高", "v": "favorite"}, {"n": "当天", "v": "day"}, {"n": "本周", "v": "week"}, {"n": "本月", "v": "month"}
        ]}
    ],
    "动画片直播": [
        {"key": "tid", "name": "语言", "value": [
            {"n": "全部", "v": ""}, {"n": "中文", "v": "中文 动画"},
            {"n": "英文", "v": "English cartoon animation"}, {"n": "日语", "v": "アニメ anime"}
        ]},
        {"key": "tid2", "name": "类型", "value": [
            {"n": "全部", "v": ""}, {"n": "国漫", "v": "国漫"},
            {"n": "日漫", "v": "anime live"}, {"n": "欧美", "v": "cartoon network live"},
            {"n": "儿童", "v": "kids animation live"}
        ]},
        {"key": "tid3", "name": "频道", "value": [
            {"n": "全部", "v": ""}, {"n": "Cartoon Network", "v": "@CartoonNetwork"},
            {"n": "PBS Kids", "v": "@PBSKids"}, {"n": "Nickelodeon", "v": "@Nickelodeon"},
            {"n": "Disney", "v": "@Disney"}, {"n": "宝宝巴士", "v": "@BabyBus"}
        ]}
    ],
    "电影直播": [
        {"key": "tid", "name": "语言", "value": [
            {"n": "全部", "v": ""}, {"n": "中文", "v": "中文 电影"},
            {"n": "英文", "v": "English movie"}, {"n": "粤语", "v": "粤语 电影"}
        ]},
        {"key": "tid2", "name": "类型", "value": [
            {"n": "全部", "v": ""}, {"n": "动作", "v": "action movie live"},
            {"n": "科幻", "v": "sci-fi movie live"}, {"n": "恐怖", "v": "horror movie live"},
            {"n": "喜剧", "v": "comedy movie live"}, {"n": "爱情", "v": "romance movie live"},
            {"n": "战争", "v": "war movie live"}
        ]},
        {"key": "tid3", "name": "来源", "value": [
            {"n": "全部", "v": ""}, {"n": "国产", "v": "国产电影 直播"},
            {"n": "港片", "v": "香港电影 直播"}, {"n": "好莱坞", "v": "Hollywood movie live"},
            {"n": "韩剧", "v": "Korean movie live"}
        ]}
    ],
    "电视剧直播": [
        {"key": "tid", "name": "语言", "value": [
            {"n": "全部", "v": ""}, {"n": "中文", "v": "中文 电视剧"},
            {"n": "英文", "v": "English TV drama"}, {"n": "韩语", "v": "Korean drama"},
            {"n": "日语", "v": "Japanese drama"}
        ]},
        {"key": "tid2", "name": "类型", "value": [
            {"n": "全部", "v": ""}, {"n": "古装", "v": "古装 电视剧 直播"},
            {"n": "现代", "v": "现代 电视剧 直播"}, {"n": "悬疑", "v": "悬疑 电视剧 直播"},
            {"n": "爱情", "v": "爱情 电视剧 直播"}, {"n": "都市", "v": "都市 电视剧 直播"}
        ]},
        {"key": "tid3", "name": "来源", "value": [
            {"n": "全部", "v": ""}, {"n": "国产", "v": "国产剧 直播"},
            {"n": "港剧", "v": "港剧 直播"}, {"n": "台剧", "v": "台剧 直播"},
            {"n": "韩剧", "v": "韩剧 直播"}, {"n": "美剧", "v": "美剧 直播"},
            {"n": "日剧", "v": "日剧 直播"}
        ]}
    ],
    "4K风景": [
        {"key": "tid", "name": "地区", "value": [
            {"n": "全部", "v": "4K 风景"}, {"n": "中国", "v": "4K 中国 风景"},
            {"n": "日本", "v": "4K Japan scenery"}, {"n": "瑞士", "v": "4K Switzerland landscape"},
            {"n": "冰岛", "v": "4K Iceland"}, {"n": "新西兰", "v": "4K New Zealand"},
            {"n": "挪威", "v": "4K Norway"}, {"n": "加拿大", "v": "4K Canada scenery"},
            {"n": "意大利", "v": "4K Italy landscape"}, {"n": "法国", "v": "4K France scenery"}
        ]},
        {"key": "tid2", "name": "主题", "value": [
            {"n": "全部", "v": ""}, {"n": "自然风光", "v": "4K nature landscape"},
            {"n": "城市夜景", "v": "4K city night"}, {"n": "森林", "v": "4K forest"},
            {"n": "海洋海滩", "v": "4K ocean beach"}, {"n": "雪山", "v": "4K snow mountain"},
            {"n": "极光", "v": "4K aurora borealis"}, {"n": "星空银河", "v": "4K starry sky milky way"},
            {"n": "海底世界", "v": "4K underwater"}, {"n": "无人机航拍", "v": "4K drone aerial"},
            {"n": "热带雨林", "v": "4K tropical rainforest"}, {"n": "沙漠", "v": "4K desert"},
            {"n": "瀑布", "v": "4K waterfall"}
        ]},
        {"key": "date", "name": "排序", "value": [
            {"n": "默认", "v": ""}, {"n": "最新", "v": "latest"}, {"n": "最热", "v": "hottest"},
            {"n": "评分最高", "v": "favorite"}, {"n": "当天", "v": "day"}, {"n": "本周", "v": "week"}, {"n": "本月", "v": "month"}
        ]}
    ]
}

class YouTubeLite:
    def __init__(self, session, headers=None, config=None):
        self.session = session
        self.headers = headers or {}
        self.config = config or {}
        self.player_cache = {}
        self.extract_cache = {}
        self.sig_plan_cache = {}
        self.extract_cache_ttl = int(self.config.get('extract_cache_ttl') or 300)

    def extract(self, url_or_id):
        video_id = self.extract_video_id(url_or_id)
        cached = self.extract_cache.get(video_id)
        now = time.time()
        if cached and cached.get('expires', 0) > now:
            return cached.get('data')
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        page_resp = self._get(watch_url)
        page = page_resp.text
        ytcfg = self._extract_ytcfg(page) or {}
        player_response = self._extract_initial_player_response(page) or {}
        player_url = self._extract_player_url(page)
        api_key = ytcfg.get('INNERTUBE_API_KEY') or self._search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
        visitor_data = self._extract_visitor_data(ytcfg, player_response)
        sts = self._extract_signature_timestamp(video_id, player_url, ytcfg)
        context = ytcfg.get('INNERTUBE_CONTEXT') or {
            'client': {'clientName': 'WEB', 'clientVersion': '2.20240310.01.00', 'hl': 'en', 'gl': 'US'}
        }
        responses = [player_response] if player_response else []
        if api_key:
            api_responses = self._call_player_api(video_id, api_key, context, watch_url, visitor_data, sts)
            if not isinstance(api_responses, list):
                api_responses = [api_responses] if api_responses else []
            responses.extend([x for x in api_responses if x])
        player_response = next((x for x in responses if (x.get('playabilityStatus') or {}).get('status') == 'OK'), player_response)
        status = (player_response.get('playabilityStatus') or {}).get('status')
        streaming = player_response.get('streamingData') or {}
        if status and status not in ('OK', 'LIVE_STREAM_OFFLINE') and not streaming:
            reason = (player_response.get('playabilityStatus') or {}).get('reason') or status
            raise Exception(f'YouTube 不可播放: {reason}')
        details = player_response.get('videoDetails') or {}
        raw_formats = []
        seen_raw = set()
        for response in responses:
            response_streaming = (response or {}).get('streamingData') or {}
            source_raw = (response_streaming.get('formats') or []) + (response_streaming.get('adaptiveFormats') or [])
            for raw in source_raw:
                key = (raw.get('itag'), raw.get('url') or raw.get('signatureCipher') or raw.get('cipher') or raw.get('mimeType'))
                if key not in seen_raw:
                    seen_raw.add(key)
                    raw = raw.copy()
                    raw['_client_name'] = (response or {}).get('_client_name')
                    raw['_client_ua'] = (response or {}).get('_client_ua')
                    raw_formats.append(raw)
        formats = []
        for raw in raw_formats:
            if raw.get('signatureCipher') or raw.get('cipher'):
                pass
            item = self._normalize_format(raw, player_url)
            if item and item.get('url'):
                formats.append(item)
        if not formats:
            raise Exception('未获取到可用播放地址')
        data = {
            'id': video_id,
            'title': details.get('title') or video_id,
            'duration': int(details.get('lengthSeconds') or 0),
            'formats': formats,
        }
        self.extract_cache[video_id] = {'data': data, 'expires': time.time() + self.extract_cache_ttl}
        return data

    @staticmethod
    def extract_video_id(text):
        text = str(text or '').strip()
        for pattern in [
            r'(?:v=|/v/|/embed/|/shorts/|youtu\.be/)([0-9A-Za-z_-]{11})',
            r'^([0-9A-Za-z_-]{11})$',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        raise Exception('无法识别 YouTube 视频 ID')

    def _client_name_id(self, client_name):
        return {
            'WEB': 1, 'MWEB': 2, 'ANDROID': 3, 'IOS': 5,
            'TVHTML5': 7, 'ANDROID_VR': 28, 'WEB_EMBEDDED_PLAYER': 56, 'WEB_REMIX': 67,
        }.get(client_name, 1)

    def _extract_visitor_data(self, ytcfg, player_response):
        return (
            self.config.get('visitor_data')
            or ytcfg.get('VISITOR_DATA')
            or (((ytcfg.get('INNERTUBE_CONTEXT') or {}).get('client') or {}).get('visitorData'))
            or ((player_response.get('responseContext') or {}).get('visitorData'))
        )

    def _extract_signature_timestamp(self, video_id, player_url, ytcfg=None):
        try:
            code = self._get_player_code(player_url)
            sts = self._search(r'(?:signatureTimestamp|sts)\s*:\s*(\d{5})', code)
            return int(sts) if sts else None
        except Exception:
            return None

    def _get_po_token(self, client_name, context='gvs'):
        tokens = self.config.get('po_token') or self.config.get('po_tokens') or {}
        if isinstance(tokens, str):
            return tokens
        if isinstance(tokens, dict):
            return tokens.get(f'{client_name}.{context}') or tokens.get(client_name) or tokens.get(context)
        return None

    def choose_playable(self, formats, quality=None):
        all_videos = [x for x in formats if x.get('vcodec') != 'none' and x.get('acodec') == 'none']
        candidates = all_videos[:]
        if quality == '4k':
            candidates = [x for x in candidates if int(x.get('height') or 0) >= 2160]
        elif quality == '2k':
            candidates = [x for x in candidates if 1440 <= int(x.get('height') or 0) < 2160]
        elif quality == '1080p':
            candidates = [x for x in candidates if 1000 <= int(x.get('height') or 0) < 1440]
        elif quality == 'best':
            safe_candidates = [x for x in candidates if not self._is_risky_best_video(x)]
            if safe_candidates:
                candidates = safe_candidates
        else:
            candidates = [x for x in candidates if int(x.get('height') or 0) >= 1080]
        if not candidates and quality == 'best':
            candidates = all_videos
        if not candidates:
            return None
        candidates.sort(key=lambda x: (int(x.get('height') or 0), 1 if x.get('ext') == 'webm' else 0, int(x.get('bitrate') or 0)), reverse=True)
        return candidates[0] if candidates else None

    def _is_risky_best_video(self, item):
        codecs = (item.get('codecs') or '').lower()
        return 'av01' in codecs

    def choose_audio(self, formats):
        candidates = [x for x in formats if x.get('acodec') != 'none' and x.get('vcodec') == 'none']
        if not candidates:
            return None
        candidates.sort(key=lambda x: (1 if x.get('ext') == 'mp4' else 0, int(x.get('bitrate') or 0)), reverse=True)
        return candidates[0] if candidates else None

    def _get(self, url, **kwargs):
        headers = self.headers.copy()
        headers.update(kwargs.pop('headers', {}) or {})
        r = self.session.get(url, headers=headers, timeout=kwargs.pop('timeout', 15), **kwargs)
        r.raise_for_status()
        return r

    def _post_json(self, url, payload, headers=None):
        h = self.headers.copy()
        h.update({'Content-Type': 'application/json', 'Origin': 'https://www.youtube.com'})
        if headers:
            h.update({k: v for k, v in headers.items() if v})
        r = self.session.post(url, json=payload, headers=h, timeout=15)
        r.raise_for_status()
        return r.json()

    def _call_player_api(self, video_id, api_key, context, referer, visitor_data=None, sts=None):
        clients = [
            {'client': {'clientName': 'ANDROID_VR', 'clientVersion': '1.65.10', 'deviceMake': 'Oculus', 'deviceModel': 'Quest 3', 'androidSdkVersion': 32, 'userAgent': 'com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip', 'osName': 'Android', 'osVersion': '12L', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'ANDROID', 'clientVersion': '21.02.35', 'androidSdkVersion': 30, 'userAgent': 'com.google.android.youtube/21.02.35 (Linux; U; Android 11) gzip', 'osName': 'Android', 'osVersion': '11', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'IOS', 'clientVersion': '21.02.3', 'deviceMake': 'Apple', 'deviceModel': 'iPhone16,2', 'userAgent': 'com.google.ios.youtube/21.02.3 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)', 'osName': 'iPhone', 'osVersion': '18.3.2.22D82', 'hl': 'en', 'gl': 'US'}},
            context,
            {'client': {'clientName': 'MWEB', 'clientVersion': '2.20260115.01.00', 'userAgent': 'Mozilla/5.0 (iPad; CPU OS 16_7_10 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1,gzip(gfe)', 'hl': 'en', 'gl': 'US'}},
        ]
        results = []
        fallback = None
        for ctx in clients:
            client_name = (ctx.get('client') or {}).get('clientName')
            try:
                url = f'https://www.youtube.com/youtubei/v1/player?key={api_key}&prettyPrint=false'
                payload = {
                    'context': ctx,
                    'videoId': video_id,
                    'playbackContext': {'contentPlaybackContext': {'html5Preference': 'HTML5_PREF_WANTS', **({'signatureTimestamp': sts} if sts else {})}},
                    'contentCheckOk': True,
                    'racyCheckOk': True,
                }
                client = ctx.get('client') or {}
                headers = {
                    'Referer': referer,
                    'X-YouTube-Client-Name': str(self._client_name_id(client.get('clientName'))),
                    'X-YouTube-Client-Version': client.get('clientVersion') or '',
                }
                if visitor_data:
                    headers['X-Goog-Visitor-Id'] = visitor_data
                client_ua = client.get('userAgent')
                if client_ua:
                    headers['User-Agent'] = client_ua
                data = self._post_json(url, payload, headers=headers)
                streaming = data.get('streamingData') or {}
                if streaming:
                    data['_client_name'] = client_name
                    data['_client_ua'] = client_ua
                    results.append(data)
                    if client_name == 'ANDROID_VR' and streaming.get('formats'):
                        return results
                if streaming and fallback is None:
                    fallback = data
                elif fallback is None:
                    fallback = data
            except Exception:
                continue
        return results or ([fallback] if fallback else [])

    def _normalize_format(self, fmt, player_url):
        media_url = fmt.get('url')
        if not media_url:
            cipher = fmt.get('signatureCipher') or fmt.get('cipher')
            if cipher:
                media_url = self._decrypt_signature_cipher(cipher, player_url)
        if not media_url:
            return None
        media_url = self._decrypt_nsig(media_url, player_url)
        client_name = fmt.get('_client_name')
        po_token = self._get_po_token(client_name, 'gvs') if client_name else None
        if po_token:
            sep = '&' if '?' in media_url else '?'
            media_url = f'{media_url}{sep}pot={quote(po_token)}'
        mime = fmt.get('mimeType') or ''
        ext = 'mp4' if 'mp4' in mime else 'webm' if 'webm' in mime else 'unknown'
        codecs = self._search(r'codecs="([^"]+)"', mime) or ''
        has_audio = mime.startswith('audio/') or any(x in codecs for x in ('mp4a', 'opus', 'vorbis'))
        has_video = mime.startswith('video/') or any(x in codecs for x in ('avc', 'vp9', 'av01', 'h264'))
        headers = (fmt.get('http_headers') or {}).copy()
        if fmt.get('_client_ua'):
            headers['User-Agent'] = fmt.get('_client_ua')
        return {
            'itag': fmt.get('itag'),
            'url': media_url,
            'mimeType': mime,
            'client': fmt.get('_client_name'),
            'ext': ext,
            'width': fmt.get('width') or 0,
            'height': fmt.get('height') or 0,
            'fps': fmt.get('fps') or 0,
            'bitrate': fmt.get('bitrate') or fmt.get('averageBitrate') or 0,
            'contentLength': fmt.get('contentLength'),
            'initRange': fmt.get('initRange') or {},
            'indexRange': fmt.get('indexRange') or {},
            'codecs': codecs,
            'quality': fmt.get('qualityLabel') or fmt.get('quality'),
            'vcodec': codecs if has_video else 'none',
            'acodec': codecs if has_audio else 'none',
            'headers': headers,
        }

    def _decrypt_signature_cipher(self, cipher, player_url):
        data = parse_qs(cipher)
        media_url = unquote(data.get('url', [''])[0])
        sig = unquote(data.get('s', [''])[0])
        sp = data.get('sp', ['sig'])[0]
        if not media_url:
            return ''
        if sig:
            decoded = self._decrypt_sig(sig, player_url)
            sep = '&' if '?' in media_url else '?'
            media_url = f'{media_url}{sep}{sp}={quote(decoded)}'
        return media_url

    def _decrypt_sig(self, sig, player_url):
        cache_key = player_url or ''
        if cache_key in self.sig_plan_cache:
            plan = self.sig_plan_cache.get(cache_key)
        else:
            code = self._get_player_code(player_url)
            plan = self._extract_sig_plan(code)
            self.sig_plan_cache[cache_key] = plan
        if not plan:
            return sig
        arr = list(sig)
        for op, arg in plan:
            if op == 'reverse':
                arr.reverse()
            elif op in ('slice', 'splice'):
                arr = arr[int(arg):]
            elif op == 'swap' and arr:
                j = int(arg) % len(arr)
                arr[0], arr[j] = arr[j], arr[0]
        return ''.join(arr)

    def _decrypt_nsig(self, media_url, player_url):
        try:
            parsed = urlparse(media_url)
            query = parse_qs(parsed.query)
            n_value = query.get('n', [None])[0]
            if not n_value:
                return media_url
            path_match = re.search(r'/n/([^/]+)', parsed.path)
            if path_match and path_match.group(1) != n_value:
                new_path = parsed.path.replace(f"/n/{path_match.group(1)}", f"/n/{n_value}", 1)
                return urlunparse(parsed._replace(path=new_path))
            return media_url
        except Exception:
            return media_url

    def _get_player_code(self, player_url):
        if not player_url:
            return ''
        if player_url in self.player_cache:
            return self.player_cache[player_url]
        if player_url.startswith('//'):
            player_url = 'https:' + player_url
        elif player_url.startswith('/'):
            player_url = 'https://www.youtube.com' + player_url
        try:
            code = self._get(player_url).text
        except Exception:
            code = ''
        self.player_cache[player_url] = code
        return code

    def _extract_sig_plan(self, code):
        if not code:
            return None
        name = None
        for pattern in [
            r'\.sig\|\|([a-zA-Z0-9_$]+)\(',
            r'"signature",\s*([a-zA-Z0-9_$]+)\(',
            r'([a-zA-Z0-9_$]+)=function\(a\)\{a=a\.split\(""\);',
        ]:
            m = re.search(pattern, code)
            if m:
                name = m.group(1)
                break
        if not name:
            return None
        body = self._extract_js_function_body(code, name)
        if not body:
            return None
        helper = self._search(r'([a-zA-Z0-9_$]+)\.[a-zA-Z0-9_$]+\(a,\d+\)', body)
        helper_map = self._extract_helper_object(code, helper) if helper else {}
        plan = []
        for part in body.split(';'):
            if 'reverse()' in part:
                plan.append(('reverse', 0))
                continue
            m = re.search(r'\.slice\((\d+)\)', part)
            if m:
                plan.append(('slice', int(m.group(1))))
                continue
            m = re.search(r'\.splice\(0,(\d+)\)', part)
            if m:
                plan.append(('splice', int(m.group(1))))
                continue
            m = re.search(r'([a-zA-Z0-9_$]+)\.([a-zA-Z0-9_$]+)\(a,(\d+)\)', part)
            if m and m.group(1) == helper:
                op = helper_map.get(m.group(2))
                if op:
                    plan.append((op, int(m.group(3))))
        return plan or None

    def _extract_helper_object(self, code, name):
        if not name:
            return {}
        m = re.search(r'var\s+' + re.escape(name) + r'=\{(.+?)\};', code, re.S) or re.search(re.escape(name) + r'=\{(.+?)\};', code, re.S)
        if not m:
            return {}
        result = {}
        for method, body in re.findall(r'([a-zA-Z0-9_$]+):function\([a-z,]+\)\{(.*?)\}', m.group(1)):
            if '.reverse(' in body:
                result[method] = 'reverse'
            elif '.splice(' in body:
                result[method] = 'splice'
            elif '.slice(' in body:
                result[method] = 'slice'
            elif 'a[0]' in body and 'length' in body:
                result[method] = 'swap'
        return result

    def _extract_js_function_body(self, code, name):
        starts = []
        for pattern in [
            r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{',
            re.escape(name) + r'\s*=\s*function\s*\([^)]*\)\s*\{',
            r'var\s+' + re.escape(name) + r'\s*=\s*function\s*\([^)]*\)\s*\{',
        ]:
            m = re.search(pattern, code)
            if m:
                starts.append(m.end() - 1)
        if not starts:
            return ''
        start = starts[0]
        depth = 0
        in_str = None
        escape = False
        for i in range(start, len(code)):
            ch = code[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch in ('"', "'", '`'):
                in_str = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return code[start + 1:i]
        return ''

    def _extract_ytcfg(self, text):
        m = re.search(r'ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;', text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except Exception:
            return None

    def _extract_initial_player_response(self, text):
        return self._extract_json_after(text, 'ytInitialPlayerResponse')

    def _extract_json_after(self, text, marker):
        pos = text.find(marker)
        if pos < 0:
            return None
        start = text.find('{', pos)
        if start < 0:
            return None
        depth = 0
        in_str = None
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if in_str:
                if ch == in_str:
                    in_str = None
                continue
            if ch == '"':
                in_str = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        return None
        return None

    def _extract_player_url(self, text):
        for pattern in [
            r'"jsUrl":"([^"]+)"',
            r'"PLAYER_JS_URL":"([^"]+)"',
            r'(/s/player/[^"\\]+/base\.js)',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1).replace('\\/', '/')
        return ''

    @staticmethod
    def _search(pattern, text, default=None):
        m = re.search(pattern, text or '', re.S)
        return m.group(1) if m else default

class YouTubeLiveLite:
    def __init__(self, session, headers=None, config=None):
        self.session = session
        self.headers = headers or {}
        self.config = config or {}
        self.cache = {}
        self.cache_ttl = int(self.config.get('live_cache_ttl') or 45)

    @staticmethod
    def extract_video_id(text):
        text = str(text or '').strip()
        for pattern in [
            r'(?:v=|/v/|/embed/|/shorts/|youtu\.be/)([0-9A-Za-z_-]{11})',
            r'^([0-9A-Za-z_-]{11})$',
        ]:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        raise Exception('无法识别 YouTube 视频 ID')

    def extract_live(self, url_or_id):
        video_id = self.extract_video_id(url_or_id)
        now = time.time()
        cached = self.cache.get(video_id)
        if cached and cached.get('expires', 0) > now:
            return cached.get('data')

        watch_url = f'https://www.youtube.com/watch?v={video_id}'
        response = self._get(watch_url)
        page = response.text
        player_response = self._extract_initial_player_response(page) or {}
        ytcfg = self._extract_ytcfg(page) or {}
        api_key = ytcfg.get('INNERTUBE_API_KEY') or self._search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
        visitor_data = self._extract_visitor_data(ytcfg, player_response)
        status_obj = player_response.get('playabilityStatus') or {}
        streaming = player_response.get('streamingData') or {}
        details = player_response.get('videoDetails') or {}

        page_hls_url = streaming.get('hlsManifestUrl') or ''
        api_data = None
        if api_key:
            api_data = self._call_player_api(video_id, api_key, ytcfg, watch_url, visitor_data)
            if api_data:
                api_streaming = api_data.get('streamingData') or {}
                api_details = api_data.get('videoDetails') or {}
                api_hls_url = api_streaming.get('hlsManifestUrl') or ''
                if api_hls_url:
                    streaming = api_streaming
                elif not page_hls_url and api_streaming:
                    streaming = api_streaming
                if api_details:
                    details = api_details
                status_obj = api_data.get('playabilityStatus') or status_obj
        if not (streaming.get('hlsManifestUrl') or '') and page_hls_url:
            streaming = dict(streaming or {})
            streaming['hlsManifestUrl'] = page_hls_url

        hls_url = streaming.get('hlsManifestUrl') or ''
        is_live = bool(details.get('isLiveContent') or hls_url)
        status = status_obj.get('status') or ''
        reason = status_obj.get('reason') or ''
        title = details.get('title') or video_id

        data = {
            'id': video_id,
            'title': title,
            'is_live': is_live,
            'status': status,
            'reason': reason,
            'hls_url': hls_url,
            'duration': int(details.get('lengthSeconds') or 0),
        }
        self.cache[video_id] = {'data': data, 'expires': time.time() + self.cache_ttl}
        return data

    def _get(self, url, **kwargs):
        headers = self.headers.copy()
        headers.update(kwargs.pop('headers', {}) or {})
        response = self.session.get(url, headers=headers, timeout=kwargs.pop('timeout', 15), **kwargs)
        response.raise_for_status()
        return response

    def _post_json(self, url, payload, headers=None):
        final_headers = self.headers.copy()
        final_headers.update({'Content-Type': 'application/json', 'Origin': 'https://www.youtube.com'})
        if headers:
            final_headers.update({k: v for k, v in headers.items() if v})
        response = self.session.post(url, json=payload, headers=final_headers, timeout=15)
        response.raise_for_status()
        return response.json()

    def _call_player_api(self, video_id, api_key, ytcfg, referer, visitor_data=None):
        context = ytcfg.get('INNERTUBE_CONTEXT') or {
            'client': {'clientName': 'WEB', 'clientVersion': '2.20240310.01.00', 'hl': 'en', 'gl': 'US'}
        }
        clients = [
            {'client': {'clientName': 'ANDROID', 'clientVersion': '21.02.35', 'androidSdkVersion': 30, 'userAgent': 'com.google.android.youtube/21.02.35 (Linux; U; Android 11) gzip', 'osName': 'Android', 'osVersion': '11', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'IOS', 'clientVersion': '21.02.3', 'deviceMake': 'Apple', 'deviceModel': 'iPhone16,2', 'userAgent': 'com.google.ios.youtube/21.02.3 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)', 'osName': 'iPhone', 'osVersion': '18.3.2.22D82', 'hl': 'en', 'gl': 'US'}},
            {'client': {'clientName': 'MWEB', 'clientVersion': '2.20260115.01.00', 'userAgent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1', 'hl': 'en', 'gl': 'US'}},
            context,
        ]
        for ctx in clients:
            client = ctx.get('client') or {}
            client_name = client.get('clientName') or 'WEB'
            try:
                url = f'https://www.youtube.com/youtubei/v1/player?key={quote(api_key)}&prettyPrint=false'
                headers = {
                    'Referer': referer,
                    'X-YouTube-Client-Name': str(self._client_name_id(client_name)),
                    'X-YouTube-Client-Version': client.get('clientVersion') or '',
                }
                if visitor_data:
                    headers['X-Goog-Visitor-Id'] = visitor_data
                if client.get('userAgent'):
                    headers['User-Agent'] = client.get('userAgent')
                payload = {
                    'context': ctx,
                    'videoId': video_id,
                    'contentCheckOk': True,
                    'racyCheckOk': True,
                }
                data = self._post_json(url, payload, headers=headers)
                streaming = data.get('streamingData') or {}
                if streaming.get('hlsManifestUrl'):
                    data['_client_name'] = client_name
                    return data
            except Exception:
                continue
        return None

    def _extract_visitor_data(self, ytcfg, player_response):
        return (
            self.config.get('visitor_data')
            or ytcfg.get('VISITOR_DATA')
            or (((ytcfg.get('INNERTUBE_CONTEXT') or {}).get('client') or {}).get('visitorData'))
            or ((player_response.get('responseContext') or {}).get('visitorData'))
        )

    def _extract_ytcfg(self, text):
        match = re.search(r'ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;', text or '', re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except Exception:
            return None

    def _extract_initial_player_response(self, text):
        return self._extract_json_after(text, 'ytInitialPlayerResponse')

    def _extract_json_after(self, text, marker):
        pos = (text or '').find(marker)
        if pos < 0:
            return None
        start = text.find('{', pos)
        if start < 0:
            return None
        depth = 0
        in_str = None
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if in_str:
                if char == in_str:
                    in_str = None
                continue
            if char in ('"', "'"):
                in_str = char
                continue
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:index + 1])
                    except Exception:
                        return None
        return None

    @staticmethod
    def _search(pattern, text, default=None):
        match = re.search(pattern, text or '', re.S)
        return match.group(1) if match else default

    def _client_name_id(self, client_name):
        return {
            'WEB': 1,
            'MWEB': 2,
            'ANDROID': 3,
            'IOS': 5,
            'TVHTML5': 7,
            'ANDROID_VR': 28,
            'WEB_EMBEDDED_PLAYER': 56,
            'WEB_REMIX': 67,
        }.get(client_name, 1)

class Spider(Spider):
    def getName(self):
        return 'YouTube 视频+直播'

    def init(self, extend):
        try:
            self.extendDict = json.loads(extend) if extend else {}
        except Exception:
            self.extendDict = {}
        self.session = requests.Session()
        proxy_val = self.extendDict.get('proxy')
        if proxy_val:
            if isinstance(proxy_val, dict):
                self.session.proxies = proxy_val
            elif isinstance(proxy_val, str):
                proxy_url = f'http://{proxy_val}' if not proxy_val.startswith('http') else proxy_val
                self.session.proxies = {'http': proxy_url, 'https': proxy_url}
        self.header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.youtube.com/'
        }
        self.session.headers.update(self.header)
        self.yt = YouTubeLite(self.session, self.header, self.extendDict)
        self.yt_live = YouTubeLiveLite(self.session, self.header, self.extendDict)
        self.search_cache = {}
        self.hls_url_cache = {}
        self.hls_proxy_enabled = self.extendDict.get('hls_proxy', True) is not False
        self._hls_key_seq = 0

    def homeContent(self, filter):
        result = {'class': YOUTUBE_CLASSES}
        if filter:
            result['filters'] = CATEGORY_FILTERS
        return result

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, cid, page, filter, ext):
        page = int(page or 1)
        filters = ext if isinstance(ext, dict) else {}
        pure_live_ids = {'live', 'news live', 'music live', 'lofi live', 'space live',
                         'nature live', 'game live', 'sports live'}
        cid_lower = str(cid or '').lower()
        if cid in pure_live_ids or 'live' in cid_lower or '直播' in str(cid or ''):
            keyword = self._build_live_keyword(cid, filters)
            videos, has_more = self._search_youtube_page(keyword, page, live_filter=True)
        else:
            keyword = self._build_keyword(cid, filters)
            videos, has_more = self._search_youtube_page(keyword, page, live_filter=False)
        return {
            'list': videos,
            'page': page,
            'pagecount': page + 1 if has_more else page,
            'limit': len(videos),
            'total': len(videos)
        }

    def searchContent(self, key, quick, pg=1):
        page = int(pg or 1)
        keyword = str(key or '').strip()
        videos, has_more = self._search_youtube_page(keyword, page, live_filter=False)
        return {
            'list': videos,
            'page': page,
            'pagecount': page + 1 if has_more else page,
            'limit': len(videos),
            'total': len(videos)
        }

    def detailContent(self, did):
        video_id = did[0]
        live_data = None
        is_live = False
        status_text = '视频'
        hls_url = None
        title = None
        try:
            live_data = self.yt_live.extract_live(video_id)
            hls_url = live_data.get('hls_url', '')
            status = live_data.get('status', '')
            title = live_data.get('title') or video_id

            if hls_url and status not in ('LIVE_STREAM_OFFLINE', 'LOGIN_REQUIRED', 'AGE_VERIFICATION_REQUIRED'):
                is_live = True
                status_text = '🔴 正在直播'
            elif status == 'LIVE_STREAM_OFFLINE':
                status_text = '⏹ 已下播'
            elif status == 'LOGIN_REQUIRED':
                status_text = '🔒 需要登录'
            elif status == 'AGE_VERIFICATION_REQUIRED':
                status_text = '🔞 年龄限制'
            else:
                status_text = '视频' if not status else status
        except Exception as e:
            pass

        safe_title = self._safe_title(title or video_id)

        if is_live and hls_url:
            play_sources = ['1080', '720', '480']
            play_urls = [
                f'{safe_title} 1080${video_id}@live1080',
                f'{safe_title} 720${video_id}@live720',
                f'{safe_title} 480${video_id}@live480',
            ]
            vod = {
                'vod_id': video_id,
                'vod_name': title or video_id,
                'vod_pic': f'http://127.0.0.1:9978/proxy?do=py&type=image&vid={video_id}',
                'vod_remarks': status_text,
                'vod_play_from': '$$$'.join(play_sources),
                'vod_play_url': '$$$'.join(play_urls)
            }
            return {'list': [vod]}

        if not title:
            title = self._get_video_title(video_id) or video_id
        safe_title = self._safe_title(title)

        play_sources = ['最高画质', 'Best', '1080p', '4k']
        play_urls = [
            f'{safe_title} 最高画质${video_id}@best',
            f'{safe_title} Best${video_id}@best',
            f'{safe_title} 1080p${video_id}@1080p',
            f'{safe_title} 4k${video_id}@4k'
        ]

        if status_text == '⏹ 已下播':
            try:
                data = self.yt.extract(video_id)
                if not data.get('formats'):
                    status_text = '⏹ 已下播（无回放）'
            except:
                status_text = '⏹ 已下播（无回放）'

        vod = {
            'vod_id': video_id,
            'vod_name': title,
            'vod_pic': f'http://127.0.0.1:9978/proxy?do=py&type=image&vid={video_id}',
            'vod_remarks': status_text,
            'vod_play_from': '$$$'.join(play_sources),
            'vod_play_url': '$$$'.join(play_urls)
        }
        return {'list': [vod]}

    def playerContent(self, flag, pid, vipFlags):
        raw_pid = pid.split('$')[-1]
        if '@' in raw_pid:
            video_id, quality = raw_pid.rsplit('@', 1)
        else:
            video_id, quality = raw_pid, 'best'
        if quality.startswith('live'):
            return self._play_live(video_id, quality)
        else:
            return self._play_video(video_id, quality)

    def _play_live(self, video_id, quality='live1080'):
        try:
            data = self.yt_live.extract_live(video_id)
            hls_url = data.get('hls_url') or ''
            if not hls_url:
                raise Exception('未获取到直播HLS地址')
            master_resp = self.session.get(hls_url, headers=self._hls_headers(hls_url, 'master'), timeout=(4, 9))
            master_resp.raise_for_status()
            variants = self._parse_variants(hls_url, master_resp.text)
            target_url = self._select_variant(variants, quality)
            if not target_url:
                target_url = hls_url
            if self.hls_proxy_enabled:
                play_url = self._cache_hls_url(target_url, video_id, 'playlist')
            else:
                play_url = target_url
            return {
                'parse': 0,
                'jx': 0,
                'url': play_url,
                'header': self.header,
                'format': 'application/x-mpegURL'
            }
        except Exception:
            return {'parse': 1, 'jx': 1, 'url': f'https://www.youtube.com/embed/{video_id}?autoplay=1'}

    def _play_video(self, video_id, quality):
        try:
            data = self.yt.extract(video_id)
            playable = self.yt.choose_playable(data['formats'], quality)
            if not playable:
                raise Exception('没有可用的视频流')
            audio = self.yt.choose_audio(data['formats'])
            if audio:
                cache_key = f'yt_{video_id}_{quality}'
                self.setCache(cache_key, {
                    'video_url': playable['url'],
                    'audio_url': audio['url'],
                    'video_item': playable,
                    'audio_item': audio,
                    'duration': data.get('duration') or 0,
                    'expires': time.time() + 300,
                })
                return {'parse': 0, 'jx': 0, 'url': f'http://127.0.0.1:9978/proxy?do=py&type=mpd&vid={video_id}&quality={quality}', 'format': 'application/dash+xml'}
            headers = self.header.copy()
            headers.update(playable.get('headers') or {})
            return {'parse': 0, 'jx': 0, 'url': playable['url'], 'header': headers}
        except Exception:
            return {'parse': 1, 'url': f'https://www.youtube.com/embed/{video_id}?autoplay=1'}

    # ---------- 搜索相关 ----------
    def _build_keyword(self, cid, filters=None):
        if cid.startswith('LIST:'):
            raw = cid[5:].strip()
            channels = [ch.strip() for ch in raw.split(',') if ch.strip()]
            terms = []
            for ch in channels:
                if ch.startswith('@'):
                    terms.append(f'channel:{ch}')
                else:
                    terms.append(f'"{ch}"')
            keyword = ' OR '.join(terms) if terms else ''
        else:
            keyword = str(cid or '').strip()
        if isinstance(filters, dict):
            for value in filters.values():
                term = self._normalize_filter_term(value)
                if term:
                    keyword += ' ' + term
        return keyword.strip()

    def _build_live_keyword(self, cid, filters=None):
        raw = str(cid or '').strip()
        terms = [raw if raw else 'live']
        if isinstance(filters, dict):
            for value in filters.values():
                term = self._normalize_filter_term(value)
                if term:
                    terms.append(term)
        keyword = ' '.join([x for x in terms if x]).strip()
        if 'live' not in keyword.lower() and '直播' not in keyword:
            keyword = f'{keyword} live'
        return keyword

    def _normalize_filter_term(self, value):
        if isinstance(value, (list, tuple)):
            return ' '.join([self._normalize_filter_term(item) for item in value if item])
        if isinstance(value, dict):
            return ' '.join([self._normalize_filter_term(item) for item in value.values() if item])
        return re.sub(r'\s+', ' ', str(value or '')).strip()[:180]

    def _search_cache_key(self, key):
        return re.sub(r'\s+', ' ', str(key or '')).strip().lower()

    def _search_youtube_page(self, key, page=1, live_filter=False):
        page = max(1, int(page or 1))
        cache_key = self._search_cache_key(key) + ('_live' if live_filter else '')
        session = self.search_cache.get(cache_key)
        if page == 1 or not session:
            session = self._fetch_search_first_page(key, live_filter)
            self.search_cache[cache_key] = session
        while len(session.get('pages', [])) < page and session.get('next'):
            data = self._fetch_search_continuation(session)
            videos = self._extract_videos_from_api(data, 30)
            session.setdefault('pages', []).append(videos)
            session['next'] = self._extract_continuation_token(data)
        pages = session.get('pages', [])
        videos = pages[page - 1] if len(pages) >= page else []
        has_more = bool(session.get('next')) or len(pages) > page
        return videos, has_more

    def _fetch_search_first_page(self, key, live_filter=False):
        sp_param = 'EgJAAQ%253D%253D' if live_filter else ''
        search_url = f'https://www.youtube.com/results?search_query={quote(str(key or ""))}'
        if sp_param:
            search_url += f'&sp={sp_param}'
        response = self.session.get(search_url, timeout=10)
        html_str = response.text
        data = self.yt._extract_json_after(html_str, 'ytInitialData') or {}
        ytcfg = self.yt._extract_ytcfg(html_str) or {}
        api_key = ytcfg.get('INNERTUBE_API_KEY') or self.yt._search(r'"INNERTUBE_API_KEY":"([^"]+)"', html_str)
        context = ytcfg.get('INNERTUBE_CONTEXT') or {'client': {'clientName': 'WEB', 'clientVersion': '2.20240310.01.00', 'hl': 'zh-CN', 'gl': 'US'}}
        client = context.get('client') or {}
        return {
            'key': key,
            'api_key': api_key,
            'context': context,
            'client_name': client.get('clientName') or 'WEB',
            'client_version': client.get('clientVersion') or '2.20240310.01.00',
            'referer': search_url,
            'pages': [self._extract_videos_from_api(data, 30)],
            'next': self._extract_continuation_token(data),
        }

    def _fetch_search_continuation(self, session):
        token = session.get('next')
        api_key = session.get('api_key')
        if not token or not api_key:
            return {}
        url = f'https://www.youtube.com/youtubei/v1/search?key={quote(api_key)}'
        headers = self.header.copy()
        headers.update({
            'Content-Type': 'application/json',
            'Origin': 'https://www.youtube.com',
            'Referer': session.get('referer') or 'https://www.youtube.com/',
            'X-YouTube-Client-Name': str(self.yt._client_name_id(session.get('client_name'))),
            'X-YouTube-Client-Version': session.get('client_version') or '2.20240310.01.00',
        })
        payload = {'context': session.get('context') or {}, 'continuation': token}
        response = self.session.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def _extract_continuation_token(self, data):
        tokens = []
        def scan(obj):
            if isinstance(obj, dict):
                endpoint = obj.get('continuationEndpoint') or {}
                token = endpoint.get('continuationCommand', {}).get('token')
                if token:
                    tokens.append(token)
                renderer = obj.get('continuationItemRenderer') or {}
                token = renderer.get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
                if token:
                    tokens.append(token)
                for value in obj.values():
                    scan(value)
            elif isinstance(obj, list):
                for value in obj:
                    scan(value)
        scan(data)
        return tokens[0] if tokens else ''

    def _extract_videos_from_api(self, data, limit=30):
        videos = []
        seen = set()
        def scan(obj):
            if len(videos) >= limit:
                return
            if isinstance(obj, dict):
                for key in ('videoRenderer', 'compactVideoRenderer', 'gridVideoRenderer', 'reelItemRenderer'):
                    if key in obj:
                        item = self._parse_renderer(obj[key])
                        if item and item['vod_id'] not in seen:
                            seen.add(item['vod_id'])
                            videos.append(item)
                for value in obj.values():
                    scan(value)
            elif isinstance(obj, list):
                for value in obj:
                    scan(value)
        scan(data)
        return videos[:limit]

    def _parse_renderer(self, renderer):
        try:
            video_id = renderer.get('videoId')
            if not video_id:
                nav = renderer.get('navigationEndpoint') or {}
                video_id = (nav.get('watchEndpoint') or {}).get('videoId')
            if not video_id:
                return None
            title_obj = renderer.get('title') or renderer.get('headline') or {}
            title = title_obj.get('simpleText') or ''.join([x.get('text', '') for x in title_obj.get('runs', [])]) or 'YouTube Video'

            dur_obj = renderer.get('lengthText') or {}
            dur = dur_obj.get('simpleText') or ''
            is_live = False
            badges = renderer.get('badges') or []
            for badge in badges:
                style = badge.get('metadataBadgeRenderer', {}).get('style', '')
                if 'LIVE' in style.upper():
                    is_live = True
                    break
            if is_live and dur and dur.upper() != 'LIVE':
                is_live = False

            if is_live:
                remarks = '🔴 直播'
            else:
                remarks = dur if dur else '视频'

            return {
                'vod_id': video_id,
                'vod_name': html.unescape(title),
                'vod_pic': f'http://127.0.0.1:9978/proxy?do=py&type=image&vid={video_id}',
                'vod_remarks': remarks
            }
        except Exception:
            return None

    def _get_video_title(self, video_id):
        try:
            response = self.session.get(f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json', timeout=5)
            return response.json().get('title') or video_id
        except Exception:
            return video_id

    def _safe_title(self, title):
        if not title:
            return 'video'
        return re.sub(r'[#$@%&!?*|\\/:<>]', ' ', title)[:60]

    def localProxy(self, params):
        if params.get('do') != 'py':
            return None
        typ = params.get('type')
        if typ == 'mpd':
            return self._proxy_mpd(params)
        if typ == 'media':
            return self._proxy_media(params)
        if typ == 'single':
            return self._proxy_single(params)
        if typ == 'image':
            return self._proxy_image(params)
        if typ == 'hls':
            return self._proxy_hls(params)
        return None

    def _proxy_image(self, params):
        vid = params.get('vid')
        if not vid:
            return [400, 'text/plain', '缺少 video id']
        quality = params.get('quality', 'hqdefault')
        img_url = f'https://i.ytimg.com/vi/{vid}/{quality}.jpg'
        try:
            r = self.session.get(img_url, timeout=10)
            if r.status_code == 200:
                content_type = r.headers.get('content-type', 'image/jpeg')
                return [200, content_type, r.content, {'Cache-Control': 'max-age=86400'}]
            else:
                return [404, 'text/plain', f'图片不存在 ({r.status_code})']
        except Exception as e:
            return [500, 'text/plain', f'代理图片失败: {str(e)}']

    def _proxy_single(self, params):
        vid = params.get('vid')
        data = self.getCache(f'yt_single_{vid}') if vid else None
        if not data:
            return [404, 'text/plain', '播放缓存已过期或不存在']
        target_url = data.get('url')
        if not target_url:
            return [404, 'text/plain', '播放地址不存在']
        headers = (data.get('headers') or self.header).copy()
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            content_type = r.headers.get('content-type', 'video/mp4')
            resp_headers = {
                'Content-Type': content_type,
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'no-cache',
            }
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            return [500, 'text/plain', f'代理播放失败: {str(e)}']

    def _proxy_mpd(self, params):
        vid = params.get('vid')
        quality = params.get('quality') or '1080p'
        data = self.getCache(f'yt_{vid}_{quality}') if vid else None
        if not data:
            return [404, 'text/plain', '视频缓存已过期或不存在']
        video_url = data.get('video_url')
        audio_url = data.get('audio_url')
        duration = data.get('duration') or 0
        video_item = data.get('video_item') or {}
        audio_item = data.get('audio_item') or {}
        media_base = f'http://127.0.0.1:9978/proxy?do=py&type=media&vid={vid}&quality={quality}'
        duration_pt = f"PT{int(duration or 0)}S"
        video_mime = (video_item.get('mimeType') or 'video/webm').split(';')[0]
        audio_mime = (audio_item.get('mimeType') or 'audio/mp4').split(';')[0]
        video_init = video_item.get('initRange') or {}
        video_index = video_item.get('indexRange') or {}
        audio_init = audio_item.get('initRange') or {}
        audio_index = audio_item.get('indexRange') or {}
        mpd = f'''<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="{duration_pt}" minBufferTime="PT1.5S" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
  <Period id="1" start="PT0S">
    <AdaptationSet mimeType="{html.escape(video_mime)}" startWithSAP="1" segmentAlignment="true" scanType="progressive">
      <Representation id="v{video_item.get('itag', 1)}" bandwidth="{video_item.get('bitrate', 1000000)}" codecs="{html.escape(video_item.get('codecs') or '')}" height="{video_item.get('height', 0)}" width="{video_item.get('width', 0)}">
        <BaseURL>{html.escape(media_base + '&track=video')}</BaseURL>
        <SegmentBase indexRange="{video_index.get('start', '0')}-{video_index.get('end', '0')}"><Initialization range="{video_init.get('start', '0')}-{video_init.get('end', '0')}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        if audio_url:
            mpd += f'''    <AdaptationSet mimeType="{html.escape(audio_mime)}" startWithSAP="1" segmentAlignment="true" lang="und">
      <Representation id="a{audio_item.get('itag', 1)}" bandwidth="{audio_item.get('bitrate', 128000)}" codecs="{html.escape(audio_item.get('codecs') or '')}" audioSamplingRate="44100">
        <BaseURL>{html.escape(media_base + '&track=audio')}</BaseURL>
        <SegmentBase indexRange="{audio_index.get('start', '0')}-{audio_index.get('end', '0')}"><Initialization range="{audio_init.get('start', '0')}-{audio_init.get('end', '0')}"/></SegmentBase>
      </Representation>
    </AdaptationSet>
'''
        mpd += '  </Period>\n</MPD>'
        return [200, 'application/dash+xml', mpd]

    def _proxy_media(self, params):
        vid = params.get('vid')
        quality = params.get('quality') or '1080p'
        track = params.get('track')
        data = self.getCache(f'yt_{vid}_{quality}') if vid else None
        if not data or track not in ('video', 'audio'):
            return [404, 'text/plain', '媒体不存在']
        target_url = data.get('video_url') if track == 'video' else data.get('audio_url')
        if not target_url:
            return [404, 'text/plain', f'{track} 流不存在']
        media_item = data.get('video_item') if track == 'video' else data.get('audio_item')
        headers = self.header.copy()
        headers.update((media_item or {}).get('headers') or {})
        range_header = params.get('range') or params.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            r = self.session.get(target_url, headers=headers, stream=True, timeout=30)
            content_type = r.headers.get('content-type', 'application/octet-stream')
            resp_headers = {'Content-Type': content_type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-cache'}
            if r.headers.get('content-range'):
                resp_headers['Content-Range'] = r.headers.get('content-range')
            if r.headers.get('content-length'):
                resp_headers['Content-Length'] = r.headers.get('content-length')
            return [r.status_code, content_type, r.content, resp_headers]
        except Exception as e:
            return [500, 'text/plain', f'代理媒体失败: {str(e)}']

    HLS_TTL = {'master': 6 * 3600, 'playlist': 6 * 3600, 'media': 120, 'media_retry': 120}

    def _hls_ttl(self, kind):
        return self.HLS_TTL.get(kind, 180)

    def _prune_hls_cache(self):
        now = time.time()
        expired = [k for k, v in self.hls_url_cache.items() if v.get('expires', 0) < now]
        for k in expired:
            self.hls_url_cache.pop(k, None)

    def _cache_hls_url(self, target_url, video_id='', kind='media'):
        self._prune_hls_cache()
        self._hls_key_seq += 1
        key = f'{int(time.time() * 1000)}_{self._hls_key_seq}'
        self.hls_url_cache[key] = {
            'url': target_url,
            'video_id': video_id,
            'kind': kind,
            'expires': time.time() + self._hls_ttl(kind),
        }
        return f'http://127.0.0.1:9978/proxy?do=py&type=hls&key={quote(key)}'

    def _request_hls(self, target_url, kind, key):
        last_error = None
        response = None
        for attempt, delay in enumerate((0, 0.25, 0.7), 1):
            if delay:
                time.sleep(delay)
            try:
                headers_kind = 'media_retry' if kind == 'media' and attempt > 1 else kind
                headers = self._hls_headers(target_url, headers_kind)
                response = self.session.get(target_url, headers=headers, timeout=(4, 9))
                if response.status_code not in (403, 408, 429, 500, 502, 503, 504):
                    return response, attempt, None
                last_error = Exception(f'HTTP {response.status_code}')
                response.close()
                response = None
            except (requests.Timeout, requests.ConnectionError) as e:
                last_error = e
                if response is not None:
                    response.close()
                    response = None
        return None, 3, last_error

    def _refresh_hls_target(self, item, key):
        video_id = item.get('video_id') or ''
        kind = item.get('kind') or ''
        if not video_id or kind not in ('master', 'playlist'):
            return ''
        try:
            self.yt_live.cache.pop(video_id, None)
            data = self.yt_live.extract_live(video_id)
            master_url = data.get('hls_url') or ''
            if not master_url:
                return ''
            refreshed_url = master_url
            if kind == 'playlist':
                master = self.session.get(master_url, headers=self._hls_headers(master_url, 'master'), timeout=(4, 9))
                master.raise_for_status()
                refreshed_url = self._pick_variant_playlist(master_url, master.text) or ''
            if refreshed_url:
                item['url'] = refreshed_url
                item['expires'] = time.time() + self._hls_ttl(kind)
            return refreshed_url
        except Exception:
            return ''

    def _parse_variants(self, base_url, text):
        lines = [line.strip() for line in (text or '').splitlines()]
        variants = []
        for i, line in enumerate(lines):
            if not line.startswith('#EXT-X-STREAM-INF'):
                continue
            res_match = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
            if not res_match:
                continue
            height = int(res_match.group(2))
            for j in range(i + 1, len(lines)):
                next_line = lines[j].strip()
                if not next_line or next_line.startswith('#'):
                    continue
                absolute_url = urljoin(base_url, next_line)
                variants.append((height, absolute_url))
                break
        variants.sort(key=lambda x: x[0], reverse=True)
        return variants

    def _select_variant(self, variants, quality):
        quality_map = {'live1080': 1080, 'live720': 720, 'live480': 480, 'live360': 360, 'live240': 240}
        target_height = quality_map.get(quality, 0)
        if not target_height or not variants:
            return variants[0][1] if variants else None
        best_match = None
        best_diff = float('inf')
        for height, url in variants:
            diff = abs(height - target_height)
            if diff < best_diff:
                best_diff = diff
                best_match = url
        return best_match

    def _proxy_hls(self, params):
        key = params.get('key') or ''
        item = self.hls_url_cache.get(key)
        if not item or item.get('expires', 0) < time.time():
            return [404, 'text/plain', 'HLS 缓存已过期']
        item['expires'] = time.time() + self._hls_ttl(item.get('kind'))
        kind = item.get('kind') or 'media'
        target_url = item.get('url') or ''
        try:
            response, attempts, error = self._request_hls(target_url, kind, key)
            refreshed = False
            if response is None and kind in ('master', 'playlist'):
                target_url = self._refresh_hls_target(item, key)
                if target_url:
                    refreshed = True
                    response, refresh_attempts, error = self._request_hls(target_url, kind, key)
                    attempts += refresh_attempts
            if response is None:
                raise error or Exception('HLS 请求失败')
            content_type = response.headers.get('content-type') or ''
            is_m3u8 = kind in ('master', 'playlist') or 'mpegurl' in content_type.lower() or target_url.split('?')[0].endswith('.m3u8')
            if is_m3u8:
                text = response.text
                rewritten = self._rewrite_m3u8(text, target_url, item.get('video_id') or '')
                return [response.status_code, 'application/vnd.apple.mpegurl', rewritten, {'Content-Type': 'application/vnd.apple.mpegurl', 'Cache-Control': 'no-cache'}]
            resp_headers = {'Content-Type': content_type or 'application/octet-stream', 'Cache-Control': 'no-cache'}
            if response.headers.get('content-length'):
                resp_headers['Content-Length'] = response.headers.get('content-length')
            return [response.status_code, content_type or 'application/octet-stream', response.content, resp_headers]
        except Exception as e:
            return [504, 'text/plain', f'HLS 上游超时或不可用: {str(e)}']

    def _hls_headers(self, target_url, kind=None):
        if kind == 'media_retry':
            return {
                'User-Agent': 'com.google.android.youtube/21.02.35 (Linux; U; Android 11) gzip',
                'Accept': '*/*',
            }
        headers = self.header.copy()
        headers['Accept'] = '*/*'
        if kind in ('master', 'playlist'):
            headers['Origin'] = 'https://www.youtube.com'
            headers['Referer'] = 'https://www.youtube.com/'
        elif kind == 'media':
            headers['User-Agent'] = 'com.google.android.youtube/21.02.35 (Linux; U; Android 11) gzip'
            headers.pop('Origin', None)
            headers.pop('Referer', None)
        return headers

    def _pick_variant_playlist(self, base_url, text):
        lines = [line.strip() for line in (text or '').splitlines()]
        best_score = -1
        best_url = ''
        for index, line in enumerate(lines):
            if not line.startswith('#EXT-X-STREAM-INF'):
                continue
            score = 0
            bandwidth = re.search(r'BANDWIDTH=(\d+)', line)
            resolution = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
            if bandwidth:
                score += int(bandwidth.group(1))
            if resolution:
                score += int(resolution.group(1)) * int(resolution.group(2))
            for next_line in lines[index + 1:]:
                if not next_line or next_line.startswith('#'):
                    continue
                if score > best_score:
                    best_score = score
                    best_url = urljoin(base_url, next_line)
                break
        return best_url

    def _rewrite_m3u8(self, text, base_url, video_id=''):
        output = []
        for line in (text or '').splitlines():
            stripped = line.strip()
            if not stripped:
                output.append(line)
                continue
            if stripped.startswith('#'):
                output.append(self._rewrite_m3u8_tag(line, base_url, video_id))
                continue
            absolute = urljoin(base_url, stripped)
            kind = 'playlist' if stripped.endswith('.m3u8') or '/hls_playlist/' in stripped else 'media'
            output.append(self._cache_hls_url(absolute, video_id, kind))
        return '\n'.join(output) + '\n'

    def _rewrite_m3u8_tag(self, line, base_url, video_id=''):
        def replace_uri(match):
            raw_url = match.group(1)
            absolute = urljoin(base_url, raw_url)
            proxied = self._cache_hls_url(absolute, video_id, 'media')
            return f'URI="{proxied}"'
        return re.sub(r'URI="([^"]+)"', replace_uri, line)

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass