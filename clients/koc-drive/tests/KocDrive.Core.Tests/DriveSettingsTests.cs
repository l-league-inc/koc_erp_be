using KocDrive.Core;
using KocDrive.Core.Api;
using Xunit;

namespace KocDrive.Core.Tests;

public class DriveSettingsTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), "koc-drive-settings-" + Guid.NewGuid().ToString("N"));

    public DriveSettingsTests() => Directory.CreateDirectory(_directory);

    public void Dispose() => Directory.Delete(_directory, recursive: true);

    [Fact]
    public void MissingFileUsesDefaults()
    {
        var settings = DriveSettings.Load(FilePath("missing.json"));

        Assert.Equal("", settings.ServerUrl);
        Assert.True(settings.LaunchAtStartup);
        Assert.Equal(DriveSettings.DefaultIntervalSeconds, settings.SyncIntervalSeconds);
        Assert.True(settings.ShowNotifications);
        Assert.True(settings.AutoUpdate);
    }

    [Fact]
    public void RoundTripKeepsValues()
    {
        var settings = new DriveSettings
        {
            ServerUrl = "https://erp.example.com",
            LaunchAtStartup = false,
            SyncIntervalSeconds = 30,
            ShowNotifications = false,
            AutoUpdate = false,
        };
        var path = FilePath("settings.json");
        settings.Save(path);

        var loaded = DriveSettings.Load(path);

        Assert.Equal("https://erp.example.com", loaded.ServerUrl);
        Assert.False(loaded.LaunchAtStartup);
        Assert.Equal(30, loaded.SyncIntervalSeconds);
        Assert.False(loaded.ShowNotifications);
        Assert.False(loaded.AutoUpdate);
    }

    [Fact]
    public void PartialJsonKeepsOtherDefaults()
    {
        File.WriteAllText(FilePath("settings.json"), """{"showNotifications":false}""");

        var settings = DriveSettings.Load(FilePath("settings.json"));

        Assert.Equal("", settings.ServerUrl);
        Assert.True(settings.LaunchAtStartup);
        Assert.Equal(DriveSettings.DefaultIntervalSeconds, settings.SyncIntervalSeconds);
        Assert.False(settings.ShowNotifications);
        Assert.True(settings.AutoUpdate);
    }

    [Fact]
    public void InvalidJsonUsesDefaults()
    {
        File.WriteAllText(FilePath("settings.json"), "{");

        var settings = DriveSettings.Load(FilePath("settings.json"));

        Assert.Equal(DriveSettings.DefaultIntervalSeconds, settings.SyncIntervalSeconds);
        Assert.True(settings.LaunchAtStartup);
    }

    [Fact]
    public void ShortIntervalIsRaisedToMinimum()
    {
        var settings = new DriveSettings { SyncIntervalSeconds = 2 };
        settings.Save(FilePath("settings.json"));

        var loaded = DriveSettings.Load(FilePath("settings.json"));

        Assert.Equal(DriveSettings.MinimumIntervalSeconds, loaded.SyncIntervalSeconds);
    }

    [Fact]
    public void EmptyServerUrlUsesDefault()
    {
        var settings = new DriveSettings();

        Assert.True(settings.TryResolveApiBase(null, out var uri));
        Assert.Equal(KocClient.DefaultBaseUrl, uri.AbsoluteUri.TrimEnd('/'));
    }

    [Fact]
    public void EnvironmentUrlWins()
    {
        var settings = new DriveSettings { ServerUrl = "https://saved.example.com" };

        Assert.True(settings.TryResolveApiBase("https://env.example.com", out var uri));
        Assert.Equal("https://env.example.com/", uri.AbsoluteUri);
    }

    [Fact]
    public void RejectsNonHttpUrl()
    {
        var settings = new DriveSettings { ServerUrl = "ftp://files.example.com" };

        Assert.False(settings.TryResolveApiBase(null, out var uri));
        Assert.Equal(KocClient.DefaultBaseUrl, uri.AbsoluteUri.TrimEnd('/'));
        Assert.False(DriveSettings.IsAcceptableServerUrl("ftp://files.example.com"));
        Assert.False(DriveSettings.IsAcceptableServerUrl("http://files.example.com"));
        Assert.False(DriveSettings.IsAcceptableServerUrl("https://user:secret@erp.example.com"));
        Assert.True(DriveSettings.IsAcceptableServerUrl(""));
        Assert.True(DriveSettings.IsAcceptableServerUrl("https://erp.example.com"));
        Assert.True(DriveSettings.IsAcceptableServerUrl("http://127.0.0.1:8000"));
    }

    [Fact]
    public void RedactsSecrets()
    {
        Assert.Equal("요청이 실패했습니다.", SecretText.Redact("Bearer eyJabc.def"));
        Assert.Equal("이메일 또는 비밀번호가 올바르지 않습니다.", SecretText.Redact("이메일 또는 비밀번호가 올바르지 않습니다."));
    }

    [Fact]
    public void SameBaseIgnoresTrailingSlash()
    {
        Assert.True(DriveSettings.SameApiBase(new Uri("https://erp.example.com"), new Uri("https://erp.example.com/")));
        Assert.False(DriveSettings.SameApiBase(new Uri("https://erp.example.com"), new Uri("https://other.example.com")));
    }

    private string FilePath(string name) => Path.Combine(_directory, name);
}
