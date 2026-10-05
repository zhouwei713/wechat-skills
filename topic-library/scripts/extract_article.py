#!/usr/bin/env python3
"""从文章页面提取正文和基础信息，回写到 articles.json。

页面来源（按优先级）
  1. work/html/<id>.html   用浏览器打开文章后保存的整页 HTML（公众号文章最稳的方式）
  2. work/text/<id>.txt    已经拿到的纯文本正文（比如 WebFetch 的结果），第一行可以是标题
  3. --fetch               脚本直接请求链接，公众号经常会被拦，失败就保持"仅卡片"

产出
  work/text/<id>.md        清洗后的正文，给模型读
  articles.json            补上 publish_date / word_count / image_count / read_status / account / title

用法
  python extract_article.py work/articles.json [--fetch] [--ids a1,a3]
"""
import argparse, html, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from common import load, save

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

CN = timezone(timedelta(hours=8))
BLOCK_PAGE = re.compile(r'(环境异常|完成验证后即可继续访问|该内容已被发布者删除|此内容因违规无法查看|访问过于频繁|参数错误)')


def from_html(raw):
    info = {}
    m = re.search(r'var\s+ct\s*=\s*"(\d{9,11})"', raw) or re.search(r'"create_time"\s*:\s*"?(\d{9,11})', raw)
    if m:
        info['publish_date'] = datetime.fromtimestamp(int(m.group(1)), CN).strftime('%Y-%m-%d')
    else:
        m = re.search(r'(20\d\d)[-年](\d{1,2})[-月](\d{1,2})', re.sub(r'<[^>]+>', ' ', raw)[:20000])
        if m:
            info['publish_date'] = f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    m = re.search(r'var\s+nickname\s*=\s*(?:htmlDecode\()?"([^"]+)"', raw) or re.search(r'id="js_name"[^>]*>\s*([^<]+?)\s*<', raw)
    if m:
        info['account'] = html.unescape(m.group(1)).strip()
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', raw) or re.search(r'class="rich_media_title[^"]*"[^>]*>\s*([\s\S]*?)</h1>', raw)
    if m:
        info['title'] = html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()

    if BeautifulSoup:
        soup = BeautifulSoup(raw, 'html.parser')
        body = soup.select_one('#js_content') or soup.select_one('article') or soup.body or soup
        for t in body.select('script,style'):
            t.decompose()
        imgs = len(body.find_all('img'))
        parts = []
        for el in body.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'pre', 'blockquote', 'li', 'section'], recursive=True):
            if el.name == 'section' and el.find(['p', 'h1', 'h2', 'h3', 'pre', 'section']):
                continue
            if el.find_parent('pre') is not None and el.name != 'pre':
                continue
            txt = el.get_text('\n' if el.name == 'pre' else '', strip=el.name != 'pre')
            if not txt.strip():
                continue
            if el.name in ('h1', 'h2', 'h3', 'h4'):
                parts.append('## ' + txt.strip())
            elif el.name == 'pre':
                parts.append('```\n' + txt.strip('\n') + '\n```')
            elif el.name == 'li':
                parts.append('* ' + txt.strip())
            else:
                parts.append(txt.strip())
        # 去掉连续重复（嵌套 section 偶尔会重复取到）
        dedup = []
        for p in parts:
            if not dedup or dedup[-1] != p:
                dedup.append(p)
        text = '\n\n'.join(dedup)
    else:
        seg = re.search(r'id="js_content"[\s\S]*?>([\s\S]*?)<script', raw)
        seg = seg.group(1) if seg else raw
        imgs = len(re.findall(r'<img\b', seg))
        seg = re.sub(r'<(script|style)[\s\S]*?</\1>', '', seg)
        seg = re.sub(r'</(p|section|h\d|li|pre|div)>|<br\s*/?>', '\n', seg)
        text = html.unescape(re.sub(r'<[^>]+>', '', seg))
        text = re.sub(r'\n\s*\n+', '\n\n', text).strip()
    info['image_count'] = imgs
    return info, text


def word_count(text):
    t = re.sub(r'```[\s\S]*?```', '', text)
    cjk = len(re.findall(r'[一-鿿]', t))
    en = len(re.findall(r'[A-Za-z0-9]+', t))
    return cjk + en


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('articles')
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--ids')
    a = ap.parse_args()
    data = load(a.articles)
    work = Path(a.articles).parent
    want = set(a.ids.split(',')) if a.ids else None

    for x in data['articles']:
        if want and x['id'] not in want:
            continue
        raw_html, text, info = None, None, {}
        hp, tp = work / 'html' / f'{x["id"]}.html', work / 'text' / f'{x["id"]}.txt'
        if hp.exists():
            raw_html = hp.read_text('utf-8', errors='replace')
        elif tp.exists():
            text = tp.read_text('utf-8', errors='replace').strip()
        elif a.fetch and x.get('url'):
            try:
                import urllib.request
                req = urllib.request.Request(x['url'], headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'})
                raw_html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='replace')
            except Exception as ex:
                print(f'  {x["id"]} 抓取失败：{ex}')

        if raw_html is not None:
            if BLOCK_PAGE.search(raw_html[:30000]) and 'js_content' not in raw_html:
                print(f'  {x["id"]} 页面被拦截或已删除，保持仅卡片')
                raw_html = None
            else:
                info, text = from_html(raw_html)

        if text and word_count(text) >= 200:
            (work / 'text').mkdir(parents=True, exist_ok=True)
            (work / 'text' / f'{x["id"]}.md').write_text(text, 'utf-8')
            x['read_status'] = '已读全文'
            x['word_count'] = word_count(text)
            x['image_count'] = info.get('image_count', x.get('image_count'))
            for k in ('publish_date', 'account', 'title'):
                if info.get(k) and not x.get(k):
                    x[k] = info[k]
            if info.get('publish_date'):
                x['publish_date'] = info['publish_date']
        else:
            x['read_status'] = '仅卡片' if (x.get('title') or x.get('summary')) else '未读取'
        print(f'  {x["id"]} {x["read_status"]} | {x.get("title","")[:28]} | 字数 {x.get("word_count","-")} | 图 {x.get("image_count","-")} | {x.get("publish_date","")}')

    save(a.articles, data)
    st = {}
    for x in data['articles']:
        st[x['read_status']] = st.get(x['read_status'], 0) + 1
    print('读取状态', st)


if __name__ == '__main__':
    main()
