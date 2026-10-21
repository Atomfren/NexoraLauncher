; Установщик NexoraLauncher (Inno Setup 6)
;
; Сборка: python scripts/build.py --installer
; или вручную: ISCC.exe /DAppVersion=1.5.0 installer\nexora.iss  (после python scripts/build.py)
;
; Ставится для текущего пользователя в %LOCALAPPDATA%\Programs\NexoraLauncher, без прав администратора:
; автообновление лаунчера копирует новые файлы прямо в папку программы, и она должна быть доступна на запись.
; Данные пользователя (%LOCALAPPDATA%\nexoralauncher: сборки, миры, аккаунты) при удалении по умолчанию остаются.

#ifndef AppVersion
  #error Передайте версию: ISCC /DAppVersion=X.Y.Z installer\nexora.iss
#endif

#define AppName "NexoraLauncher"
#define AppTitle "Nexora"
#define AppExe "NexoraLauncher.exe"
#define AppUrl "https://github.com/Atomfren/NexoraLauncher"

[Setup]
; Постоянный AppId: по нему новая версия ставится поверх старой, а не рядом
AppId={{6E1C2A7B-4F3D-4C8E-9B2A-1D5E7F9A3C42}
AppName={#AppTitle}
AppVersion={#AppVersion}
AppVerName={#AppTitle} {#AppVersion}
AppPublisher=Atomfren
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppTitle}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename={#AppName}-{#AppVersion}-setup
SetupIconFile=..\resources\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppTitle}
LicenseFile=..\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.DeleteData=Удалить также сборки, миры, аккаунты и настройки Nexora?%n%nПапка: %1%n%nЕсли собираетесь поставить лаунчер заново, ответьте «Нет».
english.DeleteData=Also delete Nexora builds, worlds, accounts and settings?%n%nFolder: %1%n%nAnswer “No” if you plan to reinstall the launcher.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppTitle}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppTitle}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppTitle}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppTitle}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Автообновление добавляет файлы, о которых установщик не знает, — убираем папку программы целиком
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\nexoralauncher');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox(FmtMessage(CustomMessage('DeleteData'), [DataDir]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
