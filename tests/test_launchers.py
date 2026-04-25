#!/usr/bin/env python3
import subprocess
import tempfile
import unittest
import os
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_launcher(name):
    loader = SourceFileLoader(name.replace("-", "_"), str(ROOT / name))
    spec = importlib.util.spec_from_loader(name.replace("-", "_"), loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class LauncherDryRunTests(unittest.TestCase):
    def test_codex_no_net_filter_allows_all_network_without_proxy(self):
        result = subprocess.run(
            [str(ROOT / "codex-sandbox"), "--dry-run", "--no-net-filter"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Network: all outbound allowed (--no-net-filter)", result.stdout)
        self.assertIn("(allow network-outbound)", result.stdout)
        self.assertNotIn("Network: localhost only", result.stdout)
        self.assertNotIn("proxy on 127.0.0.1", result.stderr)

    def test_resolve_cli_bin_skips_wrapper_directory(self):
        launcher = load_launcher("claude-sandbox")

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            wrapper_dir = tmpdir / "wrapper"
            real_dir = tmpdir / "real"
            wrapper_dir.mkdir()
            real_dir.mkdir()

            wrapper = wrapper_dir / "claude"
            real = real_dir / "claude"
            wrapper.write_text("#!/bin/sh\nexit 1\n")
            real.write_text("#!/bin/sh\nexit 0\n")
            wrapper.chmod(0o755)
            real.chmod(0o755)

            resolved = launcher.resolve_cli_bin(
                "claude",
                explicit=None,
                env_var="CLAUDE_BIN_DOES_NOT_EXIST",
                fallback="/missing/claude",
                path=f"{wrapper_dir}:{real_dir}",
                skip_dirs=[wrapper_dir],
            )

        self.assertEqual(resolved, str(real))

    def test_install_preserves_existing_binaries_as_real_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            prefix = tmpdir / "bin"
            home = tmpdir / "home"
            prefix.mkdir()
            home.mkdir()

            (prefix / "claude").write_text("#!/bin/sh\necho real claude\n")
            (prefix / "codex").write_text("#!/bin/sh\necho real codex\n")
            (prefix / "claude").chmod(0o755)
            (prefix / "codex").chmod(0o755)

            env = os.environ.copy()
            env["PREFIX"] = str(prefix)
            env["HOME"] = str(home)
            result = subprocess.run(
                [str(ROOT / "install.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("real claude", (prefix / "claude.real").read_text())
            self.assertIn("real codex", (prefix / "codex.real").read_text())
            self.assertIn("claude-sandbox alias shim", (prefix / "claude").read_text())
            self.assertIn("codex-sandbox alias shim", (prefix / "codex").read_text())

            env["CLAUDE_SANDBOX_ACTIVE"] = "1"
            active_claude = subprocess.run(
                [str(prefix / "claude")],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(active_claude.returncode, 0, active_claude.stderr)
            self.assertEqual(active_claude.stdout.strip(), "real claude")

            env["CODEX_SANDBOX_ACTIVE"] = "1"
            active_codex = subprocess.run(
                [str(prefix / "codex")],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(active_codex.returncode, 0, active_codex.stderr)
            self.assertEqual(active_codex.stdout.strip(), "real codex")


if __name__ == "__main__":
    unittest.main()
