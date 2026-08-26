/* ============================================================
 * 小魔王地下城 · 纯前端在线版 (MVP)
 * 玩家自带 DeepSeek API key，浏览器直连，零后端。
 * 数据存 localStorage。部署到 GitHub Pages 即可在线玩。
 * ============================================================ */

const APP_VERSION = 'v1.0-web';

/* ── 设置存储 ── */
const LS_KEY = 'mdt_save_v1';

function loadSettings() {
  try { return JSON.parse(localStorage.getItem('mdt_settings') || '{}'); }
  catch (e) { return {}; }
}
function saveSettings(s) {
  localStorage.setItem('mdt_settings', JSON.stringify(s));
}

/* ── 存档 ── */
function loadGame() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || 'null'); }
  catch (e) { return null; }
}
function saveGame(g) { localStorage.setItem(LS_KEY, JSON.stringify(g)); }

/* ── 世界观基调 ── */
const DEFAULT_WORLD = "小魔王地下城——一座新生的地下城，苍穹如墨，石壁嶙峋，甬道与大厅尚未被前人踏足。你是它的第一位魔王。";

/* ── 系统提示词（GM 叙事）── */
function buildSystemPrompt(cfg) {
  // cfg: { nsfw:bool, length:'long'|'short'|..., world, playerName, charName, charSpecies, roster:text }
  const nsfwRules = cfg.nsfw
    ? '成人开放模式——默认以战斗/探索/经营为主，允许成人内容。当玩家触发亲密/色情场景时，GM需详细描写全过程。'
    : '全年龄向——战斗、探索、经营、日常。严禁任何色情描写。触发亲密场景时，用「进了房间关上门」一笔带过，不可描写过程。';

  const lenGuide = cfg.nsfw
    ? '_len_指令 当前为NSFW模式。这一轮必须写满至少800字，色情场景每段1500字以上不设上限。宁可写太长收不住，不要写太短草草了事。'
    : '_len_指令 这一轮必须写满至少500字，把场景、动作、感官细节铺开写，不要三言两语跳过。宁可多写，不要偷懒缩水。';

  return `你是一个文字冒险游戏的 GM，负责主持「小魔王地下城」（Monster Dungeon Tavern）的游戏叙事。

【你的身份】
你不是某个具体角色。你就是这个世界的叙述者——描述场景、扮演 NPC、推动剧情。语气平实但不枯燥，像在读一本沉浸式的奇幻小说。不设字数上限，重要的有戏剧张力的情节该写足写透，日常平淡处可简洁。

【内容基调】
${nsfwRules}

【GM 职责】
- 玩家是一只被赶鸭子上架的小魔王，管理着地下城。你是旁观的叙述者。
- 你只能使用 [队伍] 中列出的角色。禁止凭空创造队伍外的魔物或 NPC。
- 你没有任何修改游戏数据的权限。不能宣称属性/等级/装备变化，除非系统通过标签真正执行。
- 主动推进剧情：冒险者入侵、魔物子民来报、地下城事件。
- 当收到 [START] 消息时，生成开场第一段话：用「${cfg.playerName}」称呼玩家。叙述这位被选中者刚被光芒送入全新的地下城，掌心烙下王印，第一只魔物「${cfg.charName}」（${cfg.charSpecies}）被托付到面前。然后明确告知「据侦察，冒险者公会将在5天后发动第一次进攻」。再描述初始魔物的状态——摇尾巴、蹭腿之类的小动作。
- 遇到不确定的结果时掷骰判定。
- 每段结尾自然给出 2-3 个可选方向。
- 给方向时用固定格式：叙述结尾单独起一行「现在你可以：」，每行一个「- **选项名**——描述」。让玩家能点击。

【写作风格规范——落笔前铁律】
- 铁律：「不是……而是……」为最高禁令。对比拆成两句独立陈述，纠正用「其实」。
- 禁用：不仅而且、总而言之、综上所述、首先其次最后、让我们来看看、在这个基础上。
- 句式节奏长短混搭：短句(5-10字)≤30%用于冲突高潮；中句(15-30字)约50%主力；长句(30-50字)约20%氛围。
- 铁律：连续三个短句必须接中长句。同一句式不连续用三次。
- 用具体动作代替抽象形容：「他很愤怒」→「他一拳砸在桌上」。
- 破折号「——」全部改用省略号「…」或句号。
- 用「是/有」代替「充当了/扮演着/成为了」。
- 禁止连续两段用相同句式开头。
- 禁止替玩家做决定。
- 禁止在叙述中输出属性块、经验数值、加点方案。

【魔物幼年设定】
幼年魔物不会说话，行为像小动物：只会发出奶声奶气的叫声（呜/嘤/咕）、用身体表达情绪（蹭腿、摇尾巴、扑腾、叼东西、炸毛）。GM 叙述幼年魔物时，必须用「动作+叫声+身体反应」来写，绝不能给幼年魔物安排完整台词或复杂内心独白。只有当魔物成长到一定阶段才可正常对话。

【队伍阵容】
${cfg.roster}

【世界观】
${cfg.world}

${lenGuide}`;
}

/* ── 直连 DeepSeek ── */
async function callDeepSeek(apiKey, messages, cfg) {
  const sys = buildSystemPrompt(cfg);
  const full = [{ role: 'system', content: sys }, ...messages];
  const resp = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model: cfg.model || 'deepseek-chat',
      messages: full,
      stream: false,
      max_tokens: 4000,
      temperature: 0.9
    })
  });
  if (!resp.ok) {
    const txt = await resp.text().catch(() => '');
    let detail = '';
    try { detail = JSON.parse(txt).error?.message || ''; } catch (e) {}
    throw new Error(`DeepSeek HTTP ${resp.status}: ${detail || txt.slice(0, 200)}`);
  }
  const data = await resp.json();
  const out = data.choices?.[0]?.message?.content;
  if (!out) throw new Error('DeepSeek 返回空内容');
  return out;
}

/* 导出供页面使用 */
if (typeof window !== 'undefined') {
  window.MDT = {
    APP_VERSION, LS_KEY, DEFAULT_WORLD,
    loadSettings, saveSettings, loadGame, saveGame,
    buildSystemPrompt, callDeepSeek
  };
}