import logging
logging.basicConfig(level=logging.DEBUG)
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.network.tests.test_mesh_transport import TestMeshTransport

suite = unittest.TestSuite()
suite.addTest(TestMeshTransport('test_bidirectional_mtls_tunnel'))
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
if not result.wasSuccessful():
    sys.exit(1)
