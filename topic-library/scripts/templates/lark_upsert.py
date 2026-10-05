# -*- coding: utf-8 -*-
"""通过 lark-cli 写入飞书多维表格（可复用模板）。

这是 topic-library skill 自带的写入模板，**不要从零重写调用层**。复用方法：
  1. 复制到本次工作目录    cp <skill>/scripts/templates/lark_upsert.py work/_final.py
  2. 只改下面几个常量      CLI / NODE / BASE / TABLE（WORK 一般不用改）
  3. 在工作目录下运行      python work/_final.py

环境要求
  node 和 lark-cli 已安装，且 `lark-cli auth status` 显示 user 身份 ready。
  CLI 默认取 PATH 里的 lark-cli；Windows 上如果没在 PATH 里，用 `where lark-cli` 找到
  node_modules/@larksuite/cli/scripts/run.js 的绝对路径填进来。

三条硬经验（都写进 SKILL.md 7.1 了，都是静默失败——不报错、返回空或写错位置）：
  1. 不设 LARK_CLI_NO_PROXY —— 设了 CLI 输出不进 stdout，subprocess 读到空字符串
  2. @file 只认相对路径 —— 绝对路径（正斜杠也不行）静默返回空 stdout，必须 cwd=WORK
  3. 临时文件必须每条唯一名 —— 共用一个文件循环写，跑到一半会消失（报 cannot open JSON file）
另：不要用 +record-batch-create，它的 rows 数组会错位（传 5 行进去 5 行全写进第 1 列），
必须逐条 +record-upsert。
"""
import json
import os
import shutil
import subprocess
import sys
import time
import datetime

# ── 复用时改这里 ─────────────────────────────────────────────────
CLI = shutil.which('lark-cli') or 'lark-cli'     # 或填 @larksuite/cli/scripts/run.js 的绝对路径
NODE = shutil.which('node') or 'node'
BASE = '<your-base-token>'                        # 多维表格 base token
TABLE = '<your-table-id>'                         # 表 id
WORK = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
# ────────────────────────────────────────────────────────────

# 本次要用到的开放词表选项（每个不超过 50 个）。不建这些选项会报 800030005，整条记录写不进去。
# 超过 50 个值必须把该列建成 text 长文本，见 SKILL.md「修改字段」一节。
FIELDS = {
    "公众号": [],
    "选题簇": [],
}
# 长文本列：列表会合成一段文本再写。多选上限 50 会静默截断，所以这几列建成 text
LONG = {"大纲", "亮点", "空白", "可带走资产", "提到的工具", "钩子词"}
DATE = {"发布日期", "入库日期"}


def env_plain():
    """关键：把 LARK_CLI_NO_PROXY 摘掉。设了它 CLI 的 JSON 不进 stdout。"""
    e = dict(os.environ)
    e.pop('LARK_CLI_NO_PROXY', None)
    return e


def call(args, retries=3):
    p = None
    for k in range(retries):
        p = subprocess.run([NODE, CLI] + args, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', env=env_plain(),
                           cwd=WORK, timeout=90)
        for s in (p.stdout or '', (p.stdout or '') + '\n' + (p.stderr or '')):
            i = s.find('{')
            if i >= 0:
                try:
                    return json.loads(s[i:])
                except Exception:
                    continue
        time.sleep(1.0 + k)      # 空返回退避重试
    return {'ok': False, '_raw': (((p.stdout or '') + (p.stderr or '')) or 'EMPTY')[:250]}


def norm(k, v):
    """把 records.json 里的值转成多维表格能收的格式。"""
    if v in (None, '', []):
        return None
    if isinstance(v, dict) and 'link' in v:      # 链接列线上是 text，要拆成纯字符串
        return v['link']
    if k in LONG and isinstance(v, list):
        return '\n'.join(str(x) for x in v)
    if k in DATE and isinstance(v, (int, float)):
        return datetime.datetime.fromtimestamp(v / 1000).strftime('%Y-%m-%d %H:%M:%S')
    return v


def existing():
    d = call(['base', '+record-list', '--base-token', BASE, '--table-id', TABLE,
              '--as', 'user', '--limit', '200', '--format', 'json'])
    return list(dict.fromkeys((d.get('data') or {}).get('record_id_list') or []))


def clear():
    """清空表。--record-id 是 stringArray 要重复传，不能传逗号分隔字符串；一次最多 3 个。"""
    for _ in range(20):
        ids = existing()
        if not ids:
            break
        args = ['base', '+record-delete', '--base-token', BASE, '--table-id', TABLE,
                '--as', 'user', '--yes']
        for i in ids[:3]:
            args += ['--record-id', i]
        d = call(args)
        if not d.get('ok'):
            print('删失败:', str(d.get('error') or d.get('_raw'))[:150])
            break
        time.sleep(0.5)
    print('清空后剩余:', len(existing()))


def main():
    if BASE.startswith('<') or TABLE.startswith('<'):
        sys.exit('请先把 BASE / TABLE 改成你自己的 base token 和 table id')

    clear()

    # 逐条 upsert，每条独立临时文件
    ops = json.load(open(os.path.join(WORK, 'work/records.json'), encoding='utf-8'))['ops']
    real = {f['name'] for f in call(['base', '+field-list', '--base-token', BASE,
                                     '--table-id', TABLE, '--as', 'user'])['data']['fields']}
    done, fails = 0, []
    for n, op in enumerate(ops, 1):
        rf = {}
        for k, v in op['fields'].items():
            if k in real:                      # 只写线上真实存在的列
                nv = norm(k, v)
                if nv not in (None, '', []):
                    rf[k] = nv
        rel = f'work/_r{n:03d}.json'          # 相对路径 + cwd=WORK，坑 2
        ab = os.path.join(WORK, rel)
        with open(ab, 'w', encoding='utf-8') as f:
            json.dump(rf, f, ensure_ascii=False)
        if not os.path.exists(ab):
            print(f'  {n} 临时文件写失败')
            fails.append(((rf.get('标题') or '')[:30], 'no file'))
            continue
        d = call(['base', '+record-upsert', '--base-token', BASE, '--table-id', TABLE,
                  '--as', 'user', '--json', '@' + rel])
        if d.get('ok'):
            done += 1
        else:
            e = d.get('error') or {}
            fails.append(((rf.get('标题') or '')[:30], (e.get('message') or d.get('_raw') or '')[:120]))
            print(f'  FAIL {n}', (rf.get('标题') or '')[:22], '|', e.get('code'), e.get('message'))
        try:
            os.remove(ab)
        except Exception:
            pass
        if n % 10 == 0:
            print(f'  {n}/{len(ops)}  已写 {done}')
        time.sleep(0.25)

    print('写入合计:', done, '/', len(ops))
    print('表内实际:', len(existing()))
    for t, e in fails:
        print('  FAIL', t, '|', e)


if __name__ == '__main__':
    main()
