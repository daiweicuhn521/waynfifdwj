# -*- coding: utf-8 -*-
"""
懂片帝 AI（https://dongpian17.com/）—— FongMi/TV Python 点播源

全部接口来自站点前端 bundle 与服务端返回，逐条实测，无推测、无兜底：

  /v1/runtime/bootstrap     公开，返回 catalog_ui（频道 + 各类型筛选选项）
  /v1/feed/home             首页，sections[].cards，且每个 section 自带 browse.params
  /v1/browse/catalog        分类 / 筛选 / 搜索 / 分页（page、limit、total 精确）
  /v1/catalog/{id}          详情，含 episodes[] 与 episode_pagination
  /v1/catalog/{id}/episodes 分集翻页（limit + offset，page 参数被服务端忽略）
  /v1/playback/resolve/{t}  按分集 token 取线路，line_options[] 含直链与官方线路
  /v1/users/anonymous       建匿名播放会话（201 + Set-Cookie，guest 50 万词元/日）
  /v1/users/password/login  账号登录（201 + Set-Cookie，member 100 万词元/日）
  /v1/playback/resolve-line 官方线路二次解析（POST ticket + 会话 Cookie -> 真实地址）

签名（前端 movie-card-runtime-*.js 的 Aa/Ta/Ca，已核对并实测 200）：
  msg   = METHOD + "\\n" + pathname+search + "\\n" + ts(ms) + "\\n" + nonce(16B hex)
  sig   = HMAC-SHA256(key, msg).hexdigest()
  heads = x-ai-movie-timestamp / x-ai-movie-nonce / x-ai-movie-signature

只用标准库 hmac/hashlib/secrets/time/uuid/re/urllib + json，网络统一走 self.net：
  - 站点全是 JSON 接口，不需要 lxml / bs4 / pyquery
  - 签名是标准 HMAC-SHA256，不需要 cryptography / pycryptodome / js.eval
  - 线路按集解析：详情只解析首集拿线路清单，播放值放稳定自定义 ID，
    playerContent 再按 token 现取；100 集短剧也不会在详情页发 100 次请求
  - 现取结果走 net.cached 短 TTL 缓存，来回切集不重复请求、不重复扣配额

关于「最重要的官方线路」（本版补齐的部分）：
  line_options 里 url_kind="resolve_ticket" / resolve_required=true /
  url="resolve://<ticket>" 的线路，preference_weight=999（站点最高优先级），
  标签如「AI4K-专享J」「1080P-官方Z」「1080P-专享U」「海外-官方C」。
  上一版因其无 Cookie 时 resolve-line 返回 401 而整体弃用，只留了免登录直链，
  这是错的。实测：

    * 不带任何 Cookie -> 401 playback_user_session_required
    * 带 ai_movie_session Cookie -> 201，line.url 是真实播放地址

  会话从站点自己的接口取得，无需注册、无需验证码、无需 OCR：
    POST /v1/users/anonymous
    body {"anonymous_id": "web_<uuid4>"}
    -> 201 + Set-Cookie: ai_movie_session=ums2_...（Path=/，一年有效）
  实测注册 + 登录链路同样可用（/v1/users/password/login，member 配额翻倍），
  线路清单与匿名态完全一致；因此源默认自动建匿名会话（每台设备独立配额、
  零配置），另支持在 ext 里填自己的账号密码走登录以提升每日配额。
  绝不把共享账号硬编码进源：配额会被所有用户一天耗尽，且凭据必然泄露。

  官方线路不是每部片都有（电影常见、部分剧集有、短剧基本没有）；
  有就列，没有就不列，不补空、不猜测。各集 ticket 不同，但
  (provider_id, play_from) 跨集稳定，故线路按该键对齐。
  resolve-line 解出的 url_kind 实测有 m3u8 与 mp4 两种：
    - m3u8 -> format=application/x-mpegURL（指南 §2.6.2，大写 URL）
    - mp4  -> 不写 format，让 App 按内容/后缀推断（写错会整站 Container Unsupported）
  解出的地址实测裸 UA 直连 200（m3u8 主清单无 KEY/MAP；mp4 返回 video/mp4），
  故 playerContent 只需给 UA，不需要带 Cookie。
  verify= 参数带时效，所以解出的地址不写进详情播放串，播放时现取并短 TTL 缓存。
"""

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from urllib.parse import quote, urlencode

from base.spider import Spider as BaseSpider

SITE = "https://dongpian17.com"

# 前端 movie-card-runtime-*.js 中 Bo 常量的值，客户端 HMAC 密钥
SIGN_KEY = "8b9a908a05eac640e1ee06f52acaa741bfe4ba9e004eeffdbeb635e532e06666"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

PAGE_SIZE = 20         # 列表页大小，与 browse 返回的 pagination.limit 一致
EPISODE_PAGE = 48      # /episodes 单次上限
RESOLVE_TTL = 300000   # 单集线路清单 / 官方线路解析结果缓存（毫秒，短 TTL）
SESSION_TTL = 1200000  # 播放会话缓存（毫秒，远小于 cookie 一年有效期）

COOKIE_NAME = "ai_movie_session"
# 会话 Set-Cookie 是多值：4 个 Max-Age=0 清除指令 + 1 个真值。
# 真值形如 ums2_<base64>.<base64>.<sig>，长度 280；空值长度不足 20，自动跳过。
COOKIE_RE = re.compile(r"ai_movie_session=([A-Za-z0-9_.\-]{20,})")


class Spider(BaseSpider):

    # ---------------------------------------------------------------- 生命周期

    def init(self, extend=""):
        # 实例可能被缓存复用，每次 init 重置站点相关状态
        options = json.loads(extend) if isinstance(extend, str) and extend.strip() else {}
        if not isinstance(options, dict):
            raise ValueError("ext 需为 JSON 对象字符串")
        self.site = str(options.get("site") or SITE).rstrip("/")
        # 可选：用户自己注册的账号，走登录态（member，配额翻倍）。
        # 不填则用匿名会话，二者线路完全一致。
        self.account = str(options.get("account") or "").strip()
        self.password = str(options.get("password") or "").strip()

    # ------------------------------------------------------------------ 网络层

    def _opts(self, path, method="GET", cookie=None):
        """生成一次请求的三件套签名头。path 必须与最终 URL 的 path+query 完全一致。"""
        ts = str(int(time.time() * 1000))
        nonce = secrets.token_hex(16)
        message = "\n".join((method, path, ts, nonce))
        sig = hmac.new(SIGN_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()
        headers = {
            "Accept": "application/json",
            "Referer": self.site + "/",
            "Origin": self.site,
            "x-ai-movie-timestamp": ts,
            "x-ai-movie-nonce": nonce,
            "x-ai-movie-signature": sig,
        }
        if cookie:
            headers["Cookie"] = COOKIE_NAME + "=" + cookie
        return {
            "headers": headers,
            "timeout": 15000,
            "callTimeout": 20000,
        }

    def _get(self, path):
        # net.json：网络失败 / 非 2xx / 非法 JSON 直接抛异常，不做静默降级
        return self.net.json(self.site + path, self._opts(path))

    def _post(self, path, body, cookie=None):
        """带签名的 JSON POST。用 net.req 以便读取响应头里的 Set-Cookie。"""
        opts = self._opts(path, "POST", cookie)
        opts["headers"]["Content-Type"] = "application/json"
        opts["method"] = "POST"
        opts["body"] = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        resp = self.net.req(self.site + path, opts)
        if resp.get("error"):
            raise RuntimeError("请求失败 %s: %s" % (path, resp["error"]))
        if not 200 <= resp.get("code", 0) < 300:
            raise RuntimeError("请求失败 %s: HTTP %s %s" %
                               (path, resp.get("code"), str(resp.get("content"))[:200]))
        return resp

    def _post_json(self, path, body, cookie=None):
        return json.loads(self._post(path, body, cookie)["content"])

    def _ui(self):
        # bootstrap 自带 cache_ttl_seconds=300，这里按站点的 TTL 做短缓存
        return self.net.cached(
            "dpd.bootstrap",
            {"ttl": 300000, "stale": False, "persist": False},
            lambda: self._get("/v1/runtime/bootstrap")["catalog_ui"],
        )

    # ------------------------------------------------------------ 播放会话

    @staticmethod
    def _pick_cookie(headers):
        """从 net.req 的 headers 里取真正的 ai_movie_session 值。

        headers 可能是 dict / 合并字符串 / list（Java 侧形态），统一序列化后
        用正则取最长的匹配，跳过 Max-Age=0 的空值清除指令。
        """
        text = headers if isinstance(headers, str) else json.dumps(
            headers or {}, ensure_ascii=False)
        found = COOKIE_RE.findall(text)
        if not found:
            raise RuntimeError("建立播放会话失败：响应未返回 ai_movie_session")
        return max(found, key=len)

    def _new_session(self):
        if self.account or self.password:
            if not (self.account and self.password):
                raise ValueError("登录需同时提供 account 与 password")
            path = "/v1/users/password/login"
            body = {"account": self.account, "password": self.password}
        else:
            path = "/v1/users/anonymous"
            body = {"anonymous_id": "web_" + str(uuid.uuid4())}
        return self._pick_cookie(self._post(path, body)["headers"])

    def _session(self):
        """惰性建会话并缓存。同一配置一个 key，避免每台设备反复注册匿名账号。"""
        key = "dpd.session." + hashlib.md5(
            (self.site + "|" + self.account).encode()).hexdigest()
        return self.net.cached(
            key, {"ttl": SESSION_TTL, "stale": False, "persist": False},
            self._new_session,
        )

    # ------------------------------------------------------------------ 首页

    def homeContent(self, filter):
        ui = self._ui()
        classes = [{"type_id": c["key"], "type_name": c["label"]}
                   for c in ui["channels"]]
        result = {"class": classes}
        if filter:
            result["filters"] = self._filters(ui)
        return result

    def _filters(self, ui):
        """把 bootstrap 的 rows/options 原样映射成 FongMi 筛选。

        option.params 直接 urlencode 成 v（如 year_gte=1990&year_lte=1999），
        categoryContent 里作为已编码的 query 片段拼回，保持站点参数名不变。
        params 为空的 row（short_drama 的 status / orientation）没有可映射的
        请求参数，不生成，避免臆造。
        """
        out = {}
        for cat in ui["catalogs"]:
            rows = []
            for row in cat["rows"]:
                values = [{"n": row["all_label"], "v": ""}]
                for option in row["options"]:
                    params = option.get("params") or {}
                    if not params:
                        continue
                    values.append({"n": option["label"], "v": urlencode(params)})
                if len(values) > 1:
                    rows.append({"key": row["key"], "name": row["label"],
                                 "init": "", "value": values})
            out[cat["kind"]] = rows
        return out

    def homeVideoContent(self):
        data = self._get("/v1/feed/home")
        cards = {}
        for section in data["sections"]:
            for card in section.get("cards", []):
                # 有序去重：同一部片可能出现在多个板块
                if card.get("id") and card["id"] not in cards:
                    cards[card["id"]] = self._card(card)
        return {"list": list(cards.values())}

    # -------------------------------------------------------------- 分类/搜索

    def _browse_path(self, tid, pg, extend):
        ui = self._ui()
        allowed = {row["key"] for cat in ui["catalogs"] for row in cat["rows"]}

        if tid == "recommend":
            # 来自 /v1/feed/home 首个 section 的 browse.params
            base = [("sort", "trending"), ("window", "day")]
        elif tid == "updates":
            base = [("intent", "latest_catalog")]
        else:
            base = [("kind", tid)]

        base += [("page", str(pg)), ("limit", str(PAGE_SIZE))]
        query = urlencode(base)

        extras = [v for k, v in (extend or {}).items()
                  if k in allowed and isinstance(v, str) and v]
        if extras:
            query += "&" + "&".join(extras)
        return "/v1/browse/catalog?" + query

    def categoryContent(self, tid, pg, filter, extend):
        data = self._get(self._browse_path(tid, pg, extend))
        items = [self._card(c) for c in data["cards"]]
        # 站点已分页：传入精确 total，page() 只算 pagecount、不再切片
        return self.page(items, pg, PAGE_SIZE, data["pagination"]["total"])

    def searchContent(self, key, quick, pg="1"):
        path = "/v1/browse/catalog?" + urlencode(
            {"q": key, "page": str(pg), "limit": str(PAGE_SIZE)})
        data = self._get(path)
        items = [self._card(c) for c in data["cards"]]
        return self.page(items, pg, PAGE_SIZE, data["pagination"]["total"])

    def _card(self, c):
        return {
            "vod_id": c["id"],
            "vod_name": c.get("title", ""),
            "vod_pic": c.get("poster_url", ""),
            "vod_remarks": c.get("remarks", ""),
            "vod_year": str(c.get("year") or ""),
        }

    @staticmethod
    def _safe(name):
        # 集数名称 / 线路名里的 $ 与 # 必须转义，否则播放串会被切断
        return str(name).replace("$", "＄").replace("#", "＃").strip()

    # ------------------------------------------------------------------ 详情

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        return {"list": [self._detail(str(i)) for i in ids]}

    def _detail(self, vid):
        key = quote(vid, safe="")
        d = self._get("/v1/catalog/" + key)

        episodes = list(d.get("episodes") or [])
        page = d.get("episode_pagination") or {}
        # 服务端按 offset 翻页；只有 has_more 为真时才追加请求
        while page.get("has_more") and episodes:
            path = "/v1/catalog/%s/episodes?%s" % (
                key, urlencode({"limit": EPISODE_PAGE, "offset": len(episodes)}))
            more = self._get(path)
            episodes.extend(more.get("episodes") or [])
            page = more.get("episode_pagination") or {}

        flags, urls = self._lines(episodes)

        item = self._card(d)
        item.update({
            "type_name": "、".join(d.get("genres") or []),
            "vod_year": str(d.get("year") or ""),
            "vod_area": d.get("area") or "",
            "vod_language": d.get("language") or "",
            "vod_director": "、".join(d.get("directors") or []),
            "vod_actor": "、".join(d.get("actors") or []),
            "vod_content": d.get("description") or "",
            "vod_play_from": flags,
            "vod_play_url": urls,
        })
        return item

    def _resolve(self, token):
        """按分集 token 取线路；短 TTL 缓存，来回切集不重复请求。"""
        path = "/v1/playback/resolve/" + quote(token, safe="")
        return self.net.cached(
            "dpd.resolve." + token,
            {"ttl": RESOLVE_TTL, "stale": False, "persist": False},
            lambda: self._get(path),
        )

    @staticmethod
    def _playable(line):
        """站点给的两类可播线路，其余一律不收（不补空、不猜测）。

        直链：url_kind=m3u8、resolve_required=false、真实 http 地址。
        官方：url_kind=resolve_ticket、resolve_required=true、url=resolve://<ticket>。
        """
        url = str(line.get("url") or "")
        if line.get("resolve_required"):
            return url.startswith("resolve://") or bool(line.get("resolve_ticket"))
        return (line.get("url_kind") == "m3u8"
                and not line.get("resolve_required")
                and url.startswith("http"))

    @classmethod
    def _sorted_lines(cls, data):
        """按站点自己的 preference_weight 降序；官方线路 999 自然排第一。"""
        lines = [x for x in data.get("line_options", []) if cls._playable(x)]
        return sorted(lines,
                      key=lambda x: (-(x.get("preference_weight") or 0),
                                     x.get("play_from") or "",
                                     x.get("provider_id") or ""))

    @staticmethod
    def _line_key(line):
        return "%s|%s" % (line["provider_id"], line["play_from"])

    def _lines(self, episodes):
        """详情：只解析首集拿线路清单，播放值放稳定自定义 ID（指南 §1.3）。"""
        if not episodes:
            return "", ""
        first = self._resolve(episodes[0]["token"])
        lines = self._sorted_lines(first)

        flags, urls = [], []
        for line in lines:
            key = self._line_key(line)
            parts = []
            for ep in episodes:
                name = (ep.get("title") or ep.get("key")
                        or ("第%s集" % ep.get("number", "")))
                # token|provider_id|play_from —— 不含真实地址，永不过期
                parts.append("%s$%s|%s" % (self._safe(name), ep["token"], key))
            flags.append(self._safe(line.get("display_label")
                                    or line.get("label") or line["play_from"]))
            urls.append("#".join(parts))
        return "$$$".join(flags), "$$$".join(urls)

    # ------------------------------------------------------------------ 播放

    @staticmethod
    def _ticket(line):
        """取官方线路的 ticket，与前端 Xe() 一致：优先 resolve_ticket 字段。"""
        t = str(line.get("resolve_ticket") or "").strip()
        if t:
            return t
        url = str(line.get("url") or "").strip()
        return url[10:].strip() if url.startswith("resolve://") else url

    def _resolve_line(self, ticket):
        """官方线路二次解析：会话 Cookie + POST ticket -> 真实播放地址。

        结果短 TTL 缓存：同一影片只计一次词元，且 verify= 地址带时效。
        """
        key = "dpd.line." + hashlib.md5(ticket.encode()).hexdigest()
        path = "/v1/playback/resolve-line?view=compact"

        def load():
            data = self._post_json(path, {"ticket": ticket}, self._session())
            line = data.get("line") or {}
            url = str(line.get("url") or "")
            if not url.startswith("http"):
                raise RuntimeError("官方线路未返回播放地址：%s" %
                                   str(data.get("message") or data)[:200])
            return {"url": url, "url_kind": line.get("url_kind") or ""}

        return self.net.cached(
            key, {"ttl": RESOLVE_TTL, "stale": False, "persist": False}, load)

    def playerContent(self, flag, id, vipFlags):
        token, provider_id, play_from = id.split("|", 2)
        hit = None
        for line in self._sorted_lines(self._resolve(token)):
            if (line.get("provider_id") == provider_id
                    and line.get("play_from") == play_from):
                hit = line
                break
        # 该集没有这条线路：明确报错，不静默换线、不臆造地址
        if hit is None:
            raise RuntimeError("该集无此线路，请切换播放线路")

        if hit.get("resolve_required"):
            got = self._resolve_line(self._ticket(hit))
            url, kind = got["url"], got["url_kind"]
        else:
            url, kind = hit["url"], hit.get("url_kind") or ""

        result = {
            "parse": 0,
            "url": url,
            "header": json.dumps({"User-Agent": UA}),
        }
        # 指南 §2.6.2：format 必须来自播放接口的真实返回，绝不能按后缀猜。
        # 实测 url_kind 有 m3u8 与 mp4；mp4 不写 format，让 App 自行推断。
        if kind == "m3u8":
            result["format"] = "application/x-mpegURL"
        return result
