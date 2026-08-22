; Installeur Windows de DubPack Creator.
; Construit depuis macOS ou Windows avec makensis:
;   makensis -DVERSION=2.0.0 -DSTAGE=build/windows-stage installer/windows.nsi
;
; Installation par utilisateur (pas de droits administrateur), dans
; %LOCALAPPDATA%\DubPackCreator. Les projets, modèles et réglages vivent au
; même endroit et survivent aux mises à jour comme à la désinstallation.

Unicode true
!include "MUI2.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef STAGE
  !define STAGE "build\windows-stage"
!endif

Name "DubPack Creator"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\DubPackCreator"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"

!define MUI_WELCOMEPAGE_TITLE "DubPack Creator ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "Cet assistant installe DubPack Creator, le créateur de dub packs pour The Choicer Voicer.$\r$\n$\r$\nAu premier lancement, l'application télécharge ses composants (quelques minutes). Ensuite, elle se met à jour toute seule.$\r$\n$\r$\nClique sur Suivant pour continuer."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\DubPack Creator.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Lancer DubPack Creator maintenant"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "French"

Section "DubPack Creator" SecMain
  SectionIn RO

  ; Ferme proprement une instance en cours avant de remplacer ses fichiers.
  IfFileExists "$INSTDIR\DubPack Creator.exe" 0 +2
    ExecWait '"$INSTDIR\DubPack Creator.exe" --quit'

  SetOutPath "$INSTDIR"
  File "/oname=DubPack Creator.exe" "${LAUNCHER}"

  SetOutPath "$INSTDIR\code"
  File /r "${STAGE}\code\*"

  SetOutPath "$INSTDIR\python"
  File /r "${STAGE}\python\*"

  SetOutPath "$INSTDIR\bin"
  File /r "${STAGE}\bin\*"

  SetOutPath "$INSTDIR"

  ; Raccourcis
  CreateDirectory "$SMPROGRAMS\DubPack Creator"
  CreateShortCut "$SMPROGRAMS\DubPack Creator\DubPack Creator.lnk" "$INSTDIR\DubPack Creator.exe"
  CreateShortCut "$DESKTOP\DubPack Creator.lnk" "$INSTDIR\DubPack Creator.exe"

  ; Désinstallation
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DubPackCreator" \
    "DisplayName" "DubPack Creator"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DubPackCreator" \
    "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DubPackCreator" \
    "Publisher" "evanthifagne"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DubPackCreator" \
    "DisplayIcon" "$INSTDIR\DubPack Creator.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DubPackCreator" \
    "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DubPackCreator" \
    "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DubPackCreator" \
    "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DubPackCreator" \
    "NoRepair" 1
SectionEnd

Section "Uninstall"
  IfFileExists "$INSTDIR\DubPack Creator.exe" 0 +2
    ExecWait '"$INSTDIR\DubPack Creator.exe" --quit'

  Delete "$INSTDIR\DubPack Creator.exe"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\launcher.json"
  Delete "$INSTDIR\launcher.log"
  Delete "$INSTDIR\server.log"
  RMDir /r "$INSTDIR\code"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\bin"
  RMDir /r "$INSTDIR\update"
  ; Les projets, modèles téléchargés et réglages restent volontairement:
  ; une réinstallation les retrouvera tels quels.
  RMDir "$INSTDIR"

  Delete "$DESKTOP\DubPack Creator.lnk"
  Delete "$SMPROGRAMS\DubPack Creator\DubPack Creator.lnk"
  RMDir "$SMPROGRAMS\DubPack Creator"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DubPackCreator"

  IfFileExists "$INSTDIR\projects\*.*" 0 +2
    MessageBox MB_OK "Tes projets et modèles ont été conservés dans :$\r$\n$INSTDIR$\r$\n$\r$\nSupprime ce dossier à la main si tu veux tout effacer."
SectionEnd
