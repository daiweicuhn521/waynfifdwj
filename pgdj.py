# -*- coding: utf-8 -*-
"""
皮狗DJ站 视频源（PY 版）

兼容内核（三大家族，本次改版即围绕它们的差异）：
  · FongMi 系：OK影视 / FongMi / 影视仓(FongMi分支)      —— Chaquopy + com.github.catvod.Proxy
  · OSC   系：TVBoxOSC / takagen99(Box) / 影视仓(Pyramid) —— Chaquopy + com.undcover.freedom.pyramid
  · 自研内核：dsplayer 等                                  —— Chaquopy + 引擎按源注入 proxyUrl

【各壳关键差异】（改版依据）
  1) 本地代理端口：各系都不固定，不能写死 9978。
     FongMi : Server.start() 从 9978 起找第一个空闲端口 -> Proxy.set(i)；
              正确基址 = com.github.catvod.Proxy.getUrl(true) = http://127.0.0.1:{port}/proxy
     OSC系  : PythonLoader.getPort() 同样从 9978 起探测；
              正确基址 = PythonLoader.getInstance().localProxyUrl() = http://127.0.0.1:{port}/proxy
     dsplayer: 端口由引擎动态分配；引擎把地址按源注入（存 Spider.t4_api，
              同时挂到 PyUtil 桩 getProxy()），形如
              http://127.0.0.1:{port}/proxy?<路由参数>，**带 query**。
  2) /proxy 路由（决定图片能不能显示）：
     FongMi : 有 siteKey -> 该站点；do=js -> js加载器；do=py -> py源的 localProxy ★；
              其余(如 do=pic) -> jar加载器，图片必然 404  —— 这就是“OK影视没图”的根因。
     OSC系  : 只要带 do 参数就一定进 py 源的 localProxy（do 取值无所谓）。
     dsplayer: 代理地址由引擎按源注入，路由参数已在其 query 里；源只需在
              query 后追加 type/b64 即可，**不能再补一个 ?do=py**（会拼成坏链）。
     => vod_pic 统一按「基址是否已带 query」选择 ? / & 分隔符，三系通吃。
  3) localProxy 返回值：各系一致，均为 [code, mime, bytes/str, header?, base64?]。
  4) 站点调用预算：FongMi 单次 30s（homeContent 与 homeVideoContent 属同一次调用）；
     OSC Future.get(20s)。任何一步都必须收敛超时、能并行就并行。
"""

import re
import json
import time
import gzip
import base64
import html as html_lib
import threading
import urllib.parse
import urllib.request

try:
    from concurrent.futures import ThreadPoolExecutor
except Exception:
    ThreadPoolExecutor = None

try:
    import requests as _requests
    _HAS_REQUESTS = True
except Exception:
    _requests = None
    _HAS_REQUESTS = False

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass


# ======================================================================
# 常量
# ======================================================================
UA_DEFAULT = ("Mozilla/5.0 (Linux; Android 10; MIX 2) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Mobile Safari/537.36")

# 取图方式：
#   "direct" 默认。把 <url>@Referer=...@User-Agent=... 直接交给宿主图片库加载，
#            由壳自己带着防盗链请求头去取图，**不经过 127.0.0.1 本地代理**。
#            FongMi 系 ImgUtil 会解析 @Referer；takagen99 这类壳的 Python 源
#            本地代理链路与 FongMi 不同、默认不保证开放，直连可绕开该差异。
#   "proxy"  走壳的本地代理（?do=py&type=pic&b64=...）。仅在个别既不解析
#            @Referer、本地代理又确实可用的壳上才需要，改这一行即可切回。
PIC_MODE = "direct"

T_LIST = 10      # 列表页 / 详情页
T_AJAX = 8       # 取播放地址接口
T_PROBE = 4      # 播放地址候选 URL 探测
T_PIC = 10       # 图片

PAGES_PER_REQUEST = 3
HTML_CACHE_TTL = 45          # 列表页短缓存（秒），反复进出分类不再重复请求

# 图片内存缓存（LRU）
_PIC_CACHE = {}
_PIC_ORDER = []
_PIC_BYTES = [0]
_PIC_LOCK = threading.Lock()
_PIC_MAX_ITEMS = 256
_PIC_MAX_BYTES = 48 * 1024 * 1024

_SESSION = None
_SESSION_LOCK = threading.Lock()

_PROXY_RE = re.compile(r'^https?://127\.0\.0\.1:\d+/proxy$')


def _log(*args):
    try:
        print("[pgdj]", *args)
    except Exception:
        pass


# ======================================================================
# HTTP
# ======================================================================
def _session():
    """全局复用 requests.Session：连接池复用 TCP/TLS，页面与图片抓取都受益。"""
    global _SESSION
    if not _HAS_REQUESTS:
        return None
    if _SESSION is not None:
        return _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            try:
                s = _requests.Session()
                s.trust_env = False
                try:
                    from requests.adapters import HTTPAdapter
                    ad = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=1)
                    s.mount("http://", ad)
                    s.mount("https://", ad)
                except Exception:
                    pass
                _SESSION = s
            except Exception:
                _SESSION = None
    return _SESSION


def _decode(raw):
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _get(url, headers, timeout, binary=False):
    """GET。优先 requests（连接池）；不可用时退回 urllib。
       binary=True  -> (bytes, content_type) 或 None
       binary=False -> str 或 None
    """
    s = _session()
    if s is not None:
        r = s.get(url, headers=headers, timeout=timeout)
        ctype = r.headers.get("Content-Type", "")
        if binary:
            return (r.content, ctype)
        return _decode(r.content)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        enc = (resp.headers.get("Content-Encoding", "") or "").lower()
    if "gzip" in enc:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    if binary:
        return (raw, ctype)
    return _decode(raw)


# ======================================================================
# 图片缓存
# ======================================================================
def _pic_cache_get(key):
    with _PIC_LOCK:
        v = _PIC_CACHE.get(key)
        if v is None:
            return None
        try:
            _PIC_ORDER.remove(key)
        except ValueError:
            pass
        _PIC_ORDER.append(key)
        return v


def _pic_cache_put(key, mime, data):
    n = len(data or b"")
    if n <= 0 or n > 4 * 1024 * 1024:
        return
    with _PIC_LOCK:
        old = _PIC_CACHE.get(key)
        if old:
            _PIC_BYTES[0] -= len(old[1])
            try:
                _PIC_ORDER.remove(key)
            except ValueError:
                pass
        _PIC_CACHE[key] = (mime, data)
        _PIC_ORDER.append(key)
        _PIC_BYTES[0] += n
        while _PIC_ORDER and (len(_PIC_ORDER) > _PIC_MAX_ITEMS or _PIC_BYTES[0] > _PIC_MAX_BYTES):
            k = _PIC_ORDER.pop(0)
            v = _PIC_CACHE.pop(k, None)
            if v:
                _PIC_BYTES[0] -= len(v[1])


# ======================================================================
# 壳探测
# ======================================================================
def _valid_proxy_base(b):
    return isinstance(b, str) and _PROXY_RE.match(b.strip().rstrip('/')) is not None


def _t3_getproxy():
    """读自研内核（dsplayer 等）经 PyUtil 桩注入的代理地址。

    dsplayer 引擎在装载源之前会把 com.github.tvbox.osc.util 预注册进
    sys.modules（T3 兼容桩），其中 PyUtil.getProxy(flag) 返回**本次调用**
    注入的 proxyUrl；取不到时返回 ""。这是除 t4_api 之外的第二条取址通道，
    两者取到的是同一个值，互为兜底。
    """
    try:
        from com.github.tvbox.osc.util import PyUtil
        try:
            v = PyUtil.getProxy(True)
        except Exception:
            v = PyUtil.getProxy()
        return v or ""
    except Exception:
        return ""


def _normalize_injected_proxy(raw):
    """把内核注入的 proxyUrl 规范成可用基址，不可用返回 ""。

    关键差异：FongMi / OSC 的探测接口返回的是**纯净**基址
    （http://127.0.0.1:{port}/proxy）；而 dsplayer 这类自研内核按源
    注入代理地址，其值**带 query**（引擎还会在其后追加 `&extend=`，
    可见形如 `http://127.0.0.1:{port}/proxy?do=py`），且路径名未必
    叫 /proxy。因此这里只要求「http(s) + 本地回环 + 显式端口」即认定
    为内核代理，path 与 query 原样保留 —— query 承载内核的源路由参数
    （决定请求派给哪个源的 localProxy），绝不能丢，也绝不能再插一个 ?。
    """
    if not raw:
        return ""
    try:
        s = str(raw).strip()
        if not s:
            return ""
        sp = urllib.parse.urlsplit(s)
        if sp.scheme not in ("http", "https"):
            return ""
        if (sp.hostname or "").lower() not in ("127.0.0.1", "localhost", "::1"):
            return ""
        try:
            if not sp.port:
                return ""
        except Exception:
            return ""
        base = "{}://{}{}".format(sp.scheme, sp.netloc, sp.path or "").rstrip("/")
        if sp.query:
            base += "?" + sp.query
        return base
    except Exception:
        return ""


def _detect_proxy_base(t4_api=""):
    """返回 (本地代理基址, 壳标识)。各壳端口都不固定，必须运行时探测。"""
    # 1) FongMi / OK影视 / 影视仓(FongMi分支)
    try:
        from com.github.catvod import Proxy as _P
        b = _P.getUrl(True)
        if _valid_proxy_base(b):
            return b.strip().rstrip('/'), "fongmi"
    except Exception:
        pass
    # 1b) FongMi 备用入口
    try:
        from java import jclass
        b = jclass("com.fongmi.android.tv.server.Server").get().getAddress("/proxy")
        if _valid_proxy_base(b):
            return b.strip().rstrip('/'), "fongmi"
    except Exception:
        pass
    # 2) OSC / takagen99 / 影视仓(Pyramid)
    try:
        from java import jclass
        inst = jclass("com.undcover.freedom.pyramid.PythonLoader").getInstance()
        b = inst.localProxyUrl()
        if _valid_proxy_base(b):
            return b.strip().rstrip('/'), "osc"
    except Exception:
        pass
    # 3) 自研内核（dsplayer 等）：引擎按源注入的 proxyUrl。
    #    放在三条原生探测之后 —— FongMi / OSC 走自己的通道（行为不变、零回归），
    #    只有它们都探不到时（dsplayer 环境无上述 Java 类）才用注入地址兜底；
    #    注入地址必为「本机 py 源代理」，比写死 9978 可靠得多。
    for _cand in (t4_api, _t3_getproxy()):
        _b = _normalize_injected_proxy(_cand)
        if _b:
            return _b, "dsplayer"
    # 4) 兜底：端口不固定，9978 只是最后手段（大概率取不到图）。
    #    shell 标为 "fallback"，供 _pic_url 判定「本地代理不可用 → 改用直连」。
    return "http://127.0.0.1:9978/proxy", "fallback"


def _fix_pic_url(u):
    """源站图片可能带 //video/ 、//rand/ 这类重复斜杠，统一修掉。"""
    u = (u or "").strip().replace("&amp;", "&")
    u = u.replace("//video/", "/video/").replace("//rand/", "/rand/")
    return u


# ======================================================================
# 站点
# ======================================================================
class Spider(BaseSpider):

    HOST = "https://www.pgdjz.com"
    CDN = "https://st.pgdjz.fun"
    PATH_PREFIX = "zwmtv"

    PAGES_PER_REQUEST = PAGES_PER_REQUEST

    # 类级默认值：任何时刻（哪怕 init 还没执行到赋值）访问都不报 AttributeError。
    # 默认按「本地代理不可用」处理，图片走直连，宁可直连也不裂图。
    _shell = "fallback"
    _pic_base = ""

    def getName(self):
        return "皮狗DJ视频"

    def init(self, extend=""):
        self.host = self.HOST
        self.ua = UA_DEFAULT
        self.categories = [
            {"type_id": "lists/12",   "type_name": "超清MV"},
            {"type_id": "lists/123",  "type_name": "车载MV"},
            {"type_id": "lists/112",  "type_name": "跳舞MV"},
            {"type_id": "lists/158",  "type_name": "国内夜店"},
            {"type_id": "lists/90",   "type_name": "派对MV"},
            {"type_id": "lists/125",  "type_name": "发烧MV"},
            {"type_id": "lists/21",   "type_name": "国外夜店"},
            {"type_id": "lists/20",   "type_name": "抒情MV"},
        ]
        self._url_cache = {}          # vod_id -> {"title","year","pic","play_url"}
        self._html_cache = {}         # url -> (ts, text)
        self._pic_base, self._shell = _detect_proxy_base(
            getattr(self, "t4_api", "") or "")
        _log("init shell=%s pic_base=%s pic_mode=%s" % (self._shell, self._pic_base, PIC_MODE))
        return

    # ------------------------------------------------------------------
    # HTTP（带短缓存）
    # ------------------------------------------------------------------
    def _http(self, url, binary=False, timeout=None, ttl=0):
        timeout = timeout or T_LIST
        if not binary and ttl:
            hit = self._html_cache.get(url)
            if hit and (time.time() - hit[0]) < ttl:
                return hit[1]
        headers = {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.host + "/",
        }
        if binary:
            return _get(url, headers, timeout, binary=True)
        text = _get(url, headers, timeout, binary=False)
        if ttl and text:
            if len(self._html_cache) > 64:
                self._html_cache.clear()
            self._html_cache[url] = (time.time(), text)
        return text

    # ------------------------------------------------------------------
    # 图片地址：按壳适配
    # ------------------------------------------------------------------
    def _pic_url(self, pic):
        if not pic:
            return ""
        pic = _fix_pic_url(pic)
        if not pic:
            return ""
        if PIC_MODE == "direct" or self._shell == "fallback":
            # 全壳统一走直连：把请求头以 @Referer / @User-Agent 后缀交给宿主图片库，
            # 由壳自己去请求图片，不再经过 127.0.0.1 本地代理。
            # 原实现写作 `PIC_MODE == "direct" and self._shell == "fongmi"`，
            # 于是 takagen99 这类 shell 探测结果不是 fongmi 的壳，即使把
            # PIC_MODE 改成 direct 也仍然走 proxy → 封面照旧一张都不显示。
            return "{}@Referer={}@User-Agent={}".format(pic, self.host + "/", self.ua)
        b64 = base64.urlsafe_b64encode(pic.encode("utf-8")).decode("ascii").rstrip("=")
        # 参数分隔符按基址是否已带 query 决定：
        #   · FongMi / OSC：基址纯净 → 补 "?do=py"。FongMi 靠 do=py 路由到
        #     py 源 localProxy；OSC 系只要带 do 参数即可（取值无所谓）。
        #   · dsplayer 等注入式内核：基址自带路由 query → 用 "&" 追加图片
        #     参数，避免拼出第二个 "?"（那会变成坏链、必然取不到图）。
        if "?" in self._pic_base:
            return "{}&type=pic&b64={}".format(self._pic_base, b64)
        return "{}?do=py&type=pic&b64={}".format(self._pic_base, b64)

    def localProxy(self, param):
        """本地代理取图。各壳都会把 query 参数传进来（通常为 dict）。"""
        try:
            if isinstance(param, str):
                s = param.strip()
                if not s:
                    return None
                try:
                    param = json.loads(s)
                except Exception:
                    # 兜底：内核若以 query string 形式传参（do=py&type=pic&b64=...）
                    try:
                        param = {k: v[0] for k, v in urllib.parse.parse_qs(s).items()}
                    except Exception:
                        return None
            if not isinstance(param, dict):
                return None
            do = str(param.get("do") or "").lower()
            typ = str(param.get("type") or "").lower()
            # 兼容：FongMi 必须 do=py；OSC 只要求带 do；老写法 do=pic 一并保留
            if do not in ("py", "pic", "") and typ not in ("pic", "image"):
                return None

            pic_url = ""
            b64 = str(param.get("b64") or "")
            if b64:
                try:
                    pad = (-len(b64)) % 4
                    pic_url = base64.urlsafe_b64decode((b64 + "=" * pad).encode("ascii")).decode("utf-8")
                except Exception:
                    pic_url = ""
            if not pic_url:
                pic_url = str(param.get("url") or param.get("u") or "")
                if pic_url:
                    try:
                        pic_url = urllib.parse.unquote(pic_url)
                    except Exception:
                        pass
            pic_url = _fix_pic_url(pic_url)
            if not pic_url or not pic_url.lower().startswith("http"):
                return None
            return self._fetch_image(pic_url)
        except Exception:
            return None

    def _fetch_image(self, url):
        hit = _pic_cache_get(url)
        if hit is not None:
            return [200, hit[0], hit[1]]
        headers = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        raw = None
        ctype = "image/jpeg"
        try:
            got = _get(url, headers, T_PIC, binary=True)
            if got is not None:
                raw, ctype = got
        except Exception:
            raw = None
        if not raw:
            return None
        ctype = (ctype or "image/jpeg").split(";")[0].strip() or "image/jpeg"
        _pic_cache_put(url, ctype, raw)
        return [200, ctype, raw]

    # ------------------------------------------------------------------
    # URL 拼接 + 探测
    # ------------------------------------------------------------------
    def _make_url(self, title, year):
        if not title or not year:
            return ""
        safe_title = re.sub(r'[\\/:*?"<>|\r\n\t]+', '', title)
        safe_title = safe_title.replace("\u3000", " ").replace("\xa0", " ").strip()
        raw_path = "/{}/{}/{}.mp4".format(self.PATH_PREFIX, year, safe_title)
        encoded = urllib.parse.quote(raw_path, safe="/")
        return "{}{}".format(self.CDN.rstrip('/'), encoded)

    def _probe_candidates(self, title, year):
        cands = [self._make_url(title, year)]
        t2 = re.sub(r'^[\-\–\—\_\.\s·•]+', '', title).strip()
        if t2 and t2 != title:
            cands.append(self._make_url(t2, year))
        t3 = re.sub(r'\s*[\(（][^\)）]*[\)）]\s*$', '', title).strip()
        if t3 and t3 != title:
            cands.append(self._make_url(t3, year))
        t4 = re.sub(r'^[\-\–\—\_\.\s·•]+', '', t3).strip()
        if t4 and t4 not in (title, t2, t3):
            cands.append(self._make_url(t4, year))
        out = []
        for u in cands:
            if u and u not in out:
                out.append(u)
        return out

    def _head_ok(self, url):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": self.ua,
                "Referer": self.host + "/",
            }, method="HEAD")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=T_PROBE) as resp:
                if resp.status in (200, 206):
                    return url
        except Exception:
            pass
        return ""

    def _probe_url(self, title, year):
        """候选地址并行探测，命中即返回（原来是 4 个串行 HEAD，最坏 32s）。"""
        cands = self._probe_candidates(title, year)
        if not cands:
            return ""
        if len(cands) == 1 or ThreadPoolExecutor is None:
            for u in cands:
                if self._head_ok(u):
                    return u
            return cands[0]
        ex = ThreadPoolExecutor(max_workers=min(4, len(cands)))
        try:
            for u in ex.map(self._head_ok, cands):
                if u:
                    return u
        finally:
            ex.shutdown(wait=True)
        return cands[0]

    # ------------------------------------------------------------------
    # 列表页解析
    # ------------------------------------------------------------------
    def _parse_list(self, html, dedup=False):
        items = []
        seen_ids = set()
        seen_titles = set()

        def _normalize(t):
            x = t
            x = re.sub(r'^\[\w+\]', '', x)
            x = re.sub(r'^\d+P[\-\s]*', '', x)
            x = re.sub(r'^(?:高清|超清|标清|蓝光|推荐)[\-\s]*', '', x)
            x = re.sub(r'^[\-\–\—\_\.\s·•]+', '', x)
            return x.strip()

        def _add_item(vod_id, raw_title, pic):
            if vod_id in seen_ids:
                return
            if not raw_title or len(raw_title) < 3:
                return

            year = ""
            ym = re.search(r'(\d{4})-\d{2}-\d{2}', raw_title)
            if ym:
                year = ym.group(1)
            if not year:
                year = "2026"

            clean_title = raw_title
            clean_title = re.sub(r'^\d+\.?\d*万?', '', clean_title)
            clean_title = re.sub(r'^\d{4}-\d{2}-\d{2}', '', clean_title)
            clean_title = re.sub(r'^[推荐]+', '', clean_title)
            clean_title = re.sub(
                r'^(?:超清|高清|标清|蓝光|1080P|720P)+',
                '', clean_title
            )
            clean_title = re.sub(r'^\[[^\]]{1,6}\]', '', clean_title)
            clean_title = re.sub(r'^[\-\–\—\_\.\s·•]+', '', clean_title)
            clean_title = clean_title.strip()

            if dedup:
                norm = _normalize(clean_title)
                if norm in seen_titles:
                    return
                seen_titles.add(norm)

            seen_ids.add(vod_id)
            self._url_cache[vod_id] = {
                "title": clean_title,
                "year": year,
                "pic": _fix_pic_url(pic),
            }

            items.append({
                "vod_id": vod_id,
                "vod_name": clean_title,
                "vod_pic": self._pic_url(pic),
                "vod_remarks": "",
            })

        # 分类页结构
        for m in re.finditer(
            r'<a\s+href="(https?://[^"]*?/dance/(\d+)\.html)"[^>]*class="[^"]*name[^"]*"[^>]*>(.*?)</a>',
            html, re.S | re.I
        ):
            link, vod_id, inner = m.group(1), m.group(2), m.group(3)
            raw_title = html_lib.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
            raw_title = re.sub(r"\s+", " ", raw_title)
            before = html[max(0, m.start() - 3000):m.start()]
            pic = ""
            pm = re.search(r'<img\s+src="([^"]+?\.(?:jpg|jpeg|png|webp))"', before, re.I)
            if pm:
                pic = pm.group(1)
            _add_item(vod_id, raw_title, pic)

        # 首页结构
        if not items:
            for m in re.finditer(
                r'<a\s+href="(https?://[^"]*?/dance/(\d+)\.html)"[^>]*>(.*?)</a>',
                html, re.S | re.I
            ):
                link, vod_id, inner = m.group(1), m.group(2), m.group(3)
                nm = re.search(r'<div\s+class="name"[^>]*>(.*?)</div>', inner, re.S | re.I)
                if nm:
                    raw_title = html_lib.unescape(re.sub(r"<[^>]+>", "", nm.group(1))).strip()
                else:
                    raw_title = html_lib.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
                raw_title = re.sub(r"\s+", " ", raw_title)
                if not raw_title or len(raw_title) < 3:
                    continue
                after = html[m.end():m.end() + 2000]
                pic = ""
                pm = re.search(r'<img\s+src="([^"]+?\.(?:jpg|jpeg|png|webp))"', inner, re.I)
                if pm:
                    pic = pm.group(1)
                if not pic:
                    pm = re.search(r'<img\s+src="([^"]+?\.(?:jpg|jpeg|png|webp))"', after, re.I)
                    if pm:
                        pic = pm.group(1)
                _add_item(vod_id, raw_title, pic)

        return items

    # ------------------------------------------------------------------
    # 详情页解析（兜底）
    # ------------------------------------------------------------------
    def _parse_detail(self, html):
        title = ""
        m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
        if m:
            title = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
            title = re.sub(r'^(?:超清|高清|推荐|标清|蓝光|推|荐)+', '', title).strip()

        cover = ""
        m = re.search(
            r'<div\s+class="img"[^>]*>\s*<img\s+src="([^"]+?\.(?:jpg|jpeg|png|webp))"',
            html, re.S | re.I
        )
        if m:
            cover = m.group(1)
        if not cover:
            m = re.search(r'<img\s+src="(https?://tp\.pgdjz\.fun/[^"]+?\.(?:jpg|jpeg|png|webp))"', html, re.I)
            if m:
                cover = m.group(1)
        return title, cover, ""

    # ------------------------------------------------------------------
    # 壳接口
    # ------------------------------------------------------------------
    def homeContent(self, filter):
        return {"class": self.categories, "filters": {}}

    def homeVideoContent(self):
        try:
            html = self._http(self.host + "/video.html", timeout=T_LIST, ttl=HTML_CACHE_TTL)
            return {"list": self._parse_list(html, dedup=True)}
        except Exception as e:
            return {"list": [], "msg": str(e)}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1

        per = self.PAGES_PER_REQUEST
        start_page = (pg - 1) * per + 1
        pages = [start_page + i for i in range(per)]

        def _load(p):
            if p <= 1:
                url = "{}/video/{}.html".format(self.host, tid)
            else:
                url = "{}/video/{}/{}.html".format(self.host, tid, p)
            try:
                return p, self._http(url, timeout=T_LIST, ttl=HTML_CACHE_TTL)
            except Exception:
                return p, ""

        page_html = {}
        if ThreadPoolExecutor is not None and len(pages) > 1:
            ex = ThreadPoolExecutor(max_workers=len(pages))
            try:
                for p, h in ex.map(_load, pages):
                    page_html[p] = h or ""
            finally:
                ex.shutdown(wait=True)
        else:
            for p in pages:
                _, h = _load(p)
                page_html[p] = h or ""

        all_items = []
        seen_ids = set()
        total_count = 0
        total_pages = 9999
        page_size = 7

        for p in pages:
            html = page_html.get(p) or ""
            if not html:
                break
            items = self._parse_list(html, dedup=False)
            if not items:
                break
            if p == start_page:
                m_nums = re.search(r'data-nums="(\d+)"', html)
                m_size = re.search(r'data-size="(\d+)"', html)
                if m_nums:
                    total_count = int(m_nums.group(1))
                if m_size:
                    page_size = int(m_size.group(1))
                if total_count > 0 and page_size > 0:
                    total_pages = max(1, (total_count + page_size - 1) // page_size)
            for it in items:
                if it["vod_id"] not in seen_ids:
                    seen_ids.add(it["vod_id"])
                    all_items.append(it)

        return {
            "list": all_items,
            "page": pg,
            "pagecount": total_pages,
            "limit": page_size,
            "total": total_count,
        }

    def searchContent(self, key, quick, pg="1"):
        return {"list": [], "msg": "该站搜索暂未支持"}

    def searchContentPage(self, key, quick, page):
        return {"list": [], "msg": "该站搜索暂未支持"}

    def detailContent(self, array):
        if isinstance(array, (list, tuple)):
            vod_id = array[0] if array else ""
        else:
            vod_id = str(array or "")
        vod_id = str(vod_id).strip()

        cached = self._url_cache.get(vod_id) or {}
        title = cached.get("title", "") or ""
        cover = cached.get("pic", "") or ""
        play_url = cached.get("play_url", "") or ""

        # ① 站点接口取直链（正常路径）
        if not play_url:
            try:
                api_url = "{}/ajax/videoplay?id={}".format(self.host, vod_id)
                resp_text = self._http(api_url, timeout=T_AJAX)
                j = json.loads(resp_text)
                if j.get("code") == 1:
                    play_url = j.get("playurl", "") or ""
                    cover = cover or (j.get("pic", "") or "")
                    play_url = play_url.replace("%2F", "/").replace("%2f", "/")
                    if play_url.startswith("https://"):
                        head = "https://"
                        tail = play_url[8:]
                    elif play_url.startswith("http://"):
                        head = "http://"
                        tail = play_url[7:]
                    else:
                        head = ""
                        tail = play_url
                    tail = re.sub(r'/+', '/', tail)
                    play_url = head + tail
            except Exception:
                play_url = ""

        # ② 接口没拿到 → 按标题猜 CDN 地址并并行探测
        if not play_url and title and cached.get("year"):
            play_url = self._probe_url(title, cached.get("year"))

        # ③ 仍缺标题/封面 → 抓一次详情页补齐（正常路径不会走到）
        if not title or not cover:
            try:
                url = "{}/dance/{}.html".format(self.host, vod_id)
                html = self._http(url, timeout=T_LIST)
                t, c, _ = self._parse_detail(html)
                title = title or t
                cover = cover or c
            except Exception:
                title = title or vod_id

        if title or play_url:
            self._url_cache[vod_id] = {
                "title": title,
                "year": cached.get("year", ""),
                "pic": cover,
                "play_url": play_url,
            }

        if not play_url:
            return {"list": [{
                "vod_id": vod_id,
                "vod_name": title or vod_id,
                "vod_pic": self._pic_url(cover),
                "vod_remarks": "",
                "vod_content": "未获取到播放地址",
            }]}

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": title or vod_id,
            "vod_pic": self._pic_url(cover),
            "vod_remarks": "",
            "vod_content": title,
            "vod_play_from": "皮狗DJ",
            "vod_play_url": "正片${}".format(play_url),
        }]}

    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()
        if not url:
            return {"parse": 0, "url": "", "header": {}}
        return {
            "parse": 0,
            "url": url,
            "header": {
                "User-Agent": self.ua,
                "Referer": self.host + "/",
                "Origin": self.host,
            },
        }

    # ------------------------------------------------------------------
    # 各壳都会调用的收尾接口（缺一个都可能在某些壳上报错）
    # ------------------------------------------------------------------
    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        pass

    def getDependence(self):
        return []

    def action(self, action):
        return ""

    def liveContent(self, url):
        return ""

    def destroy(self):
        pass
