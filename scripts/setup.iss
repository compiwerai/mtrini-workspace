; Mtrini Workspace — Windows installer (compile with Inno Setup 6: iscc scripts\setup.iss)
#define MyAppName "Mtrini Workspace"
#define MyAppVersion "0.6.1"
#define MyAppPublisher "Compiwer AI"
#define MyAppExeName "MtriniWorkspace.exe"

[Setup]
AppId={{3E7B4F2A-9C1D-4E6A-8B5F-MTRINI000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MtriniWorkspace
DefaultGroupName={#MyAppName}
OutputDir=..\installer
OutputBaseFilename=MtriniWorkspace-Setup-{#MyAppVersion}
SetupIconFile=..\assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\MtriniWorkspace\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
