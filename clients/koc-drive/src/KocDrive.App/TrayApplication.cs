using System.Collections.Concurrent;
using System.Diagnostics;
using KocDrive.CloudFiles;
using KocDrive.Core;
using KocDrive.Core.Api;
using KocDrive.Core.Sync;

namespace KocDrive.App;

internal sealed class TrayApplication : ApplicationContext
{
    private readonly NotifyIcon _icon;
    private readonly System.Windows.Forms.Timer _timer;
    private readonly PasswordVaultTokenStore _tokens = new();
    private readonly string _stateDirectory;
    private readonly string _settingsPath;
    private readonly string _syncRoot;
    private readonly SyncStore _store;
    private readonly ConcurrentDictionary<string, byte> _ignored = new(StringComparer.OrdinalIgnoreCase);
    private DriveSettings _settings;
    private KocClient _client;
    private SyncEngine? _engine;
    private SyncRootConnection? _connection;
    private FileSystemWatcher? _watcher;
    private System.Windows.Forms.Timer? _revealTimer;
    private bool _iconRevealed;
    private string? _pendingNotice;
    private int _announceSync;
    private readonly Form _dialogs = new DialogHost();
    private readonly ToolStripMenuItem _statusItem;
    private readonly ToolStripMenuItem _loginItem;
    private readonly ToolStripMenuItem _logoutItem;
    private readonly ToolStripMenuItem _syncItem;
    private int _applying;
    private int _ticking;
    private int _acceptLocalChanges;

    public TrayApplication()
    {
        _stateDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "KOC ERP");
        _settingsPath = Path.Combine(_stateDirectory, "settings.json");
        _syncRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "KOC ERP");
        Directory.CreateDirectory(_stateDirectory);
        _settings = DriveSettings.Load(_settingsPath);
        _settings.TryResolveApiBase(Environment.GetEnvironmentVariable("KOC_API_BASE"), out var apiBase);
        _client = new KocClient(apiBase, _tokens);
        _store = new SyncStore(Path.Combine(_stateDirectory, "state.db"));
        _dialogs.Show();
        _statusItem = MenuItem("로그인되지 않음", enabled: false);
        _loginItem = MenuItem("로그인", (_, _) => Defer(() => _ = LoginAsync()));
        _logoutItem = MenuItem("로그아웃", (_, _) => Logout());
        var folderItem = MenuItem("작업 폴더 열기", (_, _) => OpenWorkFolder());
        _syncItem = MenuItem("지금 동기화", (_, _) => Defer(SyncNow));
        var settingsItem = MenuItem("설정", (_, _) => Defer(OpenSettings));
        var exitItem = MenuItem("종료", (_, _) => ExitThread());
        var menu = new ContextMenuStrip
        {
            Renderer = new KocMenuRenderer(),
            Font = KocTheme.Menu,
            ShowImageMargin = false,
            BackColor = Color.White,
        };
        menu.Items.AddRange(new ToolStripItem[]
        {
            _statusItem,
            _loginItem,
            _logoutItem,
            folderItem,
            _syncItem,
            settingsItem,
            exitItem,
        });
        menu.Opening += (_, _) => RefreshMenu();
        RefreshMenu();
        _icon = new NotifyIcon
        {
            Icon = AppIcon.Load(),
            Visible = true,
            Text = "KOC ERP",
            ContextMenuStrip = menu,
        };
        _icon.DoubleClick += (_, _) => OpenWorkFolder();
        RevealTrayIcon();
        _timer = new System.Windows.Forms.Timer { Interval = _settings.IntervalMilliseconds };
        _timer.Tick += async (_, _) => await TickAsync();
        try
        {
            DesktopShortcut.Ensure(_syncRoot);
        }
        catch (Exception)
        {
        }

        StartupRegistration.Apply(_settings.LaunchAtStartup, StartupExecutable());
        _ = ResumeAsync();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _timer.Dispose();
            _revealTimer?.Dispose();
            _dialogs.Dispose();
            _watcher?.Dispose();
            _connection?.Dispose();
            _store.Dispose();
            _client.Dispose();
            _icon.Dispose();
        }

        base.Dispose(disposing);
    }

    private void RefreshMenu()
    {
        var loggedIn = IsLoggedIn;
        _statusItem.Text = LoginStatusText();
        _loginItem.Visible = !loggedIn;
        _logoutItem.Visible = loggedIn;
        _syncItem.Visible = loggedIn;
    }

    private static ToolStripMenuItem MenuItem(string text, EventHandler? onClick = null, bool enabled = true)
    {
        var item = new ToolStripMenuItem(text)
        {
            Enabled = enabled,
            Padding = new Padding(6, 6, 6, 6),
            ForeColor = enabled ? KocTheme.Text : KocTheme.Status,
        };
        if (onClick is not null)
        {
            item.Click += onClick;
        }

        return item;
    }

    private void Defer(Action action)
    {
        if (!_dialogs.IsHandleCreated)
        {
            _dialogs.CreateControl();
        }

        _dialogs.BeginInvoke(new MethodInvoker(() =>
        {
            try
            {
                action();
            }
            catch (Exception exception)
            {
                ShowFailure(exception);
            }
        }));
    }

    private DialogResult ShowModal(Form form)
    {
        _dialogs.Enabled = true;
        form.TopMost = true;
        form.StartPosition = FormStartPosition.Manual;
        PlaceOnScreen(form);
        var shown = false;
        form.Load += (_, _) => PlaceOnScreen(form);
        form.Shown += (_, _) => shown = true;
        var result = form.ShowDialog(_dialogs);
        _dialogs.Enabled = true;
        if (!shown)
        {
            throw new InvalidOperationException("창을 표시하지 못했습니다.");
        }

        return result;
    }

    private static void PlaceOnScreen(Form form)
    {
        Rectangle area;
        try
        {
            area = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1280, 800);
            var cursor = Cursor.Position;
            foreach (var screen in Screen.AllScreens)
            {
                if (screen.WorkingArea.Contains(cursor))
                {
                    area = screen.WorkingArea;
                    break;
                }
            }
        }
        catch (Exception)
        {
            return;
        }

        var overflow = form.Height - (area.Height - 24);
        if (overflow > 0)
        {
            form.ClientSize = new Size(form.ClientSize.Width, Math.Max(360, form.ClientSize.Height - overflow));
        }

        form.Location = new Point(
            area.Left + Math.Max(0, (area.Width - form.Width) / 2),
            area.Top + Math.Max(0, (area.Height - form.Height) / 2));
    }

    private static void ShowFailure(Exception exception)
    {
        AppInstall.WriteStartupLog(exception);
        var root = exception.GetBaseException();
        var frame = FirstFrame(root.StackTrace);
        var text = string.IsNullOrEmpty(frame) ? root.Message : root.Message + Environment.NewLine + frame;
        MessageBox.Show(text, "KOC ERP", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }

    private static string FirstFrame(string? stack)
    {
        if (string.IsNullOrWhiteSpace(stack))
        {
            return "";
        }

        foreach (var line in stack.Split('\n'))
        {
            var trimmed = line.Trim();
            if (trimmed.StartsWith("at ", StringComparison.Ordinal))
            {
                return trimmed;
            }
        }

        return "";
    }

    private bool IsLoggedIn => _tokens.LoadRefresh() is not null;

    private string LoginStatusText()
    {
        if (!IsLoggedIn)
        {
            return "로그인되지 않음";
        }

        var email = _store.ReadText("account");
        return string.IsNullOrWhiteSpace(email) ? "로그인됨" : $"로그인됨 · {email}";
    }

    private void OpenWorkFolder()
    {
        Directory.CreateDirectory(_syncRoot);
        Process.Start(new ProcessStartInfo
        {
            FileName = "explorer.exe",
            Arguments = $"\"{_syncRoot}\"",
            UseShellExecute = true,
        });
    }

    private void OpenSettings()
    {
        var environmentUrl = Environment.GetEnvironmentVariable("KOC_API_BASE");
        using var form = new SettingsForm(_settings, _store.ReadText("account"), _syncRoot, environmentUrl, OpenWorkFolder);
        if (ShowModal(form) != DialogResult.OK || form.Result is null)
        {
            return;
        }

        var previous = CurrentApiBase();
        _settings = form.Result;
        _settings.Save(_settingsPath);
        StartupRegistration.Apply(_settings.LaunchAtStartup, StartupExecutable());
        _timer.Interval = _settings.IntervalMilliseconds;
        var next = CurrentApiBase();
        if (!DriveSettings.SameApiBase(previous, next))
        {
            Logout();
            ReplaceClient(next);
            Report("서버 주소가 바뀌었습니다. 다시 로그인하세요.");
        }
    }

    private Uri CurrentApiBase()
    {
        _settings.TryResolveApiBase(Environment.GetEnvironmentVariable("KOC_API_BASE"), out var uri);
        return uri;
    }

    private void ReplaceClient(Uri baseUri)
    {
        var previous = _client;
        _client = new KocClient(baseUri, _tokens);
        previous.Dispose();
    }

    private static string StartupExecutable()
    {
        var current = Environment.ProcessPath ?? Application.ExecutablePath;
        if (File.Exists(AppInstall.ExePath)
            && string.Equals(Path.GetFileName(current), AppInstall.ExeName, StringComparison.OrdinalIgnoreCase))
        {
            return AppInstall.ExePath;
        }

        return current;
    }

    private void RevealTrayIcon()
    {
        _revealTimer = new System.Windows.Forms.Timer { Interval = 300 };
        _revealTimer.Tick += (_, _) =>
        {
            _revealTimer?.Stop();
            _revealTimer?.Dispose();
            _revealTimer = null;
            _icon.Visible = false;
            _icon.Visible = true;
            _iconRevealed = true;
            if (_pendingNotice is not null)
            {
                ShowNotice(_pendingNotice);
                _pendingNotice = null;
                return;
            }

            if (!IsLoggedIn)
            {
                ShowNotice("로그인이 필요합니다. 시계 옆 아이콘을 눌러 주세요.");
            }
        };
        _revealTimer.Start();
    }

    private async Task ResumeAsync()
    {
        if (_tokens.LoadRefresh() is null || _store.ReadLong("workspace") == 0)
        {
            SetStatus("로그인되지 않음");
            return;
        }

        BeginAnnouncedSync();
        try
        {
            await _client.EnsureAccessAsync(CancellationToken.None);
            await StartSyncAsync(_store.ReadLong("workspace"), _store.ReadLong("space"), _store.ReadLong("root"));
        }
        catch (Exception exception)
        {
            Volatile.Write(ref _announceSync, 0);
            Report(exception.Message);
        }
    }

    private async Task LoginAsync()
    {
        using var form = new LoginForm(async (email, password) =>
        {
            await _client.LoginAsync(email, password, CancellationToken.None);
            _store.WriteText("account", email);
        });
        if (ShowModal(form) != DialogResult.OK)
        {
            return;
        }

        try
        {
            var workspaces = await _client.ListWorkspacesAsync(CancellationToken.None);
            if (workspaces.Count == 0)
            {
                Report("워크스페이스가 없습니다.");
                Logout("워크스페이스가 없습니다.");
                return;
            }

            var workspaceId = workspaces[0].Id;
            if (workspaces.Count > 1)
            {
                using var picker = new WorkspaceForm(workspaces.Select(item => (item.Id, item.Name)).ToList());
                if (ShowModal(picker) != DialogResult.OK)
                {
                    Logout();
                    return;
                }

                workspaceId = picker.WorkspaceId;
            }

            var spaces = await _client.ListSpacesAsync(workspaceId, CancellationToken.None);
            var shared = spaces.First(space => space.Kind == "shared");
            _store.WriteLong("workspace", workspaceId);
            _store.WriteLong("space", shared.Id);
            _store.WriteLong("root", shared.RootFolderId);
            BeginAnnouncedSync();
            await StartSyncAsync(workspaceId, shared.Id, shared.RootFolderId);
        }
        catch (Exception exception)
        {
            Volatile.Write(ref _announceSync, 0);
            Report(exception.Message);
            if (_connection is null)
            {
                Logout(exception.Message);
            }
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
        Volatile.Write(ref _acceptLocalChanges, 1);
        _watcher.Created += (_, args) => OnLocalChange(args.FullPath, created: true);
        _watcher.Changed += (_, args) => OnLocalChange(args.FullPath, created: false);
        _watcher.Deleted += (_, args) => QueueDelete(args.FullPath);
        _watcher.Renamed += (_, args) => QueueRename(args.OldFullPath, args.FullPath);
        _timer.Start();
        await TickAsync();
    }

    private void SyncNow()
    {
        if (_engine is null)
        {
            return;
        }

        BeginAnnouncedSync();
        _ = TickAsync();
    }

    private void BeginAnnouncedSync()
    {
        Volatile.Write(ref _announceSync, 1);
        Notify("공유 문서를 동기화하고 있습니다.");
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
            if (Interlocked.Exchange(ref _announceSync, 0) == 1)
            {
                var changed = effects.Any(effect => effect is not SyncEffect.Status);
                Notify(changed
                    ? "동기화가 끝났습니다. 작업 폴더에서 확인해 주세요."
                    : "동기화가 끝났습니다. 이미 최신 상태입니다.");
            }
        }
        catch (Exception exception)
        {
            Interlocked.Exchange(ref _announceSync, 0);
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
        if (Volatile.Read(ref _acceptLocalChanges) == 0 || _applying > 0 || _engine is null || IsIgnored(fullPath) || IsDehydratedPlaceholder(fullPath))
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
        if (Volatile.Read(ref _acceptLocalChanges) == 0 || _applying > 0 || _engine is null)
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
        if (Volatile.Read(ref _acceptLocalChanges) == 0 || _applying > 0 || _engine is null)
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

    private void Logout(string? status = null)
    {
        Volatile.Write(ref _acceptLocalChanges, 0);
        _timer.Stop();
        _watcher?.Dispose();
        _watcher = null;
        _connection?.Dispose();
        _connection = null;
        _engine = null;
        ShellSyncRoot.Unregister();
        var removed = RemoveLocalFiles(_syncRoot);
        _store.ClearSession();
        _tokens.Clear();
        SetStatus(status ?? "로그인되지 않음");
        if (!removed)
        {
            Report("일부 파일은 다른 프로그램에서 사용 중이라 닫히지 않았습니다.");
        }
    }

    private static bool RemoveLocalFiles(string root)
    {
        if (!Directory.Exists(root))
        {
            return true;
        }

        var removed = true;
        foreach (var entry in Directory.EnumerateFileSystemEntries(root))
        {
            try
            {
                if (Directory.Exists(entry))
                {
                    foreach (var file in Directory.EnumerateFiles(entry, "*", SearchOption.AllDirectories))
                    {
                        File.SetAttributes(file, FileAttributes.Normal);
                    }

                    Directory.Delete(entry, recursive: true);
                }
                else
                {
                    File.SetAttributes(entry, FileAttributes.Normal);
                    File.Delete(entry);
                }
            }
            catch (Exception)
            {
                removed = false;
            }
        }

        return removed;
    }

    private void SetStatus(string message)
    {
        if (InvokeOnUi(() => SetStatus(message)))
        {
            return;
        }

        _icon.Text = message.Length <= 63 ? message : message[..63];
    }

    private void Report(string message) => Notify(message);

    private void Notify(string message)
    {
        if (InvokeOnUi(() => Notify(message)))
        {
            return;
        }

        SetStatus(message);
        if (!_settings.ShowNotifications)
        {
            return;
        }

        if (!_iconRevealed)
        {
            _pendingNotice = message;
            return;
        }

        ShowNotice(message);
    }

    private void ShowNotice(string message)
    {
        _icon.ShowBalloonTip(5000, "KOC ERP", message, ToolTipIcon.Info);
    }

    private bool InvokeOnUi(Action action)
    {
        if (!_dialogs.IsHandleCreated || !_dialogs.InvokeRequired)
        {
            return false;
        }

        _dialogs.BeginInvoke(new MethodInvoker(action));
        return true;
    }

    private sealed class DialogHost : Form
    {
        private bool _allowClose;

        public DialogHost()
        {
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            Location = new Point(-32000, -32000);
            ClientSize = new Size(1, 1);
            AutoScaleMode = AutoScaleMode.None;
        }

        protected override CreateParams CreateParams
        {
            get
            {
                const int toolWindow = 0x00000080;
                var parameters = base.CreateParams;
                parameters.ExStyle |= toolWindow;
                return parameters;
            }
        }

        protected override void Dispose(bool disposing)
        {
            _allowClose = true;
            base.Dispose(disposing);
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!_allowClose && e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                return;
            }

            base.OnFormClosing(e);
        }
    }

    private sealed class DiskContent(string root) : ILocalContent
    {
        public Task<byte[]> ReadAsync(string relativePath, CancellationToken cancellationToken) =>
            File.ReadAllBytesAsync(RelativePaths.Combine(root, relativePath), cancellationToken);
    }
}
