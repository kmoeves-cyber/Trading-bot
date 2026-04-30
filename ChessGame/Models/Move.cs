namespace ChessGame.Models;

public class Move
{
    public int FromRow { get; set; }
    public int FromCol { get; set; }
    public int ToRow { get; set; }
    public int ToCol { get; set; }
    public string? Promotion { get; set; }
    public bool IsCastle { get; set; }
    public bool IsEnPassant { get; set; }
    public bool IsKnighted { get; set; }
    public Piece? CapturedPiece { get; set; }

    public Move(int fromRow, int fromCol, int toRow, int toCol,
        string? promotion = null, bool isCastle = false,
        bool isEnPassant = false, bool isKnighted = false)
    {
        FromRow = fromRow; FromCol = fromCol;
        ToRow = toRow; ToCol = toCol;
        Promotion = promotion;
        IsCastle = isCastle;
        IsEnPassant = isEnPassant;
        IsKnighted = isKnighted;
    }

    public object ToDict() => new
    {
        from_row = FromRow, from_col = FromCol,
        to_row = ToRow, to_col = ToCol,
        promotion = Promotion,
        is_castle = IsCastle,
        is_en_passant = IsEnPassant,
        is_knighted = IsKnighted
    };
}
