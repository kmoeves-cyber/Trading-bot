using ChessGame.Models;

namespace ChessGame.Engine;

public record RuleEffect(string Tag, Dictionary<string, string>? Params = null)
{
    public object ToDict() => new { tag = Tag, @params = Params ?? [] };
}

public record DynamicRule(
    string Id, string Name, string Description,
    List<RuleEffect> Effects, int Duration, string Emoji, bool Instant = false)
{
    public Dictionary<string, object> ToDict() => new()
    {
        ["id"] = Id, ["name"] = Name, ["description"] = Description,
        ["effects"] = Effects.Select(e => e.ToDict()).ToList(),
        ["duration"] = Duration, ["emoji"] = Emoji, ["instant"] = Instant
    };
}

public class RulesEngine
{
    private static readonly Random Rng = new();

    public static readonly List<DynamicRule> Catalog =
    [
        new("pawns_backward", "Reverse Pawns",
            "Pawns may now move backward as well as forward.",
            [new("pawns_backward")], 8, "↩️"),
        new("king_queen_move", "Royal Power",
            "Kings can move like queens — anywhere in a straight line.",
            [new("king_queen_move")], 8, "👑"),
        new("mirror_board", "Mirror World",
            "The board is displayed from both players' opposite perspective.",
            [new("mirror_board")], 8, "🪞"),
        new("double_move", "Double Time",
            "Each player makes 2 moves per turn instead of 1.",
            [new("double_move")], 8, "⏩"),
        new("early_promote", "Speed Promotion",
            "Pawns promote to Queen the moment they cross the midpoint.",
            [new("early_promote")], 8, "🚀"),
        new("rooks_diagonal", "Rook-Bishop Fusion",
            "Rooks can now also slide diagonally like bishops.",
            [new("rooks_diagonal")], 8, "✖️"),
        new("bishops_straight", "Bishop-Rook Fusion",
            "Bishops can now also slide straight like rooks.",
            [new("bishops_straight")], 8, "➕"),
        new("knights_rook", "Knight Charge",
            "Knights abandon their L-shape and now move like rooks.",
            [new("knights_rook")], 8, "🏇"),
        new("friendly_fire", "Friendly Fire",
            "Pieces may capture their own teammates. Be careful!",
            [new("friendly_fire")], 8, "💥"),
        new("forced_capture", "Blood Rule",
            "If any capture is possible, you MUST take it. No retreat.",
            [new("forced_capture")], 8, "🩸"),
        new("pawns_knight", "Pawn Uprising",
            "Pawns have learned the knight's L-shaped leap.",
            [new("pawns_knight")], 8, "♞"),
        new("all_jump", "Leap of Faith",
            "All pieces can jump over any other piece this round.",
            [new("all_jump")], 8, "🦘"),
        new("knighted_on_jump", "Knight Fever",
            "Any piece that jumps over 3+ pieces in one move becomes a knight.",
            [new("all_jump"), new("knighted_on_jump")], 8, "⚔️"),
        new("swap_rooks_bishops", "Rook-Bishop Swap",
            "All rooks instantly become bishops, and all bishops become rooks!",
            [new("swap_types", new() { ["from_type"] = "R", ["to_type"] = "B" }),
             new("swap_types", new() { ["from_type"] = "B", ["to_type"] = "R" })],
            0, "🔄", Instant: true),
        new("swap_queens_knights", "Queen-Knight Swap",
            "Queens and knights swap their identities across the whole board!",
            [new("swap_types", new() { ["from_type"] = "Q", ["to_type"] = "N" }),
             new("swap_types", new() { ["from_type"] = "N", ["to_type"] = "Q" })],
            0, "🃏", Instant: true),
        new("shuffle_white", "White Chaos",
            "All white pieces are teleported to random squares!",
            [new("shuffle", new() { ["color"] = "w" })],
            0, "🌀", Instant: true),
        new("shuffle_black", "Black Chaos",
            "All black pieces are teleported to random squares!",
            [new("shuffle", new() { ["color"] = "b" })],
            0, "🌪️", Instant: true),
    ];

    public DynamicRule PickRandomRule(IEnumerable<string> excludeIds)
    {
        var excluded = excludeIds.ToHashSet();
        var available = Catalog.Where(r => !excluded.Contains(r.Id)).ToList();
        if (available.Count == 0) available = Catalog;
        return available[Rng.Next(available.Count)];
    }

    public (List<Dictionary<string, object>> updated, Dictionary<string, object>? newRule)
        Tick(int halfTurn, List<Dictionary<string, object>> activeRules)
    {
        // Decrement and remove expired rules
        var updated = activeRules
            .Where(r => (int)r["duration"] > 0)
            .Select(r =>
            {
                var copy = new Dictionary<string, object>(r);
                copy["remaining_turns"] = (int)copy["remaining_turns"] - 1;
                return copy;
            })
            .Where(r => (int)r["remaining_turns"] > 0)
            .ToList();

        Dictionary<string, object>? newRule = null;
        if (halfTurn > 0 && halfTurn % 4 == 0)
        {
            var activeIds = updated.Select(r => (string)r["id"]);
            var rule = PickRandomRule(activeIds);
            newRule = rule.ToDict();
            if (!rule.Instant)
            {
                var rs = new Dictionary<string, object>(newRule)
                {
                    ["remaining_turns"] = rule.Duration
                };
                updated.Add(rs);
            }
        }

        return (updated, newRule);
    }

    public HashSet<string> GetEffectsSet(List<Dictionary<string, object>> activeRules)
    {
        var tags = new HashSet<string>();
        foreach (var rule in activeRules)
        {
            var effects = (List<object>)rule["effects"];
            foreach (var e in effects)
            {
                if (e is Dictionary<string, object> ed && ed.TryGetValue("tag", out var t))
                    tags.Add(t.ToString()!);
            }
        }
        return tags;
    }

    public void ApplyInstantMutations(BoardState board, Dictionary<string, object> ruleDict)
    {
        var effects = (List<object>)ruleDict["effects"];
        foreach (var e in effects)
        {
            if (e is not Dictionary<string, object> ed) continue;
            var tag = ed["tag"].ToString()!;
            var parms = ed.ContainsKey("params")
                ? (Dictionary<string, object>)ed["params"]
                : [];

            if (tag == "swap_types")
                SwapTypes(board,
                    parms["from_type"].ToString()!,
                    parms["to_type"].ToString()!);
            else if (tag == "shuffle")
                ShuffleColor(board,
                    parms["color"].ToString()! == "w" ? PieceColor.White : PieceColor.Black);
        }
    }

    private static void SwapTypes(BoardState board, string fromType, string toType)
    {
        Enum.TryParse<PieceType>(fromType, out var ft);
        Enum.TryParse<PieceType>(toType, out var tt);
        var froms = new List<(int, int)>();
        var tos = new List<(int, int)>();
        for (int r = 0; r < 8; r++)
            for (int c = 0; c < 8; c++)
            {
                var p = board.Get(r, c);
                if (p?.Type == ft) froms.Add((r, c));
                else if (p?.Type == tt) tos.Add((r, c));
            }
        foreach (var (r, c) in froms) board.Get(r, c)!.Type = tt;
        foreach (var (r, c) in tos) board.Get(r, c)!.Type = ft;
    }

    private static void ShuffleColor(BoardState board, PieceColor color, int maxAttempts = 20)
    {
        var engine = new ChessEngine();
        var positions = new List<(int r, int c)>();
        var pieces = new List<Piece>();
        for (int r = 0; r < 8; r++)
            for (int c = 0; c < 8; c++)
            {
                var p = board.Get(r, c);
                if (p?.Color == color) { positions.Add((r, c)); pieces.Add(p); }
            }

        for (int attempt = 0; attempt < maxAttempts; attempt++)
        {
            var shuffled = positions.OrderBy(_ => Rng.Next()).ToList();
            // Clear originals
            foreach (var (r, c) in positions) board.Set(r, c, null);
            // Place at shuffled positions
            for (int i = 0; i < shuffled.Count; i++)
                board.Set(shuffled[i].r, shuffled[i].c, pieces[i]);

            if (!engine.IsInCheck(board, PieceColor.White, []) &&
                !engine.IsInCheck(board, PieceColor.Black, []))
                return;
        }
        // Restore if all attempts fail
        foreach (var (r, c) in positions) board.Set(r, c, null);
        for (int i = 0; i < positions.Count; i++)
            board.Set(positions[i].r, positions[i].c, pieces[i]);
    }
}
