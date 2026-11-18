namespace KocDrive.App;

internal static class AppVersion
{
    public static string Current
    {
        get
        {
            var version = typeof(AppVersion).Assembly.GetName().Version;
            if (version is null)
            {
                return "0.0.0";
            }

            if (version.Build < 0)
            {
                return $"{version.Major}.{version.Minor}";
            }

            return $"{version.Major}.{version.Minor}.{version.Build}";
        }
    }
}
