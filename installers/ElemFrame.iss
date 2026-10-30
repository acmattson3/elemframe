#ifndef AppVersion
  #define AppVersion "0.1.1"
#endif
#ifndef SourceDir
  #error SourceDir must point to an extracted Windows portable package
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef LicensePath
  #define LicensePath "..\LICENSE"
#endif

[Setup]
AppId={{0B839027-2575-4F5B-8BE3-D8A836C6DA53}
AppName=ElemFrame
AppVersion={#AppVersion}
AppPublisher=Andrew Mattson
AppPublisherURL=https://github.com/acmattson3/elemframe
AppSupportURL=https://github.com/acmattson3/elemframe/issues
DefaultDirName={localappdata}\Programs\ElemFrame
DefaultGroupName=ElemFrame
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
LicenseFile={#LicensePath}
OutputDir={#OutputDir}
OutputBaseFilename=ElemFrame-{#AppVersion}-windows-x86_64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UsePreviousTasks=yes
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\ElemFrame.exe

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: startup; Description: "Start ElemFrame when I sign in"; GroupDescription: "Startup:"; Flags: unchecked
Name: kiosk; Description: "Open ElemFrame in fullscreen kiosk mode"; GroupDescription: "Display:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "portable.txt,data\*,launch.json,install-state.json,*.pyc,*.pyo"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ElemFrame"; Filename: "{app}\ElemFrame.exe"; WorkingDir: "{app}"
Name: "{group}\Stop ElemFrame"; Filename: "{app}\ElemFrame.exe"; Parameters: "--stop --no-browser"; WorkingDir: "{app}"
Name: "{group}\Uninstall ElemFrame"; Filename: "{uninstallexe}"
Name: "{userdesktop}\ElemFrame"; Filename: "{app}\ElemFrame.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\ElemFrame"; Filename: "{app}\ElemFrame.exe"; WorkingDir: "{app}"; Tasks: startup

[InstallDelete]
Type: files; Name: "{app}\portable.txt"
Type: files; Name: "{userdesktop}\ElemFrame.lnk"; Check: not WizardIsTaskSelected('desktopicon')
Type: files; Name: "{userstartup}\ElemFrame.lnk"; Check: not WizardIsTaskSelected('startup')

[Run]
Filename: "{app}\ElemFrame.exe"; Description: "Open ElemFrame"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\launch.json"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\licenses"

[Code]
var
  DataPage: TInputDirWizardPage;

function JsonString(Value: String): String;
begin
  StringChangeEx(Value, '\', '\\', True);
  StringChangeEx(Value, '"', '\"', True);
  Result := '"' + Value + '"';
end;

function IsWithin(ChildPath, ParentPath: String): Boolean;
begin
  Result := Pos(Lowercase(AddBackslash(ExpandFileName(ParentPath))),
                Lowercase(AddBackslash(ExpandFileName(ChildPath)))) = 1;
end;

procedure InitializeWizard;
var
  Value: String;
begin
  DataPage := CreateInputDirPage(wpSelectDir, 'Media and settings',
    'Choose where ElemFrame keeps your media and settings.',
    'This folder is kept during upgrades and uninstall. Choose a folder outside the application directory.', False, '');
  DataPage.Add('Media and settings folder:');
  Value := ExpandConstant('{param:DATADIR|}');
  if Value = '' then
    Value := GetPreviousData('DataDir', ExpandConstant('{localappdata}\ElemFrame'));
  DataPage.Values[0] := Value;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DataPage.ID then begin
    if (DataPage.Values[0] = '') or IsWithin(DataPage.Values[0], WizardDirValue) or
       IsWithin(WizardDirValue, DataPage.Values[0]) then begin
      SuppressibleMsgBox('Choose a media/settings folder separate from the application directory.', mbError, MB_OK, IDOK);
      Result := False;
    end;
  end;
end;

function StopInstalled: Boolean;
var
  Code: Integer;
  ExePath: String;
begin
  Result := True;
  ExePath := ExpandConstant('{app}\ElemFrame.exe');
  if FileExists(ExePath) then begin
    Log('Stopping the installed ElemFrame launcher before changing program files.');
    Result := Exec(ExePath, '--stop --no-browser', ExpandConstant('{app}'),
                   SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if IsWithin(DataPage.Values[0], WizardDirValue) or IsWithin(WizardDirValue, DataPage.Values[0]) then
    Result := 'The media/settings folder must be separate from the application directory.'
  else if not StopInstalled then
    Result := 'ElemFrame is still busy. Finish file operations, close ElemFrame, and retry.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Lines: TArrayOfString;
  KioskValue: String;
begin
  if CurStep = ssPostInstall then begin
    if WizardIsTaskSelected('kiosk') then KioskValue := 'true' else KioskValue := 'false';
    SetArrayLength(Lines, 1);
    Lines[0] := '{"data_dir":' + JsonString(ExpandFileName(DataPage.Values[0])) + ',"kiosk":' + KioskValue + '}';
    if not SaveStringsToUTF8File(ExpandConstant('{app}\launch.json'), Lines, False) then
      RaiseException('Could not save the launcher settings.');
  end;
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'DataDir', DataPage.Values[0]);
end;

function InitializeUninstall: Boolean;
begin
  Result := StopInstalled;
  if not Result then
    SuppressibleMsgBox('ElemFrame is still busy. Finish file operations and retry uninstall.', mbError, MB_OK, IDOK);
end;
