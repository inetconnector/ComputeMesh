# SPDX-License-Identifier: Apache-2.0
"""Comprehensive Unit & Mock Test Suite for GitHub Integration and Developer Tools."""

import base64
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from services.mcp.builtin.github_client import execute_github_request, get_github_token
from services.mcp.builtin.github_repo_tools import (
    github_get_repo,
    github_search_repositories,
    github_get_file_contents,
    github_list_repo_tree,
    github_search_code,
)
from services.mcp.builtin.github_issue_tools import (
    github_list_issues,
    github_get_issue,
    github_create_issue,
    github_add_issue_comment,
)
from services.mcp.builtin.github_pr_tools import (
    github_list_pull_requests,
    github_get_pull_request,
    github_get_pull_request_diff,
    github_get_pull_request_files,
)
from services.mcp.builtin.github_ci_tools import (
    github_list_releases,
    github_get_latest_release,
    github_list_commits,
    github_get_workflow_runs,
)
from services.mcp.builtin.terminal_runner import run_terminal_command
from services.mcp.builtin.http_api_client import execute_http_request
from services.mcp.tool_registry import ToolRegistry
from services.mcp.agent_loop import detect_direct_tool_intent, format_tool_content_if_json


class TestGitHubClient(unittest.TestCase):
    """Test Suite for GitHub REST API Client."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_mock_token_12345"})
    def test_token_resolution(self):
        token = get_github_token()
        self.assertEqual(token, "ghp_mock_token_12345")

    @patch("urllib.request.urlopen")
    def test_execute_github_request_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"name": "ComputeMesh", "stars": 42}).encode("utf-8")
        mock_resp.headers = {"X-RateLimit-Remaining": "4990"}
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = execute_github_request("/repos/inetconnector/ComputeMesh")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("data", {}).get("name"), "ComputeMesh")
        self.assertEqual(res.get("rate_limit_remaining"), 4990)


class TestGitHubRepoTools(unittest.TestCase):
    """Test Suite for GitHub Repository Tools."""

    @patch("services.mcp.builtin.github_repo_tools.execute_github_request")
    def test_github_get_repo(self, mock_req):
        mock_req.return_value = {
            "success": True,
            "status_code": 200,
            "data": {
                "name": "ComputeMesh",
                "full_name": "inetconnector/ComputeMesh",
                "stargazers_count": 128,
                "forks_count": 14,
                "open_issues_count": 3,
                "language": "Python",
                "license": {"spdx_id": "Apache-2.0"},
                "description": "Decentralized Compute & MCP Mesh",
                "html_url": "https://github.com/inetconnector/ComputeMesh",
                "default_branch": "main",
            },
        }
        res = github_get_repo(owner="inetconnector", repo="ComputeMesh")
        self.assertEqual(res.get("full_name"), "inetconnector/ComputeMesh")
        self.assertEqual(res.get("stars"), 128)
        self.assertEqual(res.get("license"), "Apache-2.0")

    @patch("services.mcp.builtin.github_repo_tools.execute_github_request")
    def test_github_search_repositories(self, mock_req):
        mock_req.return_value = {
            "success": True,
            "status_code": 200,
            "data": {
                "total_count": 1,
                "items": [
                    {
                        "full_name": "inetconnector/ComputeMesh",
                        "stargazers_count": 128,
                        "description": "Decentralized AI Mesh",
                        "html_url": "https://github.com/inetconnector/ComputeMesh",
                    }
                ],
            },
        }
        res = github_search_repositories(query="ComputeMesh")
        self.assertEqual(res.get("total_count"), 1)
        self.assertEqual(len(res.get("repositories", [])), 1)

    @patch("services.mcp.builtin.github_repo_tools.execute_github_request")
    def test_github_get_file_contents_base64(self, mock_req):
        sample_code = "print('Hello ComputeMesh GitHub')"
        encoded = base64.b64encode(sample_code.encode("utf-8")).decode("utf-8")
        mock_req.return_value = {
            "success": True,
            "status_code": 200,
            "data": {
                "name": "main.py",
                "path": "src/main.py",
                "size": len(sample_code),
                "encoding": "base64",
                "content": encoded,
            },
        }
        res = github_get_file_contents(owner="inetconnector", repo="ComputeMesh", path="src/main.py")
        self.assertEqual(res.get("content"), sample_code)
        self.assertEqual(res.get("name"), "main.py")

    @patch("services.mcp.builtin.github_repo_tools.execute_github_request")
    def test_github_list_repo_tree(self, mock_req):
        mock_req.return_value = {
            "success": True,
            "status_code": 200,
            "data": [
                {"name": "src", "type": "dir", "path": "src", "size": 0},
                {"name": "README.md", "type": "file", "path": "README.md", "size": 1024},
            ],
        }
        res = github_list_repo_tree(owner="inetconnector", repo="ComputeMesh")
        self.assertEqual(res.get("total_entries"), 2)
        self.assertEqual(res.get("entries")[0]["name"], "src")


class TestGitHubIssueTools(unittest.TestCase):
    """Test Suite for GitHub Issues Tools."""

    @patch("services.mcp.builtin.github_issue_tools.execute_github_request")
    def test_github_list_issues(self, mock_req):
        mock_req.return_value = {
            "success": True,
            "status_code": 200,
            "data": [
                {
                    "number": 1,
                    "title": "Add GitHub Integration",
                    "state": "open",
                    "html_url": "https://github.com/inetconnector/ComputeMesh/issues/1",
                    "user": {"login": "frederik"},
                    "comments": 2,
                    "labels": [{"name": "feature"}],
                }
            ],
        }
        res = github_list_issues(owner="inetconnector", repo="ComputeMesh", state="open")
        self.assertEqual(res.get("total_issues"), 1)
        self.assertEqual(res.get("issues")[0]["title"], "Add GitHub Integration")
        self.assertIn("feature", res.get("issues")[0]["labels"])

    @patch("services.mcp.builtin.github_issue_tools.execute_github_request")
    def test_github_get_issue(self, mock_req):
        def _mock_side_effect(endpoint, **kwargs):
            if endpoint.endswith("/comments"):
                return {
                    "success": True,
                    "status_code": 200,
                    "data": [{"user": {"login": "ai-assistant"}, "body": "Working on it!", "created_at": "2026-09-14"}],
                }
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "number": 1,
                    "title": "Add GitHub Integration",
                    "state": "open",
                    "body": "Full REST API parity",
                    "html_url": "https://github.com/inetconnector/ComputeMesh/issues/1",
                    "user": {"login": "frederik"},
                    "labels": [],
                    "created_at": "2026-09-14",
                },
            }

        mock_req.side_effect = _mock_side_effect
        res = github_get_issue(owner="inetconnector", repo="ComputeMesh", issue_number=1)
        self.assertEqual(res.get("issue_number"), 1)
        self.assertEqual(len(res.get("comments", [])), 1)
        self.assertEqual(res.get("comments")[0]["body"], "Working on it!")


class TestGitHubPRTools(unittest.TestCase):
    """Test Suite for GitHub PR Tools."""

    @patch("services.mcp.builtin.github_pr_tools.execute_github_request")
    def test_github_list_pull_requests(self, mock_req):
        mock_req.return_value = {
            "success": True,
            "status_code": 200,
            "data": [
                {
                    "number": 10,
                    "title": "Feature: MCP Suite Extension",
                    "state": "open",
                    "draft": False,
                    "html_url": "https://github.com/inetconnector/ComputeMesh/pull/10",
                    "user": {"login": "frederik"},
                    "head": {"ref": "feature/mcp"},
                    "base": {"ref": "main"},
                }
            ],
        }
        res = github_list_pull_requests(owner="inetconnector", repo="ComputeMesh")
        self.assertEqual(res.get("total_prs"), 1)
        self.assertEqual(res.get("pull_requests")[0]["head_branch"], "feature/mcp")

    @patch("services.mcp.builtin.github_pr_tools.execute_github_request")
    def test_github_get_pull_request_diff(self, mock_req):
        mock_req.return_value = {
            "success": True,
            "status_code": 200,
            "data": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n",
        }
        res = github_get_pull_request_diff(owner="inetconnector", repo="ComputeMesh", pull_number=10)
        self.assertEqual(res.get("pull_number"), 10)
        self.assertIn("+new", res.get("diff"))


class TestGitHubCITools(unittest.TestCase):
    """Test Suite for GitHub CI / Releases / Commits."""

    @patch("services.mcp.builtin.github_ci_tools.execute_github_request")
    def test_github_list_releases(self, mock_req):
        mock_req.return_value = {
            "success": True,
            "status_code": 200,
            "data": [
                {
                    "tag_name": "v2.5.0",
                    "name": "ComputeMesh 2.5.0",
                    "published_at": "2026-09-14",
                    "prerelease": False,
                    "html_url": "https://github.com/inetconnector/ComputeMesh/releases/tag/v2.5.0",
                }
            ],
        }
        res = github_list_releases(owner="inetconnector", repo="ComputeMesh")
        self.assertEqual(res.get("total_releases"), 1)
        self.assertEqual(res.get("releases")[0]["tag_name"], "v2.5.0")

    @patch("services.mcp.builtin.github_ci_tools.execute_github_request")
    def test_github_get_workflow_runs(self, mock_req):
        mock_req.return_value = {
            "success": True,
            "status_code": 200,
            "data": {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "name": "CI Build & Test",
                        "status": "completed",
                        "conclusion": "success",
                        "head_branch": "main",
                        "head_sha": "abcdef123456",
                        "html_url": "https://github.com/inetconnector/ComputeMesh/actions/runs/100",
                    }
                ],
            },
        }
        res = github_get_workflow_runs(owner="inetconnector", repo="ComputeMesh")
        self.assertEqual(res.get("total_workflow_runs"), 1)
        self.assertEqual(res.get("workflow_runs")[0]["conclusion"], "success")


class TestTerminalRunner(unittest.TestCase):
    """Test Suite for Safe Terminal Runner."""

    def test_safe_echo_command(self):
        res = run_terminal_command(command="echo Hello_ComputeMesh_Terminal")
        self.assertEqual(res.get("exit_code"), 0)
        self.assertIn("Hello_ComputeMesh_Terminal", res.get("stdout", ""))

    def test_destructive_command_blocking(self):
        res = run_terminal_command(command="rm -rf /")
        self.assertEqual(res.get("exit_code"), 126)
        self.assertIn("Sicherheitsrichtlinie blockiert", res.get("stderr", ""))

    def test_destructive_windows_command_blocking(self):
        res = run_terminal_command(command="del /s /q c:\\")
        self.assertEqual(res.get("exit_code"), 126)
        self.assertIn("Sicherheitsrichtlinie blockiert", res.get("stderr", ""))


class TestHTTPAPIClient(unittest.TestCase):
    """Test Suite for Universal HTTP API Client."""

    @patch("urllib.request.urlopen")
    def test_http_get_request(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.code = 200
        mock_resp.reason = "OK"
        mock_resp.headers = MagicMock()
        mock_resp.headers.items.return_value = [("Content-Type", "application/json")]
        mock_resp.read.return_value = json.dumps({"status": "active", "version": "2.5"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = execute_http_request(url="https://api.github.com/zen")
        self.assertEqual(res.get("status_code"), 200)
        self.assertEqual(res.get("json_data", {}).get("status"), "active")

    def test_blocked_private_ip(self):
        res = execute_http_request(url="http://127.0.0.1:8080/admin")
        self.assertIn("error", res)
        self.assertIn("Lokale und private IP-Adressen sind aus Sicherheitsgründen blockiert", res.get("error"))


class TestRegistryAndAgentLoopIntegration(unittest.TestCase):
    """Test Suite for Tool Registry & Agent Loop Integration."""

    def setUp(self):
        self.registry = ToolRegistry()

    def test_github_and_developer_tools_registered(self):
        tools = [t.name for t in self.registry.list_tools()]
        expected = [
            "run_terminal_command",
            "execute_http_request",
            "github_get_repo",
            "github_search_repositories",
            "github_get_file_contents",
            "github_list_repo_tree",
            "github_search_code",
            "github_list_issues",
            "github_get_issue",
            "github_create_issue",
            "github_add_issue_comment",
            "github_list_pull_requests",
            "github_get_pull_request",
            "github_get_pull_request_diff",
            "github_get_pull_request_files",
            "github_list_releases",
            "github_get_latest_release",
            "github_list_commits",
            "github_get_workflow_runs",
        ]
        for name in expected:
            self.assertIn(name, tools, f"Missing tool registration: {name}")

    def test_tool_aliases(self):
        self.assertEqual(self.registry.get_tool("gh_repo").name, "github_get_repo")
        self.assertEqual(self.registry.get_tool("gh_issues").name, "github_list_issues")
        self.assertEqual(self.registry.get_tool("gh_prs").name, "github_list_pull_requests")
        self.assertEqual(self.registry.get_tool("terminal").name, "run_terminal_command")
        self.assertEqual(self.registry.get_tool("curl").name, "execute_http_request")

    def test_intent_detection(self):
        intent = detect_direct_tool_intent("terminal: dir", self.registry)
        self.assertIsNotNone(intent)
        self.assertEqual(intent[0], "run_terminal_command")
        self.assertEqual(intent[1].get("command"), "dir")

        intent_gh = detect_direct_tool_intent("github repo inetconnector/ComputeMesh", self.registry)
        self.assertIsNotNone(intent_gh)
        self.assertEqual(intent_gh[0], "github_get_repo")
        self.assertEqual(intent_gh[1].get("owner"), "inetconnector")
        self.assertEqual(intent_gh[1].get("repo"), "ComputeMesh")

        intent_http = detect_direct_tool_intent("curl https://api.github.com/status", self.registry)
        self.assertIsNotNone(intent_http)
        self.assertEqual(intent_http[0], "execute_http_request")

    def test_format_tool_content_if_json(self):
        # GitHub repo formatting
        gh_json = json.dumps({
            "full_name": "inetconnector/ComputeMesh",
            "stargazers_count": 100,
            "forks_count": 10,
            "open_issues_count": 2,
            "language": "Python",
            "license": "Apache-2.0",
            "description": "Decentralized Mesh",
            "html_url": "https://github.com/inetconnector/ComputeMesh",
            "default_branch": "main",
        })
        md = format_tool_content_if_json(gh_json)
        self.assertIn("### 🐙 GitHub Repository: [inetconnector/ComputeMesh]", md)
        self.assertIn("Sterne:** 100", md)

        # Terminal output formatting
        term_json = json.dumps({
            "command": "python --version",
            "exit_code": 0,
            "elapsed_seconds": 0.05,
            "stdout": "Python 3.11.9\n",
            "stderr": "",
        })
        term_md = format_tool_content_if_json(term_json)
        self.assertIn("### 💻 Terminal Befehl: `python --version`", term_md)
        self.assertIn("Python 3.11.9", term_md)


if __name__ == "__main__":
    unittest.main()
