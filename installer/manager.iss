#ifndef AppVersion
  #define AppVersion "0.2.0"
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
Filename: "{app}\LlamaInstanceManager.exe"; Description: "Set up or open your llama.cpp instances"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "LlamaCppInstanceManager"; Flags: uninsdeletevalue dontcreatekey

[Code]
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

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption := 'Install the manager, then choose your server name, instance count, ports, and optional shared models folder in the setup wizard.' + #13#10 + #13#10 + 'Python, Git, and the preset runtime are included. Each llama.cpp instance downloads its own original LLama-GUI installation.';
end;
