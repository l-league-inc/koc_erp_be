namespace KocDrive.Core.Update;

public sealed class ReleaseClient : IDisposable
{
    private readonly HttpClient _http;
    private readonly bool _ownsClient;

    public ReleaseClient(Uri baseAddress, HttpMessageHandler? handler = null)
    {
        if (!ApiEndpoint.TryParseBase(baseAddress.AbsoluteUri, out var parsed))
        {
            throw new ArgumentException("서버 주소는 https여야 합니다.", nameof(baseAddress));
        }

        _ownsClient = true;
        _http = handler == null ? new HttpClient() : new HttpClient(handler);
        _http.BaseAddress = parsed;
        _http.Timeout = TimeSpan.FromMinutes(10);
    }

    public async Task<AppRelease?> FetchAsync(CancellationToken cancellationToken)
    {
        using var response = await _http.GetAsync("api/v1/drive/release", cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException("업데이트를 확인하지 못했습니다.");
        }

        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        try
        {
            return AppReleaseManifest.Parse(body);
        }
        catch (System.Text.Json.JsonException)
        {
            throw new InvalidOperationException("업데이트를 확인하지 못했습니다.");
        }
    }

    public Task DownloadAsync(AppRelease release, string destination, CancellationToken cancellationToken) =>
        ReleaseFiles.SaveVerifiedAsync(_http, release.Url, release.Sha256, destination, cancellationToken);

    public void Dispose()
    {
        if (_ownsClient)
        {
            _http.Dispose();
        }
    }
}
