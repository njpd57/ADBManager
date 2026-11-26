; Inno Setup script. Build dist\ADBManager.exe with PyInstaller first (see README).
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
; AppId identifies the application across upgrades: never change it.
AppId={{7B0E4C2A-93D5-4F61-A8B7-2C5E19D4F6A3}
AppName=ADBManager
AppVersion={#AppVersion}
AppPublisherURL=https://github.com/njpd57/ADBManager
DefaultDirName={autopf}\ADBManager
DisableProgramGroupPage=yes
; Per-user install by default, so no administrator rights are needed.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\ADBManager.exe
OutputDir=..\dist
OutputBaseFilename=ADBManager-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ADBManager.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\ADBManager"; Filename: "{app}\ADBManager.exe"
Name: "{autodesktop}\ADBManager"; Filename: "{app}\ADBManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ADBManager.exe"; Description: "{cm:LaunchProgram,ADBManager}"; Flags: nowait postinstall skipifsilent
