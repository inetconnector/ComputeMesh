import paramiko
import sys

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key_path = r'C:\Users\frede\.ssh\computemesh_miner_operator_ed25519'
    key = paramiko.Ed25519Key.from_private_key_file(key_path)
    ssh.connect('192.168.1.27', username='root', pkey=key, timeout=10)

    script_content = """#!/bin/bash
set -e

MODELS_DIR="/var/lib/computemesh/models"
MODEL_FILE="Qwen2.5-32B-Instruct-Q4_K_M.gguf"
PART_FILE="${MODELS_DIR}/${MODEL_FILE}.part"
FINAL_FILE="${MODELS_DIR}/${MODEL_FILE}"
URL="https://huggingface.co/bartowski/qwen2.5-32b-instruct-gguf/resolve/main/Qwen2.5-32B-Instruct-Q4_K_M.gguf"
EXPECTED_SIZE="19851336576"
EXPECTED_SHA="2e5f6daea180dbc59f65a40641e94d3973b5dbaa32b3c0acf54647fa874e519e"
LOG_FILE="${MODELS_DIR}/download-32b.log"
STATUS_FILE="${MODELS_DIR}/download-32b.status"

mkdir -p "$MODELS_DIR"
cd "$MODELS_DIR"

echo "DOWNLOADING" > "$STATUS_FILE"
echo "Starting download of $MODEL_FILE at $(date)" >> "$LOG_FILE"

curl -L -C - \\
     --fail \\
     --retry 20 \\
     --retry-delay 5 \\
     --retry-max-time 7200 \\
     -o "$PART_FILE" \\
     "$URL" >> "$LOG_FILE" 2>&1

ACTUAL_SIZE=$(stat -c%s "$PART_FILE" 2>/dev/null || echo 0)
echo "Downloaded size: $ACTUAL_SIZE (expected $EXPECTED_SIZE)" >> "$LOG_FILE"

if [ "$ACTUAL_SIZE" -ne "$EXPECTED_SIZE" ]; then
    echo "ERROR: Size mismatch! Expected $EXPECTED_SIZE, got $ACTUAL_SIZE" >> "$LOG_FILE"
    echo "ERROR_SIZE_MISMATCH" > "$STATUS_FILE"
    exit 1
fi

echo "Verifying GGUF header..." >> "$LOG_FILE"
MAGIC=$(head -c 4 "$PART_FILE")
if [ "$MAGIC" != "GGUF" ]; then
    echo "ERROR: Not a GGUF file! Header is $MAGIC" >> "$LOG_FILE"
    echo "ERROR_INVALID_HEADER" > "$STATUS_FILE"
    exit 1
fi

echo "Verifying SHA256 digest..." >> "$LOG_FILE"
echo "VERIFYING_SHA" > "$STATUS_FILE"
CALC_SHA=$(sha256sum "$PART_FILE" | awk '{print $1}')
echo "Calculated SHA256: $CALC_SHA" >> "$LOG_FILE"
if [ "$CALC_SHA" != "$EXPECTED_SHA" ]; then
    echo "ERROR: SHA256 mismatch! Expected $EXPECTED_SHA, got $CALC_SHA" >> "$LOG_FILE"
    echo "ERROR_SHA_MISMATCH" > "$STATUS_FILE"
    exit 1
fi

echo "Moving $PART_FILE to $FINAL_FILE..." >> "$LOG_FILE"
mv -f "$PART_FILE" "$FINAL_FILE"

echo "Creating manifest and updating catalog.json..." >> "$LOG_FILE"
cat << 'MANIFEST_EOF' > "${MODELS_DIR}/Qwen2.5-32B-Instruct-Q4_K_M.computemesh-model-manifest.json"
{
  "architecture": "qwen2",
  "artifacts": [
    {
      "digest": "sha256:2e5f6daea180dbc59f65a40641e94d3973b5dbaa32b3c0acf54647fa874e519e",
      "media_type": "application/x-gguf",
      "size_bytes": 19851336576
    }
  ],
  "layer_count": 64,
  "license": {
    "id": "apache-2.0",
    "redistribution_allowed": true,
    "source": "https://huggingface.co/Qwen/Qwen2.5-32B-Instruct/blob/main/LICENSE"
  },
  "model_id": "bartowski/qwen2.5-32b-instruct-gguf",
  "model_version": "2.5",
  "partitioning": {
    "allowed": [
      "contiguous_layers"
    ]
  },
  "quantizations": [
    "Q4_K_M"
  ],
  "runtime_compatibility": [
    {
      "runtime": "llama.cpp"
    }
  ],
  "schema_version": 1
}
MANIFEST_EOF

cat << 'CATALOG_EOF' > "${MODELS_DIR}/catalog.json"
{
  "models": [
    {
      "filename": "Qwen2.5-32B-Instruct-Q4_K_M.gguf",
      "installed_at": "2026-11-09T05:40:00Z",
      "layer_count": 64,
      "license_id": "apache-2.0",
      "model_id": "bartowski/qwen2.5-32b-instruct-gguf",
      "quantization": "Q4_K_M",
      "sha256": "2e5f6daea180dbc59f65a40641e94d3973b5dbaa32b3c0acf54647fa874e519e",
      "size_bytes": 19851336576,
      "source_repo": "bartowski/qwen2.5-32b-instruct-gguf",
      "source_revision": "2116cbb385b8ce3a4d28cf3bf1cd2039a55821a6"
    },
    {
      "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
      "installed_at": "2026-11-08T21:55:10Z",
      "layer_count": 28,
      "license_id": "apache-2.0",
      "model_id": "bartowski/qwen2.5-7b-instruct-gguf",
      "quantization": "Q4_K_M",
      "sha256": "65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423",
      "size_bytes": 4683074240,
      "source_repo": "local/bartowski/qwen2.5-7b-instruct-gguf",
      "source_revision": "0000000000000000000000000000000000000000"
    }
  ],
  "schema_version": 1
}
CATALOG_EOF

echo "Updating computemesh-llama.service to 32B model..." >> "$LOG_FILE"
cat << 'SERVICE_EOF' > /etc/systemd/system/computemesh-llama.service
[Unit]
Description=ComputeMesh Multi-GPU Llama Inferenz Service
After=network.target computemesh-mount-models.service
Requires=computemesh-mount-models.service

[Service]
Type=simple
User=root
WorkingDirectory=/var/lib/computemesh/models
ExecStart=/usr/local/bin/llama-server --model /var/lib/computemesh/models/Qwen2.5-32B-Instruct-Q4_K_M.gguf --host 127.0.0.1 --port 8081 --ctx-size 8192 --n-gpu-layers all --split-mode layer --tensor-split 0.167,0.167,0.167,0.167,0.167,0.167 --fit on --device Vulkan0,Vulkan1,Vulkan2,Vulkan3,Vulkan4,Vulkan5 --alias bartowski/qwen2.5-32b-instruct-gguf --parallel 1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl restart computemesh-llama.service

echo "SUCCESS" > "$STATUS_FILE"
echo "Download and activation of 32B model completed at $(date)" >> "$LOG_FILE"
"""

    sftp = ssh.open_sftp()
    with sftp.open('/usr/local/bin/computemesh-upgrade-32b.sh', 'w') as f:
        f.write(script_content)
    sftp.chmod('/usr/local/bin/computemesh-upgrade-32b.sh', 0o755)
    sftp.close()

    _, stdout, _ = ssh.exec_command('ls -l /usr/local/bin/computemesh-upgrade-32b.sh')
    print("Uploaded script:", stdout.read().decode().strip())
    ssh.close()

if __name__ == '__main__':
    main()

