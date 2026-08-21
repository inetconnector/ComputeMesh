import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

class WindowsScriptTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / 'setup' / name).read_text(encoding='utf-8')

    def test_entrypoint_is_one_click(self):
        root = (ROOT / 'SETUP.cmd').read_text(encoding='utf-8')
        self.assertIn('setup\\setup.ps1', root)
        self.assertIn('-Mode menu', root)

    def test_firewall_is_private_and_subnet_scoped(self):
        text = self.read('network.ps1')
        self.assertIn('RemoteAddress LocalSubnet', text)
        self.assertIn('-Profile Private', text)
        self.assertIn('Remove-NetFirewallRule', text)
        self.assertNotIn('--bind 0.0.0.0', text)

    def test_llama_download_uses_official_latest_release(self):
        text = self.read('llama.ps1')
        self.assertIn('ggml-org/llama.cpp/releases/latest', text)
        self.assertIn('cuda-12\\.4-x64', text)
        self.assertIn('vulkan-x64', text)
        self.assertIn('Get-FileHash', text)

    def test_common_setup_auto_detects_language_and_isolates_python(self):
        text = self.read('common.ps1')
        self.assertIn('Get-Culture', text)
        self.assertIn("'.venv'", text)
        self.assertIn('Python.Python.3.13', text)

    def test_uac_restarts_setup_entrypoint_not_module(self):
        common = self.read('common.ps1')
        network = self.read('network.ps1')
        self.assertIn("SetupEntrypoint = Join-Path $PSScriptRoot 'setup.ps1'", common)
        self.assertIn('$script:SetupEntrypoint', network)
        self.assertNotIn('$PSCommandPath', network)

if __name__ == '__main__':
    unittest.main()
