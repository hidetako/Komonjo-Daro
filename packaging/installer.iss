; Inno Setup スクリプト。ビルド後に:  ISCC /DAppVersion=0.2.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Arch
  #define Arch "x64"
#endif
#define AppName "Komonjo-Daro"
#define AppExe "Komonjo-Daro.exe"
#define AppPublisher "hidetako"
#define AppURL "https://github.com/hidetako/Komonjo-Daro"

[Setup]
AppId={{51C1D070-08B9-4728-BCC8-18B38DC75C39}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
; 管理者権限不要（ユーザー領域にインストール）→ 自動更新がスムーズ
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
#if Arch == "arm64"
OutputBaseFilename=Komonjo-Daro-Setup-arm64
#else
OutputBaseFilename=Komonjo-Daro-Setup
#endif
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
#if Arch == "arm64"
; ネイティブ ARM64 版: ARM64 Windows にのみインストール可
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
; x64 版: x64 と、エミュレーションで x64 を実行できる ARM64 Windows にインストール可
ArchitecturesInstallIn64BitMode=x64compatible
#endif
; 既存バージョンの上書きインストールを許可
UsePreviousAppDir=yes
CloseApplications=force
RestartApplications=no

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Komonjo-Daro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; 通常インストール後は「起動する」チェック付き、サイレント更新後はここから1回だけ再起動
; （アプリ側は多重起動を防ぐので、万一二重に起動しても既存ウィンドウを開くだけ）
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\{#AppName}\tmp"
