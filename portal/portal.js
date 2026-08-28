/* ComputeMesh compliance wrapper.
 *
 * The historical portal implementation is preserved byte-for-byte as portal-core.js.
 * This wrapper loads it, then applies the production-facing B2B/AI/provider policy
 * without deleting playground, calculator, billing, translation or other UI logic.
 */
(function () {
  'use strict';

  const TERMS_VERSION = '2.1';
  const EEA = [
    ['AT','Austria / Österreich'],['BE','Belgium / Belgien'],['BG','Bulgaria / Bulgarien'],['HR','Croatia / Kroatien'],['CY','Cyprus / Zypern'],
    ['CZ','Czechia / Tschechien'],['DE','Germany / Deutschland'],['DK','Denmark / Dänemark'],['EE','Estonia / Estland'],['ES','Spain / Spanien'],
    ['FI','Finland / Finnland'],['FR','France / Frankreich'],['GR','Greece / Griechenland'],['HU','Hungary / Ungarn'],['IE','Ireland / Irland'],
    ['IS','Iceland / Island'],['IT','Italy / Italien'],['LI','Liechtenstein'],['LT','Lithuania / Litauen'],
    ['LU','Luxembourg / Luxemburg'],['LV','Latvia / Lettland'],['MT','Malta'],['NL','Netherlands / Niederlande'],['NO','Norway / Norwegen'],
    ['PL','Poland / Polen'],['PT','Portugal'],['RO','Romania / Rumänien'],['SE','Sweden / Schweden'],['SI','Slovenia / Slowenien'],['SK','Slovakia / Slowakei']
  ];

  const COMPLIANCE_I18N = {
    en: {
      business: 'I confirm that I register as an <strong>entrepreneur/business user</strong>, not as a consumer.',
      terms: (ver) => `I accept the <a href="/terms" target="_blank" rel="noopener">Terms v${ver}</a>.`,
      privacy: 'I acknowledge the <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.',
      countryLabel: 'Provider operating country (EEA production pool)',
      selectCountry: 'Select EEA country…',
      providerData: 'I accept the provider confidentiality/data-processing obligations: no independent use, extraction or retention of customer workload data.',
      providerLogs: 'I attest that provider systems will not persist or log plaintext prompts or responses and will follow the approved operational security policy.',
      providerPayout: 'Production provider payouts are onboarded separately through the approved payment provider (currently Stripe Connect). Registration does not guarantee node admission, workloads or earnings.',
      consumerRole: 'Use third-party AI models through ComputeMesh infrastructure',
      providerRole: 'Provide EEA compute capacity as a business',
      errBusiness: 'Business status, Terms and Privacy acknowledgement are required.',
      errProvider: 'EEA country and provider data/security obligations are required.',
      registering: 'Registering…',
      registered: 'Account created. Production node admission remains pending operator verification and server-side compliance enrollment.',
      regFailed: 'Registration failed: '
    },
    de: {
      business: 'Ich bestätige meine Registrierung als <strong>Gewerbekunde/Unternehmer (B2B)</strong>, nicht als Verbraucher.',
      terms: (ver) => `Ich akzeptiere die <a href="/terms" target="_blank" rel="noopener">AGB v${ver}</a>.`,
      privacy: 'Ich habe die <a href="/privacy" target="_blank" rel="noopener">Datenschutzerklärung</a> zur Kenntnis genommen.',
      countryLabel: 'Provider-Betriebsland (EWR/EEA-Produktionspool)',
      selectCountry: 'EWR-Land auswählen…',
      providerData: 'Ich akzeptiere die Vertraulichkeits- und Auftragsverarbeitungs-Bedingungen: keine Speicherung, Weitergabe oder Zweckentfremdung von Kundendaten.',
      providerLogs: 'Ich versichere, dass keine Klartext-Prompts oder Antworten protokolliert werden und die Sicherheitsrichtlinien eingehalten werden.',
      providerPayout: 'Auszahlungen für Provider werden separat über den zugelassenen Zahlungsdienstleister (Stripe Connect) abgewickelt. Eine Registrierung garantiert keine automatische Zulassung oder Auslastung.',
      consumerRole: 'KI-Inferenzmodelle über ComputeMesh nutzen (Kunde)',
      providerRole: 'EWR-Rechenleistung als gewerblicher Provider bereitstellen',
      errBusiness: 'Bestätigung als Gewerbekunde, AGB und Datenschutz sind erforderlich.',
      errProvider: 'EWR-Land und Provider-Sicherheitsverpflichtungen sind erforderlich.',
      registering: 'Registrierung läuft…',
      registered: 'Konto erstellt. Die produktive Node-Zulassung erfolgt nach Prüfung und Compliance-Aktivierung.',
      regFailed: 'Registrierung fehlgeschlagen: '
    }
  };

  const PAGE_META_I18N = {
    '/': {
      en: {
        title: 'ComputeMesh — AI compute from idle graphics cards',
        desc: 'ComputeMesh connects idle graphics cards into an AI compute network. Test requests through one gateway, register hardware as a provider, and see what already works today.'
      },
      de: {
        title: 'ComputeMesh — KI-Rechenleistung aus freien Grafikkarten',
        desc: 'ComputeMesh verbindet freie Grafikkarten zu einem KI-Rechennetzwerk. KI-Anfragen über ein Gateway testen, Hardware als Provider registrieren und sehen, was heute schon funktioniert.'
      }
    },
    '/docs': {
      en: {
        title: 'Developer Documentation — ComputeMesh',
        desc: 'Developer-preview documentation for the implemented ComputeMesh gateway, provider and distributed-inference engineering paths.'
      },
      de: {
        title: 'Entwickler-Dokumentation — ComputeMesh',
        desc: 'Developer-Preview-Dokumentation für die implementierten ComputeMesh-Gateway-, Provider- und Distributed-Inference-Engineering-Pfade.'
      }
    },
    '/status': {
      en: {
        title: 'Engineering Status — ComputeMesh',
        desc: 'Current pre-production engineering and validation status for ComputeMesh.'
      },
      de: {
        title: 'Engineering-Status — ComputeMesh',
        desc: 'Aktueller Pre-Production-Engineering- und Validierungsstatus von ComputeMesh.'
      }
    },
    '/benchmarks': {
      en: {
        title: 'Measured Benchmarks — ComputeMesh',
        desc: 'Recorded ComputeMesh engineering benchmark evidence with explicit hardware/runtime scope and measurement limitations.'
      },
      de: {
        title: 'Gemessene Benchmarks — ComputeMesh',
        desc: 'Aufgezeichnete ComputeMesh-Engineering-Benchmark-Evidenz mit explizitem Hardware-/Runtime-Umfang und Messgrenzen.'
      }
    },
    '/contact': {
      en: {
        title: 'Contact & Support — ComputeMesh',
        desc: 'Contact ComputeMesh support for developer API integration, billing, enterprise compute, and hardware provider onboarding.'
      },
      de: {
        title: 'Kontakt & Support — ComputeMesh',
        desc: 'ComputeMesh-Support für Entwickler-API-Integration, Abrechnung, Enterprise-Compute und Hardware-Provider-Onboarding kontaktieren.'
      }
    },
    '/terms': {
      en: {
        title: 'Terms of Service — ComputeMesh',
        desc: 'ComputeMesh B2B Terms of Service and AI-specific risk allocation.'
      },
      de: {
        title: 'Nutzungsbedingungen — ComputeMesh',
        desc: 'ComputeMesh B2B-Nutzungsbedingungen und KI-spezifische Risikoverteilung.'
      }
    },
    '/privacy': {
      en: {
        title: 'Privacy Policy — ComputeMesh',
        desc: 'GDPR privacy information for ComputeMesh.'
      },
      de: {
        title: 'Datenschutzerklärung — ComputeMesh',
        desc: 'DSGVO-Datenschutzhinweise für ComputeMesh.'
      }
    },
    '/impressum': {
      en: {
        title: 'Impressum — ComputeMesh',
        desc: 'Legal notice for ComputeMesh and InetConnector.com.'
      },
      de: {
        title: 'Impressum — ComputeMesh',
        desc: 'Anbieterkennzeichnung für ComputeMesh und InetConnector.com.'
      }
    }
  };

  const STATIC_TEXT_DE = {
    'Engineering Preview': 'Engineering-Vorschau',
    'Docs': 'Docs',
    'Status': 'Status',
    'Benchmarks': 'Benchmarks',
    'Support': 'Support',
    'Legal': 'Rechtliches',
    'Privacy': 'Datenschutz',
    'Terms': 'AGB',
    'Network Status': 'Systemstatus',
    'Register / API Key': 'Registrieren / API-Key',
    'Pre-production distributed inference engineering': 'Viele Grafikkarten. Ein KI-Netzwerk.',
    'Pool heterogeneous compute.': 'KI soll nicht nur in riesigen Rechenzentren laufen.',
    'Measure what actually works.': 'ComputeMesh verbindet freie Grafikkarten.',
    'Many graphics cards. One AI network.': 'Viele Grafikkarten. Ein KI-Netzwerk.',
    'AI should not only run in huge data centers.': 'KI soll nicht nur in riesigen Rechenzentren laufen.',
    'ComputeMesh connects idle graphics cards.': 'ComputeMesh verbindet freie Grafikkarten.',
    'Try the playground': 'Playground testen',
    'Offer hardware': 'Hardware anbieten',
    'Unavailable': 'Nicht verfügbar',
    'Example: Qwen 2.5 7B': 'Beispiel: Qwen 2.5 7B',
    'Example: Llama 3.1 8B': 'Beispiel: Llama 3.1 8B',
    'Example: DeepSeek Coder 6.7B': 'Beispiel: DeepSeek Coder 6.7B',
    'Example: Mistral 7B': 'Beispiel: Mistral 7B',
    'Example: Phi-3 Mini': 'Beispiel: Phi-3 Mini',
    'Clear Chat': 'Chat leeren',
    'Configured third-party model via ComputeMesh': 'Konfiguriertes Drittanbieter-Modell über ComputeMesh',
    'View account/provider options': 'Konto-/Provider-Optionen ansehen',
    'Example: qwen/qwen2.5-7b-instruct': 'Beispiel: qwen/qwen2.5-7b-instruct',
    'Example: qwen/qwen2.5-14b-instruct': 'Beispiel: qwen/qwen2.5-14b-instruct',
    'Example: qwen/qwen2.5-32b-instruct': 'Beispiel: qwen/qwen2.5-32b-instruct',
    'Example: llama/llama-3.1-70b-instruct': 'Beispiel: llama/llama-3.1-70b-instruct',
    'Readiness boundary:': 'Reifegrenze:',
    'TTFT note:': 'TTFT-Hinweis:',
    'a narrow physical two-machine shared-runtime proof and substantial control/gateway foundations exist, but broad LAN/WAN validation, production data-plane security, provider-enforced leases and production key/session hardening remain open. Upstream llama.cpp RPC must not be exposed directly to an untrusted/public network.': 'Ein eng begrenzter physischer Zwei-Maschinen-Shared-Runtime-Beleg und substanzielle Control/Gateway-Grundlagen existieren; breite LAN/WAN-Validierung, Produktions-Dataplane-Sicherheit, provider-erzwungene Leases und Produktions-Key/Session-Härtung bleiben offen. Upstream llama.cpp RPC darf nicht direkt in einem nicht vertrauenswürdigen/öffentlichen Netzwerk exponiert werden.',
    'the current non-streaming measured-feedback path records prefill, decode and end-to-end request duration but does not directly measure true time-to-first-token. This page therefore does not publish invented TTFT values.': 'Der aktuelle nicht-streamende Measured-Feedback-Pfad zeichnet Prefill, Decode und End-to-End-Anfragedauer auf, misst aber nicht direkt echte Time-to-First-Token. Diese Seite veröffentlicht deshalb keine erfundenen TTFT-Werte.',
    'Client Request ➔ Public Gateway / Orchestrator': 'Client-Anfrage ➔ Öffentliches Gateway / Orchestrator',
    '➔ Private Placement Decision (signed)': '➔ Private Placement-Entscheidung (signiert)',
    '➔ Public Executor verifies plan': '➔ Öffentlicher Executor prüft Plan',
    '➔ Coordinator + selected RPC worker (current two-node path)': '➔ Coordinator + ausgewählter RPC-Worker (aktueller Zwei-Knoten-Pfad)',
    '➔ Evidence + Provider Attestations ➔ Verified private feedback': '➔ Evidenz + Provider-Attestierungen ➔ Verifiziertes privates Feedback',
    '8B class': '8B-Klasse',
    '14B class': '14B-Klasse',
    '32B class': '32B-Klasse',
    '70B class': '70B-Klasse',
    '5x 8GB class rig': '5x 8GB-Klasse-Rig',
    '8x 8GB class rig': '8x 8GB-Klasse-Rig',
    'Single RTX 3080 class': 'Einzelne RTX-3080-Klasse',
    'Single RTX 4090 class': 'Einzelne RTX-4090-Klasse',
    'Generated key:': 'Generierter Schlüssel:',
    'Your API Key:': 'Dein API-Key:',
    'Select deposit amount:': 'Einzahlungsbetrag auswählen:',
    'Proceed to configured Checkout →': 'Weiter zum konfigurierten Checkout →',
    'Architecture': 'Architektur',
    'Economics UI': 'Economics UI',
    'API Integration': 'API-Integration',
    'GitHub Repository': 'GitHub-Repository',
    'Technical Docs': 'Technische Docs',
    'Engineering Status': 'Engineering-Status',
    'Measured Benchmarks': 'Gemessene Benchmarks',
    'Terms of Service': 'Nutzungsbedingungen',
    'Privacy Policy': 'Datenschutzerklärung',
    'Back to Home': 'Zurück zur Startseite',
    'Technical status:': 'Technischer Status:',
    'pre-production engineering': 'Pre-Production Engineering',
    'Registering...': 'Registrierung läuft...',
    'Registration failed. Please verify the required confirmations and try again.': 'Registrierung fehlgeschlagen. Bitte prüfe die erforderlichen Bestätigungen und versuche es erneut.',
    'Enter your prompt here...': 'Prompt hier eingeben...',
    'What parts of ComputeMesh are validated today?': 'Welche Teile von ComputeMesh sind heute validiert?',
    'If the configured gateway/model is available, click "Run Inference" to send the request.': 'Wenn Gateway/Modell konfiguriert verfügbar sind, klicke auf "Inferenz starten", um die Anfrage zu senden.',
    'Describe your question or hardware setup...': 'Beschreibe deine Frage oder Hardware-Konfiguration...',
    'I confirm that I act as an entrepreneur/business user (Unternehmer) and not as a consumer.': 'Ich bestätige, dass ich als Unternehmer/Geschäftskunde und nicht als Verbraucher handle.',
    'I have read and expressly accept the': 'Ich habe die',
    '.': '.',
    'I acknowledge the': 'Ich nehme die',
    'and the described processing.': 'und die beschriebene Verarbeitung zur Kenntnis.',
    'This page deliberately does not display placeholder global VRAM, GPU count, uptime or gateway-latency numbers as though they were live. Such metrics should appear only when sourced from an authenticated current registry/telemetry path. Until then, unavailable means unavailable.': 'Diese Seite zeigt bewusst keine Platzhalter für globale VRAM-, GPU-, Uptime- oder Gateway-Latenzwerte als wären sie live. Solche Metriken sollten nur erscheinen, wenn sie aus einem authentifizierten aktuellen Registry-/Telemetriepfad stammen. Bis dahin bedeutet "nicht verfügbar" tatsächlich nicht verfügbar.',
    'Terms of Service — Business Users': 'Nutzungsbedingungen — Geschäftskunden',
    'Effective: 27 August 2026 · Version 2.1 · Current contract text for portal account registration': 'Gültig ab: 27. August 2026 · Version 2.1 · Aktueller Vertragstext für die Portal-Kontoregistrierung',
    '1. Operator, scope and B2B restriction': '1. Betreiber, Geltungsbereich und B2B-Beschränkung',
    'ComputeMesh is operated by Herbert Daniel Frede, trading as InetConnector.com ("Operator"). Commercial account registration, paid API services and provider participation are currently offered only to entrepreneurs/business users (Unternehmer), not consumers (Verbraucher). By registering, you confirm business-user status and authority to bind the represented entity.': 'ComputeMesh wird von Herbert Daniel Frede, handelnd als InetConnector.com ("Betreiber"), betrieben. Kommerzielle Kontoregistrierung, kostenpflichtige API-Dienste und Provider-Teilnahme werden derzeit nur Unternehmern/Geschäftskunden, nicht Verbrauchern, angeboten. Mit der Registrierung bestätigst du deinen Geschäftskundenstatus und die Berechtigung, die vertretene Einheit zu binden.',
    '2. Contract formation and versioned acceptance': '2. Vertragsschluss und versionierte Zustimmung',
    'Portal credentials are issued only after explicit electronic acceptance of these Terms, acknowledgement of the Privacy Policy and confirmation of business-user status. The Service records the accepted Terms version and acceptance timestamp with the account/API-key record. Version 2.1 is required by the current registration endpoint. Material changes to continuing paid terms will be handled in a legally sufficient manner.': 'Portal-Zugangsdaten werden nur nach ausdrücklicher elektronischer Annahme dieser Bedingungen, Kenntnisnahme der Datenschutzerklärung und Bestätigung des Geschäftskundenstatus ausgegeben. Der Dienst speichert die akzeptierte AGB-Version und den Zustimmungszeitpunkt beim Konto/API-Key-Datensatz. Version 2.1 ist für den aktuellen Registrierungsendpunkt erforderlich. Wesentliche Änderungen fortlaufender kostenpflichtiger Bedingungen werden rechtlich ausreichend behandelt.',
    '3. Nature of the Service and AI-output risk': '3. Art des Dienstes und Risiko von KI-Ausgaben',
    'ComputeMesh is an orchestration and compute-infrastructure layer. Inference can be performed by third-party software, models, runtime endpoints and independent compute providers. AI output is probabilistic and may be inaccurate, incomplete, fabricated (hallucinated), biased, offensive, insecure, obsolete, inconsistent or otherwise unsuitable. No output is warranted to be true, complete, lawful, unique, non-infringing, reproducible or fit for a particular purpose. The Service does not provide medical, legal, financial, tax, safety, engineering or other professional advice.': 'ComputeMesh ist eine Orchestrierungs- und Compute-Infrastrukturschicht. Inferenz kann durch Drittanbieter-Software, Modelle, Runtime-Endpunkte und unabhängige Compute-Provider ausgeführt werden. KI-Ausgaben sind probabilistisch und können ungenau, unvollständig, erfunden (halluziniert), voreingenommen, anstößig, unsicher, veraltet, widersprüchlich oder anderweitig ungeeignet sein. Es wird nicht zugesichert, dass Ausgaben wahr, vollständig, rechtmäßig, einzigartig, nicht rechtsverletzend, reproduzierbar oder für einen bestimmten Zweck geeignet sind. Der Dienst erbringt keine medizinische, rechtliche, finanzielle, steuerliche, sicherheitsbezogene, technische oder sonstige fachliche Beratung.',
    '4. Human verification and regulated use': '4. Menschliche Prüfung und regulierte Nutzung',
    'You are responsible for prompts, inputs, configuration, model selection, review, interpretation and downstream use. You must independently verify output before relying on it. Unverified output must not be the sole basis for decisions affecting life, health, physical safety, legal rights, credit, employment, education, essential services or similarly high-impact matters. Production-critical, regulated or safety-critical use requires appropriate legal/technical assessment and, where necessary, a separate written agreement. You remain responsible for your own duties under the EU AI Act, GDPR and sector-specific law; mandatory duties imposed directly on the Operator remain unaffected.': 'Du bist verantwortlich für Prompts, Eingaben, Konfiguration, Modellauswahl, Prüfung, Interpretation und nachgelagerte Nutzung. Du musst Ausgaben unabhängig prüfen, bevor du dich darauf verlässt. Ungeprüfte Ausgaben dürfen nicht alleinige Grundlage für Entscheidungen sein, die Leben, Gesundheit, körperliche Sicherheit, Rechtspositionen, Kredit, Beschäftigung, Bildung, wesentliche Dienste oder ähnlich weitreichende Angelegenheiten betreffen. Produktionskritische, regulierte oder sicherheitskritische Nutzung erfordert eine angemessene rechtliche/technische Bewertung und gegebenenfalls eine gesonderte schriftliche Vereinbarung. Du bleibst für deine eigenen Pflichten nach EU AI Act, DSGVO und sektorspezifischem Recht verantwortlich; zwingende Pflichten des Betreibers bleiben unberührt.',
    '5. Availability, failures and distributed infrastructure': '5. Verfügbarkeit, Ausfälle und verteilte Infrastruktur',
    'Unless an individually agreed written SLA states otherwise, there is no guarantee of uptime, latency, throughput, token rate, TTFT, model or hardware availability, capacity, successful completion, recovery, compatibility or uninterrupted operation. Jobs may fail, time out, be cancelled, retried, reassigned or produce no usable result. Provider machines, networks, drivers, GPUs, model runtimes, hosting, power, DNS, certificates and payment processors may fail or change. Preview, alpha, beta, research or experimental features may be changed or withdrawn.': 'Soweit kein individuell vereinbartes schriftliches SLA etwas anderes regelt, gibt es keine Garantie für Uptime, Latenz, Durchsatz, Tokenrate, TTFT, Modell- oder Hardwareverfügbarkeit, Kapazität, erfolgreichen Abschluss, Wiederherstellung, Kompatibilität oder unterbrechungsfreien Betrieb. Jobs können fehlschlagen, ablaufen, abgebrochen, wiederholt, neu zugewiesen werden oder kein nutzbares Ergebnis erzeugen. Provider-Maschinen, Netzwerke, Treiber, GPUs, Modell-Runtimes, Hosting, Stromversorgung, DNS, Zertifikate und Zahlungsdienstleister können ausfallen oder sich ändern. Preview-, Alpha-, Beta-, Forschungs- oder experimentelle Funktionen können geändert oder zurückgezogen werden.',
    '6. Accounts, credentials and acceptable use': '6. Konten, Zugangsdaten und zulässige Nutzung',
    'You must protect API/provider keys and systems under your control and report compromise. You may not bypass security, metering, rate limits, identity checks, attestations, fraud controls or capacity controls. Unlawful activity, malware, unauthorized access, rights infringement, deceptive impersonation, prohibited AI practices, illegal surveillance, sanctions/export-control evasion and processing without required rights or legal bases are prohibited. The Operator may suspend or refuse workloads for security, abuse, compliance, sanctions or non-payment reasons.': 'Du musst API-/Provider-Keys und Systeme unter deiner Kontrolle schützen und Kompromittierungen melden. Du darfst Sicherheit, Metering, Rate Limits, Identitätsprüfungen, Attestierungen, Fraud-Kontrollen oder Kapazitätskontrollen nicht umgehen. Rechtswidrige Aktivitäten, Malware, unbefugter Zugriff, Rechtsverletzungen, täuschende Identitätsvortäuschung, verbotene KI-Praktiken, illegale Überwachung, Sanktions-/Exportkontrollumgehung und Verarbeitung ohne erforderliche Rechte oder Rechtsgrundlagen sind untersagt. Der Betreiber kann Workloads aus Sicherheits-, Missbrauchs-, Compliance-, Sanktions- oder Nichtzahlungsgründen aussetzen oder ablehnen.',
    '7. Customer content, confidentiality and data processing': '7. Kundeninhalte, Vertraulichkeit und Datenverarbeitung',
    'You retain rights you hold in inputs and grant the Operator the limited rights necessary to transmit, process, route, meter, secure and troubleshoot inputs and outputs. Full prompts/messages may be transmitted to the configured inference runtime and, in distributed execution, workload data or derived execution data may be processed by participating compute resources. You warrant that you possess all necessary rights and lawful bases. Do not submit trade secrets, personal data, special-category data, professional secrets or other highly confidential data unless the deployment, contracts and safeguards are suitable. Where the Operator acts as processor for a business customer, a separate Art. 28 GDPR data-processing agreement may be required.': 'Du behältst Rechte an deinen Eingaben und räumst dem Betreiber die beschränkten Rechte ein, die zur Übertragung, Verarbeitung, Weiterleitung, Messung, Sicherung und Fehlerbehebung von Eingaben und Ausgaben notwendig sind. Vollständige Prompts/Nachrichten können an die konfigurierte Inferenz-Runtime übertragen werden; bei verteilter Ausführung können Workload-Daten oder abgeleitete Ausführungsdaten durch teilnehmende Compute-Ressourcen verarbeitet werden. Du versicherst, über alle erforderlichen Rechte und Rechtsgrundlagen zu verfügen. Übermittle keine Geschäftsgeheimnisse, personenbezogenen Daten, besonderen Kategorien personenbezogener Daten, Berufsgeheimnisse oder sonstigen hochvertraulichen Daten, sofern Deployment, Verträge und Schutzmaßnahmen nicht geeignet sind. Soweit der Betreiber als Auftragsverarbeiter für einen Geschäftskunden handelt, kann eine gesonderte Auftragsverarbeitungsvereinbarung nach Art. 28 DSGVO erforderlich sein.',
    '8. Independent hardware providers': '8. Unabhängige Hardware-Provider',
    'Providers are independent economic operators, not employees or agents. They are responsible for lawful hardware operation, energy, connectivity, taxes, licenses and security. They must not falsify identity, hardware, telemetry, benchmarks, availability, evidence or output, extract customer data, interfere with jobs or circumvent metering/verification. Provider eligibility, workload allocation and earnings are never guaranteed.': 'Provider sind unabhängige wirtschaftliche Betreiber, keine Arbeitnehmer oder Vertreter. Sie sind verantwortlich für rechtmäßigen Hardwarebetrieb, Energie, Konnektivität, Steuern, Lizenzen und Sicherheit. Sie dürfen Identität, Hardware, Telemetrie, Benchmarks, Verfügbarkeit, Evidenz oder Ausgaben nicht fälschen, keine Kundendaten extrahieren, Jobs nicht stören und Metering/Verifikation nicht umgehen. Provider-Eignung, Workload-Zuweisung und Einnahmen werden niemals garantiert.',
    '9. Provider balances and payouts': '9. Provider-Guthaben und Auszahlungen',
    'Provider payable balances arise only from jobs accepted by applicable metering, verification and settlement rules. A displayed balance is an accounting record, not a bank deposit, e-money account or investment. Payout can be delayed or withheld while fraud, duplicate execution, disputes, chargebacks, sanctions, KYC, payment-provider restrictions or reversals are investigated. Payout is subject to cleared customer funds, current thresholds, supported currency, configured payout services, provider eligibility and law. No minimum utilization, income or payout date is guaranteed.': 'Auszahlbare Provider-Guthaben entstehen nur aus Jobs, die nach den geltenden Metering-, Verifikations- und Settlement-Regeln akzeptiert wurden. Ein angezeigtes Guthaben ist ein Buchhaltungsdatensatz, keine Bankeinlage, kein E-Geld-Konto und keine Anlage. Auszahlungen können verzögert oder einbehalten werden, während Betrug, doppelte Ausführung, Streitfälle, Rückbuchungen, Sanktionen, KYC, Zahlungsdienstleisterbeschränkungen oder Rückabwicklungen untersucht werden. Auszahlung setzt freigegebene Kundengelder, aktuelle Schwellen, unterstützte Währung, konfigurierte Auszahlungsdienste, Provider-Eignung und Recht voraus. Mindestnutzung, Einkommen oder Auszahlungstermin werden nicht garantiert.',
    '10. Free and promotional credits': '10. Kostenlose und Werbe-Credits',
    'Free, test, promotional or development credits, including registration credits, are non-cash service allocations. Unless expressly agreed otherwise, they are non-transferable, non-interest-bearing and not redeemable for cash. They may be limited, corrected or withdrawn if issued in error, abused, duplicated, required for security/compliance or when the relevant preview program ends. Promotional customer credits do not by themselves create provider cash-payout obligations.': 'Kostenlose, Test-, Werbe- oder Entwicklungs-Credits einschließlich Registrierungs-Credits sind bargeldlose Dienstzuweisungen. Soweit nicht ausdrücklich anders vereinbart, sind sie nicht übertragbar, unverzinslich und nicht gegen Geld einlösbar. Sie können beschränkt, korrigiert oder zurückgezogen werden, wenn sie irrtümlich ausgegeben, missbraucht oder dupliziert wurden, aus Sicherheits-/Compliance-Gründen erforderlich ist oder das jeweilige Preview-Programm endet. Werbe-Credits von Kunden begründen für sich genommen keine Barauszahlungspflichten gegenüber Providern.',
    '11. Fees, Stripe and taxes': '11. Entgelte, Stripe und Steuern',
    'Actual prices, platform fees, revenue shares and thresholds are those presented by the applicable live quote/order/checkout or individually agreed terms. Website calculators and research comparisons are not binding quotes or income guarantees. Payments may use Stripe Checkout and provider onboarding/payouts may use Stripe Connect, subject to Stripe\'s KYC, fraud, sanctions, reserve, currency and eligibility rules. Each party remains responsible for its own tax obligations.': 'Tatsächliche Preise, Plattformgebühren, Umsatzanteile und Schwellen sind diejenigen, die im jeweiligen Live-Angebot, Auftrag, Checkout oder in individuell vereinbarten Bedingungen dargestellt sind. Webseiten-Rechner und Forschungsvergleiche sind keine verbindlichen Angebote oder Einkommensgarantien. Zahlungen können Stripe Checkout und Provider-Onboarding/-Auszahlungen Stripe Connect nutzen, jeweils vorbehaltlich der KYC-, Betrugs-, Sanktions-, Reserve-, Währungs- und Eignungsregeln von Stripe. Jede Partei bleibt für ihre eigenen Steuerpflichten verantwortlich.',
    '12. No warranties': '12. Keine Gewährleistungen',
    'Except for individually agreed characteristics and to the maximum extent permitted by law, the Operator gives no warranty or guarantee concerning AI-output accuracy or quality, fitness for purpose, non-infringement, uninterrupted availability, economic results, security against every attack, provider conduct, third-party services or continuing compatibility with hardware, drivers, SDKs, models or upstream projects.': 'Außer für individuell vereinbarte Beschaffenheiten und im gesetzlich größtmöglichen Umfang übernimmt der Betreiber keine Gewährleistung oder Garantie für Genauigkeit oder Qualität von KI-Ausgaben, Zweckgeeignetheit, Nichtverletzung von Rechten, unterbrechungsfreie Verfügbarkeit, wirtschaftliche Ergebnisse, Sicherheit gegen jeden Angriff, Provider-Verhalten, Drittanbieterdienste oder fortlaufende Kompatibilität mit Hardware, Treibern, SDKs, Modellen oder Upstream-Projekten.',
    '13. Limitation of liability': '13. Haftungsbeschränkung',
    'Nothing excludes or limits liability where prohibited by law. Liability remains unlimited for intent, gross negligence, culpable injury to life/body/health, mandatory product-liability law, fraudulently concealed defects and expressly assumed guarantees.': 'Nichts schließt oder beschränkt Haftung, soweit dies gesetzlich verboten ist. Unbeschränkte Haftung besteht für Vorsatz, grobe Fahrlässigkeit, schuldhafte Verletzung von Leben/Körper/Gesundheit, zwingendes Produkthaftungsrecht, arglistig verschwiegene Mängel und ausdrücklich übernommene Garantien.',
    'For ordinary negligence, the Operator is liable only for breach of a material contractual obligation (Kardinalpflicht), and then only for foreseeable damage typical for this type of contract. To the extent legally permissible in B2B transactions, aggregate liability for ordinary negligence is limited to the net fees paid by the affected customer for the affected Service during the twelve months preceding the event.': 'Bei einfacher Fahrlässigkeit haftet der Betreiber nur bei Verletzung einer wesentlichen Vertragspflicht (Kardinalpflicht), und dann nur für den vertragstypischen, vorhersehbaren Schaden. Soweit in B2B-Geschäften rechtlich zulässig, ist die Gesamthaftung für einfache Fahrlässigkeit auf die Nettoentgelte begrenzt, die der betroffene Kunde für den betroffenen Dienst in den zwölf Monaten vor dem Ereignis gezahlt hat.',
    'Subject to those mandatory carve-outs, the Operator is not liable for indirect or consequential loss, lost profit, revenue, business opportunity, anticipated savings, goodwill or data, nor for losses caused by reliance on unverified AI output, customer prompts/configuration, independent-provider misconduct, third-party models/services, external networks, power failure, force majeure or unauthorized use outside the Operator\'s reasonable control.': 'Vorbehaltlich dieser zwingenden Ausnahmen haftet der Betreiber nicht für indirekte Schäden oder Folgeschäden, entgangenen Gewinn, Umsatz, Geschäftschancen, erwartete Einsparungen, Goodwill oder Daten sowie nicht für Schäden durch Vertrauen auf ungeprüfte KI-Ausgaben, Kundenprompts/-konfiguration, Fehlverhalten unabhängiger Provider, Drittanbieter-Modelle/-Dienste, externe Netzwerke, Stromausfall, höhere Gewalt oder unbefugte Nutzung außerhalb zumutbarer Kontrolle des Betreibers.',
    '14. Business-user indemnification': '14. Freistellung durch Geschäftskunden',
    'To the extent permitted by law, a business user shall indemnify the Operator against third-party claims and reasonable legal-defense costs arising from the user\'s unlawful input/use, infringement of third-party rights, privacy/AI-regulatory violations attributable to the user, or deployment/publication of output, except to the extent caused by the Operator\'s own legally attributable breach. Mandatory duties imposed directly on the Operator are not shifted by this clause.': 'Soweit gesetzlich zulässig, stellt ein Geschäftskunde den Betreiber von Ansprüchen Dritter und angemessenen Rechtsverteidigungskosten frei, die aus rechtswidrigen Eingaben/Nutzungen des Nutzers, Verletzung von Rechten Dritter, dem Nutzer zurechenbaren Datenschutz-/KI-Regulierungsverstößen oder Deployment/Veröffentlichung von Ausgaben entstehen, außer soweit sie durch eine dem Betreiber rechtlich zurechenbare Pflichtverletzung verursacht wurden. Dem Betreiber unmittelbar auferlegte zwingende Pflichten werden durch diese Klausel nicht verschoben.',
    '15. Open source, suspension and changes': '15. Open Source, Sperrung und Änderungen',
    'Open-source components remain subject to their licenses. Public source availability grants no rights in private control-plane code, confidential data or trademarks beyond applicable licenses. The Operator may suspend access for security, abuse prevention, compliance, sanctions, maintenance or non-payment. Accrued rights and mandatory retention/accounting duties survive where applicable.': 'Open-Source-Komponenten unterliegen weiterhin ihren jeweiligen Lizenzen. Öffentliche Quellverfügbarkeit gewährt über anwendbare Lizenzen hinaus keine Rechte an privatem Control-Plane-Code, vertraulichen Daten oder Marken. Der Betreiber kann Zugriff aus Sicherheits-, Missbrauchspräventions-, Compliance-, Sanktions-, Wartungs- oder Nichtzahlungsgründen aussetzen. Entstandene Rechte und zwingende Aufbewahrungs-/Buchhaltungspflichten bleiben, soweit anwendbar, bestehen.',
    '16. Governing law, venue and severability': '16. Anwendbares Recht, Gerichtsstand und Salvatorisches',
    'German law applies, excluding the CISG, to the extent legally effective. For merchants, legal persons under public law and special funds under public law, the Operator\'s place of business is the agreed venue where permitted. Mandatory venues remain unaffected. Individually negotiated terms prevail over these Terms. If a provision is invalid, statutory rules apply in its place.': 'Es gilt deutsches Recht unter Ausschluss des UN-Kaufrechts, soweit rechtlich wirksam. Für Kaufleute, juristische Personen des öffentlichen Rechts und öffentlich-rechtliche Sondervermögen ist der Geschäftssitz des Betreibers der vereinbarte Gerichtsstand, soweit zulässig. Zwingende Gerichtsstände bleiben unberührt. Individuell ausgehandelte Bedingungen gehen diesen Bedingungen vor. Ist eine Bestimmung unwirksam, gelten an ihrer Stelle die gesetzlichen Regeln.',
    '17. Evidence and contact': '17. Nachweise und Kontakt',
    'Electronic records of Terms version, acceptance time, account identifiers, payment/settlement records and security events may be retained to evidence contract formation, performance, abuse prevention and legal claims in accordance with the Privacy Policy and applicable law. Contact details are in the': 'Elektronische Aufzeichnungen zu AGB-Version, Zustimmungszeitpunkt, Konto-Identifikatoren, Zahlungs-/Settlement-Datensätzen und Sicherheitsereignissen können zum Nachweis von Vertragsschluss, Leistungserbringung, Missbrauchsprävention und Rechtsansprüchen gemäß Datenschutzerklärung und anwendbarem Recht aufbewahrt werden. Kontaktdaten stehen im',
    '; privacy information is in the': '; Datenschutzinformationen stehen in der',
    'Privacy Policy / Datenschutzhinweise': 'Datenschutzerklärung',
    'Effective: 27 August 2026 · Version 2.1 · This notice must remain synchronized with the deployed system and processor contracts.': 'Gültig ab: 27. August 2026 · Version 2.1 · Diese Hinweise müssen mit dem deployten System und den Auftragsverarbeiterverträgen synchron bleiben.',
    '1. Controller': '1. Verantwortlicher',
    'Controller (Verantwortlicher): Herbert Daniel Frede, InetConnector.com, Bismarckstraße 6, 97209 Veitshöchheim, Germany. Email: privacy@inetconnector.com. Further contact details are in the': 'Verantwortlicher: Herbert Daniel Frede, InetConnector.com, Bismarckstraße 6, 97209 Veitshöchheim, Deutschland. E-Mail: privacy@inetconnector.com. Weitere Kontaktdaten stehen im',
    '. This is the privacy contact address and is not represented as a formally appointed Data Protection Officer unless such an appointment is separately published.': '. Dies ist die Datenschutz-Kontaktadresse und wird nicht als förmlich bestellter Datenschutzbeauftragter dargestellt, sofern eine solche Bestellung nicht gesondert veröffentlicht wird.',
    '2. Data categories actually used by the current codebase': '2. Vom aktuellen Codebestand tatsächlich genutzte Datenkategorien',
    'Depending on use, ComputeMesh may process account/contact data such as email address; API/account identifiers and credential metadata; Terms/privacy acceptance version and timestamp; IP address and request/security metadata for rate limiting and abuse prevention; provider node identifiers, public cryptographic identifiers, hardware inventory, runtime/benchmark/availability telemetry and verification evidence; optional provider payout wallet metadata; billing, Stripe Checkout/Connect identifiers, webhook and settlement metadata; support communications; and prompts/messages plus generated responses to the extent required to perform inference.': 'Je nach Nutzung kann ComputeMesh Konto-/Kontaktdaten wie E-Mail-Adresse, API-/Konto-Identifikatoren und Zugangsdaten-Metadaten, AGB-/Datenschutz-Zustimmungsversion und Zeitstempel, IP-Adresse und Anfrage-/Sicherheitsmetadaten für Rate-Limiting und Missbrauchsprävention, Provider-Node-Identifikatoren, öffentliche kryptografische Identifikatoren, Hardware-Inventar, Runtime-/Benchmark-/Verfügbarkeitstelemetrie und Verifikationsevidenz, optionale Provider-Auszahlungswallet-Metadaten, Billing-, Stripe-Checkout/Connect-Identifikatoren, Webhook- und Settlement-Metadaten, Support-Kommunikation sowie Prompts/Nachrichten und generierte Antworten verarbeiten, soweit dies zur Durchführung der Inferenz erforderlich ist.',
    '3. Purposes and legal bases': '3. Zwecke und Rechtsgrundlagen',
    'Data is processed to provide/administer accounts and the Service, route and execute workloads, verify provider execution, meter/bill customers and settle providers, provide support, prevent abuse/fraud, secure the network, comply with legal/accounting obligations and establish or defend legal claims. Depending on the activity the legal basis is Art. 6(1)(b) GDPR, Art. 6(1)(c) GDPR, Art. 6(1)(f) GDPR or Art. 6(1)(a) GDPR where consent is actually required. Contract/privacy acknowledgement at registration is not used to convert processing that requires another legal basis into consent.': 'Daten werden verarbeitet, um Konten und den Dienst bereitzustellen/zu verwalten, Workloads zu routen und auszuführen, Provider-Ausführung zu verifizieren, Kunden zu messen/abzurechnen und Provider abzurechnen, Support zu leisten, Missbrauch/Betrug zu verhindern, das Netzwerk zu sichern, rechtliche/Buchhaltungspflichten zu erfüllen und Rechtsansprüche zu begründen oder zu verteidigen. Je nach Tätigkeit ist Rechtsgrundlage Art. 6 Abs. 1 lit. b DSGVO, Art. 6 Abs. 1 lit. c DSGVO, Art. 6 Abs. 1 lit. f DSGVO oder Art. 6 Abs. 1 lit. a DSGVO, soweit Einwilligung tatsächlich erforderlich ist. Vertrags-/Datenschutzbestätigung bei Registrierung wird nicht genutzt, um Verarbeitung, die eine andere Rechtsgrundlage benötigt, in Einwilligung umzudeuten.',
    '4. Controller/processor roles and business-customer content': '4. Rollen als Verantwortlicher/Auftragsverarbeiter und Geschäftskundeninhalte',
    'For account administration, billing, security and platform-operation data, the Operator may act as controller. Where ComputeMesh processes inference content solely on documented instructions of a business customer, the Operator may act as processor and an Art. 28 GDPR data-processing agreement (DPA/AVV) is required before production processing of personal data. Customers remain responsible for determining their own lawful basis and transparency duties. Subprocessors used for processor activities must be contractually bound consistently with Art. 28 GDPR.': 'Für Konto-Verwaltung, Abrechnung, Sicherheit und Plattformbetriebsdaten kann der Betreiber als Verantwortlicher handeln. Soweit ComputeMesh Inferenzinhalte ausschließlich nach dokumentierten Weisungen eines Geschäftskunden verarbeitet, kann der Betreiber als Auftragsverarbeiter handeln; vor produktiver Verarbeitung personenbezogener Daten ist eine Vereinbarung zur Auftragsverarbeitung nach Art. 28 DSGVO (DPA/AVV) erforderlich. Kunden bleiben für ihre eigene Rechtsgrundlage und Transparenzpflichten verantwortlich. Unterauftragsverarbeiter müssen für Auftragsverarbeitertätigkeiten vertragsgemäß nach Art. 28 DSGVO gebunden werden.',
    '5. AI prompts and outputs': '5. KI-Prompts und Ausgaben',
    'ComputeMesh is designed to minimize persistent storage of prompt/output content in the inference path, but it does not promise an absolute "zero log" condition. Full prompts/messages can be transmitted to the configured inference runtime and distributed compute resources required to perform the request. Metadata, evidence and error/security data may be retained. Content is not represented as being used for model training unless separately disclosed. Do not submit special-category data, professional secrets, credentials, trade secrets or other highly confidential data unless the deployment, DPA, access controls and legal basis are appropriate.': 'ComputeMesh ist darauf ausgelegt, dauerhafte Speicherung von Prompt-/Output-Inhalten im Inferenzpfad zu minimieren, verspricht aber keinen absoluten "Zero Log"-Zustand. Vollständige Prompts/Nachrichten können an die konfigurierte Inferenz-Runtime und an verteilte Compute-Ressourcen übertragen werden, die zur Ausführung der Anfrage erforderlich sind. Metadaten, Evidenz sowie Fehler-/Sicherheitsdaten können aufbewahrt werden. Inhalte werden nicht als für Modelltraining verwendet dargestellt, sofern dies nicht gesondert offengelegt ist. Übermittle keine besonderen Kategorien personenbezogener Daten, Berufsgeheimnisse, Zugangsdaten, Geschäftsgeheimnisse oder sonstigen hochvertraulichen Daten, sofern Deployment, AVV, Zugriffskontrollen und Rechtsgrundlage nicht geeignet sind.',
    '6. Distributed providers and recipients': '6. Verteilte Provider und Empfänger',
    'Where necessary, data may be processed by hosting/infrastructure providers, payment providers, support/communications providers, professional advisers and authorities where legally required. Distributed compute providers may technically process workload data required for assigned jobs. Provider access is intended to be restricted through identity, control-plane and evidence mechanisms, but no distributed system eliminates every confidentiality or security risk. Business customers must select an appropriate deployment and provider/data-residency policy for their use case.': 'Soweit erforderlich, können Daten durch Hosting-/Infrastrukturprovider, Zahlungsdienstleister, Support-/Kommunikationsdienstleister, professionelle Berater und gesetzlich zuständige Behörden verarbeitet werden. Verteilte Compute-Provider können technisch Workload-Daten verarbeiten, die für zugewiesene Jobs erforderlich sind. Provider-Zugriff soll durch Identitäts-, Control-Plane- und Evidenzmechanismen beschränkt werden, aber kein verteiltes System eliminiert jedes Vertraulichkeits- oder Sicherheitsrisiko. Geschäftskunden müssen ein für ihren Anwendungsfall geeignetes Deployment und eine passende Provider-/Datenresidenz-Richtlinie wählen.',
    '7. Payments and Stripe': '7. Zahlungen und Stripe',
    'Customer payments may be processed through Stripe Checkout and provider onboarding/payouts through Stripe Connect where configured. ComputeMesh stores or reconciles identifiers and metadata such as checkout/session, customer, payment-intent, connected-account, webhook-event, transfer and settlement records. Hosted payment interfaces are intended to prevent ComputeMesh from receiving raw card credentials. Stripe may process payment, KYC, sanctions and anti-fraud data under its applicable roles and privacy information. Billing/accounting records are retained where required by tax, commercial or accounting law.': 'Kundenzahlungen können, soweit konfiguriert, über Stripe Checkout und Provider-Onboarding/-Auszahlungen über Stripe Connect verarbeitet werden. ComputeMesh speichert oder gleicht Identifikatoren und Metadaten wie Checkout-/Session-, Customer-, Payment-Intent-, Connected-Account-, Webhook-Event-, Transfer- und Settlement-Datensätze ab. Gehostete Zahlungsoberflächen sollen verhindern, dass ComputeMesh rohe Kartendaten erhält. Stripe kann Zahlungs-, KYC-, Sanktions- und Betrugspräventionsdaten gemäß seinen jeweiligen Rollen und Datenschutzhinweisen verarbeiten. Abrechnungs-/Buchhaltungsdaten werden aufbewahrt, soweit Steuer-, Handels- oder Buchhaltungsrecht dies verlangt.',
    '8. Provider identity, telemetry and payout data': '8. Provider-Identität, Telemetrie und Auszahlungsdaten',
    'For hardware providers ComputeMesh may process node identity, public keys, IP/network metadata, hardware characteristics, runtime build information, benchmarks, availability/heartbeat telemetry, assigned-job and verification evidence, earnings, settlement status and payout destination metadata. Provider private keys are intended to remain on the provider device. Providers are responsible for safeguarding keys.': 'Für Hardware-Provider kann ComputeMesh Node-Identität, öffentliche Schlüssel, IP-/Netzwerkmetadaten, Hardwareeigenschaften, Runtime-Build-Informationen, Benchmarks, Verfügbarkeits-/Heartbeat-Telemetrie, zugewiesene Jobs und Verifikationsevidenz, Einnahmen, Settlement-Status und Auszahlungsziel-Metadaten verarbeiten. Private Provider-Schlüssel sollen auf dem Provider-Gerät verbleiben. Provider sind für den Schutz ihrer Schlüssel verantwortlich.',
    '9. Browser storage, cookies and TDDDG': '9. Browser-Speicher, Cookies und TDDDG',
    'The current portal client stores the selected language preference in browser': 'Der aktuelle Portal-Client speichert die ausgewählte Spracheinstellung im Browser',
    'under': 'unter',
    'This preference is used to provide the expressly requested language behavior and is treated as technically necessary functionality. The current audited portal does not require advertising or behavioral-tracking cookies for core operation. Non-essential analytics, advertising pixels, fingerprinting or comparable access to terminal-device information must not be enabled without a legally valid consent mechanism and updated disclosure where § 25 TDDDG or GDPR requires consent.': 'Diese Einstellung wird verwendet, um das ausdrücklich gewünschte Sprachverhalten bereitzustellen, und wird als technisch notwendige Funktion behandelt. Das aktuell geprüfte Portal benötigt für den Kernbetrieb keine Werbe- oder Verhaltens-Tracking-Cookies. Nicht notwendige Analytics, Werbepixel, Fingerprinting oder vergleichbarer Zugriff auf Endgeräteinformationen dürfen nicht ohne rechtlich gültigen Einwilligungsmechanismus und aktualisierte Hinweise aktiviert werden, soweit § 25 TDDDG oder DSGVO eine Einwilligung verlangen.',
    '10. Server/security logs and IP addresses': '10. Server-/Sicherheitslogs und IP-Adressen',
    'IP addresses and request/security information may be processed for rate limiting, security, troubleshooting, abuse/fraud prevention and legal defense. Application-level logging may differ by deployed reverse proxy, hosting environment and security tooling. No blanket promise is made that every infrastructure component is log-free. Production operators must document actual log sources and configure proportionate retention.': 'IP-Adressen und Anfrage-/Sicherheitsinformationen können für Rate-Limiting, Sicherheit, Fehlerbehebung, Missbrauchs-/Betrugsprävention und Rechtsverteidigung verarbeitet werden. Application-Level-Logging kann je nach deploytem Reverse Proxy, Hosting-Umgebung und Security-Tooling abweichen. Es wird nicht pauschal zugesagt, dass jede Infrastrukturkomponente logfrei ist. Produktionsbetreiber müssen tatsächliche Logquellen dokumentieren und verhältnismäßige Aufbewahrung konfigurieren.',
    '11. Retention and deletion': '11. Aufbewahrung und Löschung',
    'Personal data is retained only as long as necessary for the relevant purpose and thereafter only where statutory retention or legal-claim requirements apply. Account and Terms-acceptance evidence may be retained for the contractual relationship and applicable limitation periods; billing/accounting and payment records for statutory commercial/tax periods; security/rate-limit data for a proportionate operational/security period; provider telemetry/evidence for verification, fraud handling and settlement; support/legal records as necessary. Production deployments must maintain a documented retention schedule and deletion process; legal holds override routine deletion only to the extent necessary.': 'Personenbezogene Daten werden nur so lange aufbewahrt, wie es für den jeweiligen Zweck erforderlich ist, und danach nur, soweit gesetzliche Aufbewahrungs- oder Rechtsanspruchserfordernisse gelten. Konto- und AGB-Zustimmungsnachweise können für die Vertragsbeziehung und anwendbare Verjährungsfristen aufbewahrt werden; Abrechnungs-/Buchhaltungs- und Zahlungsdaten für gesetzliche handels-/steuerrechtliche Fristen; Sicherheits-/Rate-Limit-Daten für einen verhältnismäßigen Betriebs-/Sicherheitszeitraum; Provider-Telemetrie/Evidenz für Verifikation, Betrugsbearbeitung und Settlement; Support-/Rechtsunterlagen soweit erforderlich. Produktionsdeployments müssen einen dokumentierten Aufbewahrungsplan und Löschprozess pflegen; Legal Holds übersteuern Routinelöschung nur soweit erforderlich.',
    '12. International transfers': '12. Internationale Übermittlungen',
    'Some processors or subprocessors may process data outside the EEA. Where Chapter V GDPR applies, transfers must rely on a valid adequacy decision, approved Standard Contractual Clauses or another lawful mechanism, supplemented by additional safeguards where required. The actual production subprocessor list and transfer mechanism must be maintained and made available as legally required.': 'Einige Auftragsverarbeiter oder Unterauftragsverarbeiter können Daten außerhalb des EWR verarbeiten. Soweit Kapitel V DSGVO gilt, müssen Übermittlungen auf einem gültigen Angemessenheitsbeschluss, genehmigten Standardvertragsklauseln oder einem anderen rechtmäßigen Mechanismus beruhen, ergänzt durch zusätzliche Schutzmaßnahmen, soweit erforderlich. Die tatsächliche Produktionsliste der Unterauftragsverarbeiter und der Übermittlungsmechanismus müssen gepflegt und rechtlich erforderlich bereitgestellt werden.',
    '13. Security measures': '13. Sicherheitsmaßnahmen',
    'ComputeMesh uses or is designed to use measures appropriate to risk, including authenticated transport, access control, cryptographic identities, encryption for selected sensitive metadata, key isolation, rate limiting, network restrictions, audit/evidence records, backup/recovery controls and security testing. No Internet or distributed-compute system is completely secure. The Operator and processors must maintain, review and test technical and organizational measures consistent with Art. 32 GDPR.': 'ComputeMesh nutzt oder ist darauf ausgelegt, risikogerechte Maßnahmen einzusetzen, darunter authentifizierter Transport, Zugriffskontrolle, kryptografische Identitäten, Verschlüsselung ausgewählter sensibler Metadaten, Schlüsselisolierung, Rate Limiting, Netzwerkbeschränkungen, Audit-/Evidenzaufzeichnungen, Backup-/Recovery-Kontrollen und Sicherheitstests. Kein Internet- oder Distributed-Compute-System ist vollständig sicher. Betreiber und Auftragsverarbeiter müssen technische und organisatorische Maßnahmen gemäß Art. 32 DSGVO pflegen, prüfen und testen.',
    '14. Data-subject rights': '14. Betroffenenrechte',
    'Subject to statutory requirements, individuals may have rights of access (Art. 15), rectification (Art. 16), erasure (Art. 17), restriction (Art. 18), data portability (Art. 20), objection (Art. 21) and withdrawal of consent with future effect (Art. 7(3)). Requests may be sent to privacy@inetconnector.com. Identity verification may be required where necessary. You also have the right to lodge a complaint with the competent data-protection supervisory authority.': 'Vorbehaltlich gesetzlicher Voraussetzungen können Personen Rechte auf Auskunft (Art. 15), Berichtigung (Art. 16), Löschung (Art. 17), Einschränkung (Art. 18), Datenübertragbarkeit (Art. 20), Widerspruch (Art. 21) und Widerruf einer Einwilligung mit Wirkung für die Zukunft (Art. 7 Abs. 3) haben. Anfragen können an privacy@inetconnector.com gesendet werden. Eine Identitätsprüfung kann, soweit erforderlich, verlangt werden. Außerdem besteht das Recht, Beschwerde bei der zuständigen Datenschutzaufsichtsbehörde einzulegen.',
    '15. Automated decision-making': '15. Automatisierte Entscheidungsfindung',
    'Inference produces automated AI output. The Operator does not intend its own account administration to make solely automated decisions producing legal or similarly significant effects within Art. 22 GDPR unless separately disclosed and lawfully implemented. Customers using ComputeMesh output in their own decision systems must assess their own GDPR and AI Act obligations.': 'Inferenz erzeugt automatisierte KI-Ausgaben. Der Betreiber beabsichtigt nicht, in der eigenen Kontoverwaltung ausschließlich automatisierte Entscheidungen mit rechtlicher oder ähnlich erheblicher Wirkung im Sinne von Art. 22 DSGVO zu treffen, sofern dies nicht gesondert offengelegt und rechtmäßig implementiert wird. Kunden, die ComputeMesh-Ausgaben in eigenen Entscheidungssystemen nutzen, müssen ihre eigenen DSGVO- und AI-Act-Pflichten prüfen.',
    '16. Accountability and records': '16. Rechenschaftspflicht und Dokumentation',
    'Before commercial production processing of personal data, the Operator must keep the applicable record of processing activities, processor/subprocessor register, DPAs, transfer safeguards, retention schedule, incident/breach procedures and technical-organizational-measures documentation aligned with the deployed system. A data-protection impact assessment must be performed where Art. 35 GDPR requires one because processing is likely to result in a high risk to individuals.': 'Vor kommerzieller produktiver Verarbeitung personenbezogener Daten muss der Betreiber Verzeichnis von Verarbeitungstätigkeiten, Auftragsverarbeiter-/Unterauftragsverarbeiterregister, AVVs, Übermittlungsschutzmaßnahmen, Aufbewahrungsplan, Incident-/Breach-Prozesse und Dokumentation technischer und organisatorischer Maßnahmen mit dem deployten System abgleichen und pflegen. Eine Datenschutz-Folgenabschätzung ist durchzuführen, soweit Art. 35 DSGVO sie verlangt, weil die Verarbeitung voraussichtlich ein hohes Risiko für Personen zur Folge hat.',
    '17. Changes': '17. Änderungen',
    'This notice may be updated when processing, law, providers or architecture changes. Material changes will be published appropriately. The deployed code/configuration, processing records, contracts and this notice must be reviewed together after material changes.': 'Diese Hinweise können aktualisiert werden, wenn sich Verarbeitung, Recht, Provider oder Architektur ändern. Wesentliche Änderungen werden angemessen veröffentlicht. Deployter Code/Konfiguration, Verarbeitungsdokumentation, Verträge und diese Hinweise müssen nach wesentlichen Änderungen gemeinsam geprüft werden.'
  };

  const STATIC_TEXT_EN = Object.fromEntries(Object.entries(STATIC_TEXT_DE).map(([en, de]) => [de, en]));

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function plainText(html) {
    const node = document.createElement('div');
    node.innerHTML = html;
    return normalizeText(node.textContent || '');
  }

  function getStaticMap(lang) {
    const map = new Map();
    const translations = window.portalTranslations || {};
    if (translations.en && translations.de) {
      Object.keys(translations.en).forEach((key) => {
        if (translations.de[key] == null) return;
        const from = plainText(translations[lang === 'de' ? 'en' : 'de'][key]);
        const to = plainText(translations[lang][key]);
        if (from && to && from !== to) map.set(from, to);
      });
    }
    const extra = lang === 'de' ? STATIC_TEXT_DE : STATIC_TEXT_EN;
    Object.entries(extra).forEach(([from, to]) => map.set(normalizeText(from), to));
    return map;
  }

  function translateTextNodes(root, lang) {
    const map = getStaticMap(lang);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        if (parent.closest('script, style, pre, code, textarea, input')) return NodeFilter.FILTER_REJECT;
        return normalizeText(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      const normalized = normalizeText(node.nodeValue);
      const translated = map.get(normalized);
      if (!translated || translated === normalized) return;
      const leading = (node.nodeValue.match(/^\s*/) || [''])[0];
      const trailing = (node.nodeValue.match(/\s*$/) || [''])[0];
      node.nodeValue = `${leading}${translated}${trailing}`;
    });
  }

  function syncPortalMetadata(lang) {
    const path = window.location.pathname.replace(/\/$/, '') || '/';
    const meta = PAGE_META_I18N[path]?.[lang];
    if (!meta) return;
    document.title = meta.title;
    const selectors = [
      'meta[name="description"]',
      'meta[property="og:description"]',
      'meta[name="twitter:description"]'
    ];
    selectors.forEach((selector) => {
      const node = document.querySelector(selector);
      if (node) node.setAttribute('content', meta.desc);
    });
    document.querySelector('meta[property="og:title"]')?.setAttribute('content', meta.title);
    document.querySelector('meta[name="twitter:title"]')?.setAttribute('content', meta.title);
    const ld = document.querySelector('script[type="application/ld+json"]');
    if (ld) {
      try {
        const data = JSON.parse(ld.textContent || '{}');
        data.description = meta.desc;
        ld.textContent = JSON.stringify(data);
      } catch (e) {}
    }
  }

  function translateStaticAttributes(lang) {
    const map = getStaticMap(lang);
    document.querySelectorAll('[placeholder], [title]').forEach((node) => {
      ['placeholder', 'title'].forEach((attr) => {
        if (!node.hasAttribute(attr)) return;
        const translated = map.get(normalizeText(node.getAttribute(attr)));
        if (translated) node.setAttribute(attr, translated);
      });
    });
  }

  function translateFormValues(lang) {
    const map = getStaticMap(lang);
    document.querySelectorAll('textarea').forEach((node) => {
      const translated = map.get(normalizeText(node.value));
      if (translated) node.value = translated;
    });
    const output = document.getElementById('playground-output');
    if (output) {
      const translated = map.get(normalizeText(output.textContent));
      if (translated) output.textContent = translated;
    }
  }

  function syncPortalStaticLanguage(lang) {
    const l = (lang === 'de' || lang === 'en') ? lang : getLang();
    syncPortalMetadata(l);
    translateTextNodes(document.body, l);
    translateStaticAttributes(l);
    translateFormValues(l);
  }
  window.syncPortalStaticLanguage = syncPortalStaticLanguage;

  function getLang() {
    return (window.currentLang === 'de' || localStorage.getItem('cm_portal_lang') === 'de') ? 'de' : 'en';
  }

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === 'class') node.className = value;
      else if (key === 'for') node.htmlFor = value;
      else if (key === 'checked') node.checked = Boolean(value);
      else node.setAttribute(key, value);
    });
    if (text != null) node.textContent = text;
    return node;
  }

  function addCheckbox(container, id, htmlText) {
    const row = el('label', { class: 'compliance-check', for: id });
    const input = el('input', { id, type: 'checkbox' });
    const span = el('span');
    span.innerHTML = htmlText;
    row.append(input, span);
    container.appendChild(row);
  }

  function syncComplianceLanguage(lang) {
    const l = (lang === 'de' || lang === 'en') ? lang : getLang();
    const t = COMPLIANCE_I18N[l];

    const spanBiz = document.querySelector('label[for="cm-business-user"] span');
    if (spanBiz) spanBiz.innerHTML = t.business;
    const spanTerms = document.querySelector('label[for="cm-terms"] span');
    if (spanTerms) spanTerms.innerHTML = t.terms(TERMS_VERSION);
    const spanPriv = document.querySelector('label[for="cm-privacy"] span');
    if (spanPriv) spanPriv.innerHTML = t.privacy;

    const countryLabel = document.querySelector('label[for="cm-provider-country"]');
    if (countryLabel) countryLabel.textContent = t.countryLabel;
    const countryFirstOpt = document.querySelector('#cm-provider-country option[value=""]');
    if (countryFirstOpt) countryFirstOpt.textContent = t.selectCountry;

    const spanData = document.querySelector('label[for="cm-provider-data-terms"] span');
    if (spanData) spanData.innerHTML = t.providerData;
    const spanLogs = document.querySelector('label[for="cm-provider-no-logs"] span');
    if (spanLogs) spanLogs.innerHTML = t.providerLogs;

    const payoutP = document.querySelector('#cm-provider-compliance p');
    if (payoutP) payoutP.textContent = t.providerPayout;

    const role = document.getElementById('modal-role');
    if (role) {
      const consumerOption = role.querySelector('option[value="consumer"]');
      const providerOption = role.querySelector('option[value="provider"]');
      if (consumerOption) consumerOption.textContent = t.consumerRole;
      if (providerOption) providerOption.textContent = t.providerRole;
    }
  }
  window.syncComplianceLanguage = syncComplianceLanguage;

  function ensureComplianceControls() {
    const modal = document.getElementById('register-modal');
    const form = modal?.querySelector('form');
    if (!form || document.getElementById('cm-compliance-controls')) return;

    const lang = getLang();
    const t = COMPLIANCE_I18N[lang];

    const box = el('div', { id: 'cm-compliance-controls', class: 'form-group' });
    box.style.cssText = 'display:flex;flex-direction:column;gap:.75rem;padding:1rem;border:1px solid var(--border-subtle);border-radius:10px;background:rgba(17,24,39,.45);';
    addCheckbox(box, 'cm-business-user', t.business);
    addCheckbox(box, 'cm-terms', t.terms(TERMS_VERSION));
    addCheckbox(box, 'cm-privacy', t.privacy);

    const provider = el('div', { id: 'cm-provider-compliance' });
    provider.style.cssText = 'display:none;flex-direction:column;gap:.75rem;margin-top:.5rem;';
    const countryLabel = el('label', { for: 'cm-provider-country' }, t.countryLabel);
    const country = el('select', { id: 'cm-provider-country', class: 'form-control' });
    country.appendChild(el('option', { value: '' }, t.selectCountry));
    EEA.forEach(([code, name]) => country.appendChild(el('option', { value: code }, `${name} (${code})`)));
    provider.append(countryLabel, country);
    addCheckbox(provider, 'cm-provider-data-terms', t.providerData);
    addCheckbox(provider, 'cm-provider-no-logs', t.providerLogs);
    const payout = el('p', {});
    payout.style.cssText = 'font-size:.8rem;color:var(--text-muted);margin:0;';
    payout.textContent = t.providerPayout;
    provider.appendChild(payout);
    box.appendChild(provider);

    const submit = form.querySelector('button[type="submit"]');
    if (submit) form.insertBefore(box, submit);
    else form.appendChild(box);

    const wallet = form.querySelector('input[data-i18n="modal_wallet_placeholder"]');
    if (wallet) {
      wallet.value = '';
      const group = wallet.closest('.form-group');
      if (group) group.style.display = 'none';
    }

    const role = document.getElementById('modal-role');
    if (role) {
      const consumerOption = role.querySelector('option[value="consumer"]');
      const providerOption = role.querySelector('option[value="provider"]');
      if (consumerOption) consumerOption.textContent = t.consumerRole;
      if (providerOption) providerOption.textContent = t.providerRole;
      role.addEventListener('change', syncProviderControls);
    }
    syncProviderControls();
  }

  function syncProviderControls() {
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const provider = document.getElementById('cm-provider-compliance');
    if (provider) provider.style.display = role === 'provider' ? 'flex' : 'none';
  }

  function checked(id) {
    return document.getElementById(id)?.checked === true;
  }

  async function compliantRegistration(event) {
    event.preventDefault();
    ensureComplianceControls();
    const lang = getLang();
    const t = COMPLIANCE_I18N[lang];

    const form = event.currentTarget;
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const email = form.querySelector('input[type="email"]')?.value?.trim() || '';
    const keyInput = document.getElementById('generated-key-val');
    const resBox = document.getElementById('modal-result-box');
    const country = document.getElementById('cm-provider-country')?.value || '';

    if (!checked('cm-business-user') || !checked('cm-terms') || !checked('cm-privacy')) {
      if (keyInput) keyInput.value = t.errBusiness;
      if (resBox) resBox.style.display = 'block';
      return;
    }
    if (role === 'provider' && (!country || !checked('cm-provider-data-terms') || !checked('cm-provider-no-logs'))) {
      if (keyInput) keyInput.value = t.errProvider;
      if (resBox) resBox.style.display = 'block';
      return;
    }

    if (keyInput) keyInput.value = t.registering;
    if (resBox) resBox.style.display = 'block';
    try {
      const response = await fetch('/api/v1/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          role,
          wallet: '',
          country_code: role === 'provider' ? country : '',
          terms_version: TERMS_VERSION,
          accepted_terms: true,
          privacy_acknowledged: true,
          business_user: true,
          provider_data_processing_terms_accepted: role === 'provider' ? true : false,
          no_prompt_logging_attested: role === 'provider' ? true : false
        })
      });
      const data = await response.json();
      if (!response.ok || !data.api_key) throw new Error(data.error || 'registration_failed');
      if (keyInput) keyInput.value = data.api_key;
      if (role === 'provider' && resBox) {
        const note = el('p', {});
        note.style.cssText = 'font-size:.8rem;color:var(--text-muted);margin-top:.75rem;';
        note.textContent = t.registered;
        resBox.appendChild(note);
      }
    } catch (error) {
      if (keyInput) keyInput.value = `${t.regFailed}${String(error.message || error).slice(0, 160)}`;
    }
  }

  function applyLegalPositioning() {
    const lang = getLang();
    document.querySelectorAll('.chat-author').forEach((node) => {
      if (node.textContent.includes('ComputeMesh AI')) {
        node.childNodes[0].textContent = lang === 'de'
          ? 'Konfiguriertes Drittanbieter-Modell über ComputeMesh '
          : 'Configured third-party model via ComputeMesh ';
      }
    });
    window.applyQuickPrompt = function (key) {
      const safe = {
        en: {
          explain_mesh: 'In 2 concise sentences, explain ComputeMesh as distributed compute/orchestration infrastructure and distinguish it from the third-party AI models it executes.',
          python_fastapi: 'Write a high-performance Python FastAPI endpoint that forwards requests to an OpenAI-compatible /v1/chat/completions gateway with streaming.',
          gpu_sharding: 'Explain the engineering trade-offs of pipeline layer sharding across multiple GPUs without assuming a universal speedup.',
          compare_costs: 'Explain the variables that determine distributed inference cost. Do not invent savings, prices, SLAs or benchmark results.'
        },
        de: {
          explain_mesh: 'Erkläre in zwei knappen Sätzen ComputeMesh als verteilte Compute-/Orchestrierungsinfrastruktur und grenze es von den ausgeführten Drittanbieter-KI-Modellen ab.',
          python_fastapi: 'Schreibe einen performanten Python-FastAPI-Endpunkt, der Requests an ein OpenAI-kompatibles /v1/chat/completions-Gateway mit Streaming weiterleitet.',
          gpu_sharding: 'Erkläre die Engineering-Abwägungen von Pipeline-Layer-Sharding über mehrere GPUs, ohne einen universellen Speedup anzunehmen.',
          compare_costs: 'Erkläre die Variablen, die Kosten verteilter Inferenz bestimmen. Erfinde keine Einsparungen, Preise, SLAs oder Benchmark-Ergebnisse.'
        }
      };
      const input = document.getElementById('playground-prompt-input');
      const current = getLang();
      if (input && safe[current]?.[key]) {
        input.value = safe[current][key];
        input.focus();
      }
    };
  }

  function installOverrides() {
    const coreOpenModal = window.openModal;
    window.openModal = function (role = 'consumer') {
      if (typeof coreOpenModal === 'function') coreOpenModal(role);
      ensureComplianceControls();
      const select = document.getElementById('modal-role');
      if (select) select.value = role;
      syncProviderControls();
      syncComplianceLanguage(getLang());
    };
    window.handleRegistration = compliantRegistration;
    ensureComplianceControls();
    applyLegalPositioning();
    syncComplianceLanguage(getLang());
    syncPortalStaticLanguage(getLang());
  }

  const core = document.createElement('script');
  core.src = 'portal-core.js';
  core.async = false;
  core.onload = installOverrides;
  core.onerror = function () {
    const fallback = document.createElement('script');
    fallback.src = '/portal-core.js';
    fallback.async = false;
    fallback.onload = installOverrides;
    fallback.onerror = function () {
      console.error('ComputeMesh portal core failed to load');
    };
    document.head.appendChild(fallback);
  };
  document.head.appendChild(core);
})();
