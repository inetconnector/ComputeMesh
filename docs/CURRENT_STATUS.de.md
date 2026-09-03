# ComputeMesh – aktueller öffentlicher Status

**Stand:** 3. September 2026

Dieses Dokument ist die öffentliche Statuszusammenfassung. Es ist bewusst getrennt von `ComputeMesh-ControlPlane/STATE.md`, das proprietäre Placement-, Ranking- und Betriebsdetails enthält.

## Statusdisziplin

Jede Aussage unten unterscheidet zwischen:

- **gemergtem** Verhalten auf öffentlichem `main`;
- **branch-lokalem Draft** in einem offenen PR;
- **Software-/CI-Validierung**;
- **physischer/adversarialer Validierung**;
- **Produktionsgarantien**.

Eine branch-lokale Implementierung oder grüne CI ist keine Produktionsaussage über Vertraulichkeit.

## Was heute tatsächlich existiert

ComputeMesh ist ein aktives Pre-Production-System für verteilte Inferenz mit realen Implementierungen für:

- authentifizierte Provider-Control-Sitzungen und Ed25519-Node-Identity-/Enrollment-Referenzzustand;
- einen ausführbaren öffentlichen Provider-Agenten, der sich authentifiziert, gemessene Profil-/Runtime-/Benchmark-Evidence veröffentlicht, Reconnect unterstützt und authentifizierte Control-Anfragen beantwortet;
- OpenAI-/Ollama-kompatible Gateway-Oberflächen, Model-Catalog-Verarbeitung, Billing-Grundlagen und persistente Orchestrator-Zustände;
- private Produktions-Placement-/Recovery-Integration über begrenzte signierte Schnittstellen, während proprietäres Ranking, Reputation/Fraud und Pricing privat bleiben;
- einen realen llama.cpp-Shared-Runtime-Forschungspfad mit dokumentierter physischer Zwei-Maschinen-Evidence für eine enge getestete Topologie;
- globale Mesh-Trust-/Privacy-Policy mit `OPEN` / `VERIFIED` / `RESTRICTED` Provider-Trust-Tiers und `PUBLIC` / `CONFIDENTIAL` / `CRYPTO_PRIVATE` Execution-Privacy-Klassen;
- signierte/replay-sichere Protokoll-, Identity-, Accounting- und Updater-Grundlagen.

## P0-Stand Confidential Execution

### Gemergte öffentliche Grundlagen

Folgende P0-Grundlagen sind auf öffentlichem `main` gemergt:

- PR #72 — zentrale fail-closed Protected-Execution-Grundlage;
- PR #73 — attestation-gebundene X25519/HKDF/AES-256-GCM Confidential-Payload-Envelope-Grundlage;
- PR #74 — hash-gepinnte NVIDIA-Confidential-Attestation-Verifier-Prozessgrenze;
- Secure-Memory-Primitiven mit expliziter Zeroization und optional verpflichtendem Page Locking;
- POSIX-Dumpability-/Core-Dump-Härtung;
- request-spezifische Attestation- und Key-Release-Verträge.

### Offener Draft-PR #76 — `security/p0-confidential-metering`

PR #76 ist **offen und Draft**. Er darf nicht als gemergt oder produktionsreif beschrieben werden.

Der Branch enthält inzwischen deutlich mehr als den früheren Session-/Metering-Prototyp, darunter:

- persistente Confidential-Session-Zustände mit `OPEN -> DISPATCHED -> METERED -> COMPLETED` plus Fehlerzustand;
- inhaltsfreie Ed25519-Usage-Receipts, gebunden an Account/Job/Request/Response/Node/Runtime/Privacy/Operation/Model/Tokenzahlen;
- persistentes Double-Entry-Confidential-Escrow mit Restart-/Idempotency-Recovery;
- authentifizierte Confidential-Envelope-Bindung einschließlich Modell sowie Prompt-/Completion-Tokenbudgets;
- einen loopback-only OpenAI-kompatiblen lokalen Protected Proxy, sodass Plaintext vor Remote-Egress verschlüsselt werden kann;
- bidirektional verschlüsselte Protected Responses und authentifiziertes Protected Streaming, das lokal wieder in normales OpenAI-SSE umgesetzt wird;
- persistente Request-Replay-Tombstones und TLS-gepinnte Protected-Data-Plane-Clients;
- einen reinen Protected-Transport-Gateway-Mixin und eine kanonische Unified-Live-Handler-Komposition statt eines konkurrierenden zweiten öffentlichen Servers;
- einen Remote-Confidential-Session-Broker-Client, der nur inhaltsfreie Admission-Metadaten an den privaten Control Plane sendet und nur ein reduziertes Provision-Ergebnis akzeptiert;
- einen Provider-Control-Handler für Confidential Provisioning über eine bereits authentifizierte Provider-`NodeSession`, der veraltete Session-Revisionen, falsche Node-Identität, fehlende Capability-Negotiation und nicht verfügbare Modelle ablehnt;
- einen dedizierten Protected Worker mit request-spezifischem X25519-Recipient-Material, Ed25519-Metering-Identität, Replay-Prüfung, exakter Session-/Envelope-Bindung, Protected-Memory-Kontrollen, verschlüsselter Response-Verarbeitung und inhaltsfreiem Metering;
- eine dedizierte HTTPS-Worker-Grenze statt raw public llama.cpp RPC als Protected-Sicherheitsgrenze zu behandeln.

Das sind **branch-lokale Software-Grundlagen**. Sie beweisen noch nicht, dass ein Provider-Administrator auf realer Hardware keinen Plaintext inspizieren kann.

## OpenAI-Kompatibilitätsgrenze

Der beabsichtigte Nutzervertrag bleibt die Standard-OpenAI-artige Oberfläche:

- `POST /v1/chat/completions`;
- `GET /v1/models`;
- Standard-Completion-Objekte für non-stream;
- Standard-SSE-Completion-Chunks für `stream=true`.

Für `CONFIDENTIAL` / künftig `CRYPTO_PRIVATE` ist der vertrauenswürdige lokale ComputeMesh-Transport/Proxy Teil der Client-Grenze. Er nimmt lokal den normalen OpenAI-förmigen Request an, prüft Protected Provision/Attestation-Policy, verschlüsselt den Original-Request vor Remote-Egress und entschlüsselt/validiert die Protected Response wieder lokal.

Die internen `/internal/v1/confidential/...`-Routen sind Transport-Interna und keine zweite öffentliche API. Alte öffentliche `/v1/confidential/...`-Aliase sind nicht die beabsichtigte Produktoberfläche.

## Öffentliche/private Produktionsgrenze

Produktions-Ranking und -Policy gehören **nicht** in den öffentlichen Reference Scheduler.

Das private Repository `inetconnector/ComputeMesh-ControlPlane` besitzt proprietäres Produktions-Placement/-Ranking, empirischen Performance-Zustand, Reputation/Fraud-Policy, Marketplace/Pricing-Policy und private Recovery-/Settlement-Policy. Das öffentliche Repository besitzt die portablen Protocol-/Runtime-/Gateway-/Client-/Provider-Mechanismen, die für die Ausführung eines reduzierten genehmigten Ergebnisses nötig sind.

Für Confidential Admission enthält der öffentliche Branch jetzt den Remote-Broker-Vertrag und den authentifizierten Provider-Control-Provisioning-Handler. Die verbleibende Produktionsaufgabe ist, den privaten Confidential-Provision-Service über den bestehenden authentifizierten Provider-Control-Channel mit dem ausgewählten Protected Worker zu verbinden, ohne Losing Candidates, Scores, Fraud-/Reputation-Features oder Pricing-Koeffizienten offenzulegen.

## Was validiert ist – und was noch nicht

### In Software/Tests auf den Entwicklungsbranches validiert

- Protected Request-/Response-Envelope-Binding und Replay-Verhalten;
- lokales Protected-OpenAI-Proxy-Verhalten;
- Sequencing/Finalisierung des verschlüsselten Streamings;
- Confidential-Session-State und Metering-Receipts;
- Double-Entry-Confidential-Escrow und idempotente Recovery;
- Unified-Protected-Gateway-Komposition;
- Parsing/Validierung des reduzierten Remote-Confidential-Brokers;
- fail-closed Protected-Worker- und Provider-Control-Verträge.

### Physisch validiert

- ein enger historischer Trusted-Lab-Zwei-Maschinen-Shared-llama.cpp-Proof für genau die dokumentierte Hardware-/Modell-/Runtime-/Topologie-Kombination.

### Noch keine Produktionsgarantie für Vertraulichkeit

- reale unterstützte NVIDIA-Confidential-Compute-Hardware mit finalem Vendor-SDK-/Helper-Pfad;
- physische Validierung von Nonce, Measurement, CC-/Debug-Zustand und gebundenen Protected-Endpoint-/Key-Identitäten auf dieser Hardware;
- Hostile-Provider-/Root-/Admin-Memory-Inspection-Acceptance gegen die deklarierte TEE-Grenze;
- vollständiger Produktions-Bootstrap und privates Confidential-Provisioning über reale ausgewählte Provider;
- vollständige MITM-/Replay-/Substitution-/Core-Dump-/Swap-/Pagefile-Akzeptanztests;
- AMD Confidential Execution für eine konkrete Topologie;
- eine validierte `CRYPTO_PRIVATE`-Kryptokonstruktion;
- breite heterogene Multi-Node-Produktion und HA-/Operations-Reife.

## Wichtige Sicherheitsgrenzen

- `PUBLIC` Compute kann Workload-Plaintext gegenüber der Provider-Runtime exponieren und ist keine Confidential Execution.
- TLS, SSH, Container, VMs, gewöhnliches Sharding und Page Locking liefern für sich allein keine Confidential Execution.
- raw/upstream llama.cpp RPC bleibt eine experimentelle Trusted-Network-Entwicklungskomponente und ist nicht die Protected Public Security Boundary.
- `CONFIDENTIAL` muss fail-closed fehlschlagen, wenn die vollständige erforderliche Kette nicht verfügbar ist.
- `CRYPTO_PRIVATE` muss deaktiviert bleiben, bis seine Kryptokonstruktion unabhängig validiert wurde.
- CI-Erfolg darf nie als physische TEE-Akzeptanz dargestellt werden.

## Primäre Engineering-Dokumente

- `docs/CURRENT_STATUS.md` / `docs/CURRENT_STATUS.de.md` — aktueller öffentlicher Status;
- `docs/P0_CONFIDENTIAL_EXECUTION_PLAN.md` — aktuelle P0-Architektur, abgeschlossene Grundlagen und verbleibende Release-Gates;
- `THREAT_MODEL.md` und `SECURITY.md` — Sicherheitsgrenzen und Release-Blocker;
- `docs/PRIVACY_TIERS.md` — erzwungene Execution-Privacy-Semantik;
- `CONTRIBUTING.md` — Definition of Done einschließlich Documentation-Freshness-Invariant;
- `state.md` — detaillierter historischer öffentlicher Engineering-Log;
- `services/gateway/protected_transport_mixin.py` / `unified_live_handler.py` — branch-lokale Protected-Gateway-Komposition;
- `services/orchestrator/remote_confidential_broker.py` — öffentlicher reduzierter Private-Control-Plane-Client;
- `runtime/confidential/provider_control.py` / `protected_worker.py` / `worker_http.py` — providerseitige Protected-Admission-/Worker-Grenze.

## Unmittelbar nächster Readiness-Block

Das nächste P0-Gate ist die reale End-to-End-Confidential-Provisioning-/Deployment-Kette, nicht weiterer Protokoll-Unterbau:

1. privaten Confidential-Provision-Service fertigstellen und mit der bereits authentifizierten Provider-Control-Sitzung verbinden;
2. Live-Protected-Bootstrap/-Konfiguration vervollständigen, sodass Confidential Readiness false bleibt, solange Broker, Session-/Replay-Stores, Escrow, Verifier-Policy und Data Planes nicht vollständig installiert sind;
3. die standardisierte OpenAI-kompatible Nutzeroberfläche beibehalten, während Protected Transport intern bleibt;
4. den realen vendor-unterstützten NVIDIA-Attestation-Helper bauen, hash-pinnen und auf unterstützter Confidential-Compute-Hardware validieren;
5. physische/adversariale Akzeptanz vor jeder Produktionsaussage über Vertraulichkeit durchführen;
6. alle autoritativen Dokumente mit jedem materiellen Meilenstein synchron halten.
