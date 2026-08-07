using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Windows.Forms;

internal static class Program
{
    private static NotifyIcon _tray;
    private static Process _serverProc;
    private static System.Windows.Forms.Timer _statusTimer;
    private static string _launcher;
    private const string WebUrl = "http://localhost:8501";
    private const string HealthUrl = "http://127.0.0.1:8000/api/health";
    private static readonly int[] Ports = { 8000, 8501 };

    [STAThread]
    private static void Main()
    {
        _launcher = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "启动蒸馏应用.cmd");

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        _tray = new NotifyIcon
        {
            Icon = SystemIcons.Application,
            Text = "Video Account Distiller",
            Visible = true
        };

        var menu = new ContextMenuStrip();

        var openItem = new ToolStripMenuItem("打开界面");
        openItem.Click += (s, e) => OpenWeb();
        menu.Items.Add(openItem);

        var restartItem = new ToolStripMenuItem("重启服务");
        restartItem.Click += (s, e) =>
        {
            StopServer();
            Thread.Sleep(800);
            StartServer();
            _tray.ShowBalloonTip(2500, "Video Account Distiller", "服务已重启：" + WebUrl, ToolTipIcon.Info);
        };
        menu.Items.Add(restartItem);

        var exitItem = new ToolStripMenuItem("退出");
        exitItem.Click += (s, e) =>
        {
            _tray.Visible = false;
            StopServer();
            Application.Exit();
        };
        menu.Items.Add(exitItem);

        _tray.ContextMenuStrip = menu;
        _tray.DoubleClick += (s, e) => OpenWeb();

        _statusTimer = new System.Windows.Forms.Timer();
        _statusTimer.Interval = 10000;
        _statusTimer.Tick += (s, e) =>
        {
            _tray.Text = IsServerRunning()
                ? "Video Account Distiller（运行中）"
                : "Video Account Distiller（已停止）";
        };
        _statusTimer.Start();

        StartServer();
        if (IsServerRunning())
        {
            _tray.ShowBalloonTip(3000, "Video Account Distiller", "服务已启动：" + WebUrl, ToolTipIcon.Info);
        }

        Application.Run();
    }

    private static void OpenWeb()
    {
        try
        {
            Process.Start(new ProcessStartInfo(WebUrl) { UseShellExecute = true });
        }
        catch
        {
            // Ignore browser launch failures.
        }
    }

    private static bool IsServerRunning()
    {
        try
        {
            var request = (System.Net.HttpWebRequest)System.Net.WebRequest.Create(HealthUrl);
            request.Timeout = 3000;
            using (var response = (System.Net.HttpWebResponse)request.GetResponse())
            {
                return response.StatusCode == System.Net.HttpStatusCode.OK;
            }
        }
        catch
        {
            return false;
        }
    }

    private static void StartServer()
    {
        if (IsServerRunning())
        {
            return;
        }
        try
        {
            if (_serverProc != null && !_serverProc.HasExited)
            {
                return;
            }
        }
        catch
        {
            _serverProc = null;
        }

        try
        {
            var startInfo = new ProcessStartInfo("cmd.exe", "/c \"" + _launcher + "\"")
            {
                WorkingDirectory = Path.GetDirectoryName(_launcher),
                WindowStyle = ProcessWindowStyle.Hidden,
                CreateNoWindow = true,
                UseShellExecute = false
            };
            _serverProc = Process.Start(startInfo);
        }
        catch
        {
            // Keep the tray alive even if the server cannot be started right now.
        }
    }

    private static void StopServer()
    {
        try
        {
            if (_serverProc != null && !_serverProc.HasExited)
            {
                var killer = Process.Start(new ProcessStartInfo(
                    "taskkill.exe",
                    "/PID " + _serverProc.Id + " /T /F")
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden
                });
                if (killer != null)
                {
                    killer.WaitForExit(5000);
                }
            }
        }
        catch
        {
            // Fall through to the port-based cleanup.
        }
        _serverProc = null;
        KillListenersOnPorts(Ports);
    }

    private static void KillListenersOnPorts(int[] ports)
    {
        try
        {
            var psi = new ProcessStartInfo("netstat", "-ano")
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            using (var process = Process.Start(psi))
            {
                if (process == null)
                {
                    return;
                }
                string output = process.StandardOutput.ReadToEnd();
                process.WaitForExit();
                foreach (string line in output.Split('\n'))
                {
                    if (!line.Contains("LISTENING"))
                    {
                        continue;
                    }
                    foreach (int port in ports)
                    {
                        if (!line.Contains(":" + port))
                        {
                            continue;
                        }
                        string[] parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                        if (parts.Length < 5)
                        {
                            continue;
                        }
                        int pid;
                        if (int.TryParse(parts[parts.Length - 1], out pid))
                        {
                            try
                            {
                                Process.GetProcessById(pid).Kill();
                            }
                            catch
                            {
                                // Process already exited or access denied.
                            }
                        }
                    }
                }
            }
        }
        catch
        {
            // Best-effort cleanup only.
        }
    }
}
