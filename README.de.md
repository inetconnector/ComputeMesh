# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Projektphase:** M0 — Verträge/Schemas, Benchmarking, Orchestrierungssemantik, Protokoll-/Session-Grundlagen, Sicherheit und Machbarkeitsforschung.  
> **Implementierungsstatus:** Ausführbare M0-Benchmark-Werkzeuge, maschinenlesbare Verträge, transaktionale Job-/Reservation-Persistenz, erste dauerhafte Control-Handler und eine authentifizierungspflichtige Node-Session-State-Machine existieren. Es gibt weiterhin keine produktive verteilte Runtime, keinen Scheduler, Marktplatz, kein Abrechnungssystem, keinen produktiven Credential-Verifier und keine öffentlich nutzbare Provider-Node-Software.

ComputeMesh ist ein experimentelles System für verteilte KI-Inferenz. Heterogene Rechenressourcen sollen als logisch einheitliche Ausführungsumgebung nutzbar werden. Ein Client mit wenig lokalem VRAM soll später ein Modell ausführen können, dessen Speicher- und Rechenanforderungen den eigenen Rechner übersteigen, ohne Shards, Hosts, Ports oder Platzierung manuell verwalten zu müssen.

**North Star:** Der Nutzer wählt Modell und Richtlinie. ComputeMesh prüft Machbarkeit, wählt kompatible Kapazität, bereitet verifizierte Modellpartitionen vor, führt Inferenz aus, behandelt Ausfälle, verifiziert Ergebnisse risikobasiert und erzeugt einen auditierbaren Kostennachweis.

„The internet is your GPU“ ist eine Produktmetapher und keine Performance-Garantie. WAN-Latenz, Bandbreite, Jitter, Hardware-Heterogenität, Provider-Vertrauen, Modelllizenzen und Ausfallwahrscheinlichkeit sind zentrale Systemgrenzen.

## Aktueller Stand

### In M0 implementiert

- zweisprachige Root-Dokumentation und ADR-Prozess;
- Architektur-, Protokoll-, Sicherheits-, Benchmark-, Failure-, Privacy- und Data-Model-Spezifikationen;
- maschinenlesbare Draft-2020-12-Verträge für zentrale State-/Control-Records und die ersten Control-Message-Payloads;
- Inventory-, TCP-Netzwerk- und llama.cpp-`llama-bench`-Messwerkzeuge;
- deterministische Job-/Reservation-State-Machine-Semantik;
- transaktionale SQLite-Referenzpersistenz mit dauerhafter Idempotenz, Optimistic Revisions, Leases, Restart-Recovery, Request-Fingerprints und Schema-Migration;
- atomare `CommitReservation`-Bindung einer Reservation an konkreten Job + Stage;
- gemeinsame Control-Envelope-Prüfung und strukturierte Fehler;
- dauerhafte Handler für `ReserveCapacity`, `CommitReservation` und `CancelJob`;
- transportneutraler Node-Session-Lifecycle: `Hello -> Authenticate -> CapabilityNegotiation -> ProfileSync -> BenchmarkStatus -> READY -> DRAINING/CLOSED`;
- zwingend einzuspeisende `AuthenticationVerifier`-Schnittstelle **ohne permissiven Default**;
- Session-Challenge-Bindung, Credential-Expiry-Prüfung, Konsistenz von NodeHello-/authentifizierter Node-ID, Capability-Intersection, Profile-/Benchmark-Revision-Gating und externes Session-Terminate für Revocation-Signale.

### Noch nicht implementiert / noch nicht nachgewiesen

- reale llama.cpp-Benchmark-Evidenz mit Ziel-Lab-GPU/Modell;
- reale Zwei-Node-LAN-/WAN-Benchmark-Evidenz;
- produktiver Provider-Node-Agent;
- Runtime Worker bzw. gemeinsame verteilte Inferenz;
- Gateway/API und produktiver Scheduler;
- produktiver Orchestrator-Netzwerkservice/Datenbankadapter;
- produktives Node-Credential-Format, kryptografischer Verifier, Issuer-/Enrollment-Service, OS-geschützte Private-Key-Integration, Rotation oder Revocation-Backend;
- Wire-Handler/-Verträge für NodeHello/NodeAuthenticate/ProfileSync und die übrigen Node-/Runtime-/Artifact-Protokollnachrichten;
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

## Repository-Struktur

```text
ComputeMesh/
├─ apps/                  # geplante Produktoberflächen
├─ services/orchestrator/ # dauerhafter M0-State + erste Control-Handler
├─ runtime/               # geplante CUDA/llama.cpp/vLLM/Network-Integrationen
├─ protocol/              # Envelope, Payload-Verträge, Session-Semantik, Tests
├─ tools/benchmark/       # Inventory, TCP-Netzwerk, llama-bench-Adapter
├─ models/
├─ sdk/
├─ tests/
├─ deploy/
├─ research/
└─ docs/
```

## Aktuelle M0-Werkzeuge/Tests ausführen

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

Ein realer Modell-/Hardware-Lauf ist weiterhin erforderlich, bevor M1-Performanceaussagen zulässig sind.

## Protokoll-, Persistenz- und Session-Grundlagen

Der initiale dauerhafte Control-Pfad validiert gemeinsamen Envelope und operationsspezifischen Payload, bildet einen Fingerprint aus Message Type + Payload und führt danach einen atomaren SQLite-State-Effekt aus; die Envelope-`request_id` dient als dauerhafter Idempotency-Key. Replays haben genau einen Geschäftseffekt, veränderte Payload-Wiederverwendung wird abgelehnt.

Die ersten Handler decken ausschließlich bereits in `PROTOCOL.md` benannte Operationen ab: `ReserveCapacity`, `CommitReservation` und `CancelJob`.

`protocol/node_session.py` modelliert nun die dokumentierte Readiness-Reihenfolge und lässt keinen Fortschritt über Authentication hinaus zu, solange der Aufrufer keinen `AuthenticationVerifier` bereitstellt, der eine gültige, nicht abgelaufene und an die Session-Challenge gebundene Identity-Entscheidung zurückgibt. **Die Schnittstelle selbst ist noch kein produktiver Authentifizierungsmechanismus.** ADR 0005 bleibt Proposed.

## Runtime-Ausrichtung

Der erste vorgeschlagene M1-Forschungspfad ist llama.cpp-orientiert und wird hinter der ComputeMesh-Node-/Worker-Grenze gekapselt. vLLM bleibt Vergleich/Referenz. ADR 0002 ist weiterhin **Proposed**, nicht Accepted.

## Unmittelbare Engineering-Reihenfolge

```text
maschinenlesbare Verträge + Benchmark-Harnesses                [M0 implementiert]
dauerhafter Job-/Reservation-State + erste Handler             [M0 implementiert]
gemeinsamer Envelope + strukturierte Fehler                     [M0 implementiert]
authentifizierungspflichtige Node-Session-Semantik              [M0 implementiert]
-> Inventory-/Netzwerk-/Runtime-Messungen auf realen Nodes
-> konkrete Node-Credential-Verifikation über ADR 0005 auswählen/implementieren
-> NodeHello/Auth/Profile-Nachrichten an den Session-Skeleton binden
-> llama.cpp-orientierter M1-Runtime-Spike
-> Activation-Payload-Transport-Benchmark
-> gemeinsame Zwei-Node-Inferenz
-> Scheduler-Automatisierung
```

## Sicherheitshinweis

Experimentelle Runtime-RPC- oder Benchmark-Endpunkte dürfen nicht direkt dem öffentlichen Internet ausgesetzt werden. Die `AuthenticationVerifier`-Schnittstelle darf nicht als Nachweis einer produktionsreifen Node-Authentifizierung behandelt werden. `confidential_compute` ist keine zulässige Garantie, solange kein konkretes Trusted-Execution-/Attestation-Design existiert.

## Sprach-Synchronisationsregel

`README.md` und `README.de.md` müssen bei jeder öffentlich relevanten Projektänderung gemeinsam aktualisiert werden.

## Lizenz

Alle Rechte bleiben vorbehalten, bis ausdrücklich eine Lizenz ausgewählt und veröffentlicht wird. Repository-Sichtbarkeit gewährt keine Open-Source-Nutzungsrechte.
