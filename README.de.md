# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Projektphase:** M0 — Verträge/Schemas, Benchmarking, Orchestrierungssemantik, Protokollgrundlagen, Sicherheit und Machbarkeitsforschung.  
> **Implementierungsstatus:** Ausführbare M0-Benchmark-Werkzeuge, maschinenlesbare Verträge, transaktionale Job-/Reservation-Persistenz, der transportneutrale Control Envelope und die ersten nachrichtenspezifischen Control-Handler existieren. Es gibt weiterhin keine produktive verteilte Runtime, keinen Scheduler, Marktplatz, kein Abrechnungssystem und keine öffentlich nutzbare Provider-Node-Software.

ComputeMesh ist ein experimentelles System für verteilte KI-Inferenz. Heterogene Rechenressourcen sollen als logisch einheitliche Ausführungsumgebung nutzbar werden. Ein Client mit wenig lokalem VRAM soll später ein Modell ausführen können, dessen Speicher- und Rechenanforderungen den eigenen Rechner übersteigen, ohne Shards, Hosts, Ports oder Platzierung manuell verwalten zu müssen.

**North Star:** Der Nutzer wählt Modell und Richtlinie. ComputeMesh prüft Machbarkeit, wählt kompatible Kapazität, bereitet verifizierte Modellpartitionen vor, führt Inferenz aus, behandelt Ausfälle, verifiziert Ergebnisse risikobasiert und erzeugt einen auditierbaren Kostennachweis.

„The internet is your GPU“ ist eine Produktmetapher und keine Performance-Garantie. WAN-Latenz, Bandbreite, Jitter, Hardware-Heterogenität, Provider-Vertrauen, Modelllizenzen und Ausfallwahrscheinlichkeit sind zentrale Systemgrenzen.

## Aktueller Stand

### In M0 implementiert

- zweisprachige Root-Dokumentation und ADR-Prozess;
- Architektur-, Protokoll-, Sicherheits-, Benchmark-, Failure-, Privacy- und Data-Model-Spezifikationen;
- Draft-2020-12-Schemas für Node Profile, Benchmark Results, Model-/Shard-Manifeste, Reservations, Jobs, gemeinsamen Control Envelope, strukturierte Fehler und die ersten Control-Message-Payloads;
- Python-Inventory-Benchmark-Collector nur mit Standardbibliothek;
- TCP-Netzwerk-Microbenchmark für Connection Setup, RTT p50/p95, Upload-/Download-Durchsatz und Rohsamples;
- llama.cpp-`llama-bench`-Adapter, der Prompt-Processing-/Generation-Messungen in ComputeMesh-Prefill-/Decode-Records überführt;
- deterministische Job-/Reservation-State-Machine-Semantik;
- transaktionale SQLite-Referenzpersistenz mit dauerhafter Idempotenz, Optimistic Revisions, Lease-Persistenz/-Expiry, Stale-Writer-Schutz, Rollback und Restart-Recovery;
- SQLite-Schema-Migration v1 → v2 mit dauerhaften Request-Fingerprints;
- atomare `CommitReservation`-Bindung einer Reservation an konkreten Job + Stage;
- JSON-Schema-basierte Job-/Reservation-Admission;
- transportneutrale Control-Envelope-Prüfung mit Versions-/Zeit-/Formprüfung und strukturierten Fehlern;
- nachrichtenspezifische Payload-Validierung und dauerhafte Handler für `ReserveCapacity`, `CommitReservation` und `CancelJob`.

### Noch nicht implementiert / noch nicht nachgewiesen

- reale llama.cpp-Benchmark-Evidenz mit Ziel-Lab-GPU/Modell;
- reale Zwei-Node-LAN-/WAN-Benchmark-Evidenz;
- produktiver Provider-Node-Agent;
- Runtime Worker bzw. gemeinsame verteilte Inferenz;
- Gateway/API und produktiver Scheduler;
- produktiver Orchestrator-Netzwerkservice/Datenbankadapter;
- authentifizierte Node-Sessions und Autorisierung;
- die übrigen Node-/Runtime-/Artifact-Protokollnachrichten jenseits der ersten drei Handler;
- Registry, Verification, Billing/Ledger, Telemetry, SDK und UI;
- produktive Deployment-/Update-Pipeline;
- öffentliche Veröffentlichung.

Der kanonische Engineering-Handoff steht in `state.md`.

## Engineering-Invarianten

1. **In V1 wird auf Provider-Nodes kein beliebiger Kundencode ausgeführt.**
2. **Harte Scheduling-Constraints werden vor jeder Optimierung geprüft.**
3. **Arbeit wird nur abgerechnet, wenn sie eindeutig zugeordnet und auditiert werden kann.**
4. **Retries, Replays, Timeouts und doppelte Events dürfen keine doppelten Geschäftseffekte erzeugen.**
5. **Provider-Nodes werden als potenziell ausfallend, getrennt, unehrlich oder kompromittiert betrachtet.**
6. **Public Compute bedeutet nicht automatisch Prompt-Vertraulichkeit.**
7. **Performance-Aussagen benötigen reproduzierbare Messungen und Testbedingungen.**
8. **Die Data Plane transportiert nur freigegebene Inferenzprotokolldaten.**
9. **Modellartefakte sind unveränderlich, content-addressed, versioniert und vor Ausführung verifiziert.**
10. **Das System muss erklären können, warum eine Platzierung akzeptiert oder verworfen wurde.**

Änderungen dieser Invarianten erfordern einen ADR.

## Architektur im Überblick

```text
Client / SDK -> Gateway / API -> Job Orchestrator
                                  |-> Scheduler + Topology
                                  |-> Registry
                                  |-> Policy / Verification
                                  v
                           Kapazitätsreservierungen
                                  v
                         Provider Execution Mesh
                    Node A <---- Streams ----> Node B
                                  v
                       Telemetry / Metering / Ledger
```

Bei dichter Pipeline-Ausführung sollen zwischen Nodes normalerweise Stage-Aktivierungen/-Ergebnisse übertragen werden. Der KV-Cache verbleibt grundsätzlich bei den Layern, zu denen er gehört; KV-Transfer ist primär ein Migrations-, Recovery- oder Rebalancing-Vorgang.

## Repository-Struktur

```text
ComputeMesh/
├─ apps/                  # geplante Produktoberflächen
├─ services/orchestrator/ # M0 State Machine, Persistenz, Admission, Handler
├─ runtime/               # geplante CUDA/llama.cpp/vLLM/Network-Integrationen
├─ protocol/              # Control Envelope, Payload-Verträge, Schemas, Tests
├─ tools/benchmark/       # Inventory, TCP-Netzwerk, llama-bench-Adapter
├─ models/
├─ sdk/
├─ tests/
├─ deploy/
├─ research/
└─ docs/                  # Architektur-/Security-/Benchmark-/ADR-Dokumente
```

## Aktuelle M0-Werkzeuge ausführen

```powershell
git clone <repository-url>
cd ComputeMesh
python -m pip install -r requirements-dev.txt
python tools/benchmark/benchmark.py --dry-run
python -m unittest discover -s tools/benchmark/tests -v
python -m unittest discover -s services/orchestrator/tests -v
python -m unittest discover -s protocol/tests -v
```

### Node-Profil erfassen

```powershell
python tools/benchmark/benchmark.py --node-id lab-node-a --profile-revision 1
```

### Vertrauenswürdigen LAN-Pfad messen

Auf Node B:

```powershell
python tools/benchmark/network_benchmark.py server --bind 0.0.0.0 --port 43191 --once
```

Auf Node A:

```powershell
python tools/benchmark/network_benchmark.py client --host <NODE-B-LAN-IP> --port 43191 --profile-revision 1
```

Der Benchmark-Server hat **keine Authentifizierung oder Verschlüsselung**. Nur in einem kontrollierten vertrauenswürdigen LAN mit Firewall-Einschränkung verwenden; niemals öffentlich ins Internet stellen.

### Lokales llama.cpp-Prefill/Decode messen

```powershell
python tools/benchmark/llama_bench_adapter.py `
  --llama-bench C:\path\to\llama-bench.exe `
  --model C:\path\to\model.gguf `
  --profile-revision 1
```

Der Adapter ist ein Messadapter und noch kein Nachweis, dass M1 bestanden ist. Ein realer Modell-/Hardware-Lauf fehlt weiterhin.

## Protokoll- und Persistenzgrundlagen

`services/orchestrator/persistence.py` ist eine M0-SQLite-Referenz für transaktionale State-Effekte, dauerhafte Deduplizierung, Optimistic Revision Checks, restartfeste Replays, Leases und atomare Reservation-zu-Job-/Stage-Bindung. SQLite ist **nicht** als Produktionsdatenbank ausgewählt.

`protocol/control.py` implementiert die gemeinsame Control-Envelope-Semantik, ohne gRPC, QUIC, HTTP oder einen anderen Transport auszuwählen. Die initiale Message-Schicht validiert und verarbeitet nur drei bereits in `PROTOCOL.md` definierte Operationen:

- `ReserveCapacity`;
- `CommitReservation`;
- `CancelJob`.

Bei diesen Operationen wird die Envelope-`request_id` bis in die dauerhafte Idempotenzspeicherung durchgereicht; zusätzlich wird Message Type + Payload gefingert. Ein Replay derselben Anfrage hat genau einen Geschäftseffekt. Dieselbe Request-ID mit verändertem Payload wird als Idempotenzkonflikt abgelehnt.

**Authentifizierung und Autorisierung werden durch diese Handler nicht implementiert.** Die Actor-Identität bleibt unvertrauenswürdig, bis das Node-Identity-/Session-Design implementiert ist.

## Runtime-Ausrichtung

Der erste vorgeschlagene M1-Forschungspfad ist llama.cpp-orientiert und wird hinter der ComputeMesh-Node-/Worker-Grenze gekapselt. vLLM bleibt Vergleich/Referenz. ADR 0002 ist weiterhin **Proposed**, nicht Accepted.

## Unmittelbare Engineering-Reihenfolge

```text
maschinenlesbare Verträge + Inventory-Harness                 [M0 implementiert]
transaktionale Job-/Reservation-Persistenz + Schema-Admission [M0 implementiert]
gemeinsamer Control Envelope + strukturierte Fehler            [M0 implementiert]
erste dokumentierte Control-Handler                            [M0 implementiert]
TCP-Lab-Netzwerk-Microbenchmark                                [M0 implementiert]
llama-bench-Prefill-/Decode-Adapter                            [M0 implementiert]
-> Inventory-/Netzwerk-/Runtime-Messungen auf realen Nodes
-> llama.cpp-orientierter M1-Runtime-Spike
-> authentifizierter Node-Session-Skeleton
-> übrige Node-/Runtime-/Artifact-Protokollhandler
-> Activation-Payload-Transport-Benchmark
-> gemeinsame Zwei-Node-Inferenz
-> Scheduler-Automatisierung
```

## Sicherheitshinweis

Experimentelle Runtime-RPC- oder Benchmark-Endpunkte dürfen nicht direkt dem öffentlichen Internet ausgesetzt werden. `confidential_compute` ist keine zulässige Garantie, solange kein konkretes Trusted-Execution-/Attestation-Design existiert.

## Sprach-Synchronisationsregel

`README.md` und `README.de.md` müssen bei jeder öffentlich relevanten Projektänderung gemeinsam aktualisiert werden.

## Lizenz

Alle Rechte bleiben vorbehalten, bis ausdrücklich eine Lizenz ausgewählt und veröffentlicht wird. Repository-Sichtbarkeit gewährt keine Open-Source-Nutzungsrechte.
