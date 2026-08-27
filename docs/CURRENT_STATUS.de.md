# ComputeMesh – aktueller öffentlicher Status

**Stand:** 27. August 2026

Dieses Dokument ist die öffentliche, aktuelle Statuszusammenfassung. Es ist bewusst getrennt von `ComputeMesh-ControlPlane/STATE.md`, das private Control-Plane- und Betriebsdetails enthält.

## Was heute tatsächlich existiert

ComputeMesh ist nicht mehr nur ein M0/M1-Grundgerüst. Das öffentliche Repository enthält reale Implementierungen für:

- authentifizierte Provider-Control-Sitzungen sowie Ed25519-Node-Identity-/Enrollment-Referenzzustand;
- einen ausführbaren öffentlichen Provider-Agenten (`apps/node/provider_agent.py`), der sich authentifiziert, gemessene Profil-/Runtime-/Benchmark-Evidence meldet, Reconnect unterstützt und Execution-Attestation-Anfragen beantwortet;
- OpenAI-/Ollama-kompatible Gateway-Oberflächen, Model-Catalog-Verarbeitung, Billing-Grundlagen und persistente Orchestrator-Zustände;
- Live-Provider-Registrierung, Execution Evidence, authentifizierte Attestation-Sammlung, Cancellation- und Recovery-Mechanik;
- einen öffentlichen Reference-/Research-Scheduler und konservative M1-Zwei-Node-Evidence-/Feasibility-Werkzeuge;
- einen realen llama.cpp-Shared-Runtime-Forschungspfad mit mindestens einem physischen Trusted-Lab-Proof, deterministischem Baseline/Shared-Vergleich und gebundenen Proof-Artefakten;
- kontrollierte Delay-/Jitter-/Disconnect-Instrumentierung und einen Network-Sensitivity-Runner für reale Shared-Inference-Messpunkte;
- persistente Feedback-Hooks, die verifizierte öffentliche Execution-Outcomes an den privaten Performance-Pfad liefern;
- Windows-/Linux-Lab-Setup, Evidence-Transfer, GGUF-Manifest-Werkzeuge, Installer-/Appliance-Arbeit, Portal- und Updater-Komponenten.

## Öffentliche/private Produktionsgrenze

Die Produktions-Placement-Policy liegt **nicht** in `services/scheduler/placement.py`. Diese Datei bleibt ein öffentlicher Reference-/Research-Feasibility-Pfad.

Produktions-Scheduler, Ranking/Scoring, empirischer Performance-Zustand, Reputation/Fraud-Policy, Marketplace/Pricing, private Recovery-Auswahl und Settlement-Policy liegen im separaten privaten Repository `inetconnector/ComputeMesh-ControlPlane`. Der öffentliche Runtime-Pfad kommuniziert über begrenzte authentifizierte Schnittstellen mit diesem Control Plane und verifiziert signierte Placement-Entscheidungen vor der Ausführung.

Damit bleibt das öffentliche Repository für Provider, Runtime-/Protocol-Interoperabilität und reproduzierbare Forschung nutzbar, ohne die produktive Ranking-/Daten-/Policy-Intelligenz zu veröffentlichen.

## Aktuelle Live-Entwicklungstopologie

Der praktische Zwei-Node-Pfad verwendet derzeit:

1. einen Gateway-/Coordinator-Host mit öffentlichem Live-Gateway und lokalem Coordinator-`llama-server`;
2. einen enrollten Remote-Provider mit öffentlichem Provider-Agent und upstream llama.cpp RPC Worker;
3. private Placement-/Recovery-Auswahl;
4. Verifikation des signierten Execution Plans;
5. Execution Evidence und Provider Attestations;
6. persistente Übertragung verifizierter Outcome-Metriken in den privaten Performance Store.

Der upstream llama.cpp RPC-Socket ist weiterhin experimentell/unsicher und darf nicht als öffentliche Node-Sicherheitsgrenze behandelt werden. Der Entwicklungs-Bring-up kann RPC über SSH/private Netze führen; ein gehärteter Produktions-Data-Plane bleibt erforderlich.

## Was validiert ist – und was noch nicht

Software/CI-validiert sind u. a. Verträge, Identity/Session-/Persistenz-Grundlagen, Gateway-/Orchestrator-Mechanik, Placement-Grenzverifikation, Provider-Agent-Protokollpfad, Evidence/Attestation, Feedback-Lieferung, Research-Runtime-Harnesses und kontrollierte Netzwerk-Instrumentierung.

Physisch validiert ist mindestens ein enger Trusted-Lab-Zwei-Maschinen-Shared-llama.cpp-Proof, dokumentiert in `state.md`, für genau seine Hardware-/Modell-/Runtime-/Topologie-Kombination.

Noch keine allgemeine Produktionsaussage: breite heterogene Zwei-GPU-Validierung, kontrollierte LAN-/WAN-Matrizen über repräsentative Hardware/Modelle, Runtime-Transport über untrusted Netze, providerseitig erzwungene Leases, produktive Key-Aufbewahrung/Revocation-Fanout, kalibrierte Performance Prediction, große Multi-Node-Scheduling-Pfade und vollständige HA-/Operations-Reife.

## Primäre Engineering-Dokumente

- `docs/CURRENT_STATUS.md` / `docs/CURRENT_STATUS.de.md` — aktuelle öffentliche Statusquelle;
- `state.md` — historischer öffentlicher Engineering-Handoff/Log;
- `ARCHITECTURE.md` — öffentliche Zielarchitektur und Invarianten;
- `docs/PRIVATE_CONTROL_PLANE_SPLIT.md` / `docs/PUBLIC_PRIVATE_CLASSIFICATION.md` — Disclosure-Grenze;
- `services/orchestrator/README.md` — Live-Orchestrierung/Control;
- `services/gateway/README.md` — API/Gateway;
- `apps/node/README.md` — Provider-Agent/Node;
- `runtime/llama/README.md` — Shared llama.cpp Research-/Evidence-Pfad;
- `runtime/network/README.md` — Instrumentierung/Transport-Forschung;
- `tests/README.md` — Testabdeckung;
- `setup/README.md` / `setup/README.de.md` — öffentliches Lab-Setup.

## Unmittelbar nächster Readiness-Block

Der nächste große Gate ist reale Evidence statt eines weiteren Public/Private-Splits: kompletten aktuellen Stack auf Zielhardware ausführen, reproduzierbare LAN-/WAN-Messungen sammeln, verifizierte Outcomes in den privaten Predictor zurückführen, echte Provider-Resource-Leases erzwingen, Data Plane und Node-Key-Lifecycle härten und erst danach `production_scheduling` breiter freigeben.
