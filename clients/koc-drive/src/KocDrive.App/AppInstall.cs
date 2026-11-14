namespace KocDrive.App;

internal static class AppInstall
{
    public const string ExeName = "KOC ERP.exe";

    public static string DirectoryPath =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "KOC ERP");

    public static string ExePath => Path.Combine(DirectoryPath, ExeName);

    public static bool IsInstalled(string path) =>
        string.Equals(Path.GetFullPath(path), Path.GetFullPath(ExePath), StringComparison.OrdinalIgnoreCase);

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
