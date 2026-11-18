using System.Net;
using System.Security.Cryptography;
using System.Text;
using KocDrive.Core.Update;
using Xunit;

namespace KocDrive.Core.Tests;

public class AppReleaseTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), "koc-drive-release-" + Guid.NewGuid().ToString("N"));

    public AppReleaseTests() => Directory.CreateDirectory(_directory);

    public void Dispose() => Directory.Delete(_directory, recursive: true);

    [Theory]
    [InlineData("1.0.0", "1.0.1", true)]
    [InlineData("1.0.0", "1.0.0", false)]
    [InlineData("1.2.0", "1.1.9", false)]
    [InlineData("1.0", "1.0.1", true)]
    [InlineData("v1.0.0", "1.1.0", true)]
    [InlineData("1.0.0", "latest", false)]
    public void ComparesNumericVersions(string current, string candidate, bool newer)
    {
        Assert.Equal(newer, ReleaseVersion.IsNewer(current, candidate));
    }

    [Fact]
    public void DoesNotReinstallTheRunningFile()
    {
        var sha = new string('a', 64);
        var release = new AppRelease("1.2.0", new Uri("https://files.example.com/app.exe"), sha, "");

        Assert.False(ReleasePlan.ShouldInstall("1.1.0", sha, null, release));
        Assert.False(ReleasePlan.ShouldInstall("1.1.0", null, sha, release));
        Assert.True(ReleasePlan.ShouldInstall("1.1.0", new string('b', 64), new string('b', 64), release));
        Assert.False(ReleasePlan.ShouldInstall("1.2.0", null, null, release));
    }

    [Fact]
    public void EmptyManifestMeansNoRelease()
    {
        var release = AppReleaseManifest.Parse("""{"version":"","url":"","sha256":"","notes":""}""");

        Assert.Null(release);
    }

    [Fact]
    public void ParsesHttpsRelease()
    {
        var release = AppReleaseManifest.Parse(
            """
            {"version":"1.2.0","url":"https://files.example.com/KOC.exe","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","notes":"아이콘"}
            """);

        Assert.NotNull(release);
        Assert.Equal("1.2.0", release!.Version);
        Assert.Equal("https://files.example.com/KOC.exe", release.Url.AbsoluteUri);
        Assert.Equal("아이콘", release.Notes);
    }

    [Fact]
    public void RejectsInsecureDownload()
    {
        var body = """{"version":"1.2.0","url":"http://files.example.com/KOC.exe","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","notes":""}""";

        Assert.Throws<InvalidOperationException>(() => AppReleaseManifest.Parse(body));
    }

    [Fact]
    public async Task DownloadKeepsMatchingFile()
    {
        var bytes = Encoding.UTF8.GetBytes("koc-drive");
        var sha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var destination = Path.Combine(_directory, "KOC ERP.exe");
        using var http = new HttpClient(new StubHandler(_ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(bytes),
        }));

        await ReleaseFiles.SaveVerifiedAsync(http, new Uri("https://files.example.com/app.exe"), sha, destination, CancellationToken.None);

        Assert.Equal(bytes, await File.ReadAllBytesAsync(destination));
        Assert.False(File.Exists(destination + ".part"));
    }

    [Fact]
    public async Task DownloadDeletesMismatchedFile()
    {
        var destination = Path.Combine(_directory, "KOC ERP.exe");
        using var http = new HttpClient(new StubHandler(_ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(Encoding.UTF8.GetBytes("tampered")),
        }));

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            ReleaseFiles.SaveVerifiedAsync(
                http,
                new Uri("https://files.example.com/app.exe"),
                new string('a', 64),
                destination,
                CancellationToken.None));

        Assert.False(File.Exists(destination));
        Assert.False(File.Exists(destination + ".part"));
    }

    private sealed class StubHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, HttpResponseMessage> _respond;

        public StubHandler(Func<HttpRequestMessage, HttpResponseMessage> respond) => _respond = respond;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(_respond(request));
    }
}
