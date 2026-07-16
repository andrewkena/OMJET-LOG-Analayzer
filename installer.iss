#define MyAppName "OMJET LOG Analyzer"
#define MyAppVersion "0.74_16.07.2026"
#define MyAppExeName "OMJET_Log_Analyzer.exe"

[Setup]
AppId={{B6E2C9F4-7C2D-4C9E-9B3D-3D9D8E2F4A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=OMJET_Log_Analyzer_Setup
SetupIconFile=assets\logo.ico
WizardImageFile=assets\installer\wizard_image.png
WizardSmallImageFile=assets\installer\wizard_small_image.png
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительные значки:"

[Files]
Source: "dist\OMJET_Log_Analyzer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
