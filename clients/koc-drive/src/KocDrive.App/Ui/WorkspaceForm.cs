namespace KocDrive.App;

internal sealed class WorkspaceForm : KocDialog
{
    private readonly ListBox _list;
    private readonly Label _error;

    public WorkspaceForm(IReadOnlyList<(long Id, string Name)> workspaces)
        : base("KOC ERP", 492)
    {
        AddLogo();
        AddHeading("워크스페이스");
        _list = new ListBox
        {
            Width = ContentWidth - 16,
            Height = 164,
            BorderStyle = BorderStyle.None,
            BackColor = KocTheme.Input,
            ForeColor = KocTheme.Text,
            Font = KocTheme.InputFont,
            IntegralHeight = false,
        };
        foreach (var workspace in workspaces)
        {
            _list.Items.Add(new WorkspaceItem(workspace.Id, workspace.Name));
        }

        if (_list.Items.Count > 0)
        {
            _list.SelectedIndex = 0;
        }

        var frame = new RoundedPanel
        {
            Width = ContentWidth,
            Height = 180,
            Radius = 8,
            BackColor = KocTheme.Input,
            Padding = new Padding(8),
            Margin = new Padding(0, 0, 0, 8),
        };
        _list.Dock = DockStyle.Fill;
        frame.Controls.Add(_list);
        Body.Controls.Add(frame);
        _error = AddError();
        var submit = AddButton("이 공유 문서함 동기화");
        submit.Click += (_, _) =>
        {
            if (_list.SelectedItem is not WorkspaceItem item)
            {
                ShowError(_error, "워크스페이스를 선택하세요.");
                return;
            }

            WorkspaceId = item.Id;
            DialogResult = DialogResult.OK;
            Close();
        };
        AcceptButton = submit;
    }

    public long WorkspaceId { get; private set; }

    private sealed record WorkspaceItem(long Id, string Name)
    {
        public override string ToString() => Name;
    }
}
