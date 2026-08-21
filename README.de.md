# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Phase:** M0-Grundlage beim Übergang zum ersten kontrollierten gemeinsamen M1-Runtime-Experiment.  
> **Wichtig:** ComputeMesh ist **noch kein produktionsreifes verteiltes Inferenzprodukt**. Das Windows-/Linux-Setup richtet den heute tatsächlich vorhandenen Lab-/Benchmark-Ablauf ein; es ist kein öffentlicher Provider-Node-Installer.

ComputeMesh untersucht, ob heterogene Rechner als gemeinsames modellbewusstes KI-Inferenz-Fabric arbeiten können. Langfristig soll der Nutzer nur Modell und Richtlinie wählen; ComputeMesh übernimmt Machbarkeit, Platzierung, Vorbereitung, Ausführung, Fehlerbehandlung, Verifikation und nachvollziehbare Abrechnung.

## Einfachster Einstieg in die Lab-Werkzeuge

Repository klonen/herunterladen und den Starter für das Betriebssystem verwenden:

**Windows:** `SETUP.cmd` doppelklicken  
**Linux:** `./setup.sh` ausführen (oder `bash setup.sh`, falls das Ausführungsbit verloren ging).

Beide Starter bieten dasselbe einfache Menü für Rechnerprofil, vertrauenswürdige LAN-RTT-/Durchsatzmessung, lokales llama.cpp-Benchmarking und die aktuell vollständige lokale Testsuite. Modellgewichte werden niemals automatisch heruntergeladen.

Die genaue Zwei-Rechner-Anleitung steht in [setup/README.de.md](setup/README.de.md).

## Aktuell implementiert

Zu den vorhandenen Grundlagen gehören inzwischen:

- plattformübergreifendes Windows-/Linux-Lab-Setup;
- Inventory-, TCP-Netzwerk- und llama.cpp-`llama-bench`-Messwerkzeuge;
- maschinenlesbare Draft-2020-12-State-/Control-Verträge;
- deterministische Job-/Reservation-Semantik und transaktionale SQLite-Referenzpersistenz;
- strikte transportneutrale Control-Envelopes und dauerhafte erste Handler;
- authentifizierungspflichtige Node-Session-Semantik und strikte erste Wire-Bindung;
- M1-Referenz-Node-Identity `computemesh-ed25519-v1` mit Enrollment-/Key-Rotation-/Revocation-Referenzzustand;
- ein kontrollierter llama.cpp-RPC-**Research-Harness** für das erste gemeinsame M1-Runtime-Experiment;
- ein loopback-only TCP-**Mess-Relay** für opake RPC-Bytezählung, deterministische Userspace-Latenz/Jitter und kontrollierte Disconnects;
- ein deterministischer M1-**Zwei-Node-Placement-Planer**, der aus aktuellen Profilen, Modellmanifest, llama-bench-Evidenz und Netzwerkdaten nachvollziehbare Local-/Shared-Machbarkeitskandidaten erzeugt, ohne Distributed-Performance zu erfinden.

## M1-Zwei-Node-Placement-Planer

`services/scheduler/placement.py` ist die erste maschinenlesbare Placement-Komponente. Sie ist ein **Experiment-Machbarkeitsplaner**, kein produktiver Scheduler.

Geprüft werden unter anderem:

- Node-/Profile-Schemas und exakte Profilrevisionen;
- `draining` sowie stale/zu weit in der Zukunft liegende Profile;
- Größe des ausgewählten Modellartefakts gegen alle vier llama-bench-Datensätze;
- `contiguous_layers`-Erlaubnis im Modellmanifest;
- Provider-Memory-Fraction plus konservative Planer-Memory-Grenze;
- eine zwingende Coordinator→Worker-Netzwerkmessung und die explizit angegebene Worker-Node-ID.

Mögliche Ergebnisse:

- `shared_experiment` — ein konservativer zusammenhängender Zwei-Node-Layer-Split ist speicherseitig machbar;
- `local_only` — nur die lokale Coordinator-Baseline ist aktuell machbar;
- `no_plan` — aktuelle harte Bedingungen/Speichergrenzen lassen keinen Kandidaten zu.

Die Ausgabe enthält eine deterministische `decision_id`, vollständige zusammenhängende Layerbereiche, relative `tensor_split`-Gewichte, Erklärungen der Hard Constraints und die gemessene Einzel-Compute-/Netzwerkevidenz.

Entscheidend: Solange kein korrekter gemessener Shared-Runtime-Lauf existiert, bleiben immer

```text
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

Das aktuelle `benchmark_result` v1 bindet den Ziel-Node einer Netzwerkmessung strukturell noch nicht. Der Planer kennzeichnet die Peer-Bindung deshalb als `caller_asserted_v1`, statt stärkere Evidenz vorzutäuschen. Auch die Layerzahl ist ein expliziter Experimentparameter, weil `model_manifest` v1 sie noch nicht enthält. Details: [services/scheduler/README.md](services/scheduler/README.md).

## Kontrolliertes llama.cpp-M1-Experiment

`runtime/llama/rpc_spike.py` kann aktuelle llama.cpp-Geräte ermitteln, eine deterministische lokale Baseline aufzeichnen, einen expliziten Local+RPC-`layer`-Split ausführen und exakt dasselbe Modell/denselben Prompt per Token-ID-Digest vergleichen, sofern vorhanden, sonst per Output-Digest. Modell-/Runtime-/Topologie-/Timing-Evidenz wird ohne Rohprompt-/Rohoutput-Persistenz gespeichert.

Der erste Experimentpfad hält Coordinator-HTTP auf `127.0.0.1`, beschränkt RPC auf literales Loopback/RFC1918-IPv4, nutzt `--offline`, deaktiviert automatisches Fit und Cache-Flächen und behandelt Upstream-RPC ausschließlich als Trusted-Lab-Implementierungsdetail. Details: [runtime/llama/README.md](runtime/llama/README.md).

**ADR 0002 bleibt Proposed.** Harness und Planer bereiten den Nachweis vor; ein echter korrekter gemeinsamer Zwei-Node-Inferenzlauf wurde noch nicht aufgezeichnet.

## Runtime-Netzwerkmess-Relay

`runtime/network/tcp_relay.py` kann lokal zwischen llama-Coordinator und RPC-Worker im vertrauenswürdigen privaten LAN sitzen. Es lauscht nur auf `127.0.0.1`, verbindet nur zu literalem Loopback/RFC1918-IPv4, verwendet begrenzte Queues, zählt opake Bytes getrennt in beide Richtungen, trennt Setup-/Aktivzeit, kann reproduzierbare Userspace-Stream-Latenz/Jitter hinzufügen und kontrollierte Disconnects erzwingen.

Das Relay parst keine RPC-Frames: Byte-Summen enthalten Framing/Control/Daten und sind **keine** Activation-Tensor-Bytezahlen. Paketverlust wird bewusst nicht durch das Löschen von TCP-Bytes simuliert. Paket-Level-Loss/Reordering bleibt ein separates OS-/Netzwerkemulations-Experiment. Details: [runtime/network/README.md](runtime/network/README.md).

## Verifizierte echte Zielsysteme

Bereits vorhandene physische Evidenz vom 21.08.2026:

- Windows-Ziel: RTX 3080 Laptop GPU, 16 GiB VRAM, 31,7 GiB RAM;
- Linux-Ziel: Debian-13-Server, 4 logische CPU-Kerne, 7,8 GiB RAM, CPU-only;
- Windows → Internet-Linux Engineering-TCP: RTT p50 `11,884 ms`, p95 `13,369 ms`, Upload p50 `42,276 Mbit/s`, Download p50 `226,597 Mbit/s`;
- Windows-CUDA-llama.cpp 7B-Q4: Prefill `2866,127 tok/s`, Decode `76,210 tok/s`;
- Linux-CPU-llama.cpp 0.5B-Q4-Smoke: Prefill `12,382 tok/s`, Decode `0,201 tok/s`.

Das Internet-Netzwerkergebnis ist kein vertrauenswürdiger Private-LAN-A/B-Nachweis und keine verteilte gemeinsame Inferenz. Relay und Placement-Planer besitzen derzeit plattformübergreifende Software-Evidenz, aber keine echte Zwei-Rechner-Shared-Runtime-Evidenz.

## Identity- und Runtime-Sicherheitsgrenze

ADR 0005 ist **nur für die enge M1-Referenzimplementierung** akzeptiert. Vor öffentlicher Netzwerkexposition fehlen unter anderem Provider-/User-Authentifizierung um Identity-APIs, OS-geschützte private Node-Key-Speicherung, Revocation-Fan-out an aktive Sessions, authentifizierter/verschlüsselter Transport, Authorization/Rate-/Resource-Limits und produktiver Service-/Datenbankbetrieb.

Upstream-llama.cpp-RPC bleibt **nur Trusted Lab**. Die aktuelle ComputeMesh-Identity-/Session-Authentifizierung authentifiziert den Upstream-RPC-Socket nicht; weder lokales Relay noch Machbarkeitsplaner ändern diese Grenze. Niemals den RPC-Worker öffentlich oder in einem nicht vertrauenswürdigen Netz exponieren.

`confidential_compute` ist keine zulässige Garantie, solange kein konkretes Trusted-Execution-/Attestation-Design existiert.

## Noch nicht implementiert

Es gibt weiterhin keinen produktiven Provider-Node-Installer/-Service, keinen abgeschlossenen gemeinsamen Inferenznachweis, kein kalibriertes/produktives Scheduler-Ranking, kein produktives Gateway/API, keinen produktiven Identity-Netzwerkservice, keinen vollständigen Artifact-/Runtime-/Failure-Wire-Pfad, keinen produktiven Runtime-Transport, kein Paket-Level-Loss-/Reordering-Experiment, keinen fertigen Billing-/Verification-/Telemetry-Produktstack und keinen signierten Produktions-Release-/Update-Pfad.

## Unmittelbarer Ablauf

```text
Profile + lokale Benchmarks + vertrauenswürdige LAN-Pfadevidenz
        ↓
maschinenlesbarer konservativer Placement-Kandidat
        ↓
lokale deterministische llama-server-Baseline
        ↓
expliziter Local + RPC Layer-Split
        ↓
Korrektheits- + Timingvergleich
        ↓
opake RPC-Bytezählung + Latenz/Jitter/Disconnect-Experimente
        ↓
erste reproduzierbare korrekte gemeinsame Zwei-Node-Inferenz
        ↓
Placement-Prognose/-Ranking aus gemessener Shared-Evidenz kalibrieren
        ↓
bei Relevanz Paket-Level-Loss-/Reordering-Experiment
```

## Repository-Struktur

```text
ComputeMesh/
├─ SETUP.cmd / setup.sh   # einfache Windows-/Linux-Lab-Einstiege
├─ setup/                 # plattformübergreifende Lab-Orchestrierung
├─ tools/benchmark/       # Inventory, TCP, llama-bench-Adapter
├─ services/orchestrator/ # dauerhafte M0-State-/Control-Grundlage
├─ services/identity/     # M1-Referenz für Enrollment/Key-Registry
├─ services/scheduler/    # deterministischer M1-Zwei-Node-Machbarkeitsplaner
├─ protocol/              # Verträge, Session-Wire-Bindung, Ed25519-Verifier
├─ runtime/llama/         # kontrollierter llama.cpp-M1-Research-Spike
├─ runtime/network/       # begrenztes M1-TCP-Mess-Relay
├─ docs/                  # Spezifikationen und ADRs
└─ state.md               # kanonischer Engineering-Handoff
```

Für Engineering-Details zuerst `state.md`, danach `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md` und die ADRs lesen.

## Sprach-Synchronisationsregel

`README.md` und `README.de.md` sind synchronisierte Projekteinstiege und müssen bei jeder öffentlich relevanten Änderung gemeinsam aktualisiert werden.

## Lizenz

Alle Rechte bleiben vorbehalten, bis ausdrücklich eine Lizenz ausgewählt und veröffentlicht wird. Die Repository-Sichtbarkeit gewährt keine Open-Source-Nutzungsrechte.
