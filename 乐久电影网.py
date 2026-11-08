# -*- coding: utf-8 -*-
"""
l9dy.py —— 乐久电影网 (https://www.l9dy.com) 命令行工具

功能：
  1. 浏览一级 / 二级分类
  2. 按分类翻页列出影片
  3. 搜索影片
  4. 查看影片详情，列出【所有播放线路(线路/sid) + 每一集】
  5. 直接解析出 m3u8 直链（绕开网站沉重的播放器页面，加载更快）
  6. 生成离线 HTML 播放器 / .m3u 播放列表
  7. 调用本机播放器(mpv/vlc/ffplay) 直接串流，播放更流畅

【为什么更快】
  - 网站原播放页会加载大量 JS/CSS、广告与 iframe；本工具直接从
    /vplay/{id}-{sid}-{nid}/ 页面里的 player_aaaa 变量里抠出 m3u8 直链，
    省掉整页渲染，加载速度提升明显。
  - 使用 requests.Session + 连接池 + 重试，复用 TCP 连接。
  - 多线程(ThreadPoolExecutor) 并发解析多集/多线路的 m3u8。
  - 生成的 HTML 播放器预解析所有线路/集数，切换即播，无广告无等待。

依赖：pip install requests
用法见各子命令：python3 l9dy.py -h
"""

import sys
import os
import re
import json
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    sys.exit("请先安装依赖：pip install requests")

import l9dy_categories as CAT

BASE = "https://www.l9dy.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ------------------------------------------------------------------ 网络层
_session = None


def get_session():
    """带连接池 + 重试的 Session，复用 TCP 连接，提速。"""
    global _session
    if _session is None:
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20, pool_maxsize=20, max_retries=3
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({"User-Agent": UA, "Referer": BASE + "/"})
        _session = s
    return _session


def fetch(url, timeout=15):
    """抓取页面文本，失败返回空串。"""
    try:
        r = get_session().get(url, timeout=timeout)
        r.encoding = "utf-8"
        return r.text
    except Exception as e:
        print(f"[!] 请求失败 {url}: {e}", file=sys.stderr)
        return ""


# ------------------------------------------------------------------ 解析层
RE_ITEM = re.compile(
    r'<a class="stui-vodlist__thumb[^"]*" href="/varticle/(\d+)/"'
    r'[^>]*title="([^"]*)"[^>]*data-original="([^"]*)"[^>]*>'
    r'.*?<span class="pic-text[^"]*">([^<]*)</span>',
    re.S,
)
RE_BLOCK = re.compile(
    r'<h3 class="title"><img[^>]*/>([^<]*)</h3>'
    r'.*?(<ul class="stui-content__playlist[^"]*">.*?</ul>)',
    re.S,
)
RE_EP = re.compile(r'href="/vplay/(\d+)-(\d+)-(\d+)/"[^>]*>([^<]*)</a>')
RE_PLAYER = re.compile(r'player_aaaa\s*=\s*(\{.*?\})\s*</script>', re.S)
RE_URL = re.compile(r'"url":"(https?:\\/\\/[^"\\]+?\.m3u8)"')


def parse_list(html):
    """解析列表页，返回 [(id, name, cover, note), ...]。"""
    out = []
    for mid, name, cover, note in RE_ITEM.findall(html):
        out.append((mid, name.strip(), cover.strip(), note.strip()))
    # 去重（同一影片可能重复出现）
    seen, uniq = set(), []
    for it in out:
        if it[0] not in seen:
            seen.add(it[0])
            uniq.append(it)
    return uniq


def parse_detail(html):
    """解析详情页，返回 (name, info_dict, lines)。

    lines 结构：[{'name': 线路名, 'sid': sid, 'eps': [(nid, ep_name), ...]}, ...]
    """
    name = ""
    m = re.search(r'<h1 class="title">([^<]*)</h1>', html)
    if m:
        name = m.group(1).strip()

    info = {}
    for label, key in [("类型", "type"), ("地区", "area"), ("年份", "year"),
                       ("导演", "director"), ("主演", "actor")]:
        mm = re.search(
            rf'<span class="text-muted[^"]*">\s*{label}\s*：</span>(.*?)'
            r'(?:<span class="split-line"|<span class="text-muted|</p>)',
            html, re.S)
        if mm:
            txt = re.sub(r"<[^>]+>", "", mm.group(1)).replace("&nbsp;", " ").strip()
            info[key] = txt

    lines = []
    for line_name, ul_html in RE_BLOCK.findall(html):
        eps = []
        for _vid, sid, nid, ep in RE_EP.findall(ul_html):
            eps.append((int(nid), ep.strip(), int(sid)))
        if eps:
            sid = eps[0][2]
            lines.append({"name": line_name.strip(), "sid": sid, "eps": eps})
    return name, info, lines


def resolve_m3u8(vid, sid, nid, timeout=15):
    """从 /vplay/{vid}-{sid}-{nid}/ 直接抠出 m3u8 直链。

    返回 (m3u8_url, from_name) 或 (None, None)。
    """
    url = f"{BASE}/vplay/{vid}-{sid}-{nid}/"
    html = fetch(url, timeout=timeout)
    if not html:
        return None, None
    m = RE_PLAYER.search(html)
    if m:
        try:
            data = json.loads(m.group(1))
            u = data.get("url")
            if u:
                return u.replace("\\/", "/"), data.get("from")
        except Exception:
            pass
    # 兜底：直接匹配 url 字段
    m2 = RE_URL.search(html)
    if m2:
        return m2.group(1).replace("\\/", "/"), None
    return None, None


# ------------------------------------------------------------------ 并发解析
def resolve_line(vid, line, workers=8, timeout=15):
    """并发解析某线路下所有集数的 m3u8，返回带 url 的 episodes 列表。"""
    tasks = [(ep[0], ep[2], ep[0]) for ep in line["eps"]]  # (nid, sid, nid)
    results = {}

    def work(nid, sid, _):
        u, frm = resolve_m3u8(vid, sid, nid, timeout)
        return nid, u

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, *t): t[0] for t in tasks}
        for fut in as_completed(futs):
            nid, u = fut.result()
            results[nid] = u
    out = []
    for nid, ep_name, sid in line["eps"]:
        out.append({"nid": nid, "name": ep_name, "sid": sid, "url": results.get(nid)})
    return out


# ------------------------------------------------------------------ 输出/播放
def build_m3u(vid, line, episodes, name):
    """生成 .m3u 播放列表文本。"""
    lines = [f"#EXTM3U", f'#PLAYLIST:{name} - {line["name"]}']
    for ep in episodes:
        if ep["url"]:
            lines.append(f'#EXTINF:-1,{ep["name"]}')
            lines.append(ep["url"])
    return "\n".join(lines) + "\n"


HTML_PLAYER = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - 离线播放器</title>
<script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>
<style>
 body{{margin:0;background:#0b0b0b;color:#eee;font-family:system-ui,sans-serif}}
 header{{padding:10px 14px;background:#161616;border-bottom:1px solid #222}}
 h1{{font-size:16px;margin:0 0 8px}}
 select,button{{background:#222;color:#eee;border:1px solid #333;border-radius:6px;padding:6px 10px;margin-right:6px;font-size:13px}}
 video{{width:100%;height:calc(100vh - 110px);background:#000;display:block}}
 .bar{{margin-top:6px}}
</style></head>
<body>
<header>
 <h1>{title}</h1>
 <div class="bar">
   <select id="line"></select>
   <select id="ep"></select>
   <button id="prev">上一集</button>
   <button id="next">下一集</button>
   <span id="status" style="color:#0f0;font-size:12px"></span>
 </div>
</header>
<video id="v" controls autoplay></video>
<script>
const DATA = {data};
const lineSel=document.getElementById('line');
const epSel=document.getElementById('ep');
const v=document.getElementById('v');
const status=document.getElementById('status');
let hls=null;
DATA.forEach((ln,i)=>{{const o=document.createElement('option');o.value=i;o.textContent=ln.name+` (`+ln.eps.length+`集)`;lineSel.appendChild(o);}});
function loadEp(li,ei){{
  const ep=DATA[li].eps[ei];
  status.textContent='加载中…';
  if(hls){{hls.destroy();hls=null;}}
  if(!ep.url){{status.textContent='该集无直链';return;}}
  if(Hls.isSupported()){{hls=new Hls({{maxBufferLength:30,maxMaxBufferLength:60,enableWorker:true}});hls.loadSource(ep.url);hls.attachMedia(v);hls.on(Hls.Events.MANIFEST_PARSED,()=>{{v.play();status.textContent='播放中';}});hls.on(Hls.Events.ERROR,(_,e)=>{{if(e.fatal)status.textContent='错误:'+e.type;}});}}
  else if(v.canPlayType('application/vnd.apple.mpegurl')){{v.src=ep.url;v.play();status.textContent='播放中';}}
}}
function fillEps(li){{epSel.innerHTML='';DATA[li].eps.forEach((ep,i)=>{{const o=document.createElement('option');o.value=i;o.textContent=ep.name;epSel.appendChild(o);}});}}
lineSel.onchange=()=>{{fillEps(+lineSel.value);loadEp(+lineSel.value,0);}};
epSel.onchange=()=>loadEp(+lineSel.value,+epSel.value);
document.getElementById('prev').onclick=()=>{{if(epSel.selectedIndex>0){{epSel.selectedIndex--;loadEp(+lineSel.value,+epSel.value);}}}};
document.getElementById('next').onclick=()=>{{if(epSel.selectedIndex<epSel.length-1){{epSel.selectedIndex++;loadEp(+lineSel.value,+epSel.value);}}}};
v.onended=()=>document.getElementById('next').click();
fillEps(0);loadEp(0,0);
</script></body></html>"""


def generate_html_player(vid, name, resolved_lines):
    """生成预解析所有线路/集数的离线 HTML 播放器。"""
    data = []
    for ln in resolved_lines:
        data.append({
            "name": ln["name"],
            "eps": [{"name": e["name"], "url": e["url"]} for e in ln["eps"]],
        })
    return HTML_PLAYER.format(title=name, data=json.dumps(data, ensure_ascii=False))


def find_native_player():
    for p in ("mpv", "vlc", "ffplay"):
        path = subprocess.run(["which", p], capture_output=True, text=True).stdout.strip()
        if path:
            return p, path
    return None, None


def play_native(url):
    """用本机播放器直接串流 m3u8（硬件解码，比网页播放更流畅）。"""
    p, path = find_native_player()
    if not p:
        print("[!] 未找到 mpv/vlc/ffplay，无法本地播放。可改用 html 命令生成网页播放器。")
        return False
    print(f"[*] 使用 {p} 播放：{url}")
    if p == "ffplay":
        subprocess.run([path, "-fflags", "nobuffer", "-flags", "low_delay", url])
    else:
        subprocess.run([path, url])
    return True


# ------------------------------------------------------------------ CLI
def cmd_categories(args):
    CAT.print_all()


def cmd_list(args):
    slug = args.slug
    for page in range(1, args.pages + 1):
        html = fetch(CAT.list_url(slug, page))
        items = parse_list(html)
        if not items:
            print(f"[!] 第 {page} 页无内容，停止。")
            break
        print(f"\n=== {slug}  第{page}页 ({len(items)} 条) ===")
        for i, (vid, name, cover, note) in enumerate(items, 1):
            print(f"{i:>2}. [{vid}] {name}  {note}")


def cmd_search(args):
    q = args.keyword
    url = f"{BASE}/vodsearch/{q}/"
    html = fetch(url)
    items = parse_list(html)
    if not items:
        # 备用：关键词搜索接口
        url2 = f"{BASE}/index.php/vod/search.html?wd={q}"
        html = fetch(url2)
        items = parse_list(html)
    print(f"搜索「{q}」共 {len(items)} 条：")
    for i, (vid, name, cover, note) in enumerate(items, 1):
        print(f"{i:>2}. [{vid}] {name}  {note}")


def cmd_detail(args):
    html = fetch(f"{BASE}/varticle/{args.vid}/")
    if not html:
        return
    name, info, lines = parse_detail(html)
    print(f"片名：{name}")
    for k, v in info.items():
        print(f"  {k}: {v}")
    print(f"\n【所有播放线路】共 {len(lines)} 条：")
    for i, ln in enumerate(lines, 1):
        eps = "、".join(e[1] for e in ln["eps"])
        print(f"  {i:>2}. 线路[{ln['sid']}] {ln['name']}  ({len(ln['eps'])}集): {eps}")


def cmd_m3u8(args):
    html = fetch(f"{BASE}/varticle/{args.vid}/")
    name, info, lines = parse_detail(html)
    if args.line is None:
        print("可用线路：")
        for i, ln in enumerate(lines, 1):
            print(f"  {i}. [{ln['sid']}] {ln['name']}")
        return
    idx = args.line - 1
    if not (0 <= idx < len(lines)):
        print("[!] 线路序号越界")
        return
    ln = lines[idx]
    print(f"[*] 解析线路：{ln['name']} (sid={ln['sid']})")
    resolved = resolve_line(args.vid, ln, workers=args.workers)
    for ep in resolved:
        print(f"  {ep['name']:<8} {ep['url'] or '无直链'}")


def cmd_playlist(args):
    html = fetch(f"{BASE}/varticle/{args.vid}/")
    name, info, lines = parse_detail(html)
    if args.line is None:
        args.line = 1
    ln = lines[args.line - 1]
    resolved = resolve_line(args.vid, ln, workers=args.workers)
    text = build_m3u(args.vid, ln, resolved, name)
    fn = f"{name}_{ln['name']}.m3u".replace("/", "_")
    with open(fn, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[+] 已生成播放列表：{fn}  ({sum(1 for e in resolved if e['url'])} 条有效直链)")


def cmd_html(args):
    html = fetch(f"{BASE}/varticle/{args.vid}/")
    name, info, lines = parse_detail(html)
    # 默认解析所有线路（或指定一条）
    targets = lines if args.line is None else [lines[args.line - 1]]
    resolved_lines = []
    for ln in targets:
        print(f"[*] 解析线路 {ln['name']} ...")
        eps = resolve_line(args.vid, ln, workers=args.workers)
        resolved_lines.append({"name": ln["name"], "eps": eps})
    out = generate_html_player(args.vid, name, resolved_lines)
    fn = f"{name}_player.html".replace("/", "_")
    with open(fn, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"[+] 已生成离线播放器：{fn}（双击用浏览器打开即可，已预解析所有直链，切换即播）")


def cmd_play(args):
    html = fetch(f"{BASE}/varticle/{args.vid}/")
    name, info, lines = parse_detail(html)
    if args.line is None:
        args.line = 1
    ln = lines[args.line - 1]
    nid = args.ep or 1
    sid = ln["sid"]
    url, frm = resolve_m3u8(args.vid, sid, nid)
    if not url:
        print("[!] 解析直链失败")
        return
    print(f"[*] {name} / {ln['name']} / 第{nid}集 -> {url}")
    play_native(url)


def cmd_download(args):
    """用 ffmpeg 下载（合并为 mp4），适合弱网/卡顿场景。"""
    html = fetch(f"{BASE}/varticle/{args.vid}/")
    name, info, lines = parse_detail(html)
    if args.line is None:
        args.line = 1
    ln = lines[args.line - 1]
    nid = args.ep or 1
    sid = ln["sid"]
    url, frm = resolve_m3u8(args.vid, sid, nid)
    if not url:
        print("[!] 解析直链失败")
        return
    fn = f"{name}_{ln['name']}_第{nid}集.mp4".replace("/", "_")
    print(f"[*] 下载中（ffmpeg 直接合并 m3u8）：{fn}")
    r = subprocess.run(["ffmpeg", "-y", "-hwaccel", "auto", "-i", url,
                        "-c", "copy", fn], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"[+] 下载完成：{fn}")
    else:
        print("[!] 下载失败，请确认已安装 ffmpeg。")
        print(r.stderr[-500:])


def build_parser():
    p = argparse.ArgumentParser(
        description="乐久电影网 l9dy.com 命令行工具（分类/搜索/直链/播放）")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("cats", help="打印全部一级/二级分类").set_defaults(func=cmd_categories)

    pl = sub.add_parser("list", help="按分类 slug 列出影片")
    pl.add_argument("slug", help="分类 slug，如 guochandongman / xijupian")
    pl.add_argument("--pages", type=int, default=1, help="翻页数，默认1")
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("search", help="搜索影片")
    ps.add_argument("keyword", help="关键词")
    ps.set_defaults(func=cmd_search)

    pd = sub.add_parser("detail", help="影片详情 + 所有播放线路")
    pd.add_argument("vid", help="影片 id（varticle 路径里的数字）")
    pd.set_defaults(func=cmd_detail)

    pm = sub.add_parser("m3u8", help="解析某线路的 m3u8 直链")
    pm.add_argument("vid")
    pm.add_argument("--line", type=int, default=None, help="线路序号（不填则列出全部线路）")
    pm.add_argument("--workers", type=int, default=8)
    pm.set_defaults(func=cmd_m3u8)

    pp = sub.add_parser("playlist", help="生成 .m3u 播放列表")
    pp.add_argument("vid")
    pp.add_argument("--line", type=int, default=None)
    pp.add_argument("--workers", type=int, default=8)
    pp.set_defaults(func=cmd_playlist)

    ph = sub.add_parser("html", help="生成离线 HTML 播放器（预解析直链，切换即播）")
    ph.add_argument("vid")
    ph.add_argument("--line", type=int, default=None, help="不填则包含所有线路")
    ph.add_argument("--workers", type=int, default=8)
    ph.set_defaults(func=cmd_html)

    pp2 = sub.add_parser("play", help="用本机播放器直接串流")
    pp2.add_argument("vid")
    pp2.add_argument("--line", type=int, default=None)
    pp2.add_argument("--ep", type=int, default=None, help="集数 nid")
    pp2.set_defaults(func=cmd_play)

    pd2 = sub.add_parser("download", help="用 ffmpeg 下载为 mp4")
    pd2.add_argument("vid")
    pd2.add_argument("--line", type=int, default=None)
    pd2.add_argument("--ep", type=int, default=None)
    pd2.set_defaults(func=cmd_download)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
