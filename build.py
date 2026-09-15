"""
build.py
Production Build and Release Automation Script for Channel Harvest.

Performs:
1. Environment and dependency verification.
2. Multi-resolution icon generation (if missing).
3. Bundled binary staging (ffmpeg.exe, ffprobe.exe, yt-dlp.exe).
4. PyInstaller onedir freeze with version metadata and resources.
5. Runtime binaries deployment to distribution bundle.
6. Standalone portable ZIP creation (ChannelHarvest-Portable-v<version>.zip).
7. Inno Setup installer compilation (ChannelHarvest-Setup-v<version>.exe).
8. SHA-256 checksum generation (SHA256SUMS.txt).
"""

import os
import sys
import shutil
import hashlib
import zipfile
import argparse
import subprocess
from pathlib import Path
from typing import Optional, List, Dict

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.version import __version__, __app_name__


def print_step(step_name: str) -> None:
    print("\n" + "=" * 70)
    print(f">> {step_name}")
    print("=" * 70)


def print_success(msg: str) -> None:
    print(f"[SUCCESS] {msg}")


def print_error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def calculate_sha256(file_path: Path) -> str:
    """Calculates SHA-256 hexadecimal digest for a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_inno_setup() -> Optional[Path]:
    """Locates ISCC.exe compiler."""
    # 1. System PATH
    iscc_path = shutil.which("ISCC.exe") or shutil.which("iscc")
    if iscc_path:
        return Path(iscc_path)

    # 2. Common Windows locations
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path("C:/Users/Admin/AppData/Local/Programs/Inno Setup 6/ISCC.exe"),
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def ensure_icon() -> None:
    """Ensures multi-resolution ChannelHarvest.ico exists."""
    ico_path = PROJECT_ROOT / "ChannelHarvest.ico"
    png_path = PROJECT_ROOT / "Channel Harvest__Logo.png"

    if not ico_path.exists() and png_path.exists():
        print_step("Generating ChannelHarvest.ico from Logo PNG")
        try:
            from PIL import Image
            img = Image.open(png_path)
            img.save(
                ico_path,
                format="ICO",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
            )
            print_success(f"Generated {ico_path}")
        except Exception as e:
            print_error(f"Failed to generate icon: {e}")


def stage_runtime_binaries(target_dir: Path) -> bool:
    """
    Stages ffmpeg.exe, ffprobe.exe, and yt-dlp.exe into target_dir.
    Searches project runtime/, developer WinGet/Python locations, system PATH,
    or downloads official releases if missing.
    """
    print_step("Staging Runtime Binaries (ffmpeg, ffprobe, yt-dlp)")
    target_dir.mkdir(parents=True, exist_ok=True)

    binaries_to_find = ["ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe"]
    all_ok = True

    # Search candidates
    search_paths = [
        PROJECT_ROOT / "runtime",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Python" / "pythoncore-3.14-64" / "Scripts",
        Path(sys.executable).parent / "Scripts",
        Path(sys.executable).parent,
    ]

    for bin_name in binaries_to_find:
        dest_bin = target_dir / bin_name
        if dest_bin.is_file() and dest_bin.stat().st_size > 0:
            print_success(f"Existing binary ready: {dest_bin} ({dest_bin.stat().st_size:,} bytes)")
            continue

        found_path: Optional[Path] = None

        # 1. Search in candidates
        for sp in search_paths:
            if not sp.exists():
                continue
            if (sp / bin_name).is_file():
                found_path = sp / bin_name
                break
            # Recursive check in WinGet Packages
            if "WinGet" in str(sp):
                matches = list(sp.glob(f"**/{bin_name}"))
                if matches:
                    found_path = matches[0]
                    break

        # 2. Check system PATH
        if not found_path:
            which_res = shutil.which(bin_name)
            if which_res:
                found_path = Path(which_res)

        if found_path and found_path.is_file():
            shutil.copy2(found_path, dest_bin)
            print_success(f"Staged {bin_name} from {found_path} -> {dest_bin}")
        else:
            # 3. Fallback download for yt-dlp.exe
            if bin_name == "yt-dlp.exe":
                print(f"[INFO] Downloading official yt-dlp.exe from GitHub Releases...")
                import urllib.request
                url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
                try:
                    urllib.request.urlretrieve(url, dest_bin)
                    print_success(f"Downloaded official {bin_name} to {dest_bin}")
                except Exception as e:
                    print_error(f"Failed to download {bin_name}: {e}")
                    all_ok = False
            else:
                print_error(f"Could not locate required binary: {bin_name}")
                all_ok = False

    return all_ok


def clean_build_artifacts() -> None:
    """Removes temporary build directories."""
    print_step("Cleaning Previous Build Artifacts")
    for folder in [PROJECT_ROOT / "build", PROJECT_ROOT / "dist"]:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
            print(f"[CLEAN] Removed {folder}")


def build_pyinstaller() -> bool:
    """Runs PyInstaller using ChannelHarvest.spec."""
    print_step("Building Channel Harvest with PyInstaller (onedir mode)")

    spec_file = PROJECT_ROOT / "ChannelHarvest.spec"
    if not spec_file.exists():
        print_error(f"Spec file not found: {spec_file}")
        return False

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(spec_file),
        "--noconfirm",
        "--clean",
    ]

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print_error(f"PyInstaller failed with exit code {result.returncode}")
        return False

    output_exe = PROJECT_ROOT / "dist" / "ChannelHarvest" / "ChannelHarvest.exe"
    if not output_exe.is_file():
        print_error(f"PyInstaller output executable not found: {output_exe}")
        return False

    print_success(f"PyInstaller compilation complete: {output_exe}")
    return True


def create_portable_zip(release_dir: Path) -> Optional[Path]:
    """Packages dist/ChannelHarvest into a standalone portable ZIP."""
    print_step("Creating Standalone Portable ZIP")
    release_dir.mkdir(parents=True, exist_ok=True)

    dist_dir = PROJECT_ROOT / "dist" / "ChannelHarvest"
    zip_filename = f"ChannelHarvest-Portable-v{__version__}.zip"
    zip_path = release_dir / zip_filename

    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in dist_dir.rglob("*"):
            if file.is_file():
                rel_path = file.relative_to(dist_dir)
                archive_name = Path("ChannelHarvest") / rel_path
                zf.write(file, arcname=str(archive_name))

    print_success(f"Created Portable ZIP: {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return zip_path


def build_inno_setup(release_dir: Path) -> Optional[Path]:
    """Compiles the Inno Setup installer script."""
    print_step("Compiling Inno Setup Windows Installer")

    iscc_bin = find_inno_setup()
    if not iscc_bin:
        print_error("Inno Setup Compiler (ISCC.exe) not found. Skipping installer generation.")
        return None

    iss_file = PROJECT_ROOT / "installer" / "ChannelHarvest.iss"
    if not iss_file.exists():
        print_error(f"Installer script not found: {iss_file}")
        return None

    cmd = [str(iscc_bin), str(iss_file)]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT / "installer"))
    if result.returncode != 0:
        print_error(f"ISCC compilation failed with code {result.returncode}")
        return None

    installer_path = release_dir / f"ChannelHarvest-Setup-v{__version__}.exe"
    if not installer_path.is_file():
        print_error(f"Installer executable not found: {installer_path}")
        return None

    print_success(f"Compiled Windows Installer: {installer_path} ({installer_path.stat().st_size:,} bytes)")
    return installer_path


def generate_checksums(release_dir: Path) -> Path:
    """Generates SHA256SUMS.txt for all files in release directory."""
    print_step("Generating SHA-256 Checksums")

    checksum_file = release_dir / "SHA256SUMS.txt"
    entries = []

    for file in sorted(release_dir.iterdir()):
        if file.is_file() and file.name != "SHA256SUMS.txt":
            file_hash = calculate_sha256(file)
            entries.append(f"{file_hash}  {file.name}")
            print(f"  {file_hash}  {file.name} ({file.stat().st_size:,} bytes)")

    with open(checksum_file, "w", encoding="utf-8") as f:
        f.write("\n".join(entries) + "\n")

    print_success(f"Saved checksums to {checksum_file}")
    return checksum_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Channel Harvest Release Build Script")
    parser.add_argument("--skip-clean", action="store_true", help="Do not clean build/dist before building")
    parser.add_argument("--skip-installer", action="store_true", help="Skip Inno Setup installer compilation")
    parser.add_argument("--clean-only", action="store_true", help="Clean build directories and exit")
    args = parser.parse_args()

    print("=" * 70)
    print(f"  Channel Harvest Release Builder v{__version__}")
    print("=" * 70)

    if args.clean_only:
        clean_build_artifacts()
        return

    # 1. Staging preparation
    ensure_icon()

    # 2. Stage local project runtime/ folder
    project_runtime = PROJECT_ROOT / "runtime"
    if not stage_runtime_binaries(project_runtime):
        print_error("Failed to prepare required runtime binaries. Aborting build.")
        sys.exit(1)

    # 3. Clean previous builds
    if not args.skip_clean:
        clean_build_artifacts()

    # 4. PyInstaller freeze
    if not build_pyinstaller():
        print_error("PyInstaller build failed. Aborting.")
        sys.exit(1)

    # 5. Copy staged runtime binaries and icons into dist/ChannelHarvest/
    dist_root = PROJECT_ROOT / "dist" / "ChannelHarvest"
    dist_runtime = dist_root / "runtime"
    dist_runtime.mkdir(parents=True, exist_ok=True)
    for bin_file in project_runtime.iterdir():
        if bin_file.is_file():
            shutil.copy2(bin_file, dist_runtime / bin_file.name)
    print_success(f"Deployed runtime binaries to {dist_runtime}")

    for asset_name in ["Channel Harvest__Logo.png", "ChannelHarvest.ico"]:
        src_asset = PROJECT_ROOT / asset_name
        if src_asset.is_file():
            shutil.copy2(src_asset, dist_root / asset_name)
    print_success(f"Copied root assets into {dist_root}")


    # 6. Release packaging
    release_dir = PROJECT_ROOT / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    # Portable ZIP
    zip_path = create_portable_zip(release_dir)

    # Inno Setup Installer
    installer_path = None
    if not args.skip_installer:
        installer_path = build_inno_setup(release_dir)

    # Checksums
    checksum_path = generate_checksums(release_dir)

    # Summary
    print_step("Build Complete - Release Assets Summary")
    print(f"Version        : {__version__}")
    print(f"Release Folder : {release_dir}")
    if zip_path and zip_path.exists():
        print(f"Portable ZIP   : {zip_path.name} ({zip_path.stat().st_size:,} bytes)")
    if installer_path and installer_path.exists():
        print(f"Setup EXE      : {installer_path.name} ({installer_path.stat().st_size:,} bytes)")
    if checksum_path.exists():
        print(f"Checksums      : {checksum_path.name}")
    print("=" * 70)


if __name__ == "__main__":
    main()
