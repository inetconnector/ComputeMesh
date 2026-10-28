> **STATUSAKTUALISIERUNG 2026-10-28:** Der opt-in Kimi/RPC-Quellcode ist nach Public PR #138 im `main`-Commit `f1ba057a6f0d9c49ae052f0d0e1086c3181ad734` enthalten; der unten genannte Entwicklungsbranch ist historische Herkunft. **Keine** reale gemeinsame CUDA-Laptop-/Vulkan-Miner-Kimi-Inferenz nachgewiesen; `HARDWARE_NOT_RUN`, `RELEASE_NO_GO`. Die konkreten Testschritte bleiben gültiger experimenteller Arbeitsauftrag.

# Kimi-Linear 48B-A3B — erster echter 48+16-GiB-Zwei-Rechner-Versuch

**Status:** opt-in Entwicklungsintegration auf `codex/kimi-linear-dual-host-20261026`. Kein produktiver Freigabenachweis. Physische Polaris- und CUDA/RPC-Inferenz sind **NOT_RUN**. `RELEASE_NO_GO`.

## Topologie und Modellwahl

- Windows: eine RTX 3080 Laptop GPU mit nominell 16 GiB, `llama-server` mit CUDA+RPC als **Koordinator**.
- Linux NodeOS: sechs Polaris-GPUs mit nominell insgesamt 48 GiB, `ggml-rpc-server` mit Vulkan als **Worker**.
- Der Worker wird **nicht** automatisch gestartet. Plaintext-Upstream-RPC darf ausschließlich über einen vom Betreiber unabhängig authentifizierten und geschützten Tunnel genutzt werden.
- Modellquelle: https://huggingface.co/bartowski/moonshotai_Kimi-Linear-48B-A3B-Instruct-GGUF
- Erst `Q4_K_M` (ca. 30,06 GB Dateigröße), danach `Q6_K` (ca. 40,46 GB). Das Modell gehört auf den lokalen Datenträger des Koordinators. Es wird nicht vom Runner heruntergeladen.
- Die GGUF-SHA-256 muss aus einer **separat überprüften** Datei/Manifest stammen. Dateiname und nominaler VRAM sind kein Echtheits- oder Laufzeitnachweis.
- NodeOS-Build pinnt derzeit llama.cpp `29aaf1c27faa48292357cea2120d94114a545006` (v0.4.1). Koordinator und Worker sollen aus demselben überprüften Commit gebaut werden. Keine automatische Runtime-Aktualisierung oder unbewiesene Kimi-Kompatibilitätsbehauptung.

## Vorbereitung

1. NodeOS-Hardwareabnahme: sechs separate Radeon/Vulkan-GPUs und stabile PCI-/VRAM-Zuordnung wirklich messen. `vulkaninfo --summary` und `llama-server --list-devices` getrennt dokumentieren.
2. Nur für den isolierten RPC-Versuch den NodeOS-Image-Build mit `COMPUTEMESH_ENABLE_RPC_EXPERIMENT=1` ausführen (aktiviert `-DGGML_RPC=ON`). Der Standardbuild bleibt ohne RPC-Worker. Anschließend Image bauen und prüfen, dass `/usr/local/bin/ggml-rpc-server` vorhanden ist. Eine erfolgreiche Builder-Codeänderung ist **noch kein** erfolgreicher Image-Build.
3. Auf dem NodeOS-Miner in einer autorisierten lokalen Administrationssitzung nur den Loopback-Worker starten:
   `/usr/local/bin/ggml-rpc-server --host 127.0.0.1 --port 50052`
   Keine `0.0.0.0`-Bindung und keine öffentliche Firewallfreigabe.
4. Einen unabhängig authentifizierten SSH-/VPN-Tunnel vom Windows-Koordinator zum Loopback-Port des Workers bereitstellen, sodass der Windows-Rechner den Worker unter `127.0.0.1:50052` erreicht. SSH-Hostschlüssel prüfen. Für NodeOS vorher einen dafür freigegebenen SSH-Benutzer und Schlüssel autorisiert bereitstellen; das Image hat absichtlich kein gemeinsames Passwort.
5. Auf Windows einen passenden `llama-server.exe` mit CUDA+RPC aus demselben llama.cpp-Commit installieren/bauen. `--version`, `--offline --rpc 127.0.0.1:50052 --list-devices` prüfen. Die tatsächlich gemeldeten CUDA-/RPC-Geräte können von erwarteten Namen abweichen; der erste Versuch ist bewusst streng auf genau eine ausgewählte CUDA-GPU und sechs Remote-GPUs begrenzt.
6. GGUF Q4 oder Q6 lokal auf Windows ablegen und vollständige SHA-256 unabhängig kontrollieren.

## Realer Probe- und Inferenzpfad

In der öffentlichen ComputeMesh-Repositorywurzel auf Windows, mit entsprechend angepassten lokalen Pfaden und den **tatsächlich geprüften** Hash-/Runtime-Werten:

```text
python -m runtime.llama.kimi_linear_dual_host probe --llama-server C:\\llama\\llama-server.exe --model C:\\models\\Kimi-Linear-48B-A3B-Instruct-Q4_K_M.gguf --model-sha256 <ECHTER_64_STELLIGER_GGUF_HASH> --quant Q4_K_M --worker-rpc 127.0.0.1:50052 --runtime-commit 29aaf1c27faa48292357cea2120d94114a545006

python -m runtime.llama.kimi_linear_dual_host run --llama-server C:\\llama\\llama-server.exe --model C:\\models\\Kimi-Linear-48B-A3B-Instruct-Q4_K_M.gguf --model-sha256 <ECHTER_64_STELLIGER_GGUF_HASH> --quant Q4_K_M --worker-rpc 127.0.0.1:50052 --runtime-commit 29aaf1c27faa48292357cea2120d94114a545006 --output-dir C:\\ComputeMeshProofs\\kimi-q4-run1
```

`probe` führt echte Geräte-/Versionsabfrage, den vollständigen GGUF-Hash und die aktuelle VRAM-Budgetberechnung durch, **aber keine Token-Inferenz**. `run` verwendet den existierenden `runtime.llama.rpc_spike` zum wirklichen Modellstart, zur `/completion`-Anfrage und zur Erstellung eines promptfreien Ergebnis-Receipts. Es benötigt die GPU-Hardware und darf nicht als bestanden gelten, bevor ein echtes Ergebnis vorliegt.

Nach erfolgreichem `run` kann `serve` einen lokalen OpenAI-kompatiblen `llama-server` auf `127.0.0.1:18080` starten. Diese Ausgabe ist vorerst ein **Entwicklungsendpunkt**. Der reguläre Provider-Agent akzeptiert keine frei startbaren Fremdendpunkte als `INFERENCE_READY`: Für echte ControlPlane-/Chat-Freigabe fehlt noch die überprüfbare, prozess- und modellgebundene Readiness-Integration mit der bestehenden `ModelEngineService`-Sicherheitsgrenze. Diese Grenze nicht durch `ready=true`-Konstanten oder unsichere Environment-Overrides umgehen.

## Messbare Abnahmekriterien

- Windows erkennt mindestens die RTX CUDA0, die gesicherte RPC-Verbindung exakt sechs tatsächliche AMD-Vulkan-GPUs. Kein versehentlicher RPC-CPU-Fallback.
- Live-VRAM abzüglich mindestens 1 GiB Reserve pro GPU und 2 GiB zusätzlichem Headroom reicht für die geprüfte GGUF-Dateigröße.
- Gleiche validierte llama.cpp-Buildidentität auf beiden Hosts; Peeridentität des RPC-Servers über den unabhängigen geschützten Tunnel, nicht durch RPC selbst.
- Q4 real laden, Response-Tokens generieren, keine Out-of-Memory-/Vulkan-/RPC-Abstürze, gemessene Tokens/s, beide Hostprozesse und VRAM-Verbrauch protokollieren.
- Danach Q6 und längeren Kontext testen; Polaris-Kernels und Kimi-Linear-KDA-Operationen sind derzeit nicht hardwareverifiziert.
- Laufzeitabbruch, Worker-Verbindungsverlust, Wiederaufnahme, Modellwechsel und Reconnect müssen explizit negativ getestet werden, bevor der reguläre AI-Chat den gemeinsamen Endpoint erhält.
- Der bestehende M1-`shared_trial` führt für die Korrektheitsmessung einen **gleichen Modellbaseline-Lauf auf dem Koordinator** aus. Q4/Q6 überschreiten die 16 GiB des Windows-Koordinators; dieser Baseline-Test ist für diese Topologie daher nicht direkt erfüllbar. Eine echte Q4-Einzelhost-Baseline auf dem 48-GiB-AMD-Miner ist ein gesonderter Nachweis und erfordert ein korrekt daran angepasstes Evidenzschema.

## Lokal prüfbare Tests

```text
python -m unittest runtime.llama.tests.test_kimi_linear_dual_host -v
python -m unittest runtime.llama.tests.test_rpc_spike -v
python -m unittest deploy.appliance.tests.test_real_live_appliance_contract -v
```

Weitere Blocker: echtes Vulkan-/Polaris-Build, Windows CUDA+RPC-Build, Tunnelkonfiguration, mindestens eine 30-GB-GGUF-Datei, gemessene Hardwareevidenz, Provider-Readiness/ControlPlane-Integration, Windows-Security-Gate, Release-Signatur und vollständiges physisches Mesh-E2E. Keine davon wird durch diese Branch-Änderung als erledigt ausgewiesen.
