namespace KocDrive.App;

internal sealed class KocMenuColorTable : ProfessionalColorTable
{
    public override Color MenuItemSelected => KocTheme.MenuHover;

    public override Color MenuItemSelectedGradientBegin => KocTheme.MenuHover;

    public override Color MenuItemSelectedGradientEnd => KocTheme.MenuHover;

    public override Color MenuItemBorder => KocTheme.MenuHover;

    public override Color MenuItemPressedGradientBegin => KocTheme.MenuHover;

    public override Color MenuItemPressedGradientEnd => KocTheme.MenuHover;

    public override Color MenuBorder => KocTheme.Line;

    public override Color ToolStripDropDownBackground => Color.White;

    public override Color ImageMarginGradientBegin => Color.White;

    public override Color ImageMarginGradientMiddle => Color.White;

    public override Color ImageMarginGradientEnd => Color.White;

    public override Color SeparatorDark => KocTheme.Line;

    public override Color SeparatorLight => KocTheme.Line;
}

internal sealed class KocMenuRenderer : ToolStripProfessionalRenderer
{
    public KocMenuRenderer()
        : base(new KocMenuColorTable())
    {
        RoundedEdges = false;
    }

    protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
    {
        e.TextColor = e.Item.Enabled ? KocTheme.Text : KocTheme.Status;
        base.OnRenderItemText(e);
    }
}
