# Windows desktop acceptance evidence

The Windows release build is accepted only after the packaged GUI-subsystem executable:

1. loads the PySide6/Qt native window without a browser or WebView;
2. constructs all six product pages;
3. starts the embedded FastAPI/SQLite worker without a console stream;
4. returns the expected health capability contract; and
5. initializes and validates a temporary project under a Chinese path.

`packaged-desktop-smoke.json` records that check against the portable build directory.
`installed-desktop-smoke.json` records the same check after a silent install from the generated
Inno Setup executable. The test installation was then uninstalled successfully.

Build command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts/build_windows_desktop.ps1
```
