/* ComputeMesh Portal Controller & Registration Manager
 * Provides B2B compliance, role-based form switching, static/legal i18n synchronization, and API credential generation.
 */
(function () {
  'use strict';

  const TERMS_VERSION = '2.1';
  const ANDROID_APK_URL = 'https://mesh.inetconnector.com/downloads/ComputeMesh-Android.apk';

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
    '/downloads': {
      en: {
        title: 'Downloads & Software Hub — ComputeMesh',
        desc: 'Official downloads for ComputeMesh Windows background service & tray app, Android client, Linux daemon, and NodeOS mining rig appliance.'
      },
      de: {
        title: 'Downloads & Software-Hub — ComputeMesh',
        desc: 'Offizielle Downloads für ComputeMesh Windows System-Tray-Client, Android-Client, Linux-Daemon und NodeOS Mining-Rig-Appliance.'
      }
    },
    '/docs': {
      en: {
        title: 'Developer Documentation — ComputeMesh',
        desc: 'Developer documentation for the ComputeMesh gateway, provider and distributed-inference paths.'
      },
      de: {
        title: 'Entwickler-Dokumentation — ComputeMesh',
        desc: 'Entwickler-Dokumentation für die ComputeMesh-Gateway-, Provider- und Distributed-Inference-Pfade.'
      }
    },
    '/status': {
      en: {
        title: 'System & Network Status — ComputeMesh',
        desc: 'Current operational and validation status for ComputeMesh.'
      },
      de: {
        title: 'System- & Netzwerkstatus — ComputeMesh',
        desc: 'Aktueller Betriebs- und Validierungsstatus von ComputeMesh.'
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
        title: 'Legal Notice (Impressum) — ComputeMesh',
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
    'Legal': 'Rechtliches',
    'Privacy': 'Datenschutz',
    'Terms': 'AGB',
    'Network Status': 'Systemstatus',
    'Register / API Key': 'Registrieren / API-Key',
    'Many graphics cards. One AI network.': 'Viele Grafikkarten. Ein KI-Netzwerk.',
    'AI should not only run in huge data centers.': 'KI soll nicht nur in riesigen Rechenzentren laufen.',
    'ComputeMesh connects idle graphics cards.': 'ComputeMesh verbindet freie Grafikkarten.',
    'Try the playground': 'Playground testen',
    'Offer hardware': 'Hardware anbieten',
    'Unavailable': 'Nicht verfügbar',
    'Clear Chat': 'Chat leeren',
    'Configured third-party model via ComputeMesh': 'Konfiguriertes Drittanbieter-Modell über ComputeMesh',
    'View account/provider options': 'Konto-/Provider-Optionen ansehen',
    'Readiness boundary:': 'Reifegrenze:',
    'TTFT note:': 'TTFT-Hinweis:',
    'Generated key:': 'Generierter Schlüssel:',
    'Your API Key:': 'Dein API-Key:',
    'Select deposit amount:': 'Einzahlungsbetrag auswählen:',
    'Proceed to configured Checkout →': 'Weiter zum konfigurierten Checkout →',
    'Architecture': 'Architektur',
    'API Integration': 'API-Integration',
    'GitHub Repository': 'GitHub-Repository',
    'Technical Docs': 'Technische Docs',
    'Engineering Status': 'Engineering-Status',
    'Measured Benchmarks': 'Gemessene Benchmarks',
    'Terms of Service': 'Nutzungsbedingungen',
    'Privacy Policy': 'Datenschutzerklärung',
    'Back to Home': 'Zurück zur Startseite',
    'Technical status:': 'Technischer Status:',
    'Registering...': 'Registrierung läuft...',
    'Enter your prompt here...': 'Prompt hier eingeben...',
    'Germany (DE)': 'Deutschland (DE)',
    'Austria (AT)': 'Österreich (AT)',
    'Switzerland (CH)': 'Schweiz (CH)',
    'France (FR)': 'Frankreich (FR)',
    'Netherlands (NL)': 'Niederlande (NL)',
    'Sweden (SE)': 'Schweden (SE)',
    'Norway (NO)': 'Norwegen (NO)',
    'Finland (FI)': 'Finnland (FI)',
    'Denmark (DK)': 'Dänemark (DK)',
    'Poland (PL)': 'Polen (PL)',
    'Italy (IT)': 'Italien (IT)',
    'Spain (ES)': 'Spanien (ES)',
    'Ireland (IE)': 'Irland (IE)',
    'Belgium (BE)': 'Belgien (BE)',
    '🇩🇪 Germany (DE)': '🇩🇪 Deutschland (DE)',
    '🇦🇹 Austria (AT)': '🇦🇹 Österreich (AT)',
    '🇨🇭 Switzerland (CH)': '🇨🇭 Schweiz (CH)',
    '🇫🇷 France (FR)': '🇫🇷 Frankreich (FR)',
    '🇳🇱 Netherlands (NL)': '🇳🇱 Niederlande (NL)',
    '🌍 Other EU/EEA Country': '🌍 Anderes EU/EWR-Land',
    '-- Nodes active': '-- Nodes aktiv',
    'Check current status': 'Aktuellen Zustand prüfen',
    'Loading live model catalog...': 'Der Live-Modellkatalog wird geladen...',
    'Loading live models...': 'Live-Modelle werden geladen...',
    'Current operational status must be confirmed by the live API': 'Aktueller Betriebszustand muss durch die Live-API bestätigt werden',
    'Unverified': 'Ungeprüft',
    'Proof pending': 'Nachweis offen',
    'Subject to online verification': 'Nur nach Online-Prüfung',
    'Legal Notice / Provider Identification': 'Impressum / Anbieterkennzeichnung',
    'Information pursuant to § 5 DDG. Information pursuant to the MStV applies additionally only insofar as the service contains journalistic-editorial offerings and the statutory requirements are met.': 'Angaben nach § 5 DDG. Angaben nach dem MStV gelten zusätzlich nur, soweit der Dienst journalistisch-redaktionelle Angebote enthält und die gesetzlichen Voraussetzungen erfüllt sind.',
    'Service Provider': 'Diensteanbieter',
    'Germany': 'Deutschland',
    'Contact': 'Kontakt',
    'Phone:': 'Telefon:',
    'Register and VAT Information': 'Register- und Umsatzsteuerangaben',
    'VAT identification number pursuant to § 27a UStG: Available upon request.': 'Umsatzsteuer-Identifikationsnummer gemäß § 27a UStG: Auf Anfrage.',
    'Responsibility for Own Content': 'Verantwortlichkeit für eigene Inhalte',
    'The service provider is responsible for its own content under general laws. Statutory liability privileges and obligations for third-party or user-generated content are governed by applicable law, in particular the Digital Services Act and the DDG. This legal notice does not establish any broader voluntary disclaimer of liability.': 'Der Diensteanbieter ist für eigene Inhalte nach den allgemeinen Gesetzen verantwortlich. Gesetzliche Haftungsprivilegien und Pflichten für fremde bzw. nutzergenerierte Inhalte richten sich nach dem jeweils anwendbaren Recht, insbesondere dem Digital Services Act und dem DDG. Dieses Impressum begründet keinen weitergehenden freiwilligen Haftungsausschluss.',
    'External Links': 'Externe Links',
    'Links may lead to offerings of independent third parties. The respective third-party provider is responsible for its offering. Any liability of the service provider is governed by statutory provisions; a blanket exclusion of mandatory statutory responsibility is not intended.': 'Links können zu Angeboten unabhängiger Dritter führen. Der jeweilige Drittanbieter ist für sein Angebot verantwortlich. Eine Haftung des Diensteanbieters richtet sich nach den gesetzlichen Vorschriften; ein pauschaler Ausschluss zwingender gesetzlicher Verantwortlichkeit ist nicht beabsichtigt.',
    'AI Outputs': 'KI-Ausgaben',
    'ComputeMesh may facilitate technical access to AI/model outputs or orchestrate compute capacity. AI outputs can be incorrect, fabricated, incomplete, outdated, unlawful, or unsuitable for a specific purpose. Users must independently verify outputs. Contractual risk allocation and legally permissible limitations of liability are set out in the': 'ComputeMesh kann den technischen Zugang zu KI-/Modellausgaben vermitteln oder Rechenleistung orchestrieren. KI-Ausgaben können falsch, erfunden, unvollständig, veraltet, rechtswidrig oder für einen konkreten Zweck ungeeignet sein. Nutzer müssen Ausgaben eigenständig prüfen. Die vertragliche Risikoverteilung und die rechtlich zulässigen Haftungsbeschränkungen ergeben sich aus den',
    '; mandatory statutory liability remains unaffected.': '; zwingende gesetzliche Haftung bleibt unberührt.',
    'Copyright and Trademarks': 'Urheberrecht und Kennzeichen',
    'Own content and software are subject to applicable copyright and license law. Open-source components are subject to their respective licenses. The designation ComputeMesh and other identifiers may not be used in a manner that suggests a non-existent business affiliation, authorization, or origin.': 'Eigene Inhalte und Software unterliegen dem jeweils anwendbaren Urheber- und Lizenzrecht. Open-Source-Bestandteile unterliegen ihren jeweiligen Lizenzen. Die Bezeichnung ComputeMesh und sonstige Kennzeichen dürfen nicht so verwendet werden, dass eine nicht bestehende geschäftliche Verbindung, Autorisierung oder Herkunft suggeriert wird.',
    'Data Protection': 'Datenschutz',
    'Information on the processing of personal data can be found in the': 'Informationen zur Verarbeitung personenbezogener Daten stehen in der',
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
    "Actual prices, platform fees, revenue shares and thresholds are those presented by the applicable live quote/order/checkout or individually agreed terms. Website calculators and research comparisons are not binding quotes or income guarantees. Payments may use Stripe Checkout and provider onboarding/payouts may use Stripe Connect, subject to Stripe's KYC, fraud, sanctions, reserve, currency and eligibility rules. Each party remains responsible for its own tax obligations.": 'Tatsächliche Preise, Plattformgebühren, Umsatzanteile und Schwellen sind diejenigen, die im jeweiligen Live-Angebot, Auftrag, Checkout oder in individuell vereinbarten Bedingungen dargestellt sind. Webseiten-Rechner und Forschungsvergleiche sind keine verbindlichen Angebote oder Einkommensgarantien. Zahlungen können Stripe Checkout und Provider-Onboarding/-Auszahlungen Stripe Connect nutzen, jeweils vorbehaltlich der KYC-, Betrugs-, Sanktions-, Reserve-, Währungs- und Eignungsregeln von Stripe. Jede Partei bleibt für ihre eigenen Steuerpflichten verantwortlich.',
    '12. No warranties': '12. Keine Gewährleistungen',
    'Except for individually agreed characteristics and to the maximum extent permitted by law, the Operator gives no warranty or guarantee concerning AI-output accuracy or quality, fitness for purpose, non-infringement, uninterrupted availability, economic results, security against every attack, provider conduct, third-party services or continuing compatibility with hardware, drivers, SDKs, models or upstream projects.': 'Außer für individuell vereinbarte Beschaffenheiten und im gesetzlich größtmöglichen Umfang übernimmt der Betreiber keine Gewährleistung oder Garantie für Genauigkeit oder Qualität von KI-Ausgaben, Zweckgeeignetheit, Nichtverletzung von Rechten, unterbrechungsfreie Verfügbarkeit, wirtschaftliche Ergebnisse, Sicherheit gegen jeden Angriff, Provider-Verhalten, Drittanbieterdienste oder fortlaufende Kompatibilität mit Hardware, Treibern, SDKs, Modellen oder Upstream-Projekten.',
    '13. Limitation of liability': '13. Haftungsbeschränkung',
    'Nothing excludes or limits liability where prohibited by law. Liability remains unlimited for intent, gross negligence, culpable injury to life/body/health, mandatory product-liability law, fraudulently concealed defects and expressly assumed guarantees.': 'Nichts schließt oder beschränkt Haftung, soweit dies gesetzlich verboten ist. Unbeschränkte Haftung besteht für Vorsatz, grobe Fahrlässigkeit, schuldhafte Verletzung von Leben/Körper/Gesundheit, zwingendes Produkthaftungsrecht, arglistig verschwiegene Mängel und ausdrücklich übernommene Garantien.',
    'For ordinary negligence, the Operator is liable only for breach of a material contractual obligation (Kardinalpflicht), and then only for foreseeable damage typical for this type of contract. To the extent legally permissible in B2B transactions, aggregate liability for ordinary negligence is limited to the net fees paid by the affected customer for the affected Service during the twelve months preceding the event.': 'Bei einfacher Fahrlässigkeit haftet der Betreiber nur bei Verletzung einer wesentlichen Vertragspflicht (Kardinalpflicht), und dann nur für den vertragstypischen, vorhersehbaren Schaden. Soweit in B2B-Geschäften rechtlich zulässig, ist die Gesamthaftung für einfache Fahrlässigkeit auf die Nettoentgelte begrenzt, die der betroffene Kunde für den betroffenen Dienst in den zwölf Monaten vor dem Ereignis gezahlt hat.',
    "Subject to those mandatory carve-outs, the Operator is not liable for indirect or consequential loss, lost profit, revenue, business opportunity, anticipated savings, goodwill or data, nor for losses caused by reliance on unverified AI output, customer prompts/configuration, independent-provider misconduct, third-party models/services, external networks, power failure, force majeure or unauthorized use outside the Operator's reasonable control.": 'Vorbehaltlich dieser zwingenden Ausnahmen haftet der Betreiber nicht für indirekte Schäden oder Folgeschäden, entgangenen Gewinn, Umsatz, Geschäftschancen, erwartete Einsparungen, Goodwill oder Daten sowie nicht für Schäden durch Vertrauen auf ungeprüfte KI-Ausgaben, Kundenprompts/-konfiguration, Fehlverhalten unabhängiger Provider, Drittanbieter-Modelle/-Dienste, externe Netzwerke, Stromausfall, höhere Gewalt oder unbefugte Nutzung außerhalb zumutbarer Kontrolle des Betreibers.',
    '14. Business-user indemnification': '14. Freistellung durch Geschäftskunden',
    "To the extent permitted by law, a business user shall indemnify the Operator against third-party claims and reasonable legal-defense costs arising from the user's unlawful input/use, infringement of third-party rights, privacy/AI-regulatory violations attributable to the user, or deployment/publication of output, except to the extent caused by the Operator's own legally attributable breach. Mandatory duties imposed directly on the Operator are not shifted by this clause.": 'Soweit gesetzlich zulässig, stellt ein Geschäftskunde den Betreiber von Ansprüchen Dritter und angemessenen Rechtsverteidigungskosten frei, die aus rechtswidrigen Eingaben/Nutzungen des Nutzers, Verletzung von Rechten Dritter, dem Nutzer zurechenbaren Datenschutz-/KI-Regulierungsverstößen oder Deployment/Veröffentlichung von Ausgaben entstehen, außer soweit sie durch eine dem Betreiber rechtlich zurechenbare Pflichtverletzung verursacht wurden. Dem Betreiber unmittelbar auferlegte zwingende Pflichten werden durch diese Klausel nicht verschoben.',
    '15. Open source, suspension and changes': '15. Open Source, Sperrung und Änderungen',
    'Open-source components remain subject to their licenses. Public source availability grants no rights in private control-plane code, confidential data or trademarks beyond applicable licenses. The Operator may suspend access for security, abuse prevention, compliance, sanctions, maintenance or non-payment. Accrued rights and mandatory retention/accounting duties survive where applicable.': 'Open-Source-Komponenten unterliegen weiterhin ihren jeweiligen Lizenzen. Öffentliche Quellverfügbarkeit gewährt über anwendbare Lizenzen hinaus keine Rechte an privatem Control-Plane-Code, vertraulichen Daten oder Marken. Der Betreiber kann Zugriff aus Sicherheits-, Missbrauchspräventions-, Compliance-, Sanktions-, Wartungs- oder Nichtzahlungsgründen aussetzen. Entstandene Rechte und zwingende Aufbewahrungs-/Buchhaltungspflichten bleiben, soweit anwendbar, bestehen.',
    '16. Governing law, venue and severability': '16. Anwendbares Recht, Gerichtsstand und Salvatorisches',
    "German law applies, excluding the CISG, to the extent legally effective. For merchants, legal persons under public law and special funds under public law, the Operator's place of business is the agreed venue where permitted. Mandatory venues remain unaffected. Individually negotiated terms prevail over these Terms. If a provision is invalid, statutory rules apply in its place.": 'Es gilt deutsches Recht unter Ausschluss des UN-Kaufrechts, soweit rechtlich wirksam. Für Kaufleute, juristische Personen des öffentlichen Rechts und öffentlich-rechtliche Sondervermögen ist der Geschäftssitz des Betreibers der vereinbarte Gerichtsstand, soweit zulässig. Zwingende Gerichtsstände bleiben unberührt. Individuell ausgehandelte Bedingungen gehen diesen Bedingungen vor. Ist eine Bestimmung unwirksam, gelten an ihrer Stelle die gesetzlichen Regeln.',
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
    '. This preference is used to provide the expressly requested language behavior and is treated as technically necessary functionality. The current audited portal does not require advertising or behavioral-tracking cookies for core operation. Non-essential analytics, advertising pixels, fingerprinting or comparable access to terminal-device information must not be enabled without a legally valid consent mechanism and updated disclosure where § 25 TDDDG or GDPR requires consent.': '. Diese Einstellung wird verwendet, um das ausdrücklich gewünschte Sprachverhalten bereitzustellen, und wird als technisch notwendige Funktion behandelt. Das aktuell geprüfte Portal benötigt für den Kernbetrieb keine Werbe- oder Verhaltens-Tracking-Cookies. Nicht notwendige Analytics, Werbepixel, Fingerprinting oder vergleichbarer Zugriff auf Endgeräteinformationen dürfen nicht ohne rechtlich gültigen Einwilligungsmechanismus und aktualisierte Hinweise aktiviert werden, soweit § 25 TDDDG oder DSGVO eine Einwilligung verlangen.',
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
    'This notice may be updated when processing, law, providers or architecture changes. Material changes will be published appropriately. The deployed code/configuration, processing records, contracts and this notice must be reviewed together after material changes.': 'Diese Hinweise können aktualisiert werden, wenn sich Verarbeitung, Recht, Provider oder Architektur ändern. Wesentliche Änderungen werden angemessen veröffentlicht. Deployter Code/Konfiguration, Verarbeitungsdokumentation, Verträge und diese Hinweise müssen nach wesentlichen Änderungen gemeinsam geprüft werden.',
    // Agent Workspace & Fleet Cockpit static UI strings
    'Select project': 'Projekt auswählen',
    'New Chat / Task': 'Neuer Chat / Aufgabe',
    'Local Workspaces (mifcoms)': 'Lokale Workspaces (mifcoms)',
    '+ Add': '+ Hinzufügen',
    'Loading workspaces from mifcoms...': 'Lade Workspaces von mifcoms...',
    'No sessions': 'Keine Sitzungen',
    'Connected • Ready': 'Verbunden • Bereit',
    'New Chat': 'Neuer Chat',
    'Rename session': 'Sitzung umbenennen',
    'Delete session': 'Sitzung löschen',
    '⚡ ComputeMesh Agent Workspace': '⚡ ComputeMesh Agent Workspace',
    'Work with Agent on mifcoms': 'Mit KI-Agent auf mifcoms arbeiten',
    'Connected to': 'Verbunden mit',
    '. Select a local project from the sidebar or start a task directly.': '. Wähle ein lokales Projekt aus der Seitenleiste oder starte direkt eine Aufgabe.',
    '📊 Check Git status': '📊 Git-Status prüfen',
    '🧪 Run local tests': '🧪 Lokale Tests ausführen',
    '🔍 Analyze code': '🔍 Code analysieren',
    'Approve for me': 'Für mich genehmigen',
    '🛡️ Approve for me (Interactive)': '🛡️ Für mich genehmigen (Interaktiv)',
    '⚡ Run automatically (Autonomous)': '⚡ Automatisch ausführen (Autonom)',
    '🔒 Read-only access (Read-Only)': '🔒 Nur Lesezugriff (Read-Only)',
    'No project selected': 'Kein Projekt gewählt',
    'View changes': 'Änderungen anzeigen',
    'Inference Hardware': 'Inferenz-Hardware',
    'Create / register local project on mifcoms': 'Lokales Projekt auf mifcoms anlegen / registrieren',
    'Create & register project': 'Projekt anlegen & registrieren',
    'Cancel': 'Abbrechen',
    'Close': 'Schließen',
    'Project Changes & Git Diffs': 'Projekt-Änderungen & Git Diffs',
    'No pending changes for the active session.': 'Keine ausstehenden Änderungen für die aktive Sitzung vorhanden.',
    'Project Details': 'Projekt-Details',
    '⚠️ Delete physical directory': '⚠️ Physisches Verzeichnis löschen',
    'WARNING: This action permanently deletes the folder and all files inside it from disk!': 'ACHTUNG: Dieser Vorgang löscht den Ordner und alle darin enthaltenen Dateien unwiderruflich von der Festplatte!',
    'To confirm, please type the exact name of the project:': 'Zur Bestätigung tippe bitte den exakten Namen des Projekts ein:',
    'Permanently delete': 'Unwiderruflich löschen',
    'Search project...': 'Projekt suchen...',
    'Enter exact project name': 'Exakten Projektnamen eingeben',
    '✅ Enable all': '✅ Alle aktivieren',
    '❌ Disable all': '❌ Alle deaktivieren',
    'Saved per fleet': 'Gespeichert pro Flotte',
    'Enter a project name or absolute path. If the directory does not exist yet, the project folder will be automatically created locally on your machine in': 'Gib einen Projektnamen oder absoluten Pfad ein. Wenn das Verzeichnis noch nicht existiert, wird der Projektordner automatisch lokal auf deinem Rechner in',
    'physically created, initialized with README.md and Git.': 'physisch angelegt, mit README.md und Git initialisiert.',
    'All inference pipelines, API keys, provider node heartbeats and tunnels of this fleet are blocked (HTTP 403 Forbidden). For clarification and unblocking, please contact': 'Alle Inferenz-Pipelines, API-Keys, Provider-Node-Heartbeats und Tunnel dieser Flotte sind blockiert (HTTP 403 Forbidden). Zur Klärung und Freigabe wende dich bitte an',
    '75% of all inference fees': '75% aller Inferenzgebühren',
    ', executed on your provided GPU servers. Payouts are transferred automatically or on demand via Stripe Express securely directly to your bank account.': ', die auf deinen bereitgestellten GPU-Servern ausgeführt werden. Auszahlungen werden automatisch oder auf Knopfdruck über Stripe Express sicher direkt auf dein Bankkonto überwiesen.',
    'Actual Ledger Balance': 'Tatsächliches Ledger-Guthaben',
    '🔒 100% verified double-entry ledger (no fictitious numbers)': '🔒 100% verifizierter Double-Entry-Ledger (keine fiktiven Zahlen)',
    'Minimum amount for instant or batch payout': 'Mindestbetrag für Sofort- oder Sammelauszahlung',
    'Direct transfer to your bank account': 'Direktüberweisung auf dein Bankkonto',
    '🔄 Check status': '🔄 Status prüfen',
    'Scan this barcode directly with the': 'Scanne diesen Barcode direkt mit der',
    'on your smartphone. Your phone will be paired immediately with your fleet without manual password entry!': 'auf deinem Smartphone. Dein Handy wird sofort ohne manuelle Passworteingabe mit deiner Flotte gekoppelt!',
    'All API calls with your Owner Key (': 'Alle API-Aufrufe mit deinem Owner Key (',
    'without fees directly via your own hardware.': 'ohne Gebühren direkt über deine eigene Hardware.',
    'Whenever your GPU is idle, the network provides unused VRAM to paying customers. You receive': 'Sobald deine GPU im Leerlauf ist, stellt das Netzwerk ungenutzten VRAM zahlenden Kunden bereit. Du erhältst',
    'Universal Tool Compatibility': 'Universelle Tool-Kompatibilität',
    'Drop-in replacement for OpenAI in': 'Drop-In Ersatz für OpenAI in',
    'and the': 'und der',
    'Your Personal API Connection Details': 'Deine persönlichen API-Verbindungsdaten',
    'Your API / Owner Key (Free for you):': 'Dein API / Owner Key (Kostenlos für dich):',
    'The scripts already automatically include your personal': 'Die Skripte enthalten bereits automatisch deinen persönlichen',
    'and connect your Ollama service directly to your fleet.': 'und verbinden deinen Ollama-Dienst direkt mit deiner Flotte.',
    '1-Click Start with Mesh-Pool & Tray Daemon': '1-Klick Start mit Mesh-Pool & Tray Daemon',
    'Automatic background daemon for servers': 'Automatischer Hintergrund-Daemon für Server',
    'On-Device MiniCPM5-2B AI, LAN Discovery & Battery Guard': 'On-Device MiniCPM5-2B KI, LAN-Discovery & Akku-Wächter',
    '📷 Scan with smartphone:': '📷 Mit Smartphone scannen:',
    'Resets Ollama to default standalone (127.0.0.1)': 'Setzt Ollama auf Standard-Standalone (127.0.0.1)',
    '⚡ Run directly via terminal (cURL & PowerShell)': '⚡ Direkt per Terminal ausführen (cURL & PowerShell)',
    'With the': 'Mit dem',
    'your private GPU fleet becomes a dynamic AI agent. When you execute requests with your Owner Key, the model can access external data in real time or invoke custom MCP servers.': 'wird deine private GPU-Flotte zum dynamischen KI-Agenten. Wenn du Anfragen mit deinem Owner Key ausführst, kann das Modell in Echtzeit auf externe Daten zugreifen oder eigene MCP-Server ansteuern.',
    '/20 tools active for this fleet': '/20 Tools aktiv für diese Flotte',
    'Live Stock Quotes & Crypto': 'Live-Börsenkurse & Krypto',
    'Real-time Yahoo Finance & CoinGecko quotes for stocks (NVDA, AAPL, MSFT), crypto (BTC, ETH, SOL) and commodities.': 'Echtzeit Yahoo Finance & CoinGecko Kurse für Aktien (NVDA, AAPL, MSFT), Krypto (BTC, ETH, SOL) und Rohstoffe.',
    'Breaking news and headlines in real time (Tech, AI, Business, Crypto, Tagesschau or keyword search).': 'Aktuelle Meldungen und Schlagzeilen in Echtzeit (Tech, KI, Wirtschaft, Krypto, Tagesschau oder Stichwort-Suche).',
    'Real-time weather, temperature, humidity, wind and WMO conditions via Open-Meteo & wttr.in for any location.': 'Echtzeit-Wetter, Temperatur, Luftfeuchtigkeit, Wind und WMO-Bedingungen via Open-Meteo & wttr.in für jeden Ort.',
    'Precise mathematical calculations, formulas, compound interest, statistics & algorithms in the isolated AST sandbox.': 'Präzise mathematische Berechnungen, Formeln, Zinseszins, Statistik & Algorithmen im isolierten AST-Sandbox.',
    'Wikipedia & Encyclopedia': 'Wikipedia & Enzyklopädie',
    'In-depth summaries, definitions, historical data and biographies directly via the official Wikipedia API.': 'Fundierte Zusammenfassungen, Definitionen, historische Daten und Biografien direkt über die offizielle Wikipedia-API.',
    'Country & Geo Database': 'Länder- & Geodatenbank',
    'Capitals, populations, official languages, currencies, neighboring countries and time zones of all states worldwide via REST Countries.': 'Hauptstädte, Einwohnerzahlen, Amtssprachen, Währungen, Nachbarländer und Zeitzonen aller Staaten weltweit via REST Countries.',
    'World Bank & Macroeconomics': 'Weltbank & Makroökonomie',
    'Official data on gross domestic product (GDP), inflation, life expectancy, CO2 emissions and population across decades.': 'Offizielle Daten zu Bruttoinlandsprodukt (BIP), Inflation, Lebenserwartung, CO2-Emissionen und Bevölkerung über Jahrzehnte.',
    'Full search for latest scientific preprints, AI/ML research, physics, math and computer science abstracts.': 'Vollständige Suche nach neuesten wissenschaftlichen Preprints, KI-/ML-Forschung, Physik, Mathe und Informatik-Abstracts.',
    'Ingredients, allergens, Nutri-Score (A-E), Eco-Score and nutrition tables by product name or EAN barcode (Open Food Facts).': 'Inhaltsstoffe, Allergene, Nutri-Score (A-E), Eco-Score und Nährwerttabellen per Produktname oder EAN-Barcode (Open Food Facts).',
    'Packages & CVE Security': 'Pakete & CVE-Sicherheit',
    'Audit PyPI, NPM and Rust packages, versions, licenses and direct matching of known vulnerabilities via OSV.dev.': 'Prüfung von PyPI-, NPM- und Rust-Paketen, Versionen, Lizenzen und direkter Abgleich bekannter Sicherheitslücken via OSV.dev.',
    'Molecular formulas, molecular weights, IUPAC names, SMILES and properties of substances via NIH PubChem.': 'Summenformeln, Molekulargewichte, IUPAC-Namen, SMILES und Eigenschaften von Stoffen via NIH PubChem.',
    'Dictionary & Phonetics': 'Wörterbuch & Lautschrift',
    'Word definitions, phonetics, parts of speech, example sentences and synonyms via Free Dictionary API.': 'Wortdefinitionen, Lautschrift (Phonetics), Wortarten, Beispielsätze und Synonyme via Free Dictionary API.',
    'Live departure times of Deutsche Bahn (ICE, RE, S-Bahn), platforms, destinations and real-time delays via HAFAS.': 'Live-Abfahrtszeiten der Deutschen Bahn (ICE, RE, S-Bahn), Gleise, Zielbahnhöfe und Echtzeit-Verspätungen via HAFAS.',
    'Currency & Crypto Converter': 'Währungs- & Krypto-Rechner',
    'Exact time across all time zones worldwide, calendar weeks and public German holidays per federal state.': 'Genaue Uhrzeit aller Zeitzonen weltweit, Kalenderwochen und gesetzliche deutsche Feiertage pro Bundesland.',
    'Calculation of linear distance, compass bearing, geo-coordinates and driving distance/duration between locations worldwide.': 'Berechnung von Luftlinie, Himmelsrichtung, Geokoordinaten und Fahrtstrecke/Fahrzeit zwischen Orten weltweit.',
    'Direct internet research via DuckDuckGo HTML & Bing RSS with intelligent text cleaning and snippet synthesis.': 'Direkte Internet-Recherche via DuckDuckGo HTML & Bing RSS mit intelligenter Textbereinigung und Snippet-Synthese.',
    'Automatic extraction and formatting of online articles, blog posts and developer documentation.': 'Automatisches Auslesen und Formatieren von Online-Artikeln, Blogbeiträgen und Entwickler-Dokumentationen.',
    'Secure DNS check, HTTP status & SSL certificate validity of public domains with SSRF firewall (Owner Only).': 'Sichere DNS-Prüfung, HTTP-Status & SSL-Zertifikatslaufzeit öffentlicher Domains mit SSRF-Schutzwall (Owner Only).',
    'Sovereign Playwright MCP Browser & Web Automation Sandbox': 'Souveräner Playwright MCP-Browser & Web-Automation Sandbox',
    'Fully isolated Playwright browser environment in a hardened MicroVM/sandbox. Built for autonomous web tasks, research, portal interactions, form filling, script execution, file uploads & downloads – controlled by your user instructions with zero-trust protection.': 'Vollständig isolierte Playwright-Browser-Umgebung in einer abgesicherten MicroVM/Sandbox. Entwickelt für beliebige autonome Web-Aufgaben, Recherchen, Portal-Interaktionen, Formularbefüllungen, Script-Ausführungen, Datei-Uploads & Downloads – gesteuert durch deine Benutzeranweisungen mit absolutem Zero-Trust Schutz.',
    'Open internet access by default (': 'Standardmäßig offener Internetzugriff (',
    ') for universal web tasks. Optionally restrictable to custom domain whitelists.': ') für universelle Web-Aufgaben. Optional einschränkbar auf benutzerdefinierte Domain-Whitelists.',
    'No unauthorized external control. Access exclusively via HMAC-SHA256 signature of your local fleet key (': 'Keine unbefugte externe Steuerung. Zugriff ausschließlich über HMAC-SHA256 Signatur deines lokalen Flottenschlüssels (',
    ') for arbitrary documents, PDFs, media & datasets with strict traversal protection.': ') für beliebige Dokumente, PDFs, Medien & Datensätze mit striktem Traversal-Schutz.',
    'Critical or irreversible actions (orders, payments, deletions, submissions) require explicit prior confirmation with a cryptographic request token.': 'Kritische oder unwiderrufliche Aktionen (Bestellungen, Zahlungen, Löschvorgänge, Einreichungen) erfordern vorab eine explizite Bestätigung mit kryptografischem Request-Token.',
    'ComputeMesh AI Chat (Dedicated Interface)': 'ComputeMesh AI-Chat (Dedizierte Oberfläche)',
    'Full-featured, modern chat interface for your local GPU fleet and remote nodes. Open the chat in its own clean window for maximum workspace.': 'Vollwertige, moderne Chat-Oberfläche für deine lokale GPU-Flotte und Remote-Nodes. Öffne den Chat im eigenen sauberen Fenster für maximale Arbeitsfläche.',
    '🚀 Open AI Chat in Dedicated Window': '🚀 AI-Chat im eigenen Fenster öffnen',
    'Independent, physically separated emergency stop and positive authorization subsystem with multi-tenant isolation (fail-closed default state).': 'Unabhängiges, physisch getrenntes Not-Aus- und Positiv-Autorisierungs-Subsystem mit Multi-Tenant-Isolation (Fail-Closed Default State).',
    'As a fleet operator, you have full sovereignty over your own GPU nodes and servers. A fleet emergency stop halts and protects your hardware': 'Als Flottenbetreiber hast du die volle Hoheit über deine eigenen GPU-Knoten und Server. Ein Flotten-Not-Aus stoppt und schützt deine Hardware',
    '. The global mesh network, other providers and other tenants continue running': '. Das weltweite Mesh-Netzwerk, andere Provider und andere Mieter laufen',
    '. The global platform emergency stop is cryptographically reserved exclusively for the system owner (inetconnector / Stripe Account Owner) via physical DiskStation master key management.': '. Der globale Plattform-Not-Aus ist kryptografisch ausschließlich dem System-Inhaber (inetconnector / Stripe Account Owner) über die physische DiskStation-Master-Schlüsselverwaltung vorbehalten.',
    'Clicking Emergency Stop immediately revokes all cryptographic execution leases of your fleet, terminates inference process trees of your nodes and disconnects local tunnels. Other fleets in the mesh remain completely unaffected.': 'Ein Klick auf Not-Aus entzieht sofort alle kryptographischen Ausführungs-Leases deiner Flotte, beendet Inferenz-Prozessbäume deiner Knoten und trennt lokale Tunnel. Andere Flotten im Mesh bleiben völlig unberührt.',
    '🔄 Check / renew lease': '🔄 Lease prüfen / erneuern',
    'Valid for your registered fleet': 'Gültig für deine registrierte Flotte',
    '— Immediate Emergency Stop for all nodes (Master-Authorized)': '— Sofortiger Not-Aus für alle Nodes (Master-Autorisiert)',
    '— Complete security architecture, multi-tenant isolation & emergency operating manual': '— Vollständige Sicherheitsarchitektur, Multi-Tenant Isolation & Notfall-Betriebsanleitung',
    'Exclusive administration and security tools for the platform owner (inetconnector / Stripe Account Holder).': 'Exklusive Verwaltungs- und Sicherheits-Werkzeuge für den Plattform-Inhaber (inetconnector / Stripe Account Holder).',
    'Enter Master Admin Key': 'Master-Admin-Schlüssel eingeben',
    'Authenticate with your': 'Authentifiziere dich mit deinem',
    'Persistently blocks a fleet in SQLite and immediately triggers the in-memory killswitch. All nodes and API keys of this fleet are blocked instantaneously.': 'Sperrt eine Flotte persistent in SQLite und löst sofort den In-Memory-Killswitch aus. Alle Nodes und API-Keys dieser Flotte werden augenblicklich blockiert.',
    'Target Account / Owner ID (facc_... or acct_...):': 'Ziel-Account / Owner-ID (facc_... oder acct_...):',
    'Reason for suspension:': 'Grund der Sperre:',
    'Real-time synchronization with the master database': 'Echtzeit-Synchronisation mit der Master-Datenbank'
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
    const translations = window.portalTranslations || window.translations || {};
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
    if (!root) return;
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

  function getLang() {
    return (window.currentLang === 'de' || localStorage.getItem('cm_portal_lang') === 'de' || (!localStorage.getItem('cm_portal_lang') && (navigator.language || '').startsWith('de'))) ? 'de' : 'en';
  }

  function syncPortalStaticLanguage(lang) {
    const l = (lang === 'de' || lang === 'en') ? lang : getLang();
    syncPortalMetadata(l);
    translateTextNodes(document.body, l);
    translateStaticAttributes(l);
    translateFormValues(l);
    syncProviderControls();
    clarifyVisionCapabilities();
  }
  window.syncPortalStaticLanguage = syncPortalStaticLanguage;

  function registrationErrorMessage(payload, fallback) {
    const error = payload && payload.error;
    if (typeof error === 'string' && error.trim()) return error.trim();
    if (error && typeof error.message === 'string' && error.message.trim()) return error.message.trim();
    if (payload && typeof payload.message === 'string' && payload.message.trim()) return payload.message.trim();
    return fallback;
  }

  function syncProviderControls() {
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const providerFields = document.getElementById('provider-extra-fields');
    const submitBtn = document.getElementById('modal-submit-btn');
    const lang = getLang();

    if (providerFields) {
      providerFields.style.display = role === 'provider' ? 'flex' : 'none';
    }
    if (submitBtn) {
      if (role === 'provider') {
        submitBtn.textContent = lang === 'de' ? '⚡ GPU-Node registrieren' : '⚡ Register GPU Node';
      } else {
        submitBtn.textContent = lang === 'de' ? '🚀 API-Key generieren' : '🚀 Generate API Key';
      }
    }
  }

  async function compliantRegistration(event) {
    if (event && event.preventDefault) event.preventDefault();
    const form = document.getElementById('registration-form');
    const submitBtn = document.getElementById('modal-submit-btn');
    if (form?.dataset.registrationBusy === '1') return;
    const lang = getLang();
    const role = document.getElementById('modal-role')?.value || 'consumer';
    const email = document.getElementById('modal-email')?.value?.trim() || '';
    const country = document.getElementById('cm-provider-country')?.value || '';
    const wallet = document.getElementById('modal-wallet')?.value?.trim() || '';
    const bizCheck = document.getElementById('business-user-confirm');
    const keyInput = document.getElementById('generated-key-val');
    const resBox = document.getElementById('modal-result-box');

    if (!bizCheck || !bizCheck.checked) {
      const msg = lang === 'de'
        ? 'Bitte akzeptiere die Nutzungsbedingungen und bestätige die geschäftliche Nutzung (B2B).'
        : 'Please accept the Terms of Service & Privacy Policy and confirm business (B2B) use.';
      if (keyInput) keyInput.value = msg;
      if (resBox) resBox.style.display = 'block';
      return;
    }

    if (role === 'provider' && !country) {
      const msg = lang === 'de' ? 'Bitte wähle dein Betriebsland (EWR/EU).' : 'Please select your operating country.';
      if (keyInput) keyInput.value = msg;
      if (resBox) resBox.style.display = 'block';
      return;
    }

    if (form) form.dataset.registrationBusy = '1';
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.setAttribute('aria-busy', 'true');
    }

    if (keyInput) keyInput.value = lang === 'de' ? 'Zugangsdaten werden generiert…' : 'Generating API credentials…';
    if (resBox) resBox.style.display = 'block';

    try {
      const response = await fetch('/api/v1/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          role,
          wallet: role === 'provider' ? wallet : '',
          country_code: role === 'provider' ? country : '',
          terms_version: TERMS_VERSION,
          accepted_terms: true,
          privacy_acknowledged: true,
          business_user: true,
          provider_data_processing_terms_accepted: role === 'provider',
          no_prompt_logging_attested: role === 'provider'
        })
      });
      const data = await response.json();
      if (!response.ok || !data.api_key) {
        throw new Error(registrationErrorMessage(data, lang === 'de' ? 'Registrierung konnte nicht abgeschlossen werden.' : 'Registration could not be completed.'));
      }
      if (keyInput) keyInput.value = data.api_key;
      try { localStorage.setItem('cm_api_key', data.api_key); } catch (e) {}
      if (typeof window.updateCodeSnippetsWithKey === 'function') {
        window.updateCodeSnippetsWithKey(data.api_key);
      }
    } catch (error) {
      const prefix = lang === 'de' ? 'Registrierung fehlgeschlagen: ' : 'Registration failed: ';
      if (keyInput) keyInput.value = `${prefix}${String(error.message || error).slice(0, 160)}`;
    } finally {
      if (form) delete form.dataset.registrationBusy;
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.removeAttribute('aria-busy');
      }
    }
  }

  function clarifyVisionCapabilities() {
    const select = document.getElementById('playground-model-select');
    if (!select) return;
    const option = Array.from(select.options).find(o => o.value === 'qwen2.5-vl:7b');
    if (option) {
      option.textContent = getLang() === 'de'
        ? 'Qwen 2.5 VL 7B (Vision / Bildanalyse – keine Bildgenerierung)'
        : 'Qwen 2.5 VL 7B (Vision / image analysis – not image generation)';
    }
  }

  function installImageSafetyNotice() {
    const studio = document.querySelector('.playground-studio');
    if (!studio || document.getElementById('cm-image-safety-notice')) return;
    const note = document.createElement('div');
    note.id = 'cm-image-safety-notice';
    note.style.cssText = 'margin-top:1rem;padding:0.85rem 1rem;border:1px solid rgba(56,189,248,.24);border-radius:10px;background:rgba(15,23,42,.55);font-size:.82rem;line-height:1.5;color:#94a3b8;';
    note.innerHTML = getLang() === 'de'
      ? '🛡️ <strong style="color:#cbd5e1">Bild-KI Sicherheit:</strong> Vision-Modelle analysieren Bilder, erzeugen aber keine. Eine separate Bildgenerierung wird nur mit verpflichtender Prompt- und Output-Moderation, Minderjährigenschutz, Deepfake-Schutz und KI-Herkunftskennzeichnung freigeschaltet.'
      : '🛡️ <strong style="color:#cbd5e1">Image AI safety:</strong> Vision models analyze images; they do not render images. Separate image generation is enabled only with mandatory prompt/output moderation, minor protection, deepfake safeguards and AI-origin provenance.';
    studio.appendChild(note);
  }

  function installAndroidDownloadLink() {
    const links = Array.from(document.querySelectorAll('a[href*="ComputeMesh-Android.apk"]'));
    links.forEach(link => {
      link.href = ANDROID_APK_URL;
      link.setAttribute('rel', 'noopener');
    });

    const androidButton = links.find(link => link.hasAttribute('download') || link.dataset.i18n === 'dl_android_btn');
    const card = androidButton?.closest('.download-card');
    if (!card || card.querySelector('.cm-android-direct-link')) return;

    const direct = document.createElement('a');
    direct.className = 'cm-android-direct-link';
    direct.href = ANDROID_APK_URL;
    direct.rel = 'noopener';
    direct.textContent = ANDROID_APK_URL;
    direct.style.cssText = 'display:block;margin-top:.6rem;font-size:.72rem;overflow-wrap:anywhere;color:var(--accent-cyan);text-align:center;';
    card.appendChild(direct);
  }

  function setupModalHooks() {
    const roleSelect = document.getElementById('modal-role');
    if (roleSelect) {
      roleSelect.addEventListener('change', syncProviderControls);
    }
    const form = document.getElementById('registration-form');
    if (form) {
      form.onsubmit = compliantRegistration;
    }

    const coreOpenModal = window.openModal;
    window.openModal = function (role = 'consumer') {
      if (typeof coreOpenModal === 'function') coreOpenModal(role);
      if (roleSelect) roleSelect.value = role;
      syncProviderControls();
    };
    window.handleRegistration = compliantRegistration;
    window.compliantRegistration = compliantRegistration;
    syncProviderControls();
    clarifyVisionCapabilities();
    installImageSafetyNotice();
    installAndroidDownloadLink();
    syncPortalStaticLanguage(getLang());
  }

  const QUICK_PROMPTS_FALLBACK = {
    de: {
      explain_mesh: "Was macht ComputeMesh einzigartig und wie funktioniert die dezentrale GPU-Inferenz?",
      mcp_product_price: "Führe einen Preisvergleich für das iPhone 16 Pro 256GB durch und zeige die besten Händler-Angebote mit Preisen und Ersparnis in einer Tabelle",
      mcp_image: "male ein bild aus den neuesten nachrichten",
      mcp_weather: "Wie ist das aktuelle Wetter und die Temperatur in Berlin, München und Zürich im Vergleich? bereite es in eine tabelle auf",
      mcp_nasdaq: "Zeige die 5 Top Gewinner und Verlierer an der NASDAQ in einer Tabelle",
      mcp_bitcoin: "Wie steht der Bitcoin (BTC) und Ethereum (ETH) Kurs aktuell und was ist der 24h Trend?",
      mcp_news: "Welche aktuellen Nachrichten und Schlagzeilen meldet die Tagesschau heute?",
      python_fastapi: "Schreibe einen performanten Python-FastAPI-Endpunkt, der Requests an das OpenAI-kompatible /v1/chat/completions Gateway mit Streaming weiterleitet.",
      mcp_math: "Berechne mit der Python-Sandbox: Wie viel Endkapital erhalte ich bei 10.000 € Startkapital nach 10 Jahren bei 7% jährlicher Rendite mit Zinseszins?",
      gpu_sharding: "Erkläre wie Pipeline-Layer-Sharding große KI-Modelle effizient über mehrere GPUs aufteilt.",
      compare_costs: "Wie viel Geld kann ich mit ComputeMesh im Vergleich zu AWS oder Azure sparen?"
    },
    en: {
      explain_mesh: "What makes ComputeMesh unique and how does decentralized GPU inference work?",
      mcp_product_price: "Perform a price comparison for the iPhone 16 Pro 256GB and display the best merchant offers with prices and savings in a table",
      mcp_image: "paint an image based on the latest breaking news",
      mcp_weather: "What is the current weather and temperature in Berlin, Munich, and Zurich in comparison? Prepare it in a table",
      mcp_nasdaq: "Show the top 5 gainers and losers on the NASDAQ in a table",
      mcp_bitcoin: "What is the current Bitcoin (BTC) and Ethereum (ETH) market quote and 24h price trend?",
      mcp_news: "What are the latest breaking news and top headlines reported today?",
      python_fastapi: "Write a high-performance Python FastAPI streaming endpoint using the OpenAI-compatible /v1/chat/completions gateway.",
      mcp_math: "Calculate with the Python sandbox: What is the final capital on a $10,000 investment after 10 years at 7% annual compound interest?",
      gpu_sharding: "Explain how pipeline layer sharding efficiently distributes large AI models across multiple GPUs.",
      compare_costs: "How much money can I save with ComputeMesh compared to AWS or Azure?"
    }
  };

  window.applyQuickPrompt = function (promptKey) {
    const lang = getLang();
    const dict = (window.QUICK_PROMPTS && typeof window.QUICK_PROMPTS === 'object') ? window.QUICK_PROMPTS : QUICK_PROMPTS_FALLBACK;
    const prompt = (dict[lang] && dict[lang][promptKey]) || (dict.en && dict.en[promptKey]) || '';
    const inputEl = document.getElementById('playground-prompt-input');
    if (prompt && inputEl) {
      inputEl.value = prompt;
      inputEl.style.height = 'auto';
      inputEl.style.height = Math.min(Math.max(inputEl.scrollHeight, 60), 140) + 'px';
      inputEl.focus();
      inputEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  };

  if (typeof window.initPortal === 'function') {
    setupModalHooks();
    return;
  }
  const core = document.createElement('script');
  core.src = '/portal-core.js?v=5.4';
  core.async = false;
  core.onload = setupModalHooks;
  core.onerror = function () {
    const fallback = document.createElement('script');
    fallback.src = '/portal-core.js?v=5.4';
    fallback.async = false;
    fallback.onload = setupModalHooks;
    fallback.onerror = function () {
      console.error('ComputeMesh portal core failed to load');
    };
    document.head.appendChild(fallback);
  };
  document.head.appendChild(core);
})();
