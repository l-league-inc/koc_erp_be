using System.Security.Cryptography;

namespace KocDrive.Core;

public static class Hashing
{
    public static string Sha256(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
}

public static class ContentTypes
{
    public static string ForFileName(string name)
    {
        return Path.GetExtension(name).ToLowerInvariant() switch
        {
            ".txt" or ".md" or ".csv" => "text/plain",
            ".pdf" => "application/pdf",
            ".png" => "image/png",
            ".jpg" or ".jpeg" => "image/jpeg",
            ".json" => "application/json",
            _ => "application/octet-stream",
        };
    }
}

public static class RelativePaths
{
    public static string Parent(string relativePath)
    {
        var normalized = relativePath.Replace('\\', '/').Trim('/');
        var slash = normalized.LastIndexOf('/');
        return slash < 0 ? "" : normalized[..slash];
    }

    public static string Name(string relativePath)
    {
        var normalized = relativePath.Replace('\\', '/').Trim('/');
        var slash = normalized.LastIndexOf('/');
        return slash < 0 ? normalized : normalized[(slash + 1)..];
    }

    public static string Combine(string root, string relativePath)
    {
        var normalized = relativePath.Replace('\\', '/').Trim('/');
        if (normalized.Split('/').Contains("..") || Path.IsPathRooted(relativePath))
        {
            throw new InvalidOperationException("경로가 올바르지 않습니다.");
        }

        var full = Path.GetFullPath(Path.Combine(root, normalized.Replace('/', Path.DirectorySeparatorChar)));
        var rootFull = Path.GetFullPath(root);
        var prefix = rootFull.EndsWith(Path.DirectorySeparatorChar) ? rootFull : rootFull + Path.DirectorySeparatorChar;
        if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) && full != rootFull)
        {
            throw new InvalidOperationException("경로가 올바르지 않습니다.");
        }

        return full;
    }
}
