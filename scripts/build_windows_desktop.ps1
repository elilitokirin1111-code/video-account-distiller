[CmdletBinding()]
param(
    [ValidatePattern('^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')]
    [string]$Version = "1.1.0",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distRoot = Join-Path $repository "dist\windows"
$applicationDir = Join-Path $distRoot "VideoAccountDistiller"
$evidenceDir = Join-Path $repository "release-evidence\desktop"
$iconSource = Join-Path $repository "src\video_account_distiller_desktop\assets\app-icon.svg"
$iconOutput = Join-Path $repository "build\desktop\app-icon.ico"
$spec = Join-Path $repository "packaging\windows\VideoAccountDistiller.spec"
$installerScript = Join-Path $repository "packaging\windows\VideoAccountDistiller.iss"

Push-Location $repository
try {
    uv sync --extra desktop
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

    uv run python tools/build_desktop_icon.py $iconSource $iconOutput
    if ($LASTEXITCODE -ne 0) { throw "Desktop icon build failed" }

    uv run pyinstaller --noconfirm --clean --distpath $distRoot `
        --workpath (Join-Path $repository "build\pyinstaller") $spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

    $mediacrawlerRuntime = Join-Path $applicationDir "_internal\third_party\MediaCrawler"
    uv run python -c `
        "import importlib, sys; sys.path.insert(0, sys.argv[1]); importlib.import_module('cache.cache_factory')" `
        $mediacrawlerRuntime
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged MediaCrawler cache import probe failed"
    }

    Copy-Item -LiteralPath (Join-Path $repository "docs\desktop-user-guide.md") `
        -Destination (Join-Path $applicationDir "desktop-user-guide.md") -Force
    Copy-Item -LiteralPath (Join-Path $repository "LICENSE") `
        -Destination (Join-Path $applicationDir "LICENSE") -Force
    Copy-Item -LiteralPath (Join-Path $repository "THIRD_PARTY_NOTICES.md") `
        -Destination (Join-Path $applicationDir "THIRD_PARTY_NOTICES.md") -Force

    New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
    $smokeResult = Join-Path $evidenceDir "packaged-desktop-smoke.json"
    $executable = Join-Path $applicationDir "VideoAccountDistiller.exe"
    $process = Start-Process -FilePath $executable `
        -ArgumentList @("--smoke-test-output", $smokeResult) -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Packaged desktop smoke test failed with exit code $($process.ExitCode)"
    }
    $smoke = Get-Content -LiteralPath $smokeResult -Raw | ConvertFrom-Json
    if (
        -not $smoke.ok `
        -or -not $smoke.native_qt_window `
        -or $smoke.page_count -ne 6 `
        -or $smoke.progress_stage_count -ne 6 `
        -or -not $smoke.animated_wait_feedback `
        -or -not $smoke.mediacrawler_runtime_complete `
        -or ($smoke.ffmpeg_available -and -not $smoke.ffmpeg_external_process_ready)
    ) {
        throw "Packaged desktop smoke result did not satisfy the acceptance contract"
    }

    $portable = Join-Path $distRoot "VideoAccountDistiller-$Version-win64-portable.zip"
    Compress-Archive -Path (Join-Path $applicationDir "*") -DestinationPath $portable -Force

    if (-not $SkipInstaller) {
        $isccCandidates = @(
            (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        $iscc = $isccCandidates | Select-Object -First 1
        if ($iscc) {
            $installerOutput = Join-Path $distRoot "installer"
            New-Item -ItemType Directory -Path $installerOutput -Force | Out-Null
            & $iscc "/DMyAppVersion=$Version" "/DSourceDir=$applicationDir" `
                "/DOutputDir=$installerOutput" $installerScript
            if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }
            $expectedInstaller = Join-Path $installerOutput `
                "VideoAccountDistiller-Setup-$Version-win64.exe"
            if (-not (Test-Path -LiteralPath $expectedInstaller -PathType Leaf)) {
                throw "Inno Setup did not produce the exact versioned installer"
            }
        } else {
            throw "Inno Setup 6 was not found; use -SkipInstaller only for an explicit portable-only build."
        }
    }

    $artifacts = @(
        Get-Item -LiteralPath $executable
        Get-Item -LiteralPath $portable
    )
    $installerArtifact = Get-ChildItem -LiteralPath (Join-Path $distRoot "installer") `
        -Filter "VideoAccountDistiller-Setup-$Version-win64.exe" -File `
        -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($installerArtifact) {
        $artifacts += $installerArtifact
    }
    $checksumLines = foreach ($artifact in $artifacts) {
        $hash = Get-FileHash -LiteralPath $artifact.FullName -Algorithm SHA256
        "$($hash.Hash.ToLowerInvariant())  $($artifact.FullName.Substring($distRoot.Length + 1).Replace('\', '/'))"
    }
    [System.IO.File]::WriteAllLines(
        (Join-Path $distRoot "SHA256SUMS.txt"),
        $checksumLines,
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host "Desktop build accepted: $executable"
    Write-Host "Portable archive: $portable"
    Write-Host "Acceptance evidence: $smokeResult"
} finally {
    Pop-Location
}
