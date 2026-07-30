# HiveUp CI rollout comparison

## Purpose

This one-off local comparison measures the rollout delta between the released
`v2` integration CI tooling and Python HiveUp. It covers every public integration
without adding permanent shadow CI.

## Fixed inputs

| Input | Commit |
| --- | --- |
| Released tooling tag `v2` | `c929fa6db69d61022f5da4b39edbaa9cb62720b4` |
| Python HiveUp | `858b61fbaa06bc1a18b0acc768be4e4e003fe659` |
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
| Pass released CI / pass HiveUp | 9 |
| Fail released CI / fail HiveUp | 25 |
| Pass released CI / fail HiveUp | 16 |
| Fail released CI / pass HiveUp | 47 |

### Pass both (9)

`agno-agent`, `doc-maker`, `elevenlabs`, `lumin-pdf`, `notion`, `nzbn`,
`rss-reader-atoma-ah-fetch`, `slider`, and `teams`.

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

### Newly blocked by HiveUp (16)

`api-call`, `companies-register`, `facebook`, `fathom`, `google-ads`,
`google-business-profie`, `google-chat`, `google-docs`, `google-tasks`,
`heartbeat`, `jira`, `microsoft-powerpoint`, `powerbi`, `reddit`,
`rss-reader-feedparser`, and `tiktok`.

All 16 pass released CI because its test runner silently succeeds when no
canonical `tests/test_*_unit.py` file exists. Full `hiveup ci` currently treats
the absence of a canonical unit-test file as blocking. Other notices shown for
some of these integrations—deprecated SDK pins, recommended config fields, and
potentially unused scopes—remain warnings and are not the blocking delta.

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

No likely HiveUp regression, unresolved tooling issue, or timeout remains.

## Rollout policy decisions

Before moving the floating Action tag, decide the following explicitly:

1. **Canonical unit tests:** either migrate the 16 integrations, grandfather
   their existing missing-test state, or initially keep absence warning-only.
2. **Legacy context helper:** approve removal of mandatory `tests/context.py`.
   Current SDK-aligned scaffolds and isolated tests do not require it.
3. **Blocking correctness checks:** keep syntax, unresolved imports, known
   vulnerabilities, failing tests, and deployment/package integrity blocking.
4. **Staged debt:** formatting, deprecated SDK pins, old test naming, and
   historical config/code drift are candidates for warning-first rollout or
   separate remediation PRs.

## Recommendation

Do not move the floating `v2` tag until the first two policy decisions are made.
The implementation delta itself is understood: the only discovered import
regression is fixed, existing substantive failures remain visible, and the
remaining newly blocking group has one common missing-unit-test cause.

No integration source changes or legacy tooling changes are part of this
comparison.
