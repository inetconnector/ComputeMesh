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
        self.assertIn('(Test-Path $script:VenvPython) -and (Test-Python $script:VenvPython)', text)
        self.assertIn('function Invoke-Lab([string[]]$CommandArgs)', text)
        self.assertIn('$script:LabHelper @CommandArgs', text)
        self.assertNotIn('$script:LabHelper @Args', text)

    def test_setup_preserves_requested_mode_across_dot_sourcing(self):
        text = self.read('setup.ps1')
        self.assertIn('$RequestedMode = $Mode', text)
        self.assertIn('$RequestedLanguage = $Language', text)
        self.assertIn('Initialize-Setup -RequestedLanguage $RequestedLanguage -RequestedMode $RequestedMode', text)
        self.assertIn('switch ($RequestedMode)', text)

    def test_uac_restarts_setup_entrypoint_not_module(self):
        common = self.read('common.ps1')
        network = self.read('network.ps1')
        self.assertIn("SetupEntrypoint = Join-Path $PSScriptRoot 'setup.ps1'", common)
        self.assertIn('$script:SetupEntrypoint', network)
        self.assertNotIn('$PSCommandPath', network)

    def test_evidence_launchers_use_existing_isolated_bootstrap(self):
        export_cmd = self.read('EVIDENCE-EXPORT.cmd')
        bundle_cmd = self.read('BUILD-BUNDLE.cmd')
        evidence = self.read('evidence.ps1')
        self.assertIn('evidence.ps1', export_cmd)
        self.assertIn('-Mode export', export_cmd)
        self.assertIn('evidence.ps1', bundle_cmd)
        self.assertIn('-Mode bundle', bundle_cmd)
        self.assertIn(". (Join-Path $PSScriptRoot 'common.ps1')", evidence)
        self.assertIn(". (Join-Path $PSScriptRoot 'llama.ps1')", evidence)
        self.assertIn("Invoke-Lab @('export')", evidence)
        self.assertIn("Invoke-Lab @('bundle','--peer-export',$peer,'--model-manifest',$manifest)", evidence)
        self.assertIn("-c 'import jsonschema'", evidence)

    def test_shared_proof_launcher_is_private_and_routes_to_bound_runner(self):
        cmd = self.read('SHARED-PROOF.cmd')
        proof = self.read('shared-proof.ps1')
        self.assertIn('shared-proof.ps1', cmd)
        self.assertIn(". (Join-Path $PSScriptRoot 'common.ps1')", proof)
        self.assertIn(". (Join-Path $PSScriptRoot 'network.ps1')", proof)
        self.assertIn('Test-PrivateIPv4 $workerIp', proof)
        self.assertIn("'-m','runtime.llama.shared_trial'", proof)
        self.assertIn("'--bundle',$bundle", proof)
        self.assertIn("'--llama-server',$server", proof)
        self.assertIn("'--model',$model", proof)
        self.assertIn("'--worker-rpc',$worker", proof)
        self.assertIn("'--output-dir',$output", proof)
        self.assertIn('$trialArgs', proof)
        self.assertNotIn('$args =', proof)
        self.assertNotIn('0.0.0.0', proof)

    def test_shared_worker_launcher_keeps_rpc_private_and_firewall_temporary(self):
        cmd = self.read('SHARED-WORKER.cmd')
        worker = self.read('shared-worker.ps1')
        self.assertIn('shared-worker.ps1', cmd)
        self.assertIn('Get-PrivateLanInfo', worker)
        self.assertIn('-LocalAddress $info.IP', worker)
        self.assertIn('-RemoteAddress LocalSubnet', worker)
        self.assertIn('-Profile Private', worker)
        self.assertIn('-Program $rpc', worker)
        self.assertIn("-m runtime.llama.rpc_spike worker", worker)
        self.assertIn('--bind $info.IP', worker)
        self.assertIn('--port $port', worker)
        self.assertIn('finally {', worker)
        self.assertIn('Remove-NetFirewallRule', worker)
        self.assertIn('$uacArgs', worker)
        self.assertNotIn('$args =', worker)
        self.assertNotIn('--bind 0.0.0.0', worker)


if __name__ == '__main__':
    unittest.main()
