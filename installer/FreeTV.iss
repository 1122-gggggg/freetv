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
  SetupFailureExitCode: Integer;

function IsApplicationUpdate: Boolean;
begin
  Result := CompareText(ExpandConstant('{param:UPDATE|0}'), '1') = 0;
end;

procedure RaiseFailure(const Message: String);
begin
  SetupFailureExitCode := 1;
  RaiseException(Format('%s 安裝記錄：%s', [Message, ExpandConstant('{log}')]));
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := SetupFailureExitCode;
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

function IsLegacyVenvExecutable(const ExecutablePath: String): Boolean;
var
  LegacyPrefix: String;
begin
  LegacyPrefix := AddBackslash(ExpandConstant('{app}\.venv'));
  Result :=
    (Length(ExecutablePath) >= Length(LegacyPrefix)) and
    (CompareText(
      Copy(ExecutablePath, 1, Length(LegacyPrefix)),
      LegacyPrefix
    ) = 0);
end;

procedure TerminateLegacyVenvProcesses;
var
  Attempt: Integer;
  ExecutablePath: String;
  Index: Integer;
  OwnedCount: Integer;
  Process: Variant;
  Processes: Variant;
  QueryError: String;
  Services: Variant;
  TerminateError: String;
  TerminateResult: Integer;
  WmiLocator: Variant;
begin
  Attempt := 0;
  repeat
    OwnedCount := 0;
    QueryError := '';
    TerminateError := '';
    try
      WmiLocator := CreateOleObject('WbemScripting.SWbemLocator');
      Services := WmiLocator.ConnectServer('.', 'root\cimv2');
      Processes := Services.ExecQuery(
        'SELECT ProcessId, ExecutablePath FROM Win32_Process ' +
        'WHERE ExecutablePath IS NOT NULL'
      );
      for Index := 0 to Processes.Count - 1 do
      begin
        Process := Processes.ItemIndex(Index);
        ExecutablePath := Process.ExecutablePath;
        if IsLegacyVenvExecutable(ExecutablePath) then
        begin
          OwnedCount := OwnedCount + 1;
          if Attempt = 0 then
          begin
            TerminateResult := Process.Terminate(0);
            if TerminateResult <> 0 then
              TerminateError :=
                '無法終止舊版 FreeTV 程序 ' +
                IntToStr(Process.ProcessId) + '（代碼 ' +
                IntToStr(TerminateResult) + '）。';
          end;
        end;
      end;
    except
      QueryError := GetExceptionMessage;
    end;

    if QueryError <> '' then
      RaiseFailure('無法查詢舊版 FreeTV 程序：' + QueryError);
    if TerminateError <> '' then
      RaiseFailure(TerminateError);
    if OwnedCount = 0 then
      Exit;

    Sleep(100);
    Attempt := Attempt + 1;
  until Attempt >= 100;

  RaiseFailure('舊版 FreeTV 程序未在 10 秒內結束。');
end;

procedure MigrateLegacyInstallation;
var
  Action: Variant;
  Actions: Variant;
  Candidate: Variant;
  ExpectedArguments: String;
  Found: Boolean;
  Index: Integer;
  Owned: Boolean;
  QueryError: String;
  RootFolder: Variant;
  Scheduler: Variant;
  Task: Variant;
  Tasks: Variant;
begin
  Found := False;
  Owned := False;
  QueryError := '';
  try
    Scheduler := CreateOleObject('Schedule.Service');
    Scheduler.Connect;
    RootFolder := Scheduler.GetFolder('\');
    Tasks := RootFolder.GetTasks(0);
    for Index := 1 to Tasks.Count do
    begin
      Candidate := Tasks.Item(Index);
      if CompareText(Candidate.Name, 'PC TV Box') = 0 then
      begin
        Task := Candidate;
        Found := True;
        Break;
      end;
    end;

    if Found then
    begin
      Actions := Task.Definition.Actions;
      if Actions.Count = 1 then
      begin
        Action := Actions.Item(1);
        ExpectedArguments := ExpandConstant(
          '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden ' +
          '-File "{app}\scripts\start.ps1" -Supervise'
        );
        try
          Owned :=
            (CompareText(ExtractFileName(Action.Path), 'powershell.exe') = 0) and
            (CompareText(Action.Arguments, ExpectedArguments) = 0);
        except
          Owned := False;
        end;
      end;

      if Owned and (Task.State = 4) then
        Task.Stop(0);
    end;
  except
    QueryError := GetExceptionMessage;
  end;

  if QueryError <> '' then
    RaiseFailure('無法查詢舊版 PC TV Box 排程工作：' + QueryError);
  if not Found then
    Log('Legacy PC TV Box scheduled task was not found.')
  else if not Owned then
    Log('Preserving unrelated scheduled task named PC TV Box.');

  TerminateLegacyVenvProcesses;

  if Owned then
  begin
    QueryError := '';
    try
      RootFolder.DeleteTask('PC TV Box', 0);
    except
      QueryError := GetExceptionMessage;
    end;
    if QueryError <> '' then
      RaiseFailure('無法刪除舊版 PC TV Box 排程工作：' + QueryError);
  end;

  if DirExists(ExpandConstant('{app}\.venv')) and
     (not DelTree(ExpandConstant('{app}\.venv'), True, True, True)) then
    RaiseFailure('無法移除舊版 FreeTV 虛擬環境。');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    MigrateLegacyInstallation;
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

  MigrateLegacyInstallation;

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
    ewWaitUntilTerminated,
    ResultCode
  ) then
    RaiseFailure('無法啟動 FreeTV。');
  if ResultCode <> 0 then
    RaiseFailure(Format('FreeTV 啟動失敗（代碼 %d）。', [ResultCode]));
end;


[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\licenses"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\vendor"
