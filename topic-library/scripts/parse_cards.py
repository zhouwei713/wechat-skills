#!/usr/bin/env python3
"""把转发进来的文章卡片解析成 work/articles.json。

支持
  1. 纯文本：微信转发的文章卡片、复制的链接列表、"标题 + 摘要 + 公众号 + 链接"混排的文字
  2. JSON：列表，每项至少有 url，可带 title / account / summary
  3. 群聊日报的 stats.json：--from-digest 把链接清单里类型为"文章"的链接接进来，来源记为"群聊"

用法
  python parse_cards.py input.txt -o work/articles.json [--config config.json]
  python parse_cards.py --from-digest ../群日报/2026-10-04/work/stats.json -o work/articles.json --append

卡片里没有链接时（有的客户端只转标题），也会生成记录，url 为空，后续需要补链接或按标题搜索。
"""
import argparse, json, re, sys
from datetime import date
from pathlib import Path
from common import URL_RE, norm_url, load, save

CARD_MARK = re.compile(r'^\s*\[(链接|公众号|分享|文章|卡片式链接|Link)\]\s*')
ACCOUNT_PAT = re.compile(r'^(?:来自|来源|公众号)[:：\s]*(.{1,30})$')
NOISE = re.compile(r'^(\d{1,2}:\d{2}|\d{4}[-/年].*\d{1,2}:\d{2}.*|聊天记录|群聊的聊天记录|.*的聊天记录)$')


def parse_text(text):
    lines = [l.rstrip() for l in text.splitlines()]
    arts, buf = [], []

    def flush(url):
        chunk = [CARD_MARK.sub('', l).strip() for l in buf if l.strip()]
        chunk = [l for l in chunk if not NOISE.match(l)]
        title, account, summary = '', '', []
        for l in chunk:
            m = ACCOUNT_PAT.match(l)
            if m:
                account = m.group(1).strip(); continue
            if not title:
                title = l
            else:
                summary.append(l)
        # 两行卡片里最后一行很短、像账号名的，当成公众号
        if not account and len(summary) >= 1 and len(summary[-1]) <= 16 and not re.search(r'[，。,.!?？！]', summary[-1]):
            account = summary.pop()
        arts.append({'title': title, 'account': account, 'summary': ' '.join(summary)[:300], 'url': url})

    for l in lines:
        urls = URL_RE.findall(l)
        if urls:
            rest = URL_RE.sub('', l).strip()
            if rest:
                buf.append(rest)
            for u in urls:
                flush(u)
                buf = []
        else:
            buf.append(l)
    # 末尾没有链接的卡片：按空行分段
    tail = '\n'.join(buf).strip()
    if tail:
        for para in re.split(r'\n\s*\n', tail):
            buf = para.splitlines()
            if any(x.strip() for x in buf):
                flush('')
    return arts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input', nargs='?')
    ap.add_argument('-o', '--output', default='work/articles.json')
    ap.add_argument('--from-digest', help='群聊日报的 stats.json')
    ap.add_argument('--append', action='store_true', help='追加到已有 articles.json')
    ap.add_argument('--config')
    a = ap.parse_args()
    cfg = load(a.config, {}) if a.config else {}

    arts = []
    if a.input:
        p = Path(a.input)
        raw = p.read_text('utf-8-sig', errors='replace')
        if p.suffix.lower() == '.json':
            data = json.loads(raw)
            data = data.get('articles', data) if isinstance(data, dict) else data
            for d in data:
                arts.append({'title': d.get('title', ''), 'account': d.get('account', ''), 'summary': d.get('summary', ''),
                             'url': d.get('url', ''), 'source': d.get('source', '转发')})
        else:
            arts = [dict(x, source='转发') for x in parse_text(raw)]
    if a.from_digest:
        st = load(a.from_digest)
        for L in st.get('link_list', []):
            if L.get('type') == '文章':
                arts.append({'title': '', 'account': '', 'summary': L.get('context', '')[:200], 'url': L['url'], 'source': '群聊',
                             'shared_by': L.get('sender', '')})

    old = load(a.output, {'articles': []}) if a.append else {'articles': []}
    seen = {norm_url(x['url']) for x in old['articles'] if x.get('url')}
    out = list(old['articles'])
    bench = set(cfg.get('benchmark_accounts', []))
    skipped = 0
    for x in arts:
        k = norm_url(x['url'])
        if k and k in seen:
            skipped += 1; continue
        if k:
            seen.add(k)
        x['url_key'] = k
        x['id'] = f'a{len(out) + 1}'
        x['added'] = date.today().isoformat()
        x['benchmark'] = x.get('account', '') in bench
        x.setdefault('read_status', '未读取')
        out.append(x)

    if not out:
        sys.exit('没有解析出任何文章。请检查输入，或按 SKILL.md 里的格式手动整理成 JSON。')
    save(a.output, {'articles': out})
    print(f'解析出 {len(out) - len(old["articles"])} 篇，批内重复跳过 {skipped} 篇，共 {len(out)} 篇')
    for x in out[len(old['articles']):]:
        flag = '' if x['url'] else '  （没有链接）'
        print(f'  {x["id"]} {x["title"][:30] or "（无标题）"} | {x["account"] or "?"}{flag}')


if __name__ == '__main__':
    main()
