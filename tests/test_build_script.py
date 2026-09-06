"""Guards on the build scripts.

`build.bat` launches `build.ps1` with Windows PowerShell 5.1, which reads
BOM-less files as cp1252. A UTF-8 em-dash therefore decodes to `a€"` whose last
character is U+201D - and PowerShell accepts smart quotes as string delimiters,
so the surrounding string closes early and the whole script fails to parse.

That broke `.\build.bat` silently: the launcher `pause`d and returned 0, so the
failure looked like a successful build. Keeping the script pure ASCII removes the
encoding dependency entirely.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _active_flags() -> str:
    """build.ps1 keeps a commented-out copy of the exclusion block for reference;
    only the uncommented lines actually affect the build."""
    return "\n".join(
        line for line in (ROOT / "build.ps1").read_text(encoding="ascii").splitlines()
        if not line.strip().startswith("#")
    )


@pytest.mark.parametrize("name", ["build.ps1", "build.bat", "launch.bat"])
def test_shell_scripts_are_pure_ascii(name):
    raw = (ROOT / name).read_bytes()
    offenders = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not offenders, (
        f"{name} contains non-ASCII bytes at offsets "
        f"{[i for i, _ in offenders[:5]]} - PowerShell 5.1 will mis-decode them"
    )


@pytest.mark.parametrize("name", ["build.ps1", "build.bat", "launch.bat"])
def test_shell_scripts_have_no_bom(name):
    assert not (ROOT / name).read_bytes().startswith(b"\xef\xbb\xbf")


def test_build_bat_propagates_the_exit_code():
    """A failed build must not report success."""
    text = (ROOT / "build.bat").read_text(encoding="ascii")
    assert "exit /b" in text.lower()


def test_build_flags_match_the_real_dependencies():
    """Nuitka must bundle what we import, and nothing we removed."""
    flags = (ROOT / "build.ps1").read_text(encoding="ascii")
    for pkg in ("customtkinter", "pymupdf", "markitdown", "mammoth",
                "ebooklib", "pdf2docx", "tkinterdnd2", "docx2pdf"):
        assert f"--include-package={pkg}" in flags, f"missing {pkg}"
    for gone in ("weasyprint", "pystray"):
        assert f"--include-package={gone}" not in flags, f"{gone} is no longer used"


def test_tkdnd_data_dir_flag_is_present():
    """Drag-and-drop breaks silently in the .exe without this inclusion."""
    flags = (ROOT / "build.ps1").read_text(encoding="ascii")
    assert "--include-data-dir" in flags and "tkdnd" in flags


def test_sympy_is_excluded_from_the_build():
    """pdf2docx -> fontTools -> fontTools.misc.symfont imports sympy.

    Nothing in OmniConvert uses symbolic font math, but Nuitka follows the
    static import and compiles every sympy module - 3.2 GB of objects and a
    build that stalls before it links.
    """
    assert "--nofollow-import-to=sympy" in _active_flags()


@pytest.mark.parametrize("pkg", ["numpy", "pandas"])
def test_required_heavyweights_are_not_excluded(pkg):
    """These are reached transitively and must be bundled.

    pdf2docx reaches numpy through cv2, so excluding numpy produced an .exe
    that raised ImportError on every DOCX source and on High-Fidelity
    PDF -> DOCX. That shipped broken from v0.2.0 and went unnoticed because the
    build died before it ever emitted a binary.

    pandas is conditional: markitdown does NOT require it (a clean venv pulls
    only numpy), but markitdown imports it when it is installed. A build run
    from an environment that has pandas would therefore trace into a package the
    flags told it to skip, so it stays off the exclusion list either way.
    """
    assert f"--nofollow-import-to={pkg}" not in _active_flags()


def test_exclusions_and_inclusions_do_not_contradict():
    """A package cannot be both bundled and blocked."""
    flags = _active_flags()
    included = set(re.findall(r"--include-package=(\w+)", flags))
    excluded = set(re.findall(r"--nofollow-import-to=(\w+)", flags))
    clash = included & excluded
    assert not clash, f"both included and excluded: {sorted(clash)}"


@pytest.mark.parametrize("flag", ["--low-memory", "--jobs=", "--lto=no"])
def test_memory_guards_are_present(flag):
    """Without these the build OOMs silently on pymupdf's SWIG binding.

    pymupdf/mupdf.py (65k lines) expands to a ~118 MB C file. Nuitka defaults
    --jobs to the full CPU count, so that translation unit competes with N-1
    sibling compilers for RAM; when it loses, zig cc dies with no error and no
    process and scons waits forever. Two builds wedged there for ~50 minutes
    each before these flags existed.
    """
    assert flag in _active_flags()


def test_the_application_package_is_bundled():
    """Without this the exe builds cleanly and contains no application.

    main.py puts src/ on sys.path at RUNTIME, which Nuitka's static analysis
    cannot follow, so `from omniconvert.app import ...` is unresolvable at build
    time. Nuitka then compiles main.py, bundles all ten third-party libraries,
    and silently omits OmniConvert itself - a 127 MB executable that dies on
    launch with "No module named 'omniconvert'". Nothing fails during the build,
    which is what let it go unnoticed.
    """
    assert "--include-package=omniconvert" in _active_flags()


def test_build_sets_pythonpath_for_the_src_layout():
    """--include-package is resolved against sys.path at build time, so Nuitka
    has to be told where the src-layout package lives."""
    flags = _active_flags()
    assert "PYTHONPATH" in flags and "src" in flags
