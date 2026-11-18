using System.Security.Cryptography;

namespace KocDrive.App;

internal static class AppInstall
{
    public const string ExeName = "KOC ERP.exe";

    public static string DirectoryPath =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "KOC ERP");

    public static string ExePath => Path.Combine(DirectoryPath, ExeName);

    public static string IconPath => Path.Combine(DirectoryPath, "KOC ERP.ico");

    public static string InstalledShaPath => Path.Combine(DirectoryPath, "installed.sha");

    public static bool IsInstalled(string path) =>
        string.Equals(Path.GetFullPath(path), Path.GetFullPath(ExePath), StringComparison.OrdinalIgnoreCase);

    public static string EnsureIconFile()
    {
        Directory.CreateDirectory(DirectoryPath);
        var bytes = IconBytes();
        if (bytes is null || bytes.Length == 0)
        {
            return IconPath;
        }

        var hash = Convert.ToHexString(SHA256.HashData(bytes))[..8].ToLowerInvariant();
        var path = Path.Combine(DirectoryPath, $"KOC ERP.{hash}.ico");
        if (!File.Exists(path))
        {
            File.WriteAllBytes(path, bytes);
        }

        foreach (var old in Directory.EnumerateFiles(DirectoryPath, "KOC ERP*.ico"))
        {
            if (string.Equals(Path.GetFullPath(old), Path.GetFullPath(path), StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            try
            {
                File.Delete(old);
            }
            catch (Exception)
            {
            }
        }

        return path;
    }

    private static byte[]? IconBytes()
    {
        var assembly = typeof(AppInstall).Assembly;
        var resource = assembly.GetManifestResourceNames()
            .FirstOrDefault(name => name.EndsWith("koc-drive.ico", StringComparison.OrdinalIgnoreCase));
        if (resource is null)
        {
            return null;
        }

        using var stream = assembly.GetManifestResourceStream(resource);
        if (stream is null)
        {
            return null;
        }

        using var copy = new MemoryStream();
        stream.CopyTo(copy);
        return copy.ToArray();
    }

    public static string? ReadInstalledSha()
    {
        try
        {
            if (!File.Exists(InstalledShaPath))
            {
                return null;
            }

            var text = File.ReadAllText(InstalledShaPath).Trim().ToLowerInvariant();
            return text.Length == 64 ? text : null;
        }
        catch (Exception)
        {
            return null;
        }
    }

    public static void RememberInstalledSha(string sha256)
    {
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            File.WriteAllText(InstalledShaPath, sha256.Trim().ToLowerInvariant());
        }
        catch (Exception)
        {
        }
    }

    public static void InstallCopy()
    {
        var current = Environment.ProcessPath;
        if (string.IsNullOrEmpty(current)
            || IsInstalled(current)
            || !string.Equals(Path.GetFileName(current), ExeName, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        try
        {
            Directory.CreateDirectory(DirectoryPath);
            File.Copy(current, ExePath, overwrite: true);
        }
        catch (Exception exception)
        {
            WriteStartupLog(exception);
        }
    }

    public static void WriteStartupLog(Exception exception)
    {
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            var root = exception.GetBaseException();
            var message = KocDrive.Core.Api.SecretText.Redact(root.Message);
            File.WriteAllText(
                Path.Combine(DirectoryPath, "startup.log"),
                root.GetType().FullName + Environment.NewLine + message + Environment.NewLine + root.StackTrace);
        }
        catch (Exception)
        {
        }
    }
}
