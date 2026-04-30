using ChessGame.Services;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSingleton<GameSessionManager>();
builder.WebHost.UseUrls("http://0.0.0.0:5001");

var app = builder.Build();
app.UseStaticFiles();

var manager = app.Services.GetRequiredService<GameSessionManager>();

// ── Chess page ────────────────────────────────────────────────────────────────
app.MapGet("/chess", () => Results.File(
    Path.Combine(app.Environment.WebRootPath, "chess.html"),
    "text/html"));

app.MapGet("/", () => Results.Redirect("/chess"));

// ── API routes ────────────────────────────────────────────────────────────────
app.MapPost("/api/chess/new", () =>
{
    var session = manager.NewGame();
    return Results.Json(session.ToDict());
});

app.MapGet("/api/chess/state", (string game_id) =>
{
    var session = manager.GetGame(game_id);
    return session == null
        ? Results.NotFound(new { error = "Game not found" })
        : Results.Json(session.ToDict());
});

app.MapGet("/api/chess/moves", (string game_id, int row, int col) =>
{
    var moves = manager.GetLegalMovesForSquare(game_id, row, col);
    return Results.Json(new { moves });
});

app.MapPost("/api/chess/move", async (HttpContext ctx) =>
{
    var body = await ctx.Request.ReadFromJsonAsync<MoveRequest>();
    if (body == null) return Results.BadRequest(new { error = "Invalid request" });
    var result = manager.MakeMove(body.game_id, body.from_row, body.from_col,
        body.to_row, body.to_col, body.promotion);
    return Results.Json(result);
});

app.MapPost("/api/chess/resign", async (HttpContext ctx) =>
{
    var body = await ctx.Request.ReadFromJsonAsync<ResignRequest>();
    if (body == null) return Results.BadRequest();
    return Results.Json(manager.Resign(body.game_id, body.color));
});

app.Run();

record MoveRequest(string game_id, int from_row, int from_col,
    int to_row, int to_col, string? promotion);
record ResignRequest(string game_id, string color);
