namespace KocDrive.Core.Api;

public sealed class KocApiException : Exception
{
    public KocApiException(int statusCode, string message) : base(message)
    {
        StatusCode = statusCode;
    }

    public int StatusCode { get; }
}
