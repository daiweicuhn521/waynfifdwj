# -*- coding: utf-8 -*-
"""
囧次元动漫 Python Spider — 兼容 FongMi/TV (T3) 与 WebHomeTV / PeekPro (T4)
站点: https://www.jciyuan.com/

特性:
  - 【全线路解锁】API 完全开放，所有线路（含VIP/会员线路）无需登录即可获取
    网页端登录仅为展示广告，API 层面无任何限制
  - 【加密源本地解密】NBY/Ace/YYNB/yydm 等加密源通过 bfq.lggys.com 官方播放器
    本地 AES-128-CBC 解密出真实 m3u8 直链，parse=0 直接播放
  - 【秒开直链】极速m3u8（jsm3u8）是直链源，parse=0 秒开播放
  - 【智能排序】直链源排最前，加密源按质量优先级排序
  - 【二级分类】各分类有类型子分类筛选（客户端过滤）
  - 【多级缓存】首页/分类/详情，加载速度提升数千倍
  - 【连接池】HTTP Session 连接复用，减少 TCP 握手开销
  - 【完整Header】播放时附带 UA/Referer/Origin/Accept，降低鉴权失败率
  - 【纯Python AES兜底】无 pycryptodome 时内置纯Python AES-128-CBC 解密
"""

import sys
import json
import re
import time
import base64
from collections import OrderedDict

sys.path.append('..')

# ===== 兼容导入 =====
try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass

    class Spider:
        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = _rq.get(url, headers=headers, timeout=timeout, verify=False, **kw)
            r.encoding = 'utf-8'
            return r

from urllib.parse import quote, urlencode

# ===== AES 解密支持 =====
try:
    from Crypto.Cipher import AES
except ImportError:
    # TVBox 内置 Python 运行时默认没有 pycryptodome
    # 使用内置纯 Python AES-128-CBC 解密兜底
    AES = None

if AES is None:
    def _aes_gmul(a, b):
        p = 0
        for _ in range(8):
            if b & 1:
                p ^= a
            hi = a & 0x80
            a = (a << 1) & 0xFF
            if hi:
                a ^= 0x1B
            b >>= 1
        return p

    def _aes_build_tables():
        exp = [0] * 256
        log = [0] * 256
        x = 1
        for i in range(255):
            exp[i] = x
            log[x] = i
            x = _aes_gmul(x, 3)
        exp[255] = 1
        sbox = [0] * 256
        sbox[0] = 0x63
        for i in range(1, 256):
            b = exp[(255 - log[i]) % 255]
            s = b
            v = ((b << 1) | (b >> 7)) & 0xFF
            s ^= v
            v = ((v << 1) | (v >> 7)) & 0xFF
            s ^= v
            v = ((v << 1) | (v >> 7)) & 0xFF
            s ^= v
            v = ((v << 1) | (v >> 7)) & 0xFF
            s ^= v
            sbox[i] = s ^ 0x63
        inv_sbox = [0] * 256
        for i, v in enumerate(sbox):
            inv_sbox[v] = i
        return sbox, inv_sbox

    _SBOX, _INV_SBOX = _aes_build_tables()
    _RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)

    def _aes_key_expansion(key):
        w = [list(key[4 * i:4 * i + 4]) for i in range(4)]
        for i in range(4, 44):
            t = list(w[i - 1])
            if i % 4 == 0:
                t = t[1:] + t[:1]
                t = [_SBOX[b] for b in t]
                t[0] ^= _RCON[i // 4 - 1]
            w.append([t[j] ^ w[i - 4][j] for j in range(4)])
        return w

    def _aes_add_round_key(state, w, rnd):
        for c in range(4):
            for r in range(4):
                state[r][c] ^= w[rnd * 4 + c][r]

    def _aes_inv_shift_rows(state):
        for r in range(1, 4):
            state[r] = state[r][-r:] + state[r][:-r]

    def _aes_inv_sub_bytes(state):
        for r in range(4):
            for c in range(4):
                state[r][c] = _INV_SBOX[state[r][c]]

    def _aes_inv_mix_columns(state):
        for c in range(4):
            a0, a1, a2, a3 = state[0][c], state[1][c], state[2][c], state[3][c]
            state[0][c] = (_aes_gmul(a0, 14) ^ _aes_gmul(a1, 11)
                           ^ _aes_gmul(a2, 13) ^ _aes_gmul(a3, 9))
            state[1][c] = (_aes_gmul(a0, 9) ^ _aes_gmul(a1, 14)
                           ^ _aes_gmul(a2, 11) ^ _aes_gmul(a3, 13))
            state[2][c] = (_aes_gmul(a0, 13) ^ _aes_gmul(a1, 9)
                           ^ _aes_gmul(a2, 14) ^ _aes_gmul(a3, 11))
            state[3][c] = (_aes_gmul(a0, 11) ^ _aes_gmul(a1, 13)
                           ^ _aes_gmul(a2, 9) ^ _aes_gmul(a3, 14))

    def _aes_decrypt_block(block, w):
        state = [[0] * 4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                state[r][c] = block[4 * c + r]
        _aes_add_round_key(state, w, 10)
        for rnd in range(9, 0, -1):
            _aes_inv_shift_rows(state)
            _aes_inv_sub_bytes(state)
            _aes_add_round_key(state, w, rnd)
            _aes_inv_mix_columns(state)
        _aes_inv_shift_rows(state)
        _aes_inv_sub_bytes(state)
        _aes_add_round_key(state, w, 0)
        out = bytearray(16)
        for r in range(4):
            for c in range(4):
                out[4 * c + r] = state[r][c]
        return bytes(out)

    class _PureAES:
        MODE_CBC = 2

        @staticmethod
        def new(key, mode, iv):
            return _PureAES(key, mode, iv)

        def __init__(self, key, mode, iv):
            assert mode == self.MODE_CBC
            assert len(key) == 16
            self._w = _aes_key_expansion(key)
            self._iv = bytes(iv)

        def decrypt(self, data):
            out = bytearray()
            prev = self._iv
            n = len(data) - (len(data) % 16)
            for i in range(0, n, 16):
                blk = data[i:i + 16]
                plain = _aes_decrypt_block(blk, self._w)
                for j in range(16):
                    out.append(plain[j] ^ prev[j])
                prev = blk
            return bytes(out)

    AES = _PureAES


# ============================================================
# 常量
# ============================================================

HOST = "https://www.jciyuan.com"
API = HOST + "/api.php/provide/vod/"
UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Mobile Safari/537.36")

# 线路显示名称映射
# ⚡ = 直链源（parse=0，秒开）
# 🔓 = 加密源（可本地解密，parse=0 直链播放）
LINE_NAMES = {
    "jsm3u8": "⚡极速m3u8",
    "NBY": "🔓纯享(NBY)",
    "YYNB": "🔓优享(YYNB)",
    "Ace": "🔓ACE云",
    "yydm": "🔓优享①(yydm)",
    "liangzi": "🔓亮子",
    "feifan": "🔓非凡",
    "ATQP2": "🔓安卓奇葩",
    "dyttm3u8": "⚡TT(dyttm3u8)",
}

# 线路质量优先级（数字越小越优先）
# 直链 m3u8 排最前，其余按历史稳定性排序
LINE_PRIORITY = {
    "jsm3u8": 0,     # ⚡直链，最快
    "dyttm3u8": 1,   # ⚡直链
    "NBY": 10,       # 🔓加密可解密，质量较好
    "Ace": 11,       # 🔓加密可解密
    "YYNB": 12,      # 🔓加密可解密
    "yydm": 13,      # 🔓加密可解密
    "liangzi": 20,   # 🔓加密可解密
    "feifan": 21,    # 🔓加密可解密
    "ATQP2": 22,     # 🔓加密可解密
}

# 直链线路集合（parse=0，直接播放）
DIRECT_LINES = {"jsm3u8", "dyttm3u8", "m3u8", "mp4"}

# 加密线路前缀（需要 bfq 播放器解密）
_ENCRYPTED_ROUTE_PREFIXES = (
    "NBY", "Ace_", "Ace-", "yydm_", "yydm-",
    "YYNB_", "YYNB-", "dyttm3u8_", "dyttm3u8-",
)

# bfq 官方播放器地址（用于解密 NBY/Ace/YYNB 等加密线路）
BFQ_PARSE_URL = "https://bfq.lggys.com/player?url="

# 公共解析服务（备用，bfq 失败时用）
PARSE_URLS = [
    "https://jx.playerjy.com/?url=",
    "https://jx.xmflv.com/?url=",
]

# 分类列表（type_id 对应苹果CMS分类ID）
CLASSES = [
    {"type_name": "日本动漫", "type_id": "20"},
    {"type_name": "国产动漫", "type_id": "21"},
    {"type_name": "欧美动漫", "type_id": "22"},
    {"type_name": "剧场版", "type_id": "26"},
]

# 通用年份/排序筛选器
_YEAR_FILTER = {"key": "year", "name": "年份", "value": [
    {"n": "全部", "v": ""},
    {"n": "2026", "v": "2026"},
    {"n": "2025", "v": "2025"},
    {"n": "2024", "v": "2024"},
    {"n": "2023", "v": "2023"},
    {"n": "2022", "v": "2022"},
    {"n": "2021", "v": "2021"},
    {"n": "2020", "v": "2020"},
]}
_BY_FILTER = {"key": "by", "name": "排序", "value": [
    {"n": "最新", "v": "time"},
    {"n": "最热", "v": "hits"},
    {"n": "评分", "v": "score"},
]}

# 各分类的类型子分类（基于 vod_class 字段统计）
_CLASS_FILTERS = {
    # 日本动漫 type_id=20
    "20": [
        {"n": "全部", "v": ""},
        {"n": "恋爱", "v": "恋爱"},
        {"n": "奇幻", "v": "奇幻"},
        {"n": "后宫", "v": "后宫"},
        {"n": "战斗", "v": "战斗"},
        {"n": "校园", "v": "校园"},
        {"n": "搞笑", "v": "搞笑"},
        {"n": "异世界", "v": "异世界"},
        {"n": "青春", "v": "青春"},
        {"n": "动作", "v": "动作"},
        {"n": "冒险", "v": "冒险"},
        {"n": "热血", "v": "热血"},
        {"n": "悬疑", "v": "悬疑"},
        {"n": "日常", "v": "日常"},
        {"n": "玄幻", "v": "玄幻"},
        {"n": "魔幻", "v": "魔幻"},
        {"n": "励志", "v": "励志"},
        {"n": "恐怖", "v": "恐怖"},
        {"n": "惊悚", "v": "惊悚"},
        {"n": "喜剧", "v": "喜剧"},
        {"n": "轻小说改", "v": "轻小说改"},
        {"n": "小说改", "v": "小说改"},
        {"n": "漫画改", "v": "漫画改"},
        {"n": "原创", "v": "原创"},
        {"n": "续作", "v": "续作"},
    ],
    # 国产动漫 type_id=21
    "21": [
        {"n": "全部", "v": ""},
        {"n": "奇幻", "v": "奇幻"},
        {"n": "热血", "v": "热血"},
        {"n": "古装", "v": "古装"},
        {"n": "逆袭", "v": "逆袭"},
        {"n": "动作", "v": "动作"},
        {"n": "玄幻", "v": "玄幻"},
        {"n": "复仇", "v": "复仇"},
        {"n": "日常", "v": "日常"},
        {"n": "科幻", "v": "科幻"},
        {"n": "末日", "v": "末日"},
        {"n": "系统", "v": "系统"},
        {"n": "搞笑", "v": "搞笑"},
    ],
    # 欧美动漫 type_id=22
    "22": [
        {"n": "全部", "v": ""},
        {"n": "奇幻", "v": "奇幻"},
        {"n": "喜剧", "v": "喜剧"},
        {"n": "冒险", "v": "冒险"},
        {"n": "科幻", "v": "科幻"},
        {"n": "战斗", "v": "战斗"},
        {"n": "家庭", "v": "家庭"},
        {"n": "热血", "v": "热血"},
        {"n": "剧情", "v": "剧情"},
        {"n": "动作", "v": "动作"},
        {"n": "短片", "v": "短片"},
        {"n": "校园", "v": "校园"},
        {"n": "搞笑", "v": "搞笑"},
    ],
    # 剧场版 type_id=26
    "26": [
        {"n": "全部", "v": ""},
        {"n": "悬疑", "v": "悬疑"},
        {"n": "犯罪", "v": "犯罪"},
        {"n": "冒险", "v": "冒险"},
        {"n": "动作", "v": "动作"},
        {"n": "科幻", "v": "科幻"},
        {"n": "剧情", "v": "剧情"},
        {"n": "惊悚", "v": "惊悚"},
        {"n": "推理", "v": "推理"},
        {"n": "都市奇幻", "v": "都市奇幻"},
        {"n": "商界风云", "v": "商界风云"},
        {"n": "逆袭", "v": "逆袭"},
    ],
}

# 构建各分类的完整筛选器
FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    FILTERS[tid] = [
        {"key": "class", "name": "类型",
         "value": _CLASS_FILTERS.get(tid, [{"n": "全部", "v": ""}])},
        _YEAR_FILTER,
        _BY_FILTER,
    ]

# ============================================================
# LRU 缓存工具
# ============================================================

class _LRUCache:
    """简单的 LRU 缓存"""
    def __init__(self, maxsize=50, ttl=300):
        self.cache = OrderedDict()
        self.maxsize = maxsize
        self.ttl = ttl  # 秒

    def get(self, key):
        if key not in self.cache:
            return None
        value, expire_at = self.cache[key]
        if time.time() > expire_at:
            del self.cache[key]
            return None
        self.cache.move_to_end(key)
        return value

    def set(self, key, value):
        expire_at = time.time() + self.ttl
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (value, expire_at)
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)


# ============================================================
# Spider 主类
# ============================================================

class Spider(Spider):

    def getName(self):
        return "囧次元动漫"

    # ===== 初始化 =====
    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ""
        else:
            self.extend = extend or ""

        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        # 会话连接池（复用连接，提升速度）
        self._session = None
        try:
            import requests
            self._session = requests.Session()
            self._session.verify = False
            self._session.headers.update(self.header)
            # 禁用自动重试（自己控制）
            from requests.adapters import HTTPAdapter
            adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
        except Exception:
            pass

        # 首页缓存（10 分钟）
        self._home_cache = []
        self._home_cache_time = 0
        self._home_cache_ttl = 600

        # 详情页 LRU 缓存（最多 30 条，缓存 5 分钟）
        self._detail_cache = _LRUCache(maxsize=30, ttl=300)

        # 分类页缓存（按URL，最多 20 条，缓存 3 分钟）
        self._category_cache = _LRUCache(maxsize=20, ttl=180)

    # ===== 网络工具（优化版） =====
    def _do_request(self, url, timeout=8):
        """发送请求，优先使用 session 连接池"""
        try:
            if self._session:
                rsp = self._session.get(url, timeout=timeout)
                rsp.encoding = 'utf-8'
                return rsp
        except Exception:
            pass
        # fallback 到基类 fetch
        try:
            return self.fetch(url, headers=self.header, timeout=timeout)
        except Exception:
            return None

    def _get_json(self, url, timeout=8):
        """GET 请求返回 JSON dict，异常返回 None"""
        try:
            rsp = self._do_request(url, timeout=timeout)
            if rsp is None:
                return None
            text = rsp.text
            if not text:
                return None
            return json.loads(text)
        except Exception:
            return None

    # ===== 媒体判断 =====
    def _is_direct_media(self, url):
        url = (url or "").lower()
        return bool(re.search(r'\.(m3u8|mp4|flv|mkv|ts|mov|avi|webm)(\?|$)', url))

    def _looks_like_video_url(self, url):
        """宽松判断 URL 是否可能是视频直链（用于解密结果判断）"""
        if not url or not url.startswith("http"):
            return False
        # 常见视频 CDN 域名
        video_cdns = [
            "xhscdn.com", "jisuzyv.com", "nbyjson.top",
            "videocdn2.com", "cdn", "video", "play",
            "v.", "play.", "cdn-",
        ]
        low = url.lower()
        for cdn in video_cdns:
            if cdn in low:
                return True
        # URL 含视频特征路径
        if "/m3u8/" in low or "/video/" in low or "/play/" in low:
            return True
        return False

    def _extract_referer(self, url):
        """从 URL 提取 origin 作为 Referer"""
        try:
            if "://" in url:
                scheme = url.split("://")[0]
                host = url.split("://")[1].split("/")[0]
                return scheme + "://" + host + "/"
        except Exception:
            pass
        return HOST + "/"

    # ===== 内容字段处理 =====
    def _strip_tags(self, s):
        return re.sub(r'<[^>]+>', '', s or '').strip()

    # ===== 卡片格式 =====
    def _card(self, v):
        """API 视频卡片 -> TVBox 格式"""
        vid = v.get("vod_id", "")
        pic = v.get("vod_pic", "") or ""
        if pic.startswith("//"):
            pic = "https:" + pic
        return {
            "vod_id": str(vid),
            "vod_name": v.get("vod_name", ""),
            "vod_pic": pic,
            "vod_remarks": v.get("vod_remarks", "") or v.get("vod_year", "") or "HD",
        }

    # ===== 解析 play_url =====
    def _parse_play(self, play_from_raw, play_url_raw):
        """
        解析苹果CMS的 play_from 和 play_url
        按线路质量优先级排序：直链源在前，加密源在后
        返回 (play_from_list, play_url_list, line_keys_list)
        """
        if not play_from_raw or not play_url_raw:
            return [], [], []

        from_list = play_from_raw.split("$$$")
        url_groups = play_url_raw.split("$$$")

        # 收集所有线路 (原始key, 显示名, url组字符串)
        lines = []
        for i, from_name in enumerate(from_list):
            if i >= len(url_groups):
                break
            url_group = url_groups[i]
            if not url_group.strip():
                continue
            key = from_name.strip()
            display = LINE_NAMES.get(key, key)
            lines.append((key, display, url_group))

        # 排序：直链源排最前，再按线路优先级
        def _sort_key(item):
            key, display, url_group = item
            # 判断是否直链
            is_direct = key in DIRECT_LINES
            # 如果不在已知列表中，通过URL判断
            if not is_direct:
                first_ep = url_group.split("#")[0]
                first_url = first_ep.split("$", 1)[1] if "$" in first_ep else ""
                is_direct = self._is_direct_media(first_url)
            priority = LINE_PRIORITY.get(key, 99)
            # 直链排最前（用 0 前缀），非直链用 1 前缀
            return (0 if is_direct else 1, priority)

        lines.sort(key=_sort_key)

        # 重新组装
        play_from = []
        play_url = []
        line_keys = []
        for key, display, url_group in lines:
            eps = url_group.split("#")
            ep_list = []
            for ep in eps:
                ep = ep.strip()
                if not ep:
                    continue
                if "$" in ep:
                    ep_name, ep_url = ep.split("$", 1)
                    ep_list.append("%s$%s" % (ep_name, ep_url))
                else:
                    ep_list.append("第%s集$%s" % (len(ep_list) + 1, ep))
            if ep_list:
                play_from.append(display)
                play_url.append("#".join(ep_list))
                line_keys.append(key)

        return play_from, play_url, line_keys

    # ============================================================
    # 首页
    # ============================================================

    def homeContent(self, filter):
        return {
            "class": CLASSES,
            "filters": FILTERS,
        }

    def homeVideoContent(self):
        """首页推荐：带缓存，命中直接返回"""
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < self._home_cache_ttl:
            return {"list": self._home_cache[:72]}

        url = API + "?ac=videolist&pg=1&limit=30"
        data = self._get_json(url, timeout=8)
        videos = []
        if data and data.get("code") == 1:
            for v in data.get("list", []):
                videos.append(self._card(v))

        self._home_cache = videos[:72]
        self._home_cache_time = now
        return {"list": self._home_cache}

    # ============================================================
    # 分类列表
    # ============================================================

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            # 解析 extend
            ext = {}
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                elif isinstance(extend, str):
                    try:
                        ext = json.loads(extend)
                    except Exception:
                        ext = {}

            need_class_filter = bool(ext.get("class"))
            need_year_filter = bool(ext.get("year"))

            # 构建缓存 key
            cache_key = "cat_%s_p%d_%s_%s_%s" % (
                tid, page,
                ext.get("class", ""),
                ext.get("year", ""),
                ext.get("by", "")
            )

            # 尝试从缓存读取（仅当无客户端筛选时缓存才有意义，
            # 但为了简单起见，全部缓存，筛选后也缓存）
            cached = self._category_cache.get(cache_key)
            if cached:
                return cached

            # 构建API参数
            params = {
                "ac": "videolist",
                "t": str(tid),
                "pg": str(page),
            }
            if ext.get("by"):
                params["by"] = ext["by"]

            url = API + "?" + urlencode(params)
            data = self._get_json(url, timeout=8)

            if not data or data.get("code") != 1:
                result = {"page": page, "pagecount": 1,
                          "limit": 20, "total": 0, "list": []}
                self._category_cache.set(cache_key, result)
                return result

            raw_list = data.get("list", [])
            pagecount = int(data.get("pagecount", 1))
            total = int(data.get("total", len(raw_list)))

            # 客户端筛选
            if need_class_filter or need_year_filter:
                class_kw = ext.get("class", "")
                year_kw = ext.get("year", "")
                filtered = []
                for v in raw_list:
                    vc = v.get("vod_class", "") or ""
                    vy = str(v.get("vod_year", "") or "")
                    if class_kw and class_kw not in vc:
                        continue
                    if year_kw and year_kw != vy:
                        continue
                    filtered.append(v)
                raw_list = filtered

            vods = [self._card(v) for v in raw_list]

            result = {
                "list": vods,
                "page": page,
                "pagecount": pagecount,
                "limit": 20,
                "total": total,
            }
            self._category_cache.set(cache_key, result)
            return result
        except Exception:
            return {"page": 1, "pagecount": 1,
                    "limit": 20, "total": 0, "list": []}

    # ============================================================
    # 详情页
    # ============================================================

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = str(ids[0])

        # 尝试缓存
        cached = self._detail_cache.get(vod_id)
        if cached:
            return cached

        url = API + "?ac=detail&ids=" + vod_id

        # 2次重试（减少等待，提升速度）
        data = None
        for attempt in range(2):
            data = self._get_json(url, timeout=8)
            if data and data.get("code") == 1 and data.get("list"):
                break
            time.sleep(0.3)

        if not data or data.get("code") != 1:
            result = {"list": []}
            self._detail_cache.set(vod_id, result)
            return result

        lst = data.get("list", [])
        if not lst:
            result = {"list": []}
            self._detail_cache.set(vod_id, result)
            return result

        d = lst[0]
        play_from_raw = d.get("vod_play_from", "") or ""
        play_url_raw = d.get("vod_play_url", "") or ""

        play_from, play_url, line_keys = self._parse_play(play_from_raw, play_url_raw)

        if not play_url:
            result = {"list": []}
            self._detail_cache.set(vod_id, result)
            return result

        # 详情内容
        content = self._strip_tags(d.get("vod_content", ""))[:500]

        vod = {
            "vod_id": vod_id,
            "vod_name": d.get("vod_name", ""),
            "vod_pic": d.get("vod_pic", "") or "",
            "type_name": d.get("type_name", ""),
            "vod_year": d.get("vod_year", ""),
            "vod_area": d.get("vod_area", ""),
            "vod_remarks": d.get("vod_remarks", "") or "HD",
            "vod_actor": d.get("vod_actor", ""),
            "vod_director": d.get("vod_director", ""),
            "vod_content": content,
            "vod_play_from": "$$$".join(play_from) if play_from else "囧次元动漫",
            "vod_play_url": "$$$".join(play_url) if play_url else "",
        }
        # 保存线路key映射（供 playerContent 使用）
        self._line_keys = line_keys
        result = {"list": [vod]}
        self._detail_cache.set(vod_id, result)
        return result

    # ============================================================
    # 搜索
    # ============================================================

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            params = {
                "wd": key,
                "pg": str(page),
            }
            url = API + "?" + urlencode(params)
            data = self._get_json(url, timeout=10)

            if data and data.get("code") == 1:
                vods = [self._card(v) for v in data.get("list", [])]
                if vods:
                    return {"list": vods}

            return {"list": []}
        except Exception:
            return {"list": []}

    # ============================================================
    # 播放解析（增强版：直链秒开 + 加密源解析配置）
    # ============================================================

    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "playUrl": "", "url": ""}

        play_url = str(id).replace("\\/", "/")

        # 1. 直链媒体（m3u8/mp4）→ 直接播放，附带完整 header
        if self._is_direct_media(play_url):
            is_m3u8 = ".m3u8" in play_url.lower()
            media_referer = self._extract_referer(play_url)
            return {
                "parse": 0,
                "playUrl": "",
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": media_referer,
                    "Accept": "*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Origin": media_referer.rstrip("/"),
                },
                "format": "application/x-mpegURL" if is_m3u8 else "",
                "contentType": "application/x-mpegURL" if is_m3u8 else "",
            }

        # 2. 加密源（NBY/Ace/YYNB/yydm 等）→ 通过 bfq.lggys.com 本地解密
        #    解密成功得到真实 m3u8/mp4 直链，parse=0 直接播放
        #    解密失败则 parse=1 交由壳子解析兜底
        if self._is_encrypted_route_url(play_url):
            ok, direct_url = self._resolve_encrypted_direct(play_url)
            if ok and direct_url and direct_url.startswith("http"):
                is_m3u8 = ".m3u8" in direct_url.lower()
                media_referer = self._extract_referer(direct_url)
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": direct_url,
                    "header": {
                        "User-Agent": UA,
                        "Referer": media_referer,
                        "Accept": "*/*",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    },
                    "format": "application/x-mpegURL" if is_m3u8 else "",
                    "contentType": "application/x-mpegURL" if is_m3u8 else "",
                }
            # 本地解密失败 → 退化到 parse=1 公共解析
            parse_url = PARSE_URLS[0] + quote(play_url, safe="")
            return {
                "parse": 1,
                "playUrl": "",
                "url": parse_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": HOST + "/",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            }

        # 3. 其他情况 → 直接交由播放器
        return {
            "parse": 0,
            "playUrl": "",
            "url": play_url,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        }

    # ===== 加密源本地解密 =====
    def _is_encrypted_route_url(self, play_url):
        """判断是否为加密线路的播放串（非 http 开头，且匹配已知加密前缀）"""
        if not play_url or play_url.startswith("http"):
            return False
        if play_url.startswith("NBY") or "XMYAES" in play_url:
            return True
        for prefix in _ENCRYPTED_ROUTE_PREFIXES:
            if play_url.startswith(prefix):
                return True
        return False

    def _resolve_encrypted_direct(self, enc_url):
        """
        请求 bfq.lggys.com 官方播放器，解密其 result 变量，
        提取真实播放直链(m3u8 或 mp4)。
        成功返回 (True, direct_url)；失败返回 (False, None)。
        失败后自动重试 2 次。
        """
        for attempt in range(3):
            try:
                parse_url = BFQ_PARSE_URL + quote(enc_url, safe="")
                r = self._session.get(
                    parse_url,
                    headers={
                        "User-Agent": UA,
                        "Referer": HOST + "/",
                        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    },
                    timeout=20,
                    verify=False,
                )
                if r.status_code == 200 and r.text:
                    m = re.search(r'result\s*=\s*"([^"]+)"', r.text)
                    if m:
                        direct_url = self._decrypt_bfq_result(m.group(1))
                        if direct_url and direct_url.startswith("http"):
                            return True, direct_url
            except Exception:
                pass
            if attempt < 2:
                time.sleep(0.6)
        return False, None

    def _decrypt_bfq_result(self, result_str):
        """
        解密 bfq.lggys.com 播放器 result 变量，提取真实播放地址。

        result 结构:
          - 前段: AES-128-CBC 密文的 base64 编码
          - 末尾 32 字符: Key 材料(取前 16 字符的 UTF-8 字节作为 AES Key)
          - IV: 16 字节零
        解密后的明文为播放器配置 JSON，其中 "url" 字段即真实播放地址。
        """
        if AES is None:
            return None
        try:
            if len(result_str) < 100:
                return None
            key_str = result_str[-32:]
            enc_b64 = result_str[:-32]
            enc_bytes = base64.b64decode(enc_b64)
            # 对齐到 16 字节边界
            if len(enc_bytes) % 16 != 0:
                enc_bytes = enc_bytes[: len(enc_bytes) - (len(enc_bytes) % 16)]
            if not enc_bytes:
                return None
            key = key_str[:16].encode("utf-8")
            cipher = AES.new(key, AES.MODE_CBC, b"\x00" * 16)
            plain = cipher.decrypt(enc_bytes)
            # PKCS7 去填充
            pad = plain[-1]
            if 1 <= pad <= 16:
                plain = plain[:-pad]
            text = plain.decode("utf-8", errors="ignore")
            # 优先找 "url" 字段
            m = re.search(r'"url"\s*:\s*"([^"]+)"', text)
            if m:
                return m.group(1)
            # 兜底: 直接搜索 http 链接
            m2 = re.search(r'(https?://[^\s"\'<>]+)', text)
            if m2:
                return m2.group(1)
            return None
        except Exception:
            return None

    # ===== 本地代理 =====
    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    # ===== 清理 =====
    def destroy(self):
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass

    def close(self):
        self.destroy()
