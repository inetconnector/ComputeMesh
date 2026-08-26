# ComputeMesh Lab Setup — Windows and Linux

**Languages:** **English** | [Deutsch](README.de.md)

This folder is the simplest way to run the **currently implemented M0/M1 lab workflow**. It is intentionally not a production installer: the provider application, production distributed runtime, production scheduler, and production authentication/transport stack do not exist yet.

## Start

**Windows** — from the repository root, double-click:

```text
SETUP.cmd
```

**Linux** — from the repository root:

```bash
./setup.sh
```

If the executable bit was lost during download/extraction:

```bash
bash setup.sh
```

Both paths open the same menu with profile capture, network server/client, llama.cpp benchmark, and tests. The current M1 evidence-transfer steps also have dedicated launchers described below.

## Recommended two-computer workflow

The two machines may be Windows, Linux, or mixed. For the current M1 placement proof, both machines must benchmark the **same complete GGUF file**. Matching only the model family is not enough: the bundle path checks the model basename and exact artifact size, while the model manifest carries the exact GGUF SHA-256 and layer count.

First on **both** computers:

1. Start the OS-specific setup launcher.
2. Choose **1 — Prepare this computer**.
3. Check the displayed CPU/GPU/RAM summary.
4. Run the llama.cpp benchmark with the same complete GGUF on both machines.

Each setup has a random Lab node ID such as `lab-1a2b3c4d`. It is not derived from the hostname.

Then measure the LAN in both directions.

### A → B

On computer **B**:

1. Start setup.
2. Choose **2 — Network server**.
3. Allow the temporary firewall action if the OS asks for elevation.
4. Note the displayed private IP.

The current server also self-reports B's Lab node ID over the benchmark connection.

On computer **A**:

1. Start setup.
2. Choose **3 — Network client**.
3. Enter B's displayed private IP.
4. Read RTT p50/p95 and upload/download throughput.

The generated network result carries A's local Lab node ID and, with a current server, B's self-reported Lab node ID. The binding is labelled `unauthenticated_server_report_v1`: it improves experiment traceability but is **not authentication**.

### B → A

Swap the roles and repeat once. This records directionality instead of assuming symmetry and produces the opposite local/peer association.

## Transfer the worker evidence and build the current bundle

The current placement-bundle path no longer requires manually selecting eight JSON files.

Choose which machine will be the **coordinator (A)** and which will be the **worker (B)**. The bundle uses the coordinator→worker network record, so A must already have a fresh A→B result with the current embedded Lab IDs.

### 1. Export on the worker

On **Windows B**, double-click:

```text
setup\EVIDENCE-EXPORT.cmd
```

On **Linux B**:

```bash
bash setup/EVIDENCE-EXPORT.sh
```

The result is a ZIP under `artifacts/lab/exports/`. Copy that ZIP to computer A by any trusted local method you prefer.

The ZIP deliberately contains only recognized Lab profile/benchmark JSON evidence. It does **not** contain:

- the GGUF model;
- llama.cpp binaries;
- `artifacts/lab/config.json` or remembered local paths;
- arbitrary files from the node directory.

Every exported evidence file is bound in `computemesh-lab-export.json` by a relative cross-platform-safe path, exact byte size, and SHA-256. Source mtimes and source filesystem paths are not copied into the archive manifest.

### 2. Generate the model manifest from the exact GGUF

On the coordinator, generate the ComputeMesh model manifest from the same complete GGUF used by both llama-bench runs with `tools/benchmark/gguf_manifest.py`. The manifest must contain the artifact-derived `layer_count`, exact size, and SHA-256. If the model is still a llama.cpp multi-file split set, merge the complete set first; schema-v1 bundle construction does not treat one shard as the whole model.

### 3. Build on the coordinator

On **Windows A**, double-click:

```text
setup\BUILD-BUNDLE.cmd
```

Select the copied worker ZIP and the model-manifest JSON in the file dialogs.

On **Linux A**:

```bash
bash setup/BUILD-BUNDLE.sh
```

Enter/select the copied worker ZIP and model-manifest JSON when prompted.

The coordinator then:

1. validates the ZIP manifest and exact member set;
2. rejects ZIP path traversal, symlink/encrypted entries, excess file/byte limits, size mismatches, and SHA-256 mismatches;
3. extracts only after validation into `artifacts/lab/imports/<peer-node>/<export-id>/` using a temporary directory followed by an atomic rename;
4. verifies an already imported export again on a repeat import instead of silently trusting the existing files;
5. combines that peer evidence with the coordinator's own current Lab evidence and the model manifest;
6. runs the fail-closed current evidence selector and placement planner;
7. writes `experiment_bundle.json` below a new coordinator `*-bundle` run directory.

If current evidence is ambiguous, stale, from the wrong network direction, from mismatching profile revisions/model sizes, or requires the old caller-asserted peer/layer fallbacks, bundle construction fails instead of guessing.

The ZIP hashes protect transfer/copy integrity and reproducibility. They do **not** authenticate who created the evidence and are not hardware attestation. The first physical two-machine proof recorded in `state.md` validates one trusted-lab topology; repeat the workflow for any new topology, model, or runtime build.

## Run the first shared proof

Once the current bundle recommends `shared_experiment`, the runtime part no longer needs to be assembled from six manual commands. Keep the worker on the trusted private LAN and use the direct launchers.

On **Windows B**, double-click:

```text
setup\SHARED-WORKER.cmd
```

On **Linux B**:

```bash
bash setup/SHARED-WORKER.sh
```

The worker launcher binds llama.cpp RPC to one concrete RFC1918 address on TCP 50052. If Lab Setup remembers a `llama-bench`, the worker launcher will use `rpc-server` only from that same local llama.cpp build tree; it will not silently fall through to another downloaded build or `$PATH`. If the matching RPC binary is missing, install/use a complete matching build and rerun the benchmark. Where supported it opens only a temporary private-LAN/subnet-scoped firewall rule and removes that rule when the worker exits. Keep the worker window/terminal open.

Then on **Windows A**, double-click:

```text
setup\SHARED-PROOF.cmd
```

On **Linux A**:

```bash
bash setup/SHARED-PROOF.sh
```

Choose the current `experiment_bundle.json` if prompted and enter B's private IPv4 address. The coordinator runner then fails closed through this sequence:

1. validate the bundle and embedded placement schemas again;
2. reject evidence that has become stale under the planner's current profile-age policy;
3. require the exact local GGUF basename, byte size, and SHA-256 from the bundle;
4. require `llama-server --version` to match the common llama.cpp build number/commit recorded by all four selected two-node llama-bench records in the bundle;
5. discover the current local llama.cpp device and preflight RPC visibility before loading the model;
6. if `llama-cli` can see the RPC device but `llama-server` cannot, report that server/RPC compatibility condition explicitly instead of attempting the measured run;
7. run the deterministic local baseline;
8. start a fresh zero-delay loopback measurement relay and execute exactly the planner-selected two-entry split through it;
9. require exact token-ID correctness when available, otherwise exact output-digest correctness;
10. write `comparison.json`, relay metrics, and the already defined fail-closed `shared_run_evidence.json`.

A failed attempt keeps a bounded, content-free `shared_trial_failure.json` with the failing phase. Raw prompts and raw model output are not copied into that failure record.

**Current automated-runner boundary:** the coordinator side must be accelerator-backed. The selected worker may be exposed by upstream RPC even when its backend is CPU-only, but this runner does not pretend that local `--device none` is an explicit local split device. A CPU-only coordinator therefore stops before execution rather than inventing `none,RPC0` placement semantics.

This convenience layer does not authenticate llama.cpp RPC, the relay target, or the physical worker. It remains trusted-private-lab tooling.

## Windows behavior

- detects German/English from Windows;
- finds Python 3.10+ or attempts user-scoped installation with `winget`;
- creates repository-local `.venv`;
- binds the network benchmark to a concrete private address;
- passes the current random Lab node ID into the benchmark server/client evidence path;
- temporarily opens TCP 43191 only for Windows `Private` + `LocalSubnet` and removes the rule after the one-shot test;
- offers Windows file pickers for `llama-bench.exe` and GGUF;
- can download the official Windows llama.cpp build selected by the setup;
- exports/imports evidence with Python-standard-library ZIP/hash handling;
- installs the small `jsonschema` dependency into the local `.venv` only when the bundle step needs it and it is not already available.

Direct Windows launchers: `NODE.cmd`, `NETWORK-SERVER.cmd`, `NETWORK-CLIENT.cmd`, `LLAMA-BENCH.cmd`, `EVIDENCE-EXPORT.cmd`, `BUILD-BUNDLE.cmd`, `SHARED-WORKER.cmd`, `SHARED-PROOF.cmd`, `TESTS.cmd`.

## Linux behavior

- detects German/English from the Linux locale;
- requires Python 3.10+ and creates repository-local `.venv`;
- if required base packages are missing, offers installation through `apt`, `dnf`, `zypper`, `pacman`, or `apk` using root/`sudo` only after confirmation;
- detects a private RFC1918 interface with `iproute2` and binds the benchmark to that exact address;
- passes the current random Lab node ID into the benchmark server/client evidence path;
- if `firewalld` is active, creates a runtime-only rich rule limited to the detected subnet/address/port and removes it afterwards;
- if `ufw` is active, creates a temporary source-subnet rule and deletes it afterwards;
- if neither supported firewall frontend is active, it changes no firewall state and still binds only to the private interface;
- can use an existing `llama-bench` or query the latest official llama.cpp release for a matching Linux asset;
- prefers ROCm when `rocminfo` is present, otherwise Vulkan when Vulkan/NVIDIA/DRI evidence is present, otherwise CPU;
- supports official Ubuntu x64/arm64 CPU/Vulkan assets and x64 ROCm assets selected dynamically from release metadata;
- verifies a GitHub `sha256:` asset digest when available;
- wraps the downloaded executable with local `LD_LIBRARY_PATH` handling and accepts it only if `llama-bench --help` starts successfully;
- uses `zenity` for GGUF selection when available on a desktop, otherwise asks for a path with shell completion;
- reuses the same isolated Python bootstrap for evidence export/bundle launchers.

Direct Linux launchers: `NODE.sh`, `NETWORK-SERVER.sh`, `NETWORK-CLIENT.sh`, `LLAMA-BENCH.sh`, `EVIDENCE-EXPORT.sh`, `BUILD-BUNDLE.sh`, `SHARED-WORKER.sh`, `SHARED-PROOF.sh`, `TESTS.sh`. `bash setup/EVIDENCE-EXPORT.sh`, `bash setup/BUILD-BUNDLE.sh`, `bash setup/SHARED-WORKER.sh`, and `bash setup/SHARED-PROOF.sh` remain usable even when an archive/download did not preserve executable bits.

The official automatic Linux downloads are Ubuntu binaries. They often work on compatible glibc distributions, but the setup does not assume this: if the downloaded executable cannot start, it is rejected and you can point the setup at a distro-native/self-built `llama-bench`. On musl-based systems such as Alpine, an existing compatible build is the safer llama.cpp path.

## llama.cpp benchmark

On each relevant computer:

1. Start setup.
2. Choose **4 — llama.cpp prefill/decode**.
3. Select automatic official download or an existing `llama-bench`.
4. Select/provide the **same complete local `.gguf` model** on both experiment machines.
5. Read prefill tokens/s, decode tokens/s, and ms/token.

Model weights are **never downloaded automatically** and are not copied by the evidence-export helper.

## Local files

Everything generated by setup stays local and is already ignored by Git:

```text
.venv/                                         # isolated Python environment
artifacts/lab/config.json                      # local node id/revision + remembered paths
artifacts/lab/<node>/<run>/                    # benchmark outputs and bundle runs
artifacts/lab/runtime/llama.cpp/               # optional upstream llama.cpp downloads
artifacts/lab/exports/<lab-export-...>.zip     # bounded transferable evidence ZIP
artifacts/lab/imports/<peer>/<export-id>/      # verified peer evidence import
```

The lab node ID is random (`lab-xxxxxxxx`) and does not use the hostname.

## Network and evidence-transfer safety

The underlying benchmark protocol has no authentication or encryption. Both assisted server implementations:

- accept only RFC1918 private addresses;
- bind to one concrete private address, not `0.0.0.0`;
- use temporary firewall rules where the supported firewall integration is active;
- remove those temporary rules when the one-shot server exits.

The optional Lab node-ID exchange does **not** change this security boundary. A peer can self-report any Lab ID because the benchmark connection is unauthenticated. For real authenticated node identity, ComputeMesh has a separate narrow M1 Ed25519/session reference path; that is not used to authenticate this benchmark socket.

The evidence ZIP is a local transfer container, not a trust envelope. File hashes detect changed/corrupt copies but do not sign the producer, authenticate a node, or attest hardware. Import therefore belongs only in the same controlled trusted-lab workflow.

Never expose the benchmark server or upstream llama.cpp RPC worker to the public internet.

## Test status

The complete setup test action runs benchmark, orchestrator, protocol, identity, scheduler, llama-runtime, network-runtime, and setup suites. Current cross-platform counts and the exact latest validation run are recorded in `state.md`.

The Linux layer additionally covers Bash syntax, the root `setup.sh` entry point, private/public IPv4 filtering, current llama.cpp CPU/Vulkan/ROCm/ARM64 asset-name selection, private-bind/temporary-firewall invariants, and direct Linux launcher routing. Windows validation additionally parses both shared-proof PowerShell launchers with the real Windows PowerShell parser.

Evidence-transfer coverage includes exclusion of arbitrary/GGUF files, path-free export manifests, profile-revision binding, hash-verified idempotent round trips, changed-content rejection, ZIP symlink/traversal rejection, existing-import tamper detection, dependency-light `lab.py` startup with `python -S`, and a complete synthetic worker-export→coordinator-bundle round trip.

The evidence-binding tests additionally verify that the setup passes its own Lab node ID into both network roles, that current benchmark peers can self-report a bounded ID, and that peer mismatches fail instead of being silently accepted.

The repository now records one physical trusted-lab two-computer proof in `state.md`. New machines, models, runtime builds, injected-delay runs, disconnect runs, and packet-level network experiments still require fresh evidence rather than reuse of that historical proof.

Additional real target smoke evidence exists from 2026-08-21:

- Windows direct launcher profile capture on an RTX 3080 Laptop GPU machine.
- Linux direct launcher profile capture and full test suite on a Debian 13 internet server.
- Windows -> Linux internet TCP benchmark using a temporary source-limited firewall rule.
- Real llama.cpp runs on Windows CUDA with a 7B Q4 GGUF and on Linux CPU with a 0.5B Q4 GGUF.

Those two historical llama.cpp runs used different GGUFs, so they cannot be combined into the new current evidence bundle. The internet benchmark also predates the bound peer-ID path and is not a trusted-private-LAN proof or shared-inference result.

## Engineering/manual commands

Advanced users can call the new transfer path directly:

```bash
python setup/lab.py export
python setup/lab.py import --archive /path/to/peer.zip
python setup/lab.py bundle --peer-export /path/to/peer.zip --model-manifest /path/to/model_manifest.json
```

The direct bundle command also supports explicit evidence disambiguators (`--artifact-digest`, `--benchmark-model-name`, `--network-run-id`) when more than one otherwise valid current candidate exists. These selectors choose evidence; they do not re-enable the legacy caller-asserted peer/layer fallbacks.

Advanced users can still call the underlying tools under `tools/benchmark/` directly. Those CLIs remain the canonical engineering layer; the setup launchers are simpler user-facing orchestrators around them.
