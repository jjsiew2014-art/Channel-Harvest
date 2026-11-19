"""
test_certifi_bootstrap.py
Regression tests for PyInstaller frozen `certifi` namespace-package crash
(`AttributeError: module 'certifi' has no attribute 'where'`).
"""

import ast
import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import core.paths as core_paths


class TestCertifiBootstrap(unittest.TestCase):
    """Validates recovery from namespace-package or missing `certifi` on startup."""

    def setUp(self) -> None:
        self._saved_modules = {
            k: sys.modules.get(k)
            for k in ("certifi", "certifi.core")
            if k in sys.modules
        }
        self._saved_sys_path = list(sys.path)
        self._saved_env = {
            k: os.environ.get(k)
            for k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
        }
        if "yt_dlp.dependencies" in sys.modules:
            ytd = sys.modules["yt_dlp.dependencies"]
            self._saved_ytd_avail = dict(getattr(ytd, "available_dependencies", {}))
            self._saved_ytd_all = dict(getattr(ytd, "all_dependencies", {}))
        else:
            self._saved_ytd_avail = None
            self._saved_ytd_all = None

    def tearDown(self) -> None:
        for k in ("certifi", "certifi.core"):
            if k in self._saved_modules:
                sys.modules[k] = self._saved_modules[k]
            else:
                sys.modules.pop(k, None)
        sys.path[:] = self._saved_sys_path
        importlib.invalidate_caches()
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

        if "yt_dlp.dependencies" in sys.modules and self._saved_ytd_avail is not None:
            ytd = sys.modules["yt_dlp.dependencies"]
            if hasattr(ytd, "available_dependencies"):
                ytd.available_dependencies.clear()
                ytd.available_dependencies.update(self._saved_ytd_avail)
            if hasattr(ytd, "all_dependencies"):
                ytd.all_dependencies.clear()
                ytd.all_dependencies.update(self._saved_ytd_all)
            if "certifi" in self._saved_modules and self._saved_modules["certifi"] is not None:
                ytd.certifi = self._saved_modules["certifi"]

    def test_recovers_from_pep420_namespace_certifi_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            internal_dir = Path(tmpdir) / "_internal"
            certifi_dir = internal_dir / "certifi"
            certifi_dir.mkdir(parents=True)
            pem_file = certifi_dir / "cacert.pem"
            pem_file.write_text("-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n", encoding="ascii")

            sys.modules.pop("certifi", None)
            sys.modules.pop("certifi.core", None)
            # Frozen apps have no site-packages on sys.path; restrict sys.path briefly so
            # Python resolves `_internal/certifi` strictly as a PEP 420 namespace package.
            sys.path[:] = [str(internal_dir)]
            importlib.invalidate_caches()

            # Simulate broken frozen path where Python binds `_internal/certifi` as a namespace package
            os.environ["SSL_CERT_FILE"] = str(Path(tmpdir) / "nonexistent_cert.pem")
            os.environ.pop("REQUESTS_CA_BUNDLE", None)

            ns_mod = importlib.import_module("certifi")
            self.assertFalse(hasattr(ns_mod, "where"))

            # Restore site-packages so yt_dlp can still be imported in this test process
            sys.path[:] = self._saved_sys_path
            resolved = core_paths.ensure_certifi_bundle()
            self.assertEqual(resolved, pem_file)

            repaired = importlib.import_module("certifi")
            self.assertTrue(callable(repaired.where))
            self.assertEqual(Path(repaired.where()), pem_file)
            self.assertIn("BEGIN CERTIFICATE", repaired.contents())
            self.assertEqual(os.environ.get("SSL_CERT_FILE"), str(pem_file))
            self.assertEqual(os.environ.get("REQUESTS_CA_BUNDLE"), str(pem_file))

            # Importing yt_dlp.dependencies must not raise AttributeError
            ytdlp_deps = importlib.import_module("yt_dlp.dependencies")
            ytdlp_deps = importlib.reload(ytdlp_deps)
            self.assertIsNotNone(ytdlp_deps.certifi)
            self.assertEqual(Path(ytdlp_deps.certifi.where()), pem_file)

    def test_recovers_when_certifi_missing_completely_in_frozen_meipass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meipass_dir = Path(tmpdir) / "_internal"
            certifi_dir = meipass_dir / "certifi"
            certifi_dir.mkdir(parents=True)
            pem_file = certifi_dir / "cacert.pem"
            pem_file.write_text("DUMMY PEM DATA\n", encoding="ascii")

            sys.modules.pop("certifi", None)
            sys.modules.pop("certifi.core", None)
            # Force ImportError on `import certifi` by blocking sys.meta_path lookup via meta hook or import mock
            orig_import = __import__

            def _missing_certifi_import(name, *args, **kwargs):
                if name == "certifi":
                    raise ImportError("No module named 'certifi'")
                return orig_import(name, *args, **kwargs)

            with (
                mock.patch.object(sys, "frozen", True, create=True),
                mock.patch.object(sys, "_MEIPASS", str(meipass_dir), create=True),
                mock.patch("builtins.__import__", side_effect=_missing_certifi_import),
            ):
                resolved = core_paths.ensure_certifi_bundle()

            self.assertEqual(resolved, pem_file)
            self.assertIn("certifi", sys.modules)
            self.assertIn("certifi.core", sys.modules)
            self.assertEqual(Path(sys.modules["certifi"].where()), pem_file)
            self.assertEqual(Path(sys.modules["certifi.core"].where()), pem_file)
            self.assertEqual(sys.modules["certifi"].contents(), "DUMMY PEM DATA\n")

    def test_packaging_and_startup_order(self) -> None:
        app_src = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(app_src)
        setup_line = None
        gui_import_line = None
        for node in tree.body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "setup_runtime_environment"
                and setup_line is None
            ):
                setup_line = node.lineno
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "gui.main_window"
                and gui_import_line is None
            ):
                gui_import_line = node.lineno

        self.assertIsNotNone(setup_line, "app.py must call setup_runtime_environment() at module top level")
        self.assertIsNotNone(gui_import_line, "app.py must import gui.main_window")
        self.assertLess(
            setup_line,
            gui_import_line,
            "setup_runtime_environment() must run before importing gui.main_window",
        )

        spec_src = (PROJECT_ROOT / "ChannelHarvest.spec").read_text(encoding="utf-8")
        self.assertIn("collect_data_files('certifi')", spec_src)
        self.assertIn("'certifi'", spec_src)
        self.assertIn("'certifi.core'", spec_src)
        self.assertIn("rthook_certifi.py", spec_src)
        self.assertTrue((PROJECT_ROOT / "rthook_certifi.py").is_file())

        req_src = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("certifi", req_src.lower())

    def test_verify_frozen_certifi_checks_bundle_and_pyz(self) -> None:
        import build as build_script

        with tempfile.TemporaryDirectory() as tmpdir:
            dist_dir = Path(tmpdir) / "ChannelHarvest"
            dist_dir.mkdir(parents=True)
            fake_exe = dist_dir / "ChannelHarvest.exe"
            fake_exe.write_bytes(b"MZ")

            # Missing cacert.pem must fail
            self.assertFalse(build_script.verify_frozen_certifi(fake_exe))

            # Present cacert.pem + complete TOC succeeds
            pem = dist_dir / "_internal" / "certifi" / "cacert.pem"
            pem.parent.mkdir(parents=True)
            pem.write_text("PEM", encoding="ascii")

            fake_pyz = types.SimpleNamespace(toc={"certifi": (), "certifi.core": ()})
            fake_reader = mock.MagicMock()
            fake_reader.open_embedded_archive.return_value = fake_pyz

            with mock.patch("PyInstaller.archive.readers.CArchiveReader", return_value=fake_reader):
                self.assertTrue(build_script.verify_frozen_certifi(fake_exe))

            # Missing certifi.core in PYZ must fail
            fake_pyz_incomplete = types.SimpleNamespace(toc={"certifi": ()})
            fake_reader.open_embedded_archive.return_value = fake_pyz_incomplete
            with mock.patch("PyInstaller.archive.readers.CArchiveReader", return_value=fake_reader):
                self.assertFalse(build_script.verify_frozen_certifi(fake_exe))


if __name__ == "__main__":
    unittest.main()
