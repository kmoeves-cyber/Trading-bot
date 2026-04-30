namespace ChessGame.Models;

public class BoardState
{
    public Piece?[,] Grid { get; } = new Piece?[8, 8];

    public void SetupStandard()
    {
        PieceType[] backRow = [PieceType.R, PieceType.N, PieceType.B, PieceType.Q,
                                PieceType.K, PieceType.B, PieceType.N, PieceType.R];
        for (int c = 0; c < 8; c++)
        {
            Grid[0, c] = new Piece(backRow[c], PieceColor.Black);
            Grid[7, c] = new Piece(backRow[c], PieceColor.White);
            Grid[1, c] = new Piece(PieceType.P, PieceColor.Black);
            Grid[6, c] = new Piece(PieceType.P, PieceColor.White);
        }
    }

    public Piece? Get(int r, int c) =>
        r >= 0 && r <= 7 && c >= 0 && c <= 7 ? Grid[r, c] : null;

    public void Set(int r, int c, Piece? p) => Grid[r, c] = p;

    public (int r, int c)? FindKing(PieceColor color)
    {
        for (int r = 0; r < 8; r++)
            for (int c = 0; c < 8; c++)
                if (Grid[r, c] is { Type: PieceType.K } p && p.Color == color)
                    return (r, c);
        return null;
    }

    public BoardState Clone()
    {
        var b = new BoardState();
        for (int r = 0; r < 8; r++)
            for (int c = 0; c < 8; c++)
                b.Grid[r, c] = Grid[r, c]?.Clone();
        return b;
    }

    public object[][] ToArray()
    {
        var rows = new object[8][];
        for (int r = 0; r < 8; r++)
        {
            rows[r] = new object[8];
            for (int c = 0; c < 8; c++)
                rows[r][c] = Grid[r, c] != null
                    ? (object)Grid[r, c]!.ToDict()
                    : null!;
        }
        return rows;
    }
}
