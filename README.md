# claude-code-sandbox

Native macOS sandbox for [Claude Code](https://claude.ai/code). Restricts
filesystem and network access using `sandbox-exec` (SBPL profiles) and a
local HTTPS CONNECT proxy for domain-level filtering.

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

Installs `claude-sandbox` to `~/.local/bin/` (ensure it's on your `PATH`)
and creates a default config at `~/.config/claude-sandbox/config` if none exists.

To install elsewhere: `PREFIX=/usr/local/bin ./install.sh`

## Usage

```bash
# Run from a project directory
cd ~/my-project
claude-sandbox

# Or specify a project directory
claude-sandbox --project-dir ~/my-project

# Pass arguments to claude
claude-sandbox -- -p "fix the tests"

# Additional writable directory for this session
claude-sandbox --write-dir ~/other-project

# Allow an extra domain for this session
claude-sandbox --allow-domain extra.example.com

# Preview the generated SBPL profile
claude-sandbox --dry-run
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

Always allowed, no config needed:

- `api.anthropic.com`
- `mcp-proxy.anthropic.com`
- `statsig.anthropic.com`

### Filesystem restrictions

| Scope | Access |
|---|---|
| Home directory | Read/write (except sensitive dirs) |
| `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.kube`, `~/.docker` | Denied |
| System paths (`/bin`, `/usr`, `/System`, `/Library`, `/opt/homebrew`) | Read-only |
| `/tmp`, `/private/tmp`, `$TMPDIR` | Read/write |

### CLI options

```
--project-dir DIR       Project directory (default: cwd)
--write-dir DIR         Additional writable directory (repeatable)
--read-dir DIR          Additional read-only directory (repeatable)
--allow-domain DOMAIN   Additional domain to allow HTTPS access (repeatable)
--claude-bin PATH       Path to claude binary (default: ~/.local/bin/claude)
--config PATH           Config file path (default: ~/.config/claude-sandbox/config)
--dry-run               Print the SBPL profile and exit
```

## Troubleshooting

Sandbox violations are logged to `/tmp/claude-sandbox-violations.log`.

Proxy blocks are logged to `/tmp/claude-sandbox-proxy.log`. Monitor them with:

```bash
tail -f /tmp/claude-sandbox-proxy.log
```

### Known limitations

**Setuid binaries cannot run inside the sandbox.** macOS unconditionally blocks
setuid execution under `sandbox-exec`. This affects `/bin/ps` (used by tools
like `ccstatusline` for terminal width detection). The wrapper passes `COLUMNS`
into the environment as a workaround.

**Terminal width is captured at startup.** If you resize the terminal after
launching, the status line width won't update. Restart `claude-sandbox` to pick
up the new size.

**macOS TMPDIR is not `/tmp`.** macOS sets `TMPDIR` to
`/private/var/folders/.../T/`, not `/tmp`. The sandbox automatically includes
the real `TMPDIR` path in the writable paths so tools like `bunx` can write
temp files.
