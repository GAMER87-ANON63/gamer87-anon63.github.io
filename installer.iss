[Setup]
AppName=PC Hardware Dashboard
AppVersion=1.0
DefaultDirName={autopf}\PC Hardware Dashboard
DefaultGroupName=PC Hardware Dashboard
OutputBaseFilename=PCHardwareDashboard_Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Files]
Source: "dist\PC Hardware Dashboard.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PC Hardware Dashboard"; Filename: "{app}\PC Hardware Dashboard.exe"
Name: "{autodesktop}\PC Hardware Dashboard"; Filename: "{app}\PC Hardware Dashboard.exe"; Tasks: desktopicon