# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

macOS sandbox wrapper for Claude Code. Two-layer security: SBPL profiles (filesystem/network) + local HTTPS CONNECT proxy (domain filtering). No Docker, no root, no external dependencies — Python 3.11+ only (ships with macOS).

## Running & Testing

```bash
# Install to ~/.local/bin/
./install.sh

# Run (from any project dir)
claude-sandbox

# Preview generated SBPL profile without launching
claude-sandbox --dry-run

# Reload proxy domains at runtime (all instances)
claude-sandbox reload-proxies
```

There is no automated test suite. Test manually:
- `claude-sandbox --dry-run` to inspect the generated SBPL profile
- `tail -f /tmp/claude-sandbox-proxy.log` to monitor proxy allow/deny decisions
- `/tmp/claude-sandbox-violations.log` for sandbox violation events

## Architecture

```
claude-sandbox (Python)          claude-sandbox-proxy.py (Python)
├─ Parses config + CLI args      ├─ Threaded HTTP server
├─ Generates SBPL profile        ├─ Handles CONNECT tunneling
├─ Spawns proxy as daemon        ├─ Domain whitelist enforcement
├─ Pre-launches gpg-agent        ├─ SIGHUP reloads domains from JSON
├─ Spawns supervisor daemon      └─ Logs to /tmp/claude-sandbox-proxy.log
├─ os.execvp() into sandbox-exec
└─ shims/ps prepended to PATH
```

**Process model**: `claude-sandbox` forks a proxy daemon (with supervisor for auto-restart), then replaces itself with `sandbox-exec → claude` via `os.execvp()`. The supervisor watches the parent PID and kills the proxy when the sandbox exits.

**Key files**:
- `claude-sandbox` — main wrapper (~556 lines): argument parsing, SBPL generation, proxy lifecycle, `sandbox-exec` invocation
- `claude-sandbox-proxy.py` — HTTPS CONNECT proxy (~145 lines): domain whitelist, SIGHUP reload, threaded tunneling
- `shims/ps` — shell shim replacing setuid `/bin/ps` (blocked by sandbox); handles TTY/PPID patterns for `ccstatusline`
- `config.example` — template for `~/.config/claude-sandbox/config`

## SBPL Profile Generation

The SBPL profile is generated dynamically in `claude-sandbox` based on merged config+CLI values. Critical rules:

- **Last-match-wins semantics**: sensitive dir denies (`.ssh`, `.aws`, `.kube`, `.docker`) must come after broad home-dir allows
- GPG dirs (`~/.gnupg`, `~/.gpg`) get read-only access (private key ops go through the pre-launched agent outside the sandbox)
- Both symlink and real paths for `$TMPDIR` are included (macOS TMPDIR is `/private/var/folders/.../T/`, not `/tmp`)
- Network restricted to `localhost:*` only; proxy handles external connectivity

## Configuration Merging

CLI flags, config file (`~/.config/claude-sandbox/config`), and built-in defaults are merged with deduplication. Config format is line-based: `write=<path>`, `read=<path>`, `domain=<domain>`.

Built-in domains (always allowed): `api.anthropic.com`, `mcp-proxy.anthropic.com`, `statsig.anthropic.com`, `platform.claude.com`.

## Proxy Lifecycle

- Proxy runs as a detached daemon (double-fork)
- PID file at `/tmp/claude-sandbox-proxy-<port>.pid`
- Domains stored in `/tmp/claude-sandbox-domains-*` (JSON array)
- Supervisor daemon auto-restarts proxy on crash
- `reload-proxies` subcommand re-reads config, writes updated domains JSON, sends SIGHUP to all proxy instances
