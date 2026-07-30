# HiveUp CI rollout comparison

## Purpose

This one-off local comparison measures the rollout delta between the released
`v2` integration CI tooling and Python HiveUp. It covers every public integration
without adding permanent shadow CI.

## Fixed inputs

| Input | Commit |
| --- | --- |
| Remote floating tooling tag `v2` | `3e141f9332408c7d823ccdedc91d47e46fa828c4` |
| Python HiveUp | `3040c4fa0044891cd5b37252a04b9bccfa4ca822` |
| Public integrations | `d1ac5b7fdeb3ec1ad091f183453e358bc70e8c46` |
| PR-style base ref | `44c2719538cf47d8cedc10ec397aed1da4a09fa6` |

The floating tag was resolved from the remote immediately before the run rather
than from a potentially stale local tag. Each released-tooling run used an
isolated Python 3.13 environment to model a fresh single-integration GitHub
Action invocation. The current combined result ran the exact released
structure, code, test, README, and version scripts. The new result ran the
installed wheel's full `hiveup ci` profile with the same base reference. All 97
immediate integration directories containing `config.json` were included, and
no command timed out. A live no-op Asana PR independently confirmed that the
floating action accepts `tests/conftest.py` and matches the local result.

## Aggregate delta

| Result | Integrations |
| --- | ---: |
| Pass current floating CI / pass HiveUp | 72 |
| Fail current floating CI / fail HiveUp | 24 |
| Pass current floating CI / fail HiveUp | 1 |
| Fail current floating CI / pass HiveUp | 0 |

### Pass both (72)

`active-campaign`, `agno-agent`, `api-call`, `asana`, `aws`, `bitly`, `box`,
`calendly`, `canva`, `clickup`, `coda`, `companies-register`, `doc-maker`,
`dropbox`, `elevenlabs`, `eventbrite`, `facebook`, `fathom`, `fergus`,
`freshdesk`, `freshsales`, `front`, `ghost`, `github`, `gitlab`, `gmail`,
`google-ads`, `google-business-profie`, `google-calendar`, `google-chat`,
`google-docs`, `google-forms`, `google-sheets`, `google-tasks`, `grammarly`,
`hackernews`, `harvest`, `heartbeat`, `hubspot`, `instagram`, `jira`,
`linkedin`, `linkedin-ads`, `lumin-pdf`, `microsoft-powerpoint`,
`microsoft365`, `missive`, `monday-com`, `netlify`, `notion`, `nzbn`,
`perplexity`, `powerbi`, `projectworks`, `reddit`,
`rss-reader-atoma-ah-fetch`, `rss-reader-feedparser`, `salesforce`, `slider`,
`substack`, `supabase`, `supadata`, `teams`, `tiktok`, `toggl`, `trello`,
`typeform`, `whatsapp`, `x`, `youtube`, `zoho`, and `zoom`.

### Fail both (24)

`app-business-reviews`, `bigquery`, `circle`, `code-analysis`, `float`, `gong`,
`google-analytics`, `google-looker`, `google-search-console`, `heygen`,
`mailchimp`, `microsoft-excel`, `microsoft-planner`, `microsoft-word`,
`pipedrive`, `productboard`, `retail-express`, `shopify-admin`,
`shopify-customer`, `shopify-storefront`, `spreadsheet-tools`, `stripe`,
`webcal`, and `xero`.

All 24 fail Ruff formatting in both implementations. `code-analysis` also
reports the known-vulnerable `pypdf2 3.0.1` dependency. These are existing CI
debt rather than rollout regressions.

### Newly blocked by HiveUp (1)

`humanitix` passes current floating CI but fails HiveUp's broader static import
scan because `tests/test_humanitix_integration.py` imports
`curl_cffi.requests.AsyncSession`. `curl_cffi` is not declared in the
integration's requirements. The import is inside an opt-in live test, so the
current unit-test runner never imports it, while HiveUp scans the file
statically. The live test itself is skipped without `HUMANITIX_API_KEY`, and
Humanitix's 40 unit tests pass in HiveUp.

This is the one remaining rollout policy decision: either exclude opt-in live
integration tests from HiveUp's static import scan, or regard their undeclared
dependencies as blocking. No public integration changes are included here.

### Newly passing with HiveUp (0)

Current floating CI already accepts either `tests/context.py` or
`tests/conftest.py`, so removing the legacy-only requirement creates no delta.

## Regression found and fixed

An earlier development comparison found an import-resolution regression in
`nzbn`. Its tests legitimately import `context` from `tests/context.py`, but the
static import resolver considered only the integration root and parent.

HiveUp now also resolves modules beside the importing source file. The fix is
covered by a regression test. Installed-wheel verification confirms that NZBN
passes imports, all 42 unit tests, and full `hiveup ci`.

The final installed-wheel rerun covered all 97 integrations after the
compatibility policy was implemented: 72 passed, 25 failed, and no command
timed out. The current floating scripts passed 73 and failed 24. Humanitix is
the only behavioral mismatch requiring a policy decision before rollout.

## Rollout policy decisions

The rollout policies are:

1. **Canonical unit tests:** preserve the missing-test state of existing
   integrations as a warning when a base ref proves they already exist; require
   canonical tests for new integrations.
2. **Legacy context helper:** do not require `tests/context.py`. Current
   SDK-aligned scaffolds and isolated tests use the shared fixture model, while
   legacy helpers remain supported when present.
3. **Blocking correctness checks:** keep syntax, unresolved imports, known
   vulnerabilities, failing tests, and deployment/package integrity blocking.
4. **Staged debt:** formatting, deprecated SDK pins, old test naming, and
   historical config/code drift are candidates for warning-first rollout or
   separate remediation PRs.

## Recommendation

Do not move the floating `v2` tag to the HiveUp implementation until the
Humanitix live-test import policy is decided. Apart from Humanitix, the fixed
snapshot has no newly blocked integration: 24 fail both implementations and 72
pass both. New integrations are intentionally held to the canonical unit-test
requirement.

No integration source changes or legacy tooling changes are part of this
comparison.
