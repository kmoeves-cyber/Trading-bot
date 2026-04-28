import copy

COLOR_WHITE = 'w'
COLOR_BLACK = 'b'
PIECE_TYPES = {'K', 'Q', 'R', 'B', 'N', 'P'}


class Piece:
    __slots__ = ('type', 'color', 'has_moved')

    def __init__(self, type_, color, has_moved=False):
        self.type = type_
        self.color = color
        self.has_moved = has_moved

    def to_dict(self):
        return {'type': self.type, 'color': self.color, 'has_moved': self.has_moved}

    @staticmethod
    def from_dict(d):
        if d is None:
            return None
        return Piece(d['type'], d['color'], d.get('has_moved', False))

    def __repr__(self):
        return f"{self.color}{self.type}"


class Move:
    __slots__ = ('from_row', 'from_col', 'to_row', 'to_col',
                 'promotion', 'is_castle', 'is_en_passant', 'knighted', 'captured_piece')

    def __init__(self, from_row, from_col, to_row, to_col,
                 promotion=None, is_castle=False, is_en_passant=False, knighted=False):
        self.from_row = from_row
        self.from_col = from_col
        self.to_row = to_row
        self.to_col = to_col
        self.promotion = promotion
        self.is_castle = is_castle
        self.is_en_passant = is_en_passant
        self.knighted = knighted
        self.captured_piece = None

    def to_dict(self):
        return {
            'from_row': self.from_row, 'from_col': self.from_col,
            'to_row': self.to_row, 'to_col': self.to_col,
            'promotion': self.promotion, 'is_castle': self.is_castle,
            'is_en_passant': self.is_en_passant, 'knighted': self.knighted
        }

    def __eq__(self, other):
        return (self.from_row == other.from_row and self.from_col == other.from_col and
                self.to_row == other.to_row and self.to_col == other.to_col and
                self.promotion == other.promotion)

    def __repr__(self):
        return f"Move({self.from_row},{self.from_col}→{self.to_row},{self.to_col})"


class BoardState:
    def __init__(self):
        self.grid = [[None] * 8 for _ in range(8)]

    def setup_standard(self):
        back_row = ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
        for col, pt in enumerate(back_row):
            self.grid[0][col] = Piece(pt, COLOR_BLACK)
            self.grid[7][col] = Piece(pt, COLOR_WHITE)
        for col in range(8):
            self.grid[1][col] = Piece('P', COLOR_BLACK)
            self.grid[6][col] = Piece('P', COLOR_WHITE)

    def get(self, row, col):
        if 0 <= row <= 7 and 0 <= col <= 7:
            return self.grid[row][col]
        return None

    def set(self, row, col, piece):
        self.grid[row][col] = piece

    def find_king(self, color):
        for r in range(8):
            for c in range(8):
                p = self.grid[r][c]
                if p and p.type == 'K' and p.color == color:
                    return (r, c)
        return None

    def clone(self):
        new_board = BoardState()
        for r in range(8):
            for c in range(8):
                p = self.grid[r][c]
                if p:
                    new_board.grid[r][c] = Piece(p.type, p.color, p.has_moved)
        return new_board

    def to_dict(self):
        return {
            'board': [
                [self.grid[r][c].to_dict() if self.grid[r][c] else None for c in range(8)]
                for r in range(8)
            ]
        }

    @staticmethod
    def from_dict(d):
        bs = BoardState()
        raw = d['board']
        for r in range(8):
            for c in range(8):
                bs.grid[r][c] = Piece.from_dict(raw[r][c])
        return bs


class ChessEngine:
    def get_raw_moves(self, board, row, col, effects):
        piece = board.get(row, col)
        if not piece:
            return []
        pt = piece.type
        color = piece.color

        # Rule: knights_rook — knights move like rooks
        if pt == 'N' and 'knights_rook' in effects:
            return self._moves_rook_like(board, row, col, color, effects)

        # Rule: pawns_knight — pawns move like knights
        if pt == 'P' and 'pawns_knight' in effects:
            return self._moves_knight_like(board, row, col, color, effects)

        # Rule: king_queen_move — kings also get queen slides
        dispatch = {
            'K': self._moves_king,
            'Q': self._moves_queen,
            'R': self._moves_rook,
            'B': self._moves_bishop,
            'N': self._moves_knight,
            'P': self._moves_pawn,
        }
        return dispatch[pt](board, row, col, color, effects)

    def get_legal_moves(self, board, row, col, color, effects, en_passant_target=None):
        raw = self.get_raw_moves(board, row, col, effects)
        legal = []
        for move in raw:
            if self._is_legal(board, move, color, effects, en_passant_target):
                legal.append(move)
        # Rule: forced_capture — must capture if any capture available
        if 'forced_capture' in effects:
            captures = [m for m in legal if m.captured_piece is not None or m.is_en_passant]
            if captures:
                return captures
        return legal

    def get_all_legal_moves(self, board, color, effects, en_passant_target=None):
        moves = []
        for r in range(8):
            for c in range(8):
                p = board.get(r, c)
                if p and p.color == color:
                    moves.extend(self.get_legal_moves(board, r, c, color, effects, en_passant_target))
        return moves

    def is_in_check(self, board, color, effects):
        king_pos = board.find_king(color)
        if not king_pos:
            return False
        opp = COLOR_BLACK if color == COLOR_WHITE else COLOR_WHITE
        for r in range(8):
            for c in range(8):
                p = board.get(r, c)
                if p and p.color == opp:
                    for mv in self.get_raw_moves(board, r, c, effects):
                        if (mv.to_row, mv.to_col) == king_pos:
                            return True
        return False

    def is_checkmate(self, board, color, effects, en_passant_target=None):
        if not self.is_in_check(board, color, effects):
            return False
        return len(self.get_all_legal_moves(board, color, effects, en_passant_target)) == 0

    def is_stalemate(self, board, color, effects, en_passant_target=None):
        if self.is_in_check(board, color, effects):
            return False
        return len(self.get_all_legal_moves(board, color, effects, en_passant_target)) == 0

    def _is_legal(self, board, move, color, effects, en_passant_target=None):
        sim = board.clone()
        self._apply_move_to_board(sim, move, en_passant_target)
        # After move, own king must not be in check
        return not self.is_in_check(sim, color, effects)

    def _apply_move_to_board(self, board, move, en_passant_target=None):
        piece = board.get(move.from_row, move.from_col)
        if not piece:
            return

        # En passant capture
        if move.is_en_passant and en_passant_target:
            ep_r, ep_c = en_passant_target
            # The captured pawn is on the same rank as the moving pawn, different from dest
            cap_row = move.from_row
            board.set(cap_row, ep_c, None)

        # Castling rook move
        if move.is_castle:
            if move.to_col == 6:  # kingside
                rook = board.get(move.from_row, 7)
                board.set(move.from_row, 5, rook)
                board.set(move.from_row, 7, None)
                if rook:
                    rook.has_moved = True
            else:  # queenside
                rook = board.get(move.from_row, 0)
                board.set(move.from_row, 3, rook)
                board.set(move.from_row, 0, None)
                if rook:
                    rook.has_moved = True

        board.set(move.from_row, move.from_col, None)
        new_piece = Piece(piece.type, piece.color, True)

        if move.knighted:
            new_piece.type = 'N'
        elif move.promotion:
            new_piece.type = move.promotion

        board.set(move.to_row, move.to_col, new_piece)
        move.captured_piece = board.get(move.to_row, move.to_col)

    # ── Move generators ──────────────────────────────────────────────────────

    def _moves_king(self, board, row, col, color, effects):
        moves = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                r, c = row + dr, col + dc
                if not (0 <= r <= 7 and 0 <= c <= 7):
                    continue
                target = board.get(r, c)
                if target and target.color == color and 'friendly_fire' not in effects:
                    continue
                if target and target.type == 'K':
                    continue
                moves.append(Move(row, col, r, c))

        # Rule: king_queen_move
        if 'king_queen_move' in effects:
            moves.extend(self._slide(board, row, col, color, effects,
                                     [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]))

        # Castling (only if standard rules, king not moved)
        piece = board.get(row, col)
        if piece and not piece.has_moved and 'king_queen_move' not in effects:
            moves.extend(self._castle_moves(board, row, col, color, effects))

        return moves

    def _castle_moves(self, board, row, col, color, effects):
        moves = []
        # Kingside
        r7 = board.get(row, 7)
        if r7 and r7.type == 'R' and not r7.has_moved:
            if all(board.get(row, c) is None for c in (5, 6)):
                moves.append(Move(row, col, row, 6, is_castle=True))
        # Queenside
        r0 = board.get(row, 0)
        if r0 and r0.type == 'R' and not r0.has_moved:
            if all(board.get(row, c) is None for c in (1, 2, 3)):
                moves.append(Move(row, col, row, 2, is_castle=True))
        return moves

    def _moves_queen(self, board, row, col, color, effects):
        dirs = [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]
        return self._slide(board, row, col, color, effects, dirs)

    def _moves_rook(self, board, row, col, color, effects):
        dirs = [(-1,0),(1,0),(0,-1),(0,1)]
        if 'rooks_diagonal' in effects:
            dirs += [(-1,-1),(-1,1),(1,-1),(1,1)]
        return self._slide(board, row, col, color, effects, dirs)

    def _moves_rook_like(self, board, row, col, color, effects):
        dirs = [(-1,0),(1,0),(0,-1),(0,1)]
        return self._slide(board, row, col, color, effects, dirs)

    def _moves_bishop(self, board, row, col, color, effects):
        dirs = [(-1,-1),(-1,1),(1,-1),(1,1)]
        if 'bishops_straight' in effects:
            dirs += [(-1,0),(1,0),(0,-1),(0,1)]
        return self._slide(board, row, col, color, effects, dirs)

    def _moves_knight(self, board, row, col, color, effects):
        offsets = [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]
        moves = []
        for dr, dc in offsets:
            r, c = row + dr, col + dc
            if not (0 <= r <= 7 and 0 <= c <= 7):
                continue
            target = board.get(r, c)
            if target and target.color == color and 'friendly_fire' not in effects:
                continue
            if target and target.type == 'K':
                continue
            moves.append(Move(row, col, r, c))
        return moves

    def _moves_knight_like(self, board, row, col, color, effects):
        return self._moves_knight(board, row, col, color, effects)

    def _moves_pawn(self, board, row, col, color, effects):
        moves = []
        fwd = -1 if color == COLOR_WHITE else 1
        start_row = 6 if color == COLOR_WHITE else 1
        promo_row = 0 if color == COLOR_WHITE else 7
        mid_promo_row = 3 if color == COLOR_WHITE else 4  # for early_promote rule

        directions = [fwd]
        if 'pawns_backward' in effects:
            directions.append(-fwd)

        for direction in directions:
            # One step forward
            r1 = row + direction
            if 0 <= r1 <= 7 and board.get(r1, col) is None:
                promo = None
                if r1 == promo_row:
                    for pt in ('Q', 'R', 'B', 'N'):
                        moves.append(Move(row, col, r1, col, promotion=pt))
                elif 'early_promote' in effects and r1 == mid_promo_row:
                    moves.append(Move(row, col, r1, col, promotion='Q'))
                else:
                    moves.append(Move(row, col, r1, col))

                # Two steps from starting row (only forward direction)
                if direction == fwd and row == start_row:
                    r2 = row + 2 * direction
                    if 0 <= r2 <= 7 and board.get(r2, col) is None:
                        moves.append(Move(row, col, r2, col))

            # Diagonal captures
            for dc in (-1, 1):
                cr, cc = row + direction, col + dc
                if not (0 <= cr <= 7 and 0 <= cc <= 7):
                    continue
                target = board.get(cr, cc)
                if target and (target.color != color or 'friendly_fire' in effects) and target.type != 'K':
                    promo = None
                    if cr == promo_row:
                        for pt in ('Q', 'R', 'B', 'N'):
                            m = Move(row, col, cr, cc, promotion=pt)
                            m.captured_piece = target
                            moves.append(m)
                    else:
                        m = Move(row, col, cr, cc)
                        m.captured_piece = target
                        moves.append(m)

        return moves

    def get_en_passant_moves(self, board, row, col, color, en_passant_target):
        if not en_passant_target:
            return []
        ep_r, ep_c = en_passant_target
        fwd = -1 if color == COLOR_WHITE else 1
        piece = board.get(row, col)
        if not piece or piece.type != 'P':
            return []
        moves = []
        if row + fwd == ep_r and abs(col - ep_c) == 1:
            moves.append(Move(row, col, ep_r, ep_c, is_en_passant=True))
        return moves

    def _slide(self, board, row, col, color, effects, directions):
        moves = []
        can_jump = 'all_jump' in effects
        knighted_rule = 'knighted_on_jump' in effects

        for dr, dc in directions:
            r, c = row + dr, col + dc
            pieces_jumped = 0
            while 0 <= r <= 7 and 0 <= c <= 7:
                target = board.get(r, c)
                if target:
                    if can_jump:
                        if target.color == color and 'friendly_fire' not in effects:
                            pieces_jumped += 1
                            r += dr
                            c += dc
                            continue
                        if target.type == 'K':
                            break
                        knighted = knighted_rule and pieces_jumped >= 3
                        m = Move(row, col, r, c, knighted=knighted)
                        m.captured_piece = target
                        moves.append(m)
                        pieces_jumped += 1
                        r += dr
                        c += dc
                        continue
                    else:
                        # Standard: blocked by any piece
                        if target.color == color and 'friendly_fire' not in effects:
                            break
                        if target.type == 'K':
                            break
                        m = Move(row, col, r, c)
                        m.captured_piece = target
                        moves.append(m)
                        break
                else:
                    knighted = knighted_rule and can_jump and pieces_jumped >= 3
                    moves.append(Move(row, col, r, c, knighted=knighted))
                r += dr
                c += dc

        return moves
