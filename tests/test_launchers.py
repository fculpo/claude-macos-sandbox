#!/usr/bin/env python3
import subprocess
import tempfile
import unittest
import os
import time
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def wait_for_exit(proc, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            return code
        time.sleep(0.05)
    return None


def load_launcher(name):
    loader = SourceFileLoader(name.replace("-", "_"), str(ROOT / name))
    spec = importlib.util.spec_from_loader(name.replace("-", "_"), loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class LauncherDryRunTests(unittest.TestCase):
    def test_default_profile_does_not_enable_gui_access(self):
        launcher = load_launcher("claude-sandbox")

        sbpl = launcher.generate_sbpl([], [])

        self.assertNotIn("GUI app access", sbpl)
        self.assertNotIn("(system-graphics)", sbpl)
        self.assertNotIn("IOHIDParamUserClient", sbpl)

    def test_default_profile_allows_posix_semaphores_for_multiprocessing(self):
        launcher = load_launcher("claude-sandbox")

        sbpl = launcher.generate_sbpl([], [])

        self.assertIn("(allow ipc-posix-sem)", sbpl)

    def test_allow_gui_profile_includes_graphics_and_hid_access(self):
        launcher = load_launcher("claude-sandbox")

        sbpl = launcher.generate_sbpl([], [], allow_gui_access=True)

        self.assertIn('(import "system.sb")', sbpl)
        self.assertIn("GUI app access", sbpl)
        self.assertIn("(system-graphics)", sbpl)
        self.assertIn("IOHIDParamUserClient", sbpl)
        self.assertIn("IOUserUserClient", sbpl)
        self.assertIn("(allow iokit-get-properties)", sbpl)

    def test_gui_electron_override_points_to_wrapper_shape(self):
        launcher = load_launcher("claude-sandbox")

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            wrapper_source = tmpdir / "wrapper.py"
            wrapper_source.write_text("#!/usr/bin/env python3\n")

            override_dir = Path(
                launcher.create_electron_override_dir(wrapper_source, tmpdir / "override")
            )

            wrapper = override_dir / "Electron.app" / "Contents" / "MacOS" / "Electron"
            self.assertTrue(wrapper.exists())
            self.assertTrue(os.access(wrapper, os.X_OK))
            self.assertEqual(wrapper.read_text(), wrapper_source.read_text())

    def test_electron_wrapper_does_not_timeout_long_running_processes(self):
        wrapper = ROOT / "electron-gui-wrapper.py"

        source = wrapper.read_text()

        self.assertIn("socket.create_connection((host, int(raw_port)), timeout=10)", source)
        self.assertIn("sock.settimeout(None)", source)

    def test_gui_helper_streams_child_output_without_waiting_for_eof(self):
        helper = ROOT / "claude-sandbox-gui-helper.py"

        source = helper.read_text()

        self.assertIn("os.read(fd, 65536)", source)
        self.assertNotIn("stream.read(65536)", source)

    def test_gui_helpers_have_independent_lifecycles(self):
        launcher = load_launcher("claude-sandbox")
        first_proc = None
        second_proc = None
        first_fd = None
        second_fd = None

        try:
            first_proc, _ = launcher.start_gui_helper(ROOT)
            second_proc, _ = launcher.start_gui_helper(ROOT)
            first_fd = first_proc.claude_sandbox_lifecycle_fd
            second_fd = second_proc.claude_sandbox_lifecycle_fd

            os.close(first_fd)
            first_fd = None

            self.assertIsNotNone(wait_for_exit(first_proc))
            self.assertIsNone(second_proc.poll())
        finally:
            for fd in (first_fd, second_fd):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            for proc in (first_proc, second_proc):
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    wait_for_exit(proc)

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
            self.assertTrue((prefix / "claude-sandbox-gui-helper.py").exists())
            self.assertTrue((prefix / "electron-gui-wrapper.py").exists())
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

    def test_install_removes_legacy_alias_shims_and_restores_real_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            prefix = tmpdir / "bin"
            home = tmpdir / "home"
            prefix.mkdir()
            home.mkdir()

            for name in ("claude", "codex"):
                (prefix / name).write_text(
                    f"#!/usr/bin/env bash\n"
                    f"# {name}-sandbox alias shim\n"
                    f"exec \"{prefix}/{name}-sandbox\" \"$@\"\n"
                )
                (prefix / f"{name}.real").write_text(
                    f"#!/bin/sh\necho real {name}\n"
                )
                (prefix / name).chmod(0o755)
                (prefix / f"{name}.real").chmod(0o755)

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
            self.assertIn("Removed legacy alias shim", result.stdout)

            for name in ("claude", "codex"):
                restored = subprocess.run(
                    [str(prefix / name)],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                self.assertEqual(restored.returncode, 0, restored.stderr)
                self.assertEqual(restored.stdout.strip(), f"real {name}")
                self.assertFalse((prefix / f"{name}.real").exists())


if __name__ == "__main__":
    unittest.main()
