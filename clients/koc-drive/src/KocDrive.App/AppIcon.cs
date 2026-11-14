namespace KocDrive.App;

internal static class AppIcon
{
    public static Icon Load()
    {
        try
        {
            var assembly = typeof(AppIcon).Assembly;
            var resource = assembly.GetManifestResourceNames()
                .FirstOrDefault(name => name.EndsWith("koc-drive.ico", StringComparison.OrdinalIgnoreCase));
            if (resource is not null)
            {
                using var stream = assembly.GetManifestResourceStream(resource);
                if (stream is not null)
                {
                    using var file = new Icon(stream);
                    return new Icon(file, SystemInformation.SmallIconSize);
                }
            }
        }
        catch (Exception)
        {
        }

        try
        {
            var extracted = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            if (extracted is not null)
            {
                return new Icon(extracted, SystemInformation.SmallIconSize);
            }
        }
        catch (Exception)
        {
        }

        return SystemIcons.Application;
    }
}
