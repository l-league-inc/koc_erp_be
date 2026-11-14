using KocDrive.Core;

namespace KocDrive.App;

internal sealed class SettingsForm : KocDialog
{
    private readonly KocField _server;
    private readonly CheckBox _launch;
    private readonly KocField _interval;
    private readonly CheckBox _notifications;
    private readonly Label _error;
    private readonly Action _openFolder;

    public SettingsForm(DriveSettings current, string? account, string syncRoot, string? environmentUrl, Action openFolder)
        : base("KOC ERP", 700)
    {
        _openFolder = openFolder;
        AddLogo();
        AddHeading("설정");
        Body.Controls.Add(Caption("서버 주소"));
        _server = AddField("https://");
        _server.Value = current.ServerUrl;
        if (!string.IsNullOrWhiteSpace(environmentUrl))
        {
            Body.Controls.Add(Hint($"환경 변수 KOC_API_BASE가 우선합니다. 지금 주소는 {environmentUrl.Trim()} 입니다."));
        }

        _launch = Check("Windows 시작 시 자동 실행", current.LaunchAtStartup);
        Body.Controls.Add(_launch);
        Body.Controls.Add(Caption("동기화 간격 (초)"));
        _interval = AddField("15");
        _interval.Value = current.SyncIntervalSeconds.ToString();
        Body.Controls.Add(Hint("최소 5초입니다."));
        _notifications = Check("상태 알림", current.ShowNotifications);
        Body.Controls.Add(_notifications);
        Body.Controls.Add(Info("계정", string.IsNullOrWhiteSpace(account) ? "로그인되지 않음" : account));
        Body.Controls.Add(Info("작업 폴더", syncRoot));
        var open = AddButton("작업 폴더 열기", primary: false);
        open.Click += (_, _) => _openFolder();
        _error = AddError();
        var save = AddButton("저장");
        save.Click += (_, _) => Save();
        AcceptButton = save;
    }

    public DriveSettings? Result { get; private set; }

    private void Save()
    {
        var server = _server.Value.Trim();
        var intervalText = _interval.Value.Trim();
        _server.Invalid = !DriveSettings.IsAcceptableServerUrl(server);
        var intervalOk = int.TryParse(intervalText, out var seconds) && seconds >= DriveSettings.MinimumIntervalSeconds;
        _interval.Invalid = !intervalOk;
        if (!DriveSettings.IsAcceptableServerUrl(server))
        {
            ShowError(_error, "서버 주소는 https여야 합니다. 이 컴퓨터 주소만 http를 쓸 수 있습니다.");
            return;
        }

        if (!intervalOk)
        {
            ShowError(_error, "동기화 간격은 5초 이상이어야 합니다.");
            return;
        }

        Result = new DriveSettings
        {
            ServerUrl = server,
            LaunchAtStartup = _launch.Checked,
            SyncIntervalSeconds = seconds,
            ShowNotifications = _notifications.Checked,
        };
        DialogResult = DialogResult.OK;
        Close();
    }

    private static Label Caption(string text) => new()
    {
        Text = text,
        AutoSize = false,
        Width = ContentWidth,
        Height = 20,
        ForeColor = KocTheme.Status,
        BackColor = KocTheme.Card,
        Font = KocTheme.Hint,
        Margin = new Padding(0, 4, 0, 6),
    };

    private static Label Hint(string text) => new()
    {
        Text = text,
        AutoSize = false,
        Width = ContentWidth,
        Height = 40,
        ForeColor = KocTheme.Status,
        BackColor = KocTheme.Card,
        Font = KocTheme.Hint,
        Margin = new Padding(0, 0, 0, 12),
    };

    private static CheckBox Check(string text, bool value) => new()
    {
        Text = text,
        Checked = value,
        AutoSize = false,
        Width = ContentWidth,
        Height = 28,
        ForeColor = KocTheme.Text,
        BackColor = KocTheme.Card,
        Font = KocTheme.Label,
        Margin = new Padding(0, 4, 0, 12),
    };

    private static Panel Info(string caption, string value)
    {
        var panel = new Panel
        {
            Width = ContentWidth,
            Height = 52,
            BackColor = KocTheme.Card,
            Margin = new Padding(0, 0, 0, 8),
        };
        panel.Controls.Add(new Label
        {
            Text = caption,
            AutoSize = false,
            Bounds = new Rectangle(0, 0, ContentWidth, 18),
            ForeColor = KocTheme.Status,
            BackColor = KocTheme.Card,
            Font = KocTheme.Hint,
            Location = new Point(0, 0),
        });
        panel.Controls.Add(new Label
        {
            Text = value,
            AutoSize = false,
            AutoEllipsis = true,
            ForeColor = KocTheme.Text,
            BackColor = KocTheme.Card,
            Font = KocTheme.InputFont,
            Location = new Point(0, 20),
            Size = new Size(ContentWidth, 28),
        });
        return panel;
    }
}
