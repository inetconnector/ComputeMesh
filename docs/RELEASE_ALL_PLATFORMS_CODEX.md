# Codex: Entire ComputeMesh product release from GitHub main + immutable tag to live website

**Requested release outcome:** All current, working features and URLs of the ComputeMesh website, Android, Windows and Linux/NodeOS are synchronized in GitHub **main** and published to the website by **one verified tag**, never copied from an arbitrary Windows working directory.

**Repos (verified 2026-10-28):**
- Public binary/web/source: https://github.com/inetconnector/ComputeMesh ; default branch **main**, not master.
- Private control plane: https://github.com/inetconnector/ComputeMesh-ControlPlane ; default branch **main**, not master.
- Public release infrastructure draft PR: https://github.com/inetconnector/ComputeMesh/pull/139, branch `release/portal-platform-sync-20261028`.
- Current Windows checkout: `C:\Users\frede\Projekte\KI\ComputeMesh-ControlPlane\ComputeMesh`, branch `codex/kimi-nodeos-ota-20261027`, with many unrelated pending changes; DO NOT reset, stash, git-clean, blindly push or bulk-stage.

## 0. Preflight, backups and scope

Read `PRODUCT_RELEASE_QR_ONLY_GATE.md`, `UX_UNIFIED_PORTAL_IMPLEMENTATION.md`, `CODEX_WINDOWS_MESH_REPORT.md`, current `portal/` and Android + API sources in Windows checkout. Read the 3 new release-gate files in PR #139. Inventory the existing private and public main heads, commit ancestry, CI policies, release signature, product runtime and the actual Plesk deploy. Require current actual GitHub SHA in every report. No new artificial Owner-Key, no replacement release-signing key. Do not reveal secrets in reports.

A previous preflight returned:
- `RELEASE_OP_REJECTED: only main allowed; branch is codex/kimi-nodeos-ota-20261027`
- `RELEASE_OP_REJECTED: public HEAD mismatch`.
**Fix by clean reviewed integration, not bypassing preflights.**

## 1. One simple, functioning website

All pages in `portal/` must be checked (home, fleet, downloads and its index.html mirror, status, pricing, docs, models, marketplace, security, terms, privacy, imprint, contact, playground, webui, agent workspace, API login/registration, mobile). No broken internal links, no undefined onclick handlers, no duplicate IDs, no blank/dead buttons, no ignored API failures. Test responsive/mobile and desktop DE/EN.

The only normal fleet UI is `/fleet`: my computers, add device, revenue. Windows is a background node agent; miner uses NodeOS. Android pairs QR-ONLY from website `Meine Rechner > Handy > QR`, using short-lived one-use token, never an Owner-Key. Do not collapse "QR approved", "heartbeat accepted", "online", "inference ready", or payout to one fake status.

Remove or neutralize misleading claims like "all systems operational", fixed "v1.2.164" Android and fixed localhost:8080. Validate current live content by fetching origin URL after each staging deploy. Check compatibility with `portal-core.js`, `portal.js`, `portal-reference.js` and the page-specific inline scripts. `portal/downloads.html` and `portal/downloads/index.html` must be identical. Audit `portal/webui/` key propagation; do not ship with master Owner-Key copied to JS-readable cookies.

Static gate: `python tools/release/check_portal_routes.py --portal portal --artifacts-dir <staged_downloads>`. This validates first-party links and onclick functions; external domains must also be checked independently with real network requests (handle legitimate anti-bot/redirects as INCONCLUSIVE, not PASS).

## 2. Security and real component tests

- Backend `services/portal/tests/test_device_pairing.py`, `test_mobile_qr_contract.py`, `tools/appliance/tests/test_device_pairing_client.py` + gateway and owner rotation tests.
- Android `apps/android/gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug`, plus real QR scan on Android with signed heartbeat, AOSP minSdk 29, expiring/replayed QR, revoked device and app restart. Check AndroidKeyStore and crypto canonical message interoperability with Python.
- Windows Node and OpenAI tunnel: `127.0.0.1:8080` remains tunnel; ComputeMesh binds its own `8081` port; node ID `cm-win-mifcom-rtx3080` and GPU validated; no untrusted localhost token transmissions.
- Linux/NodeOS six RX470: boot, persistence, key and GPU inventory, signer, runtime, secure pairing, actual gateway accepted heartbeat; **no** claim of true inference without inference.
- Full project compile, lint, unit and API integration. Check image-generation, billing and KYC routes only with permitted test data; no live payments to test.
- Distinguish PASS, FAIL, SKIP, BLOCKED. No tests reported from a previous commit as testing current dirty files.

## 3. Integrate to GitHub main properly

- Separate dedicated clean worktree starting at exact remote `origin/main` for each public/private repository, no mutation of original dirty checkout.
- Extract and review only intended application/website/QR/backend changes, preserve foreign work and private secrets. Use reviewed PRs with normal CI, resolve conflicts deliberately, then merge into `main` **only after gate PASS**.
- Include PR #139 release verification files in public main (may need debugging before merge).
- Do not push arbitrary binaries or private settings into Git and do not skip branch-protection rules.
- Confirm `origin/main` immutable SHA after merge. This SHA will be the release source root, no silent follow-latest deployment.

## 4. Build ALL platforms from the approved source

Create reproducible release builds and a provenance report with SHA256 and exact version:
- Windows `ComputeMesh-Setup-x64.exe`, tested EXE with rollback.
- Android signed `ComputeMesh-Android.apk`, `ComputeMesh-Android.aab`, and `ComputeMesh-Android.json`, with verified production certificate fingerprint; QR-only functionality must match.
- Linux `computemesh-linux-x86_64.tar.gz`, `install.sh`.
- NodeOS `computemesh-nodeos-x86_64.iso`, `computemesh-nodeos-x86_64.img.xz`, `computemesh-nodeos-runtime-x86_64.tar.gz`, verified boot/provenance.
- Make the website show the actual installed/applicable versions and give only working download links; do not advertise a non-existing APK or unsupported image.
- Sign `portal/updates/version.json` using the **existing trusted release key** in protected coordinator, no new keys and no faked hash/signature. Signature is a gate; no partial release manifests.

## 5. Create and publish ONE immutable tag

After merging and final source/build verification, create an annotated semver tag `vX.Y.Z` on exact public main commit (use the next approved version; do not reuse existing tags). Private controlplane must record the corresponding pinned public commit in its main. There is NO branch called master on these repositories.

Tag GitHub Release must contain **all** signed installer files, signed version manifest, provenance/sha256 receipts and website source SHA. Re-fetch exact assets and independently hash and signature-verify. Failure means no public deployment and no altered stable tag.

Trigger `tagged-portal-release.yml` on main with that tag. It MUST pass link/onclick, Android build, Android signature pin, signed updater manifest, individual downloaded binary SHA/size, live gateway pairing tests and identity/owner integration tests. It emits `computemesh-website-verified.tar.gz`, a revision-identified deploy bundle. If the GitHub Action cannot run until available assets exist: first create a draft release and attach artifacts, then run the verifier. Do not publish "latest" before verified.

## 6. Codex deploys to Plesk only from verified tag bundle

Use existing approved `computemesh-plesk-*` task paths, not ad-hoc unreviewed scripts. Upload to a **staging** destination first, test all clean URLs and session/cookie flows using desktop/mobile, check Android QR display under CSP, simulate pair + heartbeat only using designated test fleet, and compare all binary HTTP Download hashes to the tag manifest. Confirm no PHP/Apache/nginx rewrite collision. Verify service-worker/cache headers and version.json availability.

Once green, back up live public_html, perform atomic swap of verified portal bundle and download files, clear only the relevant cache, run live smoke checks for 200/302 expected, file SHA, QR-to-account E2E, gateway online and security headers; auto-roll back on regressions. DO NOT deploy a new gateway backend or set `COMPUTEMESH_ENABLE_DEVICE_PAIRING=1` until signed QR end-to-end tests have passed in staging and admin authorization is checked.

## 7. Exact output / no invented result

Write `RELEASE_ALL_PLATFORMS_REPORT.md` with:
- both main SHAs, PRs, tag and actual release URL;
- tested commands and exit codes, service/OS/GPU E2E evidence;
- every installer actual version/bytes/SHA/signature and direct tested URL;
- link audit result and all external links not reliably verified;
- live site HTTP status and validated download digest after cache clear;
- feature flags, backend version, portal commit, Android version, NodeOS version, Windows version;
- rollback backup location and any remaining failures.

Flags: `git_main_synced`, `release_tag_created`, `all_platform_artifacts_verified`, `release_signature_valid`, `android_qr_e2e_passed`, `nodeos_e2e_passed`, `website_link_audit_passed`, `plesk_staging_passed`, `production_deployed`, `production_rollback_ready` with boolean and evidence. If any P0 absent, `production_deployed=false` and give the precise blocker. Do not say 'done' for file edits or theoretical tests.

**Authorization:** The user requested main/tag synchronization and Codex deployment after tests. Do not ask for a separate trivial confirmation for each step. Never reveal or rotate confidential keys. The original Windows EXE and miner remain untouched until their own tests and backups are ready.
