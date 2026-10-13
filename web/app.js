const PIECES = {
  K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
  k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟'
};
const NAMES = { q: 'QUEEN', r: 'ROOK', b: 'BISHOP', n: 'KNIGHT' };

const state = {
  board: [],
  legalMoves: [],
  selected: null,
  flipped: false,
  camera: 0,
  showCoordinates: true,
  sound: false,
  moving: false,
  playerColor: 'white',
  lastMove: null,
  fen: '',
  turn: 'white',
  status: 'playing',
  inCheck: false,
  history: [],
  sanHistory: [],
  engineInfo: {},
  engineLevel: 4,
  engineLevelName: 'CLUB',
  engineLevels: [],
  mode3d: true,
  clocks: { white: 600, black: 600 },
  clockBaseline: performance.now(),
  clockTimer: null,
  board3d: null,
  pollTimer: null,
  requestEpoch: 0,
  revision: null,
  gameId: null,
  warning: '',
  actualBackend: '',
  dragging: false,
  soundAvailable: false
};

const landingSelection = {
  playerColor: 'white',
  engineLevel: 4,
  clockSeconds: 600
};

const $ = (id) => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(path, {
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    ...options
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}

async function loadState() {
  const epoch = state.requestEpoch;
  try {
    const next = await request('/api/state');
    if (!acceptState(next, { epoch, allowGameChange: true })) return;
    syncLandingAvailability();
    showLanding();
  } catch (error) {
    if (epoch === state.requestEpoch) showEngineError(error.message);
  }
}

function applyState(next, options = {}) {
  const previousBoard = state.board;
  const previousSelected = state.selected;
  const preserveSelection = Boolean(options.preserveSelection);
  const keepSelection = preserveSelection && previousSelected !== null
    && next.board?.[previousSelected] === previousBoard[previousSelected]
    && next.turn === (next.player_color || state.playerColor)
    && next.status === 'playing';
  const hasRevision = Number.isFinite(Number(next.revision));
  const hasGameId = next.game_id !== undefined || next.gameId !== undefined;
  const nextGameId = next.game_id ?? next.gameId;
  Object.assign(state, {
    board: next.board || [],
    legalMoves: next.legal_moves || [],
    playerColor: next.player_color || 'white',
    lastMove: next.last_move || null,
    fen: next.fen || '',
    turn: next.turn || 'white',
    status: next.status || 'playing',
    inCheck: Boolean(next.in_check),
    history: next.history || [],
    sanHistory: next.san_history || [],
    engineInfo: next.engine_info || {},
    engineLevel: next.engine_level || state.engineLevel,
    engineLevelName: next.engine_level_name || state.engineLevelName,
    clocks: next.clocks || state.clocks,
    clockBaseline: performance.now(),
    engineLevels: next.engine_levels || state.engineLevels,
    selected: keepSelection ? previousSelected : null,
    moving: options.preserveMoving ? state.moving : false,
    revision: hasRevision ? Number(next.revision) : state.revision,
    gameId: hasGameId ? nextGameId : state.gameId,
    warning: next.warning || next.engine_info?.warning || '',
    actualBackend: next.actual_backend || next.engine_info?.actual_backend || next.engine_info?.backend || state.actualBackend
  });
  syncLevelOptions();
  render();
}

function acceptState(next, { epoch = state.requestEpoch, allowGameChange = false, preserveSelection = false, preserveMoving = false } = {}) {
  if (epoch !== state.requestEpoch || !next || typeof next !== 'object') return false;
  const nextGameId = next.game_id ?? next.gameId;
  const gameChanged = state.gameId != null && nextGameId != null && String(state.gameId) !== String(nextGameId);
  if (gameChanged && !allowGameChange) return false;
  const nextRevision = Number(next.revision);
  const currentRevision = Number(state.revision);
  if (!gameChanged && Number.isFinite(nextRevision) && Number.isFinite(currentRevision) && nextRevision < currentRevision) return false;
  applyState(next, { preserveSelection, preserveMoving });
  return true;
}

function clearPolling() {
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

function advanceEpoch() {
  state.requestEpoch += 1;
  clearPolling();
  return state.requestEpoch;
}

function squareName(index) {
  return 'abcdefgh'[index % 8] + (Math.floor(index / 8) + 1);
}

function render() {
  renderBoard();
  render3d();
  updateStatus();
  renderClocks();
}

function renderClocks() {
  const elapsed = (performance.now() - state.clockBaseline) / 1000;
  const clocks = { ...state.clocks };
  if (state.status === 'playing') clocks[state.turn] = Math.max(0, clocks[state.turn] - elapsed);
  const opponent = state.playerColor === 'white' ? 'black' : 'white';
  const clockElements = { white: $('whiteClock'), black: $('blackClock') };
  const playerClock = clockElements[state.playerColor];
  const opponentClock = clockElements[opponent];
  const opponentRow = document.querySelector('.opponent-row');
  const playerRow = document.querySelector('.player-row');
  if (opponentClock.parentElement !== opponentRow) opponentRow.appendChild(opponentClock);
  if (playerClock.parentElement !== playerRow) playerRow.appendChild(playerClock);
  playerClock.textContent = formatClock(clocks[state.playerColor]);
  opponentClock.textContent = formatClock(clocks[opponent]);
  playerClock.dataset.side = state.playerColor;
  opponentClock.dataset.side = opponent;
  playerClock.classList.toggle('active-clock', state.turn === state.playerColor && state.status === 'playing');
  opponentClock.classList.toggle('active-clock', state.turn === opponent && state.status === 'playing');
  $('playerColorLabel').textContent = `${state.playerColor.toUpperCase()} // HUMAN`;
  $('opponentColorLabel').textContent = `${opponent.toUpperCase()} // ENGINE`;
}

function formatClock(seconds) {
  const total = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

function renderBoard() {
  const board = $('board');
  board.innerHTML = '';
  board.classList.toggle('flipped', state.flipped);
  board.classList.toggle('camera-top', state.camera === 1);
  board.classList.toggle('camera-low', state.camera === 2);
  board.dataset.coordinates = state.showCoordinates ? 'on' : 'off';
  const ranks = state.flipped ? [...Array(8).keys()] : [...Array(8).keys()].reverse();
  const files = state.flipped ? [...Array(8).keys()].reverse() : [...Array(8).keys()];
  const orientation = ranks.flatMap((rank) => files.map((file) => rank * 8 + file));

  orientation.forEach((index, displayIndex) => {
    const piece = state.board[index];
    const name = squareName(index);
    const square = document.createElement('button');
    const colorName = piece ? (piece === piece.toUpperCase() ? 'White' : 'Black') : 'empty';
    const pieceName = piece ? ({ k: 'king', q: 'queen', r: 'rook', b: 'bishop', n: 'knight', p: 'pawn' }[piece.toLowerCase()]) : '';
    square.className = 'square';
    square.setAttribute('role', 'gridcell');
    square.setAttribute('aria-label', `${name}, ${piece ? `${colorName} ${pieceName}` : 'empty'}${state.selected === index ? ', selected' : ''}`);
    square.setAttribute('aria-selected', state.selected === index ? 'true' : 'false');
    square.type = 'button';
    square.dataset.index = index;
    square.dataset.file = displayIndex >= 56 ? name[0] : '';
    square.dataset.rank = displayIndex % 8 === 0 ? name[1] : '';
    square.classList.add((index % 8 + Math.floor(index / 8)) % 2 ? 'light' : 'dark');
    if (state.selected === index) square.classList.add('selected');
    if (state.lastMove && (state.lastMove.slice(0, 2) === name || state.lastMove.slice(2, 4) === name)) {
      square.classList.add('last-move');
    }
    if (state.inCheck && piece && piece.toLowerCase() === 'k' && piece === (state.turn === 'white' ? 'K' : 'k')) {
      square.classList.add('in-check');
    }
    const candidate = state.selected === null ? null : state.legalMoves.find(
      (move) => move.slice(0, 2) === squareName(state.selected) && move.slice(2, 4) === name
    );
    if (candidate) square.classList.add(piece ? 'capture' : 'legal');
    square.addEventListener('click', () => selectSquare(index));
    square.addEventListener('dragover', (event) => event.preventDefault());
    square.addEventListener('drop', (event) => {
      event.preventDefault();
      if (state.dragging && state.selected !== null) attemptMove(state.selected, index);
    });

    if (piece) {
      const span = document.createElement('span');
      span.className = `piece ${piece === piece.toUpperCase() ? 'white' : 'black'}`;
      span.textContent = PIECES[piece];
      const canDrag = canHumanAct() && isOwnPiece(piece);
      span.draggable = canDrag;
      if (canDrag) {
        span.addEventListener('dragstart', (event) => {
          state.dragging = true;
          state.selected = index;
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('text/plain', name);
          square.classList.add('selected');
        });
        span.addEventListener('dragend', () => {
          state.dragging = false;
          render();
        });
      } else {
        span.addEventListener('dragstart', (event) => event.preventDefault());
      }
      span.setAttribute('aria-label', `${piece === piece.toUpperCase() ? 'White' : 'Black'} ${piece.toLowerCase()}`);
      square.appendChild(span);
    }
    const rank = document.createElement('span');
    rank.className = 'rank-label';
    rank.textContent = displayIndex % 8 === 0 ? name[1] : '';
    square.appendChild(rank);
    board.appendChild(square);
  });
}

function render3d() {
  if (!state.board3d) return;
  state.board3d.sync({
    board: state.board,
    legalMoves: state.legalMoves,
    selected: state.selected,
    lastMove: state.lastMove,
    flipped: state.flipped,
    inCheck: state.inCheck,
    turn: state.turn,
    canDrag: canHumanAct()
  });
}

function isOwnPiece(piece) {
  return piece && (
    (state.playerColor === 'white' && piece === piece.toUpperCase()) ||
    (state.playerColor === 'black' && piece === piece.toLowerCase())
  );
}

function selectSquare(index) {
  if (!canHumanAct()) return;
  const piece = state.board[index];
  if (state.selected !== null) {
    if (state.selected === index) {
      state.selected = null;
      render();
      return;
    }
    const candidate = state.legalMoves.find(
      (move) => move.slice(0, 2) === squareName(state.selected) && move.slice(2, 4) === squareName(index)
    );
    if (candidate) {
      attemptMove(state.selected, index);
      return;
    }
  }
  if (isOwnPiece(piece)) {
    state.selected = index;
    render();
    setStatus('Piece selected.', 'Choose a highlighted destination.');
  }
}

function attemptMove(from, to) {
  if (!canHumanAct()) return;
  const prefix = squareName(from) + squareName(to);
  const candidates = state.legalMoves.filter((move) => move.startsWith(prefix));
  if (!candidates.length) {
    toast('That move is not available.');
    return;
  }
  if (candidates.length > 1) {
    openPromotion(from, to, candidates);
    return;
  }
  submitMove(candidates[0]);
}

function canHumanAct() {
  return state.status === 'playing'
    && state.turn === state.playerColor
    && !state.moving
    && state.engineInfo?.status !== 'thinking';
}

async function submitMove(move) {
  const epoch = advanceEpoch();
  state.moving = true;
  state.dragging = false;
  state.selected = null;
  renderBoard();
  render3d();
  setStatus('Transmitting move.', 'The position is being updated.');
  try {
    const next = await request('/api/move', {
      method: 'POST',
      body: JSON.stringify({ move })
    });
    if (!acceptState(next, { epoch, allowGameChange: false })) return;
    await maybeStartEngine(epoch);
  } catch (error) {
    if (epoch !== state.requestEpoch) return;
    state.moving = false;
    showEngineError(error.message);
    const refreshed = await request('/api/state').catch(() => null);
    if (refreshed) acceptState(refreshed, { epoch, allowGameChange: true });
  }
}

async function maybeStartEngine(epoch = state.requestEpoch) {
  if (epoch !== state.requestEpoch) return;
  if (state.status !== 'playing' || state.turn === state.playerColor) return;
  setStatus('Neon Core is thinking.', 'Searching tactical continuations…');
  updateSearch('ACTIVE // CALCULATING');
  try {
    const next = await request('/api/engine/start', { method: 'POST', body: '{}' });
    if (!acceptState(next, { epoch, allowGameChange: false, preserveSelection: true, preserveMoving: true })) return;
    if (state.engineInfo?.status === 'thinking') pollEngine(epoch);
  } catch (error) {
    if (epoch === state.requestEpoch) showEngineError(error.message);
  }
}

function pollEngine(epoch = state.requestEpoch) {
  if (epoch !== state.requestEpoch) return;
  clearPolling();
  const poll = async () => {
    if (epoch !== state.requestEpoch) return;
    try {
      const next = await request('/api/engine/status');
      if (!acceptState(next, { epoch, preserveSelection: true, preserveMoving: true })) return;
      if (next.engine_info?.status === 'thinking' && epoch === state.requestEpoch) {
        state.pollTimer = setTimeout(poll, 220);
      }
    } catch (error) {
      if (epoch === state.requestEpoch) showEngineError(error.message);
    }
  };
  poll();
}

function renderMoves() {
  const list = $('moveList');
  if (!list) return;
  const moves = state.sanHistory.length ? state.sanHistory : state.history;
  if (!moves.length) {
    list.innerHTML = '<div class="empty-state">Awaiting first move<span>Make your opening statement.</span></div>';
    return;
  }
  let html = '';
  for (let i = 0; i < moves.length; i += 2) {
    html += `<div class="move-row"><span class="move-number">${String(i / 2 + 1).padStart(2, '0')}</span><span class="move-cell ${i === moves.length - 1 ? 'latest' : ''}">${formatMove(moves[i])}</span><span class="move-cell ${i + 1 === moves.length - 1 ? 'latest' : ''}">${moves[i + 1] ? formatMove(moves[i + 1]) : '—'}</span></div>`;
  }
  list.innerHTML = html;
  list.scrollTop = list.scrollHeight;
}

function formatMove(uci) {
  return /^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci)
    ? `${uci.slice(0, 2)} › ${uci.slice(2, 4)}${uci[4] ? `=${uci[4].toUpperCase()}` : ''}`
    : uci;
}

function updateStatus() {
  document.body.dataset.status = state.status;
  $('positionText').textContent = state.status === 'playing'
    ? `${state.turn.toUpperCase()} TO MOVE`
    : state.status.replaceAll('_', ' ').toUpperCase();

  const info = state.engineInfo || {};
  const isThinking = info.status === 'thinking';
  $('stopEngineButton').textContent = isThinking ? 'STOP' : state.turn !== state.playerColor && state.status === 'playing' ? 'START' : 'STOP';
  updateSearch(isThinking
    ? `DEPTH ${info.depth || 0} // ${(info.nps || 0).toLocaleString()} NPS`
    : info.nodes ? `DEPTH ${info.depth} // ${(info.nps || 0).toLocaleString()} NPS` : info.status === 'error' ? 'ENGINE ERROR' : 'STANDBY');
  const backend = state.actualBackend || info.backend;
  $('confidenceText').textContent = isThinking
    ? `DEPTH ${info.depth || 0}`
    : info.status === 'error' ? 'ERROR'
      : backend === 'custom' ? 'PYTHON CORE'
        : backend === 'stockfish' ? 'STOCKFISH'
          : 'READY';
  $('confidenceBar').style.width = `${Math.min(100, Math.max(8, (info.depth || 0) * 5))}%`;

  if (info.status === 'error') {
    setStatus('Engine error.', info.error || 'The engine is paused. Press START to retry.');
  } else if (state.status === 'playing') {
    if (isThinking) setStatus('Neon Core is thinking.', 'Searching tactical continuations…');
    else if (state.turn === state.playerColor) setStatus('Your move.', 'Select a piece to begin the sequence.');
    else setStatus('Neon Core is ready.', 'The engine controls the next move.');
  } else if (state.status.startsWith('checkmate')) {
    setStatus('Checkmate.', state.status.endsWith('white') ? 'White controls the board.' : 'Black controls the board.');
  } else if (state.status.startsWith('resigned')) {
    setStatus('Sequence resigned.', 'Start a new sequence when you are ready.');
  } else {
    setStatus(state.status.replaceAll('_', ' ').replace(/\b\w/g, (x) => x.toUpperCase()) + '.', 'The sequence has reached a terminal state.');
  }

  const score = (state.board.length ? materialScore() : 0);
  $('materialScore').textContent = `${score >= 0 ? '+' : ''}${score.toFixed(1)}`;
  $('playerColorLabel').textContent = `${state.playerColor.toUpperCase()} // HUMAN`;
  $('opponentColorLabel').textContent = `${(state.playerColor === 'white' ? 'black' : 'white').toUpperCase()} // ENGINE`;
  $('engineIdentity').querySelector('strong').textContent = `NEON CORE // ${state.engineLevelName || 'CLUB'}`;
  const notice = $('engineNotice');
  const fallback = info.fallback || state.warning || (state.engineLevel > 4 && backend === 'custom');
  const noticeText = info.status === 'error'
    ? `ENGINE ERROR // ${info.error || 'search unavailable'}`
    : state.warning
      ? `NOTICE // ${state.warning}`
      : fallback
        ? `FALLBACK // ${info.fallback_reason || 'Python core is active'}`
        : '';
  notice.textContent = noticeText;
  notice.hidden = !noticeText;
  updateCaptured();
  renderMoves();
}

function materialScore() {
  const values = { p: 1, n: 3.2, b: 3.3, r: 5, q: 9, k: 0 };
  return state.board.reduce((score, piece) => {
    if (!piece) return score;
    const value = values[piece.toLowerCase()] || 0;
    return score + (piece === piece.toUpperCase() ? value : -value);
  }, 0);
}

function updateCaptured() {
  const initial = { p: 8, n: 2, b: 2, r: 2, q: 1 };
  const counts = { white: { p: 0, n: 0, b: 0, r: 0, q: 0 }, black: { p: 0, n: 0, b: 0, r: 0, q: 0 } };
  state.board.forEach((piece) => {
    if (piece && piece.toLowerCase() !== 'k') counts[piece === piece.toUpperCase() ? 'white' : 'black'][piece.toLowerCase()]++;
  });
  const symbols = (side) => Object.entries(initial).flatMap(([kind, count]) =>
    Array(Math.max(0, count - counts[side][kind])).fill(PIECES[side === 'white' ? kind.toUpperCase() : kind])
  ).join('');
  $('whiteCaptured').textContent = `WHITE  ${symbols('white')}`;
  $('blackCaptured').textContent = `BLACK  ${symbols('black')}`;
}

function syncLevelOptions() {
  const select = $('levelSelect');
  if (!select || !state.engineLevels.length) return;
  const existing = select.value;
  select.innerHTML = state.engineLevels.map((level) =>
    `<option value="${level.id}" ${level.available ? '' : 'disabled'}>${level.id} // ${level.name} ${level.available ? '' : '// INSTALL STOCKFISH'}</option>`
  ).join('');
  const hasExisting = [...select.options].some((option) => option.value === existing);
  select.value = hasExisting ? existing : String(state.engineLevel || 4);
  const current = state.engineLevels.find((level) => level.id === Number(select.value));
  if (current) $('engineNote').textContent = `${current.description} // ${current.backend === 'stockfish' ? 'STOCKFISH BACKEND' : 'PYTHON CORE'}`;
}

function setStatus(main, sub) {
  $('statusText').textContent = main;
  $('statusSub').textContent = sub;
}

function updateSearch(text) { $('searchText').textContent = text; }

function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2400);
}

function showEngineError(message) {
  state.engineInfo = { ...state.engineInfo, status: 'error', error: message };
  render();
  toast(message);
}

function openPromotion(from, to, candidates) {
  const modal = $('promotionModal');
  const options = $('promotionOptions');
  options.innerHTML = '';
  [...new Set(candidates.map((move) => move[4]))].forEach((promotion) => {
    const button = document.createElement('button');
    button.innerHTML = `<span>${PIECES[state.playerColor === 'white' ? promotion.toUpperCase() : promotion]}</span><small>${NAMES[promotion]}</small>`;
    button.addEventListener('click', () => {
      modal.close();
      submitMove(squareName(from) + squareName(to) + promotion);
    });
    options.appendChild(button);
  });
  modal.showModal();
}

async function newGame(settings) {
  const epoch = advanceEpoch();
  try {
    const next = await request('/api/new', { method: 'POST', body: JSON.stringify(settings) });
    if (!acceptState(next, { epoch, allowGameChange: true })) return;
    showGame();
    toast('New sequence initialized.');
    await maybeStartEngine(epoch);
  } catch (error) {
    if (epoch === state.requestEpoch) showEngineError(error.message);
  }
}

function showLanding() {
  $('landingPanel').hidden = false;
  $('playPanel').hidden = true;
  $('continueGameButton').hidden = !state.history.length;
  $('bottomStrip').hidden = true;
}

function showGame() {
  $('landingPanel').hidden = true;
  $('playPanel').hidden = false;
  $('bottomStrip').hidden = false;
}

function syncLandingAvailability() {
  document.querySelectorAll('[data-landing-level]').forEach((button) => {
    const level = state.engineLevels.find((item) => item.id === Number(button.dataset.landingLevel));
    const unavailable = Boolean(level && !level.available);
    button.disabled = unavailable;
    button.setAttribute('aria-disabled', String(unavailable));
    if (unavailable) button.title = 'Install Stockfish to use this level.';
  });
  if (state.engineLevels.some((level) => level.id === 6 && level.available)) {
    document.querySelector('[data-landing-level="6"]')?.classList.add('available');
  }
}

function startLandingGame() {
  newGame({
    player_color: landingSelection.playerColor,
    engine_level: landingSelection.engineLevel,
    clock_seconds: landingSelection.clockSeconds,
    engine_time: landingSelection.engineLevel >= 6 ? 2.8 : landingSelection.engineLevel >= 4 ? 0.65 : 0.35
  });
}

async function init3d() {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    state.mode3d = false;
    document.body.classList.add('reduced-motion');
    disable3d('3D paused for reduced motion.');
    return;
  }
  try {
    const module = await import('./board3d.js');
    state.board3d = await module.createBoard3D($('board3d'), {
      onSquare: (index) => selectSquare(index),
      onDrag: (from, to) => attemptMove(from, to),
      canDrag: (index) => canHumanAct() && isOwnPiece(state.board[index])
    });
    document.body.classList.add('three-ready');
    document.body.classList.remove('fallback-2d');
    $('boardStage').classList.add('mode-3d');
    render3d();
  } catch (error) {
    disable3d('3D renderer unavailable; using the responsive board.');
    toast('3D renderer unavailable; using the responsive board.');
  }
}

function disable3d(reason) {
  state.mode3d = false;
  document.body.classList.add('fallback-2d');
  $('modeButton').classList.remove('active');
  $('modeButton').setAttribute('aria-disabled', 'true');
  $('modeButton').title = reason;
  $('boardStage').classList.remove('mode-3d');
}

function setupEvents() {
  $('startGameButton').addEventListener('click', startLandingGame);
  $('continueGameButton').addEventListener('click', async () => {
    showGame();
    await maybeStartEngine();
  });
  document.querySelectorAll('[data-landing-color]').forEach((button) => button.addEventListener('click', () => {
    landingSelection.playerColor = button.dataset.landingColor;
    document.querySelectorAll('[data-landing-color]').forEach((item) => item.classList.toggle('active', item === button));
  }));
  document.querySelectorAll('[data-landing-level]').forEach((button) => button.addEventListener('click', () => {
    if (button.disabled) return;
    landingSelection.engineLevel = Number(button.dataset.landingLevel);
    document.querySelectorAll('[data-landing-level]').forEach((item) => item.classList.toggle('active', item === button));
  }));
  document.querySelectorAll('[data-landing-time]').forEach((button) => button.addEventListener('click', () => {
    landingSelection.clockSeconds = Number(button.dataset.landingTime);
    document.querySelectorAll('[data-landing-time]').forEach((item) => item.classList.toggle('active', item === button));
  }));
  $('playNavButton').addEventListener('click', () => {
    if (state.history.length) showGame();
    else showLanding();
  });
  $('newGameButton').addEventListener('click', () => $('newGameModal').showModal());
  $('newGameForm').addEventListener('submit', (event) => {
    if (event.submitter?.value === 'cancel') return;
    event.preventDefault();
    $('newGameModal').close();
    newGame({
      player_color: $('colorSelect').value,
      engine_time: Number($('timeSelect').value),
      clock_seconds: Number($('clockSelect').value),
      engine_level: Number($('levelSelect').value || 4)
    });
  });
  $('levelSelect').addEventListener('change', (event) => {
    const selected = state.engineLevels.find((level) => level.id === Number(event.target.value));
    if (selected) $('engineNote').textContent = `${selected.description} // ${selected.backend === 'stockfish' ? 'STOCKFISH BACKEND' : 'PYTHON CORE'}`;
  });
  $('flipButton').addEventListener('click', () => {
    state.flipped = !state.flipped;
    render();
  });
  $('cameraButton').addEventListener('click', () => {
    state.camera = (state.camera + 1) % 3;
    if (state.board3d) state.board3d.setCamera(state.camera);
    renderBoard();
    toast(['Play camera', 'Top-down clarity', 'Low orbit'][state.camera]);
  });
  $('modeButton').addEventListener('click', () => {
    if (!state.board3d || $('modeButton').getAttribute('aria-disabled') === 'true') {
      toast('The 3D renderer is still loading.');
      return;
    }
    state.mode3d = !state.mode3d;
    $('modeButton').classList.toggle('active', state.mode3d);
    $('boardStage').classList.toggle('mode-3d', state.mode3d);
    if (state.mode3d) state.board3d.resize();
  });
  $('soundButton').addEventListener('click', (event) => {
    if (!state.soundAvailable) {
      toast('Move audio is unavailable in this build.');
      return;
    }
    state.sound = !state.sound;
    event.currentTarget.classList.toggle('active', state.sound);
    toast(state.sound ? 'Sound enabled.' : 'Sound muted.');
  });
  $('coordinatesButton').addEventListener('click', () => {
    state.showCoordinates = !state.showCoordinates;
    document.body.classList.toggle('hide-coordinates', !state.showCoordinates);
    renderBoard();
  });
  $('undoButton').addEventListener('click', async () => {
    const epoch = advanceEpoch();
    try {
      const next = await request('/api/undo', { method: 'POST', body: '{}' });
      if (!acceptState(next, { epoch, allowGameChange: false })) return;
      toast('Last sequence rewound.');
      await maybeStartEngine(epoch);
    } catch (error) {
      if (epoch === state.requestEpoch) showEngineError(error.message);
    }
  });
  $('stopEngineButton').addEventListener('click', async () => {
    const epoch = advanceEpoch();
    try {
      const active = state.engineInfo?.status === 'thinking';
      const next = await request(active ? '/api/engine/stop' : '/api/engine/start', { method: 'POST', body: '{}' });
      if (!acceptState(next, { epoch, preserveSelection: true, preserveMoving: true })) return;
      if (!active && state.engineInfo?.status === 'thinking') pollEngine(epoch);
      toast(active ? 'Engine search stopped.' : 'Engine search started.');
    } catch (error) {
      if (epoch === state.requestEpoch) showEngineError(error.message);
    }
  });
  $('resignButton').addEventListener('click', async () => {
    if (!confirm('Resign this sequence?')) return;
    const epoch = advanceEpoch();
    try {
      const next = await request('/api/resign', { method: 'POST', body: '{}' });
      acceptState(next, { epoch, allowGameChange: false });
    } catch (error) {
      if (epoch === state.requestEpoch) showEngineError(error.message);
    }
  });
  $('copyFenButton').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(state.fen);
      toast('FEN copied to clipboard.');
    } catch {
      toast(state.fen);
    }
  });
  $('loadFenButton').addEventListener('click', async () => {
    const fen = window.prompt('Paste a six-field FEN position:', state.fen);
    if (!fen) return;
    const epoch = advanceEpoch();
    try {
      const next = await request('/api/fen', { method: 'POST', body: JSON.stringify({ fen }) });
      if (!acceptState(next, { epoch, allowGameChange: true })) return;
      toast('FEN position loaded.');
    } catch (error) {
      if (epoch === state.requestEpoch) showEngineError(error.message);
    }
  });
  $('exportPgnButton').addEventListener('click', () => {
    const link = document.createElement('a');
    link.href = '/api/pgn';
    link.download = 'neon-chess-game.pgn';
    link.click();
    toast('PGN export prepared.');
  });
  $('importPgnButton').addEventListener('click', () => $('importPgnInput').click());
  $('importPgnInput').addEventListener('change', async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const epoch = advanceEpoch();
    try {
      const pgn = await file.text();
      const next = await request('/api/pgn', { method: 'POST', body: JSON.stringify({ pgn }) });
      if (!acceptState(next, { epoch, allowGameChange: true })) return;
      toast('PGN imported.');
    } catch (error) {
      if (epoch === state.requestEpoch) showEngineError(error.message);
    } finally {
      event.target.value = '';
    }
  });
  $('settingsButton').addEventListener('click', () => $('newGameModal').showModal());
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      state.selected = null;
      render();
    }
    if (event.key.toLowerCase() === 'f') {
      state.flipped = !state.flipped;
      render();
    }
  });
  document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => {
    if (!button.dataset.tab || button.dataset.tab === 'play') return;
    toast('This module is queued for the next build.');
  }));
}

setupEvents();
loadState();
init3d();
state.clockTimer = setInterval(renderClocks, 200);
