# Plan: `hiveup` — Python CLI for Autohive Integrations

Status: proposed design, ready for implementation handoff.

This document specifies a new Python CLI that replaces the .NET `hiveup` tool
(`autohive-integrations-cli`) and absorbs the validation scripts in this repo
(`autohive-integrations-tooling/scripts/`) into a single installable developer tool.

## Why

1. **One language, one ecosystem.** Integrations, the SDK, and all validation
   tooling are Python. The .NET CLI duplicates validation logic (worse than the
   Python scripts), requires the .NET SDK to install, and has drifted (no
   run/test support, packaging bugs, template inconsistencies).
2. **Validation is the bottleneck.** Non-validated integrations pile up because
   the current validation workflow is "run five separate scripts with the right
   args from the right directory". The CLI makes `hiveup validate` a single
   command that runs everything CI runs, locally, with auto-fix.
3. **CI and local should be the same code.** Today `action.yml` shells out to
   scripts; developers run the same scripts by hand with different args. The CLI
   becomes the single implementation both use, so "passes locally" means
   "passes in CI".

## Where it lives

**Recommendation: this repo (`autohive-integrations-tooling`), restructured as an
installable Python package.** Rationale:

- All the validation logic already lives here; the CLI is 70% a repackaging of it.
- The GitHub Action (`action.yml`) lives here and should call the same code.
- Versioning already tracks SDK major versions (tooling `2.x` targets SDK `2.x`).
- Avoids a third repo to keep in sync.

The .NET repo (`autohive-integrations-cli`) gets archived once this ships, with a
README pointer.

### New repo layout

```text
autohive-integrations-tooling/
├── pyproject.toml                  # package: autohive-cli, console script: hiveup
├── src/
│   └── hiveup/
│       ├── __init__.py             # __version__
│       ├── cli.py                  # Typer app, command registration
│       ├── commands/               # thin command layers (arg parsing, rendering)
│       │   ├── create.py
│       │   ├── validate.py
│       │   ├── check.py
│       │   ├── test.py
│       │   ├── run.py
│       │   ├── package.py
│       │   ├── auth.py
│       │   ├── doctor.py
│       │   └── ci.py
│       ├── core/
│       │   ├── results.py          # CheckMessage / CheckResult / RunReport models
│       │   ├── discovery.py        # unified integration discovery (all/changed/explicit)
│       │   ├── config.py           # config.json parsing + canonical JSON Schema
│       │   ├── project.py          # IntegrationProject: paths, entry point, metadata
│       │   └── gitutil.py          # base-ref diffing, changed dirs, git show/cat-file
│       ├── checks/                 # all validators, pure: take paths, return CheckResult
│       │   ├── structure.py        # ported from validate_integration.py
│       │   ├── code.py             # syntax, json validity, orchestration of tools
│       │   ├── imports.py          # ported from check_imports.py
│       │   ├── config_sync.py      # ported from check_config_sync.py
│       │   ├── fetch_pattern.py    # ported from check_fetch_pattern.py
│       │   ├── readme.py           # ported from check_readme.py (+ content checks, new)
│       │   ├── version_bump.py     # ported from check_version_bump.py
│       │   ├── hygiene.py          # NEW: TODO/print/commented-code/forbidden-file scan
│       │   ├── test_coverage.py    # NEW: action → unit-test mapping
│       │   └── tools.py            # subprocess wrappers: ruff, bandit, pip-audit, pytest
│       ├── runner/                 # NEW: local execution of integrations
│       │   ├── loader.py           # import entry_point, discover Integration instance
│       │   ├── executor.py         # execute actions / triggers / connected account
│       │   └── authstore.py        # local credential profiles (.hiveup/auth.json)
│       ├── testing/
│       │   └── pytest_runner.py    # ported from run_tests.py
│       ├── scaffold/
│       │   ├── engine.py           # template rendering (placeholder substitution)
│       │   └── templates/          # package data; default template synced with SDK
│       │       └── default/...
│       └── render/
│           ├── console.py          # Rich human output (tables, ✅/⚠️/❌)
│           ├── json_out.py         # --json machine output
│           ├── github.py           # ::error/::warning annotations
│           └── markdown.py         # PR comment (replaces render_comment.py)
├── scripts/                        # kept temporarily as thin shims → src/hiveup (see Migration)
├── tests/                          # existing fixtures in tests/examples/ reused as CLI test fixtures
├── action.yml                      # updated to install package and call `hiveup ci`
└── ruff.toml                       # stays; bundled as package data too
```

## Stack decisions

| Decision | Choice | Rationale |
|---|---|---|
| Python | 3.13+ | matches SDK requirement and existing tooling |
| CLI framework | **Typer** | subcommands, completion, help text with minimal boilerplate |
| Output | **Rich** | tables, panels, spinners; already the de-facto Python standard |
| Packaging | `pyproject.toml`, console script `hiveup` | `uv tool install autohive-cli` / `pipx install autohive-cli` |
| Distribution | PyPI (`autohive-cli`), plus `uvx autohive-cli` for zero-install | replaces install.sh/install.ps1 entirely |
| Schema validation | `jsonschema` (Draft 7) | matches SDK's validator |
| Lint/format/security | shell out to `ruff`, `bandit`, `pip-audit` as declared dependencies of the CLI | they're already the tools CI uses; installing them with the CLI removes the "pip install into current env" hack in `check_code.py` |
| Command name | keep **`hiveup`** | continuity with existing docs/muscle memory |

The SDK (`autohive-integrations-sdk`) is a **runtime dependency of the CLI**
(needed by `hiveup run` and `hiveup test`). Pin `~=2.0` for the 2.x tooling line;
when SDK 3.0 releases, tooling 3.0 pins `~=3.0`.

## Command reference

### `hiveup create <name>` and `hiveup init`

Scaffold a new integration (child directory vs. in-place). Carries over the .NET
flags and fixes its bugs:

```
hiveup create my-service [--template default] [--auth-type platform|custom|none]
                         [--auth-provider github] [--auth-scopes read,write]
                         [--modular]            # actions/ subfolder layout
                         [--no-input]           # fail instead of prompting (CI/agents)
hiveup init [--name X] [--force] [same flags]
```

Behavior:

- Interactive prompts (via Rich/Typer) when flags omitted, exactly like the .NET
  CLI, but every prompt has a flag equivalent so agents/CI can run non-interactively.
- **Name handling fixed**: directory name is `lowercase-hyphens`, module/file name
  is `lowercase_underscores`, config `name` matches directory, `display_name`
  prompted/derived. (The .NET CLI generated invalid Python for hyphenated names.)
- Template is synced with `integrations-sdk/samples/template`: includes
  `config.json`, `<module>.py`, `__init__.py`, `requirements.txt` (pinned
  `autohive-integrations-sdk~=2.0.1`), `README.md` (actually named `README.md`,
  fixing the `README_TEMPLATE.md` bug), `.gitignore` (`dependencies/`),
  `icon.png` placeholder (512×512), and a proper pytest test scaffold:
  `tests/__init__.py`, `tests/conftest.py` with the `mock_context` fixture pattern
  from `skills/writing-unit-tests`, and `tests/test_<module>_unit.py` that mocks
  `context.fetch` with `FetchResponse` — not the current script-style test.
- `--modular` generates the `actions/` package layout from
  `docs/manual/integration_structure.md`, with `Integration.load(config_path)`
  using an explicit path (the SDK's default path resolution only works when vendored).
- After generation, prints next steps: `hiveup validate`, `hiveup test`, `hiveup run`.

### `hiveup validate [dirs...]` — the flagship command

Runs the full CI-equivalent pipeline locally. This is the answer to the
validation bottleneck: one command, same checks as CI, ordered fast→slow,
with fix suggestions.

```
hiveup validate                      # auto-discover integrations under cwd (or cwd itself if it is one)
hiveup validate my-service other     # explicit dirs
hiveup validate --changed --base-ref origin/main   # only changed integrations (CI parity)
hiveup validate --fix                # auto-apply ruff fixes + format, then re-check
hiveup validate --json               # machine-readable results
hiveup validate --skip tests,audit   # skip named checks
hiveup validate --only structure,sync
```

Check suite (each is an independent named check returning a `CheckResult`):

| # | Check | Source | Fails on |
|---|---|---|---|
| 1 | `structure` | port of `validate_integration.py` | missing files, bad icon, bad config.json, missing tests/ |
| 2 | `syntax` | `py_compile` over all `.py` | syntax errors |
| 3 | `imports` | port of `check_imports.py`, run on **all** `.py` files (not just entry point — fixes current gap) | unresolvable imports |
| 4 | `json` | `json.load` all `.json` | invalid JSON |
| 5 | `lint` | `ruff check` with bundled config | lint errors (auto-fixable with `--fix`) |
| 6 | `format` | `ruff format --check` | formatting (auto-fixable with `--fix`) |
| 7 | `security` | `bandit -s B101` | findings |
| 8 | `audit` | `pip-audit -r requirements.txt` | known CVEs |
| 9 | `sync` | port of `check_config_sync.py` | config/code action mismatch; input drift fails for new integrations when `--base-ref` given |
| 10 | `fetch` | port of `check_fetch_pattern.py` | SDK-1-style `.data`-less fetch usage under SDK ≥2 |
| 11 | `tests` | port of `run_tests.py` (unit tests only) | test failures / dep-install failures; warns when no unit tests |
| 12 | `readme` | port of `check_readme.py` + **new content checks** | root README not updated for new integration; warns when integration README is missing action docs / auth section |
| 13 | `version` | port of `check_version_bump.py` (only with `--base-ref`) | version not bumped / not greater; warns on lower-than-recommended bump level |
| 14 | `hygiene` | **new** | warns on `print()` in production code, unresolved `TODO`/`FIXME`, committed `.env`/`__pycache__`/`.pyc`/`*.zip`, large commented-out blocks |
| 15 | `coverage-map` | **new** | warns when a config action has no unit test referencing it (`execute_action("<name>"` grep/AST) |

Checks 12–15 automate items from `INTEGRATION_CHECKLIST.md` that are manual today.
New checks start as warnings; promote to errors after a bake-in period.

Output: Rich table summarizing per-integration × per-check status, then grouped
detail for failures with concrete fix commands. Exit codes preserved: `0` pass
(warnings OK), `1` any check failed, `2` usage/processing error.

Dependency isolation: instead of `pip install`-ing each integration's
requirements into the current interpreter (current behavior, environment
pollution), the CLI creates a cached per-integration venv
(`~/.cache/hiveup/envs/<hash-of-requirements>`) using `uv` when available,
falling back to `venv` + `pip`. `audit`, `imports`, and `tests` run against that
env. `--no-isolation` opts out (used by CI, where env pollution is fine and speed
matters).

### `hiveup check <name> [dirs...]`

Run a single named check from the table above, for fast iteration:

```
hiveup check sync my-service --base-ref origin/main
hiveup check imports my-service
hiveup check version my-service --base-ref origin/main
```

Same renderers/flags as `validate` (`--json`, `--fix` where applicable).

### `hiveup test [dir]`

Test runner, superset of `run_tests.py`:

```
hiveup test                       # unit tests (test_*_unit.py), coverage table
hiveup test --integration         # runs test_*_integration.py with -m integration; loads .env
hiveup test --all
hiveup test -k "test_search"      # pass-through to pytest
hiveup test --watch               # rerun on file change (watchfiles)
```

- Unit mode: per-integration dep install (isolated env, as above), pytest with
  `--import-mode=importlib -m unit --cov`, summary table identical in spirit to
  `run_tests.py`.
- Integration mode: loads `.env` from the integration dir and repo root
  (python-dotenv), warns about env vars declared in `.env.example` but unset,
  never runs in `hiveup validate` or CI. Honors the `integration`/`destructive`
  marker conventions from the SDK skills.

### `hiveup run` — local action execution (new capability)

The biggest DX gap in the current tooling: there is no way to execute an action
against the real API without writing a throwaway script. This is also a
validation lever — developers who can trivially run actions locally submit
working integrations.

```
hiveup run my_action                                # prompts for inputs from input_schema
hiveup run my_action --inputs inputs.json           # or --input key=value (repeatable)
hiveup run my_action --auth-profile default
hiveup run --list                                   # list actions + triggers from config.json
hiveup run --trigger new_items --last-poll-ts 2026-07-01T00:00:00Z
hiveup run --connected-account
```

Mechanics (all verified against SDK internals):

1. Read `config.json`, resolve `entry_point`, import the module with the
   integration dir on `sys.path`.
2. Discover the `Integration` instance by scanning module globals for the first
   `isinstance(x, Integration)` (samples use varying variable names, so
   discovery-by-type is required; error clearly if zero or multiple found).
3. Build the **wrapped auth envelope** the SDK requires —
   `{"auth_type": "Custom"|"PlatformOauth2"|..., "credentials": {...}}` — from
   the auth store (below). For custom auth, map config `type: "custom"` →
   runtime `auth_type: "Custom"`; validate credentials against
   `config.auth.fields` before running so the user gets a clear error, not an
   SDK traceback.
4. Prompt for inputs interactively by walking `input_schema` (types, enums,
   required), or take `--inputs file.json` / `--input k=v`.
5. `async with ExecutionContext(auth=auth) as context:` →
   `integration.execute_action(name, inputs, context)`. Handle all three result
   shapes (`ACTION`, `ACTION_ERROR`, `VALIDATION_ERROR` with its `source` field)
   and the raise-instead-of-wrap behavior of polling triggers / connected account.
6. Pretty-print the `IntegrationResult`: status, `cost_usd` if present, data as
   syntax-highlighted JSON. `--json` for raw output. `--verbose` echoes each
   `context.fetch` call (method, URL, status) via a thin fetch wrapper.

**Auth store** (`runner/authstore.py`):

- Per-integration profiles in `<integration>/.hiveup/auth.json` (gitignored by
  scaffold; the `hygiene` check errors if it's ever committed) with optional
  user-global fallback `~/.config/hiveup/auth/<integration-name>.json`.
- `hiveup auth set [--profile default]` prompts for each field in
  `config.auth.fields` (password-masked for `format: password`); for platform
  OAuth it stores a raw access token supplied by the user (`--token` or prompt) —
  the CLI does not implement OAuth flows in v1.
- Values support `env:VAR_NAME` indirection so profiles can reference `.env`.

### `hiveup package [dir]`

Port of the .NET packaging with its bugs fixed:

```
hiveup package [dir] [-o out.zip] [--skip-validate] [--platform manylinux2014_x86_64] [--python-version 3.13]
```

- Runs `hiveup validate` first by default (fail = no package) — the .NET CLI didn't.
- Vendors deps into a **temp dir** (not `<integration>/dependencies`, which the
  .NET CLI created and deleted in-place) via
  `pip install -r requirements.txt --platform manylinux2014_x86_64 --python-version 3.13 --only-binary=:all: --target <tmp>`;
  prefers `uv pip` when available.
- Zip contents: all `.py` (excluding tests/venvs/caches — reuse the .NET exclude
  list), `config.json`, the single validated `icon.*`, `dependencies/**`. Honors
  nested `entry_point` paths consistently (validation and packaging disagreed in .NET).
- Deterministic output name `<name>-<version>.zip` in cwd unless `-o` given.

Note: production deploy targets (Lambda manylinux/3.13 assumptions) copied from
the .NET CLI — **confirm with the platform team** before implementation locks this in.

### `hiveup auth [dir]`

Add/update the `auth` block in `config.json` (port of the .NET command), now
with non-interactive flags (`--auth-type/--auth-provider/--auth-scopes`, custom
field specs via `--field name:label:password`). When "none" is chosen, the auth
key is **removed**, not set to `null` (fixes .NET behavior). Preserves key order
and formatting of the rest of config.json.

Subcommand `hiveup auth set` belongs to the runner credential store (see `run`).
Disambiguation: `hiveup auth` with no subcommand edits config; `hiveup auth set`
manages local credentials. (Implementer may instead choose `hiveup credentials`
for the store if the overload proves confusing.)

### `hiveup doctor`

Environment sanity: Python ≥3.13, ruff/bandit/pip-audit importable, git present,
`uv` availability, SDK version installed vs. pinned in the integration's
requirements, whether cwd looks like an integration or an integrations repo.
Prints versions and actionable remediation.

### `hiveup ci` (internal-facing)

What `action.yml` calls. Runs the same pipeline as
`validate --changed --base-ref <ref>` plus:

- `--github-annotations`: emit `::error file=...` / `::warning ...` lines.
- `--comment-file <path>`: render the sticky-PR-comment markdown (port of
  `render_comment.py`, but fed structured `CheckResult`s instead of env vars —
  also fixes "skipped renders as passed").
- `--output-file $GITHUB_OUTPUT`: write per-check outcomes for the composite action.
- Warnings are carried as structured data, not detected by grepping output for `⚠️`.

`get_changed_dirs.py` logic moves into `core/discovery.py` +
`core/gitutil.py` and is exposed as `hiveup ci --list-changed --base-ref X`.

## Core data model

Everything renders from one result model (no more print-based checks):

```python
@dataclass
class CheckMessage:
    severity: Literal["error", "warning", "info"]
    message: str
    file: str | None = None
    line: int | None = None
    fix_hint: str | None = None      # e.g. "run: hiveup validate --fix"

@dataclass
class CheckResult:
    check: str                        # "structure", "sync", ...
    integration: str
    status: Literal["passed", "warning", "failed", "error", "skipped"]
    messages: list[CheckMessage]
    duration_s: float
    raw_output: str = ""              # captured tool output (ruff/pytest/...)

@dataclass
class ValidationReport:
    results: list[CheckResult]
    # helpers: exit_code(), by_integration(), has_failures(), to_json()
```

Renderers (`render/`) consume `ValidationReport`: Rich console, JSON, GitHub
annotations, PR-comment markdown. Checks never print directly.

Unified discovery (`core/discovery.py`) replaces the three divergent mechanisms
(validate/run_tests/get_changed_dirs): a directory is an integration iff it
contains `config.json`; skip-list unified; modes = explicit dirs / all under
root / changed vs. base ref / cwd-is-an-integration.

## Canonical config.json schema

Today the schema exists only as prose + scattered checks (SDK parses some
fields, .NET validated others, `validate_integration.py` a third set). Ship a
single JSON Schema (`core/config_schema.json`) covering: `name`, `version`,
`description`, `display_name`, `entry_point`, `auth` (custom/platform/none
variants), `actions` (with `display_name`, `description`, `input_schema`,
`output_schema`), `polling_triggers` (with `polling_interval` format `\d+[smhd]`),
`supports_billing`, `supports_connected_account`. The `structure` check
validates against it; publish it so editors get IntelliSense via
`"$schema"` (scaffold includes the key). Upstreaming it to the SDK repo later is
desirable but not required for v1.

## Migration plan

1. **CI compatibility first.** `action.yml` switches from
   `python scripts/X.py` to `pip install <action_path> && hiveup ci ...`.
   Keep per-check outputs identical in name so downstream workflows don't break.
2. **Scripts become shims.** Each `scripts/*.py` keeps its CLI surface but
   delegates to `hiveup` internals, printing a deprecation note. Remove in the
   next major.
3. **Fixture reuse.** `tests/examples/*` (good-integration, Bad-Integration,
   config-mismatch, input-drift, etc.) become the CLI's own test fixtures;
   `self-test.yml` runs the CLI against them.
4. **Docs.** README, CONTRIBUTING, LOCAL_DEVELOPMENT rewritten around
   `hiveup`; SDK manual's "validate with ../autohive-integrations-tooling/scripts/..."
   references updated to `hiveup validate`.
5. **.NET CLI archived** with a pointer once `create/init/validate/package/auth`
   reach parity.

## Bugs in current tools that the port must fix (regression checklist)

From the .NET CLI:
- Duplicate nested `foreach` over dependency files in `PackageCommand` (dup zip entries).
- `README_TEMPLATE.md` never renamed to `README.md`.
- Hyphenated names generate invalid Python identifiers.
- `entry_point` handling inconsistent between validate (nested ok) and package (filename only).
- `"auth": null` written when choosing "none" in `hiveup auth`.
- Icon rules inconsistent between validate (`icon.*`, image ext) and package (any `icon*`).

From the Python scripts:
- `check_code.py`: pip install return codes ignored; duplicate error line on sync exit 2; imports checked only on entry point.
- `check_config_sync.py`: unreachable duplicate `return False`.
- `check_version_bump.py`: `f.endswith("test_.py")` test-exclusion typo.
- `check_fetch_pattern.py`: documented exit 2 never returned; docstring overstates detection.
- `render_comment.py`: skipped checks render as "Passed".
- `action.yml`: README check runs without guarding on empty `base_ref` (version check guards; readme doesn't).
- Template drift: SDK template `README.md` says `~=1.0.2` while `requirements.txt` says `~=2.0.0` — scaffold must have one source of truth.

## Implementation phases

Each phase ends runnable and shippable.

**Phase 1 — package skeleton + validate core.** `pyproject.toml`, Typer app,
result model, discovery, renderers (console + JSON); port `structure`,
`syntax`, `json`, `imports`, `sync`, `fetch` checks with fixtures from
`tests/examples/`. Deliverable: `hiveup validate` runs the static checks.

**Phase 2 — external-tool checks + test runner.** `lint`/`format`/`security`/
`audit` wrappers, `--fix`, isolated-env manager, `tests` check,
`hiveup test` (unit + integration + `-k`), `readme`/`version` git-based checks.
Deliverable: full CI parity locally.

**Phase 3 — CI integration.** `hiveup ci`, markdown comment renderer, GitHub
annotations, `action.yml` cutover, scripts→shims, `self-test.yml` on the CLI.
Deliverable: CI runs on the new CLI.

**Phase 4 — scaffold + package + auth.** `create`/`init` with the updated
template (incl. `--modular`), `package` with fixes, `auth` editing, `doctor`.
Deliverable: .NET CLI parity; archive it.

**Phase 5 — runner + new validation checks.** `hiveup run` (actions, triggers,
connected account), auth store, `hygiene` + `coverage-map` + README-content
checks (as warnings), `--watch`. Deliverable: full DX story.

## Explicitly out of scope for v1

- Publishing/deploying to the Autohive platform (no backend API exists in the
  current CLI; add `hiveup publish` + login/token flow when the platform exposes one).
- OAuth authorization flows in `hiveup run` (raw token entry only).
- A local platform emulator/web UI.
- Windows-specific installers (PyPI + uv/pipx covers all platforms).

## Open questions for the team

1. Package/vendoring target (`manylinux2014_x86_64`, Python 3.13) — confirm the
   production runtime before hardcoding.
2. Should tooling v2 (SDK 2.x) be the target, with SDK 3.0.0.dev0 pending? Plan
   assumes yes: build against 2.x, keep checks version-aware via requirements pin.
3. PyPI name: `autohive-cli` with command `hiveup` (plan default) — or publish as
   `hiveup` if the name is available?
4. Is `hiveup run` allowed to hit real APIs by default, or should it require an
   explicit `--live` flag? Plan default: real calls, since credentials are
   explicitly configured.
