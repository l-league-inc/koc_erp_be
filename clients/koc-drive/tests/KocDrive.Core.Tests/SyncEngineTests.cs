using System.Net;
using System.Text;
using System.Text.Json;
using KocDrive.Core;
using KocDrive.Core.Api;
using KocDrive.Core.Sync;
using Xunit;

namespace KocDrive.Core.Tests;

public class ConflictTests
{
    [Fact]
    public void CleanServerChangeAppliesServer()
    {
        Assert.Equal(SyncAction.ApplyServer, ConflictPolicy.Decide("aaa", "aaa", "bbb", dirty: false));
    }

    [Fact]
    public void LocalOnlyChangeUploads()
    {
        Assert.Equal(SyncAction.UploadLocal, ConflictPolicy.Decide("aaa", "ccc", "aaa", dirty: true));
    }

    [Fact]
    public void BothSidesChangedCopiesConflict()
    {
        Assert.Equal(SyncAction.ConflictCopy, ConflictPolicy.Decide("aaa", "ccc", "bbb", dirty: true));
    }

    [Fact]
    public void ConflictNameKeepsExtension()
    {
        var taken = new HashSet<string> { "보고서 (충돌).pdf" };
        Assert.Equal("보고서 (충돌 2).pdf", ConflictNames.Copy("보고서.pdf", taken));
    }
}

public class SyncEngineTests : IDisposable
{
    private readonly string _database = Path.Combine(Path.GetTempPath(), $"koc-drive-{Guid.NewGuid():N}.db");
    private readonly MemoryContent _content = new();
    private readonly FakeApi _api = new();
    private readonly SyncStore _store;

    public SyncEngineTests()
    {
        _store = new SyncStore(_database);
    }

    [Fact]
    public async Task FirstTickBuildsPlaceholdersFromTheTree()
    {
        _api.Cursor = 4;
        _api.Folders.Add(new FolderInfo(2, 1, 10, "계약", false, "계약"));
        _api.Files.Add(new RemoteFile(3, 1, 1, 2, "a.txt", "text/plain", 4, "계약/a.txt", "abc"));
        var engine = Engine();

        var effects = await engine.TickAsync(CancellationToken.None);

        Assert.Contains(effects, effect => effect is SyncEffect.Upsert upsert && upsert.RelativePath == "계약");
        Assert.Contains(effects, effect => effect is SyncEffect.Upsert upsert && upsert.RelativePath == "계약/a.txt" && upsert.ContentHash == "abc");
        Assert.Equal(4, _store.Cursor);
    }

    [Fact]
    public void ClearSessionDropsLocalIndex()
    {
        _store.IsInitialized = true;
        _store.WriteLong("workspace", 7);
        _store.Save(new SyncNode
        {
            Entity = "file",
            ServerId = 3,
            ParentServerId = 10,
            Name = "a.txt",
            RelativePath = "a.txt",
            ServerHash = "abc",
            LocalHash = "abc",
            BaseHash = "abc",
            Size = 4,
            ContentType = "text/plain",
        });
        _store.Enqueue(new OutboxItem { Op = "delete", Entity = "file", ServerId = 3, RelativePath = "a.txt" });

        _store.ClearSession();

        Assert.Empty(_store.List());
        Assert.Empty(_store.ListOutbox());
        Assert.Equal(0, _store.ReadLong("workspace"));
        Assert.False(_store.IsInitialized);
    }

    [Fact]
    public async Task RemoteDeleteRemovesACleanFile()
    {
        _store.IsInitialized = true;
        _store.Cursor = 1;
        _store.Save(new SyncNode
        {
            Entity = "file",
            ServerId = 3,
            ParentServerId = 10,
            Name = "a.txt",
            RelativePath = "a.txt",
            ServerHash = "abc",
            LocalHash = "abc",
            BaseHash = "abc",
            Size = 4,
        });
        _api.Changes.Add(new ChangeItem(2, 1, "file", 3, "delete", EmptyPayload()));
        var effects = await Engine().TickAsync(CancellationToken.None);

        Assert.Contains(effects, effect => effect is SyncEffect.Remove remove && remove.RelativePath == "a.txt");
        Assert.Null(_store.Find("file", 3));
    }

    [Fact]
    public async Task LocalWriteReplacesWhenTheServerIsUnchanged()
    {
        var bytes = Encoding.UTF8.GetBytes("hello");
        var hash = Hashing.Sha256(bytes);
        _store.IsInitialized = true;
        _store.Save(new SyncNode
        {
            Entity = "file",
            ServerId = 3,
            ParentServerId = 10,
            Name = "a.txt",
            RelativePath = "a.txt",
            ServerHash = "abc",
            LocalHash = "abc",
            BaseHash = "abc",
            Size = 3,
        });
        _content.Files["a.txt"] = bytes;
        _api.ReplacedHash = hash;
        var engine = Engine();
        engine.QueueLocalWrite("a.txt");

        await engine.TickAsync(CancellationToken.None);

        Assert.Equal("abc", _api.ReplacedBaseHash);
        Assert.Equal(hash, _store.Find("file", 3)!.ServerHash);
        Assert.False(_store.Find("file", 3)!.Dirty);
    }

    [Fact]
    public async Task DivergedEditUploadsAConflictCopy()
    {
        var bytes = Encoding.UTF8.GetBytes("local");
        _store.IsInitialized = true;
        _store.Save(new SyncNode
        {
            Entity = "file",
            ServerId = 3,
            ParentServerId = 10,
            Name = "a.txt",
            RelativePath = "a.txt",
            ServerHash = "server",
            LocalHash = "old",
            BaseHash = "old",
            Size = 3,
            Dirty = true,
        });
        _content.Files["a.txt"] = bytes;
        _api.CreatedId = 9;
        var engine = Engine();
        engine.QueueLocalWrite("a.txt");

        var effects = await engine.TickAsync(CancellationToken.None);

        Assert.Equal("a (충돌).txt", _api.CreatedName);
        Assert.Contains(effects, effect => effect is SyncEffect.Upsert upsert && upsert.ServerId == 9);
        Assert.Contains(effects, effect => effect is SyncEffect.ApplyServer apply && apply.FileId == 3);
    }

    [Fact]
    public async Task MissingLocalFileIsDeletedOnTheServerWithoutRepeating()
    {
        _store.IsInitialized = true;
        _store.Save(new SyncNode
        {
            Entity = "file",
            ServerId = 3,
            ParentServerId = 10,
            Name = "test.txt",
            RelativePath = "test.txt",
            ServerHash = "abc",
            LocalHash = "abc",
            BaseHash = "abc",
            Size = 4,
        });
        var engine = Engine();
        engine.QueueLocalWrite("test.txt");

        var effects = await engine.TickAsync(CancellationToken.None);
        var again = await engine.TickAsync(CancellationToken.None);

        Assert.Contains(effects, effect => effect is SyncEffect.Remove remove && remove.RelativePath == "test.txt");
        Assert.DoesNotContain(effects, effect => effect is SyncEffect.Status);
        Assert.DoesNotContain(again, effect => effect is SyncEffect.Status);
        Assert.Equal([3L], _api.DeletedIds);
        Assert.Null(_store.Find("file", 3));
        Assert.Empty(_store.ListOutbox());
    }

    [Fact]
    public async Task DeleteOfAnAlreadyRemovedServerFileClearsTheQueue()
    {
        _store.IsInitialized = true;
        _store.Save(new SyncNode
        {
            Entity = "file",
            ServerId = 3,
            ParentServerId = 10,
            Name = "test.txt",
            RelativePath = "test.txt",
            ServerHash = "abc",
            LocalHash = "abc",
            BaseHash = "abc",
            Size = 4,
        });
        _api.DeleteStatus = 404;
        var engine = Engine();
        engine.QueueLocalDelete("test.txt");

        var effects = await engine.TickAsync(CancellationToken.None);

        Assert.Contains(effects, effect => effect is SyncEffect.Remove remove && remove.RelativePath == "test.txt");
        Assert.DoesNotContain(effects, effect => effect is SyncEffect.Status);
        Assert.Null(_store.Find("file", 3));
        Assert.Empty(_store.ListOutbox());
    }

    [Fact]
    public async Task ForbiddenDeleteAsksTheShellToRestoreTheFile()
    {
        _store.IsInitialized = true;
        _store.Save(new SyncNode
        {
            Entity = "file",
            ServerId = 3,
            ParentServerId = 10,
            Name = "a.txt",
            RelativePath = "a.txt",
            ServerHash = "abc",
            LocalHash = "abc",
            BaseHash = "abc",
            Size = 4,
        });
        _api.DeleteStatus = 403;
        var engine = Engine();
        engine.QueueLocalDelete("a.txt");

        var effects = await engine.TickAsync(CancellationToken.None);

        Assert.Contains(
            effects,
            effect => effect is SyncEffect.Restore restore && restore.ServerId == 3 && restore.RelativePath == "a.txt");
        Assert.NotNull(_store.Find("file", 3));
    }

    public void Dispose() => _store.Dispose();

    [Fact]
    public async Task LargeUploadAndHydrateAnnounceTheWait()
    {
        var uploadBytes = new byte[TransferTiming.GuideBytesPerSecond * 10];
        var hash = Hashing.Sha256(uploadBytes);
        _store.IsInitialized = true;
        _store.Save(new SyncNode
        {
            Entity = "file",
            ServerId = 3,
            ParentServerId = 10,
            Name = "도면.pdf",
            RelativePath = "도면.pdf",
            ServerHash = "abc",
            LocalHash = "abc",
            BaseHash = "abc",
            Size = TransferTiming.GuideBytesPerSecond * 60,
        });
        _content.Files["도면.pdf"] = uploadBytes;
        _api.ReplacedHash = hash;
        var notices = new List<string>();
        var engine = Engine(notices.Add);
        engine.QueueLocalWrite("도면.pdf");

        await engine.HydrateAsync(3, CancellationToken.None);
        await engine.TickAsync(CancellationToken.None);

        Assert.Equal("도면.pdf 파일을 받고 있습니다. 약 1분 걸릴 수 있습니다.", notices[0]);
        Assert.Equal("도면.pdf 파일을 올리고 있습니다. 약 10초 걸릴 수 있습니다.", notices[1]);
    }

    [Fact]
    public void OneGigabyteIsTheUploadCeiling()
    {
        Assert.Equal(1024L * 1024L * 1024L, SyncEngine.MaxBytes);
        Assert.Equal(859, TransferTiming.EstimatedSeconds(SyncEngine.MaxBytes));
        Assert.Equal("약 14분", TransferTiming.Duration(859));
        Assert.Null(TransferTiming.UploadMessage("a.txt", 4));
    }

    private SyncEngine Engine(Action<string>? notify = null) =>
        new(_api, _store, _content, workspaceId: 1, spaceId: 1, rootFolderId: 10, notify);

    private static JsonElement EmptyPayload() => JsonSerializer.SerializeToElement(new { });

    private sealed class MemoryContent : ILocalContent
    {
        public Dictionary<string, byte[]> Files { get; } = new();

        public Task<byte[]> ReadAsync(string relativePath, CancellationToken cancellationToken)
        {
            if (!Files.TryGetValue(relativePath, out var bytes))
            {
                throw new FileNotFoundException(relativePath);
            }

            return Task.FromResult(bytes);
        }
    }

    private sealed class FakeApi : IKocApi
    {
        public long Cursor { get; set; }

        public List<FolderInfo> Folders { get; } = new();

        public List<RemoteFile> Files { get; } = new();

        public List<ChangeItem> Changes { get; } = new();

        public string? ReplacedBaseHash { get; private set; }

        public string ReplacedHash { get; set; } = "";

        public string? CreatedName { get; private set; }

        public long CreatedId { get; set; } = 8;

        public Task LoginAsync(string email, string password, CancellationToken cancellationToken) => Task.CompletedTask;

        public Task EnsureAccessAsync(CancellationToken cancellationToken) => Task.CompletedTask;

        public Task<IReadOnlyList<WorkspaceInfo>> ListWorkspacesAsync(CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<WorkspaceInfo>>([]);

        public Task<IReadOnlyList<SpaceInfo>> ListSpacesAsync(long workspaceId, CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<SpaceInfo>>([]);

        public Task<long> SyncCursorAsync(long workspaceId, long spaceId, CancellationToken cancellationToken) =>
            Task.FromResult(Cursor);

        public Task<ChangePage> ChangesAsync(long workspaceId, long spaceId, long cursor, CancellationToken cancellationToken)
        {
            var rows = Changes.Where(change => change.Id > cursor).ToList();
            var next = rows.Count == 0 ? cursor : rows[^1].Id;
            return Task.FromResult(new ChangePage(rows, next));
        }

        public Task<IReadOnlyList<FolderInfo>> ListFoldersAsync(
            long workspaceId,
            long spaceId,
            long parentId,
            CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<FolderInfo>>(Folders.Where(folder => folder.ParentId == parentId).ToList());

        public Task<IReadOnlyList<RemoteFile>> ListFilesAsync(
            long workspaceId,
            long folderId,
            CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<RemoteFile>>(Files.Where(file => file.FolderId == folderId).ToList());

        public Task<FolderInfo> CreateFolderAsync(long workspaceId, long parentId, string name, CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<FolderInfo> UpdateFolderAsync(
            long workspaceId,
            long folderId,
            long? parentId,
            string? name,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task DeleteFolderAsync(long workspaceId, long folderId, CancellationToken cancellationToken) => Task.CompletedTask;

        public Task<RemoteFile> CreateFileAsync(
            long workspaceId,
            long folderId,
            string name,
            string contentType,
            byte[] bytes,
            CancellationToken cancellationToken)
        {
            CreatedName = name;
            var created = new RemoteFile(CreatedId, workspaceId, 1, folderId, name, contentType, bytes.Length, name, Hashing.Sha256(bytes));
            return Task.FromResult(created);
        }

        public Task<RemoteFile> ReplaceFileAsync(
            long workspaceId,
            long fileId,
            string contentType,
            byte[] bytes,
            string baseHash,
            CancellationToken cancellationToken)
        {
            ReplacedBaseHash = baseHash;
            return Task.FromResult(new RemoteFile(fileId, workspaceId, 1, 10, "a.txt", contentType, bytes.Length, "a.txt", ReplacedHash));
        }

        public Task<RemoteFile> UpdateFileAsync(
            long workspaceId,
            long fileId,
            long? folderId,
            string? name,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public int DeleteStatus { get; set; }

        public List<long> DeletedIds { get; } = new();

        public Task DeleteFileAsync(long workspaceId, long fileId, CancellationToken cancellationToken)
        {
            DeletedIds.Add(fileId);
            if (DeleteStatus >= 400)
            {
                throw new KocApiException(DeleteStatus, DeleteStatus == 404 ? "문서를 찾을 수 없습니다." : "권한이 없습니다.");
            }

            return Task.CompletedTask;
        }

        public Task<byte[]> DownloadAsync(long workspaceId, long fileId, CancellationToken cancellationToken) =>
            Task.FromResult(Array.Empty<byte>());
    }
}

public class KocClientTests
{
    [Fact]
    public async Task LoginStoresRefreshAndSendsBearer()
    {
        var handler = new ScriptedHandler();
        var tokens = new MemoryTokenStore();
        var client = new KocClient(new Uri("https://kocerpbe-main.up.railway.app"), tokens, handler);
        await client.LoginAsync("a@b.c", "secret", CancellationToken.None);
        var workspaces = await client.ListWorkspacesAsync(CancellationToken.None);

        Assert.Equal("refresh-1", tokens.Refresh);
        Assert.Equal("Bearer access-1", handler.Requests[1].Headers.Authorization?.ToString());
        Assert.Equal("문서", workspaces[0].Name);
    }

    private sealed class ScriptedHandler : HttpMessageHandler
    {
        public List<HttpRequestMessage> Requests { get; } = new();

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(request);
            var json = request.RequestUri!.AbsolutePath.EndsWith("/login", StringComparison.Ordinal)
                ? """{"access":"access-1","refresh":"refresh-1","status":"active"}"""
                : """[{"id":7,"name":"문서","slug":"docs","role":"owner"}]""";
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json"),
            });
        }
    }
}
