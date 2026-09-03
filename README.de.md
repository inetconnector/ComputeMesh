# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

## Kurz gesagt

ComputeMesh soll viele normale Computer zu einem gemeinsamen KI-Rechner verbinden.

Die Idee ist einfach:

- Wer freie Grafikkarten-Leistung hat, kann sie bereitstellen.
- Wer KI nutzen will, bekommt passende Rechenleistung aus dem Netzwerk.
- ComputeMesh entscheidet, welcher Rechner für eine Anfrage geeignet ist.
- Jede Ausführung soll messbar, überprüfbar und fair abrechenbar sein.

Man kann es sich wie ein Stromnetz für KI-Rechenleistung vorstellen: Nicht ein einzelnes riesiges Rechenzentrum macht alles, sondern viele passende Rechner arbeiten zusammen.

## Warum das spannend ist

KI braucht sehr viel Rechenleistung. Gleichzeitig stehen überall Grafikkarten ungenutzt herum: in Gaming-PCs, Workstations, kleinen Servern und Büros. ComputeMesh baut die Technik, um diese Leistung später sicher und nachvollziehbar nutzbar zu machen.

Das Ziel: KI-Rechenleistung soll nicht nur wenigen großen Anbietern gehören. Mehr Menschen und Firmen sollen Rechenleistung anbieten, nutzen und dafür bezahlt werden können.

## Was schon funktioniert

ComputeMesh ist heute ein Labor- und Vorproduktionssystem. Es gibt bereits:

- eine öffentliche Webseite, die in Deutschland standardmäßig Deutsch zeigt;
- Live-Zähler für öffentliche Kapazität, die nur frische authentifizierte Node-Heartbeats zählen;
- signierte Windows- und Linux-Clients mit Update-Prüfung;
- ein Gateway, über das KI-Anfragen angenommen werden können;
- eine Provider-App, mit der ein Rechner seine verfügbare Leistung melden kann;
- erste echte Zwei-Rechner-Experimente mit llama.cpp;
- Messungen für Rechnerleistung, Netzwerkverbindung und Ausführung;
- Sicherheitsregeln, damit geschützte Jobs nicht einfach auf unsichere Rechner fallen;
- klare Grenzen dafür, was noch Forschung ist und was noch nicht als Produkt versprochen wird.

Aktueller signierter Client-/Update-Kanal: `v1.2.35` ist live unter `https://computemesh.inetconnector.com/updates/version.json`.

## Was noch nicht versprochen wird

ComputeMesh ist noch kein fertiges Produkt für beliebige öffentliche KI-Aufträge. Dafür fehlen noch mehr echte Tests mit verschiedenen Grafikkarten, Netzwerken und Standorten.

Auch vertrauliche KI-Ausführung wird noch nicht als fertige Hardware-Sicherheitsgarantie behauptet. Dafür braucht es eine konkrete TEE-/GPU-Attestation-Technologie mit echtem Prüfer. Bis dahin wird `CONFIDENTIAL` bewusst blockiert, statt unsicher freigegeben zu werden.

## Schnell ausprobieren

Repository klonen/herunterladen und den Starter für das Betriebssystem verwenden:

**Windows:** `SETUP.cmd` doppelklicken  
**Linux:** `./setup.sh` ausführen (oder `bash setup.sh`, falls das Ausführungsbit verloren ging).

Das Menü kann den Rechner prüfen, die Netzwerkverbindung messen, lokale Modellgeschwindigkeit testen und die Tests starten. Modellgewichte werden niemals automatisch heruntergeladen.

Die genaue Zwei-Rechner-Anleitung für Entwickler steht in [setup/README.de.md](setup/README.de.md). Der aktuelle öffentliche Status steht in [docs/CURRENT_STATUS.de.md](docs/CURRENT_STATUS.de.md). `state.md` ist das ausführliche technische Projektlog.

## Technischer Überblick

Für Entwickler heißt das konkret:

- Rechner können ihre Hardware und Modellgeschwindigkeit messen.
- Zwei Rechner können in einem kontrollierten Labortest gemeinsam an einer Modell-Ausführung arbeiten.
- Der Gateway kann Anfragen annehmen und an passende Provider weitergeben.
- Provider müssen sich anmelden und ihre Identität nachweisen.
- Ergebnisse, Messwerte und Ausführungsnachweise werden nachvollziehbar gespeichert.
- Der Scheduler darf geschützte Jobs nicht heimlich auf eine unsichere Stufe herabsetzen.
- Öffentliche Jobs können später weltweit passende GPU-Leistung nutzen, wenn die Regeln erfüllt sind.
- Vertrauliche Jobs bleiben blockiert, bis echte Hardware-Attestation eingebaut ist.
- Die Webseite, Downloads und Update-Dateien sind versioniert und signiert.

Ab hier wird es technischer. Die folgenden Abschnitte erklären die Grenzen, Sicherheitsregeln und Experimentpfade für Entwickler und Betreiber.

### Öffentliche/private Produktionsgrenze

`services/scheduler/placement.py` bleibt der offengelegte deterministische **Research-/Reference**-Machbarkeitsplaner, der unten beschrieben wird. Er ist nicht die produktive Ranking-Engine.

Produktive Placement-Machbarkeit/-Bewertung/-Auswahl, empirischer Performance-Zustand, Reputation/Fraud-Eligibility, private Recovery-Auswahl, Pricing/Marketplace-Policy und Settlement-Policy liegen im separaten privaten Repository `inetconnector/ComputeMesh-ControlPlane`. Der öffentliche Orchestrator übermittelt einen begrenzten Live-Candidate-/Network-Snapshot, akzeptiert nur einen signierten und nicht abgelaufenen Execution Plan, prüft diesen fail-closed und führt nur das minimale Placement-Ergebnis aus, ohne private Candidate-Scores oder Policy-Interna zu erhalten.

Verifizierte öffentliche Execution-Outcomes können dauerhaft an den privaten Feedback-Pfad geliefert werden. Dort entwickeln sich private Performance-/Reliability-Eingaben weiter, ohne in öffentlichen Placement-Antworten serialisiert zu werden.

### Globale Mesh-Trust-/Privacy-Policy

PR #55 (`feat(mesh): integrate confidential global mesh policy`, gemergt als `e410b1d2adb417cf0e79689279b22899258ba13c`) ergänzt die öffentliche Policy-Schicht für globales Routing, ohne den bestehenden konservativen Production-Gate zu schwächen.

- Provider-Trust wird als `OPEN`, `VERIFIED` und `RESTRICTED` modelliert.
- Execution-Privacy wird davon getrennt als `PUBLIC`, `CONFIDENTIAL` und `CRYPTO_PRIVATE` modelliert.
- `PUBLIC`-Jobs können einen globalen heterogenen GPU-Pool nutzen, wenn technische Zulassung, Modell-/Runtime-/Hardware-Fit, Netzwerkbedingungen und Job-Policy zusammenpassen.
- Region/EWR sowie Kunden-/Vertragsrestriktionen bleiben eigenständige Policy-Prädikate.
- Der Scheduler darf Privacy nie stillschweigend downgraden: Protected Jobs fallen nie auf `PUBLIC` zurück, laufen nie auf `OPEN` und nie auf Nodes mit Plaintext-Logging.
- `CONFIDENTIAL` und `CRYPTO_PRIVATE` sind standardmäßig aus. Confidential Execution verlangt einen konkreten technologie-spezifischen Attestation-Verifier; TLS, Container, VMs und Sharding werden ausdrücklich nicht als Confidential Computing akzeptiert.
- Confidential Attestation ist an Node-Identität, Nonce, Runtime-Messung/-Digest und attestierten ephemeren Public Key gebunden. Content Keys dürfen nicht in gewöhnlichen Gateway-/Control-Plane-Code gelangen; jedes Key-Release-Ziel muss zum attestierten Node, Nonce und ephemeren Key-Austausch passen.

Das Repository enthält damit Policy-Verträge, Schemas, Filter und fail-closed Tests, behauptet aber weiterhin **keine** real produktionsfähige Confidential-Inference-Hardware. Dafür muss erst eine konkrete TEE-/GPU-Attestation-Technologie samt Verifier implementiert und aktiviert werden.

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

`confidential_compute` ist keine zulässige Produktgarantie, solange keine konkrete Trusted-Execution-/GPU-Attestation-Technologie samt Verifier existiert. Die aktuelle `CONFIDENTIAL`-Policy-Klasse schlägt standardmäßig bewusst fail-closed fehl.

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
