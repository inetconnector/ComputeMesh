import subprocess
import base64
from pathlib import Path

priv_bytes = Path('config/security/computemesh_release_signing_private.key').read_bytes()
pub_hex = Path('config/security/computemesh_release_signing_public.key').read_text().strip()

b64 = base64.b64encode(priv_bytes).decode('ascii')
cmd = f"echo '{pub_hex}' > /root/ComputeMesh/config/security/computemesh_release_signing_public.key && echo '{b64}' | base64 -d > /root/ComputeMesh/config/security/computemesh_release_signing_private.key && chmod 600 /root/ComputeMesh/config/security/computemesh_release_signing_private.key"

subprocess.run(['ssh', 'root@89.58.11.237', cmd], check=True)
print("Synchronized master private key to server!")
