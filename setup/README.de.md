# ComputeMesh Windows Lab Setup

**Sprachen:** [English](README.md) | **Deutsch**

Dieser Ordner ist der einfachste Weg, den **heute tatsächlich implementierten M0-Lab-Ablauf** unter Windows auszuführen. Er ist bewusst kein „Produktions-Installer“: Provider-App, verteilte Runtime, Scheduler und produktiver Authentifizierungsstack existieren noch nicht.

## Ein Klick zum Start

Im Hauptordner des Repositories einfach doppelklicken:

```text
SETUP.cmd
```

Das Setup erkennt Deutsch/Englisch aus Windows und öffnet ein Menü. Fehlt Python 3.10+, versucht es eine benutzerbezogene Installation über `winget` und erstellt anschließend lokal `.venv`.

## Empfohlener Ablauf mit zwei Rechnern

Zuerst auf **beiden** Rechnern:

1. `SETUP.cmd` starten.
2. **1 — Diesen Rechner vorbereiten** wählen.
3. CPU-/GPU-/RAM-Kurzergebnis prüfen.

Danach das LAN in beide Richtungen messen.

### A → B

Auf Rechner **B**:

1. `SETUP.cmd` starten.
2. **2 — Netzwerk-Server** wählen.
3. Die einmalige Windows-Administratorfreigabe für die temporäre Firewall-Regel bestätigen.
4. Die angezeigte private IP merken; das Setup versucht sie zusätzlich in die Zwischenablage zu kopieren.

Auf Rechner **A**:

1. `SETUP.cmd` starten.
2. **3 — Netzwerk-Client** wählen.
3. Die auf B angezeigte IP eingeben.
4. RTT p50/p95 sowie Upload-/Download-Durchsatz im Kurzergebnis ablesen.

### B → A

Danach die Rollen genau einmal tauschen. So erhalten wir Messwerte in beide Richtungen, statt Symmetrie nur anzunehmen.

## llama.cpp messen

Auf jedem relevanten Rechner:

1. `SETUP.cmd` starten.
2. **4 — llama.cpp Prefill/Decode** wählen.
3. Falls `llama-bench.exe` noch nicht vorhanden ist: automatischen Download wählen oder eine vorhandene EXE auswählen.
4. Im Windows-Dateidialog die gewünschte `.gguf`-Datei auswählen.
5. Prefill Tokens/s, Decode Tokens/s und ms/Token im Kurzergebnis ablesen.

Der automatische Download verwendet das neueste offizielle GitHub-Release von `ggml-org/llama.cpp`. Bei NVIDIA wird bevorzugt das offizielle CUDA-12.4-x64-Paket verwendet; sonst der offizielle Vulkan-x64-Build. Liefert GitHub einen `sha256:`-Digest für das Asset, wird das Archiv vor dem Entpacken geprüft.

Modellgewichte lädt dieses Setup bewusst niemals automatisch herunter.

## Direkte Starter

Wer das Menü überspringen möchte, kann direkt eine dieser Dateien doppelklicken:

- `NODE.cmd` — Rechnerprofil erfassen/aktualisieren;
- `NETWORK-SERVER.cmd` — auf einen LAN-Test warten;
- `NETWORK-CLIENT.cmd` — den anderen Rechner messen;
- `LLAMA-BENCH.cmd` — llama.cpp auswählen/starten;
- `TESTS.cmd` — Testabhängigkeiten nur in `.venv` installieren und alle aktuellen lokalen Tests ausführen.

## Wo lokale Dateien landen

Alles vom Setup Erzeugte bleibt lokal und wird bereits von Git ignoriert:

```text
.venv/                           # isolierte Python-Umgebung
artifacts/lab/config.json        # lokale Lab-Node-ID/Revision + gemerkte Pfade
artifacts/lab/<node>/<run>/      # Benchmark-Ergebnisse
artifacts/lab/runtime/llama.cpp/ # optionale offizielle llama.cpp-Downloads
```

Die Lab-Node-ID ist zufällig (`lab-xxxxxxxx`) und verwendet nicht den Windows-Hostnamen.

## Netzwerksicherheit

Das zugrunde liegende Benchmark-Protokoll besitzt keine Authentifizierung oder Verschlüsselung. Der assistierte Windows-Server:

- akzeptiert nur ein privates RFC1918-LAN-Interface;
- verlangt bzw. setzt nach Bestätigung das Windows-Netzwerkprofil `Private`;
- bindet an genau diese private Adresse und nicht an `0.0.0.0`;
- öffnet TCP 43191 ausschließlich für `RemoteAddress LocalSubnet`, Profil `Private` und die lokale `.venv`-Python-Exe;
- entfernt die Firewall-Regel automatisch, sobald der einmalige Serverlauf endet.

Den Benchmark-Server niemals öffentlich ins Internet stellen.

## Teststand und Nachweisgrenze

Der Python-Setup-Helper und Sicherheitsinvarianten der Skripte besitzen automatisierte Tests. Zusätzlich hat der Helper einen synthetischen End-to-End-Smoke-Lauf Inventory → Netzwerk-Client → llama-Adapter → gespeicherte lokale Konfiguration bestanden.

Die aktuelle Entwicklungsumgebung ist kein Windows-System und stellt kein Windows PowerShell bereit. Die PowerShell-Oberfläche wurde deshalb statisch geprüft, muss aber noch auf den realen Windows-Lab-Rechnern ausgeführt werden. Genau dieser Lauf ist Teil des nächsten Evidenzschritts.

## Engineering-/manuelle Befehle

Fortgeschrittene Nutzer können weiterhin die Werkzeuge unter `tools/benchmark/` direkt aufrufen. Diese CLIs bleiben die kanonische Engineering-Schicht; das Setup ist eine einfachere und sicherere Benutzeroberfläche darüber.
