# claude-code-sandbox

Native macOS sandbox for [Claude Code](https://claude.ai/code). Restricts
filesystem and network access using `sandbox-exec` (SBPL profiles) and a
local HTTPS CONNECT proxy for domain-level filtering.

Also includes `codex-sandbox`, a Codex CLI launcher that reuses the same
SBPL/proxy machinery with OpenAI/ChatGPT defaults.

No Docker, no root, no external dependencies — just Python 3.11+ (ships with macOS).

## How it works

```
[Claude Code in sandbox]
     |  HTTPS_PROXY=http://127.0.0.1:<port>
     |  SBPL: only localhost:* allowed
     v
[claude-sandbox-proxy.py on localhost]
     |  CONNECT api.anthropic.com:443 -> ALLOW
     |  CONNECT evil.com:443          -> DENY (403)
     v
[Internet]
```

Two layers of enforcement:

| Layer | Enforces |
|---|---|
| **SBPL sandbox** | Process can only connect to `localhost:*` — no direct internet |
| **HTTPS proxy** | Only whitelisted domains pass through CONNECT tunneling |

Even if `HTTPS_PROXY` is unset in code, the sandbox blocks all non-localhost.

## Install

```bash
git clone git@git.corp.dawex.net:tools/claude-code-sandbox.git
cd claude-code-sandbox
./install.sh
```

Installs `claude-sandbox` and `codex-sandbox` to `~/.local/bin/` (ensure it's
on your `PATH`). The installer does not replace existing `claude` or `codex`
commands.

The install also creates a default config at `~/.config/claude-sandbox/config`
if none exists.

To install elsewhere: `PREFIX=/usr/local/bin ./install.sh`

## Usage

```bash
# Run from a project directory
cd ~/my-project
claude-sandbox
codex-sandbox

# After install, regular command names route through the sandbox shims
claude
codex

# Or specify a project directory
claude-sandbox --project-dir ~/my-project
codex-sandbox --project-dir ~/my-project

# Pass arguments to claude
claude-sandbox -- -p "fix the tests"

# Pass arguments to codex
codex-sandbox -- "fix the tests"

# Additional writable directory for this session
claude-sandbox --write-dir ~/other-project
codex-sandbox --write-dir ~/other-project

# Allow an extra domain for this session
claude-sandbox --allow-domain extra.example.com
codex-sandbox --allow-domain extra.example.com

# Preview the generated SBPL profile
claude-sandbox --dry-run
codex-sandbox --dry-run

# Disable proxy/domain filtering and allow all outbound network
claude-sandbox --no-net-filter
codex-sandbox --no-net-filter
```

## Configuration

Edit `~/.config/claude-sandbox/config`:

```bash
# Writable directories (project dirs Claude can modify)
write=/Users/you/projects/myapp

# Read-only directories
read=/Users/you/.gitconfig
read=/Users/you/.config/git

# Allowed domains (added to built-in defaults)
domain=gitlab.com
domain=registry.npmjs.org
domain=pypi.org
domain=files.pythonhosted.org
```

CLI flags merge with config file values.

### Built-in default domains

`claude-sandbox` always allows:

- `api.anthropic.com`
- `mcp-proxy.anthropic.com`
- `statsig.anthropic.com`
- `platform.claude.com`

`codex-sandbox` always allows:

- `api.openai.com`
- `chatgpt.com`
- `ab.chatgpt.com`
- `auth.openai.com`
- `persistent.oaistatic.com`

### Filesystem restrictions

| Scope | Access |
|---|---|
| Home directory | Read/write (except sensitive dirs) |
| `~/.ssh`, `~/.aws`, `~/.kube`, `~/.docker` | Denied |
| `~/.gnupg`, `~/.gpg` | Read-only (GPG commit signing via pre-launched agent) |
| System paths (`/bin`, `/usr`, `/System`, `/Library`, `/opt/homebrew`) | Read-only |
| `/tmp`, `/private/tmp`, `$TMPDIR` | Read/write |

### CLI options

```
--project-dir DIR       Project directory (default: cwd)
--write-dir DIR         Additional writable directory (repeatable)
--read-dir DIR          Additional read-only directory (repeatable)
--allow-domain DOMAIN   Additional domain to allow HTTPS access (repeatable)
--claude-bin PATH       Path to claude binary (default: ~/.local/bin/claude)
--codex-bin PATH        Path to codex binary (codex-sandbox only)
--no-net-filter         Disable proxy/domain filtering; allow all outbound
--config PATH           Config file path (default: ~/.config/claude-sandbox/config)
--dry-run               Print the SBPL profile and exit
```

## Proxy management

### Reloading allowed domains at runtime

You can add or remove domains without restarting the sandbox. Edit the
domains JSON file (path printed at startup), then send `SIGHUP`:

```bash
# Find the domains file for the running proxy
ls /tmp/claude-sandbox-domains-*

# Edit it (it's a JSON array of domain strings)
# Then reload all running proxies:
claude-sandbox reload-proxies

# Or reload a specific proxy by port:
kill -HUP $(cat /tmp/claude-sandbox-proxy-<port>.pid)
```

The proxy logs a confirmation to `/tmp/claude-sandbox-proxy.log` on successful
reload.

### Auto-restart

A supervisor daemon monitors each proxy instance. If the proxy crashes, the
supervisor automatically restarts it on the same port — no manual intervention
needed and no loss of network access for the sandbox.

### PID file

Each proxy writes its PID to `/tmp/claude-sandbox-proxy-<port>.pid`. The port
and PID file path are printed at startup.

## Troubleshooting

Sandbox violations are logged to `/tmp/claude-sandbox-violations.log`.

Proxy blocks are logged to `/tmp/claude-sandbox-proxy.log` (append mode, safe
with parallel sandbox instances). Monitor with:

```bash
tail -f /tmp/claude-sandbox-proxy.log
```

### Known limitations

**Setuid binaries cannot run inside the sandbox.** macOS unconditionally blocks
setuid execution under `sandbox-exec`. This affects `/bin/ps` (used by tools
like `ccstatusline` for terminal width detection). A `ps` shim in `shims/` is
prepended to `PATH` to handle the TTY-detection patterns ccstatusline uses,
giving it dynamic terminal width support.

**GPG commit signing** works out of the box. The sandbox pre-launches `gpg-agent`
before entering the sandbox and allows Unix domain socket connections so GPG can
communicate with the agent. `~/.gnupg` is read-only inside the sandbox (public
keyring lookup); private key operations are handled by the agent running outside.

**macOS TMPDIR is not `/tmp`.** macOS sets `TMPDIR` to
`/private/var/folders/.../T/`, not `/tmp`. The sandbox automatically includes
the real `TMPDIR` path in the writable paths so tools like `bunx` can write
temp files.
