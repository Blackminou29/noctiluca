#!/bin/bash
# Construit l'image disque macOS de Noctiluca, sur un Mac.
#
# Depuis la racine du projet :
#
#     bash packaging/construire-macos.sh
#
# Étapes, chacune arrêtant tout si elle échoue :
#
#   1. un environnement Python neuf (build/venv-macos), aux versions exactes
#      de packaging/requirements-construction.txt ;
#   2. les icônes, tirées du dessin de l'application (build/icones) ;
#   3. PyInstaller : build/dist/Noctiluca.app ;
#   4. l'autovérification de l'application construite (--self-test) ;
#   5. la signature et la notarisation, si les variables ci-dessous sont
#      posées ;
#   6. l'image disque : build/paquets/Noctiluca-<version>-macos-<arch>.dmg.
#
# Le paquet vaut pour le processeur du Mac qui construit (arm64 pour un Mac
# Apple Silicon, x86_64 pour un Mac Intel) : numba et llvmlite ne
# s'installent pas en « universal2 ».
#
# Signature et notarisation (programme développeur d'Apple). Sans elles,
# macOS refuse d'ouvrir l'application téléchargée tant que l'utilisateur ne
# l'a pas autorisée dans Réglages Système ▸ Confidentialité et sécurité.
#
#   MACOS_SIGN_IDENTITY   « Developer ID Application: Nom (ÉQUIPE) »,
#                         certificat présent dans le trousseau ;
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD
#                         compte, équipe et mot de passe d'application
#                         pour notarytool (les trois, ou aucun).
#
# PYTHON désigne l'interpréteur de base (python3.13 par défaut).

set -euo pipefail

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RACINE"

PYTHON="${PYTHON:-python3.13}"
BUILD="$RACINE/build"
VENV="$BUILD/venv-macos"
APP="$BUILD/dist/Noctiluca.app"
ICONES="$BUILD/icones"
PAQUETS="$BUILD/paquets"
ARCH="$(uname -m)"

etape() { printf '\n\033[35m== %s\033[0m\n' "$1"; }

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' delugeapp/__init__.py)"
[ -n "$VERSION" ] || { echo "version introuvable" >&2; exit 1; }
echo "Noctiluca $VERSION ($ARCH)"

# Rien de la construction n'écrit dans la configuration réelle.
ISOLEE="$(mktemp -d -t noctiluca-construction)"
export NOCTILUCA_CONFIG="$ISOLEE"
trap 'rm -rf "$ISOLEE"' EXIT

etape "Environnement de construction ($VENV)"
[ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check -q \
    -r packaging/requirements-construction.txt

etape "Icônes"
"$VENV/bin/python" packaging/icones.py "$ICONES"

etape "PyInstaller"
export NOCTILUCA_ICONES="$ICONES"
"$VENV/bin/python" -m PyInstaller --noconfirm --clean --log-level WARN \
    --distpath "$BUILD/dist" --workpath "$BUILD/pyinstaller" \
    packaging/noctiluca.spec

etape "Autovérification de l'application construite"
RAPPORT="$BUILD/autotest-macos.txt"
# Lancée hors de la racine du projet : numba y prendrait
# delugeapp/core/dsp.py pour la source du paquet, et rangerait son cache dans
# celui des sources.
if ! (cd "$BUILD" && "$APP/Contents/MacOS/Noctiluca" --self-test "$RAPPORT"); then
    cat "$RAPPORT"
    echo "l'application construite a échoué à son autovérification" >&2
    exit 1
fi
cat "$RAPPORT"

if [ -n "${MACOS_SIGN_IDENTITY:-}" ] && [ -n "${APPLE_ID:-}" ]; then
    etape "Notarisation"
    ZIP="$BUILD/Noctiluca-notarisation.zip"
    ditto -c -k --keepParent "$APP" "$ZIP"
    xcrun notarytool submit "$ZIP" --wait \
        --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_PASSWORD"
    xcrun stapler staple "$APP"
    rm -f "$ZIP"
fi

etape "Image disque"
mkdir -p "$PAQUETS"
DMG="$PAQUETS/Noctiluca-$VERSION-macos-$ARCH.dmg"
SCENE="$BUILD/dmg"
rm -rf "$SCENE" "$DMG"
mkdir -p "$SCENE"
ditto "$APP" "$SCENE/Noctiluca.app"
ln -s /Applications "$SCENE/Applications"
hdiutil create -volname "Noctiluca $VERSION" -srcfolder "$SCENE" \
    -ov -format UDZO "$DMG"
rm -rf "$SCENE"
if [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
    codesign --sign "$MACOS_SIGN_IDENTITY" --timestamp "$DMG"
fi

etape "Terminé : $DMG ($(du -h "$DMG" | cut -f1))"
