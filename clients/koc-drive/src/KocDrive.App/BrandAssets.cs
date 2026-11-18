namespace KocDrive.App;

internal static class BrandAssets
{
    private static Image? _logo;

    public static Image Logo() => _logo ??= LoadLogo();

    private static Image LoadLogo()
    {
        var assembly = typeof(BrandAssets).Assembly;
        var resource = assembly.GetManifestResourceNames()
            .FirstOrDefault(name => name.EndsWith("koc-logo.png", StringComparison.OrdinalIgnoreCase));
        if (resource is null)
        {
            return new Bitmap(1, 1);
        }

        using var stream = assembly.GetManifestResourceStream(resource);
        if (stream is null)
        {
            return new Bitmap(1, 1);
        }

        using var copy = new MemoryStream();
        stream.CopyTo(copy);
        copy.Position = 0;
        using var image = Image.FromStream(copy);
        return new Bitmap(image);
    }
}
