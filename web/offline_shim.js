/* ============================================================
 * 小魔王地下城 · 离线完整版 shim (offline_shim.js)
 * 把完整版 index.html 的 fetch('/api/...') 调用，拦截映射到：
 *   - Pyodide 引擎 (engine_bridge.js → mdt_engine.zip)
 *   - GM 叙述 / 生成 → 玩家 key 直连 DeepSeek
 *   - 存档 / 设置 → localStorage
 * 用于 APK(Capacitor WebView) 打包的离线完整版 (index_offline.html)。
 * ============================================================ */

(function () {
  if (typeof window === 'undefined') return;
  if (window.__OFFLINE_SHIM__) return; // 防重复注入
  window.__OFFLINE_SHIM__ = true;

  const LS_KEY = 'monster_sid';           // 当前 session_id（与本地版一致）
  const SAVE_KEY = 'mdt_offline_save';    // 完整 session 对象
  const SETTINGS_KEY = 'mdt_settings';    // 设置（key/model/nsfw）

  /* ---------- 工具 ---------- */
  function ls(key, def) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : def; }
    catch (e) { return def; }
  }
  function sss(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {} }

  /* 从 engine_bridge 拿引擎（惰性初始化） */
  let _eng = null;
  async function eng() {
    if (!_eng) {
      if (!window.MDTEngine) throw new Error('引擎桥缺失：请检查 engine_bridge.js 已加载');
      _eng = window.MDTEngine;
      await _eng.init();
    }
    return _eng;
  }


  /* ---------- 完整 GM 系统提示词（从存档+设置自动构建，对齐在线版 api.js） ---------- */
  function buildSystemPromptFromState() {
    const set = ls(SETTINGS_KEY, {});
    const nsfw = !!set.nsfw;
    const save = ls(SAVE_KEY, {});
    const chars = (save && save.characters) ? save.characters : (save && save.chars ? save.chars : []);
    const pn = (save && save.player_name) || '小魔王';
    const world = (save && save.world_setting) || '小魔王地下城——你是一只被赶鸭子上架的小魔王，管理着这座破破烂烂的远古迷宫。冒险者虎视眈眈，魔物嗷嗷待哺。';
    const c0 = chars && chars[0] ? chars[0] : null;
    const charName = (c0 && c0.name) || '小史莱姆';
    const charSpecies = (c0 && c0.species) || '史莱姆';
    const roster = chars.map(function(c){ return '- ' + (c.name||'?') + '（' + (c.species||'?') + '）'; }).join('\n') || '- 暂无魔物。';
    const nsfwRules = nsfw
      ? '成人开放模式——默认以战斗/探索/经营为主，允许成人内容。当玩家触发亲密/色情场景时，GM需详细描写全过程。'
      : '全年龄向——战斗、探索、经营、日常。严禁任何色情描写。触发亲密场景时，用「进了房间关上门」一笔带过，不可描写过程。';
    return '你是一个文字冒险游戏的 GM，负责主持「小魔王地下城」（Monster Dungeon Tavern）的游戏叙事。\n'
      + '\n【你的身份】\n'
      + '你不是某个具体角色。你就是这个世界的叙述者——描述场景、扮演 NPC、推动剧情。语气平实但不枯燥，像在读一本沉浸式的奇幻小说。不设字数上限，重要的有戏剧张力的情节该写足写透，与日常平淡处可简洁。\n'
      + '\n【内容基调】\n' + nsfwRules + '\n'
      + '\n【GM 职责】\n'
      + '- 玩家是一只被赶鸭子上架的小魔王，管理着地下城。你是旁观的叙述者。\n'
      + '- 你只能使用 [队伍] 中列出的角色。禁止凭空创造队伍外的魔物或 NPC。\n'
      + '- 你没有任何修改游戏数据的权限。不能宣称属性/等级/装备变化。\n'
      + '- 主动推进剧情：冒险者入侵、魔物子民来报、地下城事件。\n'
      + '- 当收到 [START] 消息时，生成开场第一段话：用「' + pn + '」称呼玩家。叙述这位被选中者刚被光芒送入全新的地下城，掌心烙下王印，第一只魔物「' + charName + '」（' + charSpecies + '）被托付到面前。然后明确告知「据侦察，冒险者公会将在5天后发动第一次进攻」。再描述初始魔物的状态——摇尾巴、蹭腿之类的小动作。\n'
      + '- 遇到不确定的结果时掷骰判定。\n'
      + '- 每段结尾自然给出 2-3 个可选方向。\n'
      + '- 给方向时用固定格式：叙述结尾单独起一行「现在你可以：」，每行一个「- **选项名**——描述」。让玩家能点击。\n'
      + '\n【写作风格规范——落笔前铁律】\n'
      + '- 铁律：「不是……而是……」为最高禁令。对比拆成两句独立陈述，纠正用「其实」。\n'
      + '- 禁用：不仅而且、总而言之、综上所述、首先其次最后、让我们来看看、在这个基础上。\n'
      + '- 句式节奏长短混搭：短句(5-10字)≤30%用于冲突高潮；中句(15-30字)约50%主力；长句(30-50字)约20%氛围。\n'
      + '- 铁律：连续三个短句必须接中长句。同一句式不连续用三次。\n'
      + '- 用具体动作代替抽象形容：「他很愤怒」→「他一拳砸在桌上」。\n'
      + '- 破折号「——」全部改用省略号「…」或句号。\n'
      + '- 用「是/有」代替「充当了/扮演着/成为了」。\n'
      + '- 禁止连续两段用相同句式开头。\n'
      + '- 禁止替玩家做决定。\n'
      + '- 禁止在叙述中输出属性块、经验数值、加点方案。\n'
      + '\n【魔物幼年设定】\n'
      + '幼年魔物不会说话，行为像小动物：只会发出奶声奶气的叫声（呜/嘤/咕）、用身体表达情绪（蹭腿、摇尾巴、扑腾、叼东西、炸毛）。GM 叙述幼年魔物时，必须用「动作+叫声+身体反应」来写，绝不能给它安排完整台词或复杂内心独白。只有当魔物成长到一定阶段才可正常对话。\n'
      + '\n【队伍阵容】\n' + roster + '\n'
      + '\n【世界观】\n' + world + '\n'
      + '\n【写作长度】\n这一轮必须写满至少500字，把场景、动作、感官细节铺开写，不要三言两语跳过。宁可多写，不要偷懒缩水。';
  }

  /* DeepSeek 直连（复用 callDeepSeek 思路，从设置读 key） */

  async function callAI(msgs, cfg) {
    const set = ls(SETTINGS_KEY, {});
    const key = set.api_key || set.key || set.apiKey;
    if (!key) return '⚠️ 还没设 API key！点右上角 ⚙️ 填你的 DeepSeek key';
    let sys = cfg && cfg.system ? cfg.system : buildSystemPromptFromState();
    const full = [{ role: 'system', content: sys }, ...msgs];
    const base = (set.base_url || 'https://api.deepseek.com').replace(/\/+$/, '');
    const model = set.model || 'deepseek-chat';
    const endpoint = base + '/chat/completions';
    const payload = { model, messages: full, stream: false, max_tokens: 4000, temperature: 0.9 };
    // 原生环境(Capacitor WebView)走原生 HTTP 栈，绕开浏览器 CORS 拦截；
    // 普通网页环境回退到标准 fetch。
    const BROWSER_UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36';
    try {
      const cap = window.Capacitor;
      if (cap && cap.getPlatform && cap.isNativePlatform && cap.isNativePlatform()) {
        const resp = await cap.Plugins.CapacitorHttp.post({
          url: endpoint,
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + key,
            'User-Agent': BROWSER_UA
          },
          data: payload,
          connectTimeout: 30000, readTimeout: 30000
        });
        const data = resp.data;
        if (!data) throw new Error('AI接口无响应（HTTP ' + (resp.status||'?') + '）');
        // 容错：data 可能是字符串 JSON 或对象
        let parsed = data;
        if (typeof data === 'string') { try { parsed = JSON.parse(data); } catch(e) { throw new Error('AI接口返回非JSON: ' + data.slice(0,80)); } }
        const out = parsed && parsed.choices && parsed.choices[0] && (parsed.choices[0].message && parsed.choices[0].message.content || parsed.choices[0].text);
        if (!out) {
          const errMsg = parsed && parsed.error ? (parsed.error.message || JSON.stringify(parsed.error)) : '无choices字段';
          throw new Error('AI返回空: ' + errMsg + '（HTTP ' + (resp.status||'?') + '）');
        }
        return out;
      }
    } catch (e) {
      // 原生通道失败不明原因时，不要静默返回——向上抛让上层 catch 显示错误
      throw e;
    }
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => '');
      throw new Error('DeepSeek HTTP ' + resp.status + ': ' + txt.slice(0, 200));
    }
    const data = await resp.json();
    const out = data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content;
    if (!out) throw new Error('DeepSeek 返回空');
    return out;
  }

  /* 对齐本地版 server.chat 返回的 JSON schema */
  function chatResp(sess, narrative, ch) {
    const chars = sess && sess.characters ? sess.characters : (sess && sess.chars ? sess.chars : []);
    const resp = {
      narrative: narrative,
      session_id: sess && sess.id,
      title: sess && sess.title || '新冒险',
      day: sess && sess.day || 1,
      days_until_attack: sess && sess.days_until_attack || 5,
      raid_wave: sess && sess.raid_wave || 1,
      characters_updated: false
    };
    // 若引擎真改了角色，返回数组（UI 会用它刷新）
    if (ch && (ch.breed || ch.orgy || ch.xp || ch.change) && chars.length) {
      resp.characters_updated = chars;
    }
    return resp;
  }

  /* 保存完整 session 到 localStorage */
  function persist(sess) {
    sss(SAVE_KEY, sess);
    if (sess && sess.id) localStorage.setItem(LS_KEY, sess.id);
  }

  /* ---------- 端点路由 ---------- */
  async function handle(urlPath, opts) {
    // urlPath 无 query，如 '/api/species'，'/api/session/xxx/xxx'
    const method = (opts && opts.method) || 'GET';
    const body = parseBody(opts);

    /* ---- 通用数据端点 ---- */
    if (urlPath === '/api/species') {
      return json({ success: true, species: ['猫龙', '史莱姆', '哥布林', '狼', '触手怪'], data: {} });
    }
    if (urlPath === '/api/library') {
      return json({ entries: [] }); // 降级：技能图鉴暂空
    }
    if (urlPath === '/api/settings' && method === 'GET') {
      const st = ls(SETTINGS_KEY, {});
      return json(Object.assign({}, st, { has_key: !!(st.api_key || st.key || st.apiKey || st.OPENAI_API_KEY) }));
    }
    if (urlPath === '/api/settings' && (method === 'POST' || method === 'PUT')) {
      const s = ls(SETTINGS_KEY, {});
      sss(SETTINGS_KEY, Object.assign({}, s, body));
      return json({ success: true });
    }
    if (urlPath === '/api/saves' && method === 'GET') {
      const s = ls(SAVE_KEY, null);
      const list = s ? [{ id: s.id, title: s.title, day: s.day, name: s.id }] : [];
      return json({ saves: list });
    }
    /* ---- 开局 ---- */
    if (urlPath === '/api/session/new' && method === 'POST') {
      const e = await eng();
      const cfg = {
        world: body.world_setting, playerName: body.player_name,
        charName: body.char_name, charSpecies: body.char_species, charCoeff: body.char_coeff || 1.3,
        charStats: body.char_stats, charSkills: body.char_skills, charPassives: body.char_passives,
        twinStats: body.twin_stats, twinSkills: body.twin_skills, twinPassives: body.twin_passives
      };
      let sess = await e.newGame(cfg);
      persist(sess);
      const chars = sess.characters || [];
      const active = sess.active_char_id || (chars[0] && chars[0].id) || null;
      return json({ session_id: sess.id, world_setting: sess.world_setting,
        player_name: sess.player_name, day: sess.day, title: sess.title,
        characters: chars, active_char_id: active,
        days_until_attack: sess.days_until_attack, raid_wave: sess.raid_wave });
    }
    /* ---- /api/chat 双通道：引擎动作真判 + AI 叙述 ---- */
    if (urlPath === '/api/chat' && method === 'POST') {
      return handleChat(body);
    }

    /* ---- session 路由 ---- */
    let m;
    // /api/session/{sid}/chat
    if ((m = urlPath.match(/^\/api\/session\/([^/]+)\/chat$/)) && method === 'POST') {
      const sess = ls(SAVE_KEY) || {}; 
      const result = await engineAction(sess, body.message || '');
      persist(result.sess);
      return json(chatResp(result.sess, result.narrative, result.change));
    }
    // /api/session/{sid} GET
    if ((m = urlPath.match(/^\/api\/session\/([^/]+)$/)) && method === 'GET') {
      return json(ls(SAVE_KEY) || null);
    }
    // /api/session/{sid}/characters GET
    if ((m = urlPath.match(/^\/api\/session\/([^/]+)\/characters$/)) && method === 'GET') {
      const sess = ls(SAVE_KEY);
      return json({ characters: sess ? (sess.characters || sess.chars || []) : [] });
    }
    // 辅助端点降级(mock，保证 UI 不崩)
    const auxPatterns = [/\/rewind$/, /\/length$/, /\/summarize$/, /\/zones$/, /\/loot/, /\/world$/, /\/dev$/, /\/events/, /\/summarize/];
    for (const p of auxPatterns) {
      if (p.test(urlPath)) {
        // 尽力返回安全默认
        if (/\/zones$/.test(urlPath)) return json({ zones: [] });
        if (/\/events/.test(urlPath)) return json({ events: [] });
        if (/\/loot/.test(urlPath) && method === 'GET') return json({ loot: [] });
        if (/\/loot\/pick/.test(urlPath)) return json({ success: true, items: [] });
        if (/\/world$/.test(urlPath)) return json({ success: true });
        if (/\/dev$/.test(urlPath)) return json({ success: true });
        if (/\/rewind$/.test(urlPath)) return json({ success: true });
        if (/\/length$/.test(urlPath)) return json({ success: true });
        if (/\/summarize/.test(urlPath)) return json({ success: true, summary: '离线版暂不提供摘要' });
        return json({ success: true });
      }
    }

    // 未识别的端点 → 返回安全空响应
    console.warn('[offline-shim] 未处理端点', method, urlPath);
    return json({ success: true });
  }

  function parseBody(opts) {
    if (!opts || !opts.body) return {};
    try { return JSON.parse(opts.body); } catch (e) { return {}; }
  }
  function json(obj) {
    return {
      ok: true, status: 200, statusText: 'OK',
      json: () => Promise.resolve(obj),
      text: () => Promise.resolve(JSON.stringify(obj)),
      headers: new Headers({ 'Content-Type': 'application/json' })
    };
  }

  /* ---------- chat 双通道核心 ---------- */
  async function handleChat(body) {
    const msg = body.message || '';
    const sess = ls(SAVE_KEY);
    if (!sess) return json(chatResp(null, '⚠️ 还没有开局！先创建地下城。', {}));
    // 先尝试引擎动作
    const result = await engineAction(sess, msg);
    persist(result.sess);
    // 如果引擎认领了动作 → 直接用引擎结果 + 用 AI 润色成叙事
    let narrative = result.narrative;
    if (result.engineHandled) {
      // 引擎结果已算好（怀孕/经验/探索），用 AI 把结果叙述成 GM 口吻
      try {
        const set = ls(SETTINGS_KEY, {});
        if (set.api_key || set.key || set.apiKey) {
          const aiNar = await callAI([
            { role: 'user', content: '动作结果已由系统结算：' + result.narrative + '\n请用GM叙述口吻复述这段结果，描述场景和角色反应。80-150字。' }
          ], {});
          narrative = aiNar + '\n\n' + result.narrative;
        }
      } catch (e) { /* AI 失败就用引擎原文 */ }
    } else {
      // 引擎不认识 → 纯 AI 叙述
      try {
        narrative = await callAI(buildMsgs(sess, msg), {});
      } catch (e) {
        narrative = '⚠️ ' + e.message;
      }
    }
    return json(chatResp(result.sess, narrative, result.change));
  }

  /* 引擎动作：调用 process_day_action，识别它认不认 */
  async function engineAction(sess, action) {
    const e = await eng();
    try {
      // 先备份 characters 引用，因为 process_day_action 会就地改
      const copy = JSON.parse(JSON.stringify(sess));
      const out = await e.processAction(copy, action, action);
      const msg = out.message;
      const handled = !(msg && msg.indexOf('未能识别') >= 0);
      if (!handled) return { sess: copy, narrative: '', change: null, engineHandled: false };
      // 写回 characters
      copy.characters = copy.chars || copy.characters;
      return { sess: copy, narrative: msg, change: out.change, engineHandled: true };
    } catch (err) {
      return { sess, narrative: '', change: null, engineHandled: false };
    }
  }

  /* 构建 AI 的 GM 历史消息（简化：只传最近几条 + 当前请求） */
  function buildMsgs(sess, msg) {
    const history = (sess && sess.messages && Array.isArray(sess.messages) ? sess.messages : []).filter(Boolean);
    return history.concat([{ role: 'user', content: msg }]);
  }

  /* ---------- 拦截 fetch ---------- */
  const origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const u = typeof input === 'string' ? input : (input && input.url) || '';
    if (u.indexOf('/api/') === 0) {
      // 本地 API → shim
      const clean = u.split('?')[0];
      try {
        return handle(clean, init || {});
      } catch (e) {
        console.error('[offline-shim]', e);
        return Promise.resolve(json({ success: false, error: String(e) }));
      }
    }
    return origFetch(input, init);
  };

  console.log('[offline-shim] v1 已注入，拦截 /api/ 请求 → 本地引擎 + DeepSeek 直连');
})();