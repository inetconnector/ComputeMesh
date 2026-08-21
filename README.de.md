# ComputeMesh

**Sprachen:** [English](README.md) | **Deutsch**

> **Phase:** M0 — Engineering-/Lab-Implementierung auf dem Weg zum ersten M1-Runtime-Nachweis.  
> **Wichtig:** ComputeMesh ist **noch kein produktionsreifes verteiltes Inferenzprodukt**. Das Windows-/Linux-Setup unten richtet den heute tatsächlich vorhandenen Lab-/Benchmark-Ablauf ein; es ist kein öffentlicher Provider-Node-Installer.

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

- Windows verwendet den passenden offiziellen Windows-Build des bestehenden Setup-Pfads.
- Linux wählt dynamisch einen offiziellen Ubuntu-CPU-, Vulkan- oder ROCm-Build für unterstützte x64-/arm64-Fälle und prüft einen von GitHub gelieferten SHA-256-Digest, sofern vorhanden.
- Unter Linux wird die heruntergeladene Binary über einen lokalen Library-Wrapper gestartet und nur akzeptiert, wenn `llama-bench --help` auf genau diesem Rechner erfolgreich startet.
- Auf Linux-Desktops wird `zenity` zur GGUF-Auswahl verwendet, wenn vorhanden; sonst wird der Pfad im Terminal mit Shell-Vervollständigung abgefragt.

Modellgewichte werden niemals automatisch heruntergeladen.

## Aktuell implementiert

Zu den vorhandenen Grundlagen gehören inzwischen:

- plattformübergreifendes Windows-/Linux-Lab-Setup;
- Inventory-, TCP-Netzwerk- und llama.cpp-`llama-bench`-Messwerkzeuge;
- maschinenlesbare Draft-2020-12-Verträge für zentrale State-/Control-Daten und erste Nachrichten-Payloads;
- deterministische Job-/Reservation-State-Semantik;
- transaktionale SQLite-Referenzpersistenz mit dauerhafter Idempotenz, Revisionen, Leases, Restart-Recovery, Request-Fingerprints und Schema-Migration;
- atomare `CommitReservation`-Bindung an Job + Stage;
- transportneutrale Control-Envelope-Prüfung und strukturierte Fehler;
- dauerhafte erste Handler für `ReserveCapacity`, `CommitReservation` und `CancelJob`;
- authentifizierungspflichtige Node-Session-Semantik für `Hello -> Authenticate -> CapabilityNegotiation -> ProfileSync -> BenchmarkStatus -> READY -> DRAINING/CLOSED`;
- strikte Node-Session-Wire-Verträge und Envelope→Session-Bindung für `NodeHello`, `NodeAuthenticate`, `CapabilityNegotiation`, `NodeProfileUpdate`, `BenchmarkReport` und `DrainRequest`;
- Session-Protokollversionsaushandlung, Bindung des authentifizierten Actors, optimistische Revisionen, exakte Replay-Behandlung, Erkennung semantisch veränderter Request-ID-Wiederverwendung und eine injizierte Benchmark-Readiness-Policy;
- ein M1-Referenzpfad für Node Identity mit `computemesh-ed25519-v1`-Challenge-Signaturen hinter der zwingenden `AuthenticationVerifier`-Grenze;
- ein SQLite-Referenzregister für Identity mit kurzlebigen gehashten Enrollment-Tokens, stabilen zufälligen Node-IDs, Public-Key-Lookup, Key-Rotation und monotoner Key-/Node-Revocation.

Der Ed25519-Proof ist an Session-ID, Session-Challenge, stabile Node-ID, Key-ID, Protokollversion, Proof-Laufzeit und die akzeptierte `NodeHello`-Semantik gebunden. Die Control Plane speichert nur öffentliche Schlüssel und niemals die privaten Node-Schlüssel.

## Verifizierte echte Zielsysteme

Der Lab-Ablauf wurde auf echten Windows- und Linux-Zielen ausgeführt:

- Windows-Ziel: RTX 3080 Laptop GPU, 16 GiB VRAM, 31,7 GiB RAM.
- Linux-Ziel: Debian-13-Server, 4 logische CPU-Kerne, 7,8 GiB RAM, keine GPU erkannt.
- Windows -> Internet-Linux-TCP-Benchmark: RTT p50 `11,884 ms`, RTT p95 `13,369 ms`, Upload p50 `42,276 Mbit/s`, Download p50 `226,597 Mbit/s`.
- Windows-CUDA-llama.cpp-Benchmark mit 7B-Q4-GGUF: Prefill `2866,127 tok/s`, Decode `76,210 tok/s`.
- Linux-CPU-llama.cpp-Smoke mit 0.5B-Q4-GGUF: Prefill `12,382 tok/s`, Decode `0,201 tok/s`.

Der Internet-TCP-Test wurde bewusst über die Engineering-CLI mit temporärer, quell-IP-begrenzter Firewallregel ausgeführt, nicht über die unauthentifizierte Trusted-LAN-Oberfläche. Das ist echte Zielsystem-Evidenz, aber kein privater LAN-A/B-Nachweis und keine verteilte gemeinsame Inferenz.

## Identity-Entscheidung und Sicherheitsgrenze

ADR 0005 ist jetzt **für die enge M1-Referenzimplementierung akzeptiert**: stabile Node-IDs plus Ed25519-Challenge-Proofs, kurzlebiges Enrollment, Key-Rotation und Revocation-Semantik.

Das bedeutet ausdrücklich **nicht**, dass das Identity-System produktionsreif ist. Vor einer öffentlichen Netzwerkexposition fehlen weiterhin:

- Provider-/User-Authentifizierung um Enrollment-/Rotation-/Revocation-APIs;
- OS-geschützte Speicherung des privaten Node-Schlüssels für die unterstützten Windows-/Linux-Node-Agent-Pfade;
- Verteilung einer Revocation an bereits aktive Sessions;
- authentifizierter/verschlüsselter Control-Transport;
- Rate-/Resource-Limits und Abuse-Schutz;
- produktiver Service-/Datenbankbetrieb;
- Hardware-Attestation oder Sybil-Resistenz.

Ein widerrufener Node/Key wird bei neuer Authentifizierung abgelehnt. Bereits authentifizierte Sessions benötigen weiterhin ein externes Revocation-Signal zur Beendigung. Ein kopierter privater Schlüssel ist kryptografisch dieselbe Identität; Signaturen allein beweisen keinen einzelnen physischen Rechner.

Das Trusted-LAN-TCP-Benchmark-Protokoll besitzt weiterhin keine Anwendungs-Authentifizierung oder Verschlüsselung. Den assistierten Server nur in einem vertrauenswürdigen privaten LAN verwenden. `confidential_compute` ist keine zulässige Garantie, solange kein konkretes Trusted-Execution-/Attestation-Design existiert.

## Noch nicht implementiert

Es gibt weiterhin keinen produktiven Provider-Node/Installer, keine verteilte gemeinsame Inferenz-Runtime, kein Gateway/API, keinen Scheduler, keinen produktiven Identity-Netzwerkservice, kein vollständiges Wire-Protokoll, keinen fertigen Billing-/Verification-/Telemetry-Produktstack und keinen signierten Release-/Update-Pfad.

ADR 0002 (M1 Runtime Baseline) bleibt **Proposed**. Das nächste Software-Gate ist der enge llama.cpp-orientierte M1-Runtime-Spike hinter der ComputeMesh-Grenze.

## Zwei-Rechner-Ablauf

```text
SETUP.cmd (Windows) oder ./setup.sh (Linux) auf beiden Rechnern
        ↓
beide Rechner profilieren
        ↓
LAN A → B und B → A messen
        ↓
llama.cpp Prefill/Decode auf jedem relevanten Rechner messen
        ↓
engen M1-Runtime-Baseline-Pfad auswählen/validieren
        ↓
Activation-/Remote-Stage-Transport experimentieren
        ↓
erste korrekte gemeinsame Zwei-Node-Inferenz
        ↓
Scheduler kalibrieren
```

Die beiden Rechner dürfen Windows, Linux oder gemischt Windows/Linux sein; Benchmarkformat und Python-Helfer sind gemeinsam.

## Repository-Struktur

```text
ComputeMesh/
├─ SETUP.cmd              # Windows-M0-Einstieg
├─ setup.sh               # Linux-M0-Einstieg
├─ setup/                 # gemeinsamer Helper + Windows-/Linux-Starter
├─ tools/benchmark/       # Inventory, TCP-Netzwerk, llama-bench-Adapter
├─ services/orchestrator/ # dauerhafter M0-State + erste Control-Handler
├─ services/identity/     # M1-Referenz für Enrollment/Key-Registry
├─ protocol/              # Verträge, Session-Wire-Bindung, Ed25519-Verifier, Tests
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
