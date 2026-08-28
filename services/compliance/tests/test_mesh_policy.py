from __future__ import annotations
import unittest
from services.compliance.mesh_policy import (
    ExecutionPrivacyClass, JobRoutingPolicy, MeshFeatureFlags,
    ProviderRoutingCapabilities, ProviderTrustTier, evaluate_mesh_eligibility,
)


class GlobalMeshPolicyTests(unittest.TestCase):
    def provider(self, **updates):
        data = dict(node_id="node-global", trust_tier=ProviderTrustTier.OPEN, region="US", production_eligible=True, technically_compatible=True)
        data.update(updates)
        return ProviderRoutingCapabilities(**data)

    def test_public_can_use_open_global_provider(self):
        self.assertTrue(evaluate_mesh_eligibility(JobRoutingPolicy.public(), self.provider()).eligible)

    def test_region_policy_still_constrains_public(self):
        self.assertFalse(evaluate_mesh_eligibility(JobRoutingPolicy.public(allowed_regions={"DE", "FR"}), self.provider(region="US")).eligible)

    def test_confidential_never_downgrades_to_open(self):
        job = JobRoutingPolicy(privacy_class=ExecutionPrivacyClass.CONFIDENTIAL, minimum_trust_tier=ProviderTrustTier.VERIFIED)
        self.assertFalse(evaluate_mesh_eligibility(job, self.provider(), features=MeshFeatureFlags(confidential_execution=True)).eligible)

    def test_confidential_feature_defaults_fail_closed(self):
        job = JobRoutingPolicy(privacy_class=ExecutionPrivacyClass.CONFIDENTIAL, minimum_trust_tier=ProviderTrustTier.VERIFIED)
        provider = self.provider(trust_tier=ProviderTrustTier.VERIFIED, confidential_execution_supported=True, confidential_technology="vendor-tee-v1", attestation_verified=True, attestation_fresh=True)
        self.assertFalse(evaluate_mesh_eligibility(job, provider, features=MeshFeatureFlags()).eligible)

    def test_tls_container_vm_are_not_confidential_technology(self):
        job = JobRoutingPolicy(privacy_class=ExecutionPrivacyClass.CONFIDENTIAL, minimum_trust_tier=ProviderTrustTier.VERIFIED)
        for tech in ("tls", "container", "vm", "simulated"):
            provider = self.provider(trust_tier=ProviderTrustTier.VERIFIED, confidential_execution_supported=True, confidential_technology=tech, attestation_verified=True, attestation_fresh=True)
            self.assertFalse(evaluate_mesh_eligibility(job, provider, features=MeshFeatureFlags(confidential_execution=True)).eligible)

    def test_crypto_private_requires_exact_capabilities(self):
        job = JobRoutingPolicy(privacy_class=ExecutionPrivacyClass.CRYPTO_PRIVATE, minimum_trust_tier=ProviderTrustTier.VERIFIED, required_crypto_capabilities=frozenset({"fhe"}))
        provider = self.provider(trust_tier=ProviderTrustTier.VERIFIED, crypto_private_capabilities=frozenset({"mpc"}))
        self.assertFalse(evaluate_mesh_eligibility(job, provider, features=MeshFeatureFlags(crypto_private_execution=True)).eligible)


if __name__ == "__main__":
    unittest.main()
