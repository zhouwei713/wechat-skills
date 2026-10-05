"""公共工具：链接规范化、读写 JSON、字段定义。"""
import json, re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

HERE = Path(__file__).resolve().parent
FIELDS_PATH = HERE.parent / 'references' / 'fields.json'
URL_RE = re.compile(r'https?://[^\s<>"\'「」【】，。；！？）)]+')

WX_KEEP = ('__biz', 'mid', 'idx', 'sn')
DROP_PREFIX = ('utm_', 'spm', 'from', 'share', 'scene', 'chksm', 'sessionid', 'xsec', 'clicktime', 'enterid', 'ascene', 'devicetype', 'version', 'pass_ticket', 'wx_header', 'exportkey', 'nettype', 'lang', 'abtest', 'poc_token', 'sharer', 'mpshare', 'srcid', 'key')


def norm_url(u):
    """同一篇文章不同分享渠道的链接规范化成同一个，用来去重。"""
    if not u:
        return ''
    u = u.strip().rstrip('.,;')
    try:
        s = urlsplit(u)
    except Exception:
        return u
    host = s.netloc.lower()
    if host.endswith('mp.weixin.qq.com'):
        if s.path.startswith('/s/') and len(s.path) > 3:
            return f'https://mp.weixin.qq.com{s.path.rstrip("/")}'
        q = dict(parse_qsl(s.query))
        kept = [(k, q[k]) for k in WX_KEEP if k in q]
        return urlunsplit(('https', 'mp.weixin.qq.com', '/s', urlencode(kept), ''))
    q = [(k, v) for k, v in parse_qsl(s.query) if not k.lower().startswith(DROP_PREFIX)]
    return urlunsplit((s.scheme or 'https', host, s.path.rstrip('/'), urlencode(q), ''))


def load(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    return json.loads(p.read_text('utf-8'))


def save(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), 'utf-8')


def fields_def():
    return load(FIELDS_PATH)


def field_link_value(v):
    """多维表格里的超链接字段可能是字符串，也可能是 {link,text} 或列表。"""
    if isinstance(v, dict):
        return v.get('link') or v.get('url') or v.get('text') or ''
    if isinstance(v, list) and v:
        return field_link_value(v[0])
    return v or ''


def field_text_value(v):
    if isinstance(v, list):
        return ''.join(field_text_value(x) for x in v)
    if isinstance(v, dict):
        return v.get('text') or v.get('name') or ''
    return '' if v is None else str(v)
