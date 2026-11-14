namespace KocDrive.Core.Api;

public interface IKocApi
{
    Task LoginAsync(string email, string password, CancellationToken cancellationToken);

    Task EnsureAccessAsync(CancellationToken cancellationToken);

    Task<IReadOnlyList<WorkspaceInfo>> ListWorkspacesAsync(CancellationToken cancellationToken);

    Task<IReadOnlyList<SpaceInfo>> ListSpacesAsync(long workspaceId, CancellationToken cancellationToken);

    Task<long> SyncCursorAsync(long workspaceId, long spaceId, CancellationToken cancellationToken);

    Task<ChangePage> ChangesAsync(
        long workspaceId,
        long spaceId,
        long cursor,
        CancellationToken cancellationToken);

    Task<IReadOnlyList<FolderInfo>> ListFoldersAsync(
        long workspaceId,
        long spaceId,
        long parentId,
        CancellationToken cancellationToken);

    Task<IReadOnlyList<RemoteFile>> ListFilesAsync(
        long workspaceId,
        long folderId,
        CancellationToken cancellationToken);

    Task<FolderInfo> CreateFolderAsync(
        long workspaceId,
        long parentId,
        string name,
        CancellationToken cancellationToken);

    Task<FolderInfo> UpdateFolderAsync(
        long workspaceId,
        long folderId,
        long? parentId,
        string? name,
        CancellationToken cancellationToken);

    Task DeleteFolderAsync(long workspaceId, long folderId, CancellationToken cancellationToken);

    Task<RemoteFile> CreateFileAsync(
        long workspaceId,
        long folderId,
        string name,
        string contentType,
        byte[] bytes,
        CancellationToken cancellationToken);

    Task<RemoteFile> ReplaceFileAsync(
        long workspaceId,
        long fileId,
        string contentType,
        byte[] bytes,
        string baseHash,
        CancellationToken cancellationToken);

    Task<RemoteFile> UpdateFileAsync(
        long workspaceId,
        long fileId,
        long? folderId,
        string? name,
        CancellationToken cancellationToken);

    Task DeleteFileAsync(long workspaceId, long fileId, CancellationToken cancellationToken);

    Task<byte[]> DownloadAsync(long workspaceId, long fileId, CancellationToken cancellationToken);
}
