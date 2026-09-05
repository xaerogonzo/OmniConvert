"""Persisted preferences.

`load()` is fed a file the user (or a crash, or a future version) can have
mangled, so most of these are corruption cases. The rule under test throughout:
a bad file must cost you defaults, never a failed startup, and one bad field must
never discard its valid neighbours.
"""

import json
import os
from pathlib import Path

import pytest

from omniconvert import settings
from omniconvert.settings import CURRENT_VERSION, Settings


@pytest.fixture
def cfg(tmp_path):
    return tmp_path / "settings.json"


def write(cfg: Path, payload) -> Path:
    cfg.write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )
    return cfg


class TestRoundTrip:
    def test_save_then_load_preserves_everything(self, cfg, tmp_path):
        dest = tmp_path / "out"
        dest.mkdir()
        original = Settings(
            target_fmt="EPUB", mode="High-Fidelity", extract_cover=False,
            strict_tables=False, include_subfolders=True,
            keep_intermediates=False, dest_dir=dest, geometry="960x720+10+20",
        )
        assert settings.save(original, cfg)
        assert settings.load(cfg) == original

    def test_save_is_atomic_and_leaves_no_debris(self, cfg):
        settings.save(Settings(), cfg)
        leftovers = [p.name for p in cfg.parent.iterdir() if p.name != cfg.name]
        assert leftovers == []

    def test_save_creates_missing_directories(self, tmp_path):
        nested = tmp_path / "a" / "b" / "settings.json"
        assert settings.save(Settings(), nested)
        assert nested.exists()

    def test_save_reports_failure_rather_than_raising(self, tmp_path, monkeypatch):
        """It runs on window close; an exception there turns a clean exit into
        a crash."""
        monkeypatch.setattr(Path, "mkdir",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
        assert settings.save(Settings(), tmp_path / "x" / "s.json") is False


class TestMissingAndCorrupt:
    def test_absent_file_gives_defaults(self, cfg):
        assert settings.load(cfg) == Settings()

    @pytest.mark.parametrize(
        "content",
        ["", "{", "not json at all", "null", "[1, 2, 3]", '"a string"', "42"],
    )
    def test_unparseable_or_wrong_shape_gives_defaults(self, cfg, content):
        assert settings.load(write(cfg, content)) == Settings()

    def test_unreadable_file_gives_defaults(self, cfg, monkeypatch):
        write(cfg, {"version": 1})
        monkeypatch.setattr(
            Path, "read_text",
            lambda *a, **k: (_ for _ in ()).throw(OSError("locked")),
        )
        assert settings.load(cfg) == Settings()


class TestVersioning:
    def test_a_future_version_is_ignored_wholesale(self, cfg):
        """Its fields may mean something else entirely."""
        loaded = settings.load(write(cfg, {
            "version": CURRENT_VERSION + 1, "target_fmt": "EPUB",
        }))
        assert loaded == Settings()

    @pytest.mark.parametrize("version", [None, "1", 1.5, [], {}])
    def test_a_non_integer_version_is_ignored(self, cfg, version):
        loaded = settings.load(write(cfg, {"version": version,
                                           "target_fmt": "EPUB"}))
        assert loaded.target_fmt == "PDF"

    def test_a_missing_version_is_ignored(self, cfg):
        assert settings.load(write(cfg, {"target_fmt": "EPUB"})) == Settings()


class TestFieldLevelTolerance:
    def test_one_bad_field_does_not_discard_the_others(self, cfg):
        """The whole point of field-level fallback."""
        loaded = settings.load(write(cfg, {
            "version": 1,
            "target_fmt": "DOCX",          # valid, must survive
            "mode": "High-Fidelity",       # valid, must survive
            "extract_cover": "banana",     # corrupt, resets alone
            "strict_tables": True,
        }))
        assert loaded.target_fmt == "DOCX"
        assert loaded.mode == "High-Fidelity"
        assert loaded.extract_cover is True     # the default
        assert loaded.strict_tables is True

    @pytest.mark.parametrize("bad", ["RTF", "pdf", "", 7, None, ["PDF"]])
    def test_unknown_formats_fall_back(self, cfg, bad):
        assert settings.load(write(cfg, {"version": 1,
                                         "target_fmt": bad})).target_fmt == "PDF"

    @pytest.mark.parametrize("bad", ["standard", "Turbo", 1, None])
    def test_unknown_modes_fall_back(self, cfg, bad):
        assert settings.load(write(cfg, {"version": 1,
                                         "mode": bad})).mode == "Standard"

    @pytest.mark.parametrize("bad", ["true", 1, 0, "yes", None, []])
    def test_non_boolean_flags_fall_back(self, cfg, bad):
        """A truthy string is corruption, not intent."""
        loaded = settings.load(write(cfg, {"version": 1, "strict_tables": bad}))
        assert loaded.strict_tables is True

    def test_booleans_are_honoured_when_actually_boolean(self, cfg):
        loaded = settings.load(write(cfg, {"version": 1, "strict_tables": False,
                                           "keep_intermediates": False}))
        assert loaded.strict_tables is False and loaded.keep_intermediates is False

    def test_unknown_keys_are_ignored(self, cfg):
        loaded = settings.load(write(cfg, {
            "version": 1, "target_fmt": "TXT", "favourite_colour": "blue",
        }))
        assert loaded.target_fmt == "TXT"

    @pytest.mark.parametrize("bad", ["", "   ", 42, None, {}])
    def test_bad_destinations_become_none(self, cfg, bad):
        assert settings.load(write(cfg, {"version": 1, "dest_dir": bad})).dest_dir is None

    @pytest.mark.parametrize(
        "bad", ["", "wide", "960", "960x", "x720", "960*720", 960, None,
                "960x720+", "'; DROP TABLE"],
    )
    def test_bad_geometry_becomes_none(self, cfg, bad):
        """A corrupt geometry string must not reach Tk."""
        assert settings.load(write(cfg, {"version": 1, "geometry": bad})).geometry is None

    @pytest.mark.parametrize("good", ["960x720", "800x600+0+0", "1024x768-10+40"])
    def test_valid_geometry_survives(self, cfg, good):
        assert settings.load(write(cfg, {"version": 1, "geometry": good})).geometry == good


class TestEffectiveDestination:
    def test_an_existing_directory_is_used(self, tmp_path):
        assert Settings(dest_dir=tmp_path).effective_dest_dir() == tmp_path

    def test_a_vanished_directory_falls_back_to_none(self, tmp_path):
        """The drive was unplugged between launches."""
        assert Settings(dest_dir=tmp_path / "gone").effective_dest_dir() is None

    def test_a_file_is_not_a_directory(self, tmp_path):
        f = tmp_path / "not_a_dir.txt"
        f.write_text("x", encoding="utf-8")
        assert Settings(dest_dir=f).effective_dest_dir() is None

    def test_no_destination_is_none(self):
        assert Settings().effective_dest_dir() is None


class TestConfigPath:
    def test_lives_under_localappdata(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        p = settings.config_path()
        assert p.parent.parent == tmp_path
        assert p.name == "settings.json"

    def test_never_derived_from_the_install_directory(self, monkeypatch, tmp_path):
        """A frozen exe must not write into its own (often read-only) folder."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        install_dir = Path(settings.__file__).resolve().parent
        assert install_dir not in settings.config_path().resolve().parents

    def test_falls_back_when_localappdata_is_unset(self, monkeypatch):
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert settings.config_path().is_absolute()


def test_module_is_tk_free():
    import subprocess
    import sys

    probe = (
        "import sys; sys.path.insert(0, 'src');"
        "import omniconvert.settings;"
        "print(any(m.startswith(('tkinter', 'customtkinter')) for m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert out.stdout.strip() == "False", out.stderr
