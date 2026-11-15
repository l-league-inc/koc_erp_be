using Windows.Security.Cryptography;
using Windows.Storage;
using Windows.Storage.Provider;

namespace KocDrive.App;

internal static class ShellSyncRoot
{
    public const string Id = "KocErp!KocDrive";

    public static async Task RegisterAsync(string path)
    {
        Directory.CreateDirectory(path);
        var info = new StorageProviderSyncRootInfo
        {
            Id = Id,
            Path = await StorageFolder.GetFolderFromPathAsync(path),
            DisplayNameResource = "KOC ERP",
            IconResource = ExeIconResource(),
            HydrationPolicy = StorageProviderHydrationPolicy.Full,
            PopulationPolicy = StorageProviderPopulationPolicy.AlwaysFull,
            InSyncPolicy = StorageProviderInSyncPolicy.FileCreationTime | StorageProviderInSyncPolicy.DirectoryCreationTime,
            HardlinkPolicy = StorageProviderHardlinkPolicy.None,
            Version = "1.0.0",
            ShowSiblingsAsGroup = false,
            Context = CryptographicBuffer.ConvertStringToBinary(Id, BinaryStringEncoding.Utf8),
        };
        StorageProviderSyncRootManager.Register(info);
    }

    private static string ExeIconResource()
    {
        var path = Environment.ProcessPath;
        if (string.IsNullOrEmpty(path))
        {
            return @"%SystemRoot%\system32\imageres.dll,-3";
        }

        return path + ",0";
    }

    public static void Unregister()
    {
        try
        {
            StorageProviderSyncRootManager.Unregister(Id);
        }
        catch (Exception)
        {
        }
    }
}
