namespace KocDrive.Core.Sync;

public static class TransferTiming
{
    // document/storage.py의 GUIDE_BYTES_PER_SECOND와 같습니다. 10Mbps입니다.
    public const long GuideBytesPerSecond = 1_250_000;

    public static int EstimatedSeconds(long size)
    {
        if (size < 1)
        {
            return 1;
        }

        return (int)Math.Max(1, (size + GuideBytesPerSecond - 1) / GuideBytesPerSecond);
    }

    public static string? UploadMessage(string name, long size) =>
        Message(name, size, "올리고");

    public static string? DownloadMessage(string name, long size) =>
        Message(name, size, "받고");

    public static string Duration(int seconds)
    {
        if (seconds < 60)
        {
            return $"약 {seconds}초";
        }

        var minutes = (seconds + 30) / 60;
        if (minutes < 60)
        {
            return $"약 {minutes}분";
        }

        var hours = minutes / 60;
        var remain = minutes % 60;
        return remain == 0 ? $"약 {hours}시간" : $"약 {hours}시간 {remain}분";
    }

    private static string? Message(string name, long size, string verb)
    {
        var seconds = EstimatedSeconds(size);
        if (seconds < 10)
        {
            return null;
        }

        return $"{name} 파일을 {verb} 있습니다. {Duration(seconds)} 걸릴 수 있습니다.";
    }
}
