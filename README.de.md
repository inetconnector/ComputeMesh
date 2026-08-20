# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Projektphase:** M0 — Architektur, Protokoll, Sicherheit, Benchmarking und Machbarkeitsforschung.  
> **Produktionsstatus:** Es existieren noch keine produktive Runtime, kein Marktplatz, kein Scheduler, kein Abrechnungssystem und keine öffentlich nutzbare Node-Software.

ComputeMesh ist ein experimentelles System für verteilte KI-Inferenz. Es soll heterogene Rechenressourcen zu einer logisch einheitlichen Ausführungsumgebung verbinden. Die zentrale Produktthese lautet: Ein Client mit wenig lokalem VRAM soll Modelle ausführen können, deren Speicher- und Rechenanforderungen den eigenen Rechner übersteigen, indem vertrauenswürdig eingebundene entfernte Rechenleistung genutzt wird — ohne dass der Nutzer Shards, Hosts, Ports oder die Platzierung manuell verwalten muss.

**North Star:** Der Nutzer wählt ein Modell und eine Richtlinie. ComputeMesh entscheidet, ob die Anfrage ausführbar ist, wählt kompatible Kapazität, bereitet Modellpartitionen vor, führt die Inferenz aus, behandelt Ausfälle, verifiziert Ergebnisse risikobasiert und erzeugt einen nachvollziehbaren Kosten- und Abrechnungsnachweis.

Der Satz **„The internet is your GPU“** ist eine Produktmetapher und keine Behauptung, dass beliebige über das Internet verbundene GPUs mit der Effizienz eines Rechenzentrums gekoppelt werden können. Netzwerklatenz, Bandbreite, Jitter, Hardware-Heterogenität, Vertrauen in Provider, Modelllizenzen und Ausfallwahrscheinlichkeit sind zentrale Systemgrenzen.

## Was ComputeMesh ist

ComputeMesh ist als **modellbewusstes, verteiltes Inferenz-Fabric** geplant, mit:

- automatischer Registrierung von Provider-Nodes, Hardware-Erkennung und Benchmarking;
- signierten Modell- und Shard-Manifesten;
- topologiebewusster Platzierung mit harten Datenschutz-, Kompatibilitäts-, Speicher- und Policy-Constraints;
- Pipeline-, Expert-, Data-Parallel- und — wo geeignet — lokalem Tensor-Parallelismus;
- Kapazitätsreservierung und ausfallbewusster Neuplanung;
- strukturierter Telemetrie und reproduzierbaren Benchmark-Nachweisen;
- risikobasierter Verifikation und Node-Reputation;
- nachvollziehbarer Fiat-Abrechnung und Provider-Vergütung;
- einer Windows-first-Provider-Erfahrung für V1;
- einer OpenAI-kompatiblen öffentlichen API plus ComputeMesh-spezifischen Policy-Optionen.

## Was ComputeMesh nicht ist

V1 ist bewusst **nicht**:

- ein allgemeiner VM- oder Container-Marktplatz;
- eine Plattform zur Ausführung beliebiger Shell-, Python-, CUDA- oder Container-Workloads von Kunden auf Provider-PCs;
- ein Kryptowährungs-, ICO-, Mining- oder Renditeprodukt;
- die Behauptung, WAN-Tensor-Parallelismus sei generell praktikabel;
- das Versprechen, dass Prompts auf nicht vertrauenswürdigen Consumer-Nodes vertraulich bleiben;
- ein Ersatz für Hochgeschwindigkeits-GPU-Interconnects innerhalb von Rechenzentren;
- heute bereits ein produktionsreifes System.

## Zentrale Engineering-Invarianten

Diese Regeln sind stärker als bloße Implementierungspräferenzen. Änderungen erfordern einen ADR.

1. **In V1 wird auf Provider-Nodes kein beliebiger Kundencode ausgeführt.**
2. **Harte Scheduling-Constraints werden vor jeder Optimierung ausgewertet.**
3. **Arbeit darf nur abgerechnet werden, wenn die Plattform sie eindeutig zuordnen und auditieren kann.**
4. **Retry, Replay, Timeout oder doppelte Events dürfen weder doppelte Vergütung noch doppelte Zustandsfortschritte verursachen.**
5. **Provider-Nodes werden als potenziell ausfallend, getrennt, fehlerhaft, unehrlich oder kompromittiert betrachtet.**
6. **Public Compute bedeutet nicht automatisch Vertraulichkeit von Prompts.**
7. **Performance-Aussagen benötigen reproduzierbare Messungen mit dokumentierten Testbedingungen.**
8. **Die Data Plane transportiert nur Daten aus freigegebenen Inferenzprotokollen.**
9. **Modellartefakte sind unveränderlich, content-addressed, versioniert und werden vor der Ausführung verifiziert.**
10. **Das System muss erklären können, warum eine Platzierung akzeptiert oder verworfen wurde.**

## Architektur im Überblick

```text
                         +-----------------------+
 Client / SDK ---------->| Gateway / API         |
                         +-----------+-----------+
                                     |
                                     v
                         +-----------------------+
                         | Job Orchestrator      |
                         +-----------+-----------+
                                     |
                  +------------------+------------------+
                  |                  |                  |
                  v                  v                  v
          +---------------+  +---------------+  +----------------+
          | Scheduler     |  | Registry      |  | Policy/Trust   |
          | + topology    |  | models/shards |  | verification   |
          +-------+-------+  +-------+-------+  +--------+-------+
                  |                  |                   |
                  +------------------+-------------------+
                                     |
                              reservations
                                     |
                                     v
             +---------------- Provider execution mesh ----------------+
             |                                                          |
             |  Node A  <---- activation/result streams ---->  Node B   |
             |    |                                             |       |
             | local layers/KV                              local layers/KV|
             |                                                          |
             +----------------------------------------------------------+
                                     |
                                     v
                         +-----------------------+
                         | Telemetry + Ledger    |
                         +-----------------------+
```

### Control Plane

Die Control Plane verwaltet Identität, Enrollment, Policies, Topologie, Modellmetadaten, Scheduling, Reservierungen, Job-Zustände, Verifikationsrichtlinien, Telemetrie-Aggregation und Abrechnungsdaten.

### Data Plane

Die Data Plane führt einen bereits genehmigten Plan aus. Bei einem dichten Pipeline-Pfad besteht der normale Inter-Node-Datenverkehr pro Token hauptsächlich aus **Aktivierungsdaten zwischen Stages**, nicht aus der fortlaufenden Übertragung des gesamten KV-Caches. Der KV-Zustand soll normalerweise bei den Layern verbleiben, zu denen er gehört; KV-Migration ist vor allem ein Recovery-, Migrations- oder Rebalancing-Vorgang.

### Provider-Node

Ein Provider-Node stellt eingeschränkte Inferenzkapazität bereit, keinen allgemeinen Remote-Rechner. Er meldet Fähigkeiten und Verfügbarkeit, akzeptiert signierte Assignments, bereitet verifizierte Modellartefakte vor, führt genehmigte Stages aus, sendet begrenzte Telemetrie und kann kontrolliert in einen Drain-Zustand wechseln.

## Machbarkeits-Gates

ComputeMesh wird forschungs- und messwertgetrieben entwickelt. Produktumfang wird erst erweitert, wenn ausreichende Evidenz vorhanden ist.

| Gate | Frage | Mindestnachweis |
| --- | --- | --- |
| G1 — Ausführung | Können heterogene Geräte automatisch gemeinsam einen Modellpfad ausführen? | automatische Platzierung, gemeinsames Inferenzergebnis, messbare Compute-/Transfer-/Queue-Zeiten |
| G2 — Netzwerk | Welche verteilten Modi bleiben über reale Netzwerke nutzbar? | LAN-/WAN-Messungen für TTFT, Decode-Rate, Traffic/Token, Jitter, Paketverlust und Recovery |
| G3 — Wirtschaftlichkeit | Ist Cost/Token nach allen Overheads glaubwürdig? | Provider-Kostenmodell, Verifikationsaufwand, Netzwerkkosten, Reserve und Plattformmarge |
| G4 — Vertrauen | Kann nicht vertrauenswürdige Kapazität genutzt werden, ohne unvertretbare Sicherheits- oder Korrektheitsrisiken? | signierte Workload-Grenze, Identität, Auditierbarkeit, Verifikationsnachweise und Missbrauchsschutz |
| G5 — Betrieb | Können nicht spezialisierte Provider Nodes sicher betreiben? | Installer/Update/Rollback, Diagnostik, Temperaturgrenzen, sauberer Drain und Supportfähigkeit |

Ein nicht bestandenes Gate bedeutet nicht automatisch das Ende des Projekts. Es kann die Positionierung von globaler interaktiver Dense-Inferenz hin zu regionalen Clustern, Batch-Verarbeitung, dedizierten Providern oder MoE-/Expert-orientierter Forschung verschieben.

## Repository-Struktur

```text
ComputeMesh/
├─ apps/
│  ├─ node/          # Provider-Daemon/lokale UX
│  ├─ desktop/       # Desktop-UX für Endnutzer
│  ├─ dashboard/     # Web-UX
│  └─ admin/         # Operations-UX
├─ services/
│  ├─ gateway/
│  ├─ scheduler/
│  ├─ registry/
│  ├─ billing/
│  ├─ verification/
│  └─ telemetry/
├─ runtime/
│  ├─ cuda/
│  ├─ llama/
│  ├─ vllm/
│  └─ network/
├─ protocol/
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

## Dokumentationsübersicht

Empfohlene Reihenfolge:

1. `README.md` / `README.de.md` — Projektgrenzen und aktueller Stand in Englisch bzw. Deutsch.
2. `IMPLEMENTATION_PLAN.md` — Meilensteine, Abhängigkeiten, Gates und Definition-of-Done.
3. `ARCHITECTURE.md` — Systemgrenzen, Datenflüsse, Konsistenz- und Scheduling-Modell.
4. `PROTOCOL.md` — Protokoll-Envelope, Control Messages, Transportsemantik, Fehler, Retries und Kompatibilität.
5. `THREAT_MODEL.md` — Assets, Akteure, Trust Boundaries, Bedrohungen, Gegenmaßnahmen und Restrisiken.
6. `docs/BENCHMARK_SPEC.md` — reproduzierbare Messungen, die vor Scheduler-Entscheidungen benötigt werden.
7. `docs/DATA_MODEL.md` — kanonische Entitäten und Invarianten.
8. `docs/FAILURE_SEMANTICS.md` — Zustandsübergänge, Leases, Retries, Replanning und Billing-Neutralität.
9. `docs/PRIVACY_TIERS.md` — Garantien und ausdrücklich ausgeschlossene Garantien je Privacy-Tier.
10. `state.md` — aktuelle Fakten, Entscheidungen, Blocker und nächste Schritte.

## Geplante Technologieausrichtung

Diese Punkte sind **Kandidaten**, noch keine endgültigen Entscheidungen:

- **Go** — Control-Plane-Services und Node-Daemon;
- **C++/CUDA** — performancekritische Runtime-Integration;
- **Python** — ML-Systems-Forschung und Benchmarking;
- **TypeScript/React** — Desktop- und Web-Oberflächen;
- **PostgreSQL** — persistenter Control-Plane- und Ledger-Zustand;
- **gRPC/HTTP2 und QUIC-basierte Transporte** — Versuchskandidaten für Control- und Data-Plane-Anforderungen;
- **llama.cpp und vLLM** — Referenz-Runtime-Integrationen, die evaluiert und nicht lediglich blind umschlossen werden sollen.

Jede Wahl muss durch einen ADR dokumentiert werden, bevor sie zu einer festen Projektabhängigkeit wird.

## Aktueller realer Stand

Implementiert:

- Repository-Struktur;
- Architektur-, Protokoll-, Sicherheits- und Implementierungsplanung;
- ADR-Prozess;
- Dokumentations-Bootstrap.

Noch nicht implementiert:

- ausführbarer Node;
- Gateway/API;
- Scheduler;
- Model Registry;
- verteilte Runtime;
- Verification Service;
- Billing Ledger;
- Telemetry Service;
- Desktop-/Dashboard-Apps;
- Deployment;
- automatisierte Tests.

## Entwicklungssetup

Es gibt noch keine Anwendung, die gebaut werden kann. In M0 besteht das Setup primär aus Dokumentation und Forschung.

```powershell
git clone <repository-url>
cd ComputeMesh
Get-Content README.de.md
Get-Content state.md
Get-Content IMPLEMENTATION_PLAN.md
```

Sobald Code hinzukommt, müssen exakte Toolchain-Versionen in einem reproduzierbaren Bootstrap-Skript und einem CI-Image festgeschrieben werden, statt ausschließlich als Prosa dokumentiert zu sein.

## Sicherheitshinweis

Experimentelle Runtime-RPC-Endpunkte dürfen nicht direkt dem öffentlichen Internet ausgesetzt werden. Jede Drittanbieter-Runtime muss entsprechend ihrer eigenen Sicherheitslage behandelt und vor Provider-Nutzung hinter ComputeMesh-Authentifizierung, Autorisierung, Workload-Beschränkung, Rate Limits und Netzwerk-Policies gekapselt werden.

Siehe `SECURITY.md` und `THREAT_MODEL.md`.

## Sprache und Synchronisationsregel

Die Root-Dokumentation wird dauerhaft zweisprachig gepflegt:

- `README.md` — Englisch;
- `README.de.md` — Deutsch.

Beide Dateien müssen bei jeder Änderung an Projektstatus, Produktgrenzen, Architekturüberblick, Setup, Roadmap, Sicherheitswarnungen oder anderen öffentlich relevanten Informationen **im selben Change gemeinsam aktualisiert werden**. Eine der beiden Dateien darf nicht dauerhaft hinter der anderen zurückbleiben.

## Lizenz

Das Projekt bleibt „all rights reserved“, bis der Eigentümer ausdrücklich eine Lizenz auswählt und veröffentlicht. Aus Sichtbarkeit des Repositories oder Zugriff auf den Quelltext dürfen keine Open-Source-Nutzungsrechte abgeleitet werden.
