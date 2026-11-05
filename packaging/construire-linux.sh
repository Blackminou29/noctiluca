#!/bin/bash
# Construit l'AppImage Linux de Noctiluca, sur un Linux x86_64.
#
# Depuis la racine du projet :
#
#     bash packaging/construire-linux.sh
#
# Étapes, chacune arrêtant tout si elle échoue :
#
#   1. un environnement Python neuf (build/venv-linux), aux versions exactes
#      de packaging/requirements-construction.txt ;
#   2. les icônes, tirées du dessin de l'application (build/icones) ;
#   3. PyInstaller : build/dist/Noctiluca ;
#   4. l'autovérification de l'application construite (--self-test) ;
#   5. l'AppImage, un fichier unique qui se lance sur la plupart des
#      distributions : build/paquets/Noctiluca-<version>-linux-x86_64.AppImage,
#      autovérifiée elle aussi ; et une archive .tar.gz du même dossier.
#
# Une AppImage emporte les bibliothèques du système qui la construit,
# hormis la bibliothèque C : elle se lance sur les distributions dont la
# glibc est au moins aussi récente. Construire sur la plus ancienne qu'on
# veut servir — Ubuntu 22.04 couvre Debian 12, Ubuntu 22.04 et suivantes,
# Fedora 36 et suivantes.
#
# Paquets système nécessaires à la construction (Debian, Ubuntu) :
#
#     sudo apt install python3.13-venv libportaudio2 libxcb-cursor0 \
#         libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
#         libxcb-randr0 libxcb-render-util0 libxcb-shape0 libegl1 file
#
# (les bibliothèques xcb sont emportées dans l'AppImage ; PortAudio non :
# chez l'utilisateur, l'écoute demande le paquet libportaudio2, présent
# dans toutes les distributions, et l'application vit muette sans lui.)
#
# PYTHON désigne l'interpréteur de base (python3.13 par défaut).

set -euo pipefail

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RACINE"

PYTHON="${PYTHON:-python3.13}"
BUILD="$RACINE/build"
VENV="$BUILD/venv-linux"
DIST="$BUILD/dist/Noctiluca"
ICONES="$BUILD/icones"
PAQUETS="$BUILD/paquets"
OUTILS="$BUILD/outils"
ARCH="$(uname -m)"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"

etape() { printf '\n\033[35m== %s\033[0m\n' "$1"; }

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' delugeapp/__init__.py)"
[ -n "$VERSION" ] || { echo "version introuvable" >&2; exit 1; }
echo "Noctiluca $VERSION ($ARCH)"

# Rien de la construction n'écrit dans la configuration réelle.
ISOLEE="$(mktemp -d)"
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

autoverifier() {
    # Lancée hors de la racine du projet : numba y prendrait
    # delugeapp/core/dsp.py pour la source du paquet, et rangerait son cache
    # dans celui des sources.
    local rapport="$1"; shift
    if ! (cd "$BUILD" && QT_QPA_PLATFORM=offscreen "$@" --self-test "$rapport"); then
        cat "$rapport"
        echo "échec de l'autovérification : $*" >&2
        exit 1
    fi
    cat "$rapport"
}

etape "Autovérification de l'application construite"
autoverifier "$BUILD/autotest-linux.txt" "$DIST/Noctiluca"

etape "AppImage"
mkdir -p "$OUTILS" "$PAQUETS"
OUTIL="$OUTILS/appimagetool-$ARCH.AppImage"
if [ ! -x "$OUTIL" ]; then
    curl -fsSL -o "$OUTIL" "$APPIMAGETOOL_URL"
    chmod +x "$OUTIL"
fi
APPDIR="$BUILD/Noctiluca.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/512x512/apps"
cp -a "$DIST" "$APPDIR/usr/lib/noctiluca"
install -m 755 packaging/linux/AppRun "$APPDIR/AppRun"
cp packaging/linux/noctiluca.desktop "$APPDIR/noctiluca.desktop"
cp packaging/linux/noctiluca.desktop "$APPDIR/usr/share/applications/"
cp "$ICONES/noctiluca.png" "$APPDIR/noctiluca.png"
cp "$ICONES/noctiluca.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/"
APPIMAGE="$PAQUETS/Noctiluca-$VERSION-linux-$ARCH.AppImage"
# Sans FUSE (machine de construction, conteneur), l'outil se déplie seul.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$OUTIL" --no-appstream \
    "$APPDIR" "$APPIMAGE"
rm -rf "$APPDIR"

etape "Autovérification de l'AppImage"
APPIMAGE_EXTRACT_AND_RUN=1 autoverifier "$BUILD/autotest-appimage.txt" "$APPIMAGE"

etape "Archive"
ARCHIVE="$PAQUETS/Noctiluca-$VERSION-linux-$ARCH.tar.gz"
tar -C "$BUILD/dist" -czf "$ARCHIVE" Noctiluca

etape "Terminé"
ls -lh "$APPIMAGE" "$ARCHIVE"
