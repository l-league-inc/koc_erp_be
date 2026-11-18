using System.Net.Http;
using System.Security.Cryptography;
using System.Text.Json;

namespace KocDrive.Core.Update;

public sealed record AppRelease(string Version, Uri Url, string Sha256, string Notes);

public static class ReleasePlan
{
    public static bool ShouldInstall(string currentVersion, string? installedSha, string? runningSha, AppRelease release)
    {
        if (SameFile(installedSha, release.Sha256) || SameFile(runningSha, release.Sha256))
        {
            return false;
        }

        return ReleaseVersion.IsNewer(currentVersion, release.Version);
    }

    private static bool SameFile(string? actual, string expected) =>
        !string.IsNullOrWhiteSpace(actual)
        && string.Equals(actual.Trim(), expected.Trim(), StringComparison.OrdinalIgnoreCase);
}

public static class ReleaseVersion
{
    public static bool IsValid(string value) => TryParts(value, out _);

    public static bool IsNewer(string current, string candidate)
    {
        if (!TryParts(candidate, out var next) || !TryParts(current, out var now))
        {
            return false;
        }

        var length = Math.Max(now.Length, next.Length);
        for (var index = 0; index < length; index++)
        {
            var left = index < now.Length ? now[index] : 0;
            var right = index < next.Length ? next[index] : 0;
            if (right != left)
            {
                return right > left;
            }
        }

        return false;
    }

    private static bool TryParts(string value, out int[] parts)
    {
        parts = Array.Empty<int>();
        var text = value.Trim();
        if (text.StartsWith('v') || text.StartsWith('V'))
        {
            text = text[1..];
        }

        var tokens = text.Split('.');
        if (tokens.Length is < 2 or > 4)
        {
            return false;
        }

        var parsed = new int[tokens.Length];
        for (var index = 0; index < tokens.Length; index++)
        {
            if (tokens[index].Length is 0 or > 4 || !int.TryParse(tokens[index], out var number) || number < 0)
            {
                return false;
            }

            parsed[index] = number;
        }

        parts = parsed;
        return true;
    }
}

public static class AppReleaseManifest
{
    public static AppRelease? Parse(string json)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidOperationException("업데이트를 확인하지 못했습니다.");
        }

        var version = Read(root, "version");
        if (string.IsNullOrWhiteSpace(version))
        {
            return null;
        }

        if (!ReleaseVersion.IsValid(version))
        {
            throw new InvalidOperationException("업데이트를 확인하지 못했습니다.");
        }

        var urlText = Read(root, "url");
        if (!ApiEndpoint.TryParseBase(urlText, out var url))
        {
            throw new InvalidOperationException("업데이트 주소가 올바르지 않습니다.");
        }

        var sha256 = Read(root, "sha256").Trim().ToLowerInvariant();
        if (sha256.Length != 64 || sha256.Any(item => !"0123456789abcdef".Contains(item)))
        {
            throw new InvalidOperationException("업데이트를 확인하지 못했습니다.");
        }

        return new AppRelease(version.Trim().TrimStart('v', 'V'), url, sha256, Read(root, "notes").Trim());
    }

    private static string Read(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String)
        {
            return "";
        }

        return value.GetString() ?? "";
    }
}

public static class ReleaseFiles
{
    public const long MaxBytes = 200L * 1024L * 1024L;

    public static async Task SaveVerifiedAsync(
        HttpClient http,
        Uri url,
        string sha256,
        string destination,
        CancellationToken cancellationToken)
    {
        if (!ApiEndpoint.TryParseBase(url.AbsoluteUri, out var parsed))
        {
            throw new InvalidOperationException("업데이트 주소가 올바르지 않습니다.");
        }

        var directory = Path.GetDirectoryName(destination);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var partial = destination + ".part";
        try
        {
            using var response = await http.GetAsync(parsed, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                throw new InvalidOperationException("업데이트를 받지 못했습니다.");
            }

            await using var input = await response.Content.ReadAsStreamAsync(cancellationToken);
            await using (var output = new FileStream(partial, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                using var hasher = SHA256.Create();
                var buffer = new byte[81920];
                long total = 0;
                while (true)
                {
                    var read = await input.ReadAsync(buffer, cancellationToken);
                    if (read == 0)
                    {
                        break;
                    }

                    total += read;
                    if (total > MaxBytes)
                    {
                        throw new InvalidOperationException("업데이트 파일이 너무 큽니다.");
                    }

                    hasher.TransformBlock(buffer, 0, read, null, 0);
                    await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
                }

                hasher.TransformFinalBlock(Array.Empty<byte>(), 0, 0);
                var actual = Convert.ToHexString(hasher.Hash!).ToLowerInvariant();
                if (!string.Equals(actual, sha256.Trim(), StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidOperationException("업데이트 파일이 손상되었습니다.");
                }
            }

            File.Move(partial, destination, overwrite: true);
        }
        catch
        {
            if (File.Exists(partial))
            {
                File.Delete(partial);
            }

            throw;
        }
    }
}
