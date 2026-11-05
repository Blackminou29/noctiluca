# -*- mode: python ; coding: utf-8 -*-
"""La recette PyInstaller de Noctiluca, pour les trois systèmes.

Ne se lance pas seule : les scripts ``construire-*`` de ce dossier préparent
l'environnement, les icônes et la configuration isolée, puis appellent

    pyinstaller --noconfirm --distpath build/dist --workpath build/pyinstaller packaging/noctiluca.spec

Le résultat est un **dossier** (``build/dist/Noctiluca``), pas un exécutable
unique : un exécutable unique se décompresse à chaque lancement (plusieurs
secondes pour 300 Mo), se fait plus souvent soupçonner par les antivirus, et
empêcherait de remplacer les bibliothèques Qt, ce que la LGPL de Qt
demande de permettre. Sous macOS, le dossier est emballé en
``Noctiluca.app``.

Ce que l'analyse de PyInstaller ne voit pas, et qui est donc nommé ici :

* les modules du paquet, tous, par leurs fichiers : le catalogue anglais
  s'importe par son nom (``i18n/en/__init__.py``), et ``collect_submodules``
  importerait le paquet — donc la configuration, chez qui construit ;
* les données : les tables du firmware (``data/``) et le manuel (``docs/``),
  relus à côté des modules (``Path(__file__)``) ;
* les licences des bibliothèques emportées, que leur redistribution exige.
"""

import os
import re
import sys
from importlib import metadata
from pathlib import Path

RACINE = Path(SPECPATH).resolve().parent
PAQUET = RACINE / "delugeapp"
ICONES = Path(os.environ.get("NOCTILUCA_ICONES", RACINE / "build" / "icones"))

NOM = "Noctiluca"
VERSION = re.search(r'__version__ = "([^"]+)"',
                    (PAQUET / "__init__.py").read_text(encoding="utf-8"))[1]
#: L'identifiant macOS de l'application. Il ne doit plus changer une fois
#: l'application distribuée : macOS y attache les autorisations accordées.
IDENTIFIANT_MACOS = "fr.abalain.noctiluca"
EDITEUR = "Sébastien Abalain"

#: Les traductions de Qt emportées : celles des langues de l'interface que
#: Qt ne parle pas d'office (``main._translate_qt``). Les 11 Mo de toutes
#: les autres langues restent dehors.
LANGUES_QT = ("fr",)

#: Les distributions dont la licence accompagne le paquet.
DISTRIBUTIONS = ("PyQt6", "PyQt6-Qt6", "PyQt6-sip", "numpy", "numba",
                 "llvmlite", "sounddevice", "cffi", "pycparser")


def _modules():
    """Les modules du paquet, lus sur le disque sans rien importer."""
    for fichier in sorted(PAQUET.rglob("*.py")):
        parties = fichier.relative_to(RACINE).with_suffix("").parts
        if parties[-1] == "__init__":
            parties = parties[:-1]
        yield ".".join(parties)


def _licences():
    """Les fichiers de licence des bibliothèques, et celle de Python.

    Seulement ceux des métadonnées (``*.dist-info``) : numpy range aussi des
    ``LICENSE.txt`` dans ses sous-dossiers, qui s'écraseraient l'un l'autre
    une fois réunis — celui des métadonnées les reprend tous."""
    for nom in DISTRIBUTIONS:
        for fichier in metadata.distribution(nom).files or ():
            if (fichier.parts[0].endswith(".dist-info")
                    and re.match(r"(LICEN[CS]E|COPYING|NOTICE)",
                                 fichier.name, re.I)):
                yield str(fichier.locate()), f"licences/{nom}"
    for candidat in (Path(sys.base_prefix) / "LICENSE.txt",
                     Path(sys.base_prefix) / "lib"
                     / f"python{sys.version_info[0]}.{sys.version_info[1]}"
                     / "LICENSE.txt"):
        if candidat.exists():
            yield str(candidat), "licences/Python"
            break
    yield str(Path(SPECPATH) / "AVIS-DE-TIERS.txt"), "licences"


def _garder(entree) -> bool:
    """Ce qui entre dans le paquet."""
    chemin = entree[0].replace("\\", "/")
    nom = chemin.rsplit("/", 1)[-1]
    if "/translations/" in chemin and nom.endswith(".qm"):
        return any(nom in (f"qt_{l}.qm", f"qtbase_{l}.qm") for l in LANGUES_QT)
    # PortAudio avec le pilote ASIO de Steinberg : sounddevice ne le charge
    # que sur demande (SD_ENABLE_ASIO), l'application ne la fait pas.
    return not nom.endswith("-asio.dll")


a = Analysis(
    [str(RACINE / "main.py")],
    pathex=[str(RACINE)],
    datas=[(str(PAQUET / "data"), "delugeapp/data"),
           (str(PAQUET / "docs"), "delugeapp/docs"),
           *_licences()],
    hiddenimports=list(_modules()),
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
)
a.datas = [d for d in a.datas if _garder(d)]
a.binaries = [b for b in a.binaries if _garder(b)]
pyz = PYZ(a.pure)


def _version_windows():
    """La fiche « Détails » de l'exécutable dans l'Explorateur."""
    from PyInstaller.utils.win32 import versioninfo as vi

    nombres = tuple(int(n) for n in (VERSION.split(".") + ["0"] * 4)[:4])
    return vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=nombres, prodvers=nombres),
        kids=[vi.StringFileInfo([vi.StringTable("040C04B0", [
            vi.StringStruct("CompanyName", EDITEUR),
            vi.StringStruct("FileDescription", NOM),
            vi.StringStruct("FileVersion", VERSION),
            vi.StringStruct("InternalName", NOM),
            vi.StringStruct("OriginalFilename", f"{NOM}.exe"),
            vi.StringStruct("ProductName", NOM),
            vi.StringStruct("ProductVersion", VERSION)])]),
              vi.VarFileInfo([vi.VarStruct("Translation", [0x040C, 1200])])])


if sys.platform == "win32":
    icone = str(ICONES / "noctiluca.ico")
elif sys.platform == "darwin":
    icone = str(ICONES / "noctiluca.icns")
else:
    icone = None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NOM,
    console=False,
    icon=icone,
    version=_version_windows() if sys.platform == "win32" else None,
    # UPX abîme des bibliothèques de Qt et attire les antivirus.
    upx=False,
    strip=False,
    debug=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=os.environ.get("MACOS_SIGN_IDENTITY") or None,
    entitlements_file=str(Path(SPECPATH) / "macos" / "entitlements.plist")
    if sys.platform == "darwin" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    strip=False,
    name=NOM,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NOM}.app",
        icon=icone,
        bundle_identifier=IDENTIFIANT_MACOS,
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": NOM,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHumanReadableCopyright": f"© {EDITEUR}",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.music",
            # Le texte des demandes d'accès de macOS : la carte SD, et les
            # dossiers où l'utilisateur range ses échantillons.
            "NSRemovableVolumesUsageDescription":
                "Noctiluca lit et range la carte SD de votre Deluge.",
            "NSDocumentsFolderUsageDescription":
                "Noctiluca lit les échantillons et les morceaux que vous y "
                "rangez.",
            "NSDesktopFolderUsageDescription":
                "Noctiluca lit les échantillons et les morceaux que vous y "
                "rangez.",
        },
    )
