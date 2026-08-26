# 魔物地下城小酒馆 · 交接文档
> 最后更新：2026-08-26
> 版本：v2.18

## GM 长文本超限才接续 + 气泡内保留换行（2026-08-26）

- **需求**：像 Hermes 发 QQ——消息超字数上限就在句界接续下一条；**换行不产生新气泡，但气泡内原有换行分段必须保留**。
- **实现**（index.html addMsg 重构）：
  - **单条上限 `SINGLE_LIMIT=800`**：句子流连续累积，超 800 字才在句界切下一个气泡。
  - **换行成块加入内容但不触发切条**：`\n+` 换行段以空行 `\n\n` 拼进当前气泡保留排版，连续换行最多折一段空行。
  - 长度累计只算有效文字（`sentLen` 不含换行）。
  - choices 只渲染最后一条 → `appendChoiceButtons`；仅选项无叙述单独渲染；玩家消息单条不切。
- **关键坑**：切句正则**必须 `[^\n。！？.!?…]…` 排除 `\n`**，否则换行被 `[^…]*` 吞进前一句、换行段分支匹配不到→整段挤一起（用户截图"不不换行了"）。别按 `\n\n` 分段循环切气泡（GM 多段换行炸碎气泡）；气泡内换行保留（trim 勿去）。
- **验证**：node/Python 单测—短消息1条且含 `\n\n` 空行 / 多分段共400字整段1条且空行保留(T1'T2 预览`第一句。\n\n第二句。\n\n第三句。`)/ 1600字连续2条且拼接不丢 / 选项独立在末尾 / 无残缺条；JS node check 过。

## 📐 右侧折叠操作栏 + 布局改造（v2.23，2026-08-26）

**需求**：底部操作按钮(#input-area 的下一天/探索/生育/重写)全部迁到右侧折叠侧栏；点探索/生育后选项目在栏内下方展开，替代全屏弹窗。

**实现**：`.right-dock`(fixed right, z-index 2000)，含 toggle、actions(下一天/探索/生育/重写)、dock-body(explore-sec/breed-sec)。点探索/生育→`showExploreModal()/showBreedModal()` 调 `openDockSection` 展开+渲染到 dock 容器(`dock-explore-zones`/`dock-breed-father`/`dock-breed-mother`)。底部 input-area 只留 textarea+发送。折叠态 width 52px 只剩图标。

**验证**：curl 服务端含 right-dock/各容器/openDockSection 定义，版本 v2.23，http 200。JS node check 过。

**v2.24 修复**：建档后 create-modal 不关 + dock 不收起。根因：`createAdventure()` 用 `create-modal').classList.remove('show')` 关闭，但当前 create-modal 是内联 `style.display='flex'` 打开——class 移除无效。修为 `create-modal').style.display='none'` + 遍历收起 explore/breed dock section。

**v2.25 修复**：配种按钮点了没反应。根因：dock 里新配种按钮 `id="breed-confirm-btn"` 与旧全屏 breed-modal 的按钮**id 重复**，`pickBreedParent` 用 `getElementById` 拿到旧 modal 隐藏的那个去 enable/disable，dock 里的永远 disabled。修为 dock 按钮 id=`dock-breed-confirm-btn` 唯一，pickBreedParent 改引用。**教训：布局改造后必须全文件扫重复 id（正则 `id="..."` Counter）**。

**陷阱**：① 探索/生育 dock 按钮 onclick 必须调 showExploreModal/showBreedModal（会渲染），别只调 openDockSection（只展开不渲染）② 重启服务用绝对路径 python.exe（`C:/Users/niutun/AppData/Local/Programs/Python/Python311/python.exe`），裸 `python` 在 PowerShell Start-Process 起不来。

## ⚠️ 版本号血泪：sed 改版本号可能不生效 + 版本号才是真相（2026-08-26 深夜）

**事故**：写文档说"已 bump 到 v2.22"，实际磁盘 index.html 还是 v2.20——之前那条 Git Bash `sed -i "s/...v2.21.../v2.22/"` 的转义被吞/没执行成功，但德比伦以为改了并发消息说"重启到 v2.22"。用户报"不是 v2.22"，curl 一查服务确实返回 v2.20 = 磁盘真值。**教训：一切以 curl 服务端返回为准，别信自己"改了"的记忆。**

**排查法**（遇到"版本明明升了还是老"）：
0. 先 `curl 服务端 | grep v2.x` —— 看服务真正 serve 什么。
1. 查磁盘：`grep -n "APP_VERSION\|v2\.[0-9]" index.html`。
2. 查占用：`Get-NetTCPConnection -LocalPort 8099 | Select OwningProcess` + 该 PID 命令行确认跑的是哪个 python/server。
3. 杀旧进程要**确认端口释放**（重查监听数=0）再起新的，否则竞态起来的是老进程。
4. 改版本号用 `patch` 工具（可靠），别用 Git Bash sed（引号/转义易被吞）。

**服务重启铁律**：形如 `Stop-Process -Id (Get-NetTCPConnection -LocalPort 8099 -State Listen).OwningProcess` 杀完**必须 sleep≥2 再查端口=0**，再用 PowerShell Start-Process 起，最后 curl 验证版本号 + http 200 才算完成。竞态=老进程白起，白测。

**症状**：点「探索」/「配种」按钮，弹窗不跳出来，要"打开新冒险界面"之后才出现。一次修复（改 alert→newAdventure 引导）用户反馈"还是不行"。

**二次修复（结构性）**：不再依赖 `.show` class 机制（`classList.add('show')`→CSS `.modal-overlay.show{display:flex}`），因为一旦 CSS 加载顺序/缓存/class 不匹配就静默不弹。改成**无条件弹 modal——直接 `modal.style.display='flex'` 内联控制**：

- `showExploreModal()` / `showBreedModal()`：第一行就 `style.display='flex'` 弹出来，然后判断：
  - 有 session：正常加载探索区域 / 配种池
  - 无 session：在 modal **内部**显示「立即开始新冒险」引导按钮（不是 alert 干拦、不是全屏替换）
- `closeExploreModal()` / `closeBreedModal()` / `closeCreateModal()`：`style.display='none'`
- `newAdventure()`：打开 create-modal 也改 `style.display='flex'`

**为何"还是不行"**：初次修复只改逻辑却可能被**浏览器 JS 缓存**掩盖。用户必须**硬刷新**（Ctrl+Shift+R 或清缓存）加载新 JS。排查按钮失效：先确认拿到的是新代码（`showExploreModal` 第一行应是 `modal.style.display='flex'` 而非 `if(!session_id){alert}`）。

**残留**：skill-modal/save-modal/load-modal/loot-modal 仍用 classList('show')（次要入口，未动）。新增 modal 一律用 style.display。

- **问题**：GM 输出被 `max_tokens` 腰斩（句子没写完/标签断尾），玩家看到不完整叙述。根因是代码无视 `finish_reason`——截断时只拿到半截话直接当完整叙述用，没续写也没重试。
- **修复**：
  - 主对话调用加**截断自动重试循环**：检测 `finish_reason == "length"` → `max_tok` 翻倍（上限8192）重发一次，并注入续写指令「你的上一条被截断了，停在「…」，请接着写完、不重复已写部分」，最多重试3次。
  - 记录 `reply_truncated`（重试后仍截断才为 True），API 返回值加 `"truncated"` 字段。`reply_truncated` 在 try 前兜底初始化为 False（异常路径不经过重试）。
  - 前端两处 GM 输出点（autoStart + sendMessage）读 `data.truncated`，为 true 追加「⚠️ 这段太长了被字数上限截断,已自动重试补齐」提示。
- **验证**：后端编译过、JS node check 过、重试 while 逻辑单测过（截断→翻倍8192→重试→拿 stop）、服务重启 200。

## 幼年魔物设定 + NSFW 直呼词汇规范 + 输出长度指令修复（2026-08-26）

- **幼年魔物不会说话（通用世界观，任何模式生效）**：写在 SYS 基础规则——幼年魔物只会奶声奶气叫（呜/嘤/咕）、用身体表达情绪（蹭腿/摇尾巴/扑腾/炸毛），听不懂复杂指令。GM 必须用「动作+叫声+身体反应」写，**严禁给幼年魔物安排完整台词或内心独白**。只有成长/进化到一定阶段才解锁对话。
- **NSFW 直呼器官词硬规范（只在 NSFW 分支注入）**：把原先的「直白词汇——不婉转」升级成强迫性直呼规范——直呼名单扩充加入「小穴/肉缝」：唧唧/肉棒/小穴/肉缝/阴部/前液/后穴/肉垫/乳头/精液/操。硬约束：选定词全文复用，禁止转头写「那里/下面/那玩意儿」等代词，禁止「触碰羞处」式婉转。每次身体接触必须点名是哪个器官碰哪个器官、谁湿了谁硬了谁滴了。
- **🐛 输出长度「没解决」的根因 + 修复**：长度下拉只把 `_max_tokens`（token 上限）传给 API，但**提示词里没有「本轮要写多长」的命令**——LLM 不会因为额度变大就自动写长，它按 prompt 默认「每段150-250字」写短文，额度用不满。**修复**：chat 拼 `base_sys` 时注入 `_len_指令`——按 `_length_preset`（short300字/medium600字/long1000字/verylong1600字+）明确告知 GM 本轮必须写多少字、铺开写；NSFW 分支无条件 `NSFW强制拉满 每段1500字以上不设上限`。**实测**：同样引导 verylong 1336字 vs short 870字（修前 verylong 只 1079字）。
- **教训**：控制 LLM 输出长度必须在 `max_tokens` 之外同步注入提示词长度指令——LLM 按 prompt 隐含的段落字数习惯写，额度再大也不会主动写长。

## 🐛 新建存档"没法启动"真凶 + 修复（2026-08-26 修正）

- **真凶是装饰器堆叠错误，不是 characters_updated**（上一版记录有误，予以纠正）：给 `rewind` 加路由时把装饰器叠错了——`@app.post("/api/chat")` 错误地叠在 `rewind(def sid: str)` 上，聊天接口被整个劫持。后果：建档后 autoStart 发 `POST /api/chat [START]` → **422（缺 query sid）+ 0秒** → GM 开场起不来 = "新建后没法启动"。
- **修复**：rewind 只保留自己的 `@app.post("/api/session/{sid}/rewind")`；真正的 `def chat(req)` 补回 `@app.post("/api/chat")`。
- **验证**：`POST /api/chat`（body 带 session_id）[START] 200 + GM 开场叙述正常产出；日常对话 200；rewind 200。全链路通。
- **次因（确认仍存在但已防呆）**：后端 `"characters_updated": chars if chars_updated else False`（bool 或数组二选一），前端 `autoStart` 已加 `Array.isArray` 判断——数组才整体覆盖，否则走 `refreshCharacters()`。
- **排查法**：聊天接口返回 422 + `loc:["query","sid"]` + 0.0s = 该接口被错误路由绑架到了带 query 参数的函数。测 /api/chat 前先确认 `def chat` 头顶真挂了 `/api/chat` 装饰器。
- **教训**：给新 endpoint 加装饰器**永远单独一行 @app.post + 自己的函数**，不和其他路由叠在同一个 def 上——叠了就把旧接口顶掉了。

## 魔王参与配种 + 新建存档启动 bug 修复（2026-08-26）

- **魔王进配种池**：父方池和母方池顶部各加「😈 {魔王名}」选项，标注「性别可改」——魔王既可当父也可当母（用户需求：魔王性别随时可改，所以父母都行）。前端从 `/api/session/{sid}` 的 `player_name` 字段拿魔王名（后端已在 `get_sess` 返回该字段）。
- **后端复用现有配种逻辑**：魔王当父 → `father_is_player=True`；魔王当母 → `mother_is_player=True`，`carrier = mother if mother else father` 保证怀孕的始终是魔物那只（魔王只提供另一侧血缘），后代继承魔物种系。
- **触发条件**：「🤰 生育」按钮 = NSFW 开 && 有 ≥1 只未怀孕魔物（魔王能凑数，一只魔物也够配）。
- **🆕 createAdventure 建档后补两行**：`state.player_name = data.player_name || playerName` + `updateBreedBtn()`——否则新建的存档魔王名不存、生育按钮不显示。
- **🐛 新建存档"没法启动"根因**：后端 chat 返回 `"characters_updated": chars if chars_updated else False`（bool False 或数组二选一），前端 `autoStart` 无脑 `state.characters = data.characters_updated` → 开场 [START] 几乎不带落地标签 → 拿到 False → 把数组覆盖成布尔 → 后续 `.filter/.length` 全崩 = 面板空白。**修复**：`Array.isArray(data.characters_updated)` 判断——是数组才整体覆盖，否则走 `await refreshCharacters()`。sendMessage 一直用 refreshCharacters（安全），只有 autoStart 踩坑。教训：后端「要么 bool 要么数组」的字段，前端绝不能无脑整体赋给 state，先判类型。

## 随机剧情方向预设（2026-08-25）——防止 AI 自由发挥绕死的核心机制
- **核心问题**：之前 `PATROL_EVENT_POOL` 的事件是「一滩随机事件」，`event` 类只丢 desc 给 GM 让它自由叙述——这正踩「AI 自由发挥绕死」的坑。
- **解法**：每个事件加三样「方向预设」字段，GM 叙述时有谱：
  - `direction` → 事件所属方向（GM 知道往哪个主轴演）
  - `gm_hook` → 给 GM 的叙述指引（怎么展开、怎么收、别碰什么数据）
  - `reward_hint` → 玩家能预判的收益倾向（项目铁律：可预判才不空转）
- **七方向覆盖**（`PATROL_EVENT_POOL` 共 **22 事件**）：战斗入侵 x5（encounter 真战斗）/ 招募结盟 x3 / 基建发展 x3 / 资源机遇 x3 / 危机征兆 x2 / 秘辛探索 x3 / 情感羁绊 x3（后六类为 event 叙事）。
- **数据分布**（200 次 bootstrap）：战斗 24% / 叙事 76%，抽取概率均匀，移动端 encounter 全带 enemy（0 缺失）。
- **GM 消息注入**：server.py 巡逻 `event` 分支把 `direction`（→收益倾向）+`gm_hook` 拼进 `[EVENT]` 指令块，明确要求 GM「严格按照事件方向和叙述引导演，不另起炉灶」，选项要呼应收益倾向。
- **字段传递**：`consequence_manager.patrol_encounter_rule` 的 effect 现在把 `direction/gm_hook/reward_hint` 一并塞进事件 data（原先只有 kind/name/desc/enemy）。
- **新事件示例**（战斗）：精英暗影蝠（血厚攻高精英）；叙事：走失幼崽（招募）、地底温泉口（可建浴场）、诡异祭坛（秘辛）、窥视的鸦群（预警）、想家的新兵（羁绊）。
- **⚠️ patch 缩进坑（又双叒踩）**：改 server.py 或 consequence_manager.py 的多行函数体时，patch 会把新块的缩进全推乱导致 `IndentationError`。**必须用 execute_code 按行号重写**（skill 教训 26 已记）。本次 `patrol_encounter_rule` 的 effect 被 patch 搞乱缩进 + server.py event 分支被搞乱——都用 execute_code 重建修复。

## 输出长度 + 手动压缩记忆（2026-08-25）
- **tavern 是 memory 驱动的**：消息窗口 `MAX_CONTEXT_MESSAGES=40`，超 60 自动 `_trim_and_summarize`（机械抽事件行）+ 摘要缓存 `_history_summary` 注入 system prompt。
- **前端输出长度下拉**（冒险页底部「✍️ 输出长度」）：short512/medium1024/long2048/verylong4096。`POST /api/session/{sid}/length` 存 `_max_tokens`+`_length_preset`，主对话优先用会话值覆盖环境变量。⚠️ NSFW 模式强制 ≥4096，下拉无效。
- **「🧠 压缩记忆」按钮**：`POST /api/session/{sid}/summarize` —— 调用 LLM 语义总结最近 120 条对话历史（专用书记员 prompt，保留硬信息 + 待处理事项，≤300字），存 `_history_summary` 缓存 + 截断 messages 到最近 8 条。真语义理解，比机械抽行强得多。对话太短(<4条)→400。
- **压缩模型可调**：前端「🧮 缩用」下拉选模型（auto/deepseek-chat/deepseek-v4-flash/deepseek-reasoner/自定义…）。请求体 `{model: "..."}`。后端解析：`req.model` (≠auto) > `LLM_SUMMARY_MODEL` > `REVIEW_MODEL` > `LLM_MODEL`。⚠️ 无效模型会 401（ModelError），已包 try/except 返回友好 500，不破坏会话。
- **实测**：4 条对话总结出专业摘要（角色/战斗/建造/待办全保留）；有效模型 200、无效模型返回友好错误。
- **⚠️ .env 曾被 Hermes config.yaml 污染**（500+ 行 YAML 混入导致 python-dotenv 全程报警）——已清理成仅 5 个有效变量（OPENAI_API_KEY/LLM_MODEL/OPENAI_BASE_URL/NSFW_ENABLED/REVIEW_MODEL）。若再看到 `python-dotenv could not parse statement` 报错，检查 .env 是否被污染。

## 战利品携带额度系统（2026-08-25）——防止无限刷掉落
- **巡逻遭遇战接入真程序战斗**：`_run_patrol_combat`（复用 raid 引擎，我方全队 vs 单敌人）。玩家巡逻遇敌 → 对话选项「迎战/逃跑」→ 迎战跑引擎战斗、逃跑无事发生。
- **携带额度**：`get_carry_capacity(chars) = 50 + 5×Σ魔物等级`。稀有度占用值：common5/uncommon10/rare20/epic35/legendary60（`loot_weight`）。
- **掉落**：`roll_patrol_loot` 从探索/波次池按 tier roll 2~3 件（打赢才掉落）。
- **挑选**：打赢 → 战利品挂起 `_pending_loot` → 前端「🎒 挑选战利品」弹窗，勾选占用值 ≤ 额度带走，未选**硬丢弃**。超额 400 拒绝。
- **战败**：`victor_team != 0` → 战利品全丢 + 队伍受伤写回。
- **API**：`GET /api/session/{sid}/loot`（看待选+额度）、`POST /api/session/{sid}/loot/pick`（挑带/丢弃）。
- **事件池**：PATROL_EVENT_POOL 的 4 个 encounter 事件各配 `enemy` 字段（落单冒险者Lv3/流窜盗匪Lv4/模仿怪Lv5/地穴虫群Lv3）。
- ⚠️ 触发链路：巡逻 `/day 巡逻` → 85% 遇事件 → encounter 挂 `_pending_patrol` → 玩家「迎战」→ `_run_patrol_combat` → 赢 `roll_patrol_loot` + 弹窗挑 / 输丢弃。

## 其他改动（2026-08-25 同日）
- **字数限制解除**：前端输入框 `<input>`→`<textarea>`（Enter 发送/Shift+Enter 换行/自动增高）；GM 输出 SYS「不设字数上限」，招募/巡逻/战斗局部指令同步放宽。
- **装备描述清理**：equipment.json 中 3 处「前任魔王仓库」旧世界观残留已改。⚠️ 若加新装备别再用「前任魔王」设定。

## 世界观重构（2026-08-25）——第一位魔王
- DEFAULT_WORLD 整段重写：玩家是被选中的人、被光芒吸入全新地下城、掌烙王印、第一位魔王。初始魔物由「强大存在托付」。
- 开局选项机制化（SYS [START]）：选项必须有明确收益、面板可查、绑定 /day。
- 6 个 ORIGIN_SCENES + 2 个 CHARACTER_PRESETS 描述重写；巡逻事件池删「前任魔王/储物间」。

---

## 项目概述

Web 文字冒险 RPG。玩家扮演地下城领主，培养魔物、招募同伴、抵御冒险者入侵。GM 以中立叙述者主持一切。

- **后端**: FastAPI (Python), `server.py` 3225行
- **前端**: 纯 HTML/JS, `index.html` 156KB, 三 Tab（冒险/加点/设置）
- **LLM**: DeepSeek (OpenAI 兼容 API)
- **端口**: 8099

---

## 目录结构

```
derbiren-tavern/
├── server.py              # FastAPI 后端 — 全游戏逻辑
├── consequence_manager.py # 统一概率事件管理（重构完成 ✅）
├── combat/                # 战斗系统独立模块（提取完成 ✅）
│   ├── __init__.py
│   ├── core.py
│   └── skill.py
├── index.html             # 前端
├── recruits.json          # 8 个可招募魔物
├── species_lore.json      # 8 个可选物种设定
├── skill_library.json     # 技能模板库
├── equipment.json         # 装备数据
├── equipment_templates.json
├── constructions.json     # 工事/建筑
├── plans/                 # 设计文档
│   └── consequence_manager.md
├── reports/               # 审查报告
│   └── analysis_2026-06-12.md  # ⚠️ 已过时
├── tests/
│   └── test_explore_encounter.py  # 探索遇敌回归测试
├── saves/                 # 会话存档 (JSON)
├── venv/                  # Python 虚拟环境
├── .env                   # API Key 等配置
└── README.md
```

---

## 已完成

| 事项 | 状态 |
|------|:--:|
| 基础游戏循环（/day 训练/巡逻/探索/配种/休息/研究/净化） | ✅ |
| 7 属性战斗系统（d100命中 + 无随机伤害 + 护甲穿透） | ✅ |
| 三轮 Raid 系统（Lv3→Lv4群→Lv10三人组） | ✅ |
| 8 物种 + 动态技能生成 + 等级成长 | ✅ |
| 配种系统（跨物种/魔王/杂交亚种/怀孕） | ✅ |
| ConsequenceManager 重构（统一概率管理） | ✅ |
| 战斗系统提取为独立 combat/ 模块 | ✅ |
| 装备系统（掉落/工事建造/品质分级） | ✅ |
| 审查 AI | ✅ 8类标签全覆盖：CHAR_ADD/LEVEL_UP/DMG/EQUIP/CONSTRUCTION/DEATH/BIRTH/EVOLVE |
| GM 中立叙述 | ✅ |
| 配种/净化/巡逻 startswith bug 修复 | ✅ |
| 上下文管理（消息截断 + 长期记忆摘要） | ✅ |

---

## 待办 / 可迭代方向

| 优先级 | 内容 |
|:--:|------|
| 🔴 | **数值平衡**：命中率靠 SPD 驱动，战士类命中偏低需补偿 |
| 🔴 | **波3难度**：上次测试胜率 5/5，敌人太弱 |
| 🟡 | **探索遇敌兜底**：代码层 50% 概率触发战斗（ConsequenceManager 已有规则） |
| 🟡 | **审查 AI 发现遗漏时通知玩家**（目前只记日志） |
| 🟡 | **起名超时回退**：3天不起名自动用默认名 |
| 🟢 | frontend UI 打磨 |
| 🟢 | 更多物种/技能/装备 |

---

## 启动方式

```bash
cd C:\Users\niutun\AppData\Local\hermes\output\derbiren-tavern
source venv/Scripts/activate
python server.py
# → http://127.0.0.1:8099
```

---

## 测试方式

```bash
# 数值平衡测试
cd C:\Users\niutun\AppData\Local\hermes\output
python combat_test.py

# 探索遇敌回归测试（需 server 运行中）
cd derbiren-tavern
source venv/Scripts/activate
python tests/test_explore_encounter.py
```

---

## AI Agent 操作说明

- 单文件后端，用 `patch` 或 `write_file` 修改 `server.py`
- 改完 `kill` 旧进程 + 重启 `python server.py`
- 状态在 `saves/{session_id}.json`
- 端口 8099 占用检查：`netstat -ano | findstr :8099`


**v2.26**：NSFW 模式配种详细色情描写——server.py `nsfw_breeding`（open 分支）重写为「配种专用强制指令」：默认1200-2000字+、严格【前戏→正戏→后戏】三幕（舔舐铺垫/插入节奏/后戏温存，融合直白器官词+身体诚实+拟声词全铁律）。全年龄分支不变（宝可梦孵蛋）。改 prompt 中文多行字符串的转义血泪见 skill（patch双转义\execute_code再转义→独立.py字节级+chr操作才稳）。


**v2.27 修复（严重）**：NSFW 开关开启时仍注入非 NSFW 内容。根因：修 v2.26 prompt 转义时把 `if nsfw_on:` 的 `else:` 分支弄丢，导致全年龄内容(nsfw_rules="全年龄向"+nsfw_breeding="宝可梦孵蛋")被并进 if 块，**覆盖掉 NSFW 内容**。开 NSFW 时实际用的是全年龄内容。修复：恢复 `else:` 结构，AST 验证 IF分支=开放+配种专用、ELSE分支=全年龄+宝可梦，零串线。**血泪：改 if/else 块的 prompt 字符串后必须 py_compile + AST 验证两条分支值，别只看语法通过。**


**v2.28 更新**：
1. **配种补强（参考芒果文爱铁律）**：nsfw_breeding(NSFW分支) 追加 7 条进化铁律——话说完整（最高优先，不缩写不压缩不省略）、严禁比喻（禁「像蛋清像蜜桃」）、福瑞身体规则（禁皮肤/肤色，写毛+体液交互）、外貌必须写颜色（奶头颜色/毛色分布）、色色必须详细（每动作2-3身体细节+角色反应）、性格害羞≠旁白害羞（旁白直白主动）、不刻意升华（禁「等了多久/你是特别的」）。AST验证7条全在，总字符1746。
2. **芒果(bot6)已重启上线**：17:11 Ready，QQ 1904542481。
3. **待办-哥布林名字**：用户指出哥布林是一兄一弟（哥布A=兄战士近战/哥布B=弟射手远程），但名字「哥布A/哥布B」太平庸像占位符，与丰富desc不匹配，需改名（待用户确认风格）。


**v2.29 新增：淫趴模式（多对多群交）**
- 需求：用户提出生育「太死板一父一母」，要加「资源模式」-淫趴，不限人数和性别，开趴。拍板产出：**经验 + 概率怀孕**，人数越多受孕率越低，男男也可（不设攻受）。
- 触发：`/day 淫趴 参与者=A,B,C`（别名：狂欢/大乱交）。前端 dock 生育栏加 **💞配种/🎉淫趴** 模式切换按钮；淫趴用一个多选池（含魔王，性别不限），≥2 选中启「🎉开始淫趴」。
- 后端逻辑（server.py 配种分支前）：
  - 参与者洗牌两两配对 `(i, i+1)`，每对独立判定怀孕
  - 含魔王的对 → 魔物方100%受孕（魔王铁律，不受人数衰减）
  - 魔物×魔物 → 随机一方为载体，成功率复用现有跨物种规则 × **人数衰减** `max(0.4, 1.0-(N-2)*0.15)`（N=2→1.0, N=5→0.55, N≥6→0.4）
  - 所有参与魔物拿经验 `get_explore_tier(day)`（与锻炼一致），可触发升级/猫龙进化
  - 怀孕天数沿用 carrier 稀有度分档，孕期-60%伤害
  - 结果逐个报 `[BREED]`，事件 `_log_event("orgy")`
- SYS 提示词加「淫趴」规则段：告诉 GM 这命令存在、怎么叙述（NSFW模式按配种指令详写群交；全年龄一句带过），且**怀孕判定由系统完成，GM 只叙述不自行决定**。
- 端到端验证：3魔物（铁牙/豆苗哥布林男男 + 焰爪母猫龙）参趴 → 全员获得经验（exp9/12/13），orgy事件已记录，配对判定正常。
- 设计要点：淫趴是"资源+概率"，不是保底怀孕——N人参趴=⌊N/2⌋对独立roll，可能0到多只怀孕。


**v2.30 修复（严重）**：刷新后 GM 长回复"只剩第一段"。根因：`GET /api/session/{sid}` 返回 history 时把每条 content 硬截断 `m["content"][:500]`——实时回复走 sendMessage 拿到完整 narrative 正常分条，但刷新后 restoreHistory 读 history 拿到的是被砍到 500 字的截断版，长回复只剩第一段。修复：移除 `[:500]`，完整返回，前端 addMsg 自动分条。**教训：history 是给前端渲染的用户可见内容，绝不能截断——截断会丢段。区分「事件日志/错误信息的 [:200] 截断」（合法）与「用户消息内容截断」（禁止）。**


**v2.32 介绍文案重写大工程（用户点名）：**
- **8 物种 lore 全重写**：去"话没说完硬转折"的德比伦味（“不是…而是…”“表面…实则…”等 SYS 写作铁律禁句式），改完整书面叙事 + 贴合"幼年魔物不会说话像小动物"设定。
- **修逻辑冲突（违反第一位魔王铁律）**：①触手怪"远古魔王的残留意念"→"地下暗河淤泥自然滋生的原生魔物"（远古魔王与玩家=第一位魔王矛盾）；②幼龙"远古战争/沉睡古龙/观察蝼蚁人类决定烧死"→"血统火种、孩子气好奇"（远古遗产线+幼年说复杂话冲突）；③石像鬼"沉睡在古老建筑顶端"→"地底深处某角落"（地下城全新无古老建筑）；④哥布林"幸存者逃入地下城向魔王效忠"→"逃到地下城外围、恰逢新魔王登临"（地下城全新无人踏足）。
- **recruits.json 全部 12 条 desc 重写**（去"——但/，但/——虽然"硬转折）；**CHARACTER_PRESETS 10 条 + BIRTH_PRESETS 出生背景 4 条 desc 同步重写**。
- **哥布A/哥布B 改名 石锤&藤弓**（兄近战战士持锤/弟远程射手挽弓），三文件（server.py 名池/index.html 预设+character_presets/recruits.json）全同步。
- **配种/淫趴自动输入加话**：doBreed→`/day 配种 父=X 母=Y 请详细描写这次配种交合的全过程…`；doOrgy→`/day 淫趴 参与者=X,Y 请详细描写这场淫趴群交的全过程…`。**后端淫趴正则收紧** `参与者[=＝](.+)`→`[^\s]+`（原来贪婪会吞掉追加的话报"找不到参趴者"）。
- 表现：先去转折句式再保信息量，AI 提示词（lore 会注入）不再教坏模型写硬转折。


**v2.33 前期升级提速（用户要求"前期升级快一点"）：**
- **升级需求分段**（server.py `_check_levelup`）：L1-3 = 60×level（提速40%）、L4-6 = 80×level（提速19%）、L7+ = 100×level（还原，满级平衡不破）。
- **前期经验提升**（combat/equipment_scaling.py `get_explore_tier`）：D1-10 从 5-15 → 15-30、D11-20 从 10-25 → 20-40。后两档梯度不动。
- **效果**：锻炼约 3 天升 L2、10 天升 L3（原 L1→2 要 10 天，3 倍速）。波次奖励档（2791+）未动，属额外来源。
- 验证：引擎 get_explore_tier 实测 D1=15-30/D20=20-40；模拟 simulate 确认 3day→L2、7day→L2、10day→L3；L7+ 还原确认。


**v2.34 手机能玩（PWA + 局域网）：**
- **服务绑定 `0.0.0.0`**（原 127.0.0.1）：手机局域网可访问。本机 IP 192.168.1.17 → 手机同 WiFi 浏览器开 `http://192.168.1.17:8099/`。
- **移动端响应式**：@media(max-width:768px) 首断点——dock 缩 56px、聊天区放大字号、tab/按钮触屏友好、textarea 16px 防 iOS 缩放。
- **PWA 支持**：manifest.webmanifest + icon-192/512.png（PIL 生成王冠+魔物标志）+ head meta（apple-mobile-web-app + theme-color）。手机浏览器→菜单→「添加到主屏幕」→桌面出现 App 图标，全屏玩。已加 4 条 FileResponse 路由（/manifest.webmanifest /icon-192.png /icon-512.png）。
- **⚠️ 防火墙**：8099 监听已确认 0.0.0.0；防火墙已有 Python Allow 规则（多条），但系统里也有 python.exe Block 条目。新建允许规则需管理员权限（德比伦被拒）。若手机连不上 → 以管理员开 PowerShell 跑 `New-NetFirewallRule -DisplayName HermesTavern-8099 -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8099 -Profile Private,Domain`。
- 验证：局域网 IP 访问 / 200、/manifest 200、/icon-192 200、serve v2.34。
- 说明：这是"手机能玩"的第一阶段（局域网+PWA）。若要"不烧key的GitHub在线纯前端版"或"key上云的在线AI版"，见对话中 alternatives（纯前端=改DOL式本地引擎；serverless=key托管云）。


**v2.35 纯前端在线版（web/ 目录）——玩家自带 key：**
- **位置** `web/index.html` + `web/api.js`（静态，可挂 GitHub Pages）。
- **核心思路（用户拍板）**：网站只提供软件，玩家接入自己的 AI。key 存玩家自己浏览器 localStorage，浏览器直连 DeepSeek 官方 API，零后端、主人不烧额度。
- **可行性已验证**：DeepSeek API 支持 CORS（`access-control-allow-origin` 回显、允许 authorization 头）→ 浏览器能直连。
- **功能（MVP）**：填 key → 建魔王（选初始魔物）→ 聊天 GM 叙事 → 存档 localStorage → NSFW 开关。GM 系统提示词复用了主版 SYS（世界观+写作铁律+魔物幼年设定+NSFW 双分支）。
- **选项按钮**：复用主版 parseChoices 逻辑，把 GM 回复的「现在你可以：- **选项**——描述」渲染成可点击按钮。
- **验证**：node --check 双 JS 全过；沙盒跑 callDeepSeek 真实连上 DeepSeek（401 被正确捕获显示友好错误）→ 直连链路打通。ID 引用/函数定义/事件绑定静态度量全过。
- **尚未做（第二阶段）**：战斗引擎/配种/怀孕/探索数值/装备/升级 —— 后端 91 个函数(server.py 4074 行 + 12 模块)需搬成 JS，暂未迁移。
- **部署到 GitHub Pages**：把 web/ 内容推到仓库根，Settings→Pages→main 分支即可在线。（仓库现名仍 derbiren-tavern，改名待定。）
