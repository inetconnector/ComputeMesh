# ComputeMesh Lab Setup — Windows und Linux

**Sprachen:** [English](README.md) | **Deutsch**

Dieser Ordner ist der einfachste Weg, den **heute tatsächlich implementierten M0/M1-Lab-Ablauf** auszuführen. Er ist bewusst kein Produktions-Installer: Provider-App, produktive verteilte Runtime, produktiver Scheduler und produktiver Authentifizierungs-/Transport-Stack existieren noch nicht.

## Start

**Windows** — im Repository-Hauptordner doppelklicken:

```text
SETUP.cmd
```

**Linux** — im Repository-Hauptordner:

```bash
./setup.sh
```

Falls beim Herunterladen/Entpacken das Ausführungsbit verloren gegangen ist:

```bash
bash setup.sh
```

Beide Wege öffnen dasselbe Menü für Rechnerprofil, Netzwerk-Server/-Client, llama.cpp-Benchmark und Tests.

## Empfohlener Ablauf mit zwei Rechnern

Die beiden Rechner dürfen Windows, Linux oder gemischt sein.

Zuerst auf **beiden** Rechnern:

1. Den jeweiligen Setup-Starter starten.
2. **1 — Diesen Rechner vorbereiten** wählen.
3. CPU-/GPU-/RAM-Kurzergebnis prüfen.

Jedes Setup besitzt eine zufällige Lab-Node-ID wie `lab-1a2b3c4d`. Sie wird nicht aus dem Hostnamen abgeleitet.

Danach das LAN in beide Richtungen messen.

### A → B

Auf Rechner **B**:

1. Setup starten.
2. **2 — Netzwerk-Server** wählen.
3. Eine temporäre Firewall-/Administratorfreigabe bestätigen, falls das Betriebssystem sie verlangt.
4. Die angezeigte private IP merken.

Der aktuelle Server meldet zusätzlich die Lab-Node-ID von B über die Benchmark-Verbindung selbst.

Auf Rechner **A**:

1. Setup starten.
2. **3 — Netzwerk-Client** wählen.
3. Die private IP von B eingeben.
4. RTT p50/p95 sowie Upload-/Download-Durchsatz ablesen.

Der erzeugte Netzwerkdatensatz enthält die lokale Lab-Node-ID von A und bei einem aktuellen Server die selbst gemeldete Lab-Node-ID von B. Die Bindung wird als `unauthenticated_server_report_v1` gekennzeichnet: Das verbessert die Nachvollziehbarkeit des Experiments, ist aber **keine Authentifizierung**.

### B → A

Danach die Rollen einmal tauschen. Damit wird die Richtungsabhängigkeit gemessen statt Symmetrie nur anzunehmen und die umgekehrte Local-/Peer-Zuordnung aufgezeichnet.

## Verhalten unter Windows

- Deutsch/Englisch aus Windows erkennen;
- Python 3.10+ finden oder benutzerbezogen über `winget` installieren;
- lokale `.venv` anlegen;
- den Netzwerkbenchmark an eine konkrete private Adresse binden;
- die aktuelle zufällige Lab-Node-ID in den Netzwerk-Server-/Client-Evidenzpfad geben;
- TCP 43191 nur vorübergehend für Windows `Private` + `LocalSubnet` öffnen und die Regel nach dem einmaligen Test entfernen;
- Windows-Dateidialoge für `llama-bench.exe` und GGUF anbieten;
- den vom Setup ausgewählten offiziellen Windows-llama.cpp-Build herunterladen können.

Direkte Windows-Starter: `NODE.cmd`, `NETWORK-SERVER.cmd`, `NETWORK-CLIENT.cmd`, `LLAMA-BENCH.cmd`, `TESTS.cmd`.

## Verhalten unter Linux

- Deutsch/Englisch aus der Linux-Locale erkennen;
- Python 3.10+ verwenden und lokale `.venv` anlegen;
- fehlende Basispakete nach Rückfrage über `apt`, `dnf`, `zypper`, `pacman` oder `apk` installieren; Root/`sudo` wird nur dafür verwendet;
- mit `iproute2` ein privates RFC1918-Interface erkennen und den Benchmark an genau diese Adresse binden;
- die aktuelle zufällige Lab-Node-ID in den Netzwerk-Server-/Client-Evidenzpfad geben;
- bei aktivem `firewalld` eine nicht-permanente Rich Rule nur für erkanntes Subnetz/Adresse/Port anlegen und danach entfernen;
- bei aktivem `ufw` eine temporäre Regel für das Quellsubnetz anlegen und danach löschen;
- bei keiner unterstützten aktiven Firewall keine Firewall verändern und trotzdem nur an das private Interface binden;
- vorhandenes `llama-bench` verwenden oder das aktuelle offizielle llama.cpp-Release nach einem passenden Linux-Asset abfragen;
- ROCm bevorzugen, wenn `rocminfo` vorhanden ist, sonst Vulkan bei Vulkan-/NVIDIA-/DRI-Nachweis, sonst CPU;
- offizielle Ubuntu-x64-/arm64-CPU-/Vulkan-Assets und x64-ROCm-Assets dynamisch auswählen;
- einen von GitHub gelieferten `sha256:`-Digest prüfen, sofern vorhanden;
- die heruntergeladene Binary mit lokalem `LD_LIBRARY_PATH`-Wrapper starten und nur akzeptieren, wenn `llama-bench --help` erfolgreich startet;
- auf Desktops `zenity` zur GGUF-Auswahl verwenden, wenn vorhanden, sonst den Pfad im Terminal mit Shell-Vervollständigung abfragen.

Direkte Linux-Starter: `NODE.sh`, `NETWORK-SERVER.sh`, `NETWORK-CLIENT.sh`, `LLAMA-BENCH.sh`, `TESTS.sh`.

Die automatisch geladenen offiziellen Linux-Pakete sind Ubuntu-Binaries. Auf kompatiblen glibc-Distributionen funktionieren sie häufig, aber das Setup verlässt sich nicht darauf: Startet die Binary nicht, wird sie verworfen und du kannst ein distributionspassendes oder selbst gebautes `llama-bench` angeben. Auf musl-Systemen wie Alpine ist ein vorhandener kompatibler Build für llama.cpp der sicherere Weg.

## llama.cpp messen

Auf jedem relevanten Rechner:

1. Setup starten.
2. **4 — llama.cpp Prefill/Decode** wählen.
3. Automatischen offiziellen Download oder vorhandenes `llama-bench` auswählen.
4. Lokale `.gguf`-Modelldatei auswählen/angeben.
5. Prefill Tokens/s, Decode Tokens/s und ms/Token ablesen.

Modellgewichte werden **niemals automatisch heruntergeladen**.

## Lokale Dateien

Alles vom Setup Erzeugte bleibt lokal und wird bereits von Git ignoriert:

```text
.venv/                           # isolierte Python-Umgebung
artifacts/lab/config.json        # lokale Node-ID/Revision + gemerkte Pfade
artifacts/lab/<node>/<run>/      # Benchmark-Ergebnisse
artifacts/lab/runtime/llama.cpp/ # optionale Upstream-llama.cpp-Downloads
```

Die Lab-Node-ID ist zufällig (`lab-xxxxxxxx`) und verwendet nicht den Hostnamen.

## Netzwerksicherheit

Das zugrunde liegende Benchmark-Protokoll besitzt keine Authentifizierung oder Verschlüsselung. Beide assistierten Server:

- akzeptieren nur private RFC1918-Adressen;
- binden an genau eine private Adresse und nicht an `0.0.0.0`;
- verwenden temporäre Firewallregeln, wenn die unterstützte Firewallintegration aktiv ist;
- entfernen diese Regeln nach Ende des einmaligen Serverlaufs.

Der optionale Austausch der Lab-Node-ID ändert diese Sicherheitsgrenze **nicht**. Eine Gegenseite kann irgendeine Lab-ID selbst melden, weil die Benchmark-Verbindung nicht authentifiziert ist. Für echte authentifizierte Node-Identity besitzt ComputeMesh einen separaten engen M1-Ed25519-/Session-Referenzpfad; dieser authentifiziert den Benchmark-Socket nicht.

Den Benchmark-Server niemals öffentlich ins Internet stellen.

## Teststand

Die vollständige Setup-Testaktion führt Benchmark-, Orchestrator-, Protocol-, Identity-, Scheduler-, llama-Runtime-, Network-Runtime- und Setup-Suites aus. Die aktuellen plattformübergreifenden Testzahlen und der exakte letzte Validierungslauf stehen in `state.md`.

Die Linux-Schicht deckt zusätzlich Bash-Syntax, den Root-Einstieg `setup.sh`, private/öffentliche IPv4-Filterung, aktuelle llama.cpp-CPU-/Vulkan-/ROCm-/ARM64-Assetnamenauswahl, Private-Bind-/temporäre-Firewall-Invarianten und das Routing der direkten Linux-Starter ab.

Die neuen Evidenzbindungs-Tests prüfen außerdem, dass das Setup seine eigene Lab-Node-ID an beide Netzwerkrollen weitergibt, aktuelle Benchmark-Peers eine begrenzte ID selbst melden können und Peer-Konflikte nicht stillschweigend akzeptiert werden.

Bis ein frischer Zwei-Rechner-Lauf in einem vertrauenswürdigen privaten LAN gespeichert ist, bleibt dies Software-/Loopback-Evidenz.

Zusätzliche echte Zielsystem-Evidenz existiert seit dem 21.08.2026:

- Windows-Direktstarter-Profil auf einem Rechner mit RTX 3080 Laptop GPU.
- Linux-Direktstarter-Profil und vollständige Testsuite auf einem Debian-13-Internetserver.
- Windows -> Linux-Internet-TCP-Benchmark mit temporärer, quell-IP-begrenzter Firewallregel.
- Echte llama.cpp-Läufe auf Windows CUDA mit einem 7B-Q4-GGUF und auf Linux CPU mit einem 0.5B-Q4-GGUF.

Der Internet-Benchmark stammt noch vor dem gebundenen Peer-ID-Pfad und ist weder ein Trusted-Private-LAN-Nachweis noch ein Shared-Inference-Ergebnis.

## Engineering-/manuelle Befehle

Fortgeschrittene Nutzer können weiterhin die Werkzeuge unter `tools/benchmark/` direkt aufrufen. Diese CLIs bleiben die kanonische Engineering-Schicht; die Setup-Starter sind die einfachere Benutzeroberfläche darüber.
