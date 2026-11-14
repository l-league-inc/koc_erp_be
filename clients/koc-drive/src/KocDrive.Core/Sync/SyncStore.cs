using Microsoft.Data.Sqlite;

namespace KocDrive.Core.Sync;

public sealed class SyncStore : IDisposable
{
    private readonly SqliteConnection _connection;

    public SyncStore(string databasePath)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = databasePath,
            Mode = SqliteOpenMode.ReadWriteCreate,
        };
        _connection = new SqliteConnection(builder.ConnectionString);
        _connection.Open();
        Execute(
            """
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS nodes (
              entity TEXT NOT NULL,
              server_id INTEGER NOT NULL,
              parent_server_id INTEGER NOT NULL,
              name TEXT NOT NULL,
              relative_path TEXT NOT NULL,
              server_hash TEXT NOT NULL,
              local_hash TEXT NOT NULL,
              base_hash TEXT NOT NULL,
              size INTEGER NOT NULL,
              content_type TEXT NOT NULL,
              dirty INTEGER NOT NULL,
              PRIMARY KEY (entity, server_id)
            );
            CREATE TABLE IF NOT EXISTS outbox (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              op TEXT NOT NULL,
              entity TEXT NOT NULL,
              server_id INTEGER NOT NULL,
              relative_path TEXT NOT NULL,
              other_path TEXT NOT NULL
            );
            """);
    }

    public bool IsInitialized
    {
        get => GetMeta("initialized") == "1";
        set => SetMeta("initialized", value ? "1" : "0");
    }

    public long Cursor
    {
        get => long.TryParse(GetMeta("cursor"), out var value) ? value : 0;
        set => SetMeta("cursor", value.ToString());
    }

    public long ReadLong(string key) => long.TryParse(GetMeta(key), out var value) ? value : 0;

    public void WriteLong(string key, long value) => SetMeta(key, value.ToString());

    public long NextLocalId()
    {
        var current = long.TryParse(GetMeta("local_seq"), out var value) ? value : 0;
        var next = current >= 0 ? -1 : current - 1;
        SetMeta("local_seq", next.ToString());
        return next;
    }

    public void Save(SyncNode node)
    {
        Execute(
            """
            INSERT INTO nodes (
              entity, server_id, parent_server_id, name, relative_path,
              server_hash, local_hash, base_hash, size, content_type, dirty
            ) VALUES ($entity, $serverId, $parent, $name, $path, $serverHash, $localHash, $baseHash, $size, $type, $dirty)
            ON CONFLICT(entity, server_id) DO UPDATE SET
              parent_server_id = excluded.parent_server_id,
              name = excluded.name,
              relative_path = excluded.relative_path,
              server_hash = excluded.server_hash,
              local_hash = excluded.local_hash,
              base_hash = excluded.base_hash,
              size = excluded.size,
              content_type = excluded.content_type,
              dirty = excluded.dirty
            """,
            ("$entity", node.Entity),
            ("$serverId", node.ServerId),
            ("$parent", node.ParentServerId),
            ("$name", node.Name),
            ("$path", node.RelativePath),
            ("$serverHash", node.ServerHash),
            ("$localHash", node.LocalHash),
            ("$baseHash", node.BaseHash),
            ("$size", node.Size),
            ("$type", node.ContentType),
            ("$dirty", node.Dirty ? 1 : 0));
    }

    public SyncNode? Find(string entity, long serverId) =>
        QueryOne("SELECT * FROM nodes WHERE entity = $entity AND server_id = $serverId", ("$entity", entity), ("$serverId", serverId));

    public SyncNode? FindByPath(string relativePath) =>
        QueryOne("SELECT * FROM nodes WHERE relative_path = $path", ("$path", relativePath.Replace('\\', '/').Trim('/')));

    public IReadOnlyList<SyncNode> List() => Query("SELECT * FROM nodes ORDER BY relative_path, entity");

    public IReadOnlyList<string> SiblingNames(long parentServerId, string entity, long exceptServerId)
    {
        using var command = _connection.CreateCommand();
        command.CommandText = """
            SELECT name FROM nodes
            WHERE parent_server_id = $parent AND entity = $entity AND server_id <> $except
            """;
        command.Parameters.AddWithValue("$parent", parentServerId);
        command.Parameters.AddWithValue("$entity", entity);
        command.Parameters.AddWithValue("$except", exceptServerId);
        var names = new List<string>();
        using var reader = command.ExecuteReader();
        while (reader.Read())
        {
            names.Add(reader.GetString(0));
        }

        return names;
    }

    public void Remove(string entity, long serverId) =>
        Execute("DELETE FROM nodes WHERE entity = $entity AND server_id = $serverId", ("$entity", entity), ("$serverId", serverId));

    public void RetargetParent(long fromParentId, long toParentId) =>
        Execute(
            "UPDATE nodes SET parent_server_id = $to WHERE parent_server_id = $from",
            ("$to", toParentId),
            ("$from", fromParentId));

    public void RewritePrefix(string oldPrefix, string newPrefix)
    {
        foreach (var node in List())
        {
            var path = node.RelativePath;
            string? updated = null;
            if (path == oldPrefix)
            {
                updated = newPrefix;
            }
            else if (path.StartsWith(oldPrefix + "/", StringComparison.Ordinal))
            {
                updated = newPrefix + path[oldPrefix.Length..];
            }

            if (updated is null || updated == path)
            {
                continue;
            }

            node.RelativePath = updated;
            if (path == oldPrefix)
            {
                node.Name = RelativePaths.Name(updated);
            }

            Save(node);
        }
    }

    public void Enqueue(OutboxItem item)
    {
        if (item.Op is "write" or "delete" or "mkdir")
        {
            var existing = QueryOutbox().FirstOrDefault(row => row.Op == item.Op && row.RelativePath == item.RelativePath);
            if (existing is not null)
            {
                return;
            }
        }

        Execute(
            """
            INSERT INTO outbox (op, entity, server_id, relative_path, other_path)
            VALUES ($op, $entity, $serverId, $path, $other)
            """,
            ("$op", item.Op),
            ("$entity", item.Entity),
            ("$serverId", item.ServerId),
            ("$path", item.RelativePath),
            ("$other", item.OtherPath));
    }

    public IReadOnlyList<OutboxItem> ListOutbox() => QueryOutbox();

    public void DeleteOutbox(long id) => Execute("DELETE FROM outbox WHERE id = $id", ("$id", id));

    public void Dispose() => _connection.Dispose();

    private List<OutboxItem> QueryOutbox()
    {
        using var command = _connection.CreateCommand();
        command.CommandText = "SELECT id, op, entity, server_id, relative_path, other_path FROM outbox ORDER BY id";
        using var reader = command.ExecuteReader();
        var items = new List<OutboxItem>();
        while (reader.Read())
        {
            items.Add(new OutboxItem
            {
                Id = reader.GetInt64(0),
                Op = reader.GetString(1),
                Entity = reader.GetString(2),
                ServerId = reader.GetInt64(3),
                RelativePath = reader.GetString(4),
                OtherPath = reader.GetString(5),
            });
        }

        return items;
    }

    private void Execute(string sql, params (string Name, object Value)[] parameters)
    {
        using var command = _connection.CreateCommand();
        command.CommandText = sql;
        foreach (var (name, value) in parameters)
        {
            command.Parameters.AddWithValue(name, value);
        }

        command.ExecuteNonQuery();
    }

    private SyncNode? QueryOne(string sql, params (string Name, object Value)[] parameters)
    {
        var rows = Query(sql, parameters);
        return rows.Count == 0 ? null : rows[0];
    }

    private List<SyncNode> Query(string sql, params (string Name, object Value)[] parameters)
    {
        using var command = _connection.CreateCommand();
        command.CommandText = sql;
        foreach (var (name, value) in parameters)
        {
            command.Parameters.AddWithValue(name, value);
        }

        using var reader = command.ExecuteReader();
        var rows = new List<SyncNode>();
        while (reader.Read())
        {
            rows.Add(new SyncNode
            {
                Entity = reader.GetString(reader.GetOrdinal("entity")),
                ServerId = reader.GetInt64(reader.GetOrdinal("server_id")),
                ParentServerId = reader.GetInt64(reader.GetOrdinal("parent_server_id")),
                Name = reader.GetString(reader.GetOrdinal("name")),
                RelativePath = reader.GetString(reader.GetOrdinal("relative_path")),
                ServerHash = reader.GetString(reader.GetOrdinal("server_hash")),
                LocalHash = reader.GetString(reader.GetOrdinal("local_hash")),
                BaseHash = reader.GetString(reader.GetOrdinal("base_hash")),
                Size = reader.GetInt64(reader.GetOrdinal("size")),
                ContentType = reader.GetString(reader.GetOrdinal("content_type")),
                Dirty = reader.GetInt64(reader.GetOrdinal("dirty")) != 0,
            });
        }

        return rows;
    }

    private string? GetMeta(string key)
    {
        using var command = _connection.CreateCommand();
        command.CommandText = "SELECT value FROM meta WHERE key = $key";
        command.Parameters.AddWithValue("$key", key);
        return command.ExecuteScalar() as string;
    }

    private void SetMeta(string key, string value) =>
        Execute(
            "INSERT INTO meta (key, value) VALUES ($key, $value) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("$key", key),
            ("$value", value));
}
