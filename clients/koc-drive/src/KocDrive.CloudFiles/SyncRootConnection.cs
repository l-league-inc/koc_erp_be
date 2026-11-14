using System.Runtime.InteropServices;
using KocDrive.Core.Sync;
using Windows.Win32;
using Windows.Win32.Foundation;
using Windows.Win32.Storage.CloudFilters;
using Windows.Win32.Storage.FileSystem;

namespace KocDrive.CloudFiles;

public sealed class SyncRootConnection : IDisposable
{
    private readonly SyncEngine _engine;
    private readonly string _root;
    private readonly Action<string> _report;
    private CF_CALLBACK_REGISTRATION[]? _callbacks;
    private GCHandle _self;
    private CF_CONNECTION_KEY _connection;
    private bool _connected;

    public SyncRootConnection(SyncEngine engine, string root, Action<string> report)
    {
        _engine = engine;
        _root = root;
        _report = report;
    }

    public unsafe void Connect()
    {
        Directory.CreateDirectory(_root);
        if (_connected)
        {
            return;
        }

        _self = GCHandle.Alloc(this);
        _callbacks =
        [
            new CF_CALLBACK_REGISTRATION
            {
                Type = CF_CALLBACK_TYPE.CF_CALLBACK_TYPE_FETCH_DATA,
                Callback = FetchData,
            },
            new CF_CALLBACK_REGISTRATION
            {
                Type = CF_CALLBACK_TYPE.CF_CALLBACK_TYPE_NOTIFY_FILE_CLOSE_COMPLETION,
                Callback = CloseCompleted,
            },
            new CF_CALLBACK_REGISTRATION
            {
                Type = CF_CALLBACK_TYPE.CF_CALLBACK_TYPE_NOTIFY_DELETE,
                Callback = DeleteRequested,
            },
            new CF_CALLBACK_REGISTRATION
            {
                Type = CF_CALLBACK_TYPE.CF_CALLBACK_TYPE_NOTIFY_RENAME,
                Callback = RenameRequested,
            },
            new CF_CALLBACK_REGISTRATION
            {
                Type = CF_CALLBACK_TYPE.CF_CALLBACK_TYPE_NONE,
            },
        ];
        CF_CONNECTION_KEY connection;
        var result = PInvoke.CfConnectSyncRoot(
            _root,
            _callbacks,
            (void*)GCHandle.ToIntPtr(_self),
            CF_CONNECT_FLAGS.CF_CONNECT_FLAG_REQUIRE_FULL_FILE_PATH,
            &connection);
        result.ThrowOnFailure();
        _connection = connection;
        _connected = true;
    }

    public void Upsert(string entity, long serverId, string relativePath, long size)
    {
        var relative = relativePath.Replace('/', Path.DirectorySeparatorChar).Trim(Path.DirectorySeparatorChar);
        var name = Path.GetFileName(relative);
        var parent = Path.GetDirectoryName(relative);
        var baseDirectory = string.IsNullOrEmpty(parent) ? _root : Path.Combine(_root, parent);
        if (!Directory.Exists(baseDirectory))
        {
            Directory.CreateDirectory(baseDirectory);
        }

        var identity = PlaceholderIdentity.Create(entity, serverId);
        var isFolder = entity == "folder";
        unsafe
        {
            fixed (byte* identityPointer = identity)
            fixed (char* namePointer = name)
            {
                var entry = new CF_PLACEHOLDER_CREATE_INFO
                {
                    RelativeFileName = namePointer,
                    FileIdentity = identityPointer,
                    FileIdentityLength = (uint)identity.Length,
                    Flags = CF_PLACEHOLDER_CREATE_FLAGS.CF_PLACEHOLDER_CREATE_FLAG_MARK_IN_SYNC
                        | (isFolder
                            ? CF_PLACEHOLDER_CREATE_FLAGS.CF_PLACEHOLDER_CREATE_FLAG_DISABLE_ON_DEMAND_POPULATION
                            : 0),
                    FsMetadata = new CF_FS_METADATA
                    {
                        FileSize = isFolder ? 0 : size,
                        BasicInfo = new FILE_BASIC_INFO
                        {
                            FileAttributes = isFolder ? 0x10u : 0x80u,
                        },
                    },
                };
                var span = MemoryMarshal.CreateReadOnlySpan(ref entry, 1);
                uint processed;
                var created = PInvoke.CfCreatePlaceholders(
                    baseDirectory,
                    span,
                    CF_CREATE_FLAGS.CF_CREATE_FLAG_NONE,
                    &processed);
                if (created.Succeeded)
                {
                    return;
                }
            }
        }

        var fullPath = Path.Combine(_root, relative);
        if (isFolder || !File.Exists(fullPath))
        {
            return;
        }

        UpdateExisting(fullPath, identity, size);
    }

    public void Dispose()
    {
        if (_connected)
        {
            PInvoke.CfDisconnectSyncRoot(_connection);
            _connected = false;
        }

        if (_self.IsAllocated)
        {
            _self.Free();
        }
    }

    private static unsafe void FetchData(CF_CALLBACK_INFO* info, CF_CALLBACK_PARAMETERS* parameters)
    {
        var self = From(info);
        if (!TryIdentity(info, out var entity, out var serverId) || entity != "file")
        {
            self.Transfer(info, null, 0, 0, failed: true);
            return;
        }

        try
        {
            var bytes = self._engine.HydrateAsync(serverId, CancellationToken.None).GetAwaiter().GetResult();
            var offset = parameters->Anonymous.FetchData.RequiredFileOffset;
            var requested = parameters->Anonymous.FetchData.RequiredLength;
            if (offset < 0 || offset > bytes.Length)
            {
                self.Transfer(info, null, offset, 0, failed: true);
                return;
            }

            var length = (int)Math.Min(requested, bytes.Length - offset);
            fixed (byte* buffer = bytes)
            {
                self.Transfer(info, buffer + offset, offset, length, failed: false);
            }
        }
        catch (Exception exception)
        {
            self._report(exception.Message);
            self.Transfer(info, null, 0, 0, failed: true);
        }
    }

    private static unsafe void CloseCompleted(CF_CALLBACK_INFO* info, CF_CALLBACK_PARAMETERS* parameters)
    {
        if ((parameters->Anonymous.CloseCompletion.Flags & CF_CALLBACK_CLOSE_COMPLETION_FLAGS.CF_CALLBACK_CLOSE_COMPLETION_FLAG_DELETED) != 0)
        {
            return;
        }

        var self = From(info);
        if (!TryIdentity(info, out var entity, out _) || entity != "file")
        {
            return;
        }

        var relative = self.RelativePath(info);
        if (relative is not null)
        {
            self._engine.QueueLocalWrite(relative);
        }
    }

    private static unsafe void DeleteRequested(CF_CALLBACK_INFO* info, CF_CALLBACK_PARAMETERS* parameters)
    {
        _ = parameters->Anonymous.Delete.Flags;
        var self = From(info);
        var relative = self.RelativePath(info);
        if (relative is not null)
        {
            self._engine.QueueLocalDelete(relative);
        }

        self.Ack(info, CF_OPERATION_TYPE.CF_OPERATION_TYPE_ACK_DELETE);
    }

    private static unsafe void RenameRequested(CF_CALLBACK_INFO* info, CF_CALLBACK_PARAMETERS* parameters)
    {
        var self = From(info);
        var source = self.RelativePath(info);
        var target = self.ToRelative(parameters->Anonymous.Rename.TargetPath.ToString());
        if (source is not null && target is not null)
        {
            self._engine.QueueLocalRename(source, target);
        }

        self.Ack(info, CF_OPERATION_TYPE.CF_OPERATION_TYPE_ACK_RENAME);
    }

    private unsafe void Transfer(CF_CALLBACK_INFO* info, byte* buffer, long offset, int length, bool failed)
    {
        var operation = Operation(info, CF_OPERATION_TYPE.CF_OPERATION_TYPE_TRANSFER_DATA);
        var opParams = new CF_OPERATION_PARAMETERS
        {
            ParamSize = (uint)Marshal.SizeOf<CF_OPERATION_PARAMETERS>(),
        };
        opParams.Anonymous.TransferData.Buffer = buffer;
        opParams.Anonymous.TransferData.Offset = offset;
        opParams.Anonymous.TransferData.Length = length;
        opParams.Anonymous.TransferData.CompletionStatus = new NTSTATUS(failed ? unchecked((int)0xC0000001) : 0);
        PInvoke.CfExecute(in operation, ref opParams).ThrowOnFailure();
    }

    private unsafe void Ack(CF_CALLBACK_INFO* info, CF_OPERATION_TYPE type)
    {
        var operation = Operation(info, type);
        var opParams = new CF_OPERATION_PARAMETERS
        {
            ParamSize = (uint)Marshal.SizeOf<CF_OPERATION_PARAMETERS>(),
        };
        if (type == CF_OPERATION_TYPE.CF_OPERATION_TYPE_ACK_DELETE)
        {
            opParams.Anonymous.AckDelete.CompletionStatus = new NTSTATUS(0);
        }
        else
        {
            opParams.Anonymous.AckRename.CompletionStatus = new NTSTATUS(0);
        }

        PInvoke.CfExecute(in operation, ref opParams).ThrowOnFailure();
    }

    private static unsafe CF_OPERATION_INFO Operation(CF_CALLBACK_INFO* info, CF_OPERATION_TYPE type) => new()
    {
        StructSize = (uint)Marshal.SizeOf<CF_OPERATION_INFO>(),
        Type = type,
        ConnectionKey = info->ConnectionKey,
        TransferKey = info->TransferKey,
        CorrelationVector = info->CorrelationVector,
        RequestKey = info->RequestKey,
    };

    private static unsafe SyncRootConnection From(CF_CALLBACK_INFO* info) =>
        (SyncRootConnection)GCHandle.FromIntPtr((IntPtr)info->CallbackContext).Target!;

    private static unsafe bool TryIdentity(CF_CALLBACK_INFO* info, out string entity, out long serverId)
    {
        var bytes = new ReadOnlySpan<byte>(info->FileIdentity, (int)info->FileIdentityLength);
        return PlaceholderIdentity.TryRead(bytes, out entity, out serverId);
    }

    private unsafe string? RelativePath(CF_CALLBACK_INFO* info) => ToRelative(FullPath(info));

    private static unsafe string FullPath(CF_CALLBACK_INFO* info)
    {
        var dos = info->VolumeDosName.ToString() ?? "";
        var normalized = info->NormalizedPath.ToString() ?? "";
        return dos + normalized;
    }

    private string? ToRelative(string? fullPath)
    {
        if (string.IsNullOrWhiteSpace(fullPath))
        {
            return null;
        }

        var root = Path.GetFullPath(_root);
        var full = Path.GetFullPath(fullPath);
        var prefix = root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        return full[prefix.Length..].Replace(Path.DirectorySeparatorChar, '/');
    }

    private unsafe void UpdateExisting(string fullPath, byte[] identity, long size)
    {
        using var stream = new FileStream(fullPath, FileMode.Open, FileAccess.Write, FileShare.ReadWrite | FileShare.Delete);
        var metadata = new CF_FS_METADATA
        {
            FileSize = size,
            BasicInfo = new FILE_BASIC_INFO
            {
                FileAttributes = 0x80u,
            },
        };
        fixed (byte* identityPointer = identity)
        {
            var updated = PInvoke.CfUpdatePlaceholder(
                stream.SafeFileHandle,
                metadata,
                identityPointer,
                (uint)identity.Length,
                ReadOnlySpan<CF_FILE_RANGE>.Empty,
                CF_UPDATE_FLAGS.CF_UPDATE_FLAG_MARK_IN_SYNC,
                null,
                null);
            if (updated.Succeeded)
            {
                return;
            }

            long usn;
            PInvoke.CfConvertToPlaceholder(
                stream.SafeFileHandle,
                identityPointer,
                (uint)identity.Length,
                CF_CONVERT_FLAGS.CF_CONVERT_FLAG_MARK_IN_SYNC,
                &usn,
                null);
        }
    }
}
