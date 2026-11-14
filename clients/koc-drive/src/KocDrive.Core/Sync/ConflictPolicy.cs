namespace KocDrive.Core.Sync;

public enum SyncAction
{
    InSync,
    ApplyServer,
    UploadLocal,
    ConflictCopy,
}

public static class ConflictPolicy
{
    public static SyncAction Decide(string baseHash, string localHash, string serverHash, bool dirty)
    {
        if (localHash == serverHash)
        {
            return SyncAction.InSync;
        }

        if (!dirty)
        {
            return SyncAction.ApplyServer;
        }

        if (baseHash == serverHash)
        {
            return SyncAction.UploadLocal;
        }

        return SyncAction.ConflictCopy;
    }
}

public static class ConflictNames
{
    public static string Copy(string fileName, ISet<string> taken)
    {
        var extension = "";
        var baseName = fileName;
        var dot = fileName.LastIndexOf('.');
        if (dot > 0)
        {
            baseName = fileName[..dot];
            extension = fileName[dot..];
        }

        var first = Fit($"{baseName} (충돌){extension}");
        if (taken.Add(first))
        {
            return first;
        }

        for (var number = 2; ; number++)
        {
            var candidate = Fit($"{baseName} (충돌 {number}){extension}");
            if (taken.Add(candidate))
            {
                return candidate;
            }
        }
    }

    private static string Fit(string name) => name.Length <= 255 ? name : name[..255];
}
