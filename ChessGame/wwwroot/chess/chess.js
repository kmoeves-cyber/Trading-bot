'use strict';

// ── Piece Unicode glyphs ─────────────────────────────────────────────────────
const GLYPHS = {
  wK: '♔', wQ: '♕', wR: '♖', wB: '♗', wN: '♘', wP: '♙',
  bK: '♚', bQ: '♛', bR: '♜', bB: '♝', bN: '♞', bP: '♟',
};
const glyph = (piece) => piece ? (GLYPHS[piece.color + piece.type] || '?') : '';

// ── Column labels for move log ────────────────────────────────────────────────
const COL_LABELS = ['a','b','c','d','e','f','g','h'];
const toNotation = (row, col) => COL_LABELS[col] + (8 - row);

// ── GameClient — API wrapper ──────────────────────────────────────────────────
const GameClient = {
  gameId: null,
  state: null,

  async newGame() {
    const res = await fetch('/api/chess/new', { method: 'POST' });
    const data = await res.json();
    this.gameId = data.game_id;
    this.state = data;
    return data;
  },

  async getState() {
    const res = await fetch(`/api/chess/state?game_id=${this.gameId}`);
    const data = await res.json();
    this.state = data;
    return data;
  },

  async getLegalMoves(row, col) {
    const res = await fetch(`/api/chess/moves?game_id=${this.gameId}&row=${row}&col=${col}`);
    const data = await res.json();
    return data.moves || [];
  },

  async makeMove(fromRow, fromCol, toRow, toCol, promotion = null) {
    const res = await fetch('/api/chess/move', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        game_id: this.gameId,
        from_row: fromRow, from_col: fromCol,
        to_row: toRow, to_col: toCol,
        promotion,
      }),
    });
    const data = await res.json();
    if (data.ok) this.state = data.state;
    return data;
  },

  async resign(color) {
    const res = await fetch('/api/chess/resign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game_id: this.gameId, color }),
    });
    const data = await res.json();
    if (data.ok) this.state = data.state;
    return data;
  },
};

// ── UIRenderer ────────────────────────────────────────────────────────────────
const UIRenderer = {
  boardEl: null,
  squares: [],  // [row][col] → div

  init() {
    this.boardEl = document.getElementById('chess-board');
    this.squares = Array.from({ length: 8 }, () => new Array(8));
    this.boardEl.innerHTML = '';

    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        const sq = document.createElement('div');
        sq.className = 'square ' + ((r + c) % 2 === 0 ? 'light' : 'dark');
        sq.dataset.row = r;
        sq.dataset.col = c;
        this.boardEl.appendChild(sq);
        this.squares[r][c] = sq;
      }
    }
  },

  render(state, selectedSquare, legalMoves) {
    if (!state) return;
    const effects = this._effectsSet(state.active_rules || []);
    const mirrored = effects.has('mirror_board');
    const wrapper = document.getElementById('board-wrapper');
    wrapper.classList.toggle('mirrored', mirrored);

    const lastMove = state.move_history && state.move_history.length > 0
      ? state.move_history[state.move_history.length - 1]
      : null;

    // King in check position
    let checkPos = null;
    if (state.status === 'active') {
      const cur = state.current_turn;
      for (let r = 0; r < 8; r++) {
        for (let c = 0; c < 8; c++) {
          const p = state.board[r][c];
          if (p && p.type === 'K' && p.color === cur) {
            // We mark the king square as in-check based on server-sent in_check flag
            // Store for use below; the server response sets in_check
            checkPos = [r, c];
          }
        }
      }
    }

    const legalSet = new Set((legalMoves || []).map(m => `${m.to_row},${m.to_col}`));
    const legalCapSet = new Set(
      (legalMoves || [])
        .filter(m => state.board[m.to_row] && state.board[m.to_row][m.to_col])
        .map(m => `${m.to_row},${m.to_col}`)
    );

    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        const sq = this.squares[r][c];
        const base = (r + c) % 2 === 0 ? 'light' : 'dark';
        const key = `${r},${c}`;
        const piece = state.board[r][c];
        const isSelected = selectedSquare && selectedSquare[0] === r && selectedSquare[1] === c;
        const isLastFrom = lastMove && lastMove.from[0] === r && lastMove.from[1] === c;
        const isLastTo   = lastMove && lastMove.to[0]   === r && lastMove.to[1]   === c;
        const isLegal = legalSet.has(key);
        const isCapture = legalCapSet.has(key);

        let cls = `square ${base}`;
        if (isSelected) cls += ' selected';
        else if (isLastFrom) cls += ' last-from';
        else if (isLastTo)   cls += ' last-to';

        if (isLegal) cls += isCapture ? ' legal-capture' : ' legal-empty';

        sq.className = cls;
        if (piece) {
          sq.innerHTML = `<span class="pc-${piece.color}">${glyph(piece)}</span>`;
        } else {
          sq.textContent = '';
        }
      }
    }

    // Check highlight is applied after move response
  },

  highlightCheck(checkRow, checkCol) {
    if (checkRow == null) return;
    this.squares[checkRow][checkCol].classList.add('in-check');
  },

  _effectsSet(activeRules) {
    const s = new Set();
    for (const r of activeRules) {
      for (const e of (r.effects || [])) {
        s.add(e.tag);
      }
    }
    return s;
  },

  updateTurnIndicator(state) {
    const dot = document.getElementById('turn-dot');
    const label = document.getElementById('turn-label');
    const counter = document.getElementById('turn-counter');

    if (state.status !== 'active') {
      dot.className = 'turn-dot';
      label.textContent = state.status === 'checkmate' ? 'Game over — Checkmate!'
                        : state.status === 'stalemate' ? 'Game over — Stalemate!'
                        : state.status === 'resigned'  ? 'Game over — Resigned!'
                        : 'Game over';
      counter.textContent = '';
      return;
    }

    dot.className = `turn-dot ${state.current_turn === 'w' ? 'white' : 'black'}`;
    label.textContent = state.current_turn === 'w' ? "White's Turn" : "Black's Turn";

    const until = state.turns_until_rule;
    counter.textContent = until === 1 ? 'Rule changes next move!' : `Rule changes in ${until} moves`;
  },

  updateActiveRules(activeRules) {
    const bar = document.getElementById('active-rules-bar');
    bar.innerHTML = '';
    for (const rule of (activeRules || [])) {
      const pill = document.createElement('div');
      pill.className = 'rule-pill';
      pill.innerHTML = `
        <span class="rule-pill-emoji">${rule.emoji}</span>
        <span class="rule-pill-name">${rule.name}</span>
        <span class="rule-pill-turns">${rule.remaining_turns} left</span>
        <span class="rule-pill-hint">ⓘ</span>
      `;
      pill.addEventListener('click', () => RuleInfoModal.show(rule));
      pill.addEventListener('touchend', (e) => { e.preventDefault(); RuleInfoModal.show(rule); });
      bar.appendChild(pill);
    }
  },

  updateMoveLog(moveHistory) {
    const log = document.getElementById('move-log');
    log.innerHTML = '';
    const entries = (moveHistory || []).slice(-20);
    for (const entry of entries) {
      const div = document.createElement('div');
      div.className = 'move-entry';
      const fromStr = toNotation(entry.from[0], entry.from[1]);
      const toStr   = toNotation(entry.to[0],   entry.to[1]);
      const pieceGlyph = glyph(entry.piece);
      div.innerHTML = `
        <span class="move-num">${entry.half_turn}</span>
        <span class="move-notation">${pieceGlyph} ${fromStr}→${toStr}${entry.captured ? '✕' : ''}${entry.promotion ? '='+entry.promotion : ''}</span>
      `;
      log.appendChild(div);
    }
    log.scrollTop = log.scrollHeight;
  },

  showStatusBar(text) {
    document.getElementById('status-bar').textContent = text || '';
  },
};

// ── Rule banner ───────────────────────────────────────────────────────────────
const RuleBanner = {
  _timer: null,

  show(rule) {
    if (!rule) return;
    const banner = document.getElementById('rule-banner');
    banner.querySelector('.rule-banner-emoji').textContent = rule.emoji || '⚡';
    banner.querySelector('.rule-banner-name').textContent  = rule.name || '';
    banner.querySelector('.rule-banner-desc').textContent  = rule.description || '';
    banner.classList.add('visible');
    clearTimeout(this._timer);
    this._timer = setTimeout(() => this.hide(), 6000);
  },

  hide() {
    document.getElementById('rule-banner').classList.remove('visible');
    clearTimeout(this._timer);
  },
};

// ── Rule info modal (tap a pill) ──────────────────────────────────────────────
const RuleInfoModal = {
  show(rule) {
    const overlay = document.getElementById('rule-info-modal');
    overlay.querySelector('.rule-info-emoji').textContent = rule.emoji || '⚡';
    overlay.querySelector('.rule-info-name').textContent  = rule.name || '';
    overlay.querySelector('.rule-info-desc').textContent  = rule.description || '';
    overlay.querySelector('.rule-info-turns').textContent =
      `${rule.remaining_turns} move${rule.remaining_turns === 1 ? '' : 's'} remaining`;
    overlay.classList.remove('hidden');
  },
  hide() {
    document.getElementById('rule-info-modal').classList.add('hidden');
  },
};

// ── Promotion modal ───────────────────────────────────────────────────────────
const PromotionModal = {
  _resolve: null,

  prompt(color) {
    return new Promise((resolve) => {
      this._resolve = resolve;
      const overlay = document.getElementById('promotion-modal');
      const choices = document.getElementById('promo-choices');
      choices.innerHTML = '';
      const pieces = ['Q', 'R', 'B', 'N'];
      const glyphMap = color === 'w'
        ? { Q: '♕', R: '♖', B: '♗', N: '♘' }
        : { Q: '♛', R: '♜', B: '♝', N: '♞' };

      for (const pt of pieces) {
        const btn = document.createElement('button');
        btn.className = 'promo-btn';
        btn.textContent = glyphMap[pt];
        btn.title = pt;
        btn.addEventListener('click', () => {
          overlay.classList.add('hidden');
          resolve(pt);
        });
        choices.appendChild(btn);
      }
      overlay.classList.remove('hidden');
    });
  },
};

// ── Game over modal ───────────────────────────────────────────────────────────
const GameOverModal = {
  show(state) {
    const overlay = document.getElementById('game-over-modal');
    const banner  = overlay.querySelector('.winner-banner');
    const outcome = overlay.querySelector('.outcome-text');
    const sub     = overlay.querySelector('.outcome-sub');

    if (state.status === 'checkmate') {
      const winColor = state.winner === 'w' ? 'White' : 'Black';
      banner.textContent = state.winner === 'w' ? '♔' : '♚';
      outcome.textContent = `${winColor} wins by Checkmate!`;
      sub.textContent = 'The king has fallen.';
    } else if (state.status === 'stalemate') {
      banner.textContent = '🤝';
      outcome.textContent = "Stalemate — It's a draw!";
      sub.textContent = 'No legal moves, but the king is safe.';
    } else if (state.status === 'resigned') {
      const winColor = state.winner === 'w' ? 'White' : 'Black';
      banner.textContent = '🏳️';
      outcome.textContent = `${winColor} wins by Resignation`;
      sub.textContent = '';
    }
    overlay.classList.remove('hidden');
  },

  hide() {
    document.getElementById('game-over-modal').classList.add('hidden');
  },
};

// ── InputHandler — tap state machine ─────────────────────────────────────────
const InputHandler = {
  selectedSquare: null,
  legalMoves: [],
  pendingPromotion: null,
  busy: false,

  init() {
    const board = document.getElementById('chess-board');

    const handleTap = async (row, col) => {
      if (this.busy) return;
      const state = GameClient.state;
      if (!state || state.status !== 'active') return;

      const piece = state.board[row][col];

      // Nothing selected yet
      if (!this.selectedSquare) {
        if (!piece || piece.color !== state.current_turn) return;
        this.busy = true;
        this.selectedSquare = [row, col];
        this.legalMoves = await GameClient.getLegalMoves(row, col);
        UIRenderer.render(state, this.selectedSquare, this.legalMoves);
        this.busy = false;
        return;
      }

      const [selRow, selCol] = this.selectedSquare;

      // Tap same square = deselect
      if (selRow === row && selCol === col) {
        this.selectedSquare = null;
        this.legalMoves = [];
        UIRenderer.render(state, null, []);
        return;
      }

      // Tap another friendly piece = switch selection
      if (piece && piece.color === state.current_turn) {
        this.busy = true;
        this.selectedSquare = [row, col];
        this.legalMoves = await GameClient.getLegalMoves(row, col);
        UIRenderer.render(state, this.selectedSquare, this.legalMoves);
        this.busy = false;
        return;
      }

      // Check if this is a legal move destination
      const matchingMoves = this.legalMoves.filter(m => m.to_row === row && m.to_col === col);
      if (matchingMoves.length === 0) {
        // Illegal tap — deselect
        this.selectedSquare = null;
        this.legalMoves = [];
        UIRenderer.render(state, null, []);
        return;
      }

      // Determine if promotion is needed
      let promotion = null;
      const movingPiece = state.board[selRow][selCol];
      if (movingPiece && movingPiece.type === 'P') {
        if ((movingPiece.color === 'w' && row === 0) ||
            (movingPiece.color === 'b' && row === 7)) {
          promotion = await PromotionModal.prompt(movingPiece.color);
        }
      }

      this.busy = true;
      this.selectedSquare = null;
      this.legalMoves = [];

      const result = await GameClient.makeMove(selRow, selCol, row, col, promotion);
      if (!result.ok) {
        this.busy = false;
        UIRenderer.showStatusBar(result.error || 'Illegal move');
        UIRenderer.render(GameClient.state, null, []);
        return;
      }

      const newState = result.state;
      UIRenderer.render(newState, null, []);
      UIRenderer.updateTurnIndicator(newState);
      UIRenderer.updateActiveRules(newState.active_rules);
      UIRenderer.updateMoveLog(newState.move_history);

      // Highlight check
      if (result.in_check) {
        const cur = newState.current_turn;
        for (let r = 0; r < 8; r++) {
          for (let c = 0; c < 8; c++) {
            const p = newState.board[r][c];
            if (p && p.type === 'K' && p.color === cur) {
              UIRenderer.highlightCheck(r, c);
            }
          }
        }
        UIRenderer.showStatusBar(newState.current_turn === 'w' ? 'White is in check!' : 'Black is in check!');
      } else {
        UIRenderer.showStatusBar('');
      }

      // Show new rule banner
      if (result.new_rule) {
        RuleBanner.show(result.new_rule);
      }

      // Game over
      if (result.checkmate || result.stalemate || newState.status === 'resigned') {
        GameOverModal.show(newState);
      }

      this.busy = false;
    };

    // Bind both click and touchend
    board.addEventListener('click', (e) => {
      const sq = e.target.closest('.square');
      if (!sq) return;
      handleTap(parseInt(sq.dataset.row), parseInt(sq.dataset.col));
    });

    board.addEventListener('touchend', (e) => {
      e.preventDefault();
      const touch = e.changedTouches[0];
      const el = document.elementFromPoint(touch.clientX, touch.clientY);
      const sq = el && el.closest('.square');
      if (!sq) return;
      handleTap(parseInt(sq.dataset.row), parseInt(sq.dataset.col));
    }, { passive: false });
  },

  reset() {
    this.selectedSquare = null;
    this.legalMoves = [];
    this.busy = false;
  },
};

// ── Board sizing — scales piece glyphs to fit the board ───────────────────────
function initBoardSizing() {
  const wrapper = document.getElementById('board-wrapper');
  if (!wrapper) return;

  const update = () => {
    const w = wrapper.getBoundingClientRect().width;
    if (w < 1) return;
    const fontSize = Math.round(w / 8 * 0.82);
    document.documentElement.style.setProperty('--board-size', fontSize + 'px');
  };

  update();
  new ResizeObserver(update).observe(wrapper);
}

// ── App bootstrap ─────────────────────────────────────────────────────────────
async function startNewGame() {
  GameOverModal.hide();
  RuleBanner.hide();
  InputHandler.reset();
  UIRenderer.showStatusBar('');

  const state = await GameClient.newGame();
  UIRenderer.render(state, null, []);
  UIRenderer.updateTurnIndicator(state);
  UIRenderer.updateActiveRules(state.active_rules);
  UIRenderer.updateMoveLog(state.move_history);
}

document.addEventListener('DOMContentLoaded', () => {
  UIRenderer.init();
  InputHandler.init();

  // Rule banner dismiss
  document.getElementById('rule-ok').addEventListener('click', () => RuleBanner.hide());

  // Rule info modal dismiss
  document.getElementById('rule-info-close').addEventListener('click', () => RuleInfoModal.hide());
  document.getElementById('rule-info-modal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) RuleInfoModal.hide();
  });

  // New game buttons
  document.getElementById('new-game-btn').addEventListener('click', startNewGame);
  document.getElementById('play-again-btn').addEventListener('click', startNewGame);

  // Resign button
  document.getElementById('resign-btn').addEventListener('click', async () => {
    const state = GameClient.state;
    if (!state || state.status !== 'active') return;
    if (!confirm('Are you sure you want to resign?')) return;
    const result = await GameClient.resign(state.current_turn);
    if (result.ok) {
      UIRenderer.render(result.state, null, []);
      UIRenderer.updateTurnIndicator(result.state);
      GameOverModal.show(result.state);
    }
  });

  initBoardSizing();
  startNewGame();
});
