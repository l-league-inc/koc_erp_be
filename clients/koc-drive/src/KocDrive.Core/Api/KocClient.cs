using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace KocDrive.Core.Api;

public sealed class KocClient : IKocApi
{
    public const string DefaultBaseUrl = "https://kocerpbe-main.up.railway.app";

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    private readonly HttpClient _api;
    private readonly HttpClient _blobs;
    private readonly ITokenStore _tokens;
    private string? _access;
    private string? _refresh;

    public KocClient(Uri baseAddress, ITokenStore tokens, HttpMessageHandler? handler = null)
    {
        _tokens = tokens;
        _refresh = tokens.LoadRefresh();
        _api = handler == null ? new HttpClient() : new HttpClient(handler);
        _api.BaseAddress = baseAddress;
        _blobs = new HttpClient();
    }

    public async Task LoginAsync(string email, string password, CancellationToken cancellationToken)
    {
        var pair = await SendAsync<TokenPair>(
            HttpMethod.Post,
            "api/v1/auth/login",
            new { email, password },
            authorize: false,
            cancellationToken);
        Remember(pair);
    }

    public async Task EnsureAccessAsync(CancellationToken cancellationToken)
    {
        if (!string.IsNullOrEmpty(_access))
        {
            return;
        }

        _refresh ??= _tokens.LoadRefresh();
        if (string.IsNullOrEmpty(_refresh))
        {
            throw new KocApiException(401, "로그인이 필요합니다.");
        }

        await RefreshAsync(cancellationToken);
    }

    public async Task<IReadOnlyList<WorkspaceInfo>> ListWorkspacesAsync(CancellationToken cancellationToken) =>
        await SendAsync<List<WorkspaceInfo>>(HttpMethod.Get, "api/v1/workspace", null, true, cancellationToken);

    public async Task<IReadOnlyList<SpaceInfo>> ListSpacesAsync(long workspaceId, CancellationToken cancellationToken) =>
        await SendAsync<List<SpaceInfo>>(
            HttpMethod.Get,
            $"api/v1/document/{workspaceId}/space",
            null,
            true,
            cancellationToken);

    public async Task<long> SyncCursorAsync(long workspaceId, long spaceId, CancellationToken cancellationToken)
    {
        var body = await SendAsync<CursorBody>(
            HttpMethod.Get,
            $"api/v1/document/{workspaceId}/sync-cursor?space_id={spaceId}",
            null,
            true,
            cancellationToken);
        return body.Cursor;
    }

    public Task<ChangePage> ChangesAsync(
        long workspaceId,
        long spaceId,
        long cursor,
        CancellationToken cancellationToken) =>
        SendAsync<ChangePage>(
            HttpMethod.Get,
            $"api/v1/document/{workspaceId}/changes?space_id={spaceId}&cursor={cursor}",
            null,
            true,
            cancellationToken);

    public async Task<IReadOnlyList<FolderInfo>> ListFoldersAsync(
        long workspaceId,
        long spaceId,
        long parentId,
        CancellationToken cancellationToken) =>
        await SendAsync<List<FolderInfo>>(
            HttpMethod.Get,
            $"api/v1/document/{workspaceId}/folder?space_id={spaceId}&parent_id={parentId}",
            null,
            true,
            cancellationToken);

    public async Task<IReadOnlyList<RemoteFile>> ListFilesAsync(
        long workspaceId,
        long folderId,
        CancellationToken cancellationToken) =>
        await SendAsync<List<RemoteFile>>(
            HttpMethod.Get,
            $"api/v1/document/{workspaceId}/file?folder_id={folderId}",
            null,
            true,
            cancellationToken);

    public Task<FolderInfo> CreateFolderAsync(
        long workspaceId,
        long parentId,
        string name,
        CancellationToken cancellationToken) =>
        SendAsync<FolderInfo>(
            HttpMethod.Post,
            $"api/v1/document/{workspaceId}/folder",
            new { parent_id = parentId, name },
            true,
            cancellationToken);

    public Task<FolderInfo> UpdateFolderAsync(
        long workspaceId,
        long folderId,
        long? parentId,
        string? name,
        CancellationToken cancellationToken)
    {
        var body = new Dictionary<string, object>();
        if (parentId is not null)
        {
            body["parent_id"] = parentId.Value;
        }

        if (name is not null)
        {
            body["name"] = name;
        }

        return SendAsync<FolderInfo>(
            HttpMethod.Patch,
            $"api/v1/document/{workspaceId}/folder/{folderId}",
            body,
            true,
            cancellationToken);
    }

    public Task DeleteFolderAsync(long workspaceId, long folderId, CancellationToken cancellationToken) =>
        SendAsync<object>(
            HttpMethod.Delete,
            $"api/v1/document/{workspaceId}/folder/{folderId}",
            null,
            true,
            cancellationToken);

    public async Task<RemoteFile> CreateFileAsync(
        long workspaceId,
        long folderId,
        string name,
        string contentType,
        byte[] bytes,
        CancellationToken cancellationToken)
    {
        var ticket = await SendAsync<UploadTicket>(
            HttpMethod.Post,
            $"api/v1/document/{workspaceId}/upload",
            new { folder_id = folderId, file_name = name, content_type = contentType, size = bytes.Length },
            true,
            cancellationToken);
        await PutBytesAsync(ticket, bytes, cancellationToken);
        return await SendAsync<RemoteFile>(
            HttpMethod.Post,
            $"api/v1/document/{workspaceId}/file",
            new
            {
                folder_id = folderId,
                object_key = ticket.ObjectKey,
                original_filename = name,
                content_type = ticket.ContentType,
                size = bytes.Length,
                content_hash = Hashing.Sha256(bytes),
            },
            true,
            cancellationToken);
    }

    public async Task<RemoteFile> ReplaceFileAsync(
        long workspaceId,
        long fileId,
        string contentType,
        byte[] bytes,
        string baseHash,
        CancellationToken cancellationToken)
    {
        var ticket = await SendAsync<UploadTicket>(
            HttpMethod.Post,
            $"api/v1/document/{workspaceId}/file/{fileId}/upload",
            new { content_type = contentType, size = bytes.Length, base_hash = baseHash },
            true,
            cancellationToken);
        await PutBytesAsync(ticket, bytes, cancellationToken);
        return await SendAsync<RemoteFile>(
            HttpMethod.Post,
            $"api/v1/document/{workspaceId}/file/{fileId}/content",
            new
            {
                object_key = ticket.ObjectKey,
                content_type = ticket.ContentType,
                size = bytes.Length,
                base_hash = baseHash,
                content_hash = Hashing.Sha256(bytes),
            },
            true,
            cancellationToken);
    }

    public Task<RemoteFile> UpdateFileAsync(
        long workspaceId,
        long fileId,
        long? folderId,
        string? name,
        CancellationToken cancellationToken)
    {
        var body = new Dictionary<string, object>();
        if (folderId is not null)
        {
            body["folder_id"] = folderId.Value;
        }

        if (name is not null)
        {
            body["original_filename"] = name;
        }

        return SendAsync<RemoteFile>(
            HttpMethod.Patch,
            $"api/v1/document/{workspaceId}/file/{fileId}",
            body,
            true,
            cancellationToken);
    }

    public Task DeleteFileAsync(long workspaceId, long fileId, CancellationToken cancellationToken) =>
        SendAsync<object>(
            HttpMethod.Delete,
            $"api/v1/document/{workspaceId}/file/{fileId}",
            null,
            true,
            cancellationToken);

    public async Task<byte[]> DownloadAsync(long workspaceId, long fileId, CancellationToken cancellationToken)
    {
        var ticket = await SendAsync<DownloadTicket>(
            HttpMethod.Post,
            $"api/v1/document/{workspaceId}/file/{fileId}/sync-url",
            null,
            true,
            cancellationToken);
        return await _blobs.GetByteArrayAsync(ticket.Url, cancellationToken);
    }

    private async Task RefreshAsync(CancellationToken cancellationToken)
    {
        var pair = await SendAsync<TokenPair>(
            HttpMethod.Post,
            "api/v1/auth/refresh",
            new { refresh = _refresh },
            authorize: false,
            cancellationToken);
        Remember(pair);
    }

    private void Remember(TokenPair pair)
    {
        _access = pair.Access;
        _refresh = pair.Refresh;
        _tokens.SaveRefresh(pair.Refresh);
    }

    private async Task PutBytesAsync(UploadTicket ticket, byte[] bytes, CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Put, ticket.UploadUrl);
        request.Content = new ByteArrayContent(bytes);
        request.Content.Headers.ContentType = new MediaTypeHeaderValue(ticket.ContentType);
        using var response = await _blobs.SendAsync(request, cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new KocApiException((int)response.StatusCode, "파일 업로드에 실패했습니다.");
        }
    }

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string path,
        object? body,
        bool authorize,
        CancellationToken cancellationToken)
    {
        using var response = await SendRawAsync(method, path, body, authorize, allowRefresh: true, cancellationToken);
        if (response.StatusCode == HttpStatusCode.NoContent || response.Content.Headers.ContentLength == 0)
        {
            return default!;
        }

        var payload = await response.Content.ReadFromJsonAsync<T>(Json, cancellationToken);
        return payload ?? throw new KocApiException((int)response.StatusCode, "응답이 비어 있습니다.");
    }

    private async Task<HttpResponseMessage> SendRawAsync(
        HttpMethod method,
        string path,
        object? body,
        bool authorize,
        bool allowRefresh,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null)
        {
            request.Content = JsonContent.Create(body, options: Json);
        }

        if (authorize && !string.IsNullOrEmpty(_access))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _access);
        }

        var response = await _api.SendAsync(request, cancellationToken);
        if (response.StatusCode == HttpStatusCode.Unauthorized && authorize && allowRefresh && _refresh is not null)
        {
            response.Dispose();
            await RefreshAsync(cancellationToken);
            return await SendRawAsync(method, path, body, authorize, allowRefresh: false, cancellationToken);
        }

        if (!response.IsSuccessStatusCode)
        {
            var detail = await response.Content.ReadAsStringAsync(cancellationToken);
            response.Dispose();
            throw new KocApiException((int)response.StatusCode, string.IsNullOrWhiteSpace(detail) ? "요청이 실패했습니다." : detail);
        }

        return response;
    }
}
