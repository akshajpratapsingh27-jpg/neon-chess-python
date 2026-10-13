const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright-core');

const ROOT = path.resolve(__dirname, '..');
const INITIAL = [
  'RNBQKBNR', 'PPPPPPPP', '', '', '', '', 'pppppppp', 'rnbqkbnr'
].flatMap((rank) => rank ? [...rank] : Array(8).fill(null));

let revision = 0;
let gameNumber = 1;
let game = createGame('white');

function createGame(playerColor) {
  return {
    board: [...INITIAL],
    playerColor,
    turn: 'white',
    history: [],
    sanHistory: [],
    legalMoves: playerColor === 'white' ? ['e2e4'] : [],
    engineStatus: 'ready',
    enginePolls: 0,
    warning: '',
    actualBackend: 'custom',
    clocks: { white: 600, black: 600 }
  };
}

function squareIndex(name) {
  return 'abcdefgh'.indexOf(name[0]) + 8 * (Number(name[1]) - 1);
}

function play(move, san) {
  const from = squareIndex(move.slice(0, 2));
  const to = squareIndex(move.slice(2, 4));
  game.board[to] = game.board[from];
  game.board[from] = null;
  game.history.push(move);
  game.sanHistory.push(san);
  game.turn = game.turn === 'white' ? 'black' : 'white';
  game.legalMoves = game.turn === game.playerColor
    ? game.playerColor === 'white' ? ['e2e4'] : ['e7e5']
    : [];
}

function startEngine() {
  if (game.turn === game.playerColor || game.engineStatus === 'thinking') return;
  game.engineStatus = 'thinking';
  game.enginePolls = 0;
}

function pollEngine() {
  if (game.engineStatus !== 'thinking') return;
  game.enginePolls += 1;
  if (game.enginePolls < 2) return;
  if (game.playerColor === 'black' && game.history.length === 0) play('e2e4', 'e4');
  else if (game.playerColor === 'white' && game.history.length === 1) play('e7e5', 'e5');
  game.engineStatus = 'ready';
}

function snapshot() {
  return {
    fen: 'mock-position',
    board: game.board,
    turn: game.turn,
    status: 'playing',
    in_check: false,
    legal_moves: game.legalMoves,
    history: game.history,
    san_history: game.sanHistory,
    last_move: game.history.at(-1) || null,
    player_color: game.playerColor,
    engine_level: 1,
    engine_level_name: 'BEGINNER',
    engine_available: true,
    stockfish_available: false,
    engine_info: {
      status: game.engineStatus,
      backend: game.actualBackend,
      depth: game.engineStatus === 'thinking' ? 1 : 2,
      nodes: 20,
      nps: 1000
    },
    engine_levels: [
      { id: 1, name: 'BEGINNER', description: 'Simple tactical choices', backend: 'custom', available: true },
      { id: 5, name: 'EXPERT', description: 'Stockfish at controlled strength', backend: 'stockfish', available: false }
    ],
    actual_backend: game.actualBackend,
    warning: game.warning,
    clocks: game.clocks,
    clock_limit: 600,
    revision,
    game_id: `browser-smoke-${gameNumber}`
  };
}

function json(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(body)
  });
  response.end(body);
}

function readBody(request) {
  return new Promise((resolve) => {
    let body = '';
    request.on('data', (chunk) => { body += chunk; });
    request.on('end', () => resolve(body ? JSON.parse(body) : {}));
  });
}

function fenBoard(fen) {
  const board = [];
  for (const row of fen.split(' ')[0].split('/')) {
    for (const value of row) {
      if (/\d/.test(value)) board.push(...Array(Number(value)).fill(null));
      else board.push(value);
    }
  }
  return board;
}

function server() {
  return http.createServer(async (request, response) => {
    const url = new URL(request.url, 'http://127.0.0.1');
    if (url.pathname.startsWith('/api/')) {
      if (request.method === 'GET' && url.pathname === '/api/pgn') {
        const body = '[Event "Browser Smoke"]\n\n1. e4 e5\n';
        response.writeHead(200, { 'Content-Type': 'application/x-chess-pgn', 'Content-Disposition': 'attachment; filename=smoke.pgn' });
        response.end(body);
        return;
      }
      if (request.method === 'GET') {
        if (url.pathname === '/api/engine/status') pollEngine();
        json(response, 200, snapshot());
        return;
      }
      const payload = await readBody(request);
      if (url.pathname === '/api/new') {
        gameNumber += 1;
        revision += 1;
        game = createGame(payload.player_color === 'black' ? 'black' : 'white');
      } else if (url.pathname === '/api/move') {
        revision += 1;
        if (payload.move === 'e2e4') play('e2e4', 'e4');
        else if (payload.move === 'e7e5') play('e7e5', 'e5');
        else return json(response, 400, { error: `Illegal mock move ${payload.move}` });
      } else if (url.pathname === '/api/engine/start') {
        startEngine();
      } else if (url.pathname === '/api/engine/stop') {
        game.engineStatus = 'ready';
      } else if (url.pathname === '/api/undo') {
        revision += 1;
        game = createGame(game.playerColor);
      } else if (url.pathname === '/api/resign') {
        revision += 1;
      } else if (url.pathname === '/api/fen') {
        revision += 1;
        game.board = fenBoard(payload.fen);
        game.turn = payload.fen.split(' ')[1] === 'b' ? 'black' : 'white';
        game.history = [];
        game.sanHistory = [];
        game.legalMoves = [];
        game.engineStatus = 'ready';
      } else if (url.pathname === '/api/pgn') {
        revision += 1;
        game = createGame(game.playerColor);
        play('e2e4', 'e4');
        play('e7e5', 'e5');
      } else {
        return json(response, 404, { error: 'Not found' });
      }
      json(response, 200, snapshot());
      return;
    }

    if (url.pathname === '/favicon.ico') {
      response.writeHead(204);
      response.end();
      return;
    }

    const file = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
    const filePath = path.resolve(ROOT, 'web', file);
    if (!filePath.startsWith(path.resolve(ROOT, 'web')) || !fs.existsSync(filePath)) {
      response.writeHead(404);
      response.end('Not found');
      return;
    }
    const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' };
    response.writeHead(200, { 'Content-Type': types[path.extname(filePath)] || 'application/octet-stream' });
    fs.createReadStream(filePath).pipe(response);
  });
}

async function main() {
  const executablePath = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
  ].find((candidate) => fs.existsSync(candidate));
  if (!executablePath) throw new Error('No supported Chrome/Edge installation found.');

  const httpServer = server();
  await new Promise((resolve) => httpServer.listen(0, '127.0.0.1', resolve));
  const address = httpServer.address();
  const browser = await chromium.launch({ executablePath, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const errors = [];
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });

  try {
    await page.goto(`http://127.0.0.1:${address.port}/`, { waitUntil: 'domcontentloaded' });
    await page.locator('#board button').nth(0).count();
    await page.locator('#landingPanel').waitFor({ state: 'visible' });
    await page.waitForFunction(
      () => document.body.classList.contains('three-ready') || document.body.classList.contains('fallback-2d'),
      null,
      { timeout: 8000 }
    ).catch(() => {});
    assert.equal(await page.locator('#board button').count(), 64);
    assert.equal(await page.locator('#board button').nth(0).getAttribute('data-index'), '56', 'white must be at the bottom');
    assert.match(await page.locator('#board button').nth(0).getAttribute('aria-label'), /^a8,/);
    assert.equal(await page.locator('.square.light').count(), 32, 'squares should use chess colors, not DOM stripes');
    assert.match(await page.locator('#board button').nth(0).getAttribute('aria-label'), /empty|Black/);
    assert.equal(await page.locator('#landingPanel').isVisible(), true, 'landing page should be the first screen');
    assert.equal(await page.locator('#playPanel').isVisible(), false, 'game board should wait for an explicit start');
    assert.equal(await page.locator('.moves-card').count(), 0, 'move stream should not be present');

    await page.locator('#startGameButton').click();
    await page.locator('#playPanel').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#board button').count(), 64);

    const threeReady = await page.locator('body.three-ready').count() > 0;
    if (threeReady) {
      await page.locator('#modeButton').click();
    } else {
      assert.equal(await page.locator('body.fallback-2d').count(), 1, '3D failure should leave an explicit 2D fallback');
    }

    await page.locator('[data-index="12"]').click();
    await page.locator('[data-index="28"]').click();
    await page.locator('button[data-index="28"].last-move').waitFor();
    await page.waitForTimeout(50);
    if ((await page.locator('#confidenceText').innerText()).toLowerCase().includes('depth')) {
      assert.equal(await page.locator('[draggable="true"]').count(), 0, 'drag must be disabled while thinking');
    }
       await page.waitForFunction(() => document.querySelector('button[data-index="36"]')?.classList.contains('last-move'), null, { timeout: 4000 });

    await page.locator('#newGameButton').click();
    const beforeClose = await page.locator('#positionText').innerText();
    await page.locator('#colorSelect').selectOption('black');
    await page.locator('#newGameModal .modal-close').click();
    assert.equal(await page.locator('#newGameModal').getAttribute('open'), null, 'Close should dismiss setup');
    assert.equal(await page.locator('#positionText').innerText(), beforeClose, 'Close must not reset the game');

    await page.locator('#newGameButton').click();
    await page.locator('#colorSelect').selectOption('black');
    await page.locator('#newGameForm .modal-submit').click();
    await page.waitForFunction(() => document.querySelector('button[data-index="28"]')?.classList.contains('last-move'), null, { timeout: 4000 });
    assert.match(await page.locator('#opponentColorLabel').innerText(), /WHITE/);
    assert.match(await page.locator('#playerColorLabel').innerText(), /BLACK/);
    assert.equal(await page.locator('.opponent-row .clock').getAttribute('data-side'), 'white');
    assert.equal(await page.locator('.player-row .clock').getAttribute('data-side'), 'black');

    if (threeReady) {
      await page.locator('#modeButton').click();
      const canvas = page.locator('#board3d');
      const box = await canvas.boundingBox();
      assert.ok(box && box.width > 0 && box.height > 0, '3D canvas should have a visible board-sized surface');
      // Approximate e7 -> e5 in the default camera projection. This exercises
      // the left-piece raycast drag path after the black game auto-start.
      await page.mouse.move(box.x + box.width * 0.65, box.y + box.height * 0.42);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.49, { steps: 3 });
      await page.mouse.up();
      await page.waitForFunction(() => document.querySelector('button[data-index="36"]')?.classList.contains('last-move'), null, { timeout: 4000 });
      await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
    }

    const downloadPromise = page.waitForEvent('download');
    await page.locator('#exportPgnButton').click();
    assert.equal((await downloadPromise).suggestedFilename(), 'smoke.pgn');
    await page.locator('#importPgnInput').setInputFiles({
      name: 'browser-smoke.pgn',
      mimeType: 'text/plain',
      buffer: Buffer.from('[Event "Browser Smoke"]\n\n1. e4 e5\n')
    });
    await page.waitForFunction(() => document.querySelector('button[data-index="36"]')?.classList.contains('last-move'), null, { timeout: 4000 });

    const reducedPage = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    const reducedErrors = [];
    reducedPage.on('pageerror', (error) => reducedErrors.push(error.message));
    reducedPage.on('console', (message) => {
      if (message.type() === 'error') reducedErrors.push(message.text());
    });
    await reducedPage.emulateMedia({ reducedMotion: 'reduce' });
    await reducedPage.goto(`http://127.0.0.1:${address.port}/`, { waitUntil: 'domcontentloaded' });
    await reducedPage.locator('body.reduced-motion').waitFor();
    assert.equal(await reducedPage.locator('#boardStage.mode-3d').count(), 0, 'reduced motion should use 2D mode');
    assert.equal(await reducedPage.locator('#board button').count(), 64);
    assert.deepEqual(reducedErrors, []);
    await reducedPage.close();

    assert.deepEqual(errors, [], `browser errors: ${errors.join('; ')}`);
    console.log(`browser smoke passed on ${executablePath}${threeReady ? ' with 3D initialization' : ' with 2D fallback'}`);
  } finally {
    await browser.close();
    await new Promise((resolve) => httpServer.close(resolve));
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
