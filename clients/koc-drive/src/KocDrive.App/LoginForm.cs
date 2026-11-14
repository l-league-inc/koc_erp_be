namespace KocDrive.App;

internal sealed class LoginForm : Form
{
    private readonly TextBox _email = new() { PlaceholderText = "이메일", Width = 280 };
    private readonly TextBox _password = new() { PlaceholderText = "비밀번호", Width = 280, UseSystemPasswordChar = true };

    public LoginForm()
    {
        Text = "KOC ERP 로그인";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(320, 150);
        var layout = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(16) };
        var submit = new Button { Text = "로그인", Width = 280 };
        submit.Click += (_, _) =>
        {
            Email = _email.Text.Trim();
            Password = _password.Text;
            DialogResult = DialogResult.OK;
            Close();
        };
        layout.Controls.Add(_email);
        layout.Controls.Add(_password);
        layout.Controls.Add(submit);
        Controls.Add(layout);
        AcceptButton = submit;
    }

    public string Email { get; private set; } = "";

    public string Password { get; private set; } = "";
}

internal sealed class WorkspaceForm : Form
{
    public WorkspaceForm(IReadOnlyList<(long Id, string Name)> workspaces)
    {
        Text = "워크스페이스";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(320, 160);
        var list = new ListBox { Width = 280, Height = 80 };
        foreach (var workspace in workspaces)
        {
            list.Items.Add(new WorkspaceItem(workspace.Id, workspace.Name));
        }

        list.SelectedIndex = 0;
        var submit = new Button { Text = "이 공유 문서함 동기화", Width = 280 };
        submit.Click += (_, _) =>
        {
            if (list.SelectedItem is WorkspaceItem item)
            {
                WorkspaceId = item.Id;
                DialogResult = DialogResult.OK;
                Close();
            }
        };
        var layout = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(16) };
        layout.Controls.Add(list);
        layout.Controls.Add(submit);
        Controls.Add(layout);
    }

    public long WorkspaceId { get; private set; }

    private sealed record WorkspaceItem(long Id, string Name)
    {
        public override string ToString() => Name;
    }
}
