#ifndef AppVersion
  #define AppVersion "0.2.1"
#endif
[Setup]
AppId={{5E8A15A3-7C9C-47A5-A577-16CE0B45B43B}
AppName=llama.cpp Instance Manager
AppVersion={#AppVersion}
AppPublisher=ThatMonitorCord
AppPublisherURL=https://github.com/ThatMonitorCord/llama.cpp-Instance-Manager
AppSupportURL=https://github.com/ThatMonitorCord/llama.cpp-Instance-Manager/issues
AppUpdatesURL=https://github.com/ThatMonitorCord/llama.cpp-Instance-Manager/releases
DefaultDirName={localappdata}\Programs\llama.cpp Instance Manager
DefaultGroupName=llama.cpp Instance Manager
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=llama-cpp-instance-manager-{#AppVersion}-windows-x64-setup
SetupIconFile=..\assets\manager.ico
UninstallDisplayIcon={app}\LlamaInstanceManager.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=LlamaInstanceManager.exe
RestartApplications=no
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Files]
Source: "..\dist\LlamaInstanceManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\downloads\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{group}\llama.cpp Instance Manager"; Filename: "{app}\LlamaInstanceManager.exe"
Name: "{userdesktop}\llama.cpp Instance Manager"; Filename: "{app}\LlamaInstanceManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LlamaInstanceManager.exe"; Description: "Open llama.cpp Instance Manager"; Flags: nowait postinstall skipifsilent
Filename: "{app}\LlamaInstanceManager.exe"; Parameters: "{code:RestartParameters}"; Flags: nowait skipifnotsilent; Check: RestartManagerAfterUpdate

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "LlamaCppInstanceManager"; Flags: uninsdeletevalue dontcreatekey

[Code]
var
  ActionPage: TInputOptionWizardPage;
  ExistingInstall: Boolean;
  CanUpdate: Boolean;
  InstalledVersion: String;
  ForcedAction: String;

function RestartManagerAfterUpdate(): Boolean;
begin
  Result := ExpandConstant('{param:RESTARTMANAGER|0}') = '1';
end;

function RestartParameters(Param: String): String;
begin
  Result := '';
  if GetEnv('LLAMA_MANAGER_DATA') <> '' then
    Result := '--data-dir ' + AddQuotes(GetEnv('LLAMA_MANAGER_DATA'));
end;

function SetupAction(): String;
begin
  if not ExistingInstall then Result := 'install'
  else if ActionPage.SelectedValueIndex = 0 then Result := 'update'
  else Result := 'reinstall';
end;

function HasWebView2(): Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKLM32, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
  if not Result then
    Result := (RegQueryStringValue(HKCU, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  Existing: String;
begin
  Result := '';
  if (ForcedAction <> '') and (ForcedAction <> 'update') and (ForcedAction <> 'reinstall') then begin
    Result := 'Choose /ACTION=update or /ACTION=reinstall.';
    Exit;
  end;
  if (ForcedAction <> '') and not ExistingInstall then begin
    Result := 'No existing manager installation was found. Run setup without /ACTION for a new installation.';
    Exit;
  end;
  if (SetupAction() = 'update') and not CanUpdate then begin
    Result := 'This setup does not contain a newer version. Choose Reinstall program to repair the installed program files.';
    Exit;
  end;
  if not HasWebView2() then begin
    WizardForm.StatusLabel.Caption := 'Installing Microsoft Edge WebView2 Runtime...';
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then begin
      Result := 'Could not start WebView2 setup. Run setup again to retry.';
      Exit;
    end;
    if not HasWebView2() then begin
      Result := 'WebView2 could not be installed. Check your internet connection and run setup again.';
      Exit;
    end;
  end;
  Existing := ExpandConstant('{app}\LlamaInstanceManager.exe');
  if FileExists(Existing) then begin
    if not Exec(Existing, '--quit --background', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := 'Close the instance manager before continuing.'
    else if ExitCode <> 0 then
      Result := 'Wait for instance installation to finish, then close the manager and try again.';
  end;
end;

function InitializeUninstall(): Boolean;
var
  ExitCode: Integer;
begin
  Result := Exec(ExpandConstant('{app}\LlamaInstanceManager.exe'), '--quit --background', '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Result then Result := ExitCode = 0;
  if not Result then MsgBox('Close the instance manager after its current installation finishes, then try again.', mbError, MB_OK);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = ActionPage.ID) and not ExistingInstall) or
    ((PageID = wpSelectDir) and ExistingInstall);
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Action: String;
begin
  Action := SetupAction();
  if CurPageID = wpReady then begin
    if Action = 'update' then begin
      WizardForm.PageNameLabel.Caption := 'Ready to update';
      WizardForm.NextButton.Caption := '&Update';
      WizardForm.ReadyLabel.Caption := 'Update llama.cpp Instance Manager from ' + InstalledVersion + ' to {#AppVersion}.';
    end else if Action = 'reinstall' then begin
      WizardForm.PageNameLabel.Caption := 'Ready to reinstall';
      WizardForm.NextButton.Caption := '&Reinstall';
      WizardForm.ReadyLabel.Caption := 'Reinstall llama.cpp Instance Manager {#AppVersion} to replace missing or damaged program files.';
    end;
  end;
  if CurPageID = wpFinished then begin
    if Action = 'update' then WizardForm.FinishedHeadingLabel.Caption := 'Manager update complete'
    else if Action = 'reinstall' then WizardForm.FinishedHeadingLabel.Caption := 'Manager reinstall complete';
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := 'Setup version: {#AppVersion}' + NewLine;
  if ExistingInstall then
    Result := Result + 'Installed version: ' + InstalledVersion + NewLine + NewLine +
      'Your settings, llama.cpp instances, and models will be kept.' + NewLine +
      'The manager will close during setup. Running instances will keep running.' + NewLine;
  Result := Result + NewLine + MemoDirInfo + NewLine + MemoTasksInfo;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    Log('Setup action: ' + SetupAction() + '; installed version: ' + InstalledVersion + '; setup version: {#AppVersion}');
end;

procedure InitializeWizard();
var
  Key: String;
  Description: String;
  RegisteredPath: String;
  OldVersion: Int64;
  NewVersion: Int64;
begin
  ExistingInstall := FileExists(AddBackslash(WizardDirValue()) + 'LlamaInstanceManager.exe');
  InstalledVersion := '';
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{5E8A15A3-7C9C-47A5-A577-16CE0B45B43B}_is1';
  RegisteredPath := '';
  if not RegQueryStringValue(HKCU, Key, 'InstallLocation', RegisteredPath) then
    RegQueryStringValue(HKLM64, Key, 'InstallLocation', RegisteredPath);
  ExistingInstall := ExistingInstall or ((RegisteredPath <> '') and DirExists(RegisteredPath) and
    (CompareText(AddBackslash(RegisteredPath), AddBackslash(WizardDirValue())) = 0));
  if not RegQueryStringValue(HKCU, Key, 'DisplayVersion', InstalledVersion) then
    RegQueryStringValue(HKLM64, Key, 'DisplayVersion', InstalledVersion);
  CanUpdate := True;
  if StrToVersion(InstalledVersion, OldVersion) and StrToVersion('{#AppVersion}', NewVersion) then
    CanUpdate := ComparePackedVersion(NewVersion, OldVersion) > 0;
  if InstalledVersion = '' then InstalledVersion := 'unknown';
  Description := 'Installed version: ' + InstalledVersion + #13#10 + 'Setup version: {#AppVersion}' + #13#10 + #13#10 +
    'Both choices keep your settings, llama.cpp instances, and models. Running instances stay running.';
  if not CanUpdate then
    Description := Description + #13#10 + 'A newer version is not included in this setup. Choose Reinstall program to repair program files.';
  ActionPage := CreateInputOptionPage(wpWelcome, 'Choose setup action',
    'Update your existing installation or reinstall the program.', Description, True, False);
  ActionPage.Add('&Update existing installation');
  ActionPage.Add('&Reinstall program (replace missing or damaged program files)');
  ActionPage.CheckListBox.ItemEnabled[0] := CanUpdate;
  if CanUpdate then ActionPage.SelectedValueIndex := 0 else ActionPage.SelectedValueIndex := 1;
  ForcedAction := Lowercase(ExpandConstant('{param:ACTION|}'));
  if ForcedAction = 'reinstall' then ActionPage.SelectedValueIndex := 1;
  if ForcedAction = 'update' then ActionPage.SelectedValueIndex := 0;
  if ExistingInstall then begin
    WizardForm.WelcomeLabel1.Caption := 'llama.cpp Instance Manager is already installed';
    WizardForm.WelcomeLabel2.Caption := 'Installed version: ' + InstalledVersion + #13#10 + 'Setup version: {#AppVersion}' + #13#10 + #13#10 +
      'Choose Update existing installation or Reinstall program on the next screen.' + #13#10 + #13#10 +
      'Your settings, llama.cpp instances, and models will be kept.' + #13#10 + #13#10 + 'Manager and installer by ThatMonitorCord.';
  end else
    WizardForm.WelcomeLabel2.Caption := 'Install llama.cpp Instance Manager {#AppVersion}, then choose your server name, instance count, ports, and optional shared models folder in the manager.' + #13#10 + #13#10 +
      'Python, Git, and the preset runtime are included. Each llama.cpp instance downloads its own original LLama-GUI installation.' + #13#10 + #13#10 + 'Manager and installer by ThatMonitorCord.';
end;
