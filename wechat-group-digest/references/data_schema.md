# 数据格式

## messages.json（parse_chat.py 产出）

解析脚本认不出格式时，按这个结构手动整理，后面的流程照常跑。

```json
{
  "meta": {"source": "chat.txt", "dates": ["2026-10-03"], "count": 62},
  "messages": [
    {
      "id": 18,
      "date": "2026-10-03",
      "time": "12:22:10",
      "sender": "阿杰",
      "type": "text",
      "content": "新版对长提示词更敏感，把运镜写进第一句效果会好很多",
      "quote": null,
      "reply_to": null,
      "urls": [],
      "noise": false
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| id | 从 1 开始连续编号，后面所有引用都靠它 |
| type | text / link / image / video / voice / emoji / file / card / system / recall |
| quote | 引用回复时为 `{"sender","text"}` |
| reply_to | 被引用消息的 id，找不到为 null |
| noise | 水消息标记。只影响送给模型的内容，统计照常计入 |

## analysis.json（模型产出）

所有 `refs`、`msg_ids`、`msg_id` 都是 messages.json 里的 id。时间、条数、参与人由脚本根据 id 算，不用写。

```json
{
  "lead": "今天群里最热的是 Seedance 2.0 新版本到底值不值得换……",
  "lead_highlight": "Seedance 2.0 新版本到底值不值得换",

  "key_points": [
    {"text": "Seedance 2.0 人脸稳了但运镜变僵，做口播的可以换，做剧情的先别急。", "highlight": "", "source": ["T1"]}
  ],

  "topics": [
    {
      "id": "T1",
      "title": "Seedance 2.0 要不要换？",
      "type": "争论",
      "extra_tags": ["工具测评"],
      "status": "还在争",
      "expanded": true,
      "msg_ids": [9, 10, 11, 12],
      "bullets": [
        {"text": "Momo 用同一张参考图跑 10 次，人脸基本不跑了。", "highlight": "人脸基本不跑了", "refs": [9, 11], "from_link": false}
      ],
      "disagreement": "做口播的觉得值得换，做剧情的觉得不如旧版。",
      "comment": "分歧来自用途不同……"
    }
  ],

  "roles": {"questions": [15, 33], "answers": [16, 34]},

  "tips": [
    {
      "title": "去 AI 味要单独跑一遍",
      "body": "写稿和去 AI 味分两次让模型做，效果比一次要求稳定。",
      "verbatim": "保留原意，删掉所有总结句和排比，每段不超过三句，口语一点",
      "refs": [34, 36],
      "credibility": "待验证",
      "source": "群友"
    }
  ],

  "open_questions": [
    {"msg_id": 57, "text": "剪映的智能字幕怎么批量改字体？", "followers": 2}
  ],

  "actions": [
    {
      "type": "做工具",
      "title": "剪映字幕批量改字体的小工具",
      "signal": "本周已有 3 个人问过同一件事，群里没人给出办法。",
      "first_step": "先看剪映草稿里的 draft_content.json，确认字体字段能不能批量替换。",
      "priority": 3,
      "difficulty": "中",
      "effort": "约 1 天",
      "source": ["Q1"]
    }
  ],

  "quotes": [
    {"msg_id": 22, "text": "工具换得勤的人，作品一般都不多。"},
    {"msg_id": 51, "text": "被封的人越来越多，申诉连个人都碰不到。", "paraphrased": true}
  ],

  "links": [
    {"url": "https://github.com/doocs/md", "title": "doocs/md 公众号 Markdown 编辑器", "note": "阿杰排版用的开源插件", "read": "已读取", "summary": "……"}
  ]
}
```

### 枚举值

| 字段 | 可选值 |
|---|---|
| topics.type / extra_tags | 工具测评、求助答疑、行业消息、经验分享、争论、资源分享、活动通知、闲聊 |
| topics.status | 已解决、有共识、还在争、没人回、已沉淀、简单提及 |
| tips.credibility | 已验证、待验证、推测 |
| tips.source | 群友、链接 |
| actions.type | 写文章、做工具、做Skill、做内容、马上试 |
| actions.difficulty | 低、中、高 |
| actions.priority | 1 到 3，3 最高 |
| links.read | 已读取、仅标题、未读取、未尝试 |

### 引用 id 的写法

* 要点的 `source` 写话题 id（T1）或行动项 id（A1，按 actions 数组顺序从 1 开始）
* 行动项的 `source` 写话题 id（T1）、干货 id（tip1，按 tips 顺序）、待解决问题 id（Q1，按 open_questions 顺序）
* 渲染时会自动换成"话题 1""干货沉淀"这类读者能看懂的标签
