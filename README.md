# Derbiren Tavern

<!--
  v2.9 · AGENT-READABLE HEADER
  Entry: server.py (FastAPI, default port 8099)
  Dependencies: fastapi, uvicorn, openai, httpx, python-dotenv
  Python: 3.10+
  LLM: OpenAI-compatible (default deepseek-chat)
  State: JSON files in saves/ directory
  Frontend: index.html (zero-dependency vanilla JS)
-->

AI-powered text adventure web app. A tsundere furry demon GM runs your dungeon — build monsters, fight adventurer raids, and recruit creatures to your cause.

[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-green)](https://www.python.org/)
[![Release](https://img.shields.io/badge/release-v2.9.0-purple)](https://github.com/Newtonsword/derbiren-tavern/releases)

## Quick Start

```bash
git clone https://github.com/Newtonsword/derbiren-tavern.git
cd derbiren-tavern
pip install -r requirements.txt
cp .env.example .env          # add your API key (free: platform.deepseek.com)
python server.py               # → http://127.0.0.1:8099
```

## What It Is

You're a fledgling dungeon lord. Adventurers are coming in 5 days. Train your monsters, patrol for recruits, and fight off waves of invaders. The GM — **Derbiren**, a bratty black-furred demon — narrates everything with sarcasm and occasional fire.

## Features

- **AI GM** — OpenAI-compatible LLM drives all narrative, combat, and NPC dialogue
- **8 Playable Species** — Cat-Dragon, Hatchling, Tentacle, Gargoyle, Killer Rabbit, Wolf, Slime, Goblin — each with unique lore and skill themes
- **Dynamic Skill Generation** — AI creates new skills each time; every species gets distinct active/passive abilities
- **Day System** — Train, patrol, rest, research, or breed. Days tick toward the next raid
- **Recruitment** — Patrolling has a 35% chance to find wild monsters (8 unique recruits with personalities)
- **3-Wave Raid System** — Lv.3 rookie → Lv.4 squad of 5 → Lv.10 warrior-archer-mage trio
- **Multi-Character Combat** — Up to 4v4 battles with full formula calculation
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
derbiren-tavern/
├── server.py              # FastAPI backend — all game logic
├── index.html             # Single-page frontend (vanilla JS, zero deps)
├── recruits.json          # Pool of 8 recruitable monsters
├── species_lore.json      # Detailed lore for 8 playable species
├── skill_library.json     # Skill template reference
├── derbiren_persona.md    # GM personality definition
├── requirements.txt       # Python dependencies
├── .env.example           # Configuration template
├── saves/                 # JSON session files (auto-created)
└── README.md
```

## For Hermes Agents

This project is designed to be AI-agent-operable:

- **Single-file backend** — `server.py` contains all logic; modify with `patch` or `write_file`
- **Stateless API** — Every endpoint is RESTful; session state in `saves/{session_id}.json`
- **Hot reload** — Kill + restart `python server.py` to pick up code changes
- **Port** — Default 8099; check `netstat -ano | findstr :8099` if occupied
- **Model** — Set `LLM_MODEL=deepseek-chat` in `.env` (v4-pro doesn't support structured output)
- **Testing** — `combat_test.py` in `output/` simulates full raid waves with attribute math

## License

MIT — do whatever you want. If your friend has fun, tell Newt to let Derbiren know. (￣▽￣)🔥
