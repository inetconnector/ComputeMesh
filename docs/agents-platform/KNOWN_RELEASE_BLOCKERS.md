# Known Agents Platform Release Blockers

## BLOCKER-001 — Portal loads forbidden third-party Google Fonts

**Status:** OPEN — pre-existing on `main`, not introduced by Agents Platform.

The full `python run_all_tests.py` release gate currently reports 774/775 tests passing. The only failing test is:

`services.portal.tests.test_portal_server.TestPortalServer.test_portal_html_has_no_forbidden_third_party_resources`

The baseline file `portal/ai-auth.html` contains browser requests to:

- `fonts.googleapis.com`
- `fonts.gstatic.com`

The existing Portal security test explicitly forbids those origins. The test must not be weakened to make the branch green.

### Acceptable resolution

Remove the third-party browser font dependencies (using existing/system/local font fallbacks or repository-hosted font assets), then run the Portal test and the full ComputeMesh regression again.

### Release rule

Until this blocker is resolved or deliberately accepted through the repository's normal security/release governance, the AgentsPlatform branch is not recorded as fully release-ready even though Agents Platform-specific, MCP and private ControlPlane gates pass.
