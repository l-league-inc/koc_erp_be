namespace KocDrive.App;

internal static class AppIcon
{
    public static Icon Load()
    {
        try
        {
            var icon = OpenEmbedded();
            if (icon is not null)
            {
                return icon;
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

    private static Icon? OpenEmbedded()
    {
        var assembly = typeof(AppIcon).Assembly;
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
        copy.Position = 0;
        return new Icon(copy);
    }
}
