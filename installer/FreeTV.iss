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
Name: "desktopicon"; Description: "建立桌面捷徑"
Name: "autostart"; Description: "登入 Windows 後自動啟動 FreeTV"
Name: "appliancepower"; Description: "關上筆電螢幕後仍持續運作（停用目前電源方案的自動睡眠與休眠）"; Flags: unchecked

[Files]
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Excludes: "config\*,logs\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceRoot}\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\FreeTV"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\freetv.py"" start"; WorkingDir: "{app}"
Name: "{autodesktop}\FreeTV"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\freetv.py"" start"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\FreeTV"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\freetv.py"" start --supervise"; WorkingDir: "{app}"; Tasks: autostart

[Code]
var
  PreservedConfigPath: String;
  PreservedLogsPath: String;

function IsApplicationUpdate: Boolean;
begin
  Result := CompareText(ExpandConstant('{param:UPDATE|0}'), '1') = 0;
end;

procedure RaiseFailure(const Message: String);
begin
  RaiseException(Format('%s 安裝記錄：%s', [Message, ExpandConstant('{log}')]));
end;

procedure CopyUserDirectory(
  const SourcePath: String;
  const DestinationPath: String;
  const Name: String
);
var
  Parameters: String;
  ResultCode: Integer;
begin
  Parameters :=
    '"' + SourcePath + '" "' + DestinationPath +
    '" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /XJ';
  if not Exec(
    ExpandConstant('{sys}\robocopy.exe'),
    Parameters,
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
    RaiseFailure('無法啟動 ' + Name + ' 使用者資料保留作業。');
  if ResultCode >= 8 then
    RaiseFailure(
      Name + ' 使用者資料保留作業失敗（代碼 ' +
      IntToStr(ResultCode) + '）。'
    );
end;

procedure PreserveUserDirectory(const Name: String; var PreservedPath: String);
var
  OriginalPath: String;
  PreserveRoot: String;
begin
  OriginalPath := ExpandConstant('{app}\') + Name;
  if not DirExists(OriginalPath) then
    Exit;

  PreserveRoot := ExpandConstant('{localappdata}\FreeTV-uninstall-preserve');
  PreservedPath := PreserveRoot + '\' + Name;
  if DirExists(PreservedPath) then
    RaiseFailure(
      '無法保留 ' + Name + '；復原目錄已存在於 ' + PreservedPath + '。'
    );
  if not ForceDirectories(PreserveRoot) then
    RaiseFailure('無法建立 ' + Name + ' 的保留目錄。');
  CopyUserDirectory(OriginalPath, PreservedPath, Name);
end;

procedure RestoreUserDirectory(const Name: String; const PreservedPath: String);
var
  DestinationPath: String;
begin
  if (PreservedPath = '') or (not DirExists(PreservedPath)) then
    Exit;

  DestinationPath := ExpandConstant('{app}\') + Name;
  if not ForceDirectories(ExpandConstant('{app}')) then
    RaiseFailure('無法重新建立 FreeTV 使用者資料目錄。');
  CopyUserDirectory(PreservedPath, DestinationPath, Name);
  if not DelTree(PreservedPath, True, True, True) then
    RaiseFailure('無法清理 ' + Name + ' 的暫存保留資料。');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    PreserveUserDirectory('config', PreservedConfigPath);
    PreserveUserDirectory('logs', PreservedLogsPath);
  end
  else if CurUninstallStep = usPostUninstall then
  begin
    RestoreUserDirectory('config', PreservedConfigPath);
    RestoreUserDirectory('logs', PreservedLogsPath);
    DelTree(
      ExpandConstant('{localappdata}\FreeTV-uninstall-preserve'),
      True,
      True,
      True
    );
  end;
end;

procedure DeleteLegacyScheduledTask;
var
  ResultCode: Integer;
begin
  if not Exec(
    ExpandConstant('{sys}\schtasks.exe'),
    '/Query /TN "PC TV Box"',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
    RaiseFailure('無法檢查舊版 PC TV Box 排程工作。');

  if ResultCode <> 0 then
    Exit;

  if not Exec(
    ExpandConstant('{sys}\schtasks.exe'),
    '/Delete /TN "PC TV Box" /F',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
    RaiseFailure('無法刪除舊版 PC TV Box 排程工作。');
  if ResultCode <> 0 then
    RaiseFailure(Format('刪除舊版 PC TV Box 排程工作失敗（代碼 %d）。', [ResultCode]));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  PowerShell: String;
  Python: String;
  Pythonw: String;
  Parameters: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  WizardForm.StatusLabel.Caption := '正在初始化 FreeTV…';
  Python := ExpandConstant('{app}\runtime\python.exe');
  Parameters := ExpandConstant('"{app}\freetv.py" setup');
  if not Exec(
    Python,
    Parameters,
    ExpandConstant('{app}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
    RaiseFailure('無法啟動 FreeTV 初始化程式。');
  if ResultCode <> 0 then
    RaiseFailure(Format('FreeTV 初始化失敗（代碼 %d）。', [ResultCode]));

  if DirExists(ExpandConstant('{app}\.venv')) and
     (not DelTree(ExpandConstant('{app}\.venv'), True, True, True)) then
    RaiseFailure('無法移除舊版 FreeTV 虛擬環境。');
  DeleteLegacyScheduledTask;

  if WizardIsTaskSelected('appliancepower') and (not IsApplicationUpdate) then
  begin
    WizardForm.StatusLabel.Caption := '正在設定闔蓋不中斷的機上盒電源模式…';
    PowerShell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    Parameters := ExpandConstant(
      '-NoProfile -ExecutionPolicy Bypass -File "{app}\scripts\configure-appliance-power.ps1"'
    );
    if not ShellExec(
      'runas',
      PowerShell,
      Parameters,
      ExpandConstant('{app}'),
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    ) then
      RaiseFailure('無法取得設定機上盒電源模式所需的系統管理員權限。');
    if ResultCode <> 0 then
      RaiseFailure(Format('機上盒電源模式設定失敗（代碼 %d）。', [ResultCode]));
  end;

  WizardForm.StatusLabel.Caption := '正在啟動 FreeTV…';
  Pythonw := ExpandConstant('{app}\runtime\pythonw.exe');
  Parameters := ExpandConstant('"{app}\freetv.py" start --no-browser --no-tunnel');
  if not Exec(
    Pythonw,
    Parameters,
    ExpandConstant('{app}'),
    SW_HIDE,
    ewNoWait,
    ResultCode
  ) then
    RaiseFailure('無法啟動 FreeTV。');
end;

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""PC TV Box"" /F"; RunOnceId: "RemoveLegacyPCTVBoxTask"; Flags: waituntilterminated runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\licenses"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\vendor"
