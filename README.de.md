# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Phase:** M0-Grundlage beim Übergang zum ersten kontrollierten M1-Runtime-Experiment.  
> **Wichtig:** ComputeMesh ist **noch kein produktionsreifes verteiltes Inferenzprodukt**. Das Windows-/Linux-Setup richtet den heute tatsächlich vorhandenen Lab-/Benchmark-Ablauf ein; es ist kein öffentlicher Provider-Node-Installer.

ComputeMesh untersucht, ob heterogene Rechner als gemeinsames modellbewusstes KI-Inferenz-Fabric arbeiten können. Langfristig soll der Nutzer nur Modell und Richtlinie wählen; ComputeMesh übernimmt Machbarkeit, Platzierung, Vorbereitung, Ausführung, Fehlerbehandlung, Verifikation und nachvollziehbare Abrechnung.

## Einfachster Einstieg in die Lab-Werkzeuge

Repository klonen/herunterladen und den Starter für das Betriebssystem verwenden:

**Windows:** `SETUP.cmd` doppelklicken  
**Linux:** `./setup.sh` ausführen (oder `bash setup.sh`, falls das Ausführungsbit verloren ging).

Beide Starter bieten dasselbe einfache Menü für Rechnerprofil, vertrauenswürdige LAN-RTT-/Durchsatzmessung, lokales llama.cpp-Benchmarking und die aktuell vollständige Testsuite. Modellgewichte werden niemals automatisch heruntergeladen.

Die genaue Zwei-Rechner-Anleitung steht in [setup/README.de.md](setup/README.de.md).

## Aktuell implementiert

Zu den vorhandenen Grundlagen gehören inzwischen:

- plattformübergreifendes Windows-/Linux-Lab-Setup;
- Inventory-, TCP-Netzwerk- und llama.cpp-`llama-bench`-Messwerkzeuge;
- maschinenlesbare Draft-2020-12-State-/Control-Verträge;
- deterministische Job-/Reservation-Semantik;
- transaktionale SQLite-Referenzpersistenz mit dauerhafter Idempotenz, Revisionen, Leases, Restart-Recovery, Request-Fingerprints und atomarer Reservation→Job/Stage-Bindung;
- strikte transportneutrale `ControlEnvelope`-Prüfung und strukturierte Fehler;
- dauerhafte Handler für `ReserveCapacity`, `CommitReservation` und `CancelJob`;
- authentifizierungspflichtige Node-Session-Semantik und strikte Wire-Bindung für `NodeHello`, `NodeAuthenticate`, `CapabilityNegotiation`, `NodeProfileUpdate`, `BenchmarkReport` und `DrainRequest`;
- Protokollversionsaushandlung, Bindung des authentifizierten Actors, optimistische Session-Revisionen, Replay-/Konfliktbehandlung und Capability-/Profile-/Benchmark-Readiness-Gates;
- den M1-Referenzpfad `computemesh-ed25519-v1` mit kurzlebigen Challenge-Proofs;
- ein SQLite-Referenzregister für Identity mit gehashten Enrollment-Tokens, stabilen schlüsselunabhängigen Node-IDs, Rotation und monotoner Key-/Node-Revocation;
- einen kontrollierten llama.cpp-RPC-**Research-Harness** für das erste M1-Shared-Runtime-Experiment;
- ein loopback-only TCP-**Mess-Relay** für opake RPC-Bytezählung, deterministische Userspace-Latenz/Jitter und kontrollierte Verbindungsabbrüche.

## Kontrolliertes llama.cpp-M1-Experiment

`runtime/llama/rpc_spike.py` ist der erste ausführbare Experiment-Controller für eine gemeinsame Runtime. Er macht Upstream-llama.cpp-RPC ausdrücklich **nicht** zum ComputeMesh-Protokoll.

Der Harness kann:

1. einen Upstream-RPC-Worker nur auf Loopback/RFC1918-Literal-IPv4 starten;
2. die exakten Local-/RPC-Gerätenamen des aktuellen llama.cpp-Builds ermitteln;
3. eine deterministische lokale Baseline aufzeichnen;
4. einen expliziten lokalen + RPC-`layer`-Split mit fester Geräteliste und festen Tensor-Verhältnissen ausführen;
5. exakt dasselbe Modell/denselben Prompt per Token-ID-Digest vergleichen, sofern vorhanden, sonst per Output-Digest;
6. Modell-SHA-256, llama.cpp-Version, Topologie, Placement, Model-Ready-/Request-Zeit und Prefill-/Decode-Metriken speichern, ohne Rohprompt oder Rohoutput zu persistieren.

Für das erste Experiment wird der Coordinator-HTTP-Server zwingend an `127.0.0.1` gebunden, `--offline` verwendet, automatisches Fit und Prompt-/RPC-Cache-Flächen werden deaktiviert und fortgeschrittene Tensor-Overrides werden nicht verwendet. Details: [runtime/llama/README.md](runtime/llama/README.md).

**ADR 0002 bleibt Proposed.** Der Harness ist die Infrastruktur für den Nachweis; ein echter gemeinsamer Zwei-Node-Inferenzlauf wurde noch nicht erbracht.

## Runtime-Netzwerkmess-Relay

`runtime/network/tcp_relay.py` kann lokal zwischen llama-Coordinator und einem RPC-Worker im vertrauenswürdigen privaten LAN sitzen. Es:

- lauscht ausschließlich auf `127.0.0.1`;
- verbindet ausschließlich zu literalem Loopback/RFC1918-IPv4;
- verwendet begrenzte Queues/Backpressure;
- zählt opake TCP-Stream-Bytes getrennt in beide Richtungen;
- trennt Setup-/Wartezeit von der aktiv verbundenen Relay-Zeit;
- kann reproduzierbare Userspace-One-Way-Latenz und Chunk-Jitter hinzufügen;
- kann nach aktiver Zeit oder übertragenen Bytes gezielt trennen;
- persistiert inhaltsfreie Terminierungs-/Fehlermetriken.

Das Relay parst keine RPC-Frames. Seine Byte-Summen enthalten deshalb Framing, Control und Daten und sind **keine** Activation-Tensor-Bytezahlen. Paketverlust wird ebenfalls nicht simuliert: beliebige Bytes aus einem TCP-Stream zu entfernen würde das Protokoll beschädigen, nicht IP-Verlust und Retransmission modellieren. Paket-Level-Loss/Reordering bleibt ein separates OS-/Netzwerkemulations-Experiment. Details: [runtime/network/README.md](runtime/network/README.md).

## Verifizierte echte Zielsysteme

Bereits vorhandene physische Evidenz vom 21.08.2026:

- Windows-Ziel: RTX 3080 Laptop GPU, 16 GiB VRAM, 31,7 GiB RAM;
- Linux-Ziel: Debian-13-Server, 4 logische CPU-Kerne, 7,8 GiB RAM, CPU-only;
- Windows → Internet-Linux Engineering-TCP: RTT p50 `11,884 ms`, p95 `13,369 ms`, Upload p50 `42,276 Mbit/s`, Download p50 `226,597 Mbit/s`;
- Windows-CUDA-llama.cpp 7B-Q4: Prefill `2866,127 tok/s`, Decode `76,210 tok/s`;
- Linux-CPU-llama.cpp 0.5B-Q4-Smoke: Prefill `12,382 tok/s`, Decode `0,201 tok/s`.

Das Internet-Netzwerkergebnis ist kein vertrauenswürdiger Private-LAN-A/B-Nachweis und keine verteilte gemeinsame Inferenz. Für das neue RPC-Mess-Relay gibt es plattformübergreifende Softwaretests, aber noch kein echtes Zwei-Rechner-Relay-Ergebnis.

## Identity-Entscheidung und Sicherheitsgrenze

ADR 0005 ist **nur für die enge M1-Referenzimplementierung** akzeptiert: stabile Node-IDs plus Ed25519-Challenge-Proofs, kurzlebiges Enrollment, Key-Rotation und Revocation-Semantik.

Das macht das Identity-System nicht produktionsreif. Vor öffentlicher Netzwerkexposition fehlen unter anderem Provider-/User-Authentifizierung um Identity-APIs, OS-geschützte private Node-Key-Speicherung, Revocation-Fan-out an aktive Sessions, authentifizierter/verschlüsselter Transport, Authorization/Rate-/Resource-Limits und produktiver Service-/Datenbankbetrieb. Ein kopierter privater Schlüssel ist weiterhin kryptografisch dieselbe Identität; Signaturen beweisen keinen einzelnen physischen Rechner.

Für den Upstream-llama.cpp-RPC-Worker gilt eine noch engere Grenze: **nur Trusted Lab**. Die aktuelle ComputeMesh-Identity-/Session-Authentifizierung authentifiziert den Upstream-RPC-Socket nicht. Das lokale Mess-Relay ändert diese Sicherheitsgrenze nicht. Niemals den RPC-Worker öffentlich oder in einem nicht vertrauenswürdigen Netz exponieren.

`confidential_compute` ist keine zulässige Garantie, solange kein konkretes Trusted-Execution-/Attestation-Design existiert.

## Noch nicht implementiert

Es gibt weiterhin keinen produktiven Provider-Node-Installer/-Service, keinen abgeschlossenen gemeinsamen Inferenznachweis, keinen automatischen M1-Scheduler/Placement-Planner, kein produktives Gateway/API, keinen produktiven Identity-Netzwerkservice, keinen vollständigen Artifact-/Runtime-/Failure-Wire-Pfad, keinen produktiven Runtime-Transport, kein Paket-Level-Loss-/Reordering-Experiment, keinen fertigen Billing-/Verification-/Telemetry-Produktstack und keinen signierten Produktions-Release-/Update-Pfad.

## Unmittelbarer Ablauf

```text
Profile + lokale Benchmarks
        ↓
vertrauenswürdige Private-LAN-A↔B-Messung
        ↓
lokale deterministische llama-server-Baseline
        ↓
expliziter Local + RPC Layer-Split
        ↓
Korrektheits- + Timingvergleich
        ↓
opake RPC-Bytezählung + Latenz/Jitter/Disconnect-Experimente
        ↓
bei Bedarf Paket-Level-Loss-/Reordering-Experiment
        ↓
erste reproduzierbare gemeinsame Zwei-Node-Inferenz
        ↓
erste maschinenlesbare Placement-Entscheidung
```

## Repository-Struktur

```text
ComputeMesh/
├─ SETUP.cmd / setup.sh   # einfache Windows-/Linux-Lab-Einstiege
├─ setup/                 # plattformübergreifende Lab-Orchestrierung
├─ tools/benchmark/       # Inventory, TCP, llama-bench-Adapter
├─ services/orchestrator/ # dauerhafte M0-State-/Control-Grundlage
├─ services/identity/     # M1-Referenz für Enrollment/Key-Registry
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
