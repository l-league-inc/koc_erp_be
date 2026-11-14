using Microsoft.Win32;

namespace KocDrive.App;

internal static class StartupRegistration
{
    private const string ValueName = "KocDrive";

    public static void Apply(bool enabled, string executablePath)
    {
        using var key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
        if (key is null)
        {
            return;
        }

        if (enabled)
        {
            key.SetValue(ValueName, $"\"{executablePath}\"");
            return;
        }

        key.DeleteValue(ValueName, throwOnMissingValue: false);
    }
}
