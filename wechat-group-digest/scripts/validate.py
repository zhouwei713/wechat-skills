#!/usr/bin/env python3
"""校验模型写的 analysis.json。出现 ERROR 时退出码为 1，需要回去改对应板块再跑。

检查内容
  结构与枚举值、引用编号是否真实存在、金句和原文提示词是否逐字出自原消息、
  行动项来源能否找到、导语里的数字是否与统计一致、用户禁用的写法。

用法
  python validate.py work/analysis.json --messages work/messages.json --stats work/stats.json [--config config.json]
"""
import argparse, json, re, sys
from pathlib import Path

TOPIC_TYPES = {'工具测评', '求助答疑', '行业消息', '经验分享', '争论', '闲聊', '资源分享', '活动通知'}
TOPIC_STATUS = {'已解决', '有共识', '还在争', '没人回', '已沉淀', '简单提及'}
CRED = {'已验证', '待验证', '推测'}
ACT_TYPES = {'写文章', '做工具', '做Skill', '做内容', '马上试'}
DIFF = {'低', '中', '高'}
READ = {'已读取', '仅标题', '未读取', '未尝试'}
DEFAULT_BANS = ['——', '—', '不是[^。！？\n]{0,30}而是']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('analysis')
    ap.add_argument('--messages', required=True)
    ap.add_argument('--stats', required=True)
    ap.add_argument('--config')
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text('utf-8')) if a.config else {}
    A = json.loads(Path(a.analysis).read_text('utf-8'))
    msgs = {m['id']: m for m in json.loads(Path(a.messages).read_text('utf-8'))['messages']}
    S = json.loads(Path(a.stats).read_text('utf-8'))
    errs, warns = [], []
    E = errs.append
    W = warns.append

    def chk_ids(ids, where):
        for i in ids or []:
            if i not in msgs:
                E(f'{where} 引用了不存在的消息 #{i}')

    for k in ['lead', 'key_points', 'topics', 'tips', 'open_questions', 'actions', 'quotes', 'links', 'roles']:
        if k not in A:
            E(f'缺少字段 {k}')
    if errs:
        report(errs, warns)

    # 导语与要点
    lead = A['lead']
    if len(lead) > cfg.get('lead_max_chars', 140):
        W(f'导语 {len(lead)} 字，建议 120 字以内')
    if len(A['key_points']) != 3:
        E(f'今日要点需要正好 3 条，现在 {len(A["key_points"])} 条')

    tids = {t['id'] for t in A['topics']}
    aids = {f'A{i+1}' for i in range(len(A['actions']))}
    for i, kp in enumerate(A['key_points'], 1):
        for s in kp.get('source', []):
            if s not in tids and s not in aids:
                E(f'要点 {i} 的来源 {s} 不存在（应为话题 id 如 T1 或行动项 id 如 A1）')

    # 话题
    seen = {}
    for t in A['topics']:
        w = f'话题 {t.get("id")}'
        if t.get('type') not in TOPIC_TYPES:
            E(f'{w} 类型 {t.get("type")} 不在 {sorted(TOPIC_TYPES)}')
        if t.get('status') not in TOPIC_STATUS:
            E(f'{w} 状态 {t.get("status")} 不在 {sorted(TOPIC_STATUS)}')
        if not t.get('msg_ids'):
            E(f'{w} 没有 msg_ids')
        chk_ids(t.get('msg_ids'), w)
        for i in t.get('msg_ids', []):
            if i in seen and t.get('expanded', True):
                W(f'消息 #{i} 同时出现在 {seen[i]} 和 {t["id"]}')
            seen[i] = t['id']
        for b in t.get('bullets', []):
            if not b.get('refs'):
                E(f'{w} 的要点没有 refs：{b.get("text","")[:20]}')
            chk_ids(b.get('refs'), w)
            if b.get('highlight') and b['highlight'] not in b['text']:
                E(f'{w} 的 highlight 不是该要点原文的一部分：{b["highlight"]}')
        if t.get('expanded', True) and not t.get('bullets'):
            E(f'{w} 是展开话题但没有 bullets')
    exp = [t for t in A['topics'] if t.get('expanded', True)]
    if len(exp) > cfg.get('max_topics', 7):
        W(f'展开话题 {len(exp)} 个，超过上限 {cfg.get("max_topics", 7)}')

    # 角色
    chk_ids(A['roles'].get('questions'), 'roles.questions')
    chk_ids(A['roles'].get('answers'), 'roles.answers')

    # 干货
    for i, tp in enumerate(A['tips'], 1):
        w = f'干货 {i}'
        if tp.get('credibility') not in CRED:
            E(f'{w} 可信度应为 {sorted(CRED)}')
        chk_ids(tp.get('refs'), w)
        v = tp.get('verbatim')
        if v and tp.get('source', '群友') == '群友':
            if not any(v in msgs[r]['content'] for r in tp.get('refs', []) if r in msgs):
                E(f'{w} 的 verbatim 必须逐字出自引用的消息：{v[:30]}')

    # 待解决
    for q in A['open_questions']:
        chk_ids([q.get('msg_id')], '待解决问题')

    # 行动项
    if len(A['actions']) > cfg.get('max_actions', 5):
        E(f'行动项最多 {cfg.get("max_actions", 5)} 条')
    tip_ids = {f'tip{i+1}' for i in range(len(A['tips']))}
    q_ids = {f'Q{i+1}' for i in range(len(A['open_questions']))}
    for i, ac in enumerate(A['actions'], 1):
        w = f'行动项 A{i}'
        if ac.get('type') not in ACT_TYPES:
            E(f'{w} 类型应为 {sorted(ACT_TYPES)}')
        if ac.get('difficulty') not in DIFF:
            E(f'{w} 难度应为 低/中/高')
        if ac.get('priority') not in (1, 2, 3):
            E(f'{w} priority 应为 1 到 3')
        for k in ('title', 'signal', 'first_step', 'effort'):
            if not ac.get(k):
                E(f'{w} 缺少 {k}')
        src = ac.get('source', [])
        if not src:
            E(f'{w} 没有来源')
        for s in src:
            if s not in tids | tip_ids | q_ids:
                E(f'{w} 来源 {s} 不存在（可用 T1/tip1/Q1 这类 id）')

    # 金句
    if len(A['quotes']) > 1:
        W(f'金句有 {len(A["quotes"])} 条，强烈建议只留 1 条（辨识度是稀缺资源，多条会互相稀释）')
    # 伪金句特征：提问、求助、操作指令、打气，都是别的板块的内容
    FAKE_QUOTE = [
        (r'怎么(办|做|弄|样|搞)|有没有|能不能|可不可以|用什么|用哪个|求助|请问', '是在求助，属于待解决问题板块'),
        (r'安装|部署|下载|配置|命令|脚本|点击|输入|打开|运行|导入|导出|粘贴|一键|帮你|可以直接|建议|推荐',
         '是操作指令或建议，属于干货沉淀板块'),
        (r'^[!！~。\s]*(加油|感谢|谢谢|恭喜|冲鸭|码住|学习了|收到)[!！~。\s]*$', '是水消息'),
    ]
    for qt in A['quotes']:
        m = msgs.get(qt.get('msg_id'))
        if not m:
            E(f'金句引用了不存在的消息 #{qt.get("msg_id")}'); continue
        text = qt['text']
        if len(text) > 40:
            E(f'金句 {len(text)} 字，太长了：金句的敌人是长句，砍到 20 字以内：{text[:20]}')
        elif len(text) > 20:
            W(f'金句 {len(text)} 字，建议压到 20 字内才记得住：{text[:20]}')
        if text.endswith(('？', '?')) or re.search(r'(吗|呢|吧)[？?]?$', text):
            E(f'金句 #{m["id"]} 是疑问句，疑问句是抱怨不是金句：{text[:24]}')
        para = qt.get('paraphrased', False)
        if not para and text not in m['content']:
            E(f'金句未逐字出自原消息 #{m["id"]}，若确为整理请标 paraphrased: true：{text[:30]}')
        for pat, why in FAKE_QUOTE:
            if re.search(pat, text):
                E(f'金句 #{m["id"]} {why}：{text[:30]}')
        if para:
            # 整理版必须基于该发言人的原话，避免张冠李戴
            src = m['content']
            segs = re.findall(r'[\w一-鿿]{2,}', text)
            if not any(s in src for s in segs):
                W(f'金句 #{m["id"]} 标了 paraphrased，但和{m["sender"]}的原话没有重合，确认没有张冠李戴：{text[:24]}')
    if not A['quotes']:
        print('提示  今天没有金句，页面会整块跳过。这是常态，不算问题。')

    # 链接
    keys = {l['url'] for l in S['link_list']}
    for l in A['links']:
        if l.get('url') not in keys:
            E(f'链接不在统计结果里：{l.get("url")}')
        if l.get('read') not in READ:
            E(f'链接读取状态应为 {sorted(READ)}')
    if len(A['links']) < len(keys):
        W(f'有 {len(keys) - len(A["links"])} 个链接没有写说明，渲染时会只显示域名')

    # 数字核对
    text_all = lead + ' '.join(k['text'] for k in A['key_points'])
    for num, unit in re.findall(r'(\d+)\s*(条消息|人发言|位群友发言|个链接)', text_all):
        real = {'条消息': S['messages'], '人发言': S['speakers'], '位群友发言': S['speakers'], '个链接': S['links']}[unit]
        if int(num) != real:
            E(f'导语或要点里写了 {num}{unit}，统计结果是 {real}')

    # 写法禁忌
    bans = cfg.get('style_bans', DEFAULT_BANS)
    def walk(o, path):
        if isinstance(o, str):
            for b in bans:
                if re.search(b, o):
                    E(f'{path} 出现了禁用写法 /{b}/：{o[:40]}')
        elif isinstance(o, list):
            for i, x in enumerate(o):
                walk(x, f'{path}[{i}]')
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in ('verbatim', 'url', 'quotes'):
                    continue
                walk(v, f'{path}.{k}')
    walk({k: v for k, v in A.items() if k != 'quotes'}, 'analysis')

    report(errs, warns)


def report(errs, warns):
    for w in warns:
        print('WARN ', w)
    for e in errs:
        print('ERROR', e)
    if errs:
        print(f'\n校验未通过，{len(errs)} 个错误')
        sys.exit(1)
    print(f'校验通过（{len(warns)} 个提醒）')
    sys.exit(0)


if __name__ == '__main__':
    main()
