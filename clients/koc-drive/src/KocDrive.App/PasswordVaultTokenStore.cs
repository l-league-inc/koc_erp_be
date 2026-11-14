using KocDrive.Core.Api;
using Windows.Security.Credentials;

namespace KocDrive.App;

internal sealed class PasswordVaultTokenStore : ITokenStore
{
    private const string Resource = "KOC ERP";

    public string? LoadRefresh()
    {
        try
        {
            var credential = new PasswordVault().FindAllByResource(Resource).First();
            credential.RetrievePassword();
            return credential.Password;
        }
        catch (Exception)
        {
            return null;
        }
    }

    public void SaveRefresh(string refresh)
    {
        Clear();
        new PasswordVault().Add(new PasswordCredential(Resource, "refresh", refresh));
    }

    public void Clear()
    {
        try
        {
            var vault = new PasswordVault();
            foreach (var credential in vault.FindAllByResource(Resource))
            {
                vault.Remove(credential);
            }
        }
        catch (Exception)
        {
        }
    }
}
