using System.Runtime.InteropServices;

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
        var shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (shellType is null)
        {
            return;
        }

        var explorer = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "explorer.exe");
        dynamic shell = Activator.CreateInstance(shellType)!;
        dynamic shortcut = shell.CreateShortcut(linkPath);
        // 폴더를 바로 가리키면 Windows가 아이콘을 폴더 아이콘으로 바꿉니다.
        shortcut.TargetPath = explorer;
        shortcut.Arguments = $"\"{folderPath}\"";
        shortcut.WorkingDirectory = folderPath;
        shortcut.IconLocation = IconLocation();
        shortcut.Description = "KOC ERP";
        shortcut.Save();
        try
        {
            SHChangeNotify(0x00002000, 0x0005 | 0x1000, linkPath, IntPtr.Zero);
        }
        catch (Exception)
        {
        }
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern void SHChangeNotify(uint eventId, uint flags, string item1, IntPtr item2);

    private static string IconLocation()
    {
        try
        {
            var iconPath = AppInstall.EnsureIconFile();
            if (File.Exists(iconPath))
            {
                return iconPath + ",0";
            }
        }
        catch (Exception)
        {
        }

        return Application.ExecutablePath + ",0";
    }
}
