using System.Text.Json;

namespace KocDrive.Core.Sync;

public sealed class SyncEngine
{
    public const int MaxBytes = 50 * 1024 * 1024;

    private readonly IKocApi _api;
    private readonly SyncStore _store;
    private readonly ILocalContent _content;
    private readonly long _workspaceId;
    private readonly long _spaceId;
    private readonly long _rootFolderId;
    private readonly SemaphoreSlim _gate = new(1, 1);

    public SyncEngine(
        IKocApi api,
        SyncStore store,
        ILocalContent content,
        long workspaceId,
        long spaceId,
        long rootFolderId)
    {
        _api = api;
        _store = store;
        _content = content;
        _workspaceId = workspaceId;
        _spaceId = spaceId;
        _rootFolderId = rootFolderId;
    }

    public async Task<IReadOnlyList<SyncEffect>> TickAsync(CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            var effects = new List<SyncEffect>();
            if (!_store.IsInitialized)
            {
                await SnapshotAsync(cancellationToken);
                effects.AddRange(_store.List().Select(ToUpsert));
            }
            else
            {
                effects.AddRange(await PullAsync(cancellationToken));
            }

            effects.AddRange(await DrainAsync(cancellationToken));
            return effects;
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task<byte[]> HydrateAsync(long fileId, CancellationToken cancellationToken) =>
        await _api.DownloadAsync(_workspaceId, fileId, cancellationToken);

    public void QueueLocalWrite(string relativePath)
    {
        _gate.Wait();
        try
        {
            var path = Normalize(relativePath);
            var node = _store.FindByPath(path);
            if (node == null)
            {
                var parentId = ParentId(path);
                if (parentId == 0)
                {
                    return;
                }

                node = new SyncNode
                {
                    Entity = "file",
                    ServerId = _store.NextLocalId(),
                    ParentServerId = parentId,
                    Name = RelativePaths.Name(path),
                    RelativePath = path,
                    ContentType = ContentTypes.ForFileName(path),
                    Dirty = true,
                };
                _store.Save(node);
            }
            else if (!node.Dirty)
            {
                node.BaseHash = node.ServerHash;
                node.Dirty = true;
                _store.Save(node);
            }

            _store.Enqueue(new OutboxItem
            {
                Op = "write",
                Entity = node.Entity,
                ServerId = node.ServerId,
                RelativePath = path,
            });
        }
        finally
        {
            _gate.Release();
        }
    }

    public void QueueLocalFolder(string relativePath)
    {
        _gate.Wait();
        try
        {
            var path = Normalize(relativePath);
            if (_store.FindByPath(path) is not null)
            {
                return;
            }

            var parentId = ParentId(path);
            if (parentId == 0)
            {
                return;
            }

            var node = new SyncNode
            {
                Entity = "folder",
                ServerId = _store.NextLocalId(),
                ParentServerId = parentId,
                Name = RelativePaths.Name(path),
                RelativePath = path,
                Dirty = true,
            };
            _store.Save(node);
            _store.Enqueue(new OutboxItem
            {
                Op = "mkdir",
                Entity = "folder",
                ServerId = node.ServerId,
                RelativePath = path,
            });
        }
        finally
        {
            _gate.Release();
        }
    }

    public void QueueLocalDelete(string relativePath)
    {
        _gate.Wait();
        try
        {
            var path = Normalize(relativePath);
            var node = _store.FindByPath(path);
            if (node is null)
            {
                return;
            }

            _store.Enqueue(new OutboxItem
            {
                Op = "delete",
                Entity = node.Entity,
                ServerId = node.ServerId,
                RelativePath = path,
            });
        }
        finally
        {
            _gate.Release();
        }
    }

    public void QueueLocalRename(string fromRelativePath, string toRelativePath)
    {
        _gate.Wait();
        try
        {
            var from = Normalize(fromRelativePath);
            var to = Normalize(toRelativePath);
            var node = _store.FindByPath(from);
            if (node is null || from == to)
            {
                return;
            }

            _store.Enqueue(new OutboxItem
            {
                Op = "rename",
                Entity = node.Entity,
                ServerId = node.ServerId,
                RelativePath = from,
                OtherPath = to,
            });
        }
        finally
        {
            _gate.Release();
        }
    }

    private async Task SnapshotAsync(CancellationToken cancellationToken)
    {
        var cursor = await _api.SyncCursorAsync(_workspaceId, _spaceId, cancellationToken);
        await ImportFolderAsync(_rootFolderId, cancellationToken);
        _store.Cursor = cursor;
        _store.IsInitialized = true;
    }

    private async Task ImportFolderAsync(long folderId, CancellationToken cancellationToken)
    {
        var folders = await _api.ListFoldersAsync(_workspaceId, _spaceId, folderId, cancellationToken);
        foreach (var folder in folders)
        {
            _store.Save(CleanFolder(folder));
            await ImportFolderAsync(folder.Id, cancellationToken);
        }

        var files = await _api.ListFilesAsync(_workspaceId, folderId, cancellationToken);
        foreach (var file in files)
        {
            _store.Save(CleanFile(file));
        }
    }

    private async Task<IReadOnlyList<SyncEffect>> PullAsync(CancellationToken cancellationToken)
    {
        var effects = new List<SyncEffect>();
        var cursor = _store.Cursor;
        while (true)
        {
            var page = await _api.ChangesAsync(_workspaceId, _spaceId, cursor, cancellationToken);
            if (page.Changes.Count == 0 || page.NextCursor <= cursor)
            {
                _store.Cursor = page.NextCursor;
                break;
            }

            foreach (var change in page.Changes)
            {
                effects.AddRange(Apply(change));
            }

            cursor = page.NextCursor;
            _store.Cursor = cursor;
        }

        return effects;
    }

    private IReadOnlyList<SyncEffect> Apply(ChangeItem change)
    {
        if (change.Op == "delete")
        {
            var existing = _store.Find(change.Entity, change.EntityId);
            if (existing is null)
            {
                return [];
            }

            if (existing.Dirty)
            {
                return [new SyncEffect.Status("서버에서 지워진 항목에 로컬 수정이 남아 있습니다.")];
            }

            _store.Remove(existing.Entity, existing.ServerId);
            return [new SyncEffect.Remove(existing.RelativePath)];
        }

        var entity = change.Entity;
        var name = entity == "folder" ? Text(change.Payload, "name") : Text(change.Payload, "original_filename");
        var path = Text(change.Payload, "path");
        var parent = entity == "folder" ? Number(change.Payload, "parent_id") : Number(change.Payload, "folder_id");
        var hash = Text(change.Payload, "content_hash");
        var size = Number(change.Payload, "size");
        var contentType = Text(change.Payload, "content_type");
        if (string.IsNullOrEmpty(contentType))
        {
            contentType = "application/octet-stream";
        }

        var node = _store.Find(entity, change.EntityId);
        if (node is null)
        {
            node = new SyncNode
            {
                Entity = entity,
                ServerId = change.EntityId,
                ParentServerId = parent,
                Name = name,
                RelativePath = path,
                ServerHash = hash,
                LocalHash = hash,
                BaseHash = hash,
                Size = size,
                ContentType = contentType,
            };
            _store.Save(node);
            return [ToUpsert(node)];
        }

        var oldPath = node.RelativePath;
        node.ParentServerId = parent == 0 ? node.ParentServerId : parent;
        node.Name = string.IsNullOrEmpty(name) ? node.Name : name;
        node.RelativePath = string.IsNullOrEmpty(path) ? node.RelativePath : path;
        node.Size = entity == "file" ? size : node.Size;
        node.ContentType = entity == "file" ? contentType : node.ContentType;
        node.ServerHash = entity == "file" ? hash : node.ServerHash;
        if (!node.Dirty && entity == "file")
        {
            node.LocalHash = hash;
            node.BaseHash = hash;
        }

        _store.Save(node);
        if (node.Dirty)
        {
            return [];
        }

        if (oldPath != node.RelativePath)
        {
            _store.RewritePrefix(oldPath, node.RelativePath);
            return [new SyncEffect.Move(oldPath, node.RelativePath, node.Entity, node.ServerId, node.Size, node.ServerHash)];
        }

        return [ToUpsert(node)];
    }

    private async Task<IReadOnlyList<SyncEffect>> DrainAsync(CancellationToken cancellationToken)
    {
        var effects = new List<SyncEffect>();
        foreach (var item in _store.ListOutbox())
        {
            try
            {
                var done = item.Op switch
                {
                    "mkdir" => await DrainFolderAsync(item, effects, cancellationToken),
                    "write" => await DrainWriteAsync(item, effects, cancellationToken),
                    "delete" => await DrainDeleteAsync(item, effects, cancellationToken),
                    "rename" => await DrainRenameAsync(item, effects, cancellationToken),
                    _ => true,
                };
                if (!done)
                {
                    continue;
                }

                _store.DeleteOutbox(item.Id);
            }
            catch (KocApiException exception) when (exception.StatusCode == 403)
            {
                _store.DeleteOutbox(item.Id);
                var node = _store.Find(item.Entity, item.ServerId) ?? _store.FindByPath(item.RelativePath);
                effects.Add(node is null
                    ? new SyncEffect.Status("권한이 없어 서버에 반영하지 못했습니다.")
                    : new SyncEffect.Restore(
                        node.Entity,
                        node.ServerId,
                        node.RelativePath,
                        node.Size,
                        node.ServerHash,
                        "권한이 없어 서버에 반영하지 못했습니다."));
            }
            catch (KocApiException exception) when (exception.StatusCode == 409)
            {
                await UploadConflictCopyAsync(item, effects, cancellationToken);
                _store.DeleteOutbox(item.Id);
            }
            catch (KocApiException exception) when (exception.StatusCode == 400)
            {
                _store.DeleteOutbox(item.Id);
                effects.Add(new SyncEffect.Status(exception.Message));
            }
            catch (HttpRequestException)
            {
                effects.Add(new SyncEffect.Status("서버에 연결하지 못했습니다."));
                break;
            }
        }

        return effects;
    }

    private async Task<bool> DrainFolderAsync(OutboxItem item, List<SyncEffect> effects, CancellationToken cancellationToken)
    {
        var node = _store.FindByPath(item.RelativePath);
        if (node is null || node.ServerId > 0)
        {
            return true;
        }

        if (node.ParentServerId <= 0)
        {
            return false;
        }

        var created = await _api.CreateFolderAsync(_workspaceId, node.ParentServerId, node.Name, cancellationToken);
        _store.RetargetParent(node.ServerId, created.Id);
        _store.Remove(node.Entity, node.ServerId);
        var saved = CleanFolder(created);
        _store.Save(saved);
        effects.Add(ToUpsert(saved));
        return true;
    }

    private async Task<bool> DrainWriteAsync(OutboxItem item, List<SyncEffect> effects, CancellationToken cancellationToken)
    {
        var node = _store.FindByPath(item.RelativePath) ?? _store.Find(item.Entity, item.ServerId);
        if (node is null)
        {
            return true;
        }

        var bytes = await _content.ReadAsync(node.RelativePath, cancellationToken);
        if (bytes.Length < 1 || bytes.Length > MaxBytes)
        {
            effects.Add(new SyncEffect.Status("파일 크기는 1바이트 이상 50MB 이하여야 합니다."));
            node.Dirty = false;
            _store.Save(node);
            return true;
        }

        var localHash = Hashing.Sha256(bytes);
        var action = ConflictPolicy.Decide(node.BaseHash, localHash, node.ServerHash, node.Dirty || node.ServerId < 0);
        if (action is SyncAction.InSync)
        {
            node.Dirty = false;
            node.LocalHash = localHash;
            node.BaseHash = localHash;
            _store.Save(node);
            return true;
        }

        if (action is SyncAction.ConflictCopy)
        {
            await UploadConflictCopyAsync(node, bytes, effects, cancellationToken);
            return true;
        }

        var contentType = ContentTypes.ForFileName(node.Name);
        if (node.ServerId > 0)
        {
            var updated = await _api.ReplaceFileAsync(
                _workspaceId,
                node.ServerId,
                contentType,
                bytes,
                node.BaseHash,
                cancellationToken);
            RememberFile(node, updated);
            return true;
        }

        if (node.ParentServerId <= 0)
        {
            return false;
        }

        var created = await _api.CreateFileAsync(
            _workspaceId,
            node.ParentServerId,
            node.Name,
            contentType,
            bytes,
            cancellationToken);
        _store.Remove(node.Entity, node.ServerId);
        var saved = CleanFile(created);
        _store.Save(saved);
        effects.Add(ToUpsert(saved));
        return true;
    }

    private async Task<bool> DrainDeleteAsync(OutboxItem item, List<SyncEffect> effects, CancellationToken cancellationToken)
    {
        var node = _store.Find(item.Entity, item.ServerId) ?? _store.FindByPath(item.RelativePath);
        if (node is null)
        {
            return true;
        }

        if (node.ServerId > 0)
        {
            if (node.Entity == "folder")
            {
                await _api.DeleteFolderAsync(_workspaceId, node.ServerId, cancellationToken);
            }
            else
            {
                await _api.DeleteFileAsync(_workspaceId, node.ServerId, cancellationToken);
            }
        }

        _store.Remove(node.Entity, node.ServerId);
        effects.Add(new SyncEffect.Remove(node.RelativePath));
        return true;
    }

    private async Task<bool> DrainRenameAsync(OutboxItem item, List<SyncEffect> effects, CancellationToken cancellationToken)
    {
        var node = _store.Find(item.Entity, item.ServerId) ?? _store.FindByPath(item.RelativePath);
        if (node is null)
        {
            return true;
        }

        var destination = Normalize(item.OtherPath);
        var parentId = ParentId(destination);
        if (parentId == 0)
        {
            return false;
        }

        var name = RelativePaths.Name(destination);
        if (node.ServerId < 0)
        {
            var oldPath = node.RelativePath;
            node.Name = name;
            node.ParentServerId = parentId;
            node.RelativePath = destination;
            _store.Save(node);
            _store.RewritePrefix(oldPath, destination);
            return true;
        }

        if (node.Entity == "folder")
        {
            await _api.UpdateFolderAsync(
                _workspaceId,
                node.ServerId,
                parentId == node.ParentServerId ? null : parentId,
                name == node.Name ? null : name,
                cancellationToken);
        }
        else
        {
            await _api.UpdateFileAsync(
                _workspaceId,
                node.ServerId,
                parentId == node.ParentServerId ? null : parentId,
                name == node.Name ? null : name,
                cancellationToken);
        }

        var from = node.RelativePath;
        node.Name = name;
        node.ParentServerId = parentId;
        node.RelativePath = destination;
        _store.Save(node);
        _store.RewritePrefix(from, destination);
        effects.Add(new SyncEffect.Move(from, destination, node.Entity, node.ServerId, node.Size, node.ServerHash));
        return true;
    }

    private async Task UploadConflictCopyAsync(OutboxItem item, List<SyncEffect> effects, CancellationToken cancellationToken)
    {
        var node = _store.FindByPath(item.RelativePath) ?? _store.Find(item.Entity, item.ServerId);
        if (node is null)
        {
            return;
        }

        var bytes = await _content.ReadAsync(node.RelativePath, cancellationToken);
        await UploadConflictCopyAsync(node, bytes, effects, cancellationToken);
    }

    private async Task UploadConflictCopyAsync(
        SyncNode node,
        byte[] bytes,
        List<SyncEffect> effects,
        CancellationToken cancellationToken)
    {
        var taken = _store.SiblingNames(node.ParentServerId, "file", node.ServerId).ToHashSet(StringComparer.Ordinal);
        var name = ConflictNames.Copy(node.Name, taken);
        var created = await _api.CreateFileAsync(
            _workspaceId,
            node.ParentServerId,
            name,
            ContentTypes.ForFileName(name),
            bytes,
            cancellationToken);
        var saved = CleanFile(created);
        _store.Save(saved);
        node.Dirty = false;
        node.LocalHash = node.ServerHash;
        node.BaseHash = node.ServerHash;
        _store.Save(node);
        effects.Add(ToUpsert(saved));
        effects.Add(new SyncEffect.ApplyServer(node.ServerId, node.RelativePath, node.Size, node.ServerHash));
    }

    private void RememberFile(SyncNode node, RemoteFile updated)
    {
        node.ServerHash = updated.ContentHash;
        node.LocalHash = updated.ContentHash;
        node.BaseHash = updated.ContentHash;
        node.Size = updated.Size;
        node.ContentType = updated.ContentType;
        node.Dirty = false;
        node.Name = updated.OriginalFilename;
        node.RelativePath = updated.Path;
        _store.Save(node);
    }

    private long ParentId(string relativePath)
    {
        var parent = RelativePaths.Parent(relativePath);
        if (string.IsNullOrEmpty(parent))
        {
            return _rootFolderId;
        }

        return _store.FindByPath(parent)?.ServerId ?? 0;
    }

    private static SyncNode CleanFolder(FolderInfo folder) => new()
    {
        Entity = "folder",
        ServerId = folder.Id,
        ParentServerId = folder.ParentId ?? 0,
        Name = folder.Name,
        RelativePath = folder.Path,
        ContentType = "application/octet-stream",
    };

    private static SyncNode CleanFile(RemoteFile file) => new()
    {
        Entity = "file",
        ServerId = file.Id,
        ParentServerId = file.FolderId,
        Name = file.OriginalFilename,
        RelativePath = file.Path,
        ServerHash = file.ContentHash,
        LocalHash = file.ContentHash,
        BaseHash = file.ContentHash,
        Size = file.Size,
        ContentType = file.ContentType,
    };

    private static SyncEffect ToUpsert(SyncNode node) =>
        new SyncEffect.Upsert(node.Entity, node.ServerId, node.RelativePath, node.Size, node.ServerHash);

    private static string Normalize(string relativePath) => relativePath.Replace('\\', '/').Trim('/');

    private static string Text(JsonElement payload, string name) =>
        payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? ""
            : "";

    private static long Number(JsonElement payload, string name) =>
        payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty(name, out var value) && value.TryGetInt64(out var number)
            ? number
            : 0;
}
