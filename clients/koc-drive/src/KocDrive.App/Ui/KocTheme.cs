using System.Drawing.Drawing2D;

namespace KocDrive.App;

internal static class KocTheme
{
    public static readonly Color Page = Color.FromArgb(0xE8, 0xE8, 0xE8);
    public static readonly Color Card = Color.White;
    public static readonly Color Text = Color.FromArgb(0x33, 0x33, 0x33);
    public static readonly Color Title = Color.FromArgb(0x11, 0x11, 0x11);
    public static readonly Color Muted = Color.FromArgb(0xB8, 0xB8, 0xB8);
    public static readonly Color Input = Color.FromArgb(0xF5, 0xF5, 0xF5);
    public static readonly Color Line = Color.FromArgb(0xE5, 0xE5, 0xE5);
    public static readonly Color Button = Color.FromArgb(0x3D, 0x3D, 0x3D);
    public static readonly Color ButtonHover = Color.FromArgb(0x2F, 0x2F, 0x2F);
    public static readonly Color ButtonDisabled = Color.FromArgb(0x9A, 0x9A, 0x9A);
    public static readonly Color Danger = Color.FromArgb(0xF0, 0x44, 0x52);
    public static readonly Color MenuHover = Color.FromArgb(0xF2, 0xF4, 0xF6);
    public static readonly Color Status = Color.FromArgb(0x6B, 0x76, 0x84);

    private static readonly FontFamily Family = ResolveFamily();

    public static readonly Font Body = Create(9.75f);
    public static readonly Font Label = Create(9.75f);
    public static readonly Font InputFont = Create(10.5f);
    public static readonly Font ButtonFont = Create(11.25f);
    public static readonly Font TitleFont = Create(16.5f, FontStyle.Bold);
    public static readonly Font Menu = Create(10f);
    public static readonly Font Error = Create(9.75f);
    public static readonly Font Hint = Create(9f);

    public static GraphicsPath CreatePath(Rectangle bounds, int radius)
    {
        var path = new GraphicsPath();
        var diameter = Math.Max(1, radius * 2);
        if (bounds.Width < diameter || bounds.Height < diameter)
        {
            path.AddRectangle(bounds);
            return path;
        }

        var arc = new Rectangle(bounds.Location, new Size(diameter, diameter));
        path.AddArc(arc, 180, 90);
        arc.X = bounds.Right - diameter;
        path.AddArc(arc, 270, 90);
        arc.Y = bounds.Bottom - diameter;
        path.AddArc(arc, 0, 90);
        arc.X = bounds.Left;
        path.AddArc(arc, 90, 90);
        path.CloseFigure();
        return path;
    }

    private static Font Create(float size, FontStyle style = FontStyle.Regular)
    {
        try
        {
            return new Font(Family, size, style, GraphicsUnit.Point);
        }
        catch (ArgumentException)
        {
            return new Font(FontFamily.GenericSansSerif, size, FontStyle.Regular, GraphicsUnit.Point);
        }
    }

    private static FontFamily ResolveFamily()
    {
        foreach (var name in new[] { "Malgun Gothic", "Segoe UI" })
        {
            try
            {
                return new FontFamily(name);
            }
            catch (ArgumentException)
            {
            }
        }

        return SystemFonts.MessageBoxFont?.FontFamily ?? FontFamily.GenericSansSerif;
    }
}
