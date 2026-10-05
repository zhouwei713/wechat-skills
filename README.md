# wechat-skills

两个把微信生态里「没人愿意干的活」做成可重复流水线的 WorkBuddy Skill。

| Skill | 干什么 | 产物 |
|---|---|---|
| [`wechat-group-digest`](wechat-group-digest/) | 把微信群聊天记录变成一份能转发的长图日报 | HTML + 长图 PNG |
| [`topic-library`](topic-library/) | 把公众号文章拆成选题资料，检测撞题，写进飞书多维表格 | 选题表 + 撞题报告 |

两者可以串起来用：群日报脚本能直接把群里分享的文章喂给选题库。

---

## 为什么做这两个

**群聊日报**——每天几百条群消息，没人愿意看但又不能不看。人工翻一遍要半小时，翻完也记不住重点。
这个 skill 把「能数的交给脚本，要理解的交给模型」：消息数、发言人排名、链接清单由脚本算，
话题切分、要点提炼、机会判断交给模型，最后由脚本逐条校验模型的每一条输出。

**选题库**——转发一百篇对标文章容易，三个月后想不起写过什么、哪篇撞了哪篇才是真的难。
这个 skill 把每篇文章拆成 29 个字段（选题类型、赛道、时效、标题公式、可带走资产、空白、我的角度……），
并强制检查新选题簇是否和已有簇重复。

## 设计原则

两个 skill 都遵守同一条分工：**能数的交给脚本，要理解的交给模型，校验永远由脚本做。**

模型写的每一条内容都必须带上原消息编号或原文字段，由脚本校验器逐条比对。
所以模型偷懒、串台、张冠李戴都会在提交前被拦下来，而不是留在成品里。

## 安装

需要 [WorkBuddy](https://www.workbuddy.cn/) 环境。两个 skill 都是纯 Python（`topic-library` 额外用 Node 调飞书 CLI）。

```bash
git clone https://github.com/<your-account>/wechat-skills.git
cp -r wechat-skills/wechat-group-digest ~/.workbuddy/skills/
cp -r wechat-skills/topic-library ~/.workbuddy/skills/
```

`wechat-group-digest` 出 PNG 需要 playwright：

```bash
pip install playwright && python -m playwright install chromium
```

需要中文字体（Noto Sans CJK 或系统自带中文字体），否则长图会出现方框。

## 快速上手

### 群聊日报

```bash
SKILL=~/.workbuddy/skills/wechat-group-digest
mkdir -p /path/to/日报/2026-10-05/work /path/to/日报/2026-10-05/out
cp $SKILL/config.example.json /path/to/日报/config.json   # 改群名和 reader_profile

python $SKILL/scripts/parse_chat.py chat.txt -o work/messages.json --config ../config.json --all-days
python $SKILL/scripts/prepare.py work/messages.json --config ../config.json --history history
# 模型按 references/analysis_guide.md 写 work/analysis.json
python $SKILL/scripts/validate.py work/analysis.json --messages work/messages.json --stats work/stats.json --config ../config.json
python $SKILL/scripts/render.py --analysis work/analysis.json --stats work/stats.json \
  --messages work/messages.json --config ../config.json --out out --history history
```

`--all-days` 跨天记录必须加，否则只取最后一天。加 `--mode public` 出一版隐藏行动项的群内版。

### 选题库

```bash
SKILL=~/.workbuddy/skills/topic-library
mkdir -p /path/to/选题库/2026-10-05/work
cp $SKILL/config.example.json /path/to/选题库/config.json

python $SKILL/scripts/parse_cards.py input.txt -o work/articles.json --config ../config.json
# 抓正文（公众号文章直接请求即可，不用开浏览器）
python $SKILL/scripts/extract_article.py work/articles.json
# 读线上现有记录存成 work/existing.json，然后去重（决定每篇是新增还是更新）
python $SKILL/scripts/dedupe.py work/articles.json --existing work/existing.json
# 模型按 references/analysis_guide.md 写 work/analysis.json
python $SKILL/scripts/build_records.py work/articles.json --analysis work/analysis.json \
  --existing work/existing.json --config ../config.json
```

写入飞书见 `topic-library/SKILL.md` 的 7.1 节（含十个坑的实测记录），或直接用自带的写入模板：

```bash
cp $SKILL/scripts/templates/lark_upsert.py work/_final.py   # 改 BASE / TABLE 后运行
```

接群日报的链接：

```bash
python $SKILL/scripts/parse_cards.py --from-digest <日报目录>/work/stats.json -o work/articles.json --append
```

## 上手前：两份输入长什么样

两个 skill 的第一步都是「把一段文本转成结构化 JSON」，所以卡住基本都是输入格式不对。先看格式再跑。

**群聊记录**——`parse_chat.py` 认「时间 + 发言人 + 内容」，发言人写在时间前或后都认，也认引用消息里的「」：

```
2026-10-03 12:22阿杰：Seedance 2.0 人脸稳了但运镜变僵
「Momo：同参考图跑 10 次」
2026-10-03  12:24Momo：跑 10 次的结论我贴群里了 https://example.com/a
```

微信导出、全选复制、导出工具的格式大多能直接用。**只有日期没有发言人**（发言人写在上一行）也支持。
实在认不出，脚本会告诉你，按 `references/data_schema.md` 手动整理成 messages.json 也能继续。
记多条日期的记录一定要加 `--all-days`，否则只取最后一天。

**文章卡片**——`parse_cards.py` 靠链接切分，一篇文章一段，公众号名可以省略：

```
[链接] 5分钟教你用某工具免费做AI视频
按步骤即可完成，同时评论区提供答疑。
不正经秀才
```

每篇至少要有标题和 URL，否则后面抓正文会失败。参考 `examples/sample_input.txt`。

## config 是这两个 skill 的调音台

两个都靠 `config.json` 决定「什么值得挖」，改这一个文件比改 prompt 省事得多。

`wechat-group-digest/config.json` 里最值得先改的几项：

| 键 | 作用 |
|---|---|
| `reader_profile` | **决定日报的挖掘方向**。填「你是谁、擅长什么、不做什么」，不填只能给通用建议 |
| `aliases` / `strip_name_prefix` | 同一个人换了名字先归一，否则活跃榜被拆成两个人 |
| `ignore_senders` | 把机器人号排除掉 |
| `gap_minutes` | 相隔多久算一段沉默，超过就切话题（默认 20） |
| `max_topics` / `max_links_shown` | 控制长图长度 |
| `show_actions` / `show_quotes` | 关掉则不出现「可以动手的事」和「金句」两块 |
| `link_fetch` | 是否抓取群里链接的正文摘要（要联网） |
| `anonymize` | 匿名化发言人，`"none"` 关闭 |
| `history/` | 自动累积每天统计，用来算涨跌和跨天信号 |

`topic-library/config.json` 里 `profile` 决定选题角度和标题风格，
`benchmark_accounts` 是对标账号白名单，`style_bans` 是禁用句式（默认禁破折号和「不是…而是」）。

**改完先跑一遍校验**：`topic-library/scripts/check_fields.py` 会比对字段定义和线上表，
只报不该有的差异，飞书 API 的已知限制按每列的 `api_type` 声明后自动放行。

## 踩过的坑在各自的 SKILL.md 里

README 不重复了——`lark-cli` 的静默失败、多维表格 50 选项截断、日报 `highlight` 必须逐字切片，
连同换列类型的四步命令和备份流程，都写在各自的 `SKILL.md`（`topic-library` 的 7.1节最密集）。
只在一条值得单飞：**静默失败优先怀疑调用方式，不是数据**——
排错顺序固定为环境变量 → 参数形式 → 路径 → 数据内容，
这三个最贵的坑全都不报错，返回空或写错位置，很容易一路排查到怀疑数据本身。

## License

MIT，见 [LICENSE](LICENSE)。
