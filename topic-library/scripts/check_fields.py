#!/usr/bin/env python3
"""核对 references/fields.json 与线上多维表格的实际结构是否还对得上。

字段定义是文档声明的唯一来源，但飞书 API 有三处不支持字面类型（见 fields.json 的 _api注意），
所以定义和线上必然有差异。本脚本只报**不该有的**差异：字段缺失、多了字段、固定选项数对不上、
以及 api_type 声明与线上实际类型不符。

用法
  # 1. 先把线上字段列表存成 JSON（在选题库工作目录下跑）
  #    node <lark-cli>/scripts/run.js base +field-list \
  #      --base-token <base> --table-id <tbl> --as user --format json > work/_fields.json
  python check_fields.py work/_fields.json [--fields <fields.json>]

退出码 1 = 有不该有的差异。
"""
import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIELDS_PATH = HERE.parent / 'references' / 'fields.json'

# 线上返回的类型名 -> fields.json 里的 type
REMOTE2LOCAL = {
    'text': 'text', 'select': 'single_select', 'multiSelect': 'multi_select',
    'datetime': 'date', 'number': 'number', 'checkbox': 'checkbox', 'url': 'url',
    'longText': 'long_text', 'attachment': 'attachment',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('remote', help='线上 base +field-list 的 JSON 输出')
    ap.add_argument('--fields', default=str(FIELDS_PATH))
    a = ap.parse_args()

    F = json.loads(Path(a.fields).read_text('utf-8'))
    R = json.loads(Path(a.remote).read_text('utf-8'))
    if not R.get('ok'):
        sys.exit(f'线上返回不 ok：{str(R)[:200]}')
    remote = {f['name']: f for f in R['data']['fields']}
    local = {f['name']: f for f in F['fields']}

    errs, notes = [], []
    for name, lf in local.items():
        rf = remote.get(name)
        if not rf:
            errs.append(f'线上缺字段「{name}」（定义里的 type={lf["type"]}）')
            continue
        # api_type 声明了就以它为准（这几类字面类型 API 建不出来）
        want = lf.get('api_type') or lf['type']
        got_raw = rf['type']
        got = REMOTE2LOCAL.get(got_raw, got_raw)
        # 多选建出来 API 也返回 select，靠 multiple 区分，不算差异
        mult_ok = bool(rf.get('multiple')) == (lf['type'] == 'multi_select')
        if got != want and not (lf['type'] == 'multi_select' and got_raw == 'select' and mult_ok):
            errs.append(f'「{name}」线上是 {got_raw}，定义期望 {want}'
                        + (f'（api_type={lf["api_type"]}）' if lf.get('api_type') else ''))
        want_multi = lf['type'] == 'multi_select'
        if want_multi != bool(rf.get('multiple')):
            errs.append(f'「{name}」multiple={rf.get("multiple")}，定义期望 {want_multi}')
        if lf.get('vocab') == 'fixed':
            lo, ro = len(lf.get('options') or []), len(rf.get('options') or [])
            if lo != ro:
                diff = set(lf.get('options') or []) ^ {o['name'] for o in (rf.get('options') or [])}
                errs.append(f'「{name}」定义 {lo} 个选项，线上 {ro} 个，差异：{sorted(diff)}')
        elif lf.get('vocab') == 'open' and rf.get('options') is not None:
            n = len(rf.get('options') or [])
            # 只有还是单选/多选列时才需要盯上限；已经是 text 的不受 50 限制
            notes.append(f'「{name}」开放词表（{lf["type"]}），线上已存 {n} 项'
                         + ('（接近 50 上限，新值会被静默截断）' if n >= 45 else ''))

    for name in remote:
        if name not in local:
            notes.append(f'线上多出字段「{name}」，fields.json 里没有')

    for m in notes:
        print('提示 ', m)
    if errs:
        for m in errs:
            print('ERROR', m)
        sys.exit(f'\n字段定义与线上不一致，{len(errs)} 处')
    print(f'字段定义与线上结构一致（{len(local)} 个字段）')


if __name__ == '__main__':
    main()
