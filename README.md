# Dungeon Tavern (小魔王地下城)

A dual-platform AI-powered text adventure dungeon manager — a web app **and** an Android APK.

Built as a dungeon-lord management roguelite: train your monsters, build defenses,
patrol for recruits, and fend off waves of adventurers. Everything is narrated by an
OpenAI-compatible LLM (default: DeepSeek), which acts as a dungeon master / narrator.

<!--
  AGENT-READABLE HEADER
  Entry: server.py (FastAPI, default port 8099)
  Dependencies: fastapi, uvicorn, openai, httpx, python-dotenv
  Python: 3.10+
  LLM: OpenAI-compatible (default deepseek-chat)
  State: JSON files in saves/ directory
  Frontend: index.html (zero-dependency vanilla JS)
-->

[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-green)](https://www.python.org/)
[![Release](https://img.shields.io/badge/release-v2.43.0-purple)](https://github.com/Newtonsword/derbiren-tavern/releases)

## Platform Overview

| Platform | Entry | How to run |
|----------|-------|------------|
| **Desktop / Web** | `server.py` + `index.html` | Run FastAPI backend, open in browser |
| **Android APK** | `web/webapk/` (Capacitor + Pyodide) | Build once, install — fully offline |

The desktop version runs a full Python backend with all 43 API endpoints. The Android
version ships an offline build that runs the same game engine in the browser via Pyodide
(WebAssembly), talking to the LLM directly — no server needed.

## Quick Start (Desktop)

```bash
git clone https://github.com/Newtonsword/derbiren-tavern.git
cd derbiren-tavern
pip install -r requirements.txt
cp .env.example .env          # add your API key (free: platform.deepseek.com)
python server.py               # → http://127.0.0.1:8099
```

## Quick Start (Android APK)

```bash
cd web/webapk
npm install
npx cap sync android
cd android
# requires JDK 21 + Android SDK; see web/webapk/README.md
./gradlew assembleDebug --no-daemon
# → android/app/build/outputs/apk/debug/app-debug.apk (install on your phone)
```

The APK is **fully offline**: no server, no backend, no network dependency for game logic
(exceptions: you supply an LLM API key in the settings page for narration; Pyodide runs the
engine locally in WebAssembly).

## Game Overview

You're a fledgling dungeon lord. Adventurers are coming in a few days. Train your monsters,
patrol for recruits, and fight off waves of invaders. The narrator (an AI dungeon master)
drives all narrative, combat, and NPC dialogue.

## Features

- **AI Narrator** — OpenAI-compatible LLM drives all narrative, combat, and NPC dialogue
- **8 Playable Species** — Cat-Dragon, Hatchling, Tentacle, Gargoyle, Killer Rabbit, Wolf, Slime, Goblin — each with unique lore and skill themes
- **Dynamic Skill Generation** — AI creates new skills each time; every species gets distinct active/passive abilities
- **Day System** — Train, patrol, rest, research, or breed. Days tick toward the next raid
- **Recruitment** — Patrolling has a 35% chance to find wild monsters (8 unique recruits with personalities)
- **3-Wave Raid System** — Lv.3 rookie → Lv.4 squad of 5 → Lv.10 warrior-archer-mage trio
- **Multi-Character Combat** — Any number of allies vs enemies with full formula calculation
- **Detailed Character Panel** — 7 attributes, free point allocation, skill management, level tracking

## Combat System

**7 Attributes:** END (HP, stamina) · STR (physical damage) · SPD (accuracy, dodge, interval) · DEF (damage reduction) · INT (magic) · MP (mana pool) · WIL (morale)

**Hit Resolution:** `d100 ≤ final_hit_rate` → hit (no random damage — formulas only)
- Melee hit: `50 + SPD×3.0 + STR×0.8`
- Ranged hit: `50 + SPD×3.5 + INT×0.5`
- Magic hit: `55 + INT×2.5 + SPD×1.0`

**Damage:** `base + Σ(attr × coefficient)` — STR×2.0, SPD×1.5, END×0.8, INT×1.2, MP×0.5

**Three Damage Types:** Pierce (45% pen, high armor shred) · Blunt (30% pen + 25% ignore, consistent) · Slash (×1.15 multiplier, scales vs light armor)

**Defense:** `DEF / (DEF + 15)` percentage reduction · Armor = extra HP layer on equipment

**Derived:** HP = END×200 · Stamina = END×50 · Mana = MP×20 · Morale HP = WIL×10

**Levels:** `EXP needed = 300 × 1.2^(LV-1)` · 1 skill point per 3 levels · 5 species tiers affect growth

## Configuration (`.env`)

| Variable | Required | Default |
|----------|----------|---------|
| `OPENAI_API_KEY` | **Yes** | — |
| `OPENAI_BASE_URL` | No | `https://api.deepseek.com` |
| `LLM_MODEL` | No | `deepseek-chat` |
| `LLM_TEMPERATURE` | No | `0.85` |
| `LLM_MAX_TOKENS` | No | `1024` |
| `WEB_PORT` | No | `8099` |
| `SSL_VERIFY` | No | `false` (Windows) |

For the Android build, the same variables are set in the in-app **Settings** page (API key
required for narration; game logic runs offline via Pyodide).

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/session/new` | Create game session (params: `player_name`, `char_species`, `char_name`) |
| `POST` | `/api/chat` | Send player input → returns AI narrative |
| `GET` | `/api/session/{id}` | Full session state (characters, day, raid status) |
| `POST` | `/api/session/{id}/characters/{cid}/skills/generate` | AI-generate 3 active + 1 passive skills |
| `PUT` | `/api/settings` | Update API key/model at runtime |
| `GET` | `/api/species` | Species lore and stat templates |
| `GET` | `/api/library` | Encountered characters + skill templates |

## File Structure

```
dungeon-tavern/
├── server.py              # FastAPI backend — all game logic
├── index.html             # Desktop frontend (vanilla JS, zero deps)
├── recruits.json          # Pool of recruitable monsters
├── species_lore.json      # Detailed lore for playable species
├── skill_library.json     # Skill template reference
├── requirements.txt       # Python dependencies
├── .env.example           # Configuration template
├── saves/                 # JSON session files (auto-created)
├── web/
│   ├── index.html         # Online web build (PWA)
│   ├── offline_shim.js    # Fetch interceptor → Pyodide engine (offline)
│   ├── engine_bridge.js   # JS ↔ Pyodide bridge
│   ├── mdt_engine.zip     # Bundled game engine (Pyodide)
│   └── webapk/            # Capacitor Android project
│       ├── capacitor.config.json
│       └── www/           # APK frontend (full UI + offline engine)
└── README.md
```

## Testing

- `tests/` — Python unit tests (breeding, exp, combat systems)
- `web/pyodide_test.html` / `web/bridge_test.html` — run in a browser to verify the Pyodide offline engine loads and plays

## License

MIT — build on it freely. If your friend has fun, tell Newt. (￣▽￣)🔥