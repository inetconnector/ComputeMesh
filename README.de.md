# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Phase:** M0 — Engineering-/Lab-Implementierung.  
> **Wichtig:** ComputeMesh ist **noch kein produktionsreifes verteiltes Inferenzprodukt**. Das Windows-Setup unten richtet den heute tatsächlich implementierten Lab-/Benchmark-Ablauf ein; es ist kein öffentlicher Provider-Node-Installer.

ComputeMesh untersucht, ob heterogene Rechner als gemeinsames modellbewusstes KI-Inferenz-Fabric arbeiten können. Langfristig soll der Nutzer nur Modell und Richtlinie wählen; ComputeMesh übernimmt Machbarkeit, Platzierung, Vorbereitung, Ausführung, Fehlerbehandlung, Verifikation und nachvollziehbare Abrechnung.

## Der einfachste Einstieg unter Windows

1. Dieses Repository klonen oder herunterladen.
2. Den ComputeMesh-Ordner öffnen.
3. **`SETUP.cmd` doppelklicken.**
4. Im Menü auswählen, was gemacht werden soll.

Das ist der normale M0-Einstieg. Du musst **keine** Python-Befehle eintippen, keine virtuelle Umgebung selbst anlegen, keine Profilrevision merken und keine Benchmark-Kommandozeilen zusammenbauen.

Das Menü bietet:

| Auswahl | Funktion |
| --- | --- |
| 1 | Diesen Rechner vorbereiten und CPU/RAM/GPU-Profil erfassen |
| 2 | Auf diesem Rechner auf einen LAN-Netzwerktest warten (Server / Node B) |
| 3 | RTT und Durchsatz zum anderen Rechner messen (Client / Node A) |
| 4 | Lokale llama.cpp-Prefill-/Decode-Leistung messen |
| 5 | Lokale Testabhängigkeiten installieren und alle aktuellen Tests ausführen |

Zusätzlich gibt es direkte Starter unter `setup/`: `NODE.cmd`, `NETWORK-SERVER.cmd`, `NETWORK-CLIENT.cmd`, `LLAMA-BENCH.cmd` und `TESTS.cmd`.

Die konkrete Zwei-Rechner-Anleitung steht in [setup/README.de.md](setup/README.de.md).

## Was das Windows Lab Setup automatisch erledigt

- Deutsch/Englisch anhand der Windows-Sprache wählen;
- Python 3.10+ finden oder eine benutzerbezogene Installation über `winget` versuchen;
- eine isolierte `.venv` im Repository anlegen;
- eine stabile zufällige Lab-Node-ID erzeugen, statt den Windows-Hostnamen zu verwenden;
- die Profilrevision nur nach erfolgreicher Rechnererfassung erhöhen;
- lokale Konfiguration, Downloads und Ergebnisse unter den von Git ignorierten `artifacts/lab/`-Pfaden ablegen;
- nach Messungen direkt CPU/GPU/RAM, RTT/Durchsatz bzw. llama.cpp-Leistungswerte anzeigen;
- beim LAN-Server Port 43191 nur vorübergehend für die konkrete private IP, das Windows-Profil `Private` und `LocalSubnet` öffnen und die Regel danach wieder entfernen;
- auf Wunsch die neueste offizielle Windows-Version von llama.cpp aus `ggml-org/llama.cpp` laden und einen von GitHub gelieferten SHA-256-Digest prüfen, sofern vorhanden;
- erfolgreich verwendete Pfade zu `llama-bench.exe` und GGUF lokal für den nächsten Lauf merken.

Modelldateien werden bewusst **nicht** automatisch heruntergeladen. Du wählst eine lokale `.gguf`-Datei aus, damit Lizenz, Modellgröße und Modellauswahl ausdrücklich unter deiner Kontrolle bleiben.

## Aktuell implementiert

Zu den M0-Grundlagen gehören inzwischen:

- Inventory-, TCP-Netzwerk- und llama.cpp-`llama-bench`-Messwerkzeuge;
- maschinenlesbare Draft-2020-12-Verträge für zentrale State-/Control-Daten und erste Nachrichten-Payloads;
- deterministische Job-/Reservation-State-Semantik;
- transaktionale SQLite-Referenzpersistenz mit dauerhafter Idempotenz, Revisionen, Leases, Restart-Recovery, Request-Fingerprints und Schema-Migration;
- atomare `CommitReservation`-Bindung an Job + Stage;
- transportneutrale Control-Envelope-Prüfung und strukturierte Fehler;
- dauerhafte erste Handler für `ReserveCapacity`, `CommitReservation` und `CancelJob`;
- authentifizierungspflichtige Node-Session-Semantik für `Hello -> Authenticate -> CapabilityNegotiation -> ProfileSync -> BenchmarkStatus -> READY -> DRAINING/CLOSED`;
- eine zwingende `AuthenticationVerifier`-Grenze ohne permissiven Default;
- das oben beschriebene Windows-M0-Lab-Setup.

## Noch nicht implementiert

Es gibt weiterhin keinen produktiven:

- Provider-Node bzw. Provider-Installer;
- verteilten Runtime-Worker und noch kein korrektes gemeinsames Zwei-Node-Inferenzergebnis;
- Gateway/API oder Scheduler;
- produktiven Orchestrator-Service/Datenbankadapter;
- Enrollment-/Key-/Credential-Verifier, Issuer, Rotation oder Revocation-Backend;
- vollständigen NodeHello/Auth/Profile-Wire-Pfad;
- Registry-, Verification-, Billing/Ledger-, Telemetry-, SDK-, Dashboard- oder Desktop-Dienst;
- signierten Release-/Update-Pfad.

ADR 0005 (Node Identity) und ADR 0002 (M1 Runtime Baseline) bleiben **Proposed**, nicht Accepted.

## M0-Ablauf mit zwei Rechnern

```text
SETUP.cmd auf beiden Rechnern
        ↓
beide Rechner profilieren
        ↓
LAN A → B und B → A messen
        ↓
llama.cpp Prefill/Decode auf beiden Rechnern messen
        ↓
konkreten M1-Zwei-Node-Spike auswählen
        ↓
Activation-Transport messen
        ↓
erste korrekte gemeinsame Zwei-Node-Inferenz
        ↓
Scheduler kalibrieren
```

Das Vorhandensein des Setups ist noch kein Zwei-Node-Nachweis; die Messungen müssen auf den realen Zielrechnern durchgeführt werden.

## Sicherheitsgrenze

Der TCP-Benchmark-Server besitzt keine Anwendungs-Authentifizierung oder Verschlüsselung. Der assistierte Windows-Ablauf beschränkt ihn deshalb auf ein privates RFC1918-LAN und eine temporäre `LocalSubnet`-Firewall-Regel. Benchmark-/Runtime-Endpunkte niemals öffentlich ins Internet stellen.

Der vorhandene `AuthenticationVerifier` ist eine semantische Schnittstelle und noch kein produktives Credential-System. `confidential_compute` ist keine zulässige Garantie, solange kein konkretes Trusted-Execution-/Attestation-Design existiert.

## Repository-Struktur

```text
ComputeMesh/
├─ SETUP.cmd              # einfachster Windows-M0-Einstieg
├─ setup/                 # Windows-Lab-Ablauf + direkte Starter
├─ tools/benchmark/       # Inventory, TCP-Netzwerk, llama-bench-Adapter
├─ services/orchestrator/ # dauerhafter M0-State + erste Control-Handler
├─ protocol/              # Verträge, Envelope, Session-Semantik, Tests
├─ apps/                  # geplante Produktanwendungen
├─ runtime/               # geplante/erforschte Runtime-Integrationen
├─ docs/                  # Spezifikationen und ADRs
└─ state.md               # kanonischer Engineering-Handoff
```

Für Engineering-Details zuerst `state.md`, danach `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md` und die ADRs lesen.

## Sprach-Synchronisationsregel

`README.md` und `README.de.md` sind synchronisierte Projekteinstiege und müssen bei jeder öffentlich relevanten Änderung gemeinsam aktualisiert werden.

## Lizenz

Alle Rechte bleiben vorbehalten, bis ausdrücklich eine Lizenz ausgewählt und veröffentlicht wird. Die Repository-Sichtbarkeit gewährt keine Open-Source-Nutzungsrechte.
