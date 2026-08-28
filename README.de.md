# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Phase:** aktive Pre-Production-Entwicklung: verifizierte M1-Shared-Runtime-Evidenz im Trusted Lab plus implementierte Live-Gateway-/Provider-Control-/Orchestrator-Grundlagen und eine private Produktions-Policy-Control-Plane-Grenze.
> **Wichtig:** ComputeMesh ist **noch kein allgemein produktionsreifes verteiltes Inferenzprodukt**. Breite physische LAN-/WAN-Validierung, providerseitig erzwungene Resource-Leases, Produktions-Data-Plane-Sicherheit sowie Key-/Session-Härtung bleiben Gates.

Für den aktuellen öffentlich vertretbaren Status zuerst **[docs/CURRENT_STATUS.de.md](docs/CURRENT_STATUS.de.md)** lesen. `state.md` bleibt die detaillierte öffentliche Engineering-/Evidenzhistorie; proprietärer aktueller Produktions-Policy-Status gehört in `ComputeMesh-ControlPlane/STATE.md` des privaten Repositories.

ComputeMesh untersucht, ob heterogene Rechner als gemeinsames modellbewusstes KI-Inferenz-Fabric arbeiten können. Langfristig soll der Nutzer nur Modell und Richtlinie wählen; ComputeMesh übernimmt Machbarkeit, Platzierung, Vorbereitung, Ausführung, Fehlerbehandlung, Verifikation und nachvollziehbare Abrechnung.

## Einfachster Einstieg in die Lab-Werkzeuge

Repository klonen/herunterladen und den Starter für das Betriebssystem verwenden:

**Windows:** `SETUP.cmd` doppelklicken  
**Linux:** `./setup.sh` ausführen (oder `bash setup.sh`, falls das Ausführungsbit verloren ging).

Beide Starter bieten dasselbe einfache Menü für Rechnerprofil, vertrauenswürdige LAN-RTT-/Durchsatzmessung, lokales llama.cpp-Benchmarking und die aktuell vollständige lokale Testsuite. Neue Netzwerkmessungen tragen zusätzlich die lokale Lab-Setup-Node-ID und – wenn die Gegenseite den aktuellen Benchmark-Server verwendet – dessen selbst gemeldete Lab-Setup-Node-ID. Modellgewichte werden niemals automatisch heruntergeladen.

Für die aktuelle M1-Evidenzübergabe zwischen zwei Rechnern kann der Worker unter Windows mit `setup\EVIDENCE-EXPORT.cmd` oder unter Linux mit `bash setup/EVIDENCE-EXPORT.sh` eine begrenzte Evidenz-ZIP erzeugen. Der Coordinator kann diese ZIP prüfen/importieren und mit `setup\BUILD-BUNDLE.cmd` bzw. `bash setup/BUILD-BUNDLE.sh` das aktuelle Experiment-Bundle bauen. Sobald das Bundle `shared_experiment` empfiehlt, wird der Trusted-LAN-RPC-Worker mit `setup\SHARED-WORKER.cmd` / `bash setup/SHARED-WORKER.sh` gestartet und der gebundene Baseline→Relay→Shared→Compare→Proof-Ablauf mit `setup\SHARED-PROOF.cmd` / `bash setup/SHARED-PROOF.sh` ausgeführt. Die ZIP enthält keine GGUF-Gewichte und keine llama.cpp-Binaries.

Die genaue Zwei-Rechner-Anleitung steht in [setup/README.de.md](setup/README.de.md).

## Aktuell implementiert

Zu den vorhandenen Grundlagen gehören inzwischen:

- plattformübergreifendes Windows-/Linux-Lab-Setup;
- Inventory-, TCP-Netzwerk- und llama.cpp-`llama-bench`-Messwerkzeuge;
- begrenzte GGUF-v3-Inspektion und konservative Modellmanifest-Erzeugung mit aus dem Artefakt abgeleiteter Architektur, Layerzahl, SHA-256 und Dateigröße;
- ein begrenzter Standardbibliothek-Lab-Evidenzexport/-import mit Datei-/Anzahllimits, SHA-256-Prüfung, Traversal-/Symlink-Ablehnung und atomarem Peer-Import;
- ein fail-closed M1-Experiment-Bundle-Builder, der einen konsistenten aktuellen Zwei-Node-Evidenzsatz auswählt und die daraus erzeugte Placement-Entscheidung mit Dokument-Digests bündelt;
- maschinenlesbare Draft-2020-12-State-/Control-Verträge;
- deterministische Job-/Reservation-Semantik und transaktionale SQLite-Referenzpersistenz;
- strikte transportneutrale Control-Envelopes und dauerhafte erste Handler;
- authentifizierungspflichtige Node-Session-Semantik und strikte erste Wire-Bindung;
- M1-Referenz-Node-Identity `computemesh-ed25519-v1` mit Enrollment-/Key-Rotation-/Revocation-Referenzzustand;
- einen authentifizierten persistenten Provider-Control-Pfad plus einen ausführbaren öffentlichen Provider-Agenten, der seine enrollte Ed25519-Identität nachweist, gemessene Profil-/Runtime-/Benchmark-Evidenz meldet, Reconnect unterstützt und begrenzte Execution Attestations signiert;
- eine authentifizierte OpenAI-kompatible und Ollama-kompatible Gateway-Oberfläche für den aktuellen Cluster-Modellkatalog;
- einen integrierten Live-Shared-Serving-Pfad mit dauerhafter Recovery/Cancellation, privatem remote-first globalem Placement, Ed25519-Prüfung signierter Execution Plans, Execution Evidence/Attestation und dauerhaftem gemessenem Outcome-Feedback;
- ein kontrollierter llama.cpp-RPC-**Research-Harness** für das erste gemeinsame M1-Runtime-Experiment;
- ein fail-closed One-Command-**Physical-Shared-Trial-Runner**, der Bundle/Modell/Geräte erneut prüft, den Planer-Split über das Relay ausführt, Korrektheit prüft und das gebundene Proof-Artefakt erzeugt;
- ein loopback-only TCP-**Mess-Relay** für opake RPC-Bytezählung, deterministische Userspace-Latenz/Jitter und kontrollierte Disconnects;
- einen echten Shared-Runtime-Network-Sensitivity-Matrix-Runner für kontrollierte Delay-/Jitter-Messpunkte, ohne Packet-Loss-/Bandwidth-Evidenz zu erfinden;
- einen deterministischen M1-**Zwei-Node-Placement-Planer**, der aus aktuellen Profilen, Modellmanifest, llama-bench-Evidenz und Netzwerkdaten nachvollziehbare Local-/Shared-Machbarkeitskandidaten erzeugt, ohne Distributed-Performance zu erfinden;
- ein Public-Portal-Crawl-Paket für `computemesh.inetconnector.com` mit Canonical-Metadaten, standardmäßig deutscher DE/EN-Lokalisierung, `robots.txt`, `sitemap.xml`, lokalen Server-Routen und Search-Console-Runbook;
- ein Ed25519-signiertes Update-Manifest und sichtbare Update-Bedienelemente im NodeOS-Webdashboard sowie in den Windows-/Linux-Provider-Apps, damit Nodes das neueste signierte Paket vom Webserver installieren können;
- fail-closed Provider-Kapazitätsmeldungen: lokale Provider-Inventare zählen nur gemessenen, gesunden dedizierten GPU-VRAM, und öffentliche/Dashboard-Global-Mesh-Karten zeigen keine VRAM-/TFLOPS-Gesamtwerte, solange keine authentifizierte Node-Registry diese liefert;
- registrierte Gateway-Key-Authentifizierung ohne eingebauten Admin-Zugang: `cm_live_...`- und `cm_provider_...`-Tokens müssen über den konfigurierten Key-Store oder statische Operator-Konfiguration registriert sein, während altes dynamisches Token-Verhalten nur über explizite Lab-Flags verfügbar ist;
- einen Web-Playground-Teaser mit 20 kostenlosen Anfragen pro konfigurierbarem Vier-Stunden-Clientfenster und optionalem privaten OpenAI-/Ollama-kompatiblem Demo-Upstream für echte Modellantworten, wenn er konfiguriert ist.

### Öffentliche/private Produktionsgrenze

`services/scheduler/placement.py` bleibt der offengelegte deterministische **Research-/Reference**-Machbarkeitsplaner, der unten beschrieben wird. Er ist nicht die produktive Ranking-Engine.

Produktive Placement-Machbarkeit/-Bewertung/-Auswahl, empirischer Performance-Zustand, Reputation/Fraud-Eligibility, private Recovery-Auswahl, Pricing/Marketplace-Policy und Settlement-Policy liegen im separaten privaten Repository `inetconnector/ComputeMesh-ControlPlane`. Der öffentliche Orchestrator übermittelt einen begrenzten Live-Candidate-/Network-Snapshot, akzeptiert nur einen signierten und nicht abgelaufenen Execution Plan, prüft diesen fail-closed und führt nur das minimale Placement-Ergebnis aus, ohne private Candidate-Scores oder Policy-Interna zu erhalten.

Verifizierte öffentliche Execution-Outcomes können dauerhaft an den privaten Feedback-Pfad geliefert werden. Dort entwickeln sich private Performance-/Reliability-Eingaben weiter, ohne in öffentlichen Placement-Antworten serialisiert zu werden.

## M1-Zwei-Node-Placement und Evidenzbundle

`services/scheduler/placement.py` ist die erste maschinenlesbare Placement-Komponente. Sie ist ein **Experiment-Machbarkeitsplaner**, kein produktiver Scheduler.

Geprüft werden unter anderem:

- Node-/Profile-Schemas und exakte Profilrevisionen;
- `draining` sowie stale/zu weit in der Zukunft liegende Profile;
- Größe des ausgewählten Modellartefakts gegen alle vier llama-bench-Datensätze;
- `contiguous_layers`-Erlaubnis im Modellmanifest;
- Provider-Memory-Fraction plus konservative Planer-Memory-Grenze;
- eine Coordinator→Worker-Netzwerkmessung, deren eingebettete lokale/Peer-Lab-IDs geprüft werden, sofern vorhanden;
- eine Layerzahl aus dem Modellmanifest, sofern dort vorhanden.

Mögliche Ergebnisse:

- `shared_experiment` — ein konservativer zusammenhängender Zwei-Node-Layer-Split ist speicherseitig machbar;
- `local_only` — nur die lokale Coordinator-Baseline ist aktuell machbar;
- `no_plan` — aktuelle harte Bedingungen/Speichergrenzen lassen keinen Kandidaten zu.

Die Ausgabe enthält eine deterministische `decision_id`, vollständige zusammenhängende Layerbereiche, relative `tensor_split`-Gewichte, Erklärungen der Hard Constraints und die gemessene Einzel-Compute-/Netzwerkevidenz.

Entscheidend: Der öffentliche Research-Planer erfindet keine Shared-Runtime-Prognosen, wenn keine kalibrierte Evidenz vorliegt:

```text
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

Aktuelle Netzwerk-Benchmark-Datensätze können `local_node_id`, `peer_node_id` und `peer_identity_binding` direkt enthalten; die heutige Server-Selbstmeldung wird als `unauthenticated_server_report_v1` gekennzeichnet. Damit entfällt ein manueller Zuordnungsschritt im Experiment, **die Gegenseite wird dadurch aber nicht authentifiziert**. Ältere Netzwerkdatensätze und Modellmanifeste bleiben im direkten Placement-CLI über explizite `caller_asserted_v1`-Fallbacks für Peer-ID bzw. Layerzahl nutzbar. Eingebettete Evidenz und ein gleichzeitig angegebener Fallback dürfen sich niemals widersprechen.

Für das aktuelle reale M1-Experiment ist `services/scheduler/evidence_bundle.py` bewusst strenger. Aus zwei Lab-Evidenzwurzeln plus Modellmanifest wählt es die höchste konsistente Profilrevision, Prefill-/Decode-Läufe mit exakt passender Manifest-Artefaktgröße für einen gemeinsamen Modell-Basename, verlangt für alle vier ausgewählten llama-bench-Datensätze beider Nodes dieselbe konkrete llama.cpp-Buildnummer/denselben Commit und wählt einen korrekt gerichteten Netzwerkdatensatz mit eingebetteter Local-/Peer-ID. **Caller-asserted Peer- oder Layer-Fallbacks sind dort nicht zulässig.** Mehrdeutige neueste Läufe, mehrere Node-Identitäten, falsch gerichtete/Legacy-Netzwerkevidenz, beschädigte evidenzähnliche JSON-Dateien und Modellgrößenkonflikte führen zum Abbruch.

Das resultierende `experiment_bundle.schema.json`-Artefakt enthält die vollständige validierte Placement-Entscheidung sowie sichere Quelldateinamen und SHA-256 jedes ausgewählten Quell-JSONs. Absolute lokale Pfade werden nicht gespeichert. Die Hashes machen den ausgewählten kopierten Evidenzsatz reproduzierbar, sind aber keine kryptografische Attestation darüber, wer diese Dateien ursprünglich erzeugt hat. Details: [services/scheduler/README.md](services/scheduler/README.md).

## Zwei-Rechner-Lab-Evidenztransfer

`setup/evidence_transfer.py` entfernt den manuellen Verzeichniskopierschritt rund um den Bundle-Builder und bleibt dabei bewusst ein lokales Trusted-Lab-Werkzeug.

Auf dem Worker scannt der Exportpfad nur den Lab-JSON-Baum des Nodes und schreibt eine ZIP mit erkannten Profil-/Benchmark-Evidenzen. Modellgewichte, llama.cpp-Runtime-Downloads, `config.json`, gemerkte lokale Pfade und beliebige Dateien werden ausgeschlossen. Jede enthaltene Datei wird in `computemesh-lab-export.json` über sicheren relativen Pfad, exakte Größe und SHA-256 gebunden.

Auf dem Coordinator arbeitet der Import fail-closed: Archiv-/Member-Anzahl sowie komprimierte/unkomprimierte Bytemengen sind begrenzt; die Member-Menge muss exakt zum Manifest passen; verschlüsselte/Symlink-/Traversal-Einträge werden abgelehnt; jede Datei wird beim Streamen gegen deklarierte Größe und SHA-256 geprüft; und die Extraktion wird erst nach atomarem Rename aus einem temporären Verzeichnis sichtbar. Ein erneuter Import prüft den vorhandenen Baum neu statt ihm zu vertrauen. Ein neuer Export derselben unveränderten Evidenz behält auch bei einem anderen Exportzeitpunkt dieselbe Evidenzidentität, weil der Exportzeitpunkt nur Beobachtungsmetadatum ist.

`setup/lab.py bundle --peer-export ... --model-manifest ...` übergibt danach den verifizierten importierten Worker-Baum zusammen mit dem lokalen Coordinator-Baum an den strengeren aktuellen Bundle-Selektor. Für Windows und Linux existieren direkte Starter. Export/Import verwenden ausschließlich die Python-Standardbibliothek; die kleine JSON-Schema-Abhängigkeit wird nur für die Bundle-Erzeugung benötigt.

**Grenze:** Die Hashes erkennen Beschädigungen/Änderungen in der kopierten Evidenz. Sie authentifizieren den Erzeuger nicht, signieren keinen Node und attestieren keine Hardware. Der Transferpfad bleibt eine Convenience-Funktion im kontrollierten Trusted Lab, kein produktiver Evidenztransport.

## GGUF → Modellmanifest

`tools/benchmark/gguf_manifest.py` entfernt einen weiteren manuellen M1-Zuordnungsschritt. Für eine lokale little-endian GGUF-v3-Datei kann das Werkzeug begrenzte standardisierte Metadaten lesen und daraus ableiten:

- `general.architecture`;
- `<architecture>.block_count` als Manifest-`layer_count`;
- bekannte standardisierte `general.file_type`-Quantisierungsbezeichnungen;
- Modellname/-version/-lizenz-Metadaten, sofern vorhanden;
- exakte lokale Dateigröße und per Streaming berechneten SHA-256-Digest.

Das Werkzeug führt keinen Modellcode aus und lädt keine Tensorinhalte in den Arbeitsspeicher. Fehlende oder nicht sicher zuordenbare Lizenz-/Versions-/Quantisierungsangaben müssen explizit übergeben werden; erlaubte Partitionierungsarten werden grundsätzlich explizit angegeben und nicht geraten.

Aktuelle llama.cpp-Split-Metadaten werden ebenfalls erkannt. Ein primärer Shard mit `split.count > 1` kann identifiziert werden, aber die Schema-v1-Manifest-Erzeugung wird bewusst verweigert: Digest/Größe eines einzelnen Shards repräsentieren nicht das vollständige Modell und Schema v1 modelliert Shard-Zugehörigkeit/-Reihenfolge noch nicht ausreichend explizit. Vor der Erzeugung des aktuellen ComputeMesh-Manifests muss der vollständige Shard-Satz zu einem GGUF zusammengeführt werden. Details: [tools/benchmark/README.md](tools/benchmark/README.md).

## Kontrolliertes llama.cpp-M1-Experiment

`runtime/llama/rpc_spike.py` kann aktuelle llama.cpp-Geräte ermitteln, eine deterministische lokale Baseline aufzeichnen, einen expliziten Local+RPC-`layer`-Split ausführen und exakt dasselbe Modell/denselben Prompt per Token-ID-Digest vergleichen, sofern vorhanden, sonst per Output-Digest. Modell-/Runtime-/Topologie-/Timing-Evidenz wird ohne Rohprompt-/Rohoutput-Persistenz gespeichert. `runtime/llama/shared_trial.py` fasst diesen engen First-Proof-Pfad jetzt in einem fail-closed Coordinator-Befehl zusammen: Bundle-Frische und exakte GGUF-Identität werden erneut geprüft, die aktuelle `llama-server`-Buildnummer/der Commit muss zu der aus beiden Nodes ausgewählten llama-bench-Evidenz gebundenen Build-Identität passen, aktuelle RPC-Sichtbarkeit wird vorab getestet, Baseline und Planer-Split laufen über ein frisches Mess-Relay, exakte Korrektheit wird verlangt und anschließend `shared_run_evidence.json` gebaut.

Der erste Experimentpfad hält Coordinator-HTTP auf `127.0.0.1`, beschränkt RPC auf literales Loopback/RFC1918-IPv4, nutzt `--offline`, deaktiviert automatisches Fit und Cache-Flächen und behandelt Upstream-RPC ausschließlich als Trusted-Lab-Implementierungsdetail. Der automatische Runner verlangt derzeit einen Accelerator-backed Coordinator, statt lokale CPU-Split-Semantik zu erfinden. Details: [runtime/llama/README.md](runtime/llama/README.md).

ADR 0002 hat einen in `state.md` aufgezeichneten physischen Trusted-Lab-Proof, aber der Harness bleibt ein Experimentpfad. Er ist für sich allein weder Produktionsruntime noch Sicherheitsgrenze, und jede neue Topologie/jedes neue Modell/jeder neue Runtime-Build braucht frische Evidenz.

## Runtime-Netzwerkmess-Relay

`runtime/network/tcp_relay.py` kann lokal zwischen llama-Coordinator und RPC-Worker im vertrauenswürdigen privaten LAN sitzen. Es lauscht nur auf `127.0.0.1`, verbindet nur zu literalem Loopback/RFC1918-IPv4, verwendet begrenzte Queues, zählt opake Bytes getrennt in beide Richtungen, trennt Setup-/Aktivzeit, kann reproduzierbare Userspace-Stream-Latenz/Jitter hinzufügen und kontrollierte Disconnects erzwingen.

Das Relay parst keine RPC-Frames: Byte-Summen enthalten Framing/Control/Daten und sind **keine** Activation-Tensor-Bytezahlen. Paketverlust wird bewusst nicht durch das Löschen von TCP-Bytes simuliert. Paket-Level-Loss/Reordering bleibt ein separates OS-/Netzwerkemulations-Experiment. Details: [runtime/network/README.md](runtime/network/README.md).

## Verifizierte echte Zielsysteme

Historische physische Evidenz vom 21.08.2026:

- Windows-Ziel: RTX 3080 Laptop GPU, 16 GiB VRAM, 31,7 GiB RAM;
- Linux-Ziel: Debian-13-Server, 4 logische CPU-Kerne, 7,8 GiB RAM, CPU-only;
- Windows → Internet-Linux Engineering-TCP: RTT p50 `11,884 ms`, p95 `13,369 ms`, Upload p50 `42,276 Mbit/s`, Download p50 `226,597 Mbit/s`;
- Windows-CUDA-llama.cpp 7B-Q4: Prefill `2866,127 tok/s`, Decode `76,210 tok/s`;
- Linux-CPU-llama.cpp 0.5B-Q4-Smoke: Prefill `12,382 tok/s`, Decode `0,201 tok/s`.

Diese beiden historischen llama.cpp-Benchmark-Läufe verwendeten unterschiedliche GGUFs und können deshalb nicht zum aktuellen Evidenzbundle kombiniert werden. Das Internet-Netzwerkergebnis ist kein vertrauenswürdiger Private-LAN-A/B-Nachweis. Spätere Engineering-Arbeit hat separat einen engen physischen Zwei-Maschinen-Shared-Runtime-Proof in `state.md` dokumentiert; keine dieser Evidenzgruppen ist eine pauschale Produktionsaussage für andere Hardware/Modelle/Topologien.

## Identity- und Runtime-Sicherheitsgrenze

ADR 0005 bleibt die enge M1-Referenzentscheidung zur Identity. Der Live-Provider-Control-Pfad authentifiziert inzwischen enrollte Ed25519-Node-Identitäten und sammelt authentifizierte Execution Attestations; die Produktionshärtung ist trotzdem noch nicht abgeschlossen.

Vor untrusted öffentlichem Provider-Betrieb fehlen unter anderem OS-geschützte private Node-Key-Speicherung, Revocation-Fan-out an aktive Sessions, vollständige Service-Authorization/Rate-/Resource-Limits, gehärteter produktiver Datenbank-/HA-Betrieb und ein produktionssicherer authentifizierter/verschlüsselter Data Plane.

Die Lab-ID `unauthenticated_server_report_v1` des TCP-Benchmarks ist **nicht** der Identity-Nachweis aus ADR 0005. Der Benchmark besitzt weiterhin keine Anwendungs-Authentifizierung/-Verschlüsselung und bleibt ausschließlich für ein vertrauenswürdiges privates LAN bestimmt.

Upstream-llama.cpp-RPC bleibt **nur für vertrauenswürdige Netze**. ComputeMesh-Provider-/Session-Authentifizierung macht den Upstream-RPC-Socket nicht sicher für öffentliche Exposition. Entwicklungs-/Operator-Werkzeuge können diesen Socket hinter Loopback, privaten Netzen oder SSH-Tunneln einschließen; RPC selbst ist aber nicht die ComputeMesh-Produktions-Sicherheitsgrenze. Niemals den RPC-Worker direkt öffentlich oder in einem nicht vertrauenswürdigen Netz exponieren.

`confidential_compute` ist keine zulässige Garantie, solange kein konkretes Trusted-Execution-/Attestation-Design existiert.

## Verbleibende Product-Readiness-Arbeit

Die produktive **Policy-Grenze** existiert inzwischen privat, aber breite produktive Distributed Inference ist noch nicht validiert. Verbleibende Gates sind insbesondere:

- den vollständigen aktuellen Gateway → Private Placement → Real Provider Execution → Evidence/Attestation → Private Feedback-Pfad wiederholt auf repräsentativen physischen GPU-Paaren ausführen;
- kontrollierte LAN-Delay-/Jitter-/Bandwidth-/Disconnect-Messungen und echte Zwei-Standort-WAN-Validierung;
- den privaten Production Predictor/Optimizer aus verifizierten Messungen statt Annahmen kalibrieren;
- Resource-Reservations/Leases tatsächlich am Provider erzwingen, nicht nur im Control-Plane-State;
- den experimentellen Upstream-RPC-Pfad durch einen produktionssicheren authentifizierten/verschlüsselten Data Plane ersetzen bzw. sicher einkapseln;
- produktive Node-Key-Speicherung, Revocation-/Session-Fan-out und Service-Authorization-/Resource-Controls;
- breitere adversariale/System-/Fuzz-/Failure-Tests;
- vollständigen Produktions-Artefakt-Lifecycle einschließlich stärkerer Multi-Shard-Identity-/Order-Semantik;
- echtes Upstream-Token-Streaming/TTFT-Messung, wo erforderlich;
- abschließende HA-/Operations-Härtung für Billing, Verification, Telemetry und private Control-Plane-Persistenz.

Payment-Grenze: Der vorgesehene Real-Money-Pfad für den Kauf von Rechenguthaben ist Stripe. Der Gateway besitzt einen fail-closed Stripe-Checkout-/Webhook-Pfad, der bei Konfiguration von `STRIPE_API_KEY` und einem dauerhaften `COMPUTEMESH_STRIPE_SESSION_STORE` das offizielle Stripe-SDK nutzt; signiertes Webhook-Crediting benötigt zusätzlich `STRIPE_WEBHOOK_SECRET`. Checkout-Metadaten und Session-Store bestimmen den gekauften Compute-Credit-Betrag, damit steuerbehaftete Stripe-Gesamtsummen nicht als zusätzliches Rechenguthaben verbucht werden. Provider-Auszahlungen besitzen einen Stripe-Connect-Accounts-v2-/Express-Recipient-Onboarding-Pfad mit dauerhaften Provider-Konten, Onboarding-Links, Settlement-Records, Transfer-Idempotenz, konfigurierbarer Transfer-Währung über `COMPUTEMESH_STRIPE_SETTLEMENT_CURRENCY` und interner Ledger-Ausbuchung der Provider-Verbindlichkeiten. Ohne Stripe-Konfiguration werden keine Fake-Live-Checkout- oder Connect-URLs ausgegeben. Echtes Stripe-Connect-Onboarding benötigt weiterhin die Rechtsform- und KYC-Daten des Providers/Betreibers. MetaMask/EVM-Wallets dienen in der aktuellen Provider-Oberfläche nur dazu, eine Auszahlungsadresse für Einnahmen aus bereitgestellter Rechenleistung festzulegen; Wallets werden nicht zum Kauf von Rechenguthaben oder zum Belasten von Kunden verwendet.

## Unmittelbarer Ablauf

```text
aktueller privater Umbrella-Checkout + gepinnte öffentliche Runtime
        ↓
echte enrollte Coordinator-/Worker-Provider + ein passender llama.cpp-Build/ein Modell
        ↓
vollständige authentifizierte Gateway-/Private-Placement-/Shared-Runtime-Anfrage
        ↓
Signaturprüfung des Placements + echte Execution Evidence + Provider Attestations
        ↓
dauerhaftes Verified Outcome → neue private Performance Observation
        ↓
wiederholbare kontrollierte LAN-Delay-/Jitter-/Bandwidth-/Disconnect-Matrix
        ↓
echte WAN-/Zwei-Standort-Validierung
        ↓
private Prediction/Ranking aus gemessener Evidenz kalibrieren
        ↓
providerseitig erzwungene Leases + Produktions-Data-Plane-/Key-/Session-Härtung
        ↓
Production Scheduling erst nach bestandenen Gates breiter freigeben
```

## Repository-Struktur

```text
ComputeMesh/
├─ SETUP.cmd / setup.sh   # öffentliche Windows-/Linux-Lab-Einstiege
├─ setup/                 # Lab-Orchestrierung + begrenzter Evidenztransfer
├─ apps/node/             # ausführbarer öffentlicher Provider-Agent + Node-Oberfläche
├─ tools/benchmark/       # Inventory, TCP, llama-bench- und GGUF-Manifest-Werkzeuge
├─ services/gateway/      # authentifizierte Public API / Live Gateway
├─ services/orchestrator/ # dauerhafter State + Live Execution/Recovery/Feedback
├─ services/identity/     # Referenz-Enrollment/Key-Registry + Live-Identity-Backing
├─ services/scheduler/    # öffentliche M1-Evidenz-/Reference-Machbarkeitsplanung
├─ protocol/              # Verträge, Session-Wire-Bindung, Ed25519-Verifier
├─ runtime/llama/         # kontrollierter llama.cpp-Shared-Runtime-Research-Pfad
├─ runtime/network/       # begrenzte Network-Measurement-/Fault-Instrumentierung
├─ portal/                # öffentliches Webportal, Sitemap und Robots-Regeln
├─ docs/                  # aktueller Status, Spezifikationen, Audits und ADRs
└─ state.md               # öffentliche historische Engineering-/Evidenzübergabe
```

Für den aktuellen öffentlichen Status zuerst [docs/CURRENT_STATUS.de.md](docs/CURRENT_STATUS.de.md) lesen, danach die README der nächstliegenden Komponente. `state.md` dient der detaillierten Engineering-Chronologie/Evidenz; `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md` und die ADRs liefern Ziel-/Historienkontext.

## Sprach-Synchronisationsregel

`README.md` und `README.de.md` sind synchronisierte Projekteinstiege und müssen bei jeder öffentlich relevanten Änderung gemeinsam aktualisiert werden. Der aktuelle Status ist zusätzlich in `docs/CURRENT_STATUS.md` und `docs/CURRENT_STATUS.de.md` synchronisiert.

## Lizenz

Alle Rechte bleiben vorbehalten, bis ausdrücklich eine Lizenz ausgewählt und veröffentlicht wird. Die Repository-Sichtbarkeit gewährt keine Open-Source-Nutzungsrechte.
