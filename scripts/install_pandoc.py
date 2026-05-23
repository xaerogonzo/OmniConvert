"""
install_pandoc.py -- Download a portable pandoc binary into vendor/pandoc/

Run once:  python scripts/install_pandoc.py

Fetches the official pandoc release ZIP from GitHub (no admin rights required)
and extracts pandoc.exe into vendor/pandoc/ at the project root.
OmniConvert detects this folder automatically on next launch.
"""

import os
import sys
from pathlib import Path

# Force UTF-8 output so special chars don't crash on Windows consoles set to cp1252
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# scripts/ lives one level below the project root
ROOT = Path(__file__).parent.parent
TARGET = ROOT / "vendor" / "pandoc"


def main() -> None:
    print("OmniConvert - Portable Pandoc Installer")
    print("=" * 42)

    try:
        import pypandoc
    except ImportError:
        print("[FAIL] pypandoc is not installed. Run:  pip install -r requirements.txt")
        sys.exit(1)

    existing = TARGET / "pandoc.exe"

    # Check if already installed
    if existing.exists():
        os.environ["PATH"] = str(TARGET) + ";" + os.environ.get("PATH", "")
        try:
            ver = pypandoc.get_pandoc_version()
            print(f"[OK] Pandoc {ver} is already installed at {existing}")
            print("     Delete vendor/pandoc/ and re-run to upgrade.")
            return
        except Exception:
            print("[*] Existing binary found but unreadable -- reinstalling...")

    TARGET.mkdir(parents=True, exist_ok=True)
    print(f"[*] Downloading pandoc to {TARGET} ...")
    print("    (This may take 30-60 seconds depending on your connection)")

    try:
        pypandoc.download_pandoc(targetfolder=str(TARGET))
    except Exception as exc:
        print(f"[FAIL] Download failed: {exc}")
        sys.exit(1)

    # pandoc.exe may be nested inside a versioned subfolder -- flatten it
    if not existing.exists():
        hits = list(TARGET.rglob("pandoc.exe"))
        if hits:
            hits[0].rename(TARGET / "pandoc.exe")
            for sub in TARGET.iterdir():
                if sub.is_dir():
                    try:
                        sub.rmdir()
                    except OSError:
                        pass

    if not existing.exists():
        print("[FAIL] pandoc.exe not found after download. Check vendor/pandoc/ manually.")
        sys.exit(1)

    # Clean up the MSI / archive that pypandoc dropped in CWD before extracting
    cwd = Path.cwd()
    leftover_patterns = ["pandoc-*.msi", "pandoc-*-windows-*.zip",
                          "pandoc-*-linux-*.tar.gz", "pandoc-*-macOS.zip"]
    for pat in leftover_patterns:
        for leftover in cwd.glob(pat):
            try:
                leftover.unlink()
                print(f"[*] Cleaned up installer leftover: {leftover.name}")
            except OSError as exc:
                print(f"[!] Could not delete {leftover.name}: {exc}")

    # Smoke test
    os.environ["PATH"] = str(TARGET) + ";" + os.environ.get("PATH", "")
    try:
        ver = pypandoc.get_pandoc_version()
        size_mb = existing.stat().st_size / (1024 * 1024)
        print(f"[OK] Pandoc {ver} installed ({size_mb:.0f} MB) -> {existing}")
        print()
        print("     Restart OmniConvert -- all output formats are now available.")
    except Exception as exc:
        print(f"[!]  Binary present but version check failed: {exc}")
        print(f"     Path: {existing}")


if __name__ == "__main__":
    main()
