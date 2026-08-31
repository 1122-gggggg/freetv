#ifndef SourceRoot
  #error SourceRoot is required
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

#define AppName "FreeTV"
#define AppPublisher "FreeTV"
#define ProjectUrl "https://github.com/1122-gggggg/freetv"

[Setup]
AppId={{D4F64A62-2A79-4A79-B9DF-1C49583656C4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#ProjectUrl}
AppSupportURL={#ProjectUrl}/issues
AppUpdatesURL={#ProjectUrl}/releases/latest
DefaultDirName={localappdata}\FreeTV
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=FreeTV-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName={#AppName}
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=FreeTV Windows installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; Flags: unchecked

[Files]
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FreeTV"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\freetv.py"" start"; WorkingDir: "{app}"
Name: "{autodesktop}\FreeTV"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\freetv.py"" start"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  PowerShell: String;
  Parameters: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  WizardForm.StatusLabel.Caption := '正在安裝 FreeTV 執行環境並啟動電視介面…';
  PowerShell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  Parameters := ExpandConstant(
    '-NoProfile -ExecutionPolicy Bypass -File "{app}\scripts\install.ps1"'
  );
  if not Exec(
    PowerShell,
    Parameters,
    ExpandConstant('{app}'),
    SW_SHOW,
    ewWaitUntilTerminated,
    ResultCode
  ) then
    RaiseException('無法啟動 FreeTV 初始化程式。');
  if ResultCode <> 0 then
    RaiseException(Format('FreeTV 初始化失敗（代碼 %d）。請重新執行安裝程式。', [ResultCode]));
end;

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\install-autostart.ps1"" -Remove"; WorkingDir: "{app}"; RunOnceId: "RemoveFreeTVAutostart"; Flags: waituntilterminated runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
