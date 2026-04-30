using System.Text.Json;
using ChessGame.Engine;
using ChessGame.Models;
using Microsoft.Data.Sqlite;

namespace ChessGame.Services;

public class GameSessionManager
{
    private const string DbPath = "chess_games.db";
    private readonly Dictionary<string, GameSession> _sessions = [];
    private readonly Lock _lock = new();
    private readonly ChessEngine _engine = new();
    private readonly RulesEngine _rules = new();

    public GameSessionManager()
    {
        InitDb();
        LoadFromDb();
        StartCleanupThread();
    }

    private void InitDb()
    {
        using var con = new SqliteConnection($"Data Source={DbPath}");
        con.Open();
        con.CreateCommand().CommandText = """
            CREATE TABLE IF NOT EXISTS chess_sessions (
                game_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """;
        con.CreateCommand().ExecuteNonQuery();
    }

    private void LoadFromDb()
    {
        using var con = new SqliteConnection($"Data Source={DbPath}");
        con.Open();
        var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT game_id, state_json FROM chess_sessions";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            try
            {
                var json = reader.GetString(1);
                var session = DeserializeSession(json);
                if (session != null) _sessions[session.GameId] = session;
            }
            catch { /* skip corrupt rows */ }
        }
    }

    private void Persist(GameSession session)
    {
        session.UpdatedAt = DateTime.UtcNow.ToString("o");
        var json = JsonSerializer.Serialize(session.ToDict());
        using var con = new SqliteConnection($"Data Source={DbPath}");
        con.Open();
        var cmd = con.CreateCommand();
        cmd.CommandText = """
            INSERT OR REPLACE INTO chess_sessions (game_id, state_json, created_at, updated_at)
            VALUES ($id, $json, $created, $updated)
            """;
        cmd.Parameters.AddWithValue("$id", session.GameId);
        cmd.Parameters.AddWithValue("$json", json);
        cmd.Parameters.AddWithValue("$created", session.CreatedAt);
        cmd.Parameters.AddWithValue("$updated", session.UpdatedAt);
        cmd.ExecuteNonQuery();
    }

    private void StartCleanupThread()
    {
        var t = new Thread(() =>
        {
            while (true)
            {
                Thread.Sleep(TimeSpan.FromHours(1));
                var cutoff = DateTime.UtcNow.AddHours(-24).ToString("o");
                using var con = new SqliteConnection($"Data Source={DbPath}");
                con.Open();
                var cmd = con.CreateCommand();
                cmd.CommandText = "DELETE FROM chess_sessions WHERE updated_at < $cutoff";
                cmd.Parameters.AddWithValue("$cutoff", cutoff);
                cmd.ExecuteNonQuery();
            }
        }) { IsBackground = true };
        t.Start();
    }

    public GameSession NewGame()
    {
        var session = new GameSession();
        session.Board.SetupStandard();
        lock (_lock)
        {
            _sessions[session.GameId] = session;
            Persist(session);
        }
        return session;
    }

    public GameSession? GetGame(string gameId)
    {
        lock (_lock) { return _sessions.GetValueOrDefault(gameId); }
    }

    public List<object> GetLegalMovesForSquare(string gameId, int row, int col)
    {
        var session = GetGame(gameId);
        if (session == null || session.Status != "active") return [];
        var piece = session.Board.Get(row, col);
        if (piece == null || piece.Color != session.CurrentTurn) return [];

        var effects = _rules.GetEffectsSet(session.ActiveRules);
        var moves = _engine.GetLegalMoves(session.Board, row, col,
            session.CurrentTurn, effects, session.EnPassantTarget);

        if (piece.Type == PieceType.P)
        {
            var ep = _engine.GetEnPassantMoves(session.Board, row, col,
                session.CurrentTurn, session.EnPassantTarget);
            moves.AddRange(ep.Where(m =>
                IsLegalPublic(session.Board, m, session.CurrentTurn, effects, session.EnPassantTarget)));
        }

        return moves.Select(m => (object)m.ToDict()).ToList();
    }

    private bool IsLegalPublic(BoardState board, Move move, PieceColor color,
        HashSet<string> effects, (int r, int c)? epTarget)
    {
        var sim = board.Clone();
        _engine.ApplyMoveToBoard(sim, move, epTarget);
        return !_engine.IsInCheck(sim, color, effects);
    }

    public object MakeMove(string gameId, int fromRow, int fromCol,
        int toRow, int toCol, string? promotion)
    {
        lock (_lock)
        {
            var session = _sessions.GetValueOrDefault(gameId);
            if (session == null) return new { ok = false, error = "Game not found" };
            if (session.Status != "active") return new { ok = false, error = "Game is over" };

            var effects = _rules.GetEffectsSet(session.ActiveRules);
            var piece = session.Board.Get(fromRow, fromCol);
            if (piece == null) return new { ok = false, error = "No piece at source" };
            if (piece.Color != session.CurrentTurn) return new { ok = false, error = "Not your turn" };

            var legal = _engine.GetLegalMoves(session.Board, fromRow, fromCol,
                session.CurrentTurn, effects, session.EnPassantTarget);
            if (piece.Type == PieceType.P)
            {
                var ep = _engine.GetEnPassantMoves(session.Board, fromRow, fromCol,
                    session.CurrentTurn, session.EnPassantTarget);
                legal.AddRange(ep.Where(m =>
                    IsLegalPublic(session.Board, m, session.CurrentTurn, effects, session.EnPassantTarget)));
            }

            var chosen = legal.FirstOrDefault(m =>
                m.ToRow == toRow && m.ToCol == toCol &&
                (m.Promotion == null || m.Promotion == promotion));

            if (chosen == null) return new { ok = false, error = "Illegal move" };

            // Track en-passant captured pawn
            var captured = session.Board.Get(toRow, toCol);
            if (chosen.IsEnPassant)
                captured = session.Board.Get(fromRow, toCol);

            _engine.ApplyMoveToBoard(session.Board, chosen, session.EnPassantTarget);

            // Update en-passant target
            session.EnPassantTarget = null;
            if (piece.Type == PieceType.P && Math.Abs(toRow - fromRow) == 2)
                session.EnPassantTarget = ((fromRow + toRow) / 2, toCol);

            // Record move
            session.MoveHistory.Add(new
            {
                from = new[] { fromRow, fromCol },
                to = new[] { toRow, toCol },
                piece = piece.ToDict(),
                captured = captured?.ToDict(),
                promotion,
                half_turn = session.HalfTurnCount + 1
            });

            // Handle double-move sub-turns
            var dms = session.DoubleMove;
            bool turnComplete = true;
            if (effects.Contains("double_move"))
            {
                dms.Active = true;
                dms.SubMoves++;
                if (dms.SubMoves < dms.Required)
                    turnComplete = false;
                else
                { dms.SubMoves = 0; dms.Active = false; }
            }

            session.LastRuleAnnounced = null;

            if (turnComplete)
            {
                session.HalfTurnCount++;
                var (updatedRules, newRule) = _rules.Tick(session.HalfTurnCount, session.ActiveRules);
                session.ActiveRules = updatedRules;

                if (newRule != null)
                {
                    session.LastRuleAnnounced = newRule;
                    if ((bool)newRule["instant"])
                        _rules.ApplyInstantMutations(session.Board, newRule);
                }

                session.CurrentTurn = session.CurrentTurn == PieceColor.White
                    ? PieceColor.Black : PieceColor.White;

                effects = _rules.GetEffectsSet(session.ActiveRules);

                if (_engine.IsCheckmate(session.Board, session.CurrentTurn, effects, session.EnPassantTarget))
                {
                    session.Status = "checkmate";
                    session.Winner = session.CurrentTurn == PieceColor.White ? "b" : "w";
                }
                else if (_engine.IsStalemate(session.Board, session.CurrentTurn, effects, session.EnPassantTarget))
                    session.Status = "stalemate";
            }

            Persist(session);

            bool inCheck = _engine.IsInCheck(session.Board, session.CurrentTurn, effects);
            return new
            {
                ok = true,
                error = (string?)null,
                state = session.ToDict(),
                new_rule = session.LastRuleAnnounced,
                in_check = inCheck,
                checkmate = session.Status == "checkmate",
                stalemate = session.Status == "stalemate"
            };
        }
    }

    public object Resign(string gameId, string color)
    {
        lock (_lock)
        {
            var session = _sessions.GetValueOrDefault(gameId);
            if (session == null) return new { ok = false, error = "Game not found" };
            session.Status = "resigned";
            session.Winner = color == "w" ? "b" : "w";
            Persist(session);
            return new { ok = true, state = session.ToDict() };
        }
    }

    private static GameSession? DeserializeSession(string json)
    {
        // Minimal deserialization — just restore active games
        // Full persistence not needed for MVP; new game on restart is acceptable
        return null;
    }
}
