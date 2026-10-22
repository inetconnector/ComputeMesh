# VERBINDLICHER NÄCHSTER JULES-/ANTIGRAVITY-ENTWICKLUNGSPROMPT — ComputeMesh

**Erstellt:** 2026-10-22. **Priorität:** P0 / ZIELERREICHUNG vor neuer Feature-/Phasen-Expansion. **Branch:** main. **Baseline bei Planung (kein Lock):** `4f0768baa55eb1fbc845a99a70c6d1b2d266ab7b`. **Vorhandener offener Korrekturauftrag:** https://github.com/inetconnector/ComputeMesh/issues/113.

## Auftrag an Google Jules oder den Antigravity-Controller

Du bist der verantwortliche Repository-Entwicklungsagent. Dein Auftrag besteht NICHT darin, die nächste nummerierte Architekturphase zu implementieren, sondern den Abstand zum langfristigen Projektziel mit nachprüfbaren Ergebnissen zu verringern. **Projektziel:** Ein tatsächliches KI-Rechennetz, in dem fremde und eigene Rechner/GPU-Provider gemeinsam reale, abgesicherte KI-Aufträge ausführen und verlässlich gemessen/abgerechnet werden.

Dies ist eine dauerhaft gespeicherte Aufgabenbeschreibung, **kein Hinweis auf einen bereits gestarteten Agenten**. Zuerst aktuellen `main` und vorhandene PRs/Issues prüfen, lokales AGENTS.md und tiefere Richtlinien beachten, Nutzeränderungen bewahren. Nie einen unbelegten PASS oder CLOSED-Status erzeugen. Falls die Baseline bereits überholt ist, Befunde am aktuellen HEAD erneut beweisen, nicht alte Schwachstellen ungeprüft als vorhanden behandeln.

## Zwingende Arbeitsreihenfolge (im vorhandenen Repo, ohne Ersatzserver)

1. **Ziel-/Ist-Abgleich:** Lies die kanonischen Projektziel-, Roadmap-, STATE-/NEXT_STEPS-Dateien und diese Anweisung. Schreibe eine knappe, datierte Ziel-Abweichungs-Matrix: Zielkriterium → produktiver Quellcode → unabhängiger Nachweis → Lücke → nächster messbarer Schritt. Trenne implementiert / lokal getestet / physisch demonstriert / unabhängig bestätigt.
2. **P0 zuerst:** Bearbeite offene Findings aus Issue #113 und verifiziere die vorhandenen Vorarbeiten, bevor weitere Features hinzugefügt werden. Für jede bestätigte Lücke zuerst einen roten Negativtest, dann ursächliche Korrektur im tatsächlich aufgerufenen Pfad, dann grüne Regression. Kein bloßes Ändern der Testerwartung.
3. **Konkrete Entwicklungsarbeit, die Jules/Antigravity im Repo erledigen können:**
   1. Wähle EINEN minimalen, kohärenten Echtlastpfad: Gateway → private signierte Placement-Entscheidung → öffentlicher Provider → llama.cpp-Ausführung → verifizierte Evidence → Rückmeldung. Verhindere Abkürzungen über rein interne Mock-Resultate.
   2. Prüfe besonders tatsächliche failover_mesh.connect_to_node/handle_connection_failure-Konnektivität, echte Übertragung gegenüber internem Routingstatus, Idempotenz, Kapazitätsleases, Abbruch, Wiederaufnahme, Duplicate Events und veraltete Providerantworten.
   3. Setze vollständig lokal ausführbare Mehrprozess-Socket-/HTTP-Teststrecken mit echten Prozessen und Schlüsseln auf; simuliere Netzverlust/Out-of-order nur explizit. Messe Latenz, Vollständigkeit, Fehlerquote, Restart-Verlust, akzeptierte Ausführungs-Evidenz.
   4. Vermeide parallele unverbundene Architektur-Härtungs-Phasen, bis eine End-to-End-Wirkung und die aktuelle private/public-Submodul-SHA-Synchronisation belegt sind; Agent-Platform-Release separat kennzeichnen.
4. **Abnahmemessung:** Fester akzeptierter Auftrag mit belegbarer Ergebnis- und Evidence-Kette, reproduzierbare Negativfälle, P50/P95 auf echter lokal vorhandener Technik; SHA-gebundene Pin- und Gateprotokolle. Notiere Testkommando, Exitcode, Umgebung, Git-SHA, Testdaten-/Beleghash, Nullhypothese/Baseline und noch verbleibende Fälle. Self-reported Dokumentations-PASS ohne echten Testlauf gilt nicht.
5. **Integration statt Showcases:** Alle neuen Schutz-/Intelligenzfunktionen müssen in bestehende reale Runtime-/Call-Pfade eingebunden sein. Keine neuen Endlosfolgen aus Part X, K/Y oder M/Z ohne gemessenen Beitrag zum Endziel. Bestehende Regressionen, Berechtigungen und Releasebeschränkungen erhalten.
6. **Review und saubere Übergabe:** Kleine überprüfbare Commits/PRs nach den gültigen Repository-Regeln; Ausgabe: (a) konkrete Code-Diffs und Belegdateien, (b) Verbesserung gegenüber Ausgangsmessung oder ehrlich NEGATIVE, (c) verbleibende Blocker, (d) genau EIN begründeter nächster Schritt. Gleiche AGENTS, README, STATE/NEXT_STEPS und Issue #113 ab. Nur mit vollständig belegter Definition of Done schließen.

## Dateien und vorhandene Vorgaben

Primär: README.md Abschnitte What Works Today / Remaining product-readiness work / Immediate path; PROJECT_STATE.md; services/orchestrator; services/scheduler; services/runtime; PUBLIC_PIN und private ControlPlane Issue #65. Zusätzlicher P0-Plan: `docs/tasks/P0_AUDIT_REMEDIATION_2026-10-21.md`. Niemals bestehende Aufgaben stillschweigend löschen. Prüfe ggf. tatsächliche CI-Verfügbarkeit; Billing-/Runner-Blockade ist weder Test-Fail noch Test-PASS.

## Strikte Infrastrukturgrenze: NICHT auf fremden Servern arbeiten

**Jules/Antigravity können dieses Aufgabenpaket nur für Code, statische Prüfungen, lokal verfügbare Tests, reproduzierbare simulierte Negativfälle, CI-Konfiguration und Dokumentation bearbeiten.** Für Reale Mehr-GPU-Hosts, remote Provider-Registrierung, physisches LAN mit Störungen, WAN über zwei Standorte, live Billing/Stripe und produktive Schlüssel: BLOCKED ohne autorisierte externe Infrastruktur. gilt: **SKIP_PHYSICAL / BLOCKED_EXTERNAL_SERVER_OR_DEVICE**; keine Hosts provisionieren, keinen Cloud-/SSH-/Plesk-/Produktivzugang annehmen, keine echten Zahlungen, keine Schlüssel oder personenbezogenen Daten beschaffen, keine fremden Server starten. Schreibe nötige Host-/Netz-/Geräte-Voraussetzungen und ein präzises späteres Runbook auf. Fehlen Zugriffsrechte oder Runner, nur den machbaren Teil fertigstellen und den Rest mit BLOCKED melden. Nie lokale Simulation als echte Mehrhost-/Geräteleistung ausgeben.

## Erfolg / Stop-Regel

**DONE (nur Code-/Lokalscope):** Befunde am neuesten HEAD reproduziert; relevante aktiven Pfade ursächlich korrigiert; vor- und nachher Tests wirklich ausgeführt; nachvollziehbarer, reproduzierbarer Ziel-Fortschritt; Issue-/Dokumentstatus sachlich konsistent. **BLOCKED:** unabhängig erforderliche physische, klinische, externe Server-/Markt- oder Betreiber-Abnahme. **NO-GO:** unbewiesene Produktiv-, Sicherheits-, Quanten-/KI-Überlegenheits- oder Leistungsbehauptungen. Dieser Auftrag ist bewusst vorgelagert zur nächsten normalen Roadmap-Phase.
