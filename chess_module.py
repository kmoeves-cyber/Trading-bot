import sqlite3
import uuid
import json
import threading
import time
from datetime import datetime, timezone

from chess_engine import BoardState, ChessEngine, COLOR_WHITE, COLOR_BLACK
from chess_rules import RulesEngine


class GameSession:
    def __init__(self, game_id=None):
        self.game_id = game_id or str(uuid.uuid4())
        self.board = BoardState()
        self.board.setup_standard()
        self.current_turn = COLOR_WHITE
        self.half_turn_count = 0
        self.active_rules = []
        self.en_passant_target = None  # (row, col) or None
        self.last_rule_announced = None
        self.status = 'active'
        self.winner = None
        self.double_move_state = {'active': False, 'sub_moves': 0, 'required': 2}
        self.move_history = []
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at

    def to_dict(self):
        return {
            'game_id': self.game_id,
            'board': self.board.to_dict()['board'],
            'current_turn': self.current_turn,
            'half_turn_count': self.half_turn_count,
            'active_rules': self.active_rules,
            'en_passant_target': self.en_passant_target,
            'last_rule_announced': self.last_rule_announced,
            'status': self.status,
            'winner': self.winner,
            'double_move_state': self.double_move_state,
            'move_history': self.move_history[-50:],  # keep last 50 for client
            'turns_until_rule': 4 - (self.half_turn_count % 4) if self.half_turn_count % 4 != 0 else 4,
        }

    @staticmethod
    def from_dict(d):
        s = GameSession.__new__(GameSession)
        s.game_id = d['game_id']
        s.board = BoardState.from_dict({'board': d['board']})
        s.current_turn = d['current_turn']
        s.half_turn_count = d['half_turn_count']
        s.active_rules = d['active_rules']
        s.en_passant_target = d.get('en_passant_target')
        if s.en_passant_target:
            s.en_passant_target = tuple(s.en_passant_target)
        s.last_rule_announced = d.get('last_rule_announced')
        s.status = d['status']
        s.winner = d.get('winner')
        s.double_move_state = d.get('double_move_state',
                                    {'active': False, 'sub_moves': 0, 'required': 2})
        s.move_history = d.get('move_history', [])
        s.created_at = d.get('created_at', datetime.now(timezone.utc).isoformat())
        s.updated_at = d.get('updated_at', s.created_at)
        return s


class ChessSessionManager:
    DB_PATH = 'chess_games.db'

    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()
        self._engine = ChessEngine()
        self._rules = RulesEngine()
        self._init_db()
        self._load_from_db()
        self._start_cleanup_thread()

    def _init_db(self):
        con = sqlite3.connect(self.DB_PATH)
        con.execute("""
            CREATE TABLE IF NOT EXISTS chess_sessions (
                game_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        con.commit()
        con.close()

    def _load_from_db(self):
        con = sqlite3.connect(self.DB_PATH)
        rows = con.execute("SELECT game_id, state_json FROM chess_sessions").fetchall()
        con.close()
        for game_id, state_json in rows:
            try:
                d = json.loads(state_json)
                self._sessions[game_id] = GameSession.from_dict(d)
            except Exception:
                pass

    def _persist(self, session):
        now = datetime.now(timezone.utc).isoformat()
        session.updated_at = now
        state_json = json.dumps(session.to_dict())
        con = sqlite3.connect(self.DB_PATH)
        con.execute("""
            INSERT OR REPLACE INTO chess_sessions (game_id, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (session.game_id, state_json, session.created_at, now))
        con.commit()
        con.close()

    def _start_cleanup_thread(self):
        def cleanup():
            while True:
                time.sleep(3600)
                cutoff = time.time() - 86400  # 24h
                con = sqlite3.connect(self.DB_PATH)
                con.execute("DELETE FROM chess_sessions WHERE updated_at < ?",
                            (datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat(),))
                con.commit()
                con.close()
        t = threading.Thread(target=cleanup, daemon=True)
        t.start()

    def new_game(self):
        session = GameSession()
        with self._lock:
            self._sessions[session.game_id] = session
            self._persist(session)
        return session

    def get_game(self, game_id):
        with self._lock:
            return self._sessions.get(game_id)

    def get_legal_moves_for_square(self, game_id, row, col):
        session = self.get_game(game_id)
        if not session or session.status != 'active':
            return []
        piece = session.board.get(row, col)
        if not piece or piece.color != session.current_turn:
            return []
        effects = self._rules.get_effects_set(session.active_rules)
        moves = self._engine.get_legal_moves(
            session.board, row, col, session.current_turn, effects,
            session.en_passant_target
        )
        # Add en-passant moves
        if piece.type == 'P':
            ep_moves = self._engine.get_en_passant_moves(
                session.board, row, col, session.current_turn, session.en_passant_target)
            for m in ep_moves:
                if self._engine._is_legal(session.board, m, session.current_turn, effects,
                                           session.en_passant_target):
                    moves.append(m)
        return [m.to_dict() for m in moves]

    def make_move(self, game_id, from_row, from_col, to_row, to_col, promotion=None):
        with self._lock:
            session = self._sessions.get(game_id)
            if not session:
                return {'ok': False, 'error': 'Game not found'}
            if session.status != 'active':
                return {'ok': False, 'error': 'Game is over'}

            effects = self._rules.get_effects_set(session.active_rules)
            piece = session.board.get(from_row, from_col)

            if not piece:
                return {'ok': False, 'error': 'No piece at source'}
            if piece.color != session.current_turn:
                return {'ok': False, 'error': 'Not your turn'}

            # Find the matching legal move
            legal = self._engine.get_legal_moves(
                session.board, from_row, from_col, session.current_turn, effects,
                session.en_passant_target
            )
            # Also add en-passant moves
            if piece.type == 'P':
                ep_moves = self._engine.get_en_passant_moves(
                    session.board, from_row, from_col, session.current_turn,
                    session.en_passant_target)
                for m in ep_moves:
                    if self._engine._is_legal(session.board, m, session.current_turn, effects,
                                               session.en_passant_target):
                        legal.append(m)

            chosen = None
            for m in legal:
                if m.to_row == to_row and m.to_col == to_col:
                    if m.promotion is None or m.promotion == promotion:
                        chosen = m
                        break

            if not chosen:
                return {'ok': False, 'error': 'Illegal move'}

            # Capture metadata before applying move
            captured = session.board.get(to_row, to_col)
            if chosen.is_en_passant:
                # Captured pawn is alongside the moving pawn
                ep_cap_row = from_row
                captured = session.board.get(ep_cap_row, to_col)

            # Apply move
            self._engine._apply_move_to_board(session.board, chosen, session.en_passant_target)

            # Track en passant target
            session.en_passant_target = None
            if piece.type == 'P' and abs(to_row - from_row) == 2:
                ep_row = (from_row + to_row) // 2
                session.en_passant_target = (ep_row, to_col)

            # Record move history
            session.move_history.append({
                'from': [from_row, from_col],
                'to': [to_row, to_col],
                'piece': piece.to_dict(),
                'captured': captured.to_dict() if captured else None,
                'promotion': promotion,
                'half_turn': session.half_turn_count + 1,
            })

            # Handle double-move sub-turn
            dms = session.double_move_state
            turn_complete = True
            if 'double_move' in effects:
                dms['active'] = True
                dms['sub_moves'] += 1
                if dms['sub_moves'] < dms['required']:
                    turn_complete = False
                else:
                    dms['sub_moves'] = 0
                    dms['active'] = False

            session.last_rule_announced = None

            if turn_complete:
                session.half_turn_count += 1
                # Tick rule engine
                session.active_rules, new_rule = self._rules.tick(
                    session.half_turn_count, session.active_rules)

                if new_rule:
                    session.last_rule_announced = new_rule
                    if new_rule.get('instant', False):
                        self._rules.apply_instant_mutations(session.board, new_rule)

                # Flip turn
                session.current_turn = (COLOR_BLACK if session.current_turn == COLOR_WHITE
                                        else COLOR_WHITE)

                # Recalculate effects after rule change
                effects = self._rules.get_effects_set(session.active_rules)

                # Check game-over conditions
                opp = session.current_turn
                if self._engine.is_checkmate(session.board, opp, effects,
                                              session.en_passant_target):
                    session.status = 'checkmate'
                    session.winner = COLOR_WHITE if opp == COLOR_BLACK else COLOR_BLACK
                elif self._engine.is_stalemate(session.board, opp, effects,
                                                session.en_passant_target):
                    session.status = 'stalemate'
            else:
                # Mid double-move — check that current player isn't leaving their king in check
                pass

            self._persist(session)

            in_check = self._engine.is_in_check(session.board, session.current_turn, effects)
            return {
                'ok': True,
                'error': None,
                'state': session.to_dict(),
                'new_rule': session.last_rule_announced,
                'in_check': in_check,
                'checkmate': session.status == 'checkmate',
                'stalemate': session.status == 'stalemate',
            }

    def resign(self, game_id, color):
        with self._lock:
            session = self._sessions.get(game_id)
            if not session:
                return {'ok': False, 'error': 'Game not found'}
            session.status = 'resigned'
            session.winner = COLOR_BLACK if color == COLOR_WHITE else COLOR_WHITE
            self._persist(session)
            return {'ok': True, 'state': session.to_dict()}


# Singleton instance
chess_manager = ChessSessionManager()
