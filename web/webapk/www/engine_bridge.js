/* ============================================================
 * 小魔王地下城 · JS ↔ Pyodide Python 引擎桥 (engine_bridge.js)
 * 职责：在浏览器里加载 Pyodide → 挂载 mdt_engine.zip → 提供调用引擎的 JS API。
 * 数据存 localStorage，玩家自带 DeepSeek key 直连。
 * 引擎 = 本地版同一份 Python 逻辑（engine.py + combat/ + consequence_manager）。
 * ============================================================ */

const PYODIDE_CDN = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js';
const ENGINE_ZIP = 'mdt_engine.zip';
const SAVE_KEY = 'mdt_save_v1';
const SETTINGS_KEY = 'mdt_settings';

// 存档结构对齐本地版 server.new_session()：characters / active_char_id / day / messages
const EMPTY_SAVE = {
  id: null, title: '新冒险', world_setting: '',
  player_name: '小魔王', day: 1, days_until_attack: 5, raid_wave: 1,
  events: [], messages: [], characters: [], active_char_id: null,
  constructions: [], explored_today: [], unlocked_equipment: [],
};

const MDTEngine = {
  _py: null,           // pyodide 实例
  _ready: false,
  _stdout: [],

  /* —— 生命周期 —— */
  async init() {
    if (this._ready) return this._py;
    if (!window.loadPyodide) {
      await new Promise((res, rej) => {
        const sc = document.createElement('script');
        sc.src = PYODIDE_CDN;
        sc.onload = res; sc.onerror = () => rej(new Error('Pyodide CDN 加载失败，请检查网络'));
        document.head.appendChild(sc);
      });
    }
    const py = await loadPyodide();
    // 捕获 Python print
    py.setStdout({ batched: (s) => { this._stdout.push(s); } });

    // 拉取引擎 zip 并解压
    const resp = await fetch(ENGINE_ZIP);
    if (!resp.ok) throw new Error('引擎包加载失败 HTTP ' + resp.status);
    const buf = await resp.arrayBuffer();

    py.FS.mkdir('/mdt');
    py.FS.chdir('/mdt');
    py.unpackArchive(new Uint8Array(buf), 'zip');

    await py.runPythonAsync(`
import sys, json
sys.path.insert(0, '/mdt')
import engine
def _snapshot(sess):
    # 返回可序列化的 session 副本（去重、纯 dict）
    return json.loads(json.dumps(sess, ensure_ascii=False, default=str))
`);
    this._py = py;
    this._ready = true;
    return py;
  },

  /* —— 存档 (localStorage) —— */
  loadSave() {
    try { const s = localStorage.getItem(SAVE_KEY); if (s) return JSON.parse(s); } catch (e) {}
    return null;
  },
  saveGame(g) { localStorage.setItem(SAVE_KEY, JSON.stringify(g)); },
  clearSave() { localStorage.removeItem(SAVE_KEY); },
  loadSettings() {
    try { return JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'); } catch (e) { return {}; }
  },
  saveSettings(s) { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); },

  /* —— 引擎调用（都 await init） —— */
  async _run(code) {
    await this.init();
    this._clearOut();
    return await this._py.runPythonAsync(code);
  },

  /* 新游戏：用 Python engine 造开局角色（和本地版一致） */
    async newGame(cfg) {
      // cfg: { world, playerName, charName, charSpecies, charCoeff, charStats, charSkills, charPassives, twinStats, twinSkills, twinPassives }
      await this.init();
      this._clearOut();
      const py = this._py;
      const args = {
        world: cfg.world || '', player: cfg.playerName || '小魔王',
        cname: cfg.charName || '小魔王', cspecies: cfg.charSpecies || '人类',
        ccoeff: cfg.charCoeff || 1.3,
        charStats: cfg.charStats || null, charSkills: cfg.charSkills || null, charPassives: cfg.charPassives || null,
        twinStats: cfg.twinStats || null, twinSkills: cfg.twinSkills || null, twinPassives: cfg.twinPassives || null
      };
      const jsonArgs = JSON.stringify(args).replace(/\"/g, '\\"');
      const code = `
  import json
  _args = json.loads("${jsonArgs}")
  _sess = engine.new_session(
      world_setting=_args.get("world",""), player_name=_args.get("player","小魔王"),
      char_name=_args.get("cname","小魔王"), char_species=_args.get("cspecies","人类"),
      char_coeff=_args.get("ccoeff",1.3),
      char_stats=_args.get("charStats"), char_skills=_args.get("charSkills"), char_passives=_args.get("charPassives"),
      twin_stats=_args.get("twinStats"), twin_skills=_args.get("twinSkills"), twin_passives=_args.get("twinPassives"),
  )
  _sess["id"] = "offline_" + str(_args.get("player",""))[:6]
  print(json.dumps(_snapshot(_sess), ensure_ascii=False))
  `;
    const out = await py.runPythonAsync(code);
    // stdout 里取最后一行 JSON
    const rows = this._stdout.join('\n').split('\n');
    const jsonLine = rows.findLast ? rows.findLast(r => r.trim().startsWith('{')) :
      rows.filter(r => r.trim().startsWith('{')).pop();
    try { return JSON.parse(jsonLine); } catch (e) { throw new Error('引擎开局返回异常: ' + rows.join(' → ')); }
  },

  /* 处理一条行动（配种/淫趴/探索/锻炼……）返回 {message, save} */
  async processAction(save, actionText, userMsg) {
    await this.init();
    this._clearOut();
    const py = this._py;
    const saveJson = JSON.stringify(save).replace(/"/g, '\\"');
    const actionEsc = (actionText || '').replace(/"/g, '\\"').replace(/'/g, "\\'");
    const userEsc = (userMsg || '').replace(/"/g, '\\"').replace(/'/g, "\\'");
    const code = `
import json
_save = json.loads("${saveJson}")
_act = "${actionEsc}"
_umsg = "${userEsc}"
_msg, _chg = engine.process_day_action(_save, _act, _umsg)
print(json.dumps({"message": _msg, "save": _save, "change": _chg}, ensure_ascii=False))
`;
    await py.runPythonAsync(code);
    const rows = this._stdout.join('\n').split('\n');
    const jsonLine = rows.filter(r => r.trim().startsWith('{')).pop();
    try {
      const data = JSON.parse(jsonLine);
      return { message: data.message, save: data.save, change: data.change };
    } catch (e) {
      throw new Error('引擎行动返回异常: ' + rows.join(' → '));
    }
  },

  /* 每日结算：生育检查 + 天数推进 */
  async advanceDay(save) {
    await this.init();
    this._clearOut();
    const py = this._py;
    const saveJson = JSON.stringify(save).replace(/"/g, '\\"');
    const code = `
import json
_save = json.loads("${saveJson}")
_births = engine.check_births(_save, _save.get("characters", _save.get("chars", [])))
_msg = "\\n".join(_births) if _births else ""
print(json.dumps({"message": _msg, "save": _save}, ensure_ascii=False))
`;
    await py.runPythonAsync(code);
    const rows = this._stdout.join('\n').split('\n');
    const jsonLine = rows.filter(r => r.trim().startsWith('{')).pop();
    try { return JSON.parse(jsonLine); } catch (e) { throw new Error('每日结算异常: ' + rows.join(' → ')); }
  },

  /* 重置 stdout 缓冲（每次调用前清） */
  _clearOut() { this._stdout.length = 0; },
};

if (typeof window !== 'undefined') window.MDTEngine = MDTEngine;