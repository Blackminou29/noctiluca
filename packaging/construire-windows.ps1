<#
.SYNOPSIS
    Construit l'installateur Windows de Noctiluca.

.DESCRIPTION
    Depuis la racine du projet :

        powershell -ExecutionPolicy Bypass -File packaging\construire-windows.ps1

    Étapes, chacune arrêtant tout si elle échoue :

      1. un environnement Python neuf (build\venv-windows), aux versions
         exactes de packaging\requirements-construction.txt ;
      2. (avec -Tests) la suite de tests, dans cet environnement ;
      3. les icônes, tirées du dessin de l'application (build\icones) ;
      4. PyInstaller : l'application dans build\dist\Noctiluca ;
      5. l'autovérification de l'application construite
         (Noctiluca.exe --self-test) : rapport dans build\autotest-windows.txt ;
      6. NSIS : build\paquets\Noctiluca-<version>-windows-x64-setup.exe.

    La configuration de Noctiluca est déplacée dans un dossier temporaire le
    temps de la construction : rien ne touche aux réglages de qui construit.

.PARAMETER Tests
    Lance aussi la suite de tests avant d'empaqueter.

.PARAMETER Certificat
    Empreinte SHA-1 d'un certificat de signature de code installé dans le
    magasin de Windows. Avec elle, Noctiluca.exe puis l'installateur sont
    signés (signtool, du kit de développement de Windows). Sans signature,
    Windows SmartScreen avertit l'utilisateur au premier lancement.

.PARAMETER Interpreteur
    Le Python qui crée l'environnement de construction ; par défaut, le 3.13
    du lanceur « py ». La construction automatique (GitHub) donne le sien.
#>
param(
    [switch]$Tests,
    [string]$Certificat = "",
    [string]$Interpreteur = ""
)

$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot
Set-Location $Racine

$Build = Join-Path $Racine "build"
$Venv = Join-Path $Build "venv-windows"
$Python = Join-Path $Venv "Scripts\python.exe"
$Dist = Join-Path $Build "dist\Noctiluca"
$Icones = Join-Path $Build "icones"
$Paquets = Join-Path $Build "paquets"

function Etape([string]$texte) {
    Write-Host ""
    Write-Host "== $texte" -ForegroundColor Magenta
}

function Lancer([string]$quoi, [scriptblock]$commande) {
    # PyInstaller et pip écrivent leurs messages sur la sortie d'erreur :
    # sous PowerShell 5.1, avec « Stop », la première ligne passerait pour
    # une erreur. Seul le code de sortie d'un programme compte.
    $ErrorActionPreference = "Continue"
    & $commande
    if ($LASTEXITCODE -ne 0) { throw "$quoi : échec (code $LASTEXITCODE)" }
}

function Signer([string]$fichier) {
    if (-not $Certificat) { return }
    $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $signtool) {
        $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName | Select-Object -Last 1
    }
    if (-not $signtool) { throw "signtool.exe introuvable (kit de développement de Windows)" }
    Lancer "signature de $fichier" {
        & $signtool sign /sha1 $Certificat /fd sha256 /tr http://timestamp.digicert.com /td sha256 $fichier
    }
}

# La version vient du paquet, sans l'importer.
$Version = ([regex]'__version__ = "([^"]+)"').Match(
    (Get-Content (Join-Path $Racine "delugeapp\__init__.py") -Raw -Encoding UTF8)).Groups[1].Value
if (-not $Version) { throw "version introuvable dans delugeapp\__init__.py" }
$Morceaux = @($Version.Split(".") + @("0", "0", "0", "0"))[0..3]
$VersionWin = $Morceaux -join "."
Write-Host "Noctiluca $Version" -ForegroundColor Magenta

# Rien de la construction n'écrit dans la configuration réelle.
$Isolee = Join-Path ([System.IO.Path]::GetTempPath()) ("noctiluca-construction-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force $Isolee | Out-Null
$env:NOCTILUCA_CONFIG = $Isolee

try {
    Etape "Environnement de construction ($Venv)"
    if (-not (Test-Path $Python)) {
        Lancer "création de l'environnement (Python 3.13 est-il installé ?)" {
            if ($Interpreteur) { & $Interpreteur -m venv $Venv }
            else { & py -3.13 -m venv $Venv }
        }
    }
    Lancer "installation des dépendances" {
        & $Python -m pip install --disable-pip-version-check -q -r packaging\requirements-construction.txt
    }

    if ($Tests) {
        Etape "Suite de tests"
        Lancer "tests" { & $Python -m unittest discover -s tests -q }
    }

    Etape "Icônes"
    Lancer "icônes" { & $Python packaging\icones.py $Icones }

    Etape "PyInstaller"
    $env:NOCTILUCA_ICONES = $Icones
    Lancer "PyInstaller" {
        & $Python -m PyInstaller --noconfirm --clean --log-level WARN `
            --distpath (Join-Path $Build "dist") `
            --workpath (Join-Path $Build "pyinstaller") `
            packaging\noctiluca.spec
    }

    Etape "Autovérification de l'application construite"
    $Rapport = Join-Path $Build "autotest-windows.txt"
    # Lancée depuis son propre dossier, comme par le menu Démarrer : depuis
    # la racine du projet, numba prendrait delugeapp\core\dsp.py pour la
    # source du paquet et rangerait son cache dans celui des sources.
    $p = Start-Process -FilePath (Join-Path $Dist "Noctiluca.exe") -WorkingDirectory $Dist `
        -ArgumentList @("--self-test", "`"$Rapport`"") -Wait -PassThru
    Get-Content $Rapport -Encoding UTF8 | Write-Host
    if ($p.ExitCode -ne 0) { throw "l'application construite a échoué à son autovérification" }

    Signer (Join-Path $Dist "Noctiluca.exe")

    Etape "Installateur NSIS"
    $makensis = Get-Command makensis.exe -ErrorAction SilentlyContinue
    if (-not $makensis) {
        $makensis = @("${env:ProgramFiles(x86)}\NSIS\makensis.exe", "$env:ProgramFiles\NSIS\makensis.exe") |
            Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $makensis) { throw "NSIS introuvable : winget install NSIS.NSIS" }
    New-Item -ItemType Directory -Force $Paquets | Out-Null
    $Sortie = Join-Path $Paquets "Noctiluca-$Version-windows-x64-setup.exe"
    $Options = @("/V2", "/INPUTCHARSET", "UTF8",
        "/DVERSION=$Version", "/DVERSION_WIN=$VersionWin",
        "/DSOURCE=$Dist", "/DICONES=$Icones", "/DSORTIE=$Sortie")
    # La page de licence n'apparaît que si le projet a choisi la sienne.
    $Licence = @("LICENSE.txt", "LICENCE.txt", "LICENSE", "LICENCE") |
        ForEach-Object { Join-Path $Racine $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($Licence) { $Options += "/DLICENCE=$Licence" }
    Lancer "NSIS" { & $makensis @Options packaging\windows\noctiluca.nsi }
    Signer $Sortie

    $Taille = [math]::Round((Get-Item $Sortie).Length / 1MB, 1)
    Etape "Terminé : $Sortie ($Taille Mo)"
}
finally {
    Remove-Item Env:\NOCTILUCA_CONFIG -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $Isolee -ErrorAction SilentlyContinue
}
