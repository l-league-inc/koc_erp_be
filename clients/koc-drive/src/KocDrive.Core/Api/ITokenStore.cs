namespace KocDrive.Core.Api;

public interface ITokenStore
{
    string? LoadRefresh();

    void SaveRefresh(string refresh);

    void Clear();
}

public sealed class MemoryTokenStore : ITokenStore
{
    public string? Refresh { get; private set; }

    public string? LoadRefresh() => Refresh;

    public void SaveRefresh(string refresh) => Refresh = refresh;

    public void Clear() => Refresh = null;
}
