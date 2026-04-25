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

    def test_install_does_not_replace_existing_cli_commands_with_aliases(self):
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
            self.assertIn("real claude", (prefix / "claude").read_text())
            self.assertIn("real codex", (prefix / "codex").read_text())
            self.assertFalse((prefix / "claude.real").exists())
            self.assertFalse((prefix / "codex.real").exists())

            installed_claude = subprocess.run(
                [str(prefix / "claude")],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(installed_claude.returncode, 0, installed_claude.stderr)
            self.assertEqual(installed_claude.stdout.strip(), "real claude")

            installed_codex = subprocess.run(
                [str(prefix / "codex")],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(installed_codex.returncode, 0, installed_codex.stderr)
            self.assertEqual(installed_codex.stdout.strip(), "real codex")


if __name__ == "__main__":
    unittest.main()
