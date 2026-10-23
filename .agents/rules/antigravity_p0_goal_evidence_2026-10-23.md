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
1. Sichere bestehende localhost-TCP-Negativ-/Positivtests und ergänze einen Protokoll-Ack-Handshake, der echte Session-/Node-/Request-ID, Timeout und fehlgeleitete Antwort prüft; keine erlogenen FAILOVER_SUCCESS-Labels nach bloßer Socket-Verbindung.
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
