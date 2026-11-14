namespace KocDrive.Core.Api;

public static class ApiEndpoint
{
    public static bool TryParseBase(string? value, out Uri uri)
    {
        uri = null!;
        if (string.IsNullOrWhiteSpace(value)
            || !Uri.TryCreate(value.Trim(), UriKind.Absolute, out var parsed)
            || !string.IsNullOrEmpty(parsed.UserInfo))
        {
            return false;
        }

        if (parsed.Scheme == Uri.UriSchemeHttps || (parsed.Scheme == Uri.UriSchemeHttp && parsed.IsLoopback))
        {
            uri = parsed;
            return true;
        }

        return false;
    }
}

public static class SecretText
{
    public static bool LooksSensitive(string value) =>
        value.Contains("bearer ", StringComparison.OrdinalIgnoreCase)
        || value.Contains("eyJ", StringComparison.Ordinal)
        || value.Contains("password", StringComparison.OrdinalIgnoreCase);

    public static string Redact(string? value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "";
        }

        var text = value.Length > 300 ? value[..300] : value;
        if (!LooksSensitive(text))
        {
            return text;
        }

        return "요청이 실패했습니다.";
    }
}
