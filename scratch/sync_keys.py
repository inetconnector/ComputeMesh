import subprocess
import base64
from pathlib import Path

# Source and remote destination are both outside any git working tree —
# never REPO_ROOT/config/security, which can be swept up by a project/repo
# backup even though it is gitignored.
LOCAL_SECRETS_DIR = Path.home() / '.computemesh' / 'secrets'
REMOTE_SECRETS_DIR = '/root/.computemesh/secrets'

priv_bytes = (LOCAL_SECRETS_DIR / 'computemesh_release_signing_private.key').read_bytes()
pub_hex = (LOCAL_SECRETS_DIR / 'computemesh_release_signing_public.key').read_text().strip()

b64 = base64.b64encode(priv_bytes).decode('ascii')
cmd = (
    f"mkdir -p {REMOTE_SECRETS_DIR} && chmod 700 {REMOTE_SECRETS_DIR} && "
    f"echo '{pub_hex}' > {REMOTE_SECRETS_DIR}/computemesh_release_signing_public.key && "
    f"echo '{b64}' | base64 -d > {REMOTE_SECRETS_DIR}/computemesh_release_signing_private.key && "
    f"chmod 600 {REMOTE_SECRETS_DIR}/computemesh_release_signing_private.key "
    f"{REMOTE_SECRETS_DIR}/computemesh_release_signing_public.key"
)

subprocess.run(['ssh', 'root@89.58.11.237', cmd], check=True)
print("Synchronized master private key to server!")
