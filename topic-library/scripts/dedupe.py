#!/usr/bin/env python3
"""和多维表格里已有的记录比对，决定每篇是新增还是更新。

existing.json 是通过飞书连接器读出来的现有记录，下面几种结构都认
  [{"record_id": "...", "fields": {"链接": ..., "标题": ..., "选题簇": ...}}, ...]
  {"items": [...同上...]}
  [{"链接": ..., "标题": ...}, ...]
表还不存在或者是空表时，传一个空列表 [] 或不传。

产出
  articles.json 每篇加上 op（create / update）和 record_id
  work/existing_brief.md  已有记录的选题簇和一句话核心，给模型判断选题簇用

用法
  python dedupe.py work/articles.json --existing work/existing.json
"""
import argparse, difflib, re
from collections import Counter
from pathlib import Path
from common import load, save, norm_url, field_link_value, field_text_value


def norm_title(t):
    return re.sub(r'[\s\W_]+', '', t or '').lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('articles')
    ap.add_argument('--existing')
    ap.add_argument('--title-threshold', type=float, default=0.88)
    a = ap.parse_args()
    data = load(a.articles)
    work = Path(a.articles).parent
    ex = load(a.existing, []) if a.existing else []
    if isinstance(ex, dict):
        ex = ex.get('items') or ex.get('records') or ex.get('data', {}).get('items', []) or []

    recs = []
    for r in ex:
        f = r.get('fields', r)
        recs.append({'record_id': r.get('record_id') or r.get('id'), 'url_key': norm_url(field_link_value(f.get('链接'))),
                     'title': field_text_value(f.get('标题')), 'cluster': field_text_value(f.get('选题簇')),
                     'core': field_text_value(f.get('一句话核心')), 'date': f.get('入库日期'), 'status': field_text_value(f.get('选题状态'))})
    by_url = {r['url_key']: r for r in recs if r['url_key']}

    n_new = n_upd = 0
    for x in data['articles']:
        x['url_key'] = x.get('url_key') or norm_url(x.get('url'))
        hit = by_url.get(x['url_key']) if x['url_key'] else None
        how = '链接相同' if hit else ''
        if not hit and x.get('title'):
            nt = norm_title(x['title'])
            best, score = None, 0
            for r in recs:
                s = difflib.SequenceMatcher(None, nt, norm_title(r['title'])).ratio()
                if s > score:
                    best, score = r, s
            if best and score >= a.title_threshold:
                hit, how = best, f'标题相似 {score:.2f}'
        if hit:
            x['op'], x['record_id'], x['match_reason'] = 'update', hit['record_id'], how
            n_upd += 1
        else:
            x['op'], x['record_id'] = 'create', None
            n_new += 1
        print(f'  {x["id"]} {x["op"]:6} {how} | {x.get("title","")[:30]}')

    clusters = Counter(r['cluster'] for r in recs if r['cluster'])
    lines = [f'# 已有记录 {len(recs)} 条，选题簇 {len(clusters)} 个', '',
             '判断新文章的选题簇时，同一件事就沿用下面的簇名，一字不改。', '', '## 选题簇（篇数）']
    lines += [f'* {c}（{n}）' for c, n in clusters.most_common()]
    lines += ['', '## 最近 80 条记录', '| 选题簇 | 标题 | 一句话核心 |', '|---|---|---|']
    for r in recs[-80:]:
        lines.append(f'| {r["cluster"]} | {r["title"][:40]} | {r["core"][:50]} |')
    (work / 'existing_brief.md').write_text('\n'.join(lines), 'utf-8')

    save(a.articles, data)
    print(f'新增 {n_new} 篇，更新 {n_upd} 篇；已有选题簇 {len(clusters)} 个，摘要见 existing_brief.md')


if __name__ == '__main__':
    main()
