; Inno Setup 6 — compile after PyInstaller: iscc packaging\DiscordAudioBotTUI.iss
; Run from repo root; expects dist\DiscordAudioBotTUI\

#define MyAppName "Discord Audio Bot TUI"
#define MyAppVersion "0.1.0"
#define MyAppExeName "DiscordAudioBotTUI.exe"
#define MyAppSrc "..\dist\DiscordAudioBotTUI"

[Setup]
AppId={{A8B4C1D2-E3F4-5678-90AB-CDEF01234567}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\build\installer-output
OutputBaseFilename=DiscordAudioBotTUI-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MyAppSrc}\*"; DestDir: "{app}"; Excludes: "settings.json"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
