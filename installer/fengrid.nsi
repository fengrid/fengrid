; ===========================================================================
; fengrid.nsi — Windows installer for the Fengrid icon showcase
;
; Built with NSIS 3 (makensis). Works from Linux/macOS/WSL and Windows —
; see installer/README.md and installer/build.sh.
;
; The GUI asks for the configuration up front:
;   - portable install (keep everything on the drive — thumbdrive-friendly)
;   - add the launcher to PATH (standard installs only)
;   - which folders of icons (.png/.svg/.ico) to scan
; The page is served from a small local web server by default: the generated
; fengrid.cmd starts server\serve.py on the loopback interface and opens
; http://127.0.0.1:8642/ (fengrid --file opens the plain file instead).
;
; This installer never requires admin rights (HKCU registry only, user
; profile paths only). The x64 in the artifact name refers to the target
; platform; NSIS binaries are 32-bit stubs that install cleanly on x64
; Windows — fengrid itself is bitness-independent static files.
; ===========================================================================

Unicode true
ManifestDPIAware true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "WinMessages.nsh"
!include "StrFunc.nsh"
${Using:StrFunc} StrRep

!define APP_NAME "Fengrid"
!ifndef APP_VER
  !define APP_VER "unknown"
!endif
!define REG_UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\Fengrid"
!define SRV_PORT "8642"

Name "${APP_NAME} ${APP_VER}"
OutFile "..\dist\fengrid-win64-setup.exe"
InstallDir "$PROFILE\fengrid"
InstallDirRegKey HKCU "${REG_UNINST}" "InstallLocation"
Icon "fengrid.ico"
UninstallIcon "fengrid.ico"

!define MUI_ICON "fengrid.ico"
!define MUI_UNICON "fengrid.ico"
!define MUI_ABORTWARNING

; ---------------------------------------------------------------------------
; State
; ---------------------------------------------------------------------------
Var Portable          ; 1 = portable (thumbdrive) install
Var AddToPath         ; 1 = add launcher dir to user PATH (standard only)
Var PortCk            ; portable checkbox HWND
Var PathCk            ; PATH checkbox HWND
Var LB                ; icon-folder listbox HWND
Var Folders           ; |-separated selected icon folders
Var Sel               ; scratch

Function .onInit
  StrCpy $Portable 0
  StrCpy $AddToPath 1
  StrCpy $Folders ""
FunctionEnd

; ---------------------------------------------------------------------------
; Pages
; ---------------------------------------------------------------------------
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE.md"
Page custom PageConfigCreate PageConfigLeave
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchApp"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

; ---------------------------------------------------------------------------
; Configuration page: install mode + icon folders
; ---------------------------------------------------------------------------
Function PageConfigCreate
  nsDialogs::Create 1018
  Pop $0

  ${NSD_CreateLabel} 0 0 100% 26u "fengrid launches through a small local web server (loopback only) and opens http://127.0.0.1:${SRV_PORT}/. Pick the install mode and the folders of icons (.png / .svg / .ico) to scan."
  Pop $0

  ${NSD_CreateCheckbox} 0 32u 100% 12u "&Portable install — keep everything relative (run from a thumbdrive)"
  Pop $PortCk
  ${NSD_OnClick} $PortCk OnPortableClick

  ${NSD_CreateCheckbox} 0 48u 100% 12u "Add the launcher folder to my &PATH (standard installs only)"
  Pop $PathCk
  ${NSD_Check} $PathCk

  ${NSD_CreateLabel} 0 68u 100% 10u "Icon folders to scan:"
  Pop $0
  # the trailing "" is mandatory: NSD_Create* expands to an 8-argument
  # nsDialogs::CreateControl (x y w h text) — omitting text fails at
  # runtime, Pop receives "error" and the control never exists
  ${NSD_CreateListBox} 0 80u 100% 78u ""
  Pop $LB
  ${NSD_CreateButton} 0 162u 60u 14u "&Add folder..."
  Pop $0
  ${NSD_OnClick} $0 OnAddClick
  ${NSD_CreateButton} 68u 162u 60u 14u "&Remove selected"
  Pop $0
  ${NSD_OnClick} $0 OnRemoveClick

  nsDialogs::Show
FunctionEnd

Function OnPortableClick
  Pop $0
  ${NSD_GetState} $PortCk $0
  StrCpy $Portable $0
  ${If} $Portable <> 0
    EnableWindow $PathCk 0
    ${NSD_Uncheck} $PathCk
    StrCpy $INSTDIR "$EXEDIR\fengrid"
  ${Else}
    EnableWindow $PathCk 1
    StrCpy $INSTDIR "$PROFILE\fengrid"
  ${EndIf}
FunctionEnd

Function OnAddClick
  Pop $0
  nsDialogs::SelectFolderDialog "Select an icon folder to scan" "$EXEDIR"
  Pop $Sel
  ${If} $Sel != "error"
    ${If} $Folders == ""
      StrCpy $Folders $Sel
    ${Else}
      StrCpy $Folders "$Folders|$Sel"
    ${EndIf}
    ${NSD_LB_AddString} $LB $Sel
  ${EndIf}
FunctionEnd

Function OnRemoveClick
  Pop $0
  ${NSD_LB_GetSelection} $LB $Sel
  ${If} $Sel != ""
    ${NSD_LB_DelString} $LB $Sel
    ; remove the selection from the |-separated list: wrap in sentinels,
    ; replace "|sel|" with "|", then strip the sentinels
    ${StrRep} $Sel "|$Folders|" "|$Sel|" "|"
    ${If} $Sel == "|"
      StrCpy $Folders ""
    ${Else}
      StrLen $1 $Sel
      IntOp $1 $1 - 2
      StrCpy $Folders $Sel $1 1
    ${EndIf}
  ${EndIf}
FunctionEnd

Function PageConfigLeave
  ${NSD_LB_GetCount} $LB $0
  ${If} $0 = 0
    MessageBox MB_ICONEXCLAMATION "Select at least one folder of icons (.png / .svg / .ico) — the showcase has nothing to show without them."
    Abort
  ${EndIf}
  ${NSD_GetState} $PathCk $AddToPath
FunctionEnd

; ---------------------------------------------------------------------------
; Install
; ---------------------------------------------------------------------------
Section "Install"
  SetOutPath "$INSTDIR"
  File "..\index.html"
  File "fengrid.ico"
  File /r "..\fonts"
  File /r "..\server"
  File /oname=$PLUGINSDIR\win-setup-helper.ps1 "win-setup-helper.ps1"

  ; scan the chosen folders + write list.txt/list.js/icons/launcher
  DetailPrint "Scanning icon folders..."
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\win-setup-helper.ps1" -Mode scan -InstallDir "$INSTDIR" -Roots "$Folders"'
  Pop $0
  StrCmp $0 0 scan_ok scan_fail
scan_fail:
  DetailPrint "Icon scan failed (exit code $0)"
  MessageBox MB_ICONEXCLAMATION|MB_ABORTRETRYIGNORE "Scanning the icon folders failed (exit code $0).$\n$\nAbort to fix the folders, or Ignore to finish without icons (you can re-run the scan later).$\n$\nSee the install log for details." IDIGNORE scan_ok
  Abort
scan_ok:

  ${If} $Portable = 0
    ; user PATH (HKCU, REG_EXPAND_SZ to preserve %...% references)
    ${If} $AddToPath <> 0
      ReadRegStr $0 HKCU "Environment" "Path"
      ${If} $0 == ""
        StrCpy $1 "$PROFILE\.local\bin"
      ${Else}
        StrCpy $1 "$0;$PROFILE\.local\bin"
      ${EndIf}
      WriteRegExpandStr HKCU "Environment" "Path" "$1"
      SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
      DetailPrint "Added $PROFILE\.local\bin to the user PATH (new shells only)"
    ${EndIf}
    ; Start Menu shortcut + Add/Remove Programs entry
    SetShellVarContext current
    CreateDirectory "$SMPROGRAMS\fengrid"
    CreateShortCut "$SMPROGRAMS\fengrid\fengrid.lnk" "$PROFILE\.local\bin\fengrid.cmd" "" "$INSTDIR\fengrid.ico"
    WriteRegStr HKCU "${REG_UNINST}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKCU "${REG_UNINST}" "DisplayVersion" "${APP_VER}"
    WriteRegStr HKCU "${REG_UNINST}" "Publisher" "fengrid"
    WriteRegStr HKCU "${REG_UNINST}" "DisplayIcon" "$INSTDIR\fengrid.ico"
    WriteRegStr HKCU "${REG_UNINST}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "${REG_UNINST}" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegDWORD HKCU "${REG_UNINST}" "NoModify" 1
    WriteRegDWORD HKCU "${REG_UNINST}" "NoRepair" 1
    WriteUninstaller "$INSTDIR\uninstall.exe"
  ${EndIf}
SectionEnd

Function LaunchApp
  ${If} $Portable = 0
    Exec '"$PROFILE\.local\bin\fengrid.cmd"'
  ${Else}
    Exec '"$INSTDIR\fengrid.cmd"'
  ${EndIf}
FunctionEnd

; ---------------------------------------------------------------------------
; Uninstall (standard installs; portable installs are deleted by hand)
; ---------------------------------------------------------------------------
Section "Uninstall"
  File /oname=$PLUGINSDIR\win-setup-helper.ps1 "win-setup-helper.ps1"
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\win-setup-helper.ps1" -Mode uninstall -InstallDir "$INSTDIR"'
  Pop $0

  Delete "$INSTDIR\index.html"
  Delete "$INSTDIR\list.txt"
  Delete "$INSTDIR\list.js"
  Delete "$INSTDIR\server-state.js"
  Delete "$INSTDIR\meta.js"
  Delete "$INSTDIR\meta-state.tsv"
  Delete "$INSTDIR\fengrid.cmd"
  Delete "$INSTDIR\fengrid.ico"
  RMDir /r "$INSTDIR\icons"
  RMDir /r "$INSTDIR\fonts"
  RMDir /r "$INSTDIR\server"
  RMDir /r "$SMPROGRAMS\fengrid"
  DeleteRegKey HKCU "${REG_UNINST}"
  RMDir "$INSTDIR"
SectionEnd
