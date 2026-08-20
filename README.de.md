# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Projektphase:** M0 — Verträge/Schemas, Benchmarking, Architektur, Protokoll, Sicherheit und Machbarkeitsforschung.  
> **Implementierungsstatus:** Die ersten ausführbaren M0-Engineering-Werkzeuge existieren; es gibt noch keine produktive Runtime, keinen Marktplatz, Scheduler, kein Abrechnungssystem und keine öffentlich nutzbare Provider-Node-Software.

ComputeMesh ist ein experimentelles System für verteilte KI-Inferenz. Heterogene Rechenressourcen sollen als logisch einheitliche Ausführungsumgebung nutzbar werden. Ein Client mit wenig lokalem VRAM soll später ein Modell ausführen können, dessen Speicher- und Rechenanforderungen den eigenen Rechner übersteigen, ohne Shards, Hosts, Ports oder Platzierung manuell verwalten zu müssen.

**North Star:** Der Nutzer wählt Modell und Richtlinie. ComputeMesh prüft die Machbarkeit, wählt kompatible Kapazität, bereitet verifizierte Modellpartitionen vor, führt Inferenz aus, behandelt Ausfälle, verifiziert Ergebnisse risikobasiert und erzeugt einen auditierbaren Kostennachweis.

„The internet is your GPU“ ist eine Produktmetapher und keine Performance-Garantie. WAN-Latenz, Bandbreite, Jitter, Hardware-Heterogenität, Provider-Vertrauen, Modelllizenzen und Ausfallwahrscheinlichkeit sind zentrale Systemgrenzen.

## Aktueller Stand

### Implementiert

- zweisprachige Root-Dokumentation und ADR-Prozess;
- Architektur-, Protokoll-, Sicherheits-, Benchmark-, Failure-, Privacy- und Data-Model-Spezifikationen;
- JSON-Schema-Draft-2020-12-Verträge für:
  - Node Profile;
  - Benchmark Result;
  - Model Manifest;
  - Shard Manifest;
  - Reservation;
  - Job;
- konkrete Beispiel-Manifeste, Jobs und Reservierungen;
- ein M0-Benchmark-Collector in Python nur mit Standardbibliothek, der Host-Inventar und bei vorhandenem `nvidia-smi` NVIDIA-GPU/VRAM/Treiber erfasst;
- Unit-Tests für den Benchmark-Collector.

### Noch nicht implementiert

- produktiver Provider-Node-Agent;
- Runtime Worker oder verteilte Inferenz;
- Gateway/API;
- Scheduler/Orchestrator;
- Model-Registry-Service;
- Verification-/Reputation-Service;
- Billing-/Ledger-Service;
- Telemetry-Service;
- Desktop-/Dashboard-Anwendungen;
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
Client / SDK
    |
    v
Gateway / API
    |
    v
Job Orchestrator
    |
    +------> Scheduler + Topology
    +------> Registry
    +------> Policy / Verification
    |
    v
Kapazitätsreservierungen
    |
    v
Provider Execution Mesh
Node A <---- Activation-/Result-Streams ----> Node B
    |
    v
Telemetry / Metering / Ledger
```

Bei dichter Pipeline-Ausführung sollen zwischen Nodes normalerweise Stage-Aktivierungen/-Ergebnisse übertragen werden. Der KV-Cache verbleibt grundsätzlich bei den Layern, zu denen er gehört; KV-Transfer ist primär ein Migrations-, Recovery- oder Rebalancing-Vorgang.

## Machbarkeits-Gates

| Gate | Frage | Mindestnachweis |
| --- | --- | --- |
| G0 | Ist M1 ausreichend definiert? | erforderliche ADRs, Schemas, Labordefinition, testbare DoD |
| G1 | Können heterogene Geräte automatisch einen Modellpfad ausführen? | automatische Platzierung, korrektes gemeinsames Ergebnis, gemessene Zeiten |
| G2 | Welche Modi funktionieren über reale Netze? | LAN/WAN-TTFT, Decode, Traffic, Jitter/Loss/Recovery |
| G3 | Ist Cost/Token glaubwürdig? | gemessene Ausführung + Verifikations-/Netzwerk-/Payment-Ökonomie |
| G4 | Kann nicht vertrauenswürdige Kapazität sicher genug genutzt werden? | Workload-Grenze, Identität, Auditierbarkeit, Verifikation, Missbrauchsschutz |
| G5 | Können Nicht-Spezialisten Provider-Nodes betreiben? | Install/Update/Rollback/Diagnostik/Drain/Uninstall |

Ein nicht bestandenes Gate kann die geeignete Workload-Klasse ändern, ohne automatisch das gesamte Projekt zu beenden.

## Repository-Struktur

```text
ComputeMesh/
├─ apps/                 # geplante Node/Desktop/Dashboard/Admin-Oberflächen
├─ services/             # geplante Gateway/Scheduler/Registry/Billing/Verification/Telemetry-Services
├─ runtime/              # geplante CUDA/llama.cpp/vLLM/Network-Integrationen
├─ protocol/
│  ├─ schemas/           # maschinenlesbare M0-Verträge
│  └─ examples/          # Vertragsbeispiele
├─ tools/
│  └─ benchmark/         # erster ausführbarer M0-Collector + Unit-Tests
├─ models/
├─ sdk/
├─ tests/
├─ deploy/
├─ research/
└─ docs/
   ├─ adr/
   ├─ BENCHMARK_SPEC.md
   ├─ DATA_MODEL.md
   ├─ FAILURE_SEMANTICS.md
   ├─ PRIVACY_TIERS.md
   └─ TEST_MATRIX.md
```

## Erstes M0-Werkzeug ausführen

Für den aktuellen Collector genügt Python 3.10+; er hat keine Third-Party-Runtime-Abhängigkeit.

```powershell
git clone <repository-url>
cd ComputeMesh
python tools/benchmark/benchmark.py --dry-run
python -m unittest discover -s tools/benchmark/tests -v
```

Ein Lab-Profil schreiben:

```powershell
python tools/benchmark/benchmark.py --node-id lab-node-a --profile-revision 1
```

Die Ausgabe landet unter `artifacts/benchmark/` und wird von Git ignoriert.

Aktuell werden OS/Architektur, Python-Version, CPU/logische Kerne, physischer Speicher sowie – wenn vorhanden – NVIDIA-GPU-Name, VRAM und Treiberversion erfasst. Hostnamen, GPU-UUIDs, Prompts, Outputs und andere unnötige Identifikatoren werden bewusst nicht gesammelt.

## Empfohlene Dokumentationsreihenfolge

1. `state.md` — aktuelle Fakten, Blocker und nächste Schritte.
2. `IMPLEMENTATION_PLAN.md` — Gates, Meilensteine, Workstreams und Definition-of-Done.
3. `ARCHITECTURE.md` — Servicegrenzen und Ausführungs-/Scheduling-Modell.
4. `PROTOCOL.md` — Control-/Data-Plane-Semantik, Retries, Fehler, Leases, Cancellation.
5. `THREAT_MODEL.md` und `SECURITY.md` — Trust-Annahmen und Launch-Blocker.
6. `docs/BENCHMARK_SPEC.md` — Regeln für reproduzierbare Messungen.
7. `docs/DATA_MODEL.md` und `docs/FAILURE_SEMANTICS.md` — kanonische Entitäten und Zustände.
8. `protocol/schemas/` — aktuelle maschinenlesbare M0-Verträge.
9. `docs/adr/` — akzeptierte und vorgeschlagene Architekturentscheidungen.

## Runtime-Ausrichtung

Der erste vorgeschlagene M1-Forschungspfad ist llama.cpp-orientiert und wird hinter der ComputeMesh-Node-/Worker-Grenze gekapselt. vLLM bleibt Referenz für koordinierte Datacenter-Szenarien. ADR 0002 ist weiterhin **Proposed**, nicht Accepted. Die Runtime-Wahl wird erst akzeptiert, wenn ein Zwei-Node-Spike deterministische Platzierung, messbaren Transfer, Korrektheit, begrenzten Speicherverbrauch, Cancellation-/Failure-Verhalten und einen praktikablen Windows-Pfad nachweist.

Auch Control- und Data-Transport werden noch evaluiert. Transportverschlüsselung darf niemals mit vertraulicher Ausführung auf einem providerkontrollierten Host gleichgesetzt werden.

## Unmittelbare Engineering-Reihenfolge

```text
maschinenlesbare Verträge + Inventory-Harness   [gestartet]
-> Zwei-Node-Lab-Profile
-> Runtime-Spike
-> Reservation-/Job-State-Skeleton
-> Activation-Transport-Benchmark
-> gemeinsame Zwei-Node-Inferenz
-> Scheduler-Automatisierung
-> Failure-/Replan-Tests
```

Der Scheduler soll auf gemessenem Node-/Runtime-/Netzwerkverhalten basieren und nicht auf statischen GPU-Namenstabellen.

## Sicherheitshinweis

Experimentelle Runtime-RPC-Endpunkte dürfen nicht direkt dem öffentlichen Internet ausgesetzt werden. Drittanbieter-Runtimes sind Implementierungsdetails hinter ComputeMesh-Authentifizierung, Autorisierung, Workload-Beschränkungen, Rate Limits, Artefaktverifikation und Netzwerk-Policies.

`confidential_compute` ist keine zulässige Garantie, solange kein konkretes Trusted-Execution-/Attestation-Design existiert.

## Sprach-Synchronisationsregel

Die Root-Dokumentation wird dauerhaft in zwei synchronen Dateien gepflegt:

- `README.md` — Englisch;
- `README.de.md` — Deutsch.

Jede öffentlich relevante Änderung an Projektstatus, Produktgrenzen, Architekturüberblick, Setup, Roadmap oder Sicherheitswarnungen muss beide Dateien im selben Change aktualisieren.

## Lizenz

Das Projekt bleibt „all rights reserved“, bis ausdrücklich eine Lizenz ausgewählt und veröffentlicht wird. Die Sichtbarkeit des Repositories gewährt keine Open-Source-Nutzungsrechte.
