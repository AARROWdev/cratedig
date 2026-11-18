; Cratedig installer (Inno Setup 6). Built by build.ps1, which passes /DAppVersion=<VERSION from cratedig.py>.
; Packs the PyInstaller one-folder build in build\dist\Cratedig and adds Cratedig to "Open with"
; for every audio/video type it plays. It never sets itself as anyone's default player.

#ifndef AppVersion
  #error Build with build.ps1 (it passes /DAppVersion)
#endif

#define ProgId "Cratedig.Media"
#define Exts "wav mp3 flac aiff aif m4a aac ogg oga opus wma alac ape wv mka mp4 mkv mov avi webm wmv m4v flv mpg mpeg ts m2ts 3gp vob ogv"

[Setup]
AppId={{6F1B7E0A-2C4D-4E8B-9A61-5D3C2B8F7E14}
AppName=Cratedig
AppVersion={#AppVersion}
AppVerName=Cratedig {#AppVersion}
AppPublisher=AARROWdev
AppPublisherURL=https://github.com/AARROWdev/cratedig
DefaultDirName={autopf}\Cratedig
DefaultGroupName=Cratedig
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=force
RestartApplications=no
ChangesAssociations=yes
SetupIconFile=..\cratedig.ico
UninstallDisplayIcon={app}\Cratedig.exe
UninstallDisplayName=Cratedig
OutputDir=..\dist
OutputBaseFilename=CratedigSetup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\build\dist\Cratedig\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Cratedig"; Filename: "{app}\Cratedig.exe"
Name: "{autodesktop}\Cratedig"; Filename: "{app}\Cratedig.exe"; Tasks: desktopicon

[Registry]
; ProgID
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueData: "Cratedig media file"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueData: """{app}\Cratedig.exe"",0"
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueData: """{app}\Cratedig.exe"" ""%1"""
; "Open with" list
Root: HKA; Subkey: "Software\Classes\Applications\Cratedig.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "Cratedig"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\Cratedig.exe\shell\open\command"; ValueType: string; ValueData: """{app}\Cratedig.exe"" ""%1"""
; Settings > Default apps > Cratedig
Root: HKA; Subkey: "Software\Cratedig"; Flags: uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Cratedig\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "Cratedig"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Cratedig\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "File explorer + media player"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Cratedig"; ValueData: "Software\Cratedig\Capabilities"; Flags: uninsdeletevalue
; Per-extension entries are added in [Code] (one list, kept in Exts above)

[Run]
Filename: "{app}\Cratedig.exe"; Description: "{cm:LaunchProgram,Cratedig}"; Flags: nowait postinstall skipifsilent

[Code]
function RegRoot(): Integer;
begin
  if IsAdminInstallMode then Result := HKLM else Result := HKCU;
end;

procedure EachExt(Add: Boolean);
var S, E: String; P: Integer;
begin
  S := '{#Exts}' + ' ';
  while Length(S) > 0 do begin
    P := Pos(' ', S); E := '.' + Copy(S, 1, P - 1); Delete(S, 1, P);
    if E = '.' then Continue;
    if Add then begin
      RegWriteStringValue(RegRoot, 'Software\Classes\' + E + '\OpenWithProgids', '{#ProgId}', '');
      RegWriteStringValue(RegRoot, 'Software\Classes\Applications\Cratedig.exe\SupportedTypes', E, '');
      RegWriteStringValue(RegRoot, 'Software\Cratedig\Capabilities\FileAssociations', E, '{#ProgId}');
    end else
      RegDeleteValue(RegRoot, 'Software\Classes\' + E + '\OpenWithProgids', '{#ProgId}');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then EachExt(True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then EachExt(False);
end;

// Cratedig holds "CratedigAppMutex" (and the Global\ one) while it runs. Setup closes it (CloseApplications),
// but the uninstaller doesn't, so it refuses to start until Cratedig is closed instead of leaving a half-removed folder.
function InitializeUninstall(): Boolean;
begin
  Result := True;
  while Result and CheckForMutexes('CratedigAppMutex,Global\CratedigAppMutex') do
    if UninstallSilent or (MsgBox('Cratedig is running. Close it, then click OK to uninstall.',
                                  mbError, MB_OKCANCEL) <> IDOK) then
      Result := False;
end;
