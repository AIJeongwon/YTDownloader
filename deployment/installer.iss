#ifndef AppVersion
  #error AppVersion 전처리 상수가 필요합니다.
#endif
#ifndef SourceDir
  #error SourceDir 전처리 상수가 필요합니다.
#endif
#ifndef OutputDir
  #error OutputDir 전처리 상수가 필요합니다.
#endif
#ifndef Publisher
  #define Publisher "AIJeongwon"
#endif

[Setup]
AppId={{67985A8B-326E-4892-9158-F5AC2573577E}
AppName=YTDownloader
AppVersion={#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL=https://github.com/AIJeongwon/YTDownloader
AppSupportURL=https://github.com/AIJeongwon/YTDownloader/issues
AppUpdatesURL=https://github.com/AIJeongwon/YTDownloader/releases
DefaultDirName={localappdata}\Programs\YTDownloader
DefaultGroupName=YTDownloader
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=YTDownloader-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\YTDownloader.exe
LicenseFile={#SourceDir}\licenses\YTDownloader-MIT.txt
VersionInfoVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\YTDownloader"; Filename: "{app}\YTDownloader.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\YTDownloader"; Filename: "{app}\YTDownloader.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로 가기 만들기"; GroupDescription: "추가 바로 가기:"

[Run]
Filename: "{app}\YTDownloader.exe"; Description: "YTDownloader 실행"; Flags: nowait postinstall skipifsilent
