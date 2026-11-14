using System.Buffers.Binary;

namespace KocDrive.CloudFiles;

public static class PlaceholderIdentity
{
    public static byte[] Create(string entity, long serverId)
    {
        var bytes = new byte[9];
        bytes[0] = entity == "folder" ? (byte)1 : (byte)2;
        BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(1), serverId);
        return bytes;
    }

    public static bool TryRead(ReadOnlySpan<byte> bytes, out string entity, out long serverId)
    {
        entity = "";
        serverId = 0;
        if (bytes.Length < 9)
        {
            return false;
        }

        entity = bytes[0] == 1 ? "folder" : "file";
        serverId = BinaryPrimitives.ReadInt64LittleEndian(bytes[1..]);
        return serverId > 0;
    }
}
