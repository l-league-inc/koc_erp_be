namespace KocDrive.App;

internal static class DesktopShortcut
{
    public static void Ensure(string folderPath)
    {
        Directory.CreateDirectory(folderPath);
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (string.IsNullOrEmpty(desktop))
        {
            return;
        }

        var linkPath = Path.Combine(desktop, "KOC ERP.lnk");
        if (File.Exists(linkPath))
        {
            return;
        }

        var shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (shellType is null)
        {
            return;
        }

        dynamic shell = Activator.CreateInstance(shellType)!;
        dynamic shortcut = shell.CreateShortcut(linkPath);
        shortcut.TargetPath = folderPath;
        shortcut.WorkingDirectory = folderPath;
        shortcut.IconLocation = Application.ExecutablePath + ",0";
        shortcut.Description = "KOC ERP";
        shortcut.Save();
    }
}
