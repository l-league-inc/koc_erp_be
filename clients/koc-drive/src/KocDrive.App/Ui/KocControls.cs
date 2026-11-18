namespace KocDrive.App;

internal class KocDialog : Form
{
    public const int DialogWidth = 480;
    public const int PagePadding = 20;
    public const int CardPadding = 40;
    public const int ContentWidth = DialogWidth - (PagePadding * 2) - (CardPadding * 2);

    private readonly RoundedPanel _card = new() { Radius = 20, BackColor = KocTheme.Card };

    protected KocDialog(string title, int height)
    {
        Text = title;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.None;
        BackColor = KocTheme.Page;
        Font = KocTheme.Body;
        ClientSize = new Size(DialogWidth, height);
        try
        {
            Icon = AppIcon.Load();
        }
        catch (Exception)
        {
        }

        var host = new Panel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(PagePadding),
            BackColor = KocTheme.Page,
        };
        _card.Dock = DockStyle.Fill;
        Body = new VerticalStack
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(CardPadding, 36, CardPadding, 36),
            BackColor = KocTheme.Card,
        };
        _card.Controls.Add(Body);
        host.Controls.Add(_card);
        Controls.Add(host);
    }

    protected VerticalStack Body { get; }

    protected void AddLogo()
    {
        var row = new Panel
        {
            Width = ContentWidth,
            Height = 72,
            BackColor = KocTheme.Card,
            Margin = new Padding(0, 0, 0, 28),
        };
        row.Controls.Add(new PictureBox
        {
            Image = BrandAssets.Logo(),
            SizeMode = PictureBoxSizeMode.Zoom,
            BackColor = KocTheme.Card,
            Dock = DockStyle.Fill,
        });
        Body.Controls.Add(row);
    }

    protected void AddHeading(string text)
    {
        Body.Controls.Add(new Label
        {
            Text = text,
            AutoSize = false,
            Width = ContentWidth,
            Height = 22,
            ForeColor = KocTheme.Text,
            BackColor = KocTheme.Card,
            Font = KocTheme.Label,
            Margin = new Padding(0, 0, 0, 16),
        });
    }

    protected KocField AddField(string placeholder, bool password = false)
    {
        var field = new KocField(placeholder, password)
        {
            Width = ContentWidth,
            Margin = new Padding(0, 0, 0, 12),
        };
        Body.Controls.Add(field);
        return field;
    }

    protected Label AddError()
    {
        var error = new Label
        {
            AutoSize = false,
            Size = new Size(ContentWidth, 48),
            ForeColor = KocTheme.Danger,
            BackColor = KocTheme.Card,
            Font = KocTheme.Error,
            Margin = new Padding(0, 0, 0, 8),
            Visible = false,
        };
        Body.Controls.Add(error);
        return error;
    }

    protected KocButton AddButton(string text, bool primary = true)
    {
        var button = new KocButton(text, primary)
        {
            Width = ContentWidth,
            Margin = new Padding(0, 8, 0, 0),
        };
        Body.Controls.Add(button);
        return button;
    }

    protected void ShowError(Label error, string message)
    {
        error.Text = message;
        error.Visible = message.Length > 0;
    }
}

internal sealed class VerticalStack : Panel
{
    private bool _arranging;

    public VerticalStack()
    {
        AutoScroll = true;
        DoubleBuffered = true;
    }

    protected override void OnControlAdded(ControlEventArgs e)
    {
        base.OnControlAdded(e);
        if (e.Control is null)
        {
            return;
        }

        e.Control.VisibleChanged += (_, _) => Arrange();
        Arrange();
    }

    protected override void OnLayout(LayoutEventArgs eventArgs)
    {
        Arrange();
    }

    public void Arrange()
    {
        if (_arranging || IsDisposed)
        {
            return;
        }

        _arranging = true;
        try
        {
            var y = Padding.Top;
            var width = Math.Max(1, ClientSize.Width - Padding.Horizontal);
            foreach (Control child in Controls)
            {
                if (!child.Visible)
                {
                    continue;
                }

                var height = Math.Max(child.Height, 1);
                y += child.Margin.Top;
                child.SetBounds(Padding.Left, y, width, height);
                y += height + child.Margin.Bottom;
            }

            var contentHeight = y + Padding.Bottom;
            if (AutoScrollMinSize.Height != contentHeight)
            {
                AutoScrollMinSize = new Size(0, contentHeight);
            }
        }
        finally
        {
            _arranging = false;
        }
    }
}

internal sealed class RoundedPanel : Panel
{
    public int Radius { get; set; } = 20;

    public RoundedPanel()
    {
        DoubleBuffered = true;
        ResizeRedraw = true;
    }
}

internal sealed class KocField : Panel
{
    private readonly TextBox _box;
    private bool _invalid;

    public KocField(string placeholder, bool password)
    {
        BackColor = KocTheme.Input;
        DoubleBuffered = true;
        ResizeRedraw = true;
        _box = new TextBox
        {
            BorderStyle = BorderStyle.None,
            BackColor = KocTheme.Input,
            ForeColor = KocTheme.Text,
            Font = KocTheme.InputFont,
            PlaceholderText = placeholder,
            UseSystemPasswordChar = password,
            Location = new Point(16, 14),
        };
        Controls.Add(_box);
        Width = KocDialog.ContentWidth;
        Height = 48;
    }

    public bool Invalid
    {
        get => _invalid;
        set
        {
            _invalid = value;
            Invalidate();
        }
    }

    public string Value
    {
        get => _box.Text;
        set => _box.Text = value ?? "";
    }

    public void FocusInput() => _box.Focus();

    protected override void OnResize(EventArgs eventArgs)
    {
        base.OnResize(eventArgs);
        if (_box is null)
        {
            return;
        }

        _box.Width = Math.Max(0, Width - 32);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        var bounds = new Rectangle(0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1));
        using var path = KocTheme.CreatePath(bounds, 8);
        using var pen = new Pen(_invalid ? KocTheme.Danger : KocTheme.Line);
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        e.Graphics.DrawPath(pen, path);
    }
}

internal sealed class KocButton : Button
{
    private readonly bool _primary;

    public KocButton(string text, bool primary)
    {
        _primary = primary;
        Text = text;
        Height = 48;
        FlatStyle = FlatStyle.Flat;
        Font = KocTheme.ButtonFont;
        Cursor = Cursors.Hand;
        FlatAppearance.BorderSize = primary ? 0 : 1;
        FlatAppearance.BorderColor = KocTheme.Line;
        ApplyFace();
    }

    protected override void OnMouseEnter(EventArgs e)
    {
        base.OnMouseEnter(e);
        if (!Enabled)
        {
            return;
        }

        BackColor = _primary ? KocTheme.ButtonHover : KocTheme.MenuHover;
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        base.OnMouseLeave(e);
        ApplyFace();
    }

    protected override void OnEnabledChanged(EventArgs e)
    {
        base.OnEnabledChanged(e);
        ApplyFace();
    }

    private void ApplyFace()
    {
        if (_primary)
        {
            BackColor = Enabled ? KocTheme.Button : KocTheme.ButtonDisabled;
            ForeColor = Color.White;
            return;
        }

        BackColor = Color.White;
        ForeColor = KocTheme.Text;
    }
}
