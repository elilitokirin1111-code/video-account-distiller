#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\windows\VideoAccountDistiller"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist\windows\installer"
#endif

[Setup]
AppId={{8EECC661-966C-4CA4-86CC-8EC1E6C4982B}
AppName=视频账号蒸馏器
AppVersion={#MyAppVersion}
AppPublisher=video-account-distiller contributors
DefaultDirName={localappdata}\Programs\Video Account Distiller
DefaultGroupName=视频账号蒸馏器
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=VideoAccountDistiller-Setup-{#MyAppVersion}-win64
SetupIconFile=..\..\build\desktop\app-icon.ico
UninstallDisplayIcon={app}\VideoAccountDistiller.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=..\..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\视频账号蒸馏器"; Filename: "{app}\VideoAccountDistiller.exe"
Name: "{autodesktop}\视频账号蒸馏器"; Filename: "{app}\VideoAccountDistiller.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VideoAccountDistiller.exe"; Description: "启动视频账号蒸馏器"; Flags: nowait postinstall skipifsilent
