import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SharedLauncherSyntaxTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows PowerShell parser check")
    def test_windows_shared_powershell_scripts_parse(self):
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or shutil.which("pwsh")
        self.assertIsNotNone(powershell, "PowerShell is required on the Windows validation runner")
        for relative in ("setup/shared-proof.ps1", "setup/shared-worker.ps1"):
            path = (ROOT / relative).resolve()
            quoted = str(path).replace("'", "''")
            script = (
                "$tokens=$null; $errors=$null; "
                f"[void][System.Management.Automation.Language.Parser]::ParseFile('{quoted}',[ref]$tokens,[ref]$errors); "
                "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Output $_.Message }; exit 1 }"
            )
            with self.subTest(path=relative):
                result = subprocess.run(
                    [powershell, "-NoProfile", "-Command", script],
                    cwd=ROOT,
                    check=False,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    msg=f"PowerShell parse failed for {relative}: {result.stdout}{result.stderr}",
                )


if __name__ == "__main__":
    unittest.main()
