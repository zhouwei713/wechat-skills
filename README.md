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

## 两个 skill 里踩过的坑（都写进各自 SKILL.md 了）

开源版本保留了完整的实测记录，因为**文档里没有坑，踩一遍的成本就是几十分钟**。挑三个最有代表性的：

**`lark-cli` 在 Python subprocess 里设 `LARK_CLI_NO_PROXY` 会让 stdout 变成空字符串。** 不报错，
看起来像接口挂了。排错顺序固定：环境变量 → 参数形式 → 路径 → 数据内容。

**多维表格开放词表必须先建选项，否则整条记录写不进去**（报 `800030005`），
而单选/多选的选项数超过 50 会**静默截断**——传 60 存回 50，API 一声不吭。

**群日报的 `highlight` 必须是该条要点自己文本里的片段，不是原消息里的片段。** 首跑 10 个话题的要点全挂在这条上。

## 两个 skill 的字段定义会漂移

`topic-library/references/fields.json` 声称是字段定义的唯一来源，但它和线上表会漂移——
飞书 API 有几处不支持字面类型（`rating` 不支持、超 50 的多选会被截断、CLI 建不出 `url` 列）。

所以附了一个自查脚本：

```bash
python scripts/check_fields.py work/_fields.json
```

只报**不该有的**差异，已知的 API 限制用每列的 `api_type` 声明后自动放行。

## License

MIT，见 [LICENSE](LICENSE)。
