#!/usr/bin/env python3
"""把各种格式的微信群聊记录解析成统一的 messages.json。

支持的输入
  A. 两行式 txt   "2026-10-03 12:10:05 阿杰" 下一行起是内容（留痕/WeChatMsg 等导出）
  B. 两行式 txt   "阿杰 2026-10-03 12:10:05" 或 "阿杰  12:10"
  C. 单行式 txt   "[2026-10-03 12:10] 阿杰: 内容" / "12:10 阿杰：内容" / "阿杰：内容"
  D. JSON         列表，字段名自动识别 time/sender/content/type
  E. CSV          有表头，字段名自动识别

用法
  python parse_chat.py 输入文件 -o work/messages.json [--date 2026-10-03] [--config config.json]
解析失败时会给出提示，此时请按 references/data_schema.md 手动整理成 messages.json。
"""
import argparse, csv, json, re, sys
from datetime import datetime, date as Date
from pathlib import Path

URL_RE = re.compile(r'https?://[^\s<>"\'「」【】，。；！？）)]+')
DT = r'(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)\s+(\d{1,2}:\d{2}(?::\d{2})?)'
HM = r'(\d{1,2}:\d{2}(?::\d{2})?)'

DT_LINE = re.compile(rf'^{DT}\s*$')               # 只有日期时间，发言人写在上一行
NAME_LINE = re.compile(r'^·.{1,30}$|^\S.{0,29}$')

HDR_A = re.compile(rf'^{DT}\s+(.+?)\s*$')                 # 时间 发言人
HDR_B = re.compile(rf'^(.+?)\s+{DT}\s*$')                 # 发言人 时间
HDR_B2 = re.compile(rf'^(.{{1,30}}?)\s+{HM}\s*$')          # 发言人 时:分
ONE_A = re.compile(rf'^\[?{DT}\]?\s+([^:：]{{1,30}}?)\s*[:：]\s?(.*)$')
ONE_B = re.compile(rf'^\[?{HM}\]?\s+([^:：]{{1,30}}?)\s*[:：]\s?(.*)$')
ONE_C = re.compile(r'^([^\s:：\[\]]{1,20})\s*[:：]\s?(.+)$')

QUOTE_RE = re.compile(r'「([^「」]{1,40}?)[：:]([\s\S]*?)」')
DASH_LINE = re.compile(r'^\s*(-\s*){3,}\s*$', re.M)

TYPE_MARKERS = [
    ('image', ['[图片]', '[Image]', '[照片]']),
    ('video', ['[视频]', '[Video]']),
    ('voice', ['[语音]', '[Voice]']),
    ('emoji', ['[动画表情]', '[表情]', '[Sticker]']),
    ('file', ['[文件]', '[File]']),
    ('card', ['[链接]', '[分享]', '[小程序]', '[视频号]', '[公众号]', '[卡片式链接]', '[Link]']),
]
SYSTEM_PAT = re.compile(r'(加入了群聊|邀请.*加入|修改群名|移出了群聊|拍了拍|开启了朋友验证|成为新群主|群公告|以上是打招呼的内容|You recalled)')
RECALL_PAT = re.compile(r'撤回了一条消息')
ACKS = {'收到', '好的', '好', '嗯', '嗯嗯', '哈哈', '哈哈哈', '哈哈哈哈', '+1', '1', '666', '6', '赞', '牛', '牛啊', '厉害',
        '谢谢', '感谢', '多谢', 'ok', 'okk', '👍', '学习了', '学到了', 'mark', '码住', '同问', '确实', '是的', '对', '对的', '哦', '噢'}


def norm_date(s):
    s = re.sub(r'[年月/.]', '-', s).rstrip('日')
    y, m, d = s.split('-')[:3]
    return f'{int(y):04d}-{int(m):02d}-{int(d):02d}'


def norm_time(t):
    p = t.split(':')
    return f'{int(p[0]):02d}:{int(p[1]):02d}:{int(p[2]) if len(p) > 2 else 0:02d}'


def parse_txt(text, default_date):
    lines = text.splitlines()
    msgs = []
    # 三行式：发言人单独一行，下一行只有日期时间，再下一行起是内容（部分导出工具的默认格式）
    dt_lines = sum(1 for l in lines if DT_LINE.match(l.strip()))
    blank_run = [i for i, l in enumerate(lines) if not l.strip()]
    if dt_lines >= 3:
        cur = None
        pending = None
        for l in lines:
            s = l.strip()
            if DT_LINE.match(s):
                m = DT_LINE.match(s)
                name = pending if pending else '未知发言人'
                pending = None
                cur = {'date': norm_date(m.group(1)), 'time': norm_time(m.group(2)),
                       'sender': name.strip(), 'lines': []}
                msgs.append(cur)
                continue
            if not s:
                continue
            if cur is None or cur['lines']:
                # 内容之后又出现的短行 = 下一个发言人
                if len(s) <= 30 and not s.startswith(('[', 'http')):
                    pending = s
                elif cur is not None:
                    cur['lines'].append(l)
            else:
                cur['lines'].append(l)
        if msgs:
            return [(m['date'], m['time'], m['sender'], '\n'.join(m['lines']).strip()) for m in msgs]
    # 先判断是否为两行式：统计头部行数量
    heads = sum(1 for l in lines if HDR_A.match(l) or HDR_B.match(l))
    if heads >= 3 and heads >= len([l for l in lines if l.strip()]) * 0.15:
        cur = None
        for l in lines:
            m = HDR_A.match(l)
            if m:
                cur = {'date': norm_date(m.group(1)), 'time': norm_time(m.group(2)), 'sender': m.group(3).strip(), 'lines': []}
                msgs.append(cur); continue
            m = HDR_B.match(l)
            if m:
                cur = {'date': norm_date(m.group(2)), 'time': norm_time(m.group(3)), 'sender': m.group(1).strip(), 'lines': []}
                msgs.append(cur); continue
            if cur is not None:
                cur['lines'].append(l)
        return [(m['date'], m['time'], m['sender'], '\n'.join(m['lines']).strip()) for m in msgs]
    # 单行式（允许内容续行）。有时间戳的行足够多时，只认带时间戳的行，避免把"第一步：xxx"误判成发言人
    timed = sum(1 for l in lines if ONE_A.match(l) or ONE_B.match(l) or HDR_B2.match(l))
    allow_untimed = timed < 3
    last = None
    out = []
    for l in lines:
        if not l.strip():
            continue
        m = ONE_A.match(l)
        if m:
            last = [norm_date(m.group(1)), norm_time(m.group(2)), m.group(3).strip(), m.group(4)]
            out.append(last); continue
        m = ONE_B.match(l)
        if m:
            last = [default_date, norm_time(m.group(1)), m.group(2).strip(), m.group(3)]
            out.append(last); continue
        m = HDR_B2.match(l)
        if m:
            last = [default_date, norm_time(m.group(2)), m.group(1).strip(), '']
            out.append(last); continue
        if allow_untimed:
            m = ONE_C.match(l)
            if m:
                t = last[1] if last else '00:00:00'
                last = [default_date, t, m.group(1).strip(), m.group(2)]
                out.append(last); continue
        if last is not None:
            last[3] = (last[3] + '\n' + l).strip()
    return [tuple(x) for x in out]


def pick(d, keys):
    for k in keys:
        for kk in d:
            if kk.lower() == k:
                return d[kk]
    return None


def parse_records(rows, default_date):
    out = []
    for r in rows:
        t = pick(r, ['time', 'timestamp', 'createtime', 'create_time', 'datetime', 'date', 'strtime', '时间'])
        s = pick(r, ['sender', 'talker', 'nickname', 'name', 'from', 'remark', 'displayname', '发送人', '发言人', '昵称'])
        c = pick(r, ['content', 'msg', 'text', 'message', 'strcontent', '内容'])
        ty = pick(r, ['type', 'msgtype', 'type_name', '类型'])
        if t is None or s is None:
            continue
        if isinstance(t, (int, float)) or (isinstance(t, str) and t.isdigit()):
            ts = float(t); ts = ts / 1000 if ts > 1e11 else ts
            dt = datetime.fromtimestamp(ts)
            d, tm = dt.strftime('%Y-%m-%d'), dt.strftime('%H:%M:%S')
        else:
            m = re.search(DT, str(t))
            if m:
                d, tm = norm_date(m.group(1)), norm_time(m.group(2))
            else:
                m = re.search(HM, str(t))
                if not m:
                    continue
                d, tm = default_date, norm_time(m.group(1))
        c = '' if c is None else str(c)
        if ty and str(ty) in ('图片', 'image', '3') and not c:
            c = '[图片]'
        out.append((d, tm, str(s).strip(), c.strip()))
    return out


def classify(content):
    c = content.strip()
    if RECALL_PAT.search(c):
        return 'recall'
    if SYSTEM_PAT.search(c) and len(c) < 80:
        return 'system'
    for ty, marks in TYPE_MARKERS:
        if any(c.startswith(m) for m in marks):
            return ty
    if c and URL_RE.fullmatch(c):
        return 'link'
    return 'text'


def is_noise(m):
    if m['type'] in ('system', 'recall', 'emoji'):
        return True
    if m['type'] != 'text':
        return False
    c = re.sub(r'\[[^\]]{1,6}\]', '', m['content'])          # 去掉 [捂脸] 这类表情码
    c = re.sub(r'[\s!！~～。.,，?？]+', '', c).lower()
    if not c:
        return True
    if c in ACKS:
        return True
    if re.fullmatch(r'(哈|呵|嘿|嘻|h|6)+', c):
        return True
    if not re.search(r'[\w一-鿿]', c):           # 纯表情符号
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('-o', '--output', default='work/messages.json')
    ap.add_argument('--date', help='只保留这一天，格式 YYYY-MM-DD；不传则保留最后一天')
    ap.add_argument('--all-days', action='store_true', help='保留全部日期（周报用）')
    ap.add_argument('--config')
    a = ap.parse_args()

    cfg = json.loads(Path(a.config).read_text('utf-8')) if a.config else {}
    aliases = cfg.get('aliases', {})
    ignore = set(cfg.get('ignore_senders', []))
    p = Path(a.input)
    raw = p.read_text('utf-8-sig', errors='replace')
    default_date = a.date or Date.today().isoformat()

    if p.suffix.lower() == '.json':
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get('messages') or data.get('data') or next((v for v in data.values() if isinstance(v, list)), [])
        rows = parse_records(data, default_date)
    elif p.suffix.lower() == '.csv':
        rows = parse_records(list(csv.DictReader(raw.splitlines())), default_date)
    else:
        rows = parse_txt(raw, default_date)

    if len(rows) < 3:
        sys.exit('解析出的消息少于 3 条，格式可能不受支持。请按 references/data_schema.md 手动整理成 messages.json。')

    days = sorted({r[0] for r in rows})
    if a.all_days:
        keep = set(days)
    else:
        target = a.date or days[-1]
        keep = {target}
    rows = [r for r in rows if r[0] in keep]
    rows.sort(key=lambda r: (r[0], r[1]))

    msgs = []
    for i, (d, t, s, c) in enumerate(rows, 1):
        s = aliases.get(s, s)
        pref = cfg.get('strip_name_prefix')
        if pref and s.startswith(pref):
            s = s[len(pref):].strip() or s
        if s in ignore:
            continue
        quote = None
        qm = QUOTE_RE.search(c)
        if qm:
            quote = {'sender': aliases.get(qm.group(1).strip(), qm.group(1).strip()), 'text': qm.group(2).strip()}
            c = (c[:qm.start()] + c[qm.end():])
            c = DASH_LINE.sub('', c).strip()
        m = {'id': len(msgs) + 1, 'date': d, 'time': t, 'sender': s, 'type': None, 'content': c,
             'quote': quote, 'reply_to': None, 'urls': [], 'noise': False}
        m['type'] = classify(c)
        m['urls'] = list(dict.fromkeys(u.rstrip('.,;') for u in URL_RE.findall(c)))
        if m['urls'] and m['type'] == 'text' and len(URL_RE.sub('', c).strip()) < 4:
            m['type'] = 'link'
        m['noise'] = is_noise(m)
        msgs.append(m)

    # 解析引用：在之前的消息里找该发言人且内容吻合的那条
    for m in msgs:
        q = m['quote']
        if not q:
            continue
        key = re.sub(r'\s+', '', q['text'])[:12]
        cand = [x for x in msgs[:m['id'] - 1] if x['sender'] == q['sender']]
        hit = next((x for x in reversed(cand) if key and key in re.sub(r'\s+', '', x['content'])), None)
        if hit is None and cand:
            hit = cand[-1]
        if hit:
            m['reply_to'] = hit['id']

    out = {'meta': {'source': p.name, 'dates': sorted(keep), 'parsed_at': datetime.now().isoformat(timespec='seconds'),
                    'count': len(msgs)}, 'messages': msgs}
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(out, ensure_ascii=False, indent=1), 'utf-8')
    types = {}
    for m in msgs:
        types[m['type']] = types.get(m['type'], 0) + 1
    print(f'解析完成 {len(msgs)} 条，日期 {", ".join(sorted(keep))}，类型分布 {types}')
    print(f'可选日期 {", ".join(days)}' if len(days) > 1 else '')


if __name__ == '__main__':
    main()
