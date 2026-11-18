using System.Text.Json;

namespace KocDrive.Core;

public sealed class DriveSettings
{
    public const int DefaultIntervalSeconds = 15;
    public const int MinimumIntervalSeconds = 5;

    public string ServerUrl { get; set; } = "";

    public bool LaunchAtStartup { get; set; } = true;

    public int SyncIntervalSeconds { get; set; } = DefaultIntervalSeconds;

    public bool ShowNotifications { get; set; } = true;

    public bool AutoUpdate { get; set; } = true;

    public int IntervalMilliseconds => SyncIntervalSeconds * 1000;

    public static DriveSettings Load(string path)
    {
        if (!File.Exists(path))
        {
            return new DriveSettings();
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return new DriveSettings();
            }

            var settings = new DriveSettings();
            if (root.TryGetProperty("serverUrl", out var serverUrl) && serverUrl.ValueKind == JsonValueKind.String)
            {
                settings.ServerUrl = serverUrl.GetString() ?? "";
            }

            if (root.TryGetProperty("launchAtStartup", out var launch) && launch.ValueKind is JsonValueKind.True or JsonValueKind.False)
            {
                settings.LaunchAtStartup = launch.GetBoolean();
            }

            if (root.TryGetProperty("syncIntervalSeconds", out var interval) && interval.TryGetInt32(out var seconds))
            {
                settings.SyncIntervalSeconds = seconds;
            }

            if (root.TryGetProperty("showNotifications", out var notifications) && notifications.ValueKind is JsonValueKind.True or JsonValueKind.False)
            {
                settings.ShowNotifications = notifications.GetBoolean();
            }

            if (root.TryGetProperty("autoUpdate", out var autoUpdate) && autoUpdate.ValueKind is JsonValueKind.True or JsonValueKind.False)
            {
                settings.AutoUpdate = autoUpdate.GetBoolean();
            }

            settings.Normalize();
            return settings;
        }
        catch (JsonException)
        {
            return new DriveSettings();
        }
    }

    public void Save(string path)
    {
        Normalize();
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var payload = new
        {
            serverUrl = ServerUrl,
            launchAtStartup = LaunchAtStartup,
            syncIntervalSeconds = SyncIntervalSeconds,
            showNotifications = ShowNotifications,
            autoUpdate = AutoUpdate,
        };
        File.WriteAllText(path, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    }

    public void Normalize()
    {
        ServerUrl = ServerUrl.Trim();
        if (SyncIntervalSeconds < MinimumIntervalSeconds)
        {
            SyncIntervalSeconds = MinimumIntervalSeconds;
        }
    }

    public bool TryResolveApiBase(string? environmentOverride, out Uri baseUri)
    {
        var raw = string.IsNullOrWhiteSpace(environmentOverride) ? ServerUrl : environmentOverride;
        if (string.IsNullOrWhiteSpace(raw))
        {
            baseUri = new Uri(Api.KocClient.DefaultBaseUrl);
            return true;
        }

        if (Api.ApiEndpoint.TryParseBase(raw, out var uri))
        {
            baseUri = uri;
            return true;
        }

        baseUri = new Uri(Api.KocClient.DefaultBaseUrl);
        return false;
    }

    public static bool IsAcceptableServerUrl(string value) =>
        string.IsNullOrWhiteSpace(value) || Api.ApiEndpoint.TryParseBase(value, out _);

    public static bool SameApiBase(Uri left, Uri right) =>
        string.Equals(left.AbsoluteUri.TrimEnd('/'), right.AbsoluteUri.TrimEnd('/'), StringComparison.OrdinalIgnoreCase);

}
