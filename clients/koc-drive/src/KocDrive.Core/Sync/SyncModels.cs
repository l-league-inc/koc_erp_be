namespace KocDrive.Core.Sync;

public sealed class SyncNode
{
    public string Entity { get; set; } = "file";

    public long ServerId { get; set; }

    public long ParentServerId { get; set; }

    public string Name { get; set; } = "";

    public string RelativePath { get; set; } = "";

    public string ServerHash { get; set; } = "";

    public string LocalHash { get; set; } = "";

    public string BaseHash { get; set; } = "";

    public long Size { get; set; }

    public string ContentType { get; set; } = "application/octet-stream";

    public bool Dirty { get; set; }
}

public sealed class OutboxItem
{
    public long Id { get; set; }

    public string Op { get; set; } = "";

    public string Entity { get; set; } = "";

    public long ServerId { get; set; }

    public string RelativePath { get; set; } = "";

    public string OtherPath { get; set; } = "";
}

public abstract record SyncEffect
{
    public sealed record Upsert(string Entity, long ServerId, string RelativePath, long Size, string ContentHash) : SyncEffect;

    public sealed record Remove(string RelativePath) : SyncEffect;

    public sealed record Move(string FromRelativePath, string RelativePath, string Entity, long ServerId, long Size, string ContentHash) : SyncEffect;

    public sealed record ApplyServer(long FileId, string RelativePath, long Size, string ContentHash) : SyncEffect;

    public sealed record Restore(
        string Entity,
        long ServerId,
        string RelativePath,
        long Size,
        string ContentHash,
        string Message) : SyncEffect;

    public sealed record Status(string Message) : SyncEffect;
}

public interface ILocalContent
{
    Task<byte[]> ReadAsync(string relativePath, CancellationToken cancellationToken);
}
