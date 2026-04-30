using ChessGame.Models;

namespace ChessGame.Engine;

public class ChessEngine
{
    public List<Move> GetRawMoves(BoardState board, int row, int col, HashSet<string> effects)
    {
        var piece = board.Get(row, col);
        if (piece == null) return [];

        // Rule overrides
        if (piece.Type == PieceType.N && effects.Contains("knights_rook"))
            return SlideRook(board, row, col, piece.Color, effects);
        if (piece.Type == PieceType.P && effects.Contains("pawns_knight"))
            return KnightOffsets(board, row, col, piece.Color, effects);

        return piece.Type switch
        {
            PieceType.K => KingMoves(board, row, col, piece.Color, effects),
            PieceType.Q => QueenMoves(board, row, col, piece.Color, effects),
            PieceType.R => RookMoves(board, row, col, piece.Color, effects),
            PieceType.B => BishopMoves(board, row, col, piece.Color, effects),
            PieceType.N => KnightOffsets(board, row, col, piece.Color, effects),
            PieceType.P => PawnMoves(board, row, col, piece.Color, effects),
            _ => []
        };
    }

    public List<Move> GetLegalMoves(BoardState board, int row, int col,
        PieceColor color, HashSet<string> effects, (int r, int c)? epTarget = null)
    {
        var raw = GetRawMoves(board, row, col, effects);

        // Add en passant for pawns
        if (board.Get(row, col)?.Type == PieceType.P)
            raw.AddRange(GetEnPassantMoves(board, row, col, color, epTarget));

        var legal = raw.Where(m => IsLegal(board, m, color, effects, epTarget)).ToList();

        // Forced capture rule
        if (effects.Contains("forced_capture"))
        {
            var captures = legal.Where(m => m.CapturedPiece != null || m.IsEnPassant).ToList();
            if (captures.Count > 0) return captures;
        }
        return legal;
    }

    public List<Move> GetAllLegalMoves(BoardState board, PieceColor color,
        HashSet<string> effects, (int r, int c)? epTarget = null)
    {
        var moves = new List<Move>();
        for (int r = 0; r < 8; r++)
            for (int c = 0; c < 8; c++)
                if (board.Get(r, c)?.Color == color)
                    moves.AddRange(GetLegalMoves(board, r, c, color, effects, epTarget));
        return moves;
    }

    public bool IsInCheck(BoardState board, PieceColor color, HashSet<string> effects)
    {
        var kingPos = board.FindKing(color);
        if (kingPos == null) return false;
        var opp = color == PieceColor.White ? PieceColor.Black : PieceColor.White;
        for (int r = 0; r < 8; r++)
            for (int c = 0; c < 8; c++)
                if (board.Get(r, c)?.Color == opp)
                    foreach (var mv in GetRawMoves(board, r, c, effects))
                        if (mv.ToRow == kingPos.Value.r && mv.ToCol == kingPos.Value.c)
                            return true;
        return false;
    }

    public bool IsCheckmate(BoardState board, PieceColor color,
        HashSet<string> effects, (int r, int c)? epTarget = null) =>
        IsInCheck(board, color, effects) &&
        GetAllLegalMoves(board, color, effects, epTarget).Count == 0;

    public bool IsStalemate(BoardState board, PieceColor color,
        HashSet<string> effects, (int r, int c)? epTarget = null) =>
        !IsInCheck(board, color, effects) &&
        GetAllLegalMoves(board, color, effects, epTarget).Count == 0;

    private bool IsLegal(BoardState board, Move move, PieceColor color,
        HashSet<string> effects, (int r, int c)? epTarget)
    {
        var sim = board.Clone();
        ApplyMoveToBoard(sim, move, epTarget);
        return !IsInCheck(sim, color, effects);
    }

    public void ApplyMoveToBoard(BoardState board, Move move, (int r, int c)? epTarget = null)
    {
        var piece = board.Get(move.FromRow, move.FromCol);
        if (piece == null) return;

        if (move.IsEnPassant && epTarget.HasValue)
            board.Set(move.FromRow, epTarget.Value.c, null);

        if (move.IsCastle)
        {
            int rookFromCol = move.ToCol == 6 ? 7 : 0;
            int rookToCol = move.ToCol == 6 ? 5 : 3;
            var rook = board.Get(move.FromRow, rookFromCol);
            board.Set(move.FromRow, rookToCol, rook);
            board.Set(move.FromRow, rookFromCol, null);
            if (rook != null) rook.HasMoved = true;
        }

        move.CapturedPiece = board.Get(move.ToRow, move.ToCol);
        board.Set(move.FromRow, move.FromCol, null);

        var newPiece = new Piece(piece.Type, piece.Color, true);
        if (move.IsKnighted) newPiece.Type = PieceType.N;
        else if (move.Promotion != null &&
                 Enum.TryParse<PieceType>(move.Promotion, out var pt))
            newPiece.Type = pt;

        board.Set(move.ToRow, move.ToCol, newPiece);
    }

    // ── Move generators ──────────────────────────────────────────────────────

    private List<Move> KingMoves(BoardState board, int r, int c,
        PieceColor color, HashSet<string> effects)
    {
        var moves = new List<Move>();
        for (int dr = -1; dr <= 1; dr++)
            for (int dc = -1; dc <= 1; dc++)
            {
                if (dr == 0 && dc == 0) continue;
                int nr = r + dr, nc = c + dc;
                if (nr < 0 || nr > 7 || nc < 0 || nc > 7) continue;
                var t = board.Get(nr, nc);
                if (t?.Type == PieceType.K) continue;
                if (t?.Color == color && !effects.Contains("friendly_fire")) continue;
                moves.Add(new Move(r, c, nr, nc));
            }

        if (effects.Contains("king_queen_move"))
            moves.AddRange(Slide(board, r, c, color, effects,
                [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]));

        var piece = board.Get(r, c)!;
        if (!piece.HasMoved && !effects.Contains("king_queen_move"))
            moves.AddRange(CastleMoves(board, r, c, color));

        return moves;
    }

    private List<Move> CastleMoves(BoardState board, int r, int c, PieceColor color)
    {
        var moves = new List<Move>();
        var r7 = board.Get(r, 7);
        if (r7 is { Type: PieceType.R } && !r7.HasMoved &&
            board.Get(r, 5) == null && board.Get(r, 6) == null)
            moves.Add(new Move(r, c, r, 6, isCastle: true));
        var r0 = board.Get(r, 0);
        if (r0 is { Type: PieceType.R } && !r0.HasMoved &&
            board.Get(r, 1) == null && board.Get(r, 2) == null && board.Get(r, 3) == null)
            moves.Add(new Move(r, c, r, 2, isCastle: true));
        return moves;
    }

    private List<Move> QueenMoves(BoardState board, int r, int c,
        PieceColor color, HashSet<string> effects) =>
        Slide(board, r, c, color, effects,
            [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]);

    private List<Move> RookMoves(BoardState board, int r, int c,
        PieceColor color, HashSet<string> effects)
    {
        var dirs = new List<(int, int)> { (-1,0),(1,0),(0,-1),(0,1) };
        if (effects.Contains("rooks_diagonal"))
            dirs.AddRange([(-1,-1),(-1,1),(1,-1),(1,1)]);
        return Slide(board, r, c, color, effects, dirs);
    }

    private List<Move> SlideRook(BoardState board, int r, int c,
        PieceColor color, HashSet<string> effects) =>
        Slide(board, r, c, color, effects, [(-1,0),(1,0),(0,-1),(0,1)]);

    private List<Move> BishopMoves(BoardState board, int r, int c,
        PieceColor color, HashSet<string> effects)
    {
        var dirs = new List<(int, int)> { (-1,-1),(-1,1),(1,-1),(1,1) };
        if (effects.Contains("bishops_straight"))
            dirs.AddRange([(-1,0),(1,0),(0,-1),(0,1)]);
        return Slide(board, r, c, color, effects, dirs);
    }

    private List<Move> KnightOffsets(BoardState board, int r, int c,
        PieceColor color, HashSet<string> effects)
    {
        var moves = new List<Move>();
        (int, int)[] offsets = [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)];
        foreach (var (dr, dc) in offsets)
        {
            int nr = r + dr, nc = c + dc;
            if (nr < 0 || nr > 7 || nc < 0 || nc > 7) continue;
            var t = board.Get(nr, nc);
            if (t?.Type == PieceType.K) continue;
            if (t?.Color == color && !effects.Contains("friendly_fire")) continue;
            moves.Add(new Move(r, c, nr, nc));
        }
        return moves;
    }

    private List<Move> PawnMoves(BoardState board, int r, int c,
        PieceColor color, HashSet<string> effects)
    {
        var moves = new List<Move>();
        int fwd = color == PieceColor.White ? -1 : 1;
        int startRow = color == PieceColor.White ? 6 : 1;
        int promoRow = color == PieceColor.White ? 0 : 7;
        int midPromoRow = color == PieceColor.White ? 3 : 4;

        var directions = new List<int> { fwd };
        if (effects.Contains("pawns_backward")) directions.Add(-fwd);

        foreach (int dir in directions)
        {
            int r1 = r + dir;
            if (r1 >= 0 && r1 <= 7 && board.Get(r1, c) == null)
            {
                if (r1 == promoRow)
                    foreach (var pt in new[] { "Q", "R", "B", "N" })
                        moves.Add(new Move(r, c, r1, c, promotion: pt));
                else if (effects.Contains("early_promote") && r1 == midPromoRow)
                    moves.Add(new Move(r, c, r1, c, promotion: "Q"));
                else
                    moves.Add(new Move(r, c, r1, c));

                if (dir == fwd && r == startRow)
                {
                    int r2 = r + 2 * dir;
                    if (r2 >= 0 && r2 <= 7 && board.Get(r2, c) == null)
                        moves.Add(new Move(r, c, r2, c));
                }
            }

            foreach (int dc in new[] { -1, 1 })
            {
                int cr = r + dir, cc = c + dc;
                if (cr < 0 || cr > 7 || cc < 0 || cc > 7) continue;
                var t = board.Get(cr, cc);
                if (t == null || t.Type == PieceType.K) continue;
                if (t.Color == color && !effects.Contains("friendly_fire")) continue;
                if (cr == promoRow)
                    foreach (var pt in new[] { "Q", "R", "B", "N" })
                    {
                        var m = new Move(r, c, cr, cc, promotion: pt);
                        m.CapturedPiece = t;
                        moves.Add(m);
                    }
                else
                {
                    var m = new Move(r, c, cr, cc);
                    m.CapturedPiece = t;
                    moves.Add(m);
                }
            }
        }
        return moves;
    }

    public List<Move> GetEnPassantMoves(BoardState board, int r, int c,
        PieceColor color, (int r, int c)? epTarget)
    {
        if (epTarget == null) return [];
        var piece = board.Get(r, c);
        if (piece?.Type != PieceType.P) return [];
        int fwd = color == PieceColor.White ? -1 : 1;
        if (r + fwd == epTarget.Value.r && Math.Abs(c - epTarget.Value.c) == 1)
            return [new Move(r, c, epTarget.Value.r, epTarget.Value.c, isEnPassant: true)];
        return [];
    }

    private List<Move> Slide(BoardState board, int r, int c, PieceColor color,
        HashSet<string> effects, IEnumerable<(int dr, int dc)> directions)
    {
        var moves = new List<Move>();
        bool canJump = effects.Contains("all_jump");
        bool knightedRule = effects.Contains("knighted_on_jump");

        foreach (var (dr, dc) in directions)
        {
            int nr = r + dr, nc = c + dc;
            int jumped = 0;
            while (nr >= 0 && nr <= 7 && nc >= 0 && nc <= 7)
            {
                var t = board.Get(nr, nc);
                if (t != null)
                {
                    if (canJump)
                    {
                        if (t.Color == color && !effects.Contains("friendly_fire"))
                        { jumped++; nr += dr; nc += dc; continue; }
                        if (t.Type == PieceType.K) break;
                        bool k = knightedRule && jumped >= 3;
                        var m = new Move(r, c, nr, nc, isKnighted: k);
                        m.CapturedPiece = t;
                        moves.Add(m);
                        jumped++;
                        nr += dr; nc += dc;
                        continue;
                    }
                    else
                    {
                        if (t.Color == color && !effects.Contains("friendly_fire")) break;
                        if (t.Type == PieceType.K) break;
                        var m = new Move(r, c, nr, nc);
                        m.CapturedPiece = t;
                        moves.Add(m);
                        break;
                    }
                }
                else
                {
                    bool k = knightedRule && canJump && jumped >= 3;
                    moves.Add(new Move(r, c, nr, nc, isKnighted: k));
                }
                nr += dr; nc += dc;
            }
        }
        return moves;
    }
}
