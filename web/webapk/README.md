# 小魔王地下城 — Android APK (Capacitor + Pyodide)

This directory builds the **fully-offline Android APK** of the game. It bundles the same
game engine that `server.py` runs, compiled to Python/WebAssembly via **Pyodide**, and
serves it from Capacitor's WebView. The backend is replaced by a JS shim
(`www/offline_shim.js`) that routes:

- `fetch('/api/...')` → **Pyodide engine** (game logic, combat, breeding, saves — all local)
- LLM calls → **DeepSeek direct** from the browser (no server)

## Prerequisites

- **Node.js 18+** (for Capacitor CLI)
- **JDK 21** (AGP 8.x requires 21 — JDK 17 will fail with "无效的源发行版:21")
- **Android SDK** with platform 34 + build-tools 34 (`ANDROID_HOME` set)

## Build

```bash
cd web/webapk
npm install                 # installs @capacitor/cli, android, core
npx cap sync android        # copies www/ → android/assets/public
cd android
export JAVA_HOME=<jdk21-path>     # e.g. C:\...\jdk-21.0.xyz
export ANDROID_HOME=<android-sdk> # e.g. C:\...\android-sdk
./gradlew assembleDebug --no-daemon
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk`

## Version discipline

Every change to `www/index.html` must **bump all three** before `cap sync` + `gradlew`:

1. `APP_VERSION` in `www/index.html` (JS constant)
2. The footer version `<div>` in `www/index.html`
3. (Optional) `package.json` / `capacitor.config.json`

Users confirm the new build by reading the footer version. Missing a bump = "还在旧版" reports.

## Key files

| File | Role |
|------|------|
| `www/index.html` | Full offline UI (vanilla JS, mobile drawer layout) |
| `www/offline_shim.js` | Fetch interceptor → Pyodide engine / DeepSeek direct |
| `www/engine_bridge.js` | JS ↔ Pyodide bridge (new_session, breed, save, load) |
| `www/mdt_engine.zip` | Bundled game engine (19 files, incl. `engine.py` + `combat/`) |
| `www/api.js` | Direct DeepSeek call helper (used by shim) |

## Known pitfalls

- **Pyodide in-file offline** — engine loads from `mdt_engine.zip` inside the app; no CDN needed.
- **cap sync copies `www/`** — always `npx cap sync` after editing `www/`, then rebuild.
- **Clean gradle issues** — `./gradlew clean` if incremental build gives stale resources.