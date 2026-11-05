; Noctiluca — l'installateur Windows (NSIS 3, interface moderne).
;
; Ne se compile pas seul : packaging\construire-windows.ps1 construit
; d'abord l'application (PyInstaller), puis appelle
;
;   makensis /INPUTCHARSET UTF8 /DVERSION=1.0.0 /DVERSION_WIN=1.0.0.0
;            /DSOURCE=build\dist\Noctiluca /DICONES=build\icones
;            /DSORTIE=build\paquets\Noctiluca-1.0.0-windows-x64-setup.exe
;            [/DLICENCE=LICENSE.txt] packaging\windows\noctiluca.nsi
;
; /INPUTCHARSET UTF8 est indispensable : ce fichier est en UTF-8 sans BOM,
; et NSIS le lirait sinon dans le jeu de caractères de Windows.
;
; Ce que l'installateur fait :
;   * installe pour tous les utilisateurs, dans Program Files (64 bits) ;
;   * parle français sous un Windows français, anglais ailleurs ;
;   * se met à jour par-dessus une version précédente, au même endroit, en
;     retirant d'abord ses anciennes bibliothèques ;
;   * refuse d'écrire tant que Noctiluca est ouvert ;
;   * relance Noctiluca, s'il est demandé, **sans** les droits
;     d'administrateur : une fenêtre élevée ne reçoit plus les fichiers
;     glissés depuis l'Explorateur.
;
; Ce que le désinstallateur ne fait jamais : toucher aux données de
; l'utilisateur (%APPDATA%\Noctiluca : réglages, index, sauvegardes de la
; carte, copie de travail). Il ne retire que ce que l'installateur a posé,
; fichier par fichier — jamais « tout le dossier », qui pourrait être celui
; qu'un utilisateur a choisi par erreur.

Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!macro EXIGER nom
  !ifndef ${nom}
    !error "Paramètre manquant : /D${nom}=... (voir l'en-tête de ce fichier)"
  !endif
!macroend
!insertmacro EXIGER VERSION
!insertmacro EXIGER VERSION_WIN
!insertmacro EXIGER SOURCE
!insertmacro EXIGER ICONES
!insertmacro EXIGER SORTIE

!define NOM "Noctiluca"
!define EDITEUR "Sébastien Abalain"
!define EXE "Noctiluca.exe"
!define DESINSTALLATEUR "uninstall.exe"
!define CLE "Software\Microsoft\Windows\CurrentVersion\Uninstall\${NOM}"

Name "${NOM}"
OutFile "${SORTIE}"
InstallDir "$PROGRAMFILES64\${NOM}"
RequestExecutionLevel admin
BrandingText "${NOM} ${VERSION}"

VIProductVersion "${VERSION_WIN}"
VIAddVersionKey /LANG=0 "ProductName" "${NOM}"
VIAddVersionKey /LANG=0 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=0 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=0 "CompanyName" "${EDITEUR}"
VIAddVersionKey /LANG=0 "FileDescription" "${NOM} ${VERSION} (installation)"
VIAddVersionKey /LANG=0 "LegalCopyright" "© ${EDITEUR}"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "FileFunc.nsh"

; --------------------------------------------------------------------------
; Pages
; --------------------------------------------------------------------------

!define MUI_ICON "${ICONES}\noctiluca.ico"
!define MUI_UNICON "${ICONES}\noctiluca.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${ICONES}\installateur.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${ICONES}\installateur.bmp"
!define MUI_ABORTWARNING
!define MUI_COMPONENTSPAGE_NODESC

!insertmacro MUI_PAGE_WELCOME
!ifdef LICENCE
  !insertmacro MUI_PAGE_LICENSE "${LICENCE}"
!endif
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE VerifierFermee
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION Lancer
!insertmacro MUI_PAGE_FINISH

!define MUI_UNCONFIRMPAGE_TEXT_TOP "$(DonneesGardees)"
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; La première langue est celle d'un Windows qui n'est pas en français.
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "French"

; --------------------------------------------------------------------------
; Textes
; --------------------------------------------------------------------------

LangString SectionApp ${LANG_ENGLISH} "${NOM} (required)"
LangString SectionApp ${LANG_FRENCH} "${NOM} (indispensable)"
LangString SectionBureau ${LANG_ENGLISH} "Desktop shortcut"
LangString SectionBureau ${LANG_FRENCH} "Raccourci sur le Bureau"
LangString WindowsTropAncien ${LANG_ENGLISH} \
  "${NOM} requires Windows 10 or later, 64-bit."
LangString WindowsTropAncien ${LANG_FRENCH} \
  "${NOM} demande Windows 10 ou plus récent, en 64 bits."
LangString EncoreOuvert ${LANG_ENGLISH} \
  "${NOM} is running.$\r$\n$\r$\nClose it, then click Retry."
LangString EncoreOuvert ${LANG_FRENCH} \
  "${NOM} est ouvert.$\r$\n$\r$\nFermez-le, puis cliquez sur Recommencer."
LangString DonneesGardees ${LANG_ENGLISH} \
  "${NOM} will be removed from the folder below. Your settings, index and \
  card backups, in %APPDATA%\${NOM}, are left untouched."
LangString DonneesGardees ${LANG_FRENCH} \
  "${NOM} va être retiré du dossier ci-dessous. Vos réglages, votre index \
  et les sauvegardes de votre carte, dans %APPDATA%\${NOM}, ne sont pas \
  touchés."

; --------------------------------------------------------------------------
; Fonctions
; --------------------------------------------------------------------------

; Noctiluca ouvert tient son exécutable : l'ouvrir en écriture échoue.
!macro VERIFIER_FERMEE un
Function ${un}VerifierFermee
  ${If} ${FileExists} "$INSTDIR\${EXE}"
    encore:
    ClearErrors
    FileOpen $0 "$INSTDIR\${EXE}" a
    ${If} ${Errors}
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(EncoreOuvert)" \
        /SD IDCANCEL IDRETRY encore
      Abort
    ${EndIf}
    FileClose $0
  ${EndIf}
FunctionEnd
!macroend
!insertmacro VERIFIER_FERMEE ""
!insertmacro VERIFIER_FERMEE "un."

Function .onInit
  ${IfNot} ${RunningX64}
  ${OrIfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "$(WindowsTropAncien)" /SD IDOK
    Abort
  ${EndIf}
  ; Une version déjà installée : la mise à jour se fait au même endroit.
  SetRegView 64
  ReadRegStr $0 HKLM "${CLE}" "InstallLocation"
  ${If} $0 != ""
    StrCpy $INSTDIR $0
  ${EndIf}
FunctionEnd

; Par l'Explorateur, qui tourne sans élévation : lancé directement,
; Noctiluca hériterait des droits d'administrateur de l'installateur.
Function Lancer
  Exec '"$WINDIR\explorer.exe" "$INSTDIR\${EXE}"'
FunctionEnd

Function un.onInit
  SetRegView 64
  Call un.VerifierFermee
FunctionEnd

; --------------------------------------------------------------------------
; Installation
; --------------------------------------------------------------------------

Section "$(SectionApp)" SectionApp
  SectionIn RO
  SetShellVarContext all
  SetOutPath "$INSTDIR"

  ; Une mise à jour : les bibliothèques de la version précédente partent
  ; d'abord, sans quoi un fichier retiré du paquet resterait.
  ${If} ${FileExists} "$INSTDIR\${EXE}"
    RMDir /r "$INSTDIR\_internal"
  ${EndIf}

  File "${SOURCE}\${EXE}"
  File /r "${SOURCE}\_internal"
  WriteUninstaller "$INSTDIR\${DESINSTALLATEUR}"

  CreateShortCut "$SMPROGRAMS\${NOM}.lnk" "$INSTDIR\${EXE}"

  WriteRegStr HKLM "${CLE}" "DisplayName" "${NOM}"
  WriteRegStr HKLM "${CLE}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${CLE}" "Publisher" "${EDITEUR}"
  WriteRegStr HKLM "${CLE}" "DisplayIcon" "$INSTDIR\${EXE},0"
  WriteRegStr HKLM "${CLE}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${CLE}" "UninstallString" \
    '"$INSTDIR\${DESINSTALLATEUR}"'
  WriteRegStr HKLM "${CLE}" "QuietUninstallString" \
    '"$INSTDIR\${DESINSTALLATEUR}" /S'
  WriteRegDWORD HKLM "${CLE}" "NoModify" 1
  WriteRegDWORD HKLM "${CLE}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${CLE}" "EstimatedSize" "$0"
SectionEnd

Section "$(SectionBureau)" SectionBureau
  SetShellVarContext all
  CreateShortCut "$DESKTOP\${NOM}.lnk" "$INSTDIR\${EXE}"
SectionEnd

; --------------------------------------------------------------------------
; Désinstallation : ce que l'installateur a posé, rien d'autre.
; --------------------------------------------------------------------------

Section "Uninstall"
  SetShellVarContext all
  Delete "$SMPROGRAMS\${NOM}.lnk"
  Delete "$DESKTOP\${NOM}.lnk"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\${DESINSTALLATEUR}"
  ; Sans /r : le dossier ne part que s'il est vide.
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${CLE}"
SectionEnd
