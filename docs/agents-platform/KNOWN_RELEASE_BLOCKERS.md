# Known Agents Platform Release Blockers

## BLOCKER-001 — Portal loaded forbidden third-party Google Fonts

**Status:** RESOLVED on `AgentsPlatform`.

The full public release gate originally reported 774/775 tests passing because:

`services.portal.tests.test_portal_server.TestPortalServer.test_portal_html_has_no_forbidden_third_party_resources`

found browser requests in `portal/ai-auth.html` to:

- `fonts.googleapis.com`
- `fonts.gstatic.com`

The security test was not weakened. The external font links were removed and the page now uses the existing CSS font-family declarations with local/system fallbacks when those named fonts are not locally installed.

### Validation

Public commit `cdc61dd4fbd990cb24ac832ba78d7a059710fe0c` completed Agents Platform CI run `35218556118` successfully, including:

- Agents Platform contract tests;
- routing evaluation;
- DAG/workflow tests;
- operational health tests;
- advanced orchestration and integrated pipeline tests;
- tool-result and egress safety tests;
- existing skill execution, MCP hardening and MCP system regressions;
- the full `python run_all_tests.py` ComputeMesh regression.

No known public release blocker remains from BLOCKER-001. The remaining release step is to validate the exact final public documentation/state commit, pin that exact SHA in `ComputeMesh-ControlPlane`, and re-run the private validation layer.
