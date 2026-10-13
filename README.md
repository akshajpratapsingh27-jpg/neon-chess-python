# Neon Chess

A futuristic, desktop-first chess experience with an authoritative Python chess service and an interactive HTML/CSS/JavaScript board.

## Implemented phases

- Complete legal move handling for normal moves, captures, castling, en passant, promotion, check, checkmate, stalemate, repetition, and the fifty-move rule.
- Perft regressions for the initial position and Kiwipete plus automated rule/search tests in `tests/`.
- Python alpha-beta engine with iterative deepening, quiescence search, transposition storage, move ordering, timeout-safe board restoration, and positional evaluation.
- Six named playing levels, with custom Python search for levels 1–4 and a Stockfish UCI adapter for levels 5–6.
- Background engine searches with state polling, cancellation, stale-result protection, and engine telemetry.
- SAN notation plus PGN import/export through the API and browser controls.
- Local JSON API with server-authoritative game state.
- WebGL 3D board using Three.js with procedural pieces, orbit camera, camera presets, raycast selection, legal-move markers, board flipping, and automatic 2D fallback.
- Beginner-friendly landing screen with one-click game start, side/strength/time choices, and a focused board view without the distracting move stream.
- Responsive UI with promotion picker, captured material, engine-level selection, FEN import/export, PGN import/export, clocks, accessibility labels, and local game controls.

## Run

```powershell
python run.py
```

Then open <http://127.0.0.1:8765>.

The backend uses only the Python standard library. The optional 3D renderer loads Three.js and OrbitControls from jsDelivr at runtime; if the CDN or WebGL is unavailable, the accessible 2D board remains usable.

## Enable the 2000+ level

Install a current Stockfish Windows build and either:

1. Put `stockfish.exe` in this project directory, `engine/`, or `bin/`; or
2. Set `STOCKFISH_PATH` to the executable path before starting the server:

```powershell
$env:STOCKFISH_PATH = 'C:\path\to\stockfish.exe'
python run.py
```

The API reports whether Stockfish is available. Levels 5 and 6 use Stockfish when it is installed; if it is not installed, they remain visible but disabled in the setup dialog and direct API calls safely fall back to the custom engine for development. This workspace has Stockfish 19 installed through `winget` and the Master smoke test returned a legal move with Stockfish telemetry.

The 2000+ claim still requires a fixed-time automated match benchmark on the target machine. The application does not label an unmeasured local configuration as a certified Elo rating.

## API highlights

- `GET /api/state`
- `GET /api/levels`
- `GET /api/engine/status`
- `GET /api/pgn`
- `POST /api/new`
- `POST /api/move` with `{ "move": "e2e4" }`
- `POST /api/engine/start`
- `POST /api/engine/stop`
- `POST /api/undo`
- `POST /api/resign`
- `POST /api/pgn` with `{ "pgn": "..." }`
- `POST /api/fen` with `{ "fen": "..." }`

For a local strength smoke test, run `python benchmark.py --games 10 --seconds 0.5 --white-level 6 --black-level 6`. The benchmark reports actual backends, engine identities, openings, nodes, and unfinished bounds. Use a larger fixed-time sample before making any Elo claim; a short self-play run is a diagnostic, not an official Elo measurement.

## Checks

```powershell
python -m unittest discover -s tests -v
node --check web\app.js
node --check web\board3d.js
npm run test:browser
```
