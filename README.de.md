# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Phase:** M0 — Engineering-/Lab-Implementierung.  
> **Wichtig:** ComputeMesh ist **noch kein produktionsreifes verteiltes Inferenzprodukt**. Das Windows-/Linux-Setup unten richtet den Lab-/Benchmark-Ablauf ein, der heute tatsächlich existiert; es ist kein öffentlicher Provider-Node-Installer.

ComputeMesh untersucht, ob heterogene Rechner als gemeinsames modellbewusstes KI-Inferenz-Fabric arbeiten können. Langfristig soll der Nutzer nur Modell und Richtlinie wählen; ComputeMesh übernimmt Machbarkeit, Platzierung, Vorbereitung, Ausführung, Fehlerbehandlung, Verifikation und nachvollziehbare Abrechnung.

## Der einfachste Einstieg

Repository klonen oder herunterladen und dann den Starter für das Betriebssystem verwenden:

**Windows**

```text
SETUP.cmd doppelklicken
```

**Linux**

```bash
./setup.sh
```

Falls beim Herunterladen/Entpacken das Ausführungsbit verloren gegangen ist:

```bash
bash setup.sh
```

Beide Starter öffnen dasselbe einfache Menü. Du musst **keine** darunterliegenden Python-Benchmarkbefehle eintippen, `.venv` selbst anlegen, Profilrevisionen merken oder Ergebnisordner zusammenbauen.

| Auswahl | Funktion |
| --- | --- |
| 1 | Diesen Rechner vorbereiten und CPU/RAM/GPU-Profil erfassen |
| 2 | Auf diesem Rechner auf einen vertrauenswürdigen LAN-Test warten (Node B) |
| 3 | RTT und Durchsatz zum anderen Rechner messen (Node A) |
| 4 | Lokale llama.cpp-Prefill-/Decode-Leistung messen |
| 5 | Lokale Testabhängigkeiten installieren und alle aktuellen Tests ausführen |

Die genaue Zwei-Rechner-Anleitung steht in [setup/README.de.md](setup/README.de.md).

## Was das Setup automatisch erledigt

Unter Windows und Linux gleichermaßen:

- Deutsch/Englisch aus der Systemsprache bzw. Locale auswählen;
- Python 3.10+ finden und eine lokale `.venv` im Repository anlegen;
- eine stabile zufällige Lab-Node-ID statt des Hostnamens erzeugen;
- die Profilrevision nur nach erfolgreicher Rechnererfassung erhöhen;
- lokale Konfiguration, Downloads und Ergebnisse unter den von Git ignorierten `artifacts/lab/`-Pfaden speichern;
- CPU/GPU/RAM, RTT/Durchsatz und llama.cpp-Werte direkt zusammenfassen;
- den assistierten Netzwerkserver an eine konkrete private RFC1918-Adresse statt an `0.0.0.0` binden;
- eine temporär angelegte Firewallregel nach dem einmaligen Netzwerktest wieder entfernen;
- Modellgewichte niemals automatisch herunterladen.

Plattformspezifische Vereinfachung:

- **Windows:** fehlendes Python kann benutzerbezogen über `winget` installiert werden; der Netzwerkhelfer verwendet eine temporäre Windows-`Private`-/`LocalSubnet`-Firewallregel.
- **Linux:** fehlende Basispakete können nach Rückfrage über `apt`, `dnf`, `zypper`, `pacman` oder `apk` installiert werden; aktive `firewalld`- oder `ufw`-Firewalls werden mit einer temporären, auf das erkannte private Subnetz begrenzten Regel behandelt.

## llama.cpp-Setup

Das Setup kann ein vorhandenes `llama-bench` verwenden oder einen offiziellen Upstream-Build laden.

- Windows verwendet den passenden offiziellen Windows-Pfad des bestehenden Setups.
- Linux wählt dynamisch einen offiziellen Ubuntu-CPU-, Vulkan- oder ROCm-Build für unterstützte x64-/arm64-Fälle und prüft einen von GitHub gelieferten SHA-256-Digest, sofern vorhanden.
- Unter Linux wird die heruntergeladene Binary über einen lokalen Library-Wrapper gestartet und nur akzeptiert, wenn `llama-bench --version` auf genau diesem Rechner funktioniert.
- Auf Linux-Desktops wird `zenity` als GGUF-Dateiauswahl verwendet, wenn vorhanden; sonst wird der Pfad im Terminal mit Shell-Vervollständigung abgefragt.

Die offiziellen Linux-Releases enthalten derzeit unter anderem Ubuntu-Builds für CPU, Vulkan, ROCm, OpenVINO und SYCL. Das automatische M0-Setup beschränkt sich bewusst auf CPU/Vulkan/ROCm.

## Aktuell implementiert

Zu den M0-Grundlagen gehören inzwischen:

- plattformübergreifendes Windows-/Linux-Lab-Setup;
- Inventory-, TCP-Netzwerk- und llama.cpp-`llama-bench`-Messwerkzeuge;
- maschinenlesbare Draft-2020-12-Verträge für zentrale State-/Control-Daten und erste Nachrichten-Payloads;
- deterministische Job-/Reservation-State-Semantik;
- transaktionale SQLite-Referenzpersistenz mit dauerhafter Idempotenz, Revisionen, Leases, Restart-Recovery, Request-Fingerprints und Schema-Migration;
- atomare `CommitReservation`-Bindung an Job + Stage;
- transportneutrale Control-Envelope-Prüfung und strukturierte Fehler;
- dauerhafte erste Handler für `ReserveCapacity`, `CommitReservation` und `CancelJob`;
- authentifizierungspflichtige Node-Session-Semantik für `Hello -> Authenticate -> CapabilityNegotiation -> ProfileSync -> BenchmarkStatus -> READY -> DRAINING/CLOSED`;
- eine zwingende `AuthenticationVerifier`-Grenze ohne permissiven Default.

## Noch nicht implementiert

Es gibt weiterhin keinen produktiven Provider-Node/Installer, keine verteilte gemeinsame Inferenz-Runtime, kein Gateway/API, keinen Scheduler, kein produktives Credential-System, kein vollständiges Wire-Protokoll, keinen fertigen Billing-/Verification-/Telemetry-Produktstack und keinen signierten Release-/Update-Pfad.

ADR 0005 (Node Identity) und ADR 0002 (M1 Runtime Baseline) bleiben **Proposed**, nicht Accepted.

## M0-Ablauf mit zwei Rechnern

```text
SETUP.cmd (Windows) oder ./setup.sh (Linux) auf beiden Rechnern
        ↓
beide Rechner profilieren
        ↓
LAN A → B und B → A messen
        ↓
llama.cpp Prefill/Decode auf jedem relevanten Rechner messen
        ↓
konkreten M1-Zwei-Node-Spike auswählen
        ↓
Activation-Transport messen
        ↓
erste korrekte gemeinsame Zwei-Node-Inferenz
        ↓
Scheduler kalibrieren
```

Die beiden Rechner dürfen Windows, Linux oder gemischt Windows/Linux sein; Benchmarkformat und Python-Helfer sind gemeinsam.

## Sicherheitsgrenze

Das TCP-Benchmark-Protokoll besitzt keine Anwendungs-Authentifizierung oder Verschlüsselung. Den assistierten Server nur in einem vertrauenswürdigen privaten LAN verwenden. Keiner der Starter macht die experimentelle Runtime für eine öffentliche Internet-Exposition sicher.

Der vorhandene `AuthenticationVerifier` ist eine semantische Schnittstelle und noch kein produktives Credential-System. `confidential_compute` ist keine zulässige Garantie, solange kein konkretes Trusted-Execution-/Attestation-Design existiert.

## Repository-Struktur

```text
ComputeMesh/
├─ SETUP.cmd              # Windows-M0-Einstieg
├─ setup.sh               # Linux-M0-Einstieg
├─ setup/                 # gemeinsamer Helper + Windows-/Linux-Starter
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
