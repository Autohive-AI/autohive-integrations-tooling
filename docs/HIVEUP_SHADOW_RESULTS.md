# HiveUp local shadow comparison

## Purpose

This one-off comparison checked the Python HiveUp rewrite against the unchanged
legacy .NET CLI using real integrations. It was run locally rather than added as
a permanent CI job. Generated environments, logs, and archives were kept under
`/tmp` and removed after each run.

## Fixed inputs

| Input | Commit |
| --- | --- |
| Initial Python HiveUp comparison | `b91b79774a37aab4247d941714e8f99adaf91f85` |
| Final Python HiveUp code | `a8c90d12314ab3134b8b0b992f65f5925291486f` |
| Legacy .NET HiveUp `origin/master` | `b8d999b3b1492f6c7284f3ed31a7ec6b7882f01b` |
| Integrations `origin/master` | `d1ac5b7fdeb3ec1ad091f183453e358bc70e8c46` |

The Python wheel was built and installed into a clean Python 3.13 environment.
The .NET CLI was built from a detached worktree and invoked directly without a
global installation or source changes. Each integration was copied separately
for each tool while preserving its original directory basename.

## Selected integrations

| Integration | Coverage reason |
| --- | --- |
| `api-call` | No authentication, SDK-only dependencies, legacy SDK/tests |
| `active-campaign` | Custom API-key authentication, SDK-only dependencies |
| `shopify-customer` | OAuth2 PKCE and older test/import conventions |
| `gmail` | Platform authentication and Google dependencies |
| `aws` | Modular `actions/` layout and pure-Python dependencies |
| `box` | Platform authentication and native `aiohttp` dependencies |
| `code-analysis` | Large native dependency tree and security auditing |

## Final behavioral results

The .NET columns record the unchanged baseline. Python results include the
environment fixes discovered during the comparison.

| Integration | .NET validate | .NET package | Python validate | Python test | Python package |
| --- | --- | --- | --- | --- | --- |
| `api-call` | Pass | Pass | Fail | Pass with no-tests warning | Fail |
| `active-campaign` | Pass | Pass | Fail on tests | Fail: missing `make_context` fixture | Pass |
| `shopify-customer` | Fail: unsupported auth | Fail | Fail | Pass, 31 tests | Fail |
| `gmail` | Pass | Pass | Pass with warnings | Pass, 110 tests | Pass |
| `aws` | Fail: modular actions missed | Pass | Pass with warning | Pass, 37 tests | Pass |
| `box` | Pass | Pass | Pass with warning | Pass, 38 tests | Pass |
| `code-analysis` | Pass | Pass | Fail | Pass, 7 tests | Fail |

Packaging intentionally runs the deployment checks rather than the complete CI
test and audit suite. ActiveCampaign can therefore package even though its
existing unit-test fixtures are incomplete.

## Python regressions found and fixed

### SDK configuration in isolated test environments

Older integrations call `Integration.load()` without an explicit config path.
Installed SDK versions resolve that default relative to their own package
location, which differs between a deployment ZIP and a cached virtual
environment. Tests therefore initially failed with a missing cached-environment
`config.json`.

HiveUp now mirrors the integration config to the SDK's inferred deployment
location before invoking tests. This is isolated per cached integration
environment and refreshes from the current integration config on every run.

### Package-style integration imports

The isolated pytest process did not receive the integration root and parent as
import locations. This broke real imports such as `gmail.gmail` and `box.box`.
HiveUp now supplies those paths only to the child process and runs it from the
integration root, without changing the CLI process's import state.

### Hyphenated integration roots containing `__init__.py`

Pytest attempted to collect roots such as `active-campaign` as Python packages,
although a hyphenated directory cannot be a Python package name and the root
package context does not exist in the deployment ZIP. HiveUp now tests a
temporary source copy with that root package marker removed. The original source
is never modified.

Regression tests cover all three cases. The final tooling suite contains 75
passing tests.

## Package comparison

Both tools produced archives for ActiveCampaign and AWS during the initial
comparison. The Python archives met the backend package contract:

- Python 3.13 and `manylinux2014_x86_64`
- compatible wheels only
- source, config, icon, README, and requirements at ZIP root
- dependencies under `dependencies/`
- root-level configured entry point
- no injected `main.py`
- no integration tests, `.pyc`, or `__pycache__`
- native extensions identified as ELF x86-64 CPython 3.13 files
- byte-identical output across repeated builds

| Archive | Files | Dependency files | Native extensions |
| --- | ---: | ---: | ---: |
| ActiveCampaign .NET | 447 | 443 | 8 |
| ActiveCampaign Python | 297 | 291 | 8 |
| AWS .NET | 2,811 | 2,800 | 8 |
| AWS Python | 2,466 | 2,453 | 8 |

The legacy archives included 152 and 347 generated `.pyc` files respectively.
The Python archives excluded them and included root README and requirements
files omitted by the legacy packager.

Files such as `aiohttp.test_utils` and `jsonschema/benchmarks` remain in the
Python archive because they are contents of upstream wheels. HiveUp does not
delete importable modules from compatible wheels based only on test-like names.

## Accepted behavioral differences

The following differences are intentional and are not parity regressions:

- Python HiveUp performs syntax, import, lint, formatting, security, dependency
  audit, config synchronization, fetch-pattern, and test checks absent from the
  legacy validator.
- Python packaging validates the deployment contract before building; the .NET
  tool can package AWS despite its own validator rejecting the modular layout.
- Python packages are deterministic and exclude development/cache artifacts.
- Diagnostics and archive bytes do not need to match the .NET implementation.
- `hiveup test`, `check`, `ci`, and `doctor` have no direct .NET equivalents.

## Remaining integration findings

These are findings in the selected integrations rather than HiveUp regressions:

- `api-call` uses SDK 1.0.2, has no discoverable `_unit.py` test, and retains a
  legacy `context` import.
- `active-campaign` unit tests require an unavailable `make_context` fixture.
- `shopify-customer` uses `oauth2_pkce`, has a legacy `context` import, README
  formatting drift, and config/code schema drift.
- `code-analysis` has an E402 lint violation, README formatting drift, and pins
  vulnerable `PyPDF2` 3.0.1 (`PYSEC-2026-1835`, fixed in 3.9.0).
- Several integrations pin deprecated SDK 2.0.0 instead of 2.0.1 or later.

No changes to these integrations or to the legacy .NET CLI are included in the
Python HiveUp rewrite.

## Conclusion

The local comparison exposed three test-environment compatibility regressions,
all now fixed and verified against the affected real integrations. Remaining
failures are either deliberately stricter Python checks or existing integration
issues. No permanent shadow CI workflow is required.
