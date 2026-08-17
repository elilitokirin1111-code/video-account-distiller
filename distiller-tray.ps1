# Video Account Distiller system-tray controller.
#
# Runs the local API + Web app hidden, with a tray icon that offers:
#   - 打开界面   (open http://localhost:8501)
#   - 重启服务   (stop and start the hidden server)
#   - 退出       (stop the server and remove the tray icon)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $repo '启动蒸馏应用.cmd'
$webUrl = 'http://localhost:8501'
$healthUrl = 'http://127.0.0.1:8000/api/health'

$script:serverProc = $null
$script:notify = $null

function Test-ServerRunning {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 3 -UseBasicParsing
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Start-Server {
    if (Test-ServerRunning) {
        return
    }
    if ($script:serverProc -and -not $script:serverProc.HasExited) {
        return
    }
    $script:serverProc = Start-Process `
        -FilePath 'cmd.exe' `
        -ArgumentList @('/c', ('"' + $launcher + '"')) `
        -WorkingDirectory $repo `
        -WindowStyle Hidden `
        -PassThru
}

function Stop-Server {
    if ($script:serverProc -and -not $script:serverProc.HasExited) {
        & taskkill.exe /PID $script:serverProc.Id /T /F 2>$null | Out-Null
    }
    $script:serverProc = $null
}

$script:notify = New-Object System.Windows.Forms.NotifyIcon
$script:notify.Icon = [System.Drawing.SystemIcons]::Application
$script:notify.Text = 'Video Account Distiller'
$script:notify.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip

$openItem = New-Object System.Windows.Forms.ToolStripMenuItem('打开界面')
$openItem.Add_Click({ Start-Process $webUrl })
$menu.Items.Add($openItem) | Out-Null

$restartItem = New-Object System.Windows.Forms.ToolStripMenuItem('重启服务')
$restartItem.Add_Click({
    Stop-Server
    Start-Sleep -Milliseconds 800
    Start-Server
    $script:notify.ShowBalloonTip(
        2500,
        'Video Account Distiller',
        '服务已重启：' + $webUrl,
        [System.Windows.Forms.ToolTipIcon]::Info
    )
})
$menu.Items.Add($restartItem) | Out-Null

$exitItem = New-Object System.Windows.Forms.ToolStripMenuItem('退出')
$exitItem.Add_Click({
    $script:notify.Visible = $false
    Stop-Server
    [System.Windows.Forms.Application]::Exit()
})
$menu.Items.Add($exitItem) | Out-Null

$script:notify.ContextMenuStrip = $menu
$script:notify.Add_DoubleClick({ Start-Process $webUrl })

$statusTimer = New-Object System.Windows.Forms.Timer
$statusTimer.Interval = 10000
$statusTimer.Add_Tick({
    if (Test-ServerRunning) {
        $script:notify.Text = 'Video Account Distiller（运行中）'
    } else {
        $script:notify.Text = 'Video Account Distiller（已停止）'
    }
})

Start-Server
$statusTimer.Start()

if (Test-ServerRunning) {
    $script:notify.ShowBalloonTip(
        3000,
        'Video Account Distiller',
        '服务已启动：' + $webUrl,
        [System.Windows.Forms.ToolTipIcon]::Info
    )
}

[System.Windows.Forms.Application]::Run()
