# HiveUp CI rollout comparison

## Purpose

This one-off local comparison measures the rollout delta between the released
`v2` integration CI tooling and Python HiveUp. It covers every public integration
without adding permanent shadow CI.

## Fixed inputs

| Input | Commit |
| --- | --- |
| Released tooling tag `v2` | `c929fa6db69d61022f5da4b39edbaa9cb62720b4` |
| Python HiveUp | `3040c4fa0044891cd5b37252a04b9bccfa4ca822` |
| Public integrations | `d1ac5b7fdeb3ec1ad091f183453e358bc70e8c46` |
| PR-style base ref | `44c2719538cf47d8cedc10ec397aed1da4a09fa6` |

Each released-tooling run used a clean Python 3.13 environment to model a fresh
single-integration GitHub Action invocation. The old combined result ran the
exact released structure, code, test, README, and version scripts. The new
result ran the installed wheel's full `hiveup ci` profile with the same base
reference. All 97 immediate integration directories containing `config.json`
were included, and no command timed out.

## Aggregate delta

| Result | Integrations |
| --- | ---: |
| Pass released CI / pass HiveUp | 25 |
| Fail released CI / fail HiveUp | 25 |
| Pass released CI / fail HiveUp | 0 |
| Fail released CI / pass HiveUp | 47 |

### Pass both (25)

`agno-agent`, `api-call`, `companies-register`, `doc-maker`, `elevenlabs`,
`facebook`, `fathom`, `google-ads`, `google-business-profie`, `google-chat`,
`google-docs`, `google-tasks`, `heartbeat`, `jira`, `lumin-pdf`,
`microsoft-powerpoint`, `notion`, `nzbn`, `powerbi`, `reddit`,
`rss-reader-atoma-ah-fetch`, `rss-reader-feedparser`, `slider`, `teams`, and
`tiktok`.

### Fail both (25)

`app-business-reviews`, `bigquery`, `circle`, `code-analysis`, `float`, `gong`,
`google-analytics`, `google-looker`, `google-search-console`, `heygen`,
`humanitix`, `mailchimp`, `microsoft-excel`, `microsoft-planner`,
`microsoft-word`, `pipedrive`, `productboard`, `retail-express`,
`shopify-admin`, `shopify-customer`, `shopify-storefront`, `spreadsheet-tools`,
`stripe`, `webcal`, and `xero`.

These are existing CI debt. Reasons do not always align because HiveUp removes
obsolete structural checks while adding formatting, import, audit, and schema
checks. Substantive findings remain blocking.

### Newly blocked by HiveUp (0)

No existing public integration passes the released CI while failing HiveUp.

The initial comparison found 16 such integrations because the released test
runner silently succeeds when no canonical `tests/test_*_unit.py` file exists.
HiveUp now uses the PR base ref to preserve that historical state: an existing
integration without canonical tests receives a non-blocking warning, while a
new integration without canonical tests fails. Scaffolds continue to generate
canonical unit tests. This avoids an integration migration while preventing new
zero-test integrations from entering the repository.

### Newly passing with HiveUp (47)

`active-campaign`, `asana`, `aws`, `bitly`, `box`, `calendly`, `canva`,
`clickup`, `coda`, `dropbox`, `eventbrite`, `fergus`, `freshdesk`, `freshsales`,
`front`, `ghost`, `github`, `gitlab`, `gmail`, `google-calendar`, `google-forms`,
`google-sheets`, `grammarly`, `hackernews`, `harvest`, `hubspot`, `instagram`,
`linkedin`, `linkedin-ads`, `microsoft365`, `missive`, `monday-com`, `netlify`,
`perplexity`, `projectworks`, `salesforce`, `substack`, `supabase`, `supadata`,
`toggl`, `trello`, `typeform`, `whatsapp`, `x`, `youtube`, `zoho`, and `zoom`.

All 47 fail the released structure validator because it requires
`tests/context.py`. HiveUp uses isolated environments and the current SDK-aligned
shared fixture/scaffold model, so that obsolete helper file is not required.
Removal of this old structural requirement should be explicitly approved as a
rollout policy decision.

## Regression found and fixed

The initial comparison had one additional pass-old/fail-new integration:
`nzbn`. Its tests legitimately import `context` from `tests/context.py`, but the
static import resolver considered only the integration root and parent.

HiveUp now also resolves modules beside the importing source file. The fix is
covered by a regression test. Installed-wheel verification confirms that NZBN
passes imports, all 42 unit tests, and full `hiveup ci`.

The final installed-wheel rerun covered all 97 integrations after the
compatibility policy was implemented: 72 passed, 25 failed, no command timed
out, and the failed set exactly matched the previous fail-both set. No likely
HiveUp regression or unresolved tooling issue remains.

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

The floating `v2` tag can move without newly blocking any existing public
integration represented by the fixed snapshot. The 25 integrations that fail
HiveUp also fail released CI today, though HiveUp may expose different or
additional reasons within that already-failing group. New integrations are
intentionally held to the canonical unit-test requirement.

No integration source changes or legacy tooling changes are part of this
comparison.
