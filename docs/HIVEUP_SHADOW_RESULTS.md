# HiveUp all-public shadow comparison

## Purpose

This one-off comparison checked the Python HiveUp rewrite against the unchanged
legacy .NET CLI using every public integration. It was run locally rather than
added as a permanent CI job. Generated environments, logs, and archives were
kept under `/tmp` and removed after the results were collected.

## Fixed inputs

| Input | Commit |
| --- | --- |
| Initial all-public Python comparison | `1974c03515df9d0d6f6171046d9c62a7476fd6a7` |
| Final Python HiveUp verification | `6e0561a31c16b2a6f179ab1ca3fc93dd28315c94` |
| Legacy .NET HiveUp `origin/master` | `b8d999b3b1492f6c7284f3ed31a7ec6b7882f01b` |
| Integrations `origin/master` | `d1ac5b7fdeb3ec1ad091f183453e358bc70e8c46` |

The Python wheel was built and installed into a clean Python 3.13 environment.
The .NET CLI was built from a detached worktree and invoked directly without a
global installation or source changes. All 97 immediate child directories with
a `config.json` were copied separately for each tool while preserving their
original directory basename. No integration was omitted.

## Complete scope

`active-campaign`, `agno-agent`, `api-call`, `app-business-reviews`, `asana`,
`aws`, `bigquery`, `bitly`, `box`, `calendly`, `canva`, `circle`, `clickup`,
`coda`, `code-analysis`, `companies-register`, `doc-maker`, `dropbox`,
`elevenlabs`, `eventbrite`, `facebook`, `fathom`, `fergus`, `float`,
`freshdesk`, `freshsales`, `front`, `ghost`, `github`, `gitlab`, `gmail`,
`gong`, `google-ads`, `google-analytics`, `google-business-profie`,
`google-calendar`, `google-chat`, `google-docs`, `google-forms`, `google-looker`,
`google-search-console`, `google-sheets`, `google-tasks`, `grammarly`,
`hackernews`, `harvest`, `heartbeat`, `heygen`, `hubspot`, `humanitix`,
`instagram`, `jira`, `linkedin`, `linkedin-ads`, `lumin-pdf`, `mailchimp`,
`microsoft-excel`, `microsoft-planner`, `microsoft-powerpoint`,
`microsoft-word`, `microsoft365`, `missive`, `monday-com`, `netlify`, `notion`,
`nzbn`, `perplexity`, `pipedrive`, `powerbi`, `productboard`, `projectworks`,
`reddit`, `retail-express`, `rss-reader-atoma-ah-fetch`,
`rss-reader-feedparser`, `salesforce`, `shopify-admin`, `shopify-customer`,
`shopify-storefront`, `slider`, `spreadsheet-tools`, `stripe`, `substack`,
`supabase`, `supadata`, `teams`, `tiktok`, `toggl`, `trello`, `typeform`,
`webcal`, `whatsapp`, `x`, `xero`, `youtube`, `zoho`, and `zoom`.

## Final behavioral results

The .NET columns record the unchanged baseline. Python validation and tests were
rerun after fixing every test-runner regression discovered by the comparison.

| Operation | Success | Failure | Timeout |
| --- | ---: | ---: | ---: |
| .NET `validate` | 91 | 6 | 0 |
| Python `validate` | 54 | 43 | 0 |
| Python-only `test` | 97 | 0 | 0 |
| .NET `package` | 95 | 2 | 0 |
| Python `package` | 55 | 42 | 0 |

Packaging intentionally runs the deployment checks rather than the complete CI
test and audit suite. Python package failures are therefore not expected to map
one-to-one to full validation failures.

The 43 remaining Python validation failures contain concrete stricter-check or
integration findings. The comparison found no remaining likely Python
regression, unresolved tooling issue, or timeout.

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

### Shared pytest configuration in temporary source copies

The temporary copy initially lost repository-level pytest configuration. That
removed shared fixtures from the root `conftest.py` and `asyncio_mode = "auto"`
from `pyproject.toml`. HiveUp now copies only applicable pytest project files to
the temporary root. It does not copy `.env` files or credentials.

Regression tests cover all four cases. The final tooling suite contains 75
passing tests.

## Package comparison

Both tools produced archives for 55 integrations. The Python archives met the
backend package contract:

- Python 3.13 and `manylinux2014_x86_64`
- compatible wheels only
- source, config, icon, and README at ZIP root
- dependencies under `dependencies/`
- root-level configured entry point
- no injected `main.py`
- no integration tests, `.pyc`, or `__pycache__`
- native extensions identified as ELF x86-64 CPython 3.13 files
- deterministic output, verified through representative repeated builds

`requirements.txt` is used to stage dependencies but omitted from the deployment
ZIP so container processing consumes the expanded `dependencies/` tree instead
of treating it as an offline wheel index.

| Paired package measurement | .NET | Python |
| --- | ---: | ---: |
| Archives compared | 55 | 55 |
| Total archive size | 352.9 MB | 278.6 MB |
| Median dependency files | 443 | 291 |
| Native extensions | 497 | 497 |
| Root README present | 0 | 55 |
| Root requirements present | 0 | 55 |

Both tools consistently retained the root entry point, config, and icon. Python
excluded cache and `.pyc` files in all paired archives, while the legacy
archives included them. Neither included integration-owned test directories.

Repeated Python packages were byte-identical for ActiveCampaign and AWS. The
corresponding .NET packages differed between builds. Spreadsheet Tools failed
Python validation consistently on both package attempts, while .NET produced
two different archives.

The two .NET package failures were `rss-reader-feedparser` and
`shopify-customer`, both caused by legacy polymorphic config discriminator
parsing. Python package failures were validation-gated rather than unexplained
packager crashes.

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

The .NET validator rejected six integrations: `aws`, `facebook`, `humanitix`,
`instagram`, `rss-reader-feedparser`, and `shopify-customer`. AWS demonstrates a
legacy validator defect: it misses actions in the modular `actions/` package but
packages the integration anyway.

Python validation reported findings in 43 integrations:

`api-call`, `app-business-reviews`, `bigquery`, `circle`, `code-analysis`,
`companies-register`, `facebook`, `fathom`, `float`, `gong`, `google-ads`,
`google-analytics`, `google-business-profie`, `google-chat`, `google-docs`,
`google-looker`, `google-search-console`, `google-tasks`, `heartbeat`, `heygen`,
`humanitix`, `jira`, `mailchimp`, `microsoft-excel`, `microsoft-planner`,
`microsoft-powerpoint`, `microsoft-word`, `notion`, `nzbn`, `pipedrive`,
`powerbi`, `productboard`, `reddit`, `retail-express`, `rss-reader-feedparser`,
`shopify-admin`, `shopify-customer`, `shopify-storefront`, `spreadsheet-tools`,
`stripe`, `tiktok`, `webcal`, and `xero`.

The failures include missing modern unit-test files or imports, deprecated SDK
constraints, Ruff and README formatting findings, dependency vulnerabilities,
and config/schema drift. Notion changed from pass to fail after shared pytest
configuration was correctly preserved because the repository's Ruff settings
expose an existing unused import in `tests/context.py`.

All 97 standalone Python test runs pass. None of the remaining validation or
package differences is classified as a likely HiveUp regression or unresolved
tooling issue.

No changes to these integrations or to the legacy .NET CLI are included in the
Python HiveUp rewrite.

## Conclusion

The all-public comparison exposed four test-environment compatibility issues,
all now fixed and verified across every public integration. Python HiveUp tests
pass for 97/97 integrations, package outputs match the backend contract, and no
likely Python regression remains. Validation failures are deliberately stricter
checks or existing integration findings. No permanent shadow CI workflow is
required.
