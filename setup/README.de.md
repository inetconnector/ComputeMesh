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

Beide Wege öffnen dasselbe Menü für Rechnerprofil, Netzwerk-Server/-Client, llama.cpp-Benchmark und Tests. Für die aktuellen M1-Evidenztransfer-Schritte gibt es zusätzlich direkte Starter, die weiter unten beschrieben sind.

## Empfohlener Ablauf mit zwei Rechnern

Die beiden Rechner dürfen Windows, Linux oder gemischt sein. Für den aktuellen M1-Placement-Nachweis müssen beide Rechner **dieselbe vollständige GGUF-Datei** benchmarken. Nur dieselbe Modellfamilie reicht nicht: Der Bundle-Pfad prüft Modell-Basename und exakte Artefaktgröße; das Modellmanifest enthält zusätzlich den exakten GGUF-SHA-256 und die Layerzahl.

Zuerst auf **beiden** Rechnern:

1. Den jeweiligen Setup-Starter starten.
2. **1 — Diesen Rechner vorbereiten** wählen.
3. CPU-/GPU-/RAM-Kurzergebnis prüfen.
4. Den llama.cpp-Benchmark mit derselben vollständigen GGUF-Datei auf beiden Rechnern ausführen.

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

## Worker-Evidenz übertragen und aktuelles Bundle bauen

Für den aktuellen Placement-Bundle-Pfad müssen nicht mehr acht einzelne JSON-Dateien von Hand ausgewählt werden.

Lege fest, welcher Rechner der **Coordinator (A)** und welcher der **Worker (B)** ist. Das Bundle verwendet den Netzwerkdatensatz Coordinator→Worker; A muss also bereits einen frischen A→B-Lauf mit den aktuellen eingebetteten Lab-IDs besitzen.

### 1. Auf dem Worker exportieren

Auf **Windows B** doppelklicken:

```text
setup\EVIDENCE-EXPORT.cmd
```

Auf **Linux B**:

```bash
bash setup/EVIDENCE-EXPORT.sh
```

Das Ergebnis ist eine ZIP-Datei unter `artifacts/lab/exports/`. Diese ZIP-Datei auf einem beliebigen vertrauenswürdigen lokalen Weg auf Rechner A kopieren.

Die ZIP-Datei enthält bewusst nur erkannte Lab-Profil-/Benchmark-JSON-Evidenz. Sie enthält **nicht**:

- das GGUF-Modell;
- llama.cpp-Binaries;
- `artifacts/lab/config.json` oder gemerkte lokale Pfade;
- beliebige andere Dateien aus dem Node-Verzeichnis.

Jede exportierte Evidenzdatei wird in `computemesh-lab-export.json` über einen relativen plattformübergreifend sicheren Pfad, die exakte Bytegröße und SHA-256 gebunden. Quell-mtimes und absolute Quell-Dateisystempfade werden nicht ins Exportmanifest übernommen.

### 2. Modellmanifest aus exakt dieser GGUF erzeugen

Auf dem Coordinator das ComputeMesh-Modellmanifest aus genau derselben vollständigen GGUF-Datei erzeugen, die beide llama-bench-Läufe verwendet haben. Dafür `tools/benchmark/gguf_manifest.py` verwenden. Das Manifest muss die aus dem Artefakt abgeleitete `layer_count`, exakte Größe und SHA-256 enthalten. Liegt das Modell noch als llama.cpp-Mehrdatei-Split vor, zuerst den vollständigen Shard-Satz zusammenführen; Schema-v1-Bundle-Erzeugung behandelt einen einzelnen Shard nicht als Gesamtmodell.

### 3. Auf dem Coordinator bündeln

Auf **Windows A** doppelklicken:

```text
setup\BUILD-BUNDLE.cmd
```

Im Dateidialog die kopierte Worker-ZIP und das Modellmanifest-JSON auswählen.

Auf **Linux A**:

```bash
bash setup/BUILD-BUNDLE.sh
```

Die kopierte Worker-ZIP und das Modellmanifest-JSON eingeben/auswählen.

Der Coordinator führt dann automatisch aus:

1. ZIP-Manifest und exakte Member-Menge prüfen;
2. ZIP-Pfadtraversal, Symlink-/verschlüsselte Einträge, Datei-/Byte-Limitüberschreitungen, Größenkonflikte und SHA-256-Konflikte ablehnen;
3. erst nach erfolgreicher Prüfung nach `artifacts/lab/imports/<peer-node>/<export-id>/` extrahieren, zunächst in ein temporäres Verzeichnis und dann per atomarem Rename;
4. bei erneutem Import einen bereits vorhandenen Export vollständig erneut prüfen statt bestehende Dateien still zu vertrauen;
5. diese Peer-Evidenz mit der aktuellen lokalen Coordinator-Evidenz und dem Modellmanifest kombinieren;
6. den fail-closed aktuellen Evidenzselektor und Placement-Planer ausführen;
7. `experiment_bundle.json` in ein neues `*-bundle`-Run-Verzeichnis des Coordinators schreiben.

Sind aktuelle Evidenzen mehrdeutig, stale, aus der falschen Netzwerkrichtung, aus nicht passenden Profilrevisionen/Modellgrößen oder würden sie die alten caller-asserted Peer-/Layer-Fallbacks benötigen, bricht die Bundle-Erzeugung ab statt zu raten.

Die ZIP-Hashes schützen Übertragungs-/Kopierintegrität und Reproduzierbarkeit. Sie authentifizieren **nicht**, wer die Evidenz erzeugt hat, und sind keine Hardware-Attestation.

## Ersten Shared-Proof ausführen

Sobald das aktuelle Bundle `shared_experiment` empfiehlt, muss der Runtime-Teil nicht mehr aus sechs manuellen Befehlen zusammengesetzt werden. Der Worker bleibt im vertrauenswürdigen privaten LAN und beide Rollen besitzen direkte Starter.

Auf **Windows B** doppelklicken:

```text
setup\SHARED-WORKER.cmd
```

Auf **Linux B**:

```bash
bash setup/SHARED-WORKER.sh
```

Der Worker-Starter bindet llama.cpp-RPC an genau eine RFC1918-Adresse auf TCP 50052. Ist im Lab Setup ein `llama-bench` gespeichert, verwendet der Worker-Starter `rpc-server` nur aus demselben lokalen llama.cpp-Build-Baum; er fällt nicht still auf einen anderen Download oder `$PATH` zurück. Fehlt dort die passende RPC-Binary, muss ein vollständiger passender Build verwendet und der Benchmark neu ausgeführt werden. Wo unterstützt, wird nur eine temporäre auf privates LAN/Subnetz begrenzte Firewallregel geöffnet und beim Ende des Workers wieder entfernt. Das Worker-Fenster/Terminal offen lassen.

Danach auf **Windows A** doppelklicken:

```text
setup\SHARED-PROOF.cmd
```

Auf **Linux A**:

```bash
bash setup/SHARED-PROOF.sh
```

Falls gefragt, das aktuelle `experiment_bundle.json` auswählen und die private IPv4 von B eingeben. Der Coordinator arbeitet dann fail-closed in dieser Reihenfolge:

1. Bundle und eingebettete Placement-Schemas erneut prüfen;
2. Evidenz ablehnen, die nach der aktuellen Profil-Altersgrenze des Planers inzwischen stale geworden ist;
3. exakt den GGUF-Basename, die Bytegröße und den SHA-256 aus dem Bundle verlangen;
4. verlangen, dass `llama-server --version` zu der gemeinsamen llama.cpp-Buildnummer/dem Commit passt, die alle vier ausgewählten Zwei-Node-llama-bench-Datensätze im Bundle tragen;
5. das aktuelle lokale llama.cpp-Gerät ermitteln und die RPC-Sichtbarkeit vor dem Modellladen prüfen;
6. falls `llama-cli` den RPC-Worker sieht, `llama-server` aber nicht, diesen Server/RPC-Kompatibilitätsfall ausdrücklich melden statt den Messlauf zu starten;
7. die deterministische lokale Baseline ausführen;
8. ein frisches Zero-Delay-Loopback-Mess-Relay starten und exakt den vom Planer gewählten Zwei-Einträge-Split darüber ausführen;
9. exakte Token-ID-Korrektheit verlangen, sofern vorhanden, sonst exakten Output-Digest;
10. `comparison.json`, Relay-Metriken und das bereits definierte fail-closed `shared_run_evidence.json` schreiben.

Ein fehlgeschlagener Versuch behält ein begrenztes, inhaltsfreies `shared_trial_failure.json` mit der Fehlerphase. Rohprompt und Roh-Modelloutput werden dort nicht hineinkopiert.

**Aktuelle Grenze des automatischen Runners:** Die Coordinator-Seite muss Accelerator-backed sein. Der ausgewählte Worker darf von Upstream-RPC auch mit CPU-only-Backend exponiert werden; der Runner tut aber nicht so, als sei lokales `--device none` ein explizites Split-Gerät. Ein CPU-only-Coordinator stoppt daher vor der Ausführung, statt `none,RPC0`-Placement-Semantik zu erfinden.

Diese Convenience-Schicht authentifiziert weder llama.cpp-RPC noch Relay-Ziel oder physischen Worker. Sie bleibt Trusted-Private-Lab-Tooling.

## Verhalten unter Windows

- Deutsch/Englisch aus Windows erkennen;
- Python 3.10+ finden oder benutzerbezogen über `winget` installieren;
- lokale `.venv` anlegen;
- den Netzwerkbenchmark an eine konkrete private Adresse binden;
- die aktuelle zufällige Lab-Node-ID in den Netzwerk-Server-/Client-Evidenzpfad geben;
- TCP 43191 nur vorübergehend für Windows `Private` + `LocalSubnet` öffnen und die Regel nach dem einmaligen Test entfernen;
- Windows-Dateidialoge für `llama-bench.exe` und GGUF anbieten;
- den vom Setup ausgewählten offiziellen Windows-llama.cpp-Build herunterladen können;
- Evidenzexport/-import ausschließlich mit Standardbibliothek-ZIP-/Hash-Funktionen durchführen;
- die kleine `jsonschema`-Abhängigkeit nur dann in die lokale `.venv` installieren, wenn der Bundle-Schritt sie benötigt und sie noch nicht vorhanden ist.

Direkte Windows-Starter: `NODE.cmd`, `NETWORK-SERVER.cmd`, `NETWORK-CLIENT.cmd`, `LLAMA-BENCH.cmd`, `EVIDENCE-EXPORT.cmd`, `BUILD-BUNDLE.cmd`, `SHARED-WORKER.cmd`, `SHARED-PROOF.cmd`, `TESTS.cmd`.

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
- auf Desktops `zenity` zur GGUF-Auswahl verwenden, wenn vorhanden, sonst den Pfad im Terminal mit Shell-Vervollständigung abfragen;
- denselben isolierten Python-Bootstrap für Evidenzexport-/Bundle-Starter wiederverwenden.

Direkte Linux-Starter: `NODE.sh`, `NETWORK-SERVER.sh`, `NETWORK-CLIENT.sh`, `LLAMA-BENCH.sh`, `EVIDENCE-EXPORT.sh`, `BUILD-BUNDLE.sh`, `SHARED-WORKER.sh`, `SHARED-PROOF.sh`, `TESTS.sh`. `bash setup/EVIDENCE-EXPORT.sh`, `bash setup/BUILD-BUNDLE.sh`, `bash setup/SHARED-WORKER.sh` und `bash setup/SHARED-PROOF.sh` funktionieren auch dann, wenn Download/Archiv das Ausführungsbit nicht erhalten hat.

Die automatisch geladenen offiziellen Linux-Pakete sind Ubuntu-Binaries. Auf kompatiblen glibc-Distributionen funktionieren sie häufig, aber das Setup verlässt sich nicht darauf: Startet die Binary nicht, wird sie verworfen und du kannst ein distributionspassendes oder selbst gebautes `llama-bench` angeben. Auf musl-Systemen wie Alpine ist ein vorhandener kompatibler Build für llama.cpp der sicherere Weg.

## llama.cpp messen

Auf jedem relevanten Rechner:

1. Setup starten.
2. **4 — llama.cpp Prefill/Decode** wählen.
3. Automatischen offiziellen Download oder vorhandenes `llama-bench` auswählen.
4. Auf beiden Experimentrechnern dieselbe **vollständige lokale `.gguf`-Modelldatei** auswählen/angeben.
5. Prefill Tokens/s, Decode Tokens/s und ms/Token ablesen.

Modellgewichte werden **niemals automatisch heruntergeladen** und vom Evidenzexport nicht kopiert.

## Lokale Dateien

Alles vom Setup Erzeugte bleibt lokal und wird bereits von Git ignoriert:

```text
.venv/                                         # isolierte Python-Umgebung
artifacts/lab/config.json                      # lokale Node-ID/Revision + gemerkte Pfade
artifacts/lab/<node>/<run>/                    # Benchmark-Ergebnisse und Bundle-Runs
artifacts/lab/runtime/llama.cpp/               # optionale Upstream-llama.cpp-Downloads
artifacts/lab/exports/<lab-export-...>.zip     # begrenzte übertragbare Evidenz-ZIP
artifacts/lab/imports/<peer>/<export-id>/      # verifizierter Peer-Evidenzimport
```

Die Lab-Node-ID ist zufällig (`lab-xxxxxxxx`) und verwendet nicht den Hostnamen.

## Netzwerk- und Evidenztransfer-Sicherheit

Das zugrunde liegende Benchmark-Protokoll besitzt keine Authentifizierung oder Verschlüsselung. Beide assistierten Server:

- akzeptieren nur private RFC1918-Adressen;
- binden an genau eine private Adresse und nicht an `0.0.0.0`;
- verwenden temporäre Firewallregeln, wenn die unterstützte Firewallintegration aktiv ist;
- entfernen diese Regeln nach Ende des einmaligen Serverlaufs.

Der optionale Austausch der Lab-Node-ID ändert diese Sicherheitsgrenze **nicht**. Eine Gegenseite kann irgendeine Lab-ID selbst melden, weil die Benchmark-Verbindung nicht authentifiziert ist. Für echte authentifizierte Node-Identity besitzt ComputeMesh einen separaten engen M1-Ed25519-/Session-Referenzpfad; dieser authentifiziert den Benchmark-Socket nicht.

Die Evidenz-ZIP ist ein lokaler Transfercontainer und kein Trust Envelope. Dateihashes erkennen veränderte/beschädigte Kopien, signieren aber nicht den Erzeuger, authentifizieren keinen Node und attestieren keine Hardware. Auch der Import gehört deshalb ausschließlich in den kontrollierten Trusted-Lab-Ablauf.

Benchmark-Server und Upstream-llama.cpp-RPC-Worker niemals öffentlich ins Internet stellen.

## Teststand

Die vollständige Setup-Testaktion führt Benchmark-, Orchestrator-, Protocol-, Identity-, Scheduler-, llama-Runtime-, Network-Runtime- und Setup-Suites aus. Die aktuellen plattformübergreifenden Testzahlen und der exakte letzte Validierungslauf stehen in `state.md`.

Die Linux-Schicht deckt zusätzlich Bash-Syntax, den Root-Einstieg `setup.sh`, private/öffentliche IPv4-Filterung, aktuelle llama.cpp-CPU-/Vulkan-/ROCm-/ARM64-Assetnamenauswahl, Private-Bind-/temporäre-Firewall-Invarianten und das Routing der direkten Linux-Starter ab. Die Windows-Validierung lässt zusätzlich beide Shared-Proof-PowerShell-Starter vom echten Windows-PowerShell-Parser parsen.

Die Evidenztransfer-Abdeckung umfasst Ausschluss beliebiger/GGUF-Dateien, pfadfreie Exportmanifeste, Profilrevisionsbindung, hash-verifizierte idempotente Roundtrips, Ablehnung veränderter Inhalte, ZIP-Symlink-/Traversal-Ablehnung, Erkennung manipulierter vorhandener Imports, abhängigkeitssparsamen `lab.py`-Start mit `python -S` und einen vollständigen synthetischen Worker-Export→Coordinator-Bundle-Roundtrip.

Die Evidenzbindungs-Tests prüfen außerdem, dass das Setup seine eigene Lab-Node-ID an beide Netzwerkrollen weitergibt, aktuelle Benchmark-Peers eine begrenzte ID selbst melden können und Peer-Konflikte nicht stillschweigend akzeptiert werden.

Bis ein frischer Zwei-Rechner-Lauf in einem vertrauenswürdigen privaten LAN mit einer identischen vollständigen GGUF-Datei gespeichert ist, bleibt dies Software-/Loopback-/synthetische Evidenz.

Zusätzliche echte Zielsystem-Evidenz existiert seit dem 21.08.2026:

- Windows-Direktstarter-Profil auf einem Rechner mit RTX 3080 Laptop GPU.
- Linux-Direktstarter-Profil und vollständige Testsuite auf einem Debian-13-Internetserver.
- Windows -> Linux-Internet-TCP-Benchmark mit temporärer, quell-IP-begrenzter Firewallregel.
- Echte llama.cpp-Läufe auf Windows CUDA mit einem 7B-Q4-GGUF und auf Linux CPU mit einem 0.5B-Q4-GGUF.

Diese beiden historischen llama.cpp-Läufe verwendeten unterschiedliche GGUFs und können deshalb nicht zum neuen aktuellen Evidenzbundle zusammengesetzt werden. Auch der Internet-Benchmark stammt noch vor dem gebundenen Peer-ID-Pfad und ist weder ein Trusted-Private-LAN-Nachweis noch ein Shared-Inference-Ergebnis.

## Engineering-/manuelle Befehle

Fortgeschrittene Nutzer können den neuen Transferpfad direkt aufrufen:

```bash
python setup/lab.py export
python setup/lab.py import --archive /pfad/zum/peer.zip
python setup/lab.py bundle --peer-export /pfad/zum/peer.zip --model-manifest /pfad/zum/model_manifest.json
```

Der direkte Bundle-Befehl unterstützt bei mehreren ansonsten gültigen aktuellen Kandidaten zusätzlich explizite Evidenzselektoren (`--artifact-digest`, `--benchmark-model-name`, `--network-run-id`). Diese Selektoren wählen Evidenz aus; sie aktivieren die alten caller-asserted Peer-/Layer-Fallbacks **nicht** wieder.

Fortgeschrittene Nutzer können weiterhin die Werkzeuge unter `tools/benchmark/` direkt aufrufen. Diese CLIs bleiben die kanonische Engineering-Schicht; die Setup-Starter sind die einfachere Benutzeroberfläche darüber.
