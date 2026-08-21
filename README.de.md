# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Projektphase:** M0 — Verträge/Schemas, Benchmarking, Orchestrierungssemantik, Protokollgrundlagen, Sicherheit und Machbarkeitsforschung.  
> **Implementierungsstatus:** Ausführbare M0-Inventory-/Netzwerk-/Runtime-Benchmark-Werkzeuge, maschinenlesbare Verträge, transaktionale Job-/Reservation-Persistenz und ein transportneutraler Control-Envelope-Parser existieren. Es gibt weiterhin keine produktive verteilte Runtime, keinen Scheduler, Marktplatz, kein Abrechnungssystem und keine öffentlich nutzbare Provider-Node-Software.

ComputeMesh ist ein experimentelles System für verteilte KI-Inferenz. Heterogene Rechenressourcen sollen als logisch einheitliche Ausführungsumgebung nutzbar werden. Ein Client mit wenig lokalem VRAM soll später ein Modell ausführen können, dessen Speicher- und Rechenanforderungen den eigenen Rechner übersteigen, ohne Shards, Hosts, Ports oder Platzierung manuell verwalten zu müssen.

**North Star:** Der Nutzer wählt Modell und Richtlinie. ComputeMesh prüft Machbarkeit, wählt kompatible Kapazität, bereitet verifizierte Modellpartitionen vor, führt Inferenz aus, behandelt Ausfälle, verifiziert Ergebnisse risikobasiert und erzeugt einen auditierbaren Kostennachweis.

„The internet is your GPU“ ist eine Produktmetapher und keine Performance-Garantie. WAN-Latenz, Bandbreite, Jitter, Hardware-Heterogenität, Provider-Vertrauen, Modelllizenzen und Ausfallwahrscheinlichkeit sind zentrale Systemgrenzen.

## Aktueller Stand

### Implementiert

- zweisprachige Root-Dokumentation und ADR-Prozess;
- Architektur-, Protokoll-, Sicherheits-, Benchmark-, Failure-, Privacy- und Data-Model-Spezifikationen;
- Draft-2020-12-Schemas für Node Profile, Benchmark Result, Model-/Shard-Manifeste, Reservation, Job, gemeinsamen Control Envelope und strukturierte Protokollfehler;
- Python-Inventory-Benchmark-Collector nur mit Standardbibliothek;
- TCP-Netzwerk-Microbenchmark nur mit Standardbibliothek für Connection Setup, Small-Frame-RTT p50/p95, Upload-/Download-Durchsatz und Rohsamples;
- llama.cpp-`llama-bench`-Adapter, der getrennte Prompt-Processing-/Generation-Messungen in `llama_cpp_prefill`- und `llama_cpp_decode`-Benchmark-Records umwandelt;
- deterministische Job-/Reservation-State-Machine-Semantik;
- transaktionale SQLite-M0-Persistenz mit dauerhafter Idempotenz, Revisionen, Lease-Persistenz/-Expiry, Stale-Writer-Schutz, Rollback und Restart-Recovery;
- JSON-Schema-basierte Job-/Reservation-Admission;
- transportneutraler gemeinsamer Control-Envelope-Parser mit Versions-/Zeit-/Formprüfung und strukturierten Fehlern;
- Tests für die implementierten M0-Komponenten.

### Noch nicht implementiert / noch nicht nachgewiesen

- reale llama.cpp-Benchmark-Evidenz mit Lab-GPU/Modell;
- reale Zwei-Node-LAN-/WAN-Benchmark-Evidenz;
- produktiver Provider-Node-Agent;
- Runtime Worker bzw. gemeinsame verteilte Inferenz;
- Gateway/API und produktiver Scheduler;
- produktiver Orchestrator-Netzwerkservice/Datenbankadapter;
- authentifizierte Node-Sessions und Autorisierung;
- nachrichtenspezifische Node-/Orchestrator-Protokollhandler;
- Registry, Verification, Billing/Ledger, Telemetry, SDK, UI;
- produktive Deployment-/Update-Pipeline;
- öffentliche Veröffentlichung.

Der kanonische Handoff steht in `state.md`.

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
├─ services/orchestrator/ # M0 State Machine, Persistenz, Schema-Admission
├─ runtime/               # geplante CUDA/llama.cpp/vLLM/Network-Integrationen
├─ protocol/              # Control Envelope, Schemas, Tests
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

Der Adapter führt Upstream-`llama-bench` mit getrennten Prompt-Processing-/Generation-Tests aus und konvertiert das JSON in ComputeMesh-Benchmark-Records. Er ist ein **Adapter und noch kein Nachweis für M1**: Ein realer Modell-/Hardware-Lauf fehlt weiterhin.

## Protokoll- und Persistenzgrundlagen

`services/orchestrator/persistence.py` ist eine M0-SQLite-Referenz für atomare State-/Idempotency-Effekte, Optimistic Revision Checks, restartfeste Replays, Leases und Stale-Writer-Schutz. SQLite ist **nicht** als Produktionsdatenbank ausgewählt; PostgreSQL bleibt die Control-Plane-Richtung.

`protocol/control.py` implementiert die gemeinsame Control-Envelope-Semantik aus `PROTOCOL.md`, ohne gRPC, QUIC, HTTP oder einen anderen Transport auszuwählen. Authentifizierung, Autorisierung, nachrichtenspezifische Payload-Handler und Capability Negotiation fehlen noch.

## Runtime-Ausrichtung

Der erste vorgeschlagene M1-Forschungspfad ist llama.cpp-orientiert und wird hinter der ComputeMesh-Node-/Worker-Grenze gekapselt. vLLM bleibt Vergleich/Referenz. ADR 0002 ist weiterhin **Proposed**, nicht Accepted.

## Unmittelbare Engineering-Reihenfolge

```text
maschinenlesbare Verträge + Inventory-Harness                 [M0 implementiert]
transaktionale Job-/Reservation-Persistenz + Schema-Admission [M0 implementiert]
gemeinsamer Control Envelope + strukturierte Fehler            [M0 implementiert]
TCP-Lab-Netzwerk-Microbenchmark                                [M0 implementiert]
llama-bench-Prefill-/Decode-Adapter                            [M0 implementiert]
-> Inventory-/Netzwerk-/Runtime-Messungen auf realen Nodes
-> llama.cpp-orientierter M1-Runtime-Spike
-> nachrichtenspezifische Protocol-Handler
-> authentifizierter Node-Session-Skeleton
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
