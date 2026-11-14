using System.Text.Json;
using System.Text.Json.Serialization;

namespace KocDrive.Core.Api;

public sealed record TokenPair(
    [property: JsonPropertyName("access")] string Access,
    [property: JsonPropertyName("refresh")] string Refresh);

public sealed record WorkspaceInfo(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("slug")] string Slug,
    [property: JsonPropertyName("role")] string Role);

public sealed record SpaceInfo(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("workspace_id")] long WorkspaceId,
    [property: JsonPropertyName("kind")] string Kind,
    [property: JsonPropertyName("owner_id")] long? OwnerId,
    [property: JsonPropertyName("root_folder_id")] long RootFolderId);

public sealed record FolderInfo(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("space_id")] long SpaceId,
    [property: JsonPropertyName("parent_id")] long? ParentId,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("is_root")] bool IsRoot,
    [property: JsonPropertyName("path")] string Path);

public sealed record RemoteFile(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("workspace_id")] long WorkspaceId,
    [property: JsonPropertyName("space_id")] long SpaceId,
    [property: JsonPropertyName("folder_id")] long FolderId,
    [property: JsonPropertyName("original_filename")] string OriginalFilename,
    [property: JsonPropertyName("content_type")] string ContentType,
    [property: JsonPropertyName("size")] long Size,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("content_hash")] string ContentHash);

public sealed record UploadTicket(
    [property: JsonPropertyName("upload_url")] string UploadUrl,
    [property: JsonPropertyName("object_key")] string ObjectKey,
    [property: JsonPropertyName("content_type")] string ContentType);

public sealed record DownloadTicket(
    [property: JsonPropertyName("url")] string Url,
    [property: JsonPropertyName("expires_in")] int ExpiresIn);

public sealed record ChangeItem(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("space_id")] long SpaceId,
    [property: JsonPropertyName("entity")] string Entity,
    [property: JsonPropertyName("entity_id")] long EntityId,
    [property: JsonPropertyName("op")] string Op,
    [property: JsonPropertyName("payload")] JsonElement Payload);

public sealed record ChangePage(
    [property: JsonPropertyName("changes")] IReadOnlyList<ChangeItem> Changes,
    [property: JsonPropertyName("next_cursor")] long NextCursor);

public sealed record CursorBody([property: JsonPropertyName("cursor")] long Cursor);
