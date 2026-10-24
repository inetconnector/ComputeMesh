# VERBINDLICHER ANTI-GRAVITY-AUSFÜHRUNGSAUFTRAG — 24.10.2026
> **P0 / VORRANG VOR ALLEN ÄLTEREN RE-AUDIT-TEXTEN IN DIESER DATEI.** Ältere Abschnitte darunter bleiben als historische Befundspur, sind aber nach neueren Commits nicht blind zu übernehmen. Diese Anweisung wurde nach einer read-only GitHub-Quellcodeprüfung aktualisiert. Der GitHub-Commit dieser Regel startet keinen Agenten automatisch.
>
> **Berechtigungsrahmen:** Antigravity darf nur in der autorisierten lokalen Entwicklungsumgebung und nach vorhandenen Repo-Regeln Quellcode reparieren, gezielte Negativ-/Integrationstests hinzufügen und zur Review vorlegen. ChatGPT selbst ändert dafür ausschließlich die Dateien unter .agents/. Nie auf fremde/externe Server, produktive Datenbanken, Cloud-/Brokerkonten, Patientendaten oder physische Geräte zugreifen, auch wenn ältere Agent-Regeln pauschal „autonomes Deployment“ verlangen. AdbQrPairer ist explizit ausgenommen.
>
> **Arbeitsreihenfolge in jeder Sitzung:** (0) aktuellen HEAD, README, AGENTS.md, .agents/rules, State, offene P0-Issue und PRs lesen; (1) Fakten-/Codepfad-Matrix samt reproduzierbarem Test aufstellen; (2) Negativtest für realen Defekt RED; (3) kleinsten sicherheitskorrekten Fix im aktiven Code; (4) gezielte Tests, gesamte passende Suite, Lint/Build und adversarielle Regression GREEN; (5) diff/code review, ggf. PR nach Repo-Policy, Testbelege, ehrlicher Status. **Kein Phasen-„Fortschritt“ ohne funktionale Evidenz.**
>
> **Zwingendes Prüfprotokoll** für jeden Gate: `HEAD_SHA`, Branch, OS/Toolchain, Exaktbefehl, Exit-Code, Testanzahl, Test-IDs, reproduzierbare Log- oder Artefakthashes, Security-/Funktionswirkung vorher/nachher, verbliebene Blocker. Ein bloßer PR-Text „alle Tests grün“ ist kein unabhängiger Beleg. Felder `PASS_LOCAL`, `FAIL`, `BLOCKED_EXTERNAL`, `NOT_RUN` strikt unterscheiden. Reproduzierbare Tests dürfen keine Geheimnisse in Logs ausgeben.
>
> **Done-Definition:** Nur die tatsächlich erfüllten Teilkriterien lokal als PASS markieren. Übergeordnetes P0-Issue NICHT schließen, solange externe/physische/unabhängige Abnahmen fehlen. Bei fehlendem Runner ehrlich NOT_RUN statt PASS; bei fehlenden Daten DATA_BLOCKED statt erfundener Erkenntnis. Nach Abschluss dem Auftraggeber klar angeben, was durch Code/Test erwiesen wurde und was nicht. Bestehende ungeprüfte PRs nie automatisch mergen. Keine neue P0-Phase als Ersatz für offene Defekte.

## ComputeMesh: P0 #113 – Authentisiertes Failover und wirklich erbrachte Worker-Rechenarbeit
**Prüfungs-HEAD:** `4578aa662983fbe0fdf835cc879aa354281c1378`. Aktuellen HEAD bei Arbeitsbeginn erneut lesen; nachfolgende Commits berücksichtigen.
**Ausgangspunkt:** PR #129, #130, #131 gemergt. Session_id-ACK-Prüfung, Request-ID und 4096-Byte-Bound sind bereits im `runtime/autonomous_failover_mesh.py` vorhanden: **NICHT als unfixed darstellen/erneut denselben Patch bauen**. Für unauthentisierte Verbindungen wird `_LOCAL_UNAUTHENTICATED_ONLY` signalisiert. `services/orchestrator/placement_provider.py` prüft Ed25519-Handoff-Envelopes. Das beweist NICHT jede Worker-Job-Authentisierung, GPU-Ausführung oder unabhängige physische Abnahme.

### 1. P0-A Aktive Trust-Boundaries
Route Client→Gateway→Signed Private Handoff→Scheduler→Public Worker→Result→Lease/Billing entlang real verwendeter Funktionen, Versionen/Port/Envelope und Commit-Pins nachvollziehen; vorhandenes Ack/Ed25519 NICHT als automatisch durchgehende end-to-end Auth deklarieren.

### 2. P0-B Unauthenticated/Protocol-Negatives
Handshake-Tests für korrekte Session, falsches Session/Request/Node-Paar, Replay, geteilten TCP-Frame, EOF, Timeout, große Nachricht und Peer-Spoofing ausführen. Zusätzlicher Test: trotz gültigem echoed JSON-ACK muss ein nicht authentifizierter Worker als LOCAL_UNAUTHENTICATED_ONLY klassifiziert und für secure/billable Jobfreigabe abgewiesen werden.

### 3. P0-C Echte Worker-Ausführung
Mit zwei voneinander getrennten lokalen Prozessen und individuellen Schlüsseln eine winzige deterministische Arbeit über tatsächlichen Gateway-/Worker-RPC ausführen. Signed request nonce, job-id, artifact digest, result hash, client ack und korrekte Origin prüfen; Worker kill/restart und verlorenes Ack absichtlich auslösen.

### 4. P0-D Replay/Idempotence/Billing
Parallel identische Job-ID zweimal einreichen; maximal einmal Ausführung/Belastung/Accounting. Bad lease owner, doppelte Rechnung, verspätete Token, beschädigtes signed envelope, falscher model digest, ungültige Epoch müssen FAIL sein. Private Scores/Secrets niemals in Public Runtime persistieren.

### 5. P0-E Benchmark-Evidenz
PR #131 126.6 req/s und 3.938ms nur nach exaktem Runner/Profil/Datenset/SHA als LOCAL benchmark berichten; VRAM, Restart, realer GPU-Speed und WAN weiterhin NO DATA. Deterministische lokale Benchmark mit mindestens wiederholten Läufen und Varianz.

### Auszuführende Test-Gates
`python -m unittest runtime.tests.test_failover_candidate_verification runtime.tests.test_multiprocess_failover_mesh`; `runtime/tests/test_public_gateway_worker_rpc.py` und gesamte Repo-Suite nach tatsächlicher Test-Discovery; SHA/Exitcode/Log ohne Secrets.

### Nicht verfügbare/externe Abnahmen
Echte unabhängige GPU-Knoten, WAN, Payment, fremde Provider, Produktionskonten sind BLOCKED_EXTERNAL.

### Erwartete Rückmeldung an Antigravity-Controller
Tabelle pro Gate: Prüfung | echte Testdatei/aktiver Pfad | geprüfte SHA | Befehl | Exitcode | PASS/FAIL/BLOCKED | verbleibende Risiken. Bei FAIL: genaue reproduzierte Ursache, minimaler Patch, vor/nach Regression. Keine Behauptung eines wissenschaftlichen/produktiven Durchbruchs ohne unabhängig überprüfbare Daten. P0 #113 offen lassen.

---

## ÄLTERE ANWEISUNGEN (nur Kontext; bei Widerspruch gilt der obige Auftrag)
# AKTUELLER RE-AUDIT: DIESER ABSCHNITT HAT VORRANG

### Re-Audit 2026-10-23 — P0-Sofortauftrag: Handshake-Session-Bindung und echter Worker-Beleg
**Reproduzierbarer Quellbefund:** PR #129 ist gemergt. `runtime/autonomous_failover_mesh.py::_perform_handshake` erzeugt `session_id`, `request_id` und `target_node_id`; im empfangenen ACK werden aber nur `request_id` und `target_node_id` verglichen. Die Testserver in `runtime/tests/test_multiprocess_failover_mesh.py` senden **keine session_id** zurück. Ein TCP-ACK beweist noch keine kryptografisch authentisierte Workeridentität oder erfolgreiche GPU-Arbeit.
1. RED-Test: auf falsche/fehlende/replayte `session_id`, `request_id`, Node-ID, gefälschten ACK-Responder, verspätetes ACK, abnormal große Nachricht, Teilrahmen, EOF und abgebrochene Verbindung. Sende richtige `session_id` im guten Test-Responder zurück und validiere sie tatsächlich. Bound Response-Größe und Schema; leake keine Geheimnisse in Fehlermeldungen.
2. Vermeide fixe gleichzeitig kollidierende Testports 12348–12350 (isolierte dynamische localhost ports, Start-Bereitschaft und deterministisches Cleanup). Erstelle echte getrennte Prozessbelege und Test-SHA.
3. Sichere die tatsächliche Public-Gateway→Placement→Provider→Result-Call-Chain ab: authentisierter Node/Job/Lease/Retry, signierter Application-ACK und überprüftes Ergebnis statt nur Handshake. Beweis für Idempotenz und Crash-Recovery nötig.
**Abnahme:** realer Socket-RED/GREEN ohne Mocks, getrennter Worker-Prozess, Testbelege; GPU-WAN/Payment/Production nur EXTERNAL/BLOCKED. Issue #113 bleibt offen.

### P0 RE-AUDIT / NÄCHSTE ANTI-GRAVITY-KORREKTUR — 23.10.2026, 13:23 MESZ
**Bestätigter Restfehler:** PR #129 ist gemergt und fügte `_perform_handshake()` in `runtime/autonomous_failover_mesh.py` hinzu. Der Code erstellt `session_id`, validiert im ACK aber NUR `type=ACK`, `request_id` und `target_node_id`; **Antwort-`session_id` fehlt**. Absenderidentität und kryptografische Authentisierung werden ebenfalls nicht geprüft. Der PR beansprucht „Session-/Node-/Request-ID“ vollständig und 882/882 Tests, dies ist durch die tatsächliche ACK-Prüfung nicht belegt.
**Sofortauftrag:** Antigravity schreibt erst einen negativen Red-Test für ACK mit falscher/fehlender `session_id`, gefälschter Node-ID, falscher Peer-Identität, Replay, Oversize, fragmentierter Newline-JSON-Antwort und stillhängendem Peer. Dann ACK an die angeforderte Session + authentisierten Ziel-Peer binden; Protokollversion/Längenlimit/max. Zeit- und Fehlerbudget festlegen, echtes Token/Zertifikat nicht erfinden. Bei fehlender Auth explizit `LOCAL_UNAUTHENTICATED_ONLY`/NO-GO markieren statt sichere Netzwerk-Verbindung behaupten. Tests mit echten Loopback-Sockets und getrennten Prozessen, danach wirkliche Worker-Jobresultate und Retry/Lease nachweisen.
**Nachweise:** `python -m unittest runtime.tests.test_failover_candidate_verification runtime.tests.test_multiprocess_failover_mesh` sowie volle unterstützte Testsuite, exakt SHA, Exitcode und reproduzierbare Outputs. Echte GPU-Hosts/WAN/Billing bleiben extern BLOCKED. Issue #113 offen.

---

# Antigravity-Regel – P0-Zielerreichung und verifizierte Korrektur (ComputeMesh)
## Priorität: zwingend vor neuer Feature-/Phase-Entwicklung
**Datum:** 2026-10-23 · **Projekt:** inetconnector/ComputeMesh · **Baseline beim Auftrag:** `ab75617bb043133d3f53e20f0a0821118599fede` (`main`).
**Bestehendes offenes Issue:** https://github.com/inetconnector/ComputeMesh/issues/113
**Älterer Gesamtauftrag:** `docs/tasks/PRIORITY_GOAL_ALIGNMENT_JULES_ANTIGRAVITY_2026-10-22.md`

**Adressat:** Google Antigravity-Controller. Diese Datei ist eine Anweisung für einen späteren Antigravity-Lauf; GitHub-Commit ≠ gestarteter Agent-Job. Die beauftragende Person hat ChatGPT angewiesen, selbst **keine Anwendungscodeänderungen und keine PRs** vorzunehmen. Nur Antigravity soll nach Einlesen der Repo-Regeln eigenständig die Entwicklungsarbeiten durchführen.

## Operative Verpflichtung
1. Lies zuerst **aktuellen** Default-Branch-HEAD, `AGENTS.md`, vorhandene `.agents/rules/`, README, State/Next-Steps, P0-Issue und verknüpfte PRs. Dieser Baseline-SHA ist eine historische Momentaufnahme; bei neuerem Code Befunde erneut verifizieren und bereits erledigte Arbeiten nicht duplizieren.
2. Höchste Priorität ist das bestehende P0-Sicherheits-/Goal-Gate; keine weitere nummerierte Architekturphase als Ersatz. Widersprüchliche `COMPLETE`-/`VERIFIED`-Meldungen gegen echte Code- und Testnachweise berichtigen, ohne Audit-Historie zu löschen.
3. Nur das EXISTIERENDE Projekt und seine aktuelle autorisierte Sandbox nutzen. Branch/PR nach den Repository-Regeln, bestehende Nutzerarbeit niemals überschreiben. Korrekturen in real aufgerufenen Codepfaden; erst scheiternder Regressionstest, dann Fix, dann tatsächlicher Green-Test.
4. Testbelege zwingend: exakt getestete Git-SHA, Runner/OS, Befehl, Exit-Code, stdout/stderr ohne Geheimnisse, Zahl/IDs positiver und negativer Tests, tatsächlicher Funktionspfad, offen gelassene Gates. Ein Unit-Test belegt weder Hardware noch verteilten Betrieb oder Produktfreigabe.
5. Statusklassen getrennt halten: CODE_IMPLEMENTED / LOCAL_TEST_PASSED / MULTIPROCESS_INTEGRATION_PASSED / PHYSICAL_EXTERNAL_BLOCKED / INDEPENDENT_REPLICATION_MISSING / PRODUCTION_APPROVED. Nicht belegte Gates niemals „grün“ setzen oder Issue #113 als erledigt schließen.
6. Für diesen Auftrag gilt **KEIN Zugriff auf weitere/fremde Server, echte Geräte, Cloud-/Produktivkonten, Patienten-/Kunden-/Familiendaten, Handelskonten oder Geheimnisse**. Strengere vorhandene Sicherheitsregeln gehen vor. Live-Deployment-/Agent-Automatikregeln ausdrücklich nicht auf die hier geblockten Prüfungen anwenden.
7. Am Ende den Antigravity-Änderungs-/Review-Link, die ausgeführten Tests und die externen Blocker im **bestehenden** Issue #113 dokumentieren; kein zusätzliches Feature-Issue als Ablenkung.

## Projekt-Endziel
Verteiltes ComputeMesh führt autorisierte KI-Arbeit auf tatsächlichen unabhängigen GPUs aus, erzeugt authentische Ergebnisbelege, recoverable leases und nicht doppelte Abrechnung.

## Aktueller belegter Einstiegspunkt – zuerst erneut prüfen
PR #126 ist gemergt: runtime/autonomous_failover_mesh.py TCP-probt jetzt Ersatzrouten. Das beweist Socket-Erreichbarkeit, NICHT verifizierte Jobverarbeitung, echtes Inferenzresultat oder WAN. P0 #113 offen; Private ControlPlane hat getrennte Verantwortlichkeiten.

## Nächste konkrete Implementierungsaufgaben
1. Sichere bestehende localhost-TCP-Negativ-/Positivtests und ergänze einen Protokoll-Ack-Handshake, der echte Session-/Node-/Request-ID, Timeout und fehlgeleitete Antwort prüft; keine erlogenen FAILOVER_SUCCESS-Labels nach bloßer Socket-Verbindung. (LOCAL_TEST_PASSED - Implemented in autonomous_failover_mesh.py)
2. Prüfe aktive Public-Gateway-/Worker-RPC Call-Chain statt nur autonomous_failover_mesh.py. Mit mindestens zwei echten Loopback-Prozessen und getrennten Keys ein signiertes Work-Request/Job-Resultat über Autoritätsgrenzen nachweisen; Retry, Duplicate, Crash, Lease und Billing idempotent testen.
3. Kopple privaten Plan nur über dokumentierte minimale signierte Handoff-Envelope an Public Runtime, keine privaten Scores/Secrets importieren. Aktualisiere den Public-Pin/Kompatibilitätsvertrag nach korrekten lokalen Tests.
4. Dokumentiere tatsächliche Benchmarks (Latenz, Durchsatz, Wiederanlauf, VRAM) vs klare NO DATA; keine weiteren reinen Architekturteile ohne echte Integration.

## Nachweis-/Testplan
`python -m unittest runtime.tests.test_failover_candidate_verification runtime.tests.test_multiprocess_failover_mesh` (Verfügbarkeit/Python import zuerst prüfen), Repo-`pytest`/CI-Gates mit SHA und Exit-Code; realisierte lokale Prozessgrenzen als LOCAL_ONLY kennzeichnen.

## Externe Voraussetzungen – NICHT eigenmächtig ausführen
Zwei oder mehr reale GPU-Hosts, WAN/Regionen/Jitter, Production Secrets, echte Provider, Payment/Payout und produktives Deployment: SKIP/EXTERNAL.

## Definition of Done dieses Agenten-Durchlaufs
- Mindestens einen bestätigten aktiven P0-Fehler durch echten Red/Green-Test plus Source-Fix beseitigen, ODER reproduzierbar dokumentieren, warum kein sicherer Fix ohne externe Voraussetzung möglich ist.
- Für JEDES P0-Kriterium realen Nachweis vs BLOCKED nennen. Nur wirklich erfüllte, geprüfte Teilkriterien grün markieren.
- Zielabstand (funktionale/Security-Messung) vorher/nachher dokumentieren. Nicht einfach „Phase N completed“ behaupten.
- Der Gesamt-P0-Status bleibt offen bis zur vollständigen geforderten Abnahme; fehlende physische Tests bleiben ein eigener operatorseitiger Übergabeschritt.
