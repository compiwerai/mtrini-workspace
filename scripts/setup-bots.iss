; Mtrini Bots — Windows installer (compile with Inno Setup 6: iscc scripts\setup-bots.iss)
; A separate app from Mtrini Workspace: its own folder, shortcuts and uninstaller.
#define MyAppName "Mtrini Bots"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Compiwer AI"
#define MyAppExeName "MtriniBots.exe"

[Setup]
AppId={{7A2C91D4-5E3B-4F8A-9D16-MTRINIBOTS01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MtriniBots
DefaultGroupName={#MyAppName}
OutputDir=..\installer
OutputBaseFilename=MtriniBots-Setup-{#MyAppVersion}
SetupIconFile=..\assets\bots.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\MtriniBots\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Registry]
; "Start when I sign in" is switched on inside the app. Uninstalling removes it, so nothing is left behind.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "MtriniBots"; Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
