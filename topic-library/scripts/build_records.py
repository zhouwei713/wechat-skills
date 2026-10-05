#!/usr/bin/env python3
"""校验模型的分析结果，合并脚本字段，生成可以直接交给飞书连接器写入的记录。

输入
  work/articles.json   parse / extract / dedupe 之后的文章列表
  work/analysis.json   模型按 analysis_guide.md 填写，格式 {"articles": {"a1": {"一句话核心": "...", ...}}}
  work/existing.json   可选，用来统计选题簇撞题

产出
  work/records.json    每条记录的 op（create / update）、record_id、fields，字段值已按飞书多维表格格式整理
  work/records.csv     连接器不可用时手动导入用
  work/receipt.md      给用户的回执

有 ERROR 时退出码为 1，不生成记录。

用法
  python build_records.py work/articles.json --analysis work/analysis.json [--existing work/existing.json] [--config config.json]
"""
import argparse, csv, difflib, re, sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from common import load, save, fields_def, field_text_value

CN = timezone(timedelta(hours=8))
FULLTEXT_ONLY = ['大纲', '可带走资产', '亮点', '空白', '文章形态', '开头方式']
MAX_MULTI = {'赛道标签': 3, '标题公式': 2}
# 线上是长文本列、但模型仍按列表交付的字段（多选上限 50 会静默截断，所以建的是长文本）。
# 超过上限只提醒不报错：长文本不会被截断，真正会出事的是开放词表列超过 50 个值。
LIST_AS_TEXT = {'钩子词': 3, '提到的工具': 20}
DEFAULT_BANS = ['——', '—', '不是[^。！？\n]{0,30}而是']


def ms(d):
    return int(datetime.strptime(d, '%Y-%m-%d').replace(tzinfo=CN).timestamp() * 1000)


def squash(s):
    return re.sub(r'\s+', '', s or '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('articles')
    ap.add_argument('--analysis', required=True)
    ap.add_argument('--existing')
    ap.add_argument('--config')
    a = ap.parse_args()
    cfg = load(a.config, {}) if a.config else {}
    F = fields_def()
    fmap = {f['name']: f for f in F['fields']}
    model_fields = {f['name'] for f in F['fields'] if f['filled_by'] == 'model'}
    arts = load(a.articles)['articles']
    ana = load(a.analysis)['articles']
    work = Path(a.articles).parent
    bans = cfg.get('style_bans', DEFAULT_BANS)
    errs, warns = [], []

    ex = load(a.existing, []) if a.existing else []
    if isinstance(ex, dict):
        ex = ex.get('items') or ex.get('records') or []
    old_clusters = Counter(field_text_value((r.get('fields', r)).get('选题簇')) for r in ex)
    old_clusters.pop('', None)

    for x in arts:
        w = f'{x["id"]}《{x.get("title","")[:16]}》'
        A = ana.get(x['id'])
        if A is None:
            errs.append(f'{w} 没有分析结果'); continue
        if 'op' not in x:
            # 没跑 dedupe.py 时按新增处理，但要先提醒——撞题检查依赖 dedupe 打好的 op
            warns.append(f'{w} 缺少 op 字段，按新增处理。若已入库过同一篇，请先跑 dedupe.py')
        for k in A:
            if k not in model_fields:
                errs.append(f'{w} 字段「{k}」不是模型该填的字段，可填字段见 fields.json')
        for k, v in A.items():
            f = fmap.get(k)
            if not f or v in (None, '', []):
                continue
            if f['type'] == 'multi_select':
                if not isinstance(v, list):
                    errs.append(f'{w} 「{k}」应为列表'); continue
                if len(v) > MAX_MULTI.get(k, 99):
                    errs.append(f'{w} 「{k}」最多 {MAX_MULTI[k]} 个')
                if f.get('vocab') == 'fixed':
                    bad = [i for i in v if i not in f['options']]
                    if bad:
                        errs.append(f'{w} 「{k}」出现不在选项里的值 {bad}，可选 {f["options"]}')
            if f['type'] == 'single_select' and f.get('vocab') == 'fixed' and v not in f['options']:
                errs.append(f'{w} 「{k}」的值「{v}」不在选项 {f["options"]} 里')
            if k in LIST_AS_TEXT:
                # 线上是长文本列（多选上限 50 会静默截断），但仍按列表交付
                if not isinstance(v, list):
                    errs.append(f'{w} 「{k}」应为列表（线上是长文本列，写入时会合成一段）'); continue
                if len(v) > LIST_AS_TEXT[k]:
                    warns.append(f'{w} 「{k}」{len(v)} 个，超过 {LIST_AS_TEXT[k]} 个，建议精简')
            if f['type'] == 'number' and 'min' in f and (not isinstance(v, (int, float)) or not f['min'] <= v <= f['max']):
                errs.append(f'{w} 「{k}」应为 {f["min"]} 到 {f["max"]} 的数字')
            if isinstance(v, str) and k != '可带走资产':
                for b in bans:
                    if re.search(b, v):
                        errs.append(f'{w} 「{k}」出现禁用写法 /{b}/：{v[:30]}')
        for k in ('一句话核心', '选题类型', '赛道标签', '选题簇', '匹配度'):
            if A.get(k) in (None, '', []):
                errs.append(f'{w} 缺少必填字段「{k}」')
        if len(A.get('一句话核心', '')) > 50:
            warns.append(f'{w} 一句话核心超过 50 字')

        # 没读到全文不许写结构类字段
        if x.get('read_status') != '已读全文':
            filled = [k for k in FULLTEXT_ONLY if A.get(k)]
            if filled:
                errs.append(f'{w} 读取状态为「{x.get("read_status")}」，不能填写 {filled}')
        else:
            body = squash((work / 'text' / f'{x["id"]}.md').read_text('utf-8')) if (work / 'text' / f'{x["id"]}.md').exists() else ''
            for chunk in re.split(r'\n\s*\n', A.get('可带走资产') or ''):
                c = squash(re.sub(r'^```\w*|```$', '', chunk.strip(), flags=re.M))
                if c and c not in body:
                    errs.append(f'{w} 可带走资产必须逐字出自正文，这段在正文里找不到：{chunk.strip()[:30]}')

        # 选题簇：和已有簇名很像但不完全一样，多半是该沿用没沿用
        c = A.get('选题簇', '')
        known = set(old_clusters) | {ana[y['id']].get('选题簇', '') for y in arts if y['id'] != x['id'] and y['id'] in ana}
        known.discard('')
        if c and c not in known:
            near = [o for o in known if difflib.SequenceMatcher(None, c.replace(' ', ''), o.replace(' ', '')).ratio() >= 0.7]
            if near:
                errs.append(f'{w} 新簇「{c}」和已有簇 {near} 很像，同一件事请沿用原簇名；确实不同就把簇名改得更有区分度')

    for m in warns:
        print('WARN ', m)
    if errs:
        for m in errs:
            print('ERROR', m)
        sys.exit(f'\n校验未通过，{len(errs)} 个错误，未生成记录')

    # 组装记录
    today = datetime.now(CN).strftime('%Y-%m-%d')
    ops, rows = [], []
    for x in arts:
        A = ana[x['id']]
        base = {
            '标题': x.get('title') or '（无标题）',
            '公众号': x.get('account') or None,
            '链接': {'link': x['url'], 'text': x.get('title') or x['url']} if x.get('url') else None,
            '发布日期': ms(x['publish_date']) if x.get('publish_date') else None,
            '入库日期': ms(x.get('added') or today),
            '字数': x.get('word_count'),
            '配图数': x.get('image_count'),
            '来源': x.get('source', '转发'),
            '对标账号': bool(x.get('benchmark')),
            '读取状态': x.get('read_status', '未读取'),
        }
        fields = {**base, **A}
        if x.get('op', 'create') == 'create':
            for f in F['fields']:
                if f.get('default') and f['name'] not in fields:
                    fields[f['name']] = f['default']
        else:
            for f in F['fields']:
                if f.get('keep_on_update'):
                    fields.pop(f['name'], None)
        fields = {k: v for k, v in fields.items() if v not in (None, '', [])}
        op = {'op': x.get('op', 'create'), 'id': x['id'], 'fields': fields}
        if x.get('op') == 'update':
            op['record_id'] = x.get('record_id')
            op['match'] = {F['match_field']: x.get('url')}
        ops.append(op)

        row = {}
        for f in F['fields']:
            v = fields.get(f['name'], '')
            if f['type'] == 'date' and v:
                v = datetime.fromtimestamp(v / 1000, CN).strftime('%Y-%m-%d')
            elif f['type'] == 'url' and isinstance(v, dict):
                v = v['link']
            elif f['name'] in LIST_AS_TEXT and isinstance(v, list):
                v = '\n'.join(str(x) for x in v)
            elif isinstance(v, list):
                v = ','.join(v)
            elif isinstance(v, bool):
                v = '是' if v else ''
            row[f['name']] = v
        rows.append(row)

    save(work / 'records.json', {'table_name': cfg.get('table_name', F['table_name']), 'match_field': F['match_field'], 'ops': ops})
    with open(work / 'records.csv', 'w', newline='', encoding='utf-8-sig') as fh:
        wr = csv.DictWriter(fh, fieldnames=[f['name'] for f in F['fields']])
        wr.writeheader()
        wr.writerows(rows)

    # 回执
    new_c = Counter(ana[x['id']]['选题簇'] for x in arts)
    total = Counter(old_clusters)
    for c, n in new_c.items():
        total[c] += n
    n_create = sum(1 for o in ops if o['op'] == 'create')
    lines = [f'本次处理 {len(arts)} 篇，新增 {n_create} 篇，更新 {len(arts) - n_create} 篇。']
    rs = Counter(x.get('read_status') for x in arts)
    if rs.get('仅卡片') or rs.get('未读取'):
        lines.append(f'其中 {rs.get("仅卡片", 0) + rs.get("未读取", 0)} 篇没读到全文，只分析了标题和摘要，结构类字段留空。')
    hot = [(c, total[c]) for c in new_c if total[c] >= 2]
    if hot:
        lines.append('撞题提醒，' + '；'.join(f'「{c}」算上这批共 {n} 篇' for c, n in hot) + '。')
    good = sorted([x for x in arts if ana[x['id']].get('匹配度', 0) >= 4], key=lambda x: -ana[x['id']]['匹配度'])[:2]
    for x in good:
        A = ana[x['id']]
        lines.append(f'《{x.get("title","")[:30]}》匹配度 {A["匹配度"]} 分，可以写成「{A.get("建议标题","")}」')
    (work / 'receipt.md').write_text('\n'.join(lines), 'utf-8')
    print('\n'.join(lines))
    print(f'\n记录已生成 {work / "records.json"}，备用 CSV {work / "records.csv"}')


if __name__ == '__main__':
    main()
