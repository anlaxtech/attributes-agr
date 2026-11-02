; Установщик плагина «АтрибутыАГР» для Revit 2020–2026.
; Нужен Inno Setup 6 (бесплатный): https://jrsoftware.org/isdl.php
; 1) Соберите плагин под все версии: plugin\RevitAIClassifier\build_all.bat
;    (или только нужные: dotnet build -c Release -p:RevitVersion=2023).
; 2) Адрес сервера: поменяйте DefaultUrl ниже или передайте при сборке:
;    iscc /DDefaultUrl=http://my-server:8765 /DAppVer=1.4 RevitAIClassifier.iss
; 3) (по желанию) положите рядом company_settings.json — «Экспорт настроек» из плагина.
; Установщик ставит плагин в те версии Revit, которые найдёт на компьютере.
; Версии, для которых dll не собрана, пропускаются (сборка установщика при этом не падает).

#define AppName "АтрибутыАГР для Revit"
#ifndef AppVer
  #define AppVer "1.4"
#endif
#ifndef DefaultUrl
  #define DefaultUrl "http://SERVER:8765"
#endif
#ifndef Publisher
  #define Publisher "AtributyAGR"
#endif
#define Bin "..\RevitAIClassifier\bin\Release"
#define Addin "..\RevitAIClassifier\RevitAIClassifier.addin"

[Setup]
AppId={{6F1E2B7A-4C3D-4E8F-9A1B-2C3D4E5F6A7B}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher={#Publisher}
DefaultDirName={userappdata}\Autodesk\Revit\Addins
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=AtributyAGR_Revit2020-2026_Setup_{#AppVer}
Compression=lzma2
SolidCompression=yes
UninstallDisplayName={#AppName}
WizardStyle=modern

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
ru.WelcomeLabel2=Будет установлен плагин «АтрибутыАГР» — заполнение параметров АГР — во все найденные версии Revit 2020–2026.%n%nПеред установкой ЗАКРОЙТЕ Revit.

[Files]
; dll ставится, только если Revit этой версии установлен и dll собрана; .addin — только если dll на месте
Source: "{#Bin}\R2020\RevitAIClassifier.dll"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2020\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasRevit('2020')
Source: "{#Addin}"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2020"; Flags: ignoreversion; Check: HasPlugin('2020')
Source: "company_settings.json"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2020\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasPlugin('2020')
Source: "{#Bin}\R2021\RevitAIClassifier.dll"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2021\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasRevit('2021')
Source: "{#Addin}"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2021"; Flags: ignoreversion; Check: HasPlugin('2021')
Source: "company_settings.json"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2021\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasPlugin('2021')
Source: "{#Bin}\R2022\RevitAIClassifier.dll"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2022\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasRevit('2022')
Source: "{#Addin}"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2022"; Flags: ignoreversion; Check: HasPlugin('2022')
Source: "company_settings.json"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2022\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasPlugin('2022')
Source: "{#Bin}\R2023\RevitAIClassifier.dll"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2023\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasRevit('2023')
Source: "{#Addin}"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2023"; Flags: ignoreversion; Check: HasPlugin('2023')
Source: "company_settings.json"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2023\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasPlugin('2023')
Source: "{#Bin}\R2024\RevitAIClassifier.dll"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2024\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasRevit('2024')
Source: "{#Addin}"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2024"; Flags: ignoreversion; Check: HasPlugin('2024')
Source: "company_settings.json"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2024\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasPlugin('2024')
Source: "{#Bin}\R2025\RevitAIClassifier.dll"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2025\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasRevit('2025')
Source: "{#Addin}"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2025"; Flags: ignoreversion; Check: HasPlugin('2025')
Source: "company_settings.json"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2025\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasPlugin('2025')
Source: "{#Bin}\R2026\RevitAIClassifier.dll"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2026\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasRevit('2026')
Source: "{#Addin}"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2026"; Flags: ignoreversion; Check: HasPlugin('2026')
Source: "company_settings.json"; DestDir: "{userappdata}\Autodesk\Revit\Addins\2026\RevitAIClassifier"; Flags: ignoreversion skipifsourcedoesntexist; Check: HasPlugin('2026')

[UninstallDelete]
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\20*\RevitAIClassifier\service_url.txt"

[Code]
var
  UrlPage: TInputQueryWizardPage;

{ Revit этой версии установлен? }
function HasRevit(Year: String): Boolean;
begin
  Result := DirExists(ExpandConstant('{commonpf64}\Autodesk\Revit ' + Year));
end;

{ dll плагина для этой версии уже на месте (установлена строкой выше) }
function HasPlugin(Year: String): Boolean;
begin
  Result := HasRevit(Year) and FileExists(ExpandConstant('{userappdata}\Autodesk\Revit\Addins\' + Year + '\RevitAIClassifier\RevitAIClassifier.dll'));
end;

function InitializeSetup(): Boolean;
var
  Y, Found: Integer;
begin
  Found := 0;
  for Y := 2020 to 2026 do
    if HasRevit(IntToStr(Y)) then Found := Found + 1;
  if Found = 0 then
    MsgBox('Не найдено ни одной поддерживаемой версии Revit (2020–2026). Плагин всё равно можно установить позже.', mbInformation, MB_OK);
  Result := True;
end;

procedure InitializeWizard;
begin
  UrlPage := CreateInputQueryPage(wpWelcome, 'Сервер АтрибутыАГР', 'Адрес сервиса предсказаний',
    'Адрес сервера компании, на котором работает сервис АтрибутыАГР. Если не знаете — уточните у BIM-менеджера.');
  UrlPage.Add('Адрес:', False);
  UrlPage.Values[0] := '{#DefaultUrl}';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Y: Integer;
  Dir: String;
begin
  if CurStep = ssPostInstall then
    for Y := 2020 to 2026 do
    begin
      Dir := ExpandConstant('{userappdata}\Autodesk\Revit\Addins\' + IntToStr(Y) + '\RevitAIClassifier');
      if DirExists(Dir) then
        SaveStringToFile(Dir + '\service_url.txt', Trim(UrlPage.Values[0]), False);
    end;
end;
