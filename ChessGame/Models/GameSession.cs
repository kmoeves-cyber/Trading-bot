namespace ChessGame.Models;

public class GameSession
{
    public string GameId { get; set; } = Guid.NewGuid().ToString();
    public BoardState Board { get; set; } = new();
    public PieceColor CurrentTurn { get; set; } = PieceColor.White;
    public int HalfTurnCount { get; set; } = 0;
    public List<Dictionary<string, object>> ActiveRules { get; set; } = [];
    public (int r, int c)? EnPassantTarget { get; set; }
    public Dictionary<string, object>? LastRuleAnnounced { get; set; }
    public string Status { get; set; } = "active";
    public string? Winner { get; set; }
    public DoubleMoveState DoubleMove { get; set; } = new();
    public List<object> MoveHistory { get; set; } = [];
    public string CreatedAt { get; set; } = DateTime.UtcNow.ToString("o");
    public string UpdatedAt { get; set; } = DateTime.UtcNow.ToString("o");

    public int TurnsUntilRule =>
        HalfTurnCount % 4 == 0 ? 4 : 4 - (HalfTurnCount % 4);

    public object ToDict() => new
    {
        game_id = GameId,
        board = Board.ToArray(),
        current_turn = CurrentTurn == PieceColor.White ? "w" : "b",
        half_turn_count = HalfTurnCount,
        active_rules = ActiveRules,
        en_passant_target = EnPassantTarget.HasValue
            ? new[] { EnPassantTarget.Value.r, EnPassantTarget.Value.c }
            : null,
        last_rule_announced = LastRuleAnnounced,
        status = Status,
        winner = Winner,
        double_move_state = new
        {
            active = DoubleMove.Active,
            sub_moves = DoubleMove.SubMoves,
            required = DoubleMove.Required
        },
        move_history = MoveHistory.TakeLast(50),
        turns_until_rule = TurnsUntilRule
    };
}

public class DoubleMoveState
{
    public bool Active { get; set; }
    public int SubMoves { get; set; }
    public int Required { get; set; } = 2;
}
