namespace ChessGame.Models;

public enum PieceType { K, Q, R, B, N, P }
public enum PieceColor { White, Black }

public class Piece
{
    public PieceType Type { get; set; }
    public PieceColor Color { get; set; }
    public bool HasMoved { get; set; }

    public Piece(PieceType type, PieceColor color, bool hasMoved = false)
    {
        Type = type;
        Color = color;
        HasMoved = hasMoved;
    }

    public Piece Clone() => new(Type, Color, HasMoved);

    public string ColorChar => Color == PieceColor.White ? "w" : "b";
    public string TypeChar => Type.ToString();

    public object ToDict() => new { type = TypeChar, color = ColorChar, has_moved = HasMoved };
}
