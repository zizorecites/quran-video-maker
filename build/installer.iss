; The Windows installer. GitHub builds this after making the program.
#define AppName "Quran Video Maker"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B0E3B52-2F7C-4C0E-9D5B-3A8E5C1F7D20}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=@zizorecites
AppPublisherURL=https://www.tiktok.com/@zizorecites
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\out
OutputBaseFilename=QuranVideoMaker-Windows-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent
