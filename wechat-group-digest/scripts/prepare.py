#!/usr/bin/env python3
"""统计和粗切。所有数字都在这里算，模型不碰数数。

输入 work/messages.json
输出
  work/stats.json            数字卡片、活跃榜、链接清单、问题候选、与上一期的对比
  work/blocks.md             按时间粗切好的消息块，带编号，给模型读
  work/link_candidates.json  链接抓取候选和建议策略

用法
  python prepare.py work/messages.json --config config.json [--history history/]
"""
import argparse, json, re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

QUESTION_PAT = re.compile(r'([?？]\s*$|怎么|如何|有没有|求推荐|求助|请教|哪个好|哪里|能不能|可以吗|是不是|为什么|为啥|咋|吗\s*[?？]?\s*$|有人知道|谁知道)')

DOMAIN_TYPES = [
    ('GitHub', ['github.com', 'gitee.com']),
    ('X', ['x.com', 'twitter.com']),
    ('文章', ['mp.weixin.qq.com', 'zhihu.com', 'juejin.cn', 'medium.com', 'substack.com', 'sspai.com', 'jianshu.com', 'csdn.net']),
    ('视频', ['bilibili.com', 'b23.tv', 'youtube.com', 'youtu.be', 'douyin.com', 'v.qq.com', 'channels.weixin.qq.com', 'xiaohongshu.com', 'xhslink.com', 'kuaishou.com']),
    ('文档', ['feishu.cn', 'larksuite.com', 'docs.qq.com', 'shimo.im', 'yuque.com', 'kdocs.cn', 'notion.so', 'notion.site', 'docs.google.com']),
    ('论文', ['arxiv.org', 'openreview.net']),
    ('模型', ['huggingface.co', 'modelscope.cn']),
]
# 不抓取：大概率是私人或内部资料
PRIVATE_DOMAINS = ['feishu.cn', 'larksuite.com', 'docs.qq.com', 'shimo.im', 'kdocs.cn', 'yuque.com', 'notion.so', 'notion.site', 'docs.google.com', 'pan.baidu.com', 'aliyundrive.com', 'quark.cn']
# 只能拿到标题和简介
TITLE_ONLY_DOMAINS = ['bilibili.com', 'b23.tv', 'youtube.com', 'youtu.be', 'douyin.com', 'v.qq.com', 'channels.weixin.qq.com', 'kuaishou.com', 'xiaohongshu.com', 'xhslink.com']
HIGH_VALUE = ['GitHub', '论文', '模型']


def norm_url(u):
    try:
        s = urlsplit(u)
        q = [(k, v) for k, v in parse_qsl(s.query) if not k.lower().startswith(('utm_', 'spm', 'from', 'share', 'scene', 'chksm', 'sessionid', 'xsec'))]
        return urlunsplit((s.scheme, s.netloc.lower(), s.path.rstrip('/'), urlencode(q), ''))
    except Exception:
        return u


def domain_of(u):
    return urlsplit(u).netloc.lower().split(':')[0]


def link_type(dom):
    for name, ds in DOMAIN_TYPES:
        if any(dom == d or dom.endswith('.' + d) for d in ds):
            return name
    return '网页'


def in_list(dom, lst):
    return any(dom == d or dom.endswith('.' + d) for d in lst)


def tmin(m):
    h, mi, s = map(int, m['time'].split(':'))
    return h * 60 + mi + s / 60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('messages')
    ap.add_argument('--config')
    ap.add_argument('--history', default='history')
    ap.add_argument('--workdir')
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text('utf-8')) if a.config else {}
    data = json.loads(Path(a.messages).read_text('utf-8'))
    msgs = data['messages']
    work = Path(a.workdir) if a.workdir else Path(a.messages).parent
    gap = cfg.get('gap_minutes', 20)

    counted = [m for m in msgs if m['type'] not in ('system', 'recall')]
    by_id = {m['id']: m for m in msgs}
    sender_cnt = Counter(m['sender'] for m in counted)

    # 链接
    links = {}
    for m in counted:
        for u in m['urls']:
            k = norm_url(u)
            if k not in links:
                dom = domain_of(u)
                links[k] = {'url': u, 'key': k, 'domain': dom, 'type': link_type(dom), 'first_id': m['id'],
                            'sender': m['sender'], 'time': m['time'][:5], 'shares': 0, 'sharers': [], 'context': m['content'][:200]}
            L = links[k]
            L['shares'] += 1
            if m['sender'] not in L['sharers']:
                L['sharers'].append(m['sender'])
    link_cnt = Counter()
    for L in links.values():
        link_cnt[L['sender']] += 1

    # 链接引起的讨论量：直接引用 + 10 分钟内其他人的非水消息
    for L in links.values():
        src = by_id[L['first_id']]
        direct = sum(1 for m in counted if m['reply_to'] == src['id'])
        near = sum(1 for m in counted if m['id'] > src['id'] and 0 <= tmin(m) - tmin(src) <= 10 and m['sender'] != src['sender'] and not m['noise'])
        L['replies'] = direct * 2 + min(near, 8)

    # 问题候选
    q_cands = [m['id'] for m in counted if m['type'] == 'text' and not m['noise'] and QUESTION_PAT.search(m['content']) and len(m['content']) >= 5]

    # 粗切
    blocks, cur, prev = [], [], None
    for m in counted:
        if prev is not None and (tmin(m) - tmin(prev) > gap or m['date'] != prev['date']):
            blocks.append(cur); cur = []
        cur.append(m); prev = m
    if cur:
        blocks.append(cur)

    lines = [f'# 消息块（共 {len(blocks)} 块，粗切规则为静默超过 {gap} 分钟）',
             '格式 `#编号 时间 发言人 [↪被引用编号] 内容`，水消息已省略但计入统计。', '']
    block_meta = []
    for bi, b in enumerate(blocks, 1):
        ppl = len({m['sender'] for m in b})
        lines.append(f'## B{bi} · {b[0]["time"][:5]} 至 {b[-1]["time"][:5]} · {len(b)} 条 · {ppl} 人')
        skipped = 0
        for m in b:
            if m['noise']:
                skipped += 1; continue
            c = m['content'].replace('\n', ' / ')
            if len(c) > 300:
                c = c[:300] + '……（截断）'
            if m['type'] in ('image', 'video', 'voice', 'file') and len(c) < 8:
                c = {'image': '[图片]', 'video': '[视频]', 'voice': '[语音]', 'file': '[文件]'}[m['type']] + (' ' + c if c and not c.startswith('[') else '')
            rt = f' ↪#{m["reply_to"]}' if m['reply_to'] else ''
            qmark = ' 〔问〕' if m['id'] in q_cands else ''
            lines.append(f'#{m["id"]} {m["time"][:5]} {m["sender"]}{rt}{qmark} {c}')
        if skipped:
            lines.append(f'（本块省略水消息 {skipped} 条）')
        lines.append('')
        block_meta.append({'block': f'B{bi}', 'ids': [m['id'] for m in b], 'start': b[0]['time'][:5], 'end': b[-1]['time'][:5]})

    # 链接抓取候选
    max_fetch = cfg.get('link_fetch', {}).get('max_links', 6)
    cands = []
    for L in links.values():
        dom = L['domain']
        if in_list(dom, PRIVATE_DOMAINS):
            policy, why = 'skip_private', '可能是私人或内部文档，不打开'
        elif in_list(dom, TITLE_ONLY_DOMAINS):
            policy, why = 'title_only', '视频类，只取标题和简介'
        else:
            policy, why = 'fetch', ''
        score = L['replies'] + L['shares'] * 2 + (3 if L['type'] in HIGH_VALUE else 0)
        cands.append({**L, 'policy': policy, 'policy_note': why, 'score': score})
    cands.sort(key=lambda x: -x['score'])
    n = 0
    for c in cands:
        c['recommend'] = c['policy'] != 'skip_private' and n < max_fetch
        if c['recommend']:
            n += 1

    # 上一期
    prev_stats = None
    hist = Path(a.history) / f'{cfg.get("group_id", "default")}.jsonl'
    day = msgs[0]['date'] if msgs else ''
    if hist.exists():
        rows = [json.loads(l) for l in hist.read_text('utf-8').splitlines() if l.strip()]
        rows = [r for r in rows if r.get('date', '') < day]
        if rows:
            prev_stats = rows[-1]

    stats = {
        'date': day,
        'dates': data['meta'].get('dates', [day]),
        'time_range': [counted[0]['time'][:5], counted[-1]['time'][:5]] if counted else ['', ''],
        'messages': len(counted),
        'speakers': len(sender_cnt),
        'links': len(links),
        'noise_filtered': sum(1 for m in msgs if m['noise'] or m['type'] in ('system', 'recall')),
        'ranking': sender_cnt.most_common(),
        'link_by_sender': link_cnt.most_common(),
        'question_candidates': q_cands,
        'link_list': sorted(links.values(), key=lambda x: x['first_id']),
        'blocks': block_meta,
        'hourly': [sum(1 for m in counted if int(m['time'][:2]) == h) for h in range(24)],
        'prev': prev_stats,
    }
    (work / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=1), 'utf-8')
    (work / 'blocks.md').write_text('\n'.join(lines), 'utf-8')
    (work / 'link_candidates.json').write_text(json.dumps(cands, ensure_ascii=False, indent=1), 'utf-8')
    print(f'消息 {stats["messages"]} 条 · 发言 {stats["speakers"]} 人 · 链接 {stats["links"]} 个 · 粗切 {len(blocks)} 块 · 问题候选 {len(q_cands)} 条')
    print(f'建议抓取链接 {sum(1 for c in cands if c["recommend"])} 个，详见 link_candidates.json')
    if prev_stats:
        print(f'上一期 {prev_stats["date"]} 消息 {prev_stats["messages"]} 条')


if __name__ == '__main__':
    main()
