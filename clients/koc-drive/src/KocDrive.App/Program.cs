namespace KocDrive.App;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        if (AppUpdate.TryApplyLaunch(args))
        {
            return;
        }

        try
        {
            AppInstall.InstallCopy();
            using var instance = new Mutex(initiallyOwned: true, @"Local\KocErpDrive", out var createdNew);
            if (!createdNew)
            {
                MessageBox.Show(
                    "KOC ERP가 이미 실행 중입니다. 작업 표시줄 시계 옆 ^ 를 눌러 아이콘을 확인하세요.",
                    "KOC ERP",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
                return;
            }

            ApplicationConfiguration.Initialize();
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += (_, args) =>
            {
                AppInstall.WriteStartupLog(args.Exception);
                var root = args.Exception.GetBaseException();
                MessageBox.Show(root.Message, "KOC ERP", MessageBoxButtons.OK, MessageBoxIcon.Error);
            };
            Application.Run(new TrayApplication());
        }
        catch (Exception exception)
        {
            AppInstall.WriteStartupLog(exception);
            MessageBox.Show(RootMessage(exception), "KOC ERP", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string RootMessage(Exception exception)
    {
        while (exception.InnerException is not null)
        {
            exception = exception.InnerException;
        }

        return exception.Message;
    }
}
