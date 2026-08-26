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

  /* DeepSeek 直连（复用 callDeepSeek 思路，从设置读 key） */
  async function callAI(msgs, cfg) {
    const set = ls(SETTINGS_KEY, {});
    const key = set.api_key || set.key || set.apiKey;
    if (!key) return '⚠️ 还没设 API key！点右上角 ⚙️ 填你的 DeepSeek key';
    let sys = cfg && cfg.system ? cfg.system : '你是一个文字冒险游戏的 GM，主持「小魔王地下城」的叙事。描述场景、扮演NPC、推动剧情。';
    const full = [{ role: 'system', content: sys }, ...msgs];
    const base = (set.base_url || 'https://api.deepseek.com').replace(/\/+$/, '');
    const model = set.model || 'deepseek-chat';
    const endpoint = base + '/chat/completions';
    const payload = { model, messages: full, stream: false, max_tokens: 4000, temperature: 0.9 };
    // 原生环境(Capacitor WebView)走原生 HTTP 栈，绕开浏览器 CORS 拦截；
    // 普通网页环境回退到标准 fetch。
    try {
      const cap = window.Capacitor;
      if (cap && cap.getPlatform && cap.isNativePlatform && cap.isNativePlatform()) {
        const resp = await cap.Plugins.CapacitorHttp.post({
          url: endpoint,
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
          data: payload,
          connectTimeout: 30000, readTimeout: 30000
        });
        const data = resp.data;
        const out = data && data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content;
        if (!out) throw new Error('DeepSeek 返回空');
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
    const msgs = [[...sess.messages || []], { role: 'user', content: msg }].filter(Boolean);
    return msgs;
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