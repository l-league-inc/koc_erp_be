using System.Collections.Concurrent;
using KocDrive.CloudFiles;
using KocDrive.Core;
using KocDrive.Core.Api;
using KocDrive.Core.Sync;
using Microsoft.Win32;

namespace KocDrive.App;

internal sealed class TrayApplication : ApplicationContext
{
    private readonly NotifyIcon _icon;
    private readonly System.Windows.Forms.Timer _timer;
    private readonly PasswordVaultTokenStore _tokens = new();
    private readonly string _stateDirectory;
    private readonly string _syncRoot;
    private readonly KocClient _client;
    private readonly SyncStore _store;
    private readonly ConcurrentDictionary<string, byte> _ignored = new(StringComparer.OrdinalIgnoreCase);
    private SyncEngine? _engine;
    private SyncRootConnection? _connection;
    private FileSystemWatcher? _watcher;
    private int _applying;
    private int _ticking;

    public TrayApplication()
    {
        _stateDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "KOC ERP");
        _syncRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "KOC ERP");
        Directory.CreateDirectory(_stateDirectory);
        var apiBase = Environment.GetEnvironmentVariable("KOC_API_BASE");
        _client = new KocClient(new Uri(string.IsNullOrWhiteSpace(apiBase) ? KocClient.DefaultBaseUrl : apiBase), _tokens);
        _store = new SyncStore(Path.Combine(_stateDirectory, "state.db"));
        _icon = new NotifyIcon
        {
            Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath)
                ?? System.Drawing.SystemIcons.Application,
            Visible = true,
            Text = "KOC ERP",
            ContextMenuStrip = BuildMenu(),
        };
        _timer = new System.Windows.Forms.Timer { Interval = 15_000 };
        _timer.Tick += async (_, _) => await TickAsync();
        using var run = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
        run?.SetValue("KocDrive", Application.ExecutablePath);
        _ = ResumeAsync();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _timer.Dispose();
            _watcher?.Dispose();
            _connection?.Dispose();
            _store.Dispose();
            _icon.Dispose();
        }

        base.Dispose(disposing);
    }

    private ContextMenuStrip BuildMenu()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("로그인", null, async (_, _) => await LoginAsync());
        menu.Items.Add("지금 동기화", null, async (_, _) => await TickAsync());
        menu.Items.Add("로그아웃", null, (_, _) => Logout());
        menu.Items.Add("종료", null, (_, _) => ExitThread());
        return menu;
    }

    private async Task ResumeAsync()
    {
        if (_tokens.LoadRefresh() is null || _store.ReadLong("workspace") == 0)
        {
            SetStatus("로그인이 필요합니다.");
            return;
        }

        try
        {
            await _client.EnsureAccessAsync(CancellationToken.None);
            await StartSyncAsync(_store.ReadLong("workspace"), _store.ReadLong("space"), _store.ReadLong("root"));
        }
        catch (Exception exception)
        {
            Report(exception.Message);
        }
    }

    private async Task LoginAsync()
    {
        using var form = new LoginForm();
        if (form.ShowDialog() != DialogResult.OK)
        {
            return;
        }

        try
        {
            await _client.LoginAsync(form.Email, form.Password, CancellationToken.None);
            var workspaces = await _client.ListWorkspacesAsync(CancellationToken.None);
            if (workspaces.Count == 0)
            {
                Report("워크스페이스가 없습니다.");
                return;
            }

            var workspaceId = workspaces[0].Id;
            if (workspaces.Count > 1)
            {
                using var picker = new WorkspaceForm(workspaces.Select(item => (item.Id, item.Name)).ToList());
                if (picker.ShowDialog() != DialogResult.OK)
                {
                    return;
                }

                workspaceId = picker.WorkspaceId;
            }

            var spaces = await _client.ListSpacesAsync(workspaceId, CancellationToken.None);
            var shared = spaces.First(space => space.Kind == "shared");
            _store.WriteLong("workspace", workspaceId);
            _store.WriteLong("space", shared.Id);
            _store.WriteLong("root", shared.RootFolderId);
            await StartSyncAsync(workspaceId, shared.Id, shared.RootFolderId);
        }
        catch (Exception exception)
        {
            Report(exception.Message);
        }
    }

    private async Task StartSyncAsync(long workspaceId, long spaceId, long rootFolderId)
    {
        _watcher?.Dispose();
        _connection?.Dispose();
        var content = new DiskContent(_syncRoot);
        _engine = new SyncEngine(_client, _store, content, workspaceId, spaceId, rootFolderId);
        await ShellSyncRoot.RegisterAsync(_syncRoot);
        _connection = new SyncRootConnection(_engine, _syncRoot, Report);
        _connection.Connect();
        _watcher = new FileSystemWatcher(_syncRoot)
        {
            IncludeSubdirectories = true,
            EnableRaisingEvents = true,
            NotifyFilter = NotifyFilters.FileName | NotifyFilters.DirectoryName | NotifyFilters.LastWrite | NotifyFilters.Size,
        };
        _watcher.Created += (_, args) => OnLocalChange(args.FullPath, created: true);
        _watcher.Changed += (_, args) => OnLocalChange(args.FullPath, created: false);
        _watcher.Deleted += (_, args) => QueueDelete(args.FullPath);
        _watcher.Renamed += (_, args) => QueueRename(args.OldFullPath, args.FullPath);
        _timer.Start();
        await TickAsync();
    }

    private async Task TickAsync()
    {
        if (_engine is null || Interlocked.Exchange(ref _ticking, 1) == 1)
        {
            return;
        }

        try
        {
            SetStatus("동기화 중");
            var effects = await _engine.TickAsync(CancellationToken.None);
            Interlocked.Increment(ref _applying);
            try
            {
                Apply(effects);
            }
            finally
            {
                Interlocked.Decrement(ref _applying);
            }

            SetStatus("동기화됨");
        }
        catch (Exception exception)
        {
            Report(exception.Message);
        }
        finally
        {
            Interlocked.Exchange(ref _ticking, 0);
        }
    }

    private void Apply(IReadOnlyList<SyncEffect> effects)
    {
        if (_connection is null || _engine is null)
        {
            return;
        }

        foreach (var effect in effects)
        {
            switch (effect)
            {
                case SyncEffect.Upsert upsert:
                    Ignore(upsert.RelativePath);
                    _connection.Upsert(upsert.Entity, upsert.ServerId, upsert.RelativePath, upsert.Size);
                    break;
                case SyncEffect.Move move:
                    MoveLocal(move.FromRelativePath, move.RelativePath);
                    Ignore(move.RelativePath);
                    _connection.Upsert(move.Entity, move.ServerId, move.RelativePath, move.Size);
                    break;
                case SyncEffect.Remove remove:
                    DeleteLocal(remove.RelativePath);
                    break;
                case SyncEffect.ApplyServer apply:
                    OverwriteFromServer(apply);
                    break;
                case SyncEffect.Restore restore:
                    Ignore(restore.RelativePath);
                    _connection.Upsert(restore.Entity, restore.ServerId, restore.RelativePath, restore.Size);
                    Report(restore.Message);
                    break;
                case SyncEffect.Status status:
                    Report(status.Message);
                    break;
            }
        }
    }

    private void OverwriteFromServer(SyncEffect.ApplyServer apply)
    {
        if (_engine is null || _connection is null)
        {
            return;
        }

        var bytes = _engine.HydrateAsync(apply.FileId, CancellationToken.None).GetAwaiter().GetResult();
        var full = RelativePaths.Combine(_syncRoot, apply.RelativePath);
        Ignore(apply.RelativePath);
        Directory.CreateDirectory(Path.GetDirectoryName(full)!);
        File.WriteAllBytes(full, bytes);
        _connection.Upsert("file", apply.FileId, apply.RelativePath, bytes.Length);
    }

    private void OnLocalChange(string fullPath, bool created)
    {
        if (_applying > 0 || _engine is null || IsIgnored(fullPath) || IsDehydratedPlaceholder(fullPath))
        {
            return;
        }

        var relative = ToRelative(fullPath);
        if (relative is null)
        {
            return;
        }

        if (Directory.Exists(fullPath))
        {
            _engine.QueueLocalFolder(relative);
            return;
        }

        if (!created || File.Exists(fullPath))
        {
            _engine.QueueLocalWrite(relative);
        }
    }

    private void QueueDelete(string fullPath)
    {
        if (_applying > 0 || _engine is null)
        {
            return;
        }

        var relative = ToRelative(fullPath);
        if (relative is not null)
        {
            _engine.QueueLocalDelete(relative);
        }
    }

    private void QueueRename(string oldFullPath, string fullPath)
    {
        if (_applying > 0 || _engine is null)
        {
            return;
        }

        var from = ToRelative(oldFullPath);
        var to = ToRelative(fullPath);
        if (from is not null && to is not null)
        {
            _engine.QueueLocalRename(from, to);
        }
    }

    private void MoveLocal(string fromRelative, string toRelative)
    {
        var from = RelativePaths.Combine(_syncRoot, fromRelative);
        var to = RelativePaths.Combine(_syncRoot, toRelative);
        if (!File.Exists(from) && !Directory.Exists(from))
        {
            return;
        }

        Ignore(toRelative);
        Directory.CreateDirectory(Path.GetDirectoryName(to)!);
        Directory.Move(from, to);
    }

    private void DeleteLocal(string relativePath)
    {
        var full = RelativePaths.Combine(_syncRoot, relativePath);
        Ignore(relativePath);
        if (File.Exists(full))
        {
            File.Delete(full);
        }
        else if (Directory.Exists(full))
        {
            Directory.Delete(full, recursive: false);
        }
    }

    private void Ignore(string relativePath)
    {
        var full = RelativePaths.Combine(_syncRoot, relativePath);
        _ignored[full] = 0;
    }

    private bool IsIgnored(string fullPath)
    {
        var full = Path.GetFullPath(fullPath);
        return _ignored.TryRemove(full, out _);
    }

    private string? ToRelative(string fullPath)
    {
        var root = Path.GetFullPath(_syncRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var full = Path.GetFullPath(fullPath);
        if (!full.StartsWith(root, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        return full[root.Length..].Replace(Path.DirectorySeparatorChar, '/');
    }

    private static bool IsDehydratedPlaceholder(string path)
    {
        try
        {
            var attributes = (int)File.GetAttributes(path);
            return (attributes & 0x400000) != 0;
        }
        catch (Exception)
        {
            return false;
        }
    }

    private void Logout()
    {
        _timer.Stop();
        _watcher?.Dispose();
        _watcher = null;
        _connection?.Dispose();
        _connection = null;
        _engine = null;
        _tokens.Clear();
        SetStatus("로그아웃됨");
    }

    private void SetStatus(string message)
    {
        _icon.Text = message.Length <= 63 ? message : message[..63];
    }

    private void Report(string message)
    {
        SetStatus(message);
        _icon.ShowBalloonTip(4000, "KOC ERP", message, ToolTipIcon.Info);
    }

    private sealed class DiskContent(string root) : ILocalContent
    {
        public Task<byte[]> ReadAsync(string relativePath, CancellationToken cancellationToken) =>
            File.ReadAllBytesAsync(RelativePaths.Combine(root, relativePath), cancellationToken);
    }
}
