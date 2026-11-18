using System.Diagnostics;

namespace KocDrive.App;

internal static class AppUpdate
{
    public static bool TryApplyLaunch(string[] args)
    {
        if (args.Length < 3 || !string.Equals(args[0], "--apply-update", StringComparison.Ordinal))
        {
            return false;
        }

        try
        {
            var target = Path.GetFullPath(args[1]);
            if (!string.Equals(target, Path.GetFullPath(AppInstall.ExePath), StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (!int.TryParse(args[2], out var pid))
            {
                return true;
            }

            try
            {
                using var process = Process.GetProcessById(pid);
                process.WaitForExit(20_000);
            }
            catch (ArgumentException)
            {
            }

            var source = Environment.ProcessPath;
            if (string.IsNullOrEmpty(source))
            {
                return true;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            for (var attempt = 0; attempt < 30; attempt++)
            {
                try
                {
                    File.Copy(source, target, overwrite: true);
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = target,
                        UseShellExecute = true,
                        WorkingDirectory = Path.GetDirectoryName(target)!,
                    });
                    return true;
                }
                catch (IOException) when (attempt < 29)
                {
                    Thread.Sleep(500);
                }
            }
        }
        catch (Exception exception)
        {
            AppInstall.WriteStartupLog(exception);
        }

        return true;
    }

    public static bool HandOff(string downloadedPath, string targetPath)
    {
        try
        {
            var started = Process.Start(new ProcessStartInfo
            {
                FileName = downloadedPath,
                Arguments = "--apply-update \"" + targetPath + "\" " + Environment.ProcessId,
                UseShellExecute = false,
                WorkingDirectory = Path.GetDirectoryName(downloadedPath) ?? "",
            });
            if (started is null)
            {
                return false;
            }

            Application.Exit();
            return true;
        }
        catch (Exception exception)
        {
            AppInstall.WriteStartupLog(exception);
            return false;
        }
    }
}
