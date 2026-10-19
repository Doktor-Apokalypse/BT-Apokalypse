#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{8975BCCE-C84D-44EE-AE7B-4CDAF74175B7}
AppName=BT Apokalypse
AppVersion={#AppVersion}
AppPublisher=Doktor Apokalypse
AppPublisherURL=https://github.com/Doktor-Apokalypse/BT-Apokalypse
AppSupportURL=https://github.com/Doktor-Apokalypse/BT-Apokalypse/issues
DefaultDirName={localappdata}\Programs\BT Apokalypse
DefaultGroupName=BT Apokalypse
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=BT-Apokalypse-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ChangesAssociations=yes
UninstallDisplayIcon={app}\BT Apokalypse.exe
VersionInfoVersion={#AppVersion}
VersionInfoProductName=BT Apokalypse
VersionInfoDescription=BT Apokalypse installer

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "associations"; Description: "Open .torrent files and magnet links with BT Apokalypse"; GroupDescription: "File and link associations:"

[Files]
Source: "..\dist\BT Apokalypse\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BT Apokalypse"; Filename: "{app}\BT Apokalypse.exe"
Name: "{autodesktop}\BT Apokalypse"; Filename: "{app}\BT Apokalypse.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BT Apokalypse.exe"; Parameters: "--register-associations"; Tasks: associations; Flags: runhidden waituntilterminated
Filename: "ms-settings:defaultapps?registeredAppUser=BT%20Apokalypse"; Description: "Confirm BT Apokalypse file and link defaults in Windows"; Tasks: associations; Flags: shellexec nowait postinstall skipifsilent
Filename: "{app}\BT Apokalypse.exe"; Description: "Launch BT Apokalypse"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\BT Apokalypse.exe"; Parameters: "--unregister-associations"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "RemoveTorrentAssociations"
