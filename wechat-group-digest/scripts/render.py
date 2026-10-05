#!/usr/bin/env python3
"""把 analysis.json 和 stats.json 渲染成 HTML 和长图 PNG，并写入历史记录。

用法
  python render.py --analysis work/analysis.json --stats work/stats.json --messages work/messages.json \
      --config config.json --out out/ [--mode full|public] [--no-png] [--no-history]

mode=full    给自己看，包含「可以动手的事」
mode=public  发回群里，隐藏行动项，按配置给昵称打码
"""
import argparse, html, json, re, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEEK = '一二三四五六日'
TYPE_CLASS = {'工具测评': 't-tool', '求助答疑': 't-help', '行业消息': 't-news', '经验分享': 't-share', '争论': 't-debate',
              '闲聊': 't-news', '资源分享': 't-share', '活动通知': 't-news'}
STATUS_CLASS = {'已解决': 's-ok', '已沉淀': 's-ok', '有共识': 's-agree', '还在争': 's-fight', '没人回': 's-none', '简单提及': 's-none'}
ACT_CLASS = {'写文章': 'a-write', '做工具': 'a-tool', '做Skill': 'a-tool', '做内容': 'a-video', '马上试': 'a-try'}
READ_CLASS = {'已读取': ('rl-ok', '原文已读'), '仅标题': ('rl-title', '仅标题'), '未读取': ('rl-no', '未能读取'), '未尝试': ('', '')}

e = lambda s: html.escape(str(s if s is not None else ''))


def hm(t):
    return t[:5]


def delta(cur, prev, pct=False):
    if prev in (None, 0) and pct:
        return ''
    if prev is None:
        return ''
    d = cur - prev
    if d == 0:
        return '<em style="color:var(--sub)">持平</em>'
    cls = 'up' if d > 0 else 'down'
    arrow = '↑' if d > 0 else '↓'
    val = f'{abs(d) / prev * 100:.0f}%' if pct else str(abs(d))
    return f'<em class="{cls}">{arrow} {val}</em>'


def anonymizer(cfg, ranking):
    mode = cfg.get('anonymize', 'none')
    if mode == 'none':
        return lambda s: s, {}
    keep = set(cfg.get('anonymize_keep', []))
    names = [n for n, _ in ranking if n not in keep]
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    mp = {n: f'群友{letters[i] if i < 26 else i}' for i, n in enumerate(names)}
    order = sorted(mp, key=len, reverse=True)

    def f(s):
        if not isinstance(s, str):
            return s
        for n in order:
            s = s.replace(n, mp[n])
        return s
    return f, mp


def deep(o, f):
    if isinstance(o, str):
        return f(o)
    if isinstance(o, list):
        return [deep(x, f) for x in o]
    if isinstance(o, dict):
        return {k: (v if k in ('url', 'key', 'domain') else deep(v, f)) for k, v in o.items()}
    return o


def bold(text, hl):
    t = e(text)
    if hl:
        t = t.replace(e(hl), f'<b>{e(hl)}</b>', 1)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--analysis', required=True)
    ap.add_argument('--stats', required=True)
    ap.add_argument('--messages', required=True)
    ap.add_argument('--config')
    ap.add_argument('--out', default='out')
    ap.add_argument('--mode', default='full', choices=['full', 'public'])
    ap.add_argument('--history', default='history')
    ap.add_argument('--no-png', action='store_true')
    ap.add_argument('--no-history', action='store_true')
    a = ap.parse_args()

    cfg = json.loads(Path(a.config).read_text('utf-8')) if a.config else {}
    A = json.loads(Path(a.analysis).read_text('utf-8'))
    S = json.loads(Path(a.stats).read_text('utf-8'))
    msgs = {m['id']: m for m in json.loads(Path(a.messages).read_text('utf-8'))['messages']}

    if a.mode == 'public':
        f, _ = anonymizer(cfg, S['ranking'])
    else:
        f = lambda s: s
    A = deep(A, f)
    msgs = {k: deep(v, f) for k, v in msgs.items()}
    ranking = [(f(n), c) for n, c in S['ranking']]
    link_by_sender = [(f(n), c) for n, c in S['link_by_sender']]

    # 话题排序与编号
    def topic_meta(t):
        ms = [msgs[i] for i in t['msg_ids'] if i in msgs]
        ppl = []
        for m in ms:
            if m['sender'] not in ppl:
                ppl.append(m['sender'])
        cnt = {}
        for m in ms:
            cnt[m['sender']] = cnt.get(m['sender'], 0) + 1
        ppl.sort(key=lambda p: -cnt[p])
        heat = len(ms) * (1 + 0.3 * len(ppl))
        return {'n': len(ms), 'ppl': ppl, 'start': min(hm(m['time']) for m in ms), 'end': max(hm(m['time']) for m in ms), 'heat': heat}

    for t in A['topics']:
        t['_m'] = topic_meta(t)
    expanded = sorted([t for t in A['topics'] if t.get('expanded', True)], key=lambda t: -t['_m']['heat'])
    minor = [t for t in A['topics'] if not t.get('expanded', True)]
    tlabel = {t['id']: f'话题 {i}' for i, t in enumerate(expanded, 1)}
    for t in minor:
        tlabel[t['id']] = '零散讨论'

    def src_label(s):
        if s in tlabel:
            return tlabel[s]
        if s.startswith('tip'):
            return '干货沉淀'
        if s.startswith('Q'):
            return '待解决问题'
        return s

    group = cfg.get('group_name', '群聊')
    d = datetime.strptime(S['date'], '%Y-%m-%d')
    prev = S.get('prev') or {}
    H = []
    w = H.append
    w(f'<div class="meta">{d:%Y.%m.%d} 周{WEEK[d.weekday()]} · 统计时段 {S["time_range"][0]} 至 {S["time_range"][1]}</div>')
    w(f'<h1>{e(group)}<br><span>{e(cfg.get("title_suffix", "今日群聊日报"))}</span></h1>')
    w(f'<div class="lead">{bold(A["lead"], A.get("lead_highlight"))}</div>')
    w('<div class="stats">')
    for val, lab, key, pct in [(S['messages'], '消息', 'messages', True), (S['speakers'], '发言人', 'speakers', False),
                               (len(expanded) + len(minor), '话题', 'topics', False), (S['links'], '链接', 'links', False)]:
        w(f'<div class="stat"><b>{val}</b><i>{lab}</i>{delta(val, prev.get(key), pct) if prev else ""}</div>')
    w('</div>')

    # 今日要点
    w('<div class="sec"><div class="sec-h">今日要点<small>只看这三条也够了</small></div><div class="card">')
    for i, k in enumerate(A['key_points'], 1):
        w(f'<div class="key"><div class="n">{i}</div><div>{bold(k["text"], k.get("highlight"))}</div></div>')
    w('</div></div>')

    # 行动项
    if a.mode == 'full' and A['actions'] and cfg.get('show_actions', True):
        w('<div class="sec"><div class="sec-h">可以动手的事<small>从群聊里挖出来的机会</small></div><div class="act-wrap">')
        for ac in sorted(A['actions'], key=lambda x: -x['priority']):
            stars = '<b>' + '★' * ac['priority'] + '</b>' + '☆' * (3 - ac['priority'])
            srcs = '、'.join(dict.fromkeys(src_label(s) for s in ac['source']))
            w(f'<div class="act"><div class="top"><span class="atype {ACT_CLASS[ac["type"]]}">{e(ac["type"])}</span><span class="pri">优先级 {stars}</span></div>'
              f'<h4>{e(ac["title"])}</h4>'
              f'<div class="ln"><span>信号</span><div>{e(ac["signal"])}</div></div>'
              f'<div class="ln"><span>第一步</span><div>{e(ac["first_step"])}</div></div>'
              f'<div class="chips"><i>难度 {e(ac["difficulty"])}</i><i>{e(ac["effort"])}</i><i>来源 {e(srcs)}</i></div></div>')
        w('</div></div>')

    # 活跃榜
    top_n = cfg.get('ranking_top', 7)
    top = ranking[:top_n]
    rest = ranking[top_n:]
    mx = max([c for _, c in top] + [sum(c for _, c in rest)] + [1])
    w('<div class="sec"><div class="sec-h">活跃榜<small>按发言条数</small></div><div class="card">')
    for n, c in top:
        w(f'<div class="bar"><span>{e(n)}</span><div class="t"><div style="width:{c / top[0][1] * 100:.0f}%"></div></div><span class="v">{c}</span></div>')
    if rest:
        rc = sum(c for _, c in rest)
        w(f'<div class="bar"><span>其余 {len(rest)} 人</span><div class="t"><div style="width:{min(rc / top[0][1], 1) * 100:.0f}%;background:#b9c7e3"></div></div><span class="v">{rc}</span></div>')
    qc, ac_ = {}, {}
    for i in A['roles'].get('questions', []):
        if i in msgs:
            qc[msgs[i]['sender']] = qc.get(msgs[i]['sender'], 0) + 1
    for i in A['roles'].get('answers', []):
        if i in msgs:
            ac_[msgs[i]['sender']] = ac_.get(msgs[i]['sender'], 0) + 1
    roles = []
    if qc:
        n, c = max(qc.items(), key=lambda x: x[1]); roles.append(('提问最多', n, f'{c} 个问题'))
    if ac_:
        n, c = max(ac_.items(), key=lambda x: x[1]); roles.append(('答疑最多', n, f'回答 {c} 次'))
    if link_by_sender:
        n, c = link_by_sender[0]; roles.append(('分享最多', n, f'{c} 个链接'))
    if roles:
        w('<div class="roles">' + ''.join(f'<div class="role">{r}<b>{e(n)}</b>{x}</div>' for r, n, x in roles) + '</div>')
    w('</div></div>')

    # 话题详情
    w(f'<div class="sec"><div class="sec-h">话题详情<small>共 {len(expanded) + len(minor)} 个，按热度排序</small></div>')
    for t in expanded:
        m = t['_m']
        ppl = '、'.join(m['ppl'][:3]) + (f' 等 {len(m["ppl"])} 人' if len(m['ppl']) > 3 else '')
        tags = f'<span class="tag {TYPE_CLASS.get(t["type"], "t-news")}">{e(t["type"])}</span>'
        for extra in t.get('extra_tags', []):
            tags += f'<span class="tag {TYPE_CLASS.get(extra, "t-news")}">{e(extra)}</span>'
        w(f'<div class="topic"><div class="tags">{tags}<span class="st {STATUS_CLASS.get(t["status"], "s-none")}">{e(t["status"])}</span></div>'
          f'<h3>{e(t["title"])}</h3><div class="who">{m["start"]} 至 {m["end"]} · {m["n"]} 条 · {e(ppl)}</div><ul>')
        for b in t['bullets']:
            tag = '<span class="src-tag">原文</span>' if b.get('from_link') else ''
            w(f'<li>{bold(b["text"], b.get("highlight"))}{tag}</li>')
        w('</ul>')
        if t.get('disagreement'):
            w(f'<div class="diff"><b>分歧点</b> {e(t["disagreement"])}</div>')
        if t.get('comment'):
            w(f'<div class="comment"><b>点评</b> {e(t["comment"])}</div>')
        w('</div>')
    if minor:
        n = sum(t['_m']['n'] for t in minor)
        names = '、'.join(t['title'] for t in minor)
        w(f'<div class="topic" style="padding:12px 16px"><div class="tags"><span class="tag t-news">其他零散讨论</span></div>'
          f'<div style="margin-top:6px;font-size:12.5px;color:var(--sub)">{e(names)}，共 {len(minor)} 个话题 {n} 条，未展开。</div></div>')
    w('</div>')

    # 干货
    if A['tips']:
        w('<div class="sec"><div class="sec-h">干货沉淀<small>脱离上下文也能直接用</small></div><div class="card">')
        for tp in A['tips']:
            refs = [msgs[r] for r in tp.get('refs', []) if r in msgs]
            who = refs[0]['sender'] if refs else ''
            tm = hm(refs[0]['time']) if refs else ''
            src = '链接原文' if tp.get('source') == '链接' else f'来自 {e(who)} · {tm}'
            cred = f' · {e(tp["credibility"])}'
            body = e(tp['body'])
            if tp.get('verbatim'):
                body += f'<div style="margin-top:4px"><code>{e(tp["verbatim"])}</code></div>'
            w(f'<div class="tip"><div class="h">{e(tp["title"])}</div><div>{body}</div><div class="s">{src}{cred}</div></div>')
        w('</div></div>')

    # 待解决
    if A['open_questions']:
        w('<div class="sec"><div class="sec-h">待解决问题<small>有人问，暂时没人答</small></div><div class="card">')
        for q in sorted(A['open_questions'], key=lambda x: -x.get('followers', 0)):
            m = msgs[q['msg_id']]
            fol = f'<div class="s" style="font-size:11px;color:var(--sub)">另有 {q["followers"]} 人跟问</div>' if q.get('followers') else ''
            w(f'<div class="q"><span class="who2">{e(m["sender"])}<br>{hm(m["time"])}</span><span>{e(q["text"])}{fol}</span></div>')
        w('</div></div>')

    # 金句
    if A['quotes'] and cfg.get('show_quotes', True):
        w('<div class="sec"><div class="sec-h">今日金句</div>')
        for qt in A['quotes']:
            m = msgs[qt['msg_id']]
            tag = '<em class="qt">整理自</em> ' if qt.get('paraphrased') else ''
            w(f'<div class="quote"><p>{tag}{e(qt["text"])}</p>'
              f'<span>{e(m["sender"])} · {hm(m["time"])}</span></div>')
        w('</div>')

    # 链接
    notes = {l['url']: l for l in A['links']}
    ll = S['link_list']
    shown = ll[:cfg.get('max_links_shown', 8)]
    if ll:
        more = f'共 {len(ll)} 条，展示前 {len(shown)} 条' if len(shown) < len(ll) else f'共 {len(ll)} 条'
        w(f'<div class="sec"><div class="sec-h">链接清单<small>{more}</small></div><div class="card">')
        for L in shown:
            n = notes.get(L['url'], {})
            rc, rt = READ_CLASS.get(n.get('read', '未尝试'), ('', ''))
            badge = f'<span class="rl {rc}">{rt}</span>' if rt else ''
            title = n.get('title') or L['domain']
            u = L['url'] if len(L['url']) <= 60 else L['url'][:57] + '…'
            note = f'<div>{e(n["note"])}</div>' if n.get('note') else ''
            w(f'<div class="link"><div class="row"><span class="lt">{e(L["type"])}</span><b>{e(title)}</b>{badge}</div>{note}'
              f'<div style="font-size:11px;color:var(--sub)">{e(f(L["sender"]))} · {L["time"]}</div><div class="u">{e(u)}</div></div>')
        w('</div></div>')

    brand = cfg.get('brand', '')
    w(f'<div class="foot">以上内容由 AI 根据群聊记录自动整理，点评部分为 AI 观点<br>已过滤表情、撤回与系统消息 {S["noise_filtered"]} 条'
      + (f' · {e(brand)}' if brand else '') + '</div>')

    css = (HERE.parent / 'assets' / 'digest.css').read_text('utf-8')
    for k, v in (cfg.get('theme') or {}).items():
        css = re.sub(rf'--{k}:[^;}}]+', f'--{k}:{v}', css, count=1)
    page = (f'<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(group)} {S["date"]} 日报</title><style>{css}</style></head><body>' + '\n'.join(H) + '</body></html>')

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f'{S["date"]}_{"日报" if a.mode == "full" else "群内版"}'
    hp = out / f'{stem}.html'
    hp.write_text(page, 'utf-8')
    print('HTML', hp)

    if not a.no_png:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print('未安装 playwright，跳过 PNG。安装方法见 SKILL.md')
        else:
            with sync_playwright() as p:
                b = p.chromium.launch()
                pg = b.new_page(viewport={'width': 480, 'height': 900}, device_scale_factor=cfg.get('png_scale', 2))
                pg.goto(hp.resolve().as_uri())
                pg.wait_for_timeout(400)
                pp = out / f'{stem}.png'
                pg.screenshot(path=str(pp), full_page=True)
                b.close()
            print('PNG ', pp)

    if not a.no_history and a.mode == 'full':
        hist = Path(a.history) / f'{cfg.get("group_id", "default")}.jsonl'
        hist.parent.mkdir(parents=True, exist_ok=True)
        rows = [json.loads(l) for l in hist.read_text('utf-8').splitlines() if l.strip()] if hist.exists() else []
        rows = [r for r in rows if r['date'] != S['date']]
        rows.append({'date': S['date'], 'messages': S['messages'], 'speakers': S['speakers'], 'links': S['links'],
                     'topics': len(expanded) + len(minor),
                     'topic_titles': [t['title'] for t in expanded],
                     'open_questions': [q['text'] for q in A['open_questions']],
                     'actions': [ac['title'] for ac in A['actions']]})
        rows.sort(key=lambda r: r['date'])
        hist.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', 'utf-8')
        print('历史记录已更新', hist)


if __name__ == '__main__':
    main()
