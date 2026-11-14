namespace KocDrive.App;

internal sealed class LoginForm : KocDialog
{
    private readonly Func<string, string, Task> _signIn;
    private readonly KocField _email;
    private readonly KocField _password;
    private readonly KocButton _submit;
    private readonly Label _error;

    public LoginForm(Func<string, string, Task> signIn)
        : base("KOC ERP", 520)
    {
        _signIn = signIn;
        AddLogo();
        AddHeading("관리자 로그인");
        _email = AddField("이메일을 입력해주세요.");
        _password = AddField("비밀번호를 입력해 주세요.", password: true);
        _error = AddError();
        _submit = AddButton("로그인");
        _submit.Click += async (_, _) => await SubmitAsync();
        AcceptButton = _submit;
        Shown += (_, _) => _email.FocusInput();
    }

    public string Email { get; private set; } = "";

    private async Task SubmitAsync()
    {
        var email = _email.Value.Trim();
        var password = _password.Value;
        _email.Invalid = email.Length == 0;
        _password.Invalid = password.Length == 0;
        if (email.Length == 0)
        {
            ShowError(_error, "이메일을 입력해주세요.");
            return;
        }

        if (password.Length == 0)
        {
            ShowError(_error, "비밀번호를 입력해 주세요.");
            return;
        }

        ShowError(_error, "");
        _email.Invalid = false;
        _password.Invalid = false;
        _submit.Enabled = false;
        try
        {
            await _signIn(email, password);
            _password.Value = "";
            if (IsDisposed)
            {
                return;
            }

            Email = email;
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception exception)
        {
            if (IsDisposed)
            {
                return;
            }

            _password.Value = "";
            ShowError(_error, exception.Message);
            _submit.Enabled = true;
        }
    }
}
