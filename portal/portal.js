/* ==============================================================================
   ComputeMesh Portal Client Logic: i18n (DE/EN), Calculators & Subpages
   ============================================================================== */

const translations = {
  en: {
    nav_home: "Home",
    nav_features: "Features",
    nav_pricing: "Pricing & Calculator",
    nav_downloads: "Downloads",
    nav_docs: "API Docs",
    nav_benchmarks: "Benchmarks",
    nav_status: "Network Status",
    nav_register: "Register / API Key",
    
    hero_tagline: "Decentralized AI Compute Network",
    hero_title: "Run Big AI Models 80% Cheaper on Pooled GPU Compute",
    hero_sub: "Execute open-source AI models (Llama, DeepSeek & more) at a fraction of cloud costs or earn revenue by sharing your idle graphics cards and mining rigs.",
    btn_start_inferencing: "Run AI Models (API)",
    btn_provide_compute: "Provide GPU & Earn",
    
    ticker_gpus: "Active GPUs",
    ticker_vram: "Total VRAM",
    ticker_tokens: "Tokens Served",
    ticker_uptime: "Network Uptime",

    features_tag: "Decentralized Architecture",
    features_title: "Engineered for Ultra-Fast, Low-Cost Inference",
    features_sub: "ComputeMesh solves the high cost of centralized AI by pooling consumer GPUs, datacenter accelerators, and multi-GPU mining rigs.",
    
    feat1_title: "Pipeline Layer Sharding",
    feat1_desc: "Models are seamlessly split across distributed GPUs. Activation tensors transmit in microseconds, unlocking massive 32B+ models across 8GB cards.",
    
    feat2_title: "Native AMD & NVIDIA Dual-Stack",
    feat2_desc: "Full native support for NVIDIA CUDA, AMD ROCm, and universal Vulkan backends. Mix arbitrary GPUs in one rig with zero friction.",
    
    feat3_title: "80% Cost Reduction",
    feat3_desc: "Prepaid micro-credit billing and decentralized hardware yield drastic savings compared to traditional centralized hyperscalers.",
    
    feat4_title: "OpenAI-Compatible Gateway",
    feat4_desc: "Drop-in replacement for OpenAI SDKs and cURL. Simply switch your baseURL to start serving low-latency tokens immediately.",

    feat5_title: "Mining Rig NodeOS",
    feat5_desc: "Flashable USB appliance image turning 4–12 GPU Ethereum mining rigs into autonomous provider nodes in under 2 minutes.",

    feat6_title: "Verifiable Double-Entry Ledger",
    feat6_desc: "Every token computed is cryptographically metered and settled to an auditable append-only ledger for instant provider payouts.",

    calc_tag: "ROI & Economics",
    calc_title: "Calculate Your Savings or Earnings",
    calc_sub: "Transparent pay-as-you-go pricing for developers and high-yield passive revenue for hardware providers.",
    
    tab_developer: "Developer Cost Calculator",
    tab_provider: "Hardware Provider Earnings",
    
    lbl_monthly_tokens: "Monthly Inference Volume (Million Tokens)",
    lbl_model_tier: "Model Size Tier",
    lbl_computemesh_cost: "ComputeMesh Cost",
    lbl_cloud_cost: "Traditional Cloud Cost",
    lbl_your_savings: "Estimated Savings: ~80%",
    
    lbl_gpu_setup: "Your Hardware Setup",
    lbl_hours_online: "Uptime per Day (Hours)",
    lbl_est_earnings: "Estimated Monthly Earnings",
    lbl_payout_note: "Paid in USD/EUR or Crypto (USDT/USDC) upon reaching $25.00 minimum threshold",
    lbl_provider_threshold_info: "💡 Settlement Rule: Earnings accumulate in real-time per computed token on our verifiable ledger. Automated batch payouts trigger once your balance reaches the $25.00 threshold, protecting against high transaction fees during network ramp-up.",

    dl_tag: "One-Click Deploy",
    dl_title: "Download Node Installers & NodeOS Images",
    dl_sub: "Get started in seconds on Windows, Linux, or dedicated multi-GPU mining rigs.",
    
    dl_win_title: "Windows Provider Agent",
    dl_win_desc: "GUI tray app with automatic NVIDIA CUDA acceleration and background inference daemon.",
    dl_win_btn: "Download for Windows (.exe)",

    dl_linux_title: "Linux Headless Agent",
    dl_linux_desc: "One-command terminal installer for Ubuntu 22.04/24.04 and Debian 12/13 servers.",
    dl_linux_btn: "Copy Install Command",

    dl_rig_title: "Mining Rig Appliance (NodeOS)",
    dl_rig_desc: "Flashable USB disk image for 4–12 GPU mining rigs with native AMD & NVIDIA dual-stack auto-detection.",
    dl_rig_iso_btn: "Download Bootable ISO (.iso)",
    dl_rig_btn: "Download Flash Image (.img.xz)",

    api_tag: "Integration",
    api_title: "100% OpenAI API Compatible",
    api_sub: "Change one line of code in Python, TypeScript, or cURL to start routing requests through ComputeMesh.",

    modal_title: "Get Started with ComputeMesh",
    modal_sub: "Create an account to generate your API key or register your hardware node.",
    modal_role_lbl: "I want to:",
    role_consumer: "Use AI Models (Developer API)",
    role_provider: "Provide GPUs (Earn Revenue)",
    modal_email_lbl: "Email Address",
    modal_wallet_lbl: "Payout Wallet / Account (Optional)",
    modal_wallet_placeholder: "0x... (EVM / Ethereum) or SEPA IBAN",
    modal_wallet_help: "For GPU providers: Enter your Ethereum/EVM address (0x... from MetaMask, Rabby or exchange for USDC/USDT on Arbitrum, Polygon, Ethereum, Base) or your SEPA IBAN. Payouts trigger automatically once you reach $25 earned. Can be left empty and configured later.",
    modal_submit_btn: "Generate Credentials",
    modal_key_result_lbl: "Your Generated Key:",
    modal_copy_btn: "Copy Key",

    docs_tag: "Technical Documentation",
    docs_title: "ComputeMesh Architecture & Integration Guide",
    docs_sub: "Comprehensive developer references, OpenAI API compatibility specifications, and hardware node deployment manuals.",
    docs_toc: "Contents",
    docs_sec1_title: "1. OpenAI API Drop-in Quickstart",
    docs_sec1_desc: "ComputeMesh implements full drop-in compatibility with the standard OpenAI SDK and REST specification. You only need to set your base_url and pass your ComputeMesh API key.",
    docs_sec2_title: "2. Decentralized Mesh Architecture",
    docs_sec2_desc: "ComputeMesh connects consumer GPUs, professional cloud accelerators, and multi-GPU mining rigs through a low-latency, peer-to-peer execution topology.",
    docs_sec3_title: "3. Pipeline Layer Sharding & PCIe 1x Physics",
    docs_sec3_desc: "Unlike training workloads that require high-bandwidth all-reduce operations, autoregressive inference at batch size 1 only transmits the activation tensor of a single token (e.g. 8.2 KB for a 32B model). Across a 500 MB/s PCIe 1x mining riser, this transfer takes only 0.016 milliseconds.",
    docs_sec4_title: "4. Hardware Provider Node Setup",
    docs_sec4_desc: "Anyone with a modern GPU (NVIDIA, AMD, or Intel) can run a ComputeMesh provider agent. Nodes authenticate using asymmetric Ed25519 cryptography without exposing private keys.",
    docs_sec5_title: "5. Mining Rig NodeOS Appliance",
    docs_sec5_desc: "NodeOS is a headless appliance image based on Debian 13 that boots directly from a USB stick with native dual-stack driver detection and embedded dashboard.",
    docs_sec6_title: "6. Verifiable Ledger, Accounting & Settlement Rules",
    docs_sec6_desc: "ComputeMesh operates an auditable, append-only double-entry financial ledger. For every token generated by a hardware node, micro-units are credited directly to the provider's balance. To avoid prohibitive on-chain gas fees and payment overhead on micro-transactions, automated batch withdrawals require a minimum accumulated threshold of $25.00 USD (or equivalent in EUR / USDC / USDT). During the project's early ramp-up phase, workload is dynamically routed across active nodes, and all earnings remain permanent and secure on-ledger until the payout threshold is reached.",

    status_all_systems: "All Systems Operational",
    status_uptime_desc: "Decentralized inference mesh running at 99.98% global availability.",
    status_avg_latency: "Avg TTFT Latency",
    status_regional_title: "Regional Gateways & Sharding Clusters",

    benchmarks_tag: "Performance Metrics",
    benchmarks_title: "Decentralized Model Inference Benchmarks",
    benchmarks_sub: "Empirical tokens/second throughput and time-to-first-token (TTFT) across multi-GPU mining rigs and distributed coordinator-worker pairs.",

    terms_title: "Terms of Service & Provider Settlement Rules",
    terms_sec1_title: "1. Acceptance of Terms",
    terms_sec1_text: "By accessing or using the ComputeMesh decentralized compute platform, API gateway, or provider node software, you agree to be bound by these Terms of Service.",
    terms_sec2_title: "2. API Usage & Compute Credits (Consumers)",
    terms_sec2_text: "Developers and enterprise customers purchase prepaid compute credits in USD, EUR, or crypto (USDC/USDT). Consumption is billed strictly per processed token metered by our verifiable double-entry ledger.",
    terms_sec3_title: "3. Hardware Provider Obligations",
    terms_sec3_text: "Hardware providers supply GPU compute capacity using official ComputeMesh binaries. Providers are responsible for maintaining stable connectivity and truthful node telemetry during active sessions.",
    terms_sec4_title: "4. Provider Earnings, Real-Time Accounting & Minimum Payout Threshold ($25.00)",
    terms_sec4_text: "For each successfully served inference token, micro-credits are recorded in real-time to the provider's double-entry ledger account. To prevent disproportionate blockchain gas fees and payment processing charges on micro-transactions, automated payouts (via EVM wallet or SEPA) require a minimum accumulated balance of $25.00 USD (or equivalent EUR / USDC / USDT). Once your balance meets or exceeds this threshold, earnings are dispatched in the next automated settlement batch to your registered wallet address or IBAN.",
    terms_sec5_title: "5. Early Network Bootstrap & Ramp-Up Phase",
    terms_sec5_text: "During the initial bootstrap and growth phase of ComputeMesh, incoming inference workload is dynamically distributed across active nodes according to model demand. All earned credits are permanent, non-expiring, and securely preserved on the ledger until the $25.00 threshold is reached. No fixed daily yield or minimum capacity utilization is guaranteed during early network bootstrapping.",
    terms_sec6_title: "6. Limitation of Liability & Disclaimers",
    terms_sec6_text: "ComputeMesh provides decentralized orchestration software on an 'as-is' and 'as-available' basis without warranties of uninterrupted uptime or constant node utilization.",
    privacy_title: "Privacy Policy",
    impressum_title: "Impressum / Legal Notice",
    impressum_meta: "Information pursuant to § 5 DDG (Digital Services Act) and § 18 Abs. 2 MStV",
    impressum_provider_hdr: "Service Provider & Address",
    impressum_contact_hdr: "Contact",
    impressum_responsible_hdr: "Responsible for content pursuant to § 18 Abs. 2 MStV",
    impressum_liability_content_hdr: "Liability for Contents",
    impressum_liability_content_text: "As a service provider, we are responsible for our own content on these pages under general law. However, we are not obligated to monitor transmitted or stored third-party information or to investigate circumstances that indicate illegal activity.",
    impressum_liability_links_hdr: "Liability for Links",
    impressum_liability_links_text: "Our offer may contain links to external third-party websites over whose content we have no influence. Therefore, we cannot assume any liability for these external contents.",
    impressum_copyright_hdr: "Copyright",
    impressum_copyright_text: "The contents, source codes, and works created by the site operators on these pages are subject to German copyright law. Duplication, editing, distribution, and any kind of exploitation outside the limits of copyright law require written consent.",

    contact_tag: "Get in Touch",
    contact_title: "Support & Community Helpdesk",
    contact_sub: "Have questions about running a provider mining rig, integrating our OpenAI API, or purchasing enterprise compute credits?",
    contact_name_lbl: "Your Name",
    contact_topic_lbl: "Topic",
    contact_msg_lbl: "Message",
    contact_send_btn: "Send Message",
    contact_success: "✓ Your message has been sent successfully! Our engineering team will respond within 24 hours.",
    nav_topup: "💳 Top Up Credits",
    topup_modal_title: "💳 Top Up Compute Credits",
    topup_modal_sub: "Purchase prepaid micro-credits via instant Stripe Checkout (Credit Card, SEPA, Apple Pay).",
    topup_key_lbl: "Your API Key:",
    topup_amount_lbl: "Select Deposit Tier:",
    topup_submit_btn: "Proceed to Stripe Checkout →",
    playground_title: "⚡ Live In-Browser API Playground",
    playground_send: "▶ Run Inference",

    footer_rights: "All rights reserved. Decentralized AI Mesh Architecture.",
  },
  
  de: {
    nav_home: "Startseite",
    nav_features: "Funktionen",
    nav_pricing: "Preise & Rechner",
    nav_downloads: "Downloads",
    nav_docs: "API Dokumentation",
    nav_benchmarks: "Benchmarks",
    nav_status: "Netzwerk-Status",
    nav_register: "Registrieren / API-Key",
    
    hero_tagline: "Dezentrales KI-Rechennetzwerk",
    hero_title: "Große KI-Modelle 80% günstiger berechnen – auf geteilter GPU-Power",
    hero_sub: "Nutze Open-Source-KI (Llama, DeepSeek & Co.) zu einem Bruchteil der Cloud-Kosten oder verdiene Geld, indem du deine ungenutzten Grafikkarten & Mining-Rigs vermietest.",
    btn_start_inferencing: "KI-Modelle nutzen (API)",
    btn_provide_compute: "GPU vermieten & verdienen",
    
    ticker_gpus: "Aktive GPUs",
    ticker_vram: "Gesamter VRAM",
    ticker_tokens: "Verarbeitete Tokens",
    ticker_uptime: "Netzwerk-Verfügbarkeit",

    features_tag: "Dezentrale Architektur",
    features_title: "Entwickelt für ultraschnelle, bezahlbare KI",
    features_sub: "ComputeMesh löst die hohen Kosten zentraler Anbieter durch das Bündeln von Consumer-GPUs, Server-Beschleunigern und Multi-GPU-Mining-Rigs.",
    
    feat1_title: "Pipeline Layer-Sharding",
    feat1_desc: "Modelle werden nahtlos über mehrere GPUs verteilt. Aktivierungstensoren werden in Mikrosekunden übertragen – 32B+ Modelle laufen auf 8GB-Karten.",
    
    feat2_title: "Natives AMD & NVIDIA Dual-Stack",
    feat2_desc: "Vollständige Unterstützung für NVIDIA CUDA, AMD ROCm und universelles Vulkan. Mische beliebige Karten in einem Rig völlig reibungslos.",
    
    feat3_title: "80% Kostenersparnis",
    feat3_desc: "Prepaid-Abrechnung in Mikro-Credits und dezentrale Hardware senken die Kosten gegenüber herkömmlichen Cloud-Hyperscalern drastisch.",
    
    feat4_title: "OpenAI-kompatibles Gateway",
    feat4_desc: "Direkter Ersatz für OpenAI SDKs und cURL. Ändere einfach die baseURL, um sofort kostengünstige Tokens zu generieren.",

    feat5_title: "Mining-Rig NodeOS",
    feat5_desc: "Flashbares USB-Betriebssystem-Image, das 4–12 GPU Ethereum-Mining-Rigs in unter 2 Minuten in autonome Provider-Knoten verwandelt.",

    feat6_title: "Verifizierbares Hauptbuch (Ledger)",
    feat6_desc: "Jedes berechnete Token wird kryptografisch erfasst und unveränderlich in einem Buchungssystem verbucht – für automatische Auszahlungen.",

    calc_tag: "Wirtschaftlichkeit & Ertrag",
    calc_title: "Berechne deine Ersparnis oder Einnahmen",
    calc_sub: "Transparente Pay-As-You-Go-Preise für Entwickler und lukrative passive Einnahmen für Hardware-Betreiber.",
    
    tab_developer: "Entwickler-Kostenrechner",
    tab_provider: "Hardware-Ertragsrechner",
    
    lbl_monthly_tokens: "Monatliches Token-Volumen (Millionen Tokens)",
    lbl_model_tier: "Modellgröße",
    lbl_computemesh_cost: "ComputeMesh Kosten",
    lbl_cloud_cost: "Herkömmliche Cloud Kosten",
    lbl_your_savings: "Geschätzte Ersparnis: ~80%",
    
    lbl_gpu_setup: "Deine Hardware-Ausstattung",
    lbl_hours_online: "Laufzeit pro Tag (Stunden)",
    lbl_est_earnings: "Geschätzter Monatsverdienst",
    lbl_payout_note: "Auszahlung in USD/EUR oder Krypto (USDC/USDT) ab 25,00 $ Mindestguthaben",
    lbl_provider_threshold_info: "💡 Auszahlungsregel: Erträge werden in Echtzeit pro berechnetem Token im Ledger verbucht. Die automatische Auszahlung wird ausgelöst, sobald dein Guthaben 25,00 $ erreicht, um unverhältnismäßige Gebühren in der Anlaufphase zu vermeiden.",

    dl_tag: "1-Klick-Installation",
    dl_title: "Node-Installer & NodeOS-Images herunterladen",
    dl_sub: "Starte in Sekunden auf Windows, Linux oder dedizierten Multi-GPU-Mining-Rigs.",
    
    dl_win_title: "Windows Provider Agent",
    dl_win_desc: "Desktop-App im System-Tray mit automatischer NVIDIA CUDA-Erkennung und Hintergrunddienst.",
    dl_win_btn: "Für Windows herunterladen (.exe)",

    dl_linux_title: "Linux Headless Agent",
    dl_linux_desc: "1-Befehl Terminal-Installer für Ubuntu 22.04/24.04 und Debian 12/13 Server.",
    dl_linux_btn: "Installationsbefehl kopieren",

    dl_rig_title: "Mining-Rig Appliance (NodeOS)",
    dl_rig_desc: "Flashbares USB-Disk-Image für 4–12 GPU Mining-Rigs mit nativer AMD & NVIDIA Auto-Erkennung.",
    dl_rig_iso_btn: "Bootfähiges ISO herunterladen (.iso)",
    dl_rig_btn: "Flash-Image herunterladen (.img.xz)",

    api_tag: "Integration",
    api_title: "100% OpenAI API-kompatibel",
    api_sub: "Ändere eine einzige Zeile Code in Python, TypeScript oder cURL, um Anfragen über ComputeMesh zu leiten.",

    modal_title: "Jetzt bei ComputeMesh starten",
    modal_sub: "Erstelle ein Konto, um deinen API-Schlüssel zu generieren oder deinen Hardware-Knoten zu registrieren.",
    modal_role_lbl: "Ich möchte:",
    role_consumer: "KI-Modelle nutzen (Entwickler-API)",
    role_provider: "Grafikkarten vermieten (Geld verdienen)",
    modal_email_lbl: "E-Mail-Adresse",
    modal_wallet_lbl: "Auszahlungs-Wallet / Konto (Optional)",
    modal_wallet_placeholder: "0x... (EVM / Ethereum) oder SEPA-IBAN",
    modal_wallet_help: "Für GPU-Provider: Gib deine Ethereum/EVM-Adresse (0x... aus MetaMask, Rabby oder Krypto-Börse für USDC/USDT auf Arbitrum, Polygon, Ethereum, Base) oder deine SEPA-IBAN an. Auszahlungen erfolgen automatisch ab 25 $ erwirtschaftetem Guthaben. Kann auch leer gelassen und später hinterlegt werden.",
    modal_submit_btn: "Zugangsdaten generieren",
    modal_key_result_lbl: "Dein generierter Schlüssel:",
    modal_copy_btn: "Schlüssel kopieren",

    docs_tag: "Technische Dokumentation",
    docs_title: "ComputeMesh Architektur- & Integrationshandbuch",
    docs_sub: "Umfassende Entwickler-Referenzen, OpenAI-API-Spezifikationen und Installationsanleitungen für Hardware-Knoten.",
    docs_toc: "Inhalt",
    docs_sec1_title: "1. OpenAI-API Schnellstart (Drop-in)",
    docs_sec1_desc: "ComputeMesh bietet vollständige Kompatibilität mit dem offiziellen OpenAI SDK. Es genügt die baseURL anzupassen und deinen ComputeMesh API-Key zu übergeben.",
    docs_sec2_title: "2. Dezentrale Mesh-Architektur",
    docs_sec2_desc: "ComputeMesh verbindet Consumer-Grafikkarten, Cloud-Server und Mining-Rigs über eine latenzoptimierte Peer-to-Peer-Struktur.",
    docs_sec3_title: "3. Pipeline Layer-Sharding & PCIe-1x Physik",
    docs_sec3_desc: "Im Gegensatz zum Modelltraining überträgt die Textgenerierung (Inferenz) bei Batch-Größe 1 lediglich den Aktivierungs-Vektor eines einzelnen Tokens (z. B. 8.2 KB bei 32B-Modellen). Über einen 500 MB/s PCIe-1x-Riser dauert diese Übertragung nur 0,016 Millisekunden.",
    docs_sec4_title: "4. Provider-Node einrichten",
    docs_sec4_desc: "Jeder mit einer modernen Grafikkarte (NVIDIA, AMD oder Intel) kann einen Provider-Agenten betreiben. Die Knoten authentifizieren sich kryptografisch mit Ed25519.",
    docs_sec5_title: "5. Mining-Rig NodeOS Appliance",
    docs_sec5_desc: "NodeOS ist ein USB-Betriebssystem-Image auf Debian 13-Basis mit automatischer AMD- und NVIDIA-Treibererkennung und integriertem Dashboard.",
    docs_sec6_title: "6. Verifizierbares Ledger, Abrechnung & Auszahlungsregeln",
    docs_sec6_desc: "ComputeMesh betreibt ein manipulationssicheres Doppelbuchhaltungs-Ledger. Für jedes generierte Token werden Mikro-Einheiten in Echtzeit dem Provider-Konto gutgeschrieben. Um unverhältnismäßige Gas- und Transaktionsgebühren bei Kleinstbeträgen zu vermeiden, gilt ein Mindestauszahlungsbetrag von 25,00 USD (bzw. 25 EUR / 25 USDC/USDT). In der Anlaufphase des Netzwerks wächst das Auftragsvolumen mit der Modellnachfrage; Guthaben verfällt niemals und bleibt sicher verbucht.",

    status_all_systems: "Alle Systeme betriebsbereit",
    status_uptime_desc: "Dezentrales Inferenz-Netzwerk läuft mit 99,98% weltweiter Verfügbarkeit.",
    status_avg_latency: "Durchschnittliche Latenz (TTFT)",
    status_regional_title: "Regionale Gateways & Sharding-Cluster",

    benchmarks_tag: "Leistungskennzahlen",
    benchmarks_title: "Dezentrale Modell-Inferenz Benchmarks",
    benchmarks_sub: "Gemessene Token/Sekunde-Durchsätze und Latenzen über Multi-GPU-Mining-Rigs und verteilte Knoten.",

    terms_title: "Allgemeine Geschäfts- und Nutzungsbedingungen (AGB)",
    terms_sec1_title: "1. Geltungsbereich und Vertragspartner",
    terms_sec1_text: "Durch den Zugriff auf oder die Nutzung der dezentralen ComputeMesh-Plattform, des API-Gateways oder der Provider-Node-Software erklärst du dich mit diesen Nutzungsbedingungen einverstanden.",
    terms_sec2_title: "2. API-Nutzung und Rechenguthaben (Consumer)",
    terms_sec2_text: "Entwickler und Unternehmenskunden erwerben Prepaid-Rechenguthaben (in USD, EUR oder Krypto/USDC/USDT). Die Abrechnung erfolgt nutzungsbasiert pro verarbeitetem Token über unser manipulationssicheres Doppelbuchhaltungs-Ledger.",
    terms_sec3_title: "3. Pflichten der Hardware-Provider",
    terms_sec3_text: "Hardware-Provider stellen GPU-Rechenleistung über die offizielle ComputeMesh-Software bereit. Provider sind dafür verantwortlich, dass ihre Knoten eine stabile Netzwerkverbindung aufweisen und korrekte Telemetrie- und Leistungswerte übermitteln.",
    terms_sec4_title: "4. Vergütung, Ertragsverbuchung und Mindestauszahlungsgrenze (25,00 $ Payout Threshold)",
    terms_sec4_text: "Für jede erfolgreich bereitgestellte Recheneinheit (Inferenz-Token) wird dem internen Provider-Konto in Echtzeit ein Vergütungsbetrag in Mikro-Einheiten gutgeschrieben. Um unverhältnismäßige Netzwerk- und Transaktionsgebühren (Gas Fees / Bankspesen) bei Kleinstbeträgen zu vermeiden, gilt für alle Auszahlungen (Krypto oder Banküberweisung) ein Mindestauszahlungsbetrag von 25,00 USD (bzw. 25 EUR / 25 USDC/USDT). Sobald dieser Schwellenwert auf dem Ledger erreicht oder überschritten ist, wird die Auszahlung im nächsten automatisierten Abrechnungszyklus an die hinterlegte Wallet-Adresse oder IBAN veranlasst.",
    terms_sec5_title: "5. Besonderheiten der Projekt- und Anlaufphase (Bootstrap Phase)",
    terms_sec5_text: "In der frühen Wachstums- und Aufbauphase des ComputeMesh-Netzwerks wird das Auftragsvolumen dynamisch anhand der realen Kundenanfragen und Modellnachfrage auf aktive Knoten verteilt. Erwirtschaftete Teilbeträge verfallen niemals und bleiben unveränderlich im Ledger gespeichert, bis das Auszahlungslimit von 25,00 $ erreicht ist. Es besteht in der Anlaufphase kein Anspruch auf eine garantierte Mindestauslastung oder feste Tageserträge.",
    terms_sec6_title: "6. Haftungsbeschränkung und Verfügbarkeit",
    terms_sec6_text: "ComputeMesh stellt die dezentrale Koordinations- und Vermittlungsplattform 'wie besehen' ('as-is') und vorbehaltlich technischer Verfügbarkeit bereit. Eine ununterbrochene Verfügbarkeit oder ein bestimmter Mindestdurchsatz kann bei dezentral verteilten Knotenstrukturen nicht garantiert werden.",
    privacy_title: "Datenschutzerklärung",
    impressum_title: "Impressum",
    impressum_meta: "Angaben gemäß § 5 DDG (Digitale-Dienste-Gesetz) und § 18 Abs. 2 MStV",
    impressum_provider_hdr: "Diensteanbieter & Anschrift",
    impressum_contact_hdr: "Kontakt",
    impressum_responsible_hdr: "Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV",
    impressum_liability_content_hdr: "Haftung für Inhalte",
    impressum_liability_content_text: "Als Diensteanbieter sind wir gemäß den allgemeinen Gesetzen für eigene Inhalte auf diesen Seiten verantwortlich. Wir sind jedoch nicht verpflichtet, übermittelte oder gespeicherte fremde Informationen zu überwachen oder nach Umständen zu forschen, die auf eine rechtswidrige Tätigkeit hinweisen. Verpflichtungen zur Entfernung oder Sperrung der Nutzung von Informationen nach den allgemeinen Gesetzen bleiben hiervon unberührt.",
    impressum_liability_links_hdr: "Haftung für Links",
    impressum_liability_links_text: "Unser Angebot enthält ggf. Links zu externen Websites Dritter, auf deren Inhalte wir keinen Einfluss haben. Deshalb können wir für diese fremden Inhalte auch keine Gewähr übernehmen. Für die Inhalte der verlinkten Seiten ist stets der jeweilige Anbieter oder Betreiber der Seiten verantwortlich.",
    impressum_copyright_hdr: "Urheberrecht",
    impressum_copyright_text: "Die durch die Seitenbetreiber erstellten Inhalte, Quellcodes und Werke auf diesen Seiten unterliegen dem deutschen Urheberrecht. Die Vervielfältigung, Bearbeitung, Verbreitung und jede Art der Verwertung außerhalb der Grenzen des Urheberrechtes bedürfen der schriftlichen Zustimmung des jeweiligen Autors bzw. Erstellers.",

    contact_tag: "Kontakt & Hilfe",
    contact_title: "Support & Community Helpdesk",
    contact_sub: "Hast du Fragen zum Betrieb eines Mining-Rigs, zur API-Integration oder zum Erwerb von Rechenguthaben?",
    contact_name_lbl: "Dein Name",
    contact_topic_lbl: "Thema",
    contact_msg_lbl: "Nachricht",
    contact_send_btn: "Nachricht absenden",
    nav_topup: "💳 Guthaben aufladen",
    topup_modal_title: "💳 Rechenguthaben aufladen",
    topup_modal_sub: "Prepaid-Mikro-Credits sofort via Stripe Checkout aufladen (Kreditkarte, SEPA, Apple Pay).",
    topup_key_lbl: "Dein API-Schlüssel:",
    topup_amount_lbl: "Guthaben-Paket wählen:",
    topup_submit_btn: "Weiter zu Stripe Checkout →",
    playground_title: "⚡ Live In-Browser API Playground",
    playground_send: "▶ Inferenz starten",

    footer_rights: "Alle Rechte vorbehalten. Dezentrale KI-Mesh-Architektur.",
  }
};

let currentLang = 'en';

function switchLanguage(lang) {
  currentLang = lang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (translations[lang] && translations[lang][key]) {
      if (el.tagName === 'INPUT' && el.getAttribute('placeholder')) {
        el.setAttribute('placeholder', translations[lang][key]);
      } else {
        el.textContent = translations[lang][key];
      }
    }
  });
  const btn = document.getElementById('lang-toggle-btn');
  if (btn) {
    btn.textContent = lang === 'en' ? '🇩🇪 Deutsch' : '🇬🇧 English';
  }
  localStorage.setItem('cm_portal_lang', lang);
  updateCalculators();
}

function toggleLanguage() {
  const nextLang = currentLang === 'en' ? 'de' : 'en';
  switchLanguage(nextLang);
}

// Pricing Calculators
function updateCalculators() {
  // Developer Calculator
  const tokensM = parseFloat(document.getElementById('slider-tokens')?.value || 50);
  const modelTier = document.getElementById('select-model')?.value || '8b';
  
  let ratePerMillion = 0.20; // 8B base
  let cloudRate = 1.00;
  
  if (modelTier === '14b') { ratePerMillion = 0.35; cloudRate = 1.75; }
  else if (modelTier === '32b') { ratePerMillion = 0.70; cloudRate = 3.50; }
  else if (modelTier === '70b') { ratePerMillion = 1.40; cloudRate = 7.00; }
  
  const cmCost = (tokensM * ratePerMillion).toFixed(2);
  const cloudCost = (tokensM * cloudRate).toFixed(2);
  
  const cmEl = document.getElementById('calc-cm-cost');
  const cloudEl = document.getElementById('calc-cloud-cost');
  const tokensVal = document.getElementById('tokens-val');
  
  if (cmEl) cmEl.textContent = `$${cmCost}`;
  if (cloudEl) cloudEl.textContent = `$${cloudCost}`;
  if (tokensVal) tokensVal.textContent = `${tokensM} M`;

  // Provider Calculator
  const rigType = document.getElementById('select-rig')?.value || '5x8gb';
  const hours = parseFloat(document.getElementById('slider-hours')?.value || 24);
  
  let monthlyYield = 145.0; // 5x 8GB base
  if (rigType === 'rtx3080') monthlyYield = 65.0;
  else if (rigType === 'rtx4090') monthlyYield = 195.0;
  else if (rigType === '8x3070') monthlyYield = 310.0;
  
  const estEarnings = ((monthlyYield * (hours / 24))).toFixed(2);
  const earnEl = document.getElementById('calc-provider-earnings');
  const hoursVal = document.getElementById('hours-val');
  
  if (earnEl) earnEl.textContent = `$${estEarnings} / Mo`;
  if (hoursVal) hoursVal.textContent = `${hours} h/day`;
}

function showTab(tabName) {
  document.querySelectorAll('.calc-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.calc-pane').forEach(p => p.style.display = 'none');
  
  if (tabName === 'dev') {
    document.getElementById('tab-dev-btn')?.classList.add('active');
    const pane = document.getElementById('pane-dev');
    if (pane) pane.style.display = 'grid';
  } else {
    document.getElementById('tab-prov-btn')?.classList.add('active');
    const pane = document.getElementById('pane-prov');
    if (pane) pane.style.display = 'grid';
  }
}

// Modal Registration
function openModal(role = 'consumer') {
  const modal = document.getElementById('register-modal');
  if (modal) modal.classList.add('active');
  const select = document.getElementById('modal-role');
  if (select) select.value = role;
}

function closeModal() {
  const modal = document.getElementById('register-modal');
  if (modal) modal.classList.remove('active');
  const resBox = document.getElementById('modal-result-box');
  if (resBox) resBox.style.display = 'none';
}

function handleRegistration(e) {
  e.preventDefault();
  const role = document.getElementById('modal-role').value;
  const prefix = role === 'consumer' ? 'cm_live_' : 'cm_node_';
  const randomHex = Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map(b => b.toString(16).padStart(2, '0')).join('');
  const generatedKey = prefix + randomHex;
  
  const keyInput = document.getElementById('generated-key-val');
  if (keyInput) keyInput.value = generatedKey;
  
  const resBox = document.getElementById('modal-result-box');
  if (resBox) resBox.style.display = 'block';
}

function copyKey() {
  const keyInput = document.getElementById('generated-key-val');
  if (keyInput) {
    navigator.clipboard.writeText(keyInput.value);
    alert(currentLang === 'de' ? 'Schlüssel in Zwischenablage kopiert!' : 'Key copied to clipboard!');
  }
}

function copyLinuxCommand() {
  const cmd = "curl -fsSL https://get.computemesh.net/install.sh | sudo bash";
  navigator.clipboard.writeText(cmd);
  alert(currentLang === 'de' ? 'Befehl kopiert!' : 'Command copied!');
}

function openDepositModal() {
  const modal = document.getElementById('deposit-modal');
  if (modal) modal.classList.add('active');
  const msgBox = document.getElementById('deposit-msg-box');
  if (msgBox) msgBox.style.display = 'none';
}

function closeDepositModal() {
  const modal = document.getElementById('deposit-modal');
  if (modal) modal.classList.remove('active');
}

async function handleDepositSubmit(e) {
  e.preventDefault();
  const keyInput = document.getElementById('deposit-key-input');
  const amountSelect = document.getElementById('deposit-amount-select');
  const msgBox = document.getElementById('deposit-msg-box');
  const btn = document.getElementById('deposit-submit-btn');

  if (!keyInput || !amountSelect || !msgBox) return;

  const apiKey = keyInput.value.trim();
  const amountUsd = parseFloat(amountSelect.value);

  if (!apiKey) {
    alert(currentLang === 'de' ? 'Bitte gib deinen API-Schlüssel ein.' : 'Please enter your API key.');
    return;
  }

  btn.disabled = true;
  btn.textContent = currentLang === 'de' ? 'Erstelle Checkout-Session...' : 'Creating checkout session...';
  msgBox.style.display = 'block';
  msgBox.style.background = 'rgba(0, 242, 254, 0.1)';
  msgBox.style.color = 'var(--primary)';
  msgBox.textContent = currentLang === 'de' ? 'Verbinde mit Stripe...' : 'Connecting to Stripe...';

  try {
    const res = await fetch('/v1/billing/checkout', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      },
      body: JSON.stringify({ amount_usd: amountUsd })
    });

    if (!res.ok) {
      const err = await res.text();
      msgBox.style.background = 'rgba(239, 68, 68, 0.15)';
      msgBox.style.color = 'var(--accent-red)';
      msgBox.textContent = `Error: ${err}`;
      btn.disabled = false;
      btn.textContent = currentLang === 'de' ? 'Weiter zu Stripe Checkout →' : 'Proceed to Stripe Checkout →';
      return;
    }

    const data = await res.json();
    msgBox.style.background = 'rgba(16, 185, 129, 0.15)';
    msgBox.style.color = 'var(--accent-emerald)';
    msgBox.innerHTML = `✓ Checkout Session created! <a href="${data.checkout_url}" target="_blank" style="color: #00f2fe; text-decoration: underline; font-weight: bold;">Click here to complete payment on Stripe →</a>`;

    // Automatically open Stripe checkout in a new window/tab
    window.open(data.checkout_url, '_blank');
  } catch (err) {
    msgBox.style.background = 'rgba(239, 68, 68, 0.15)';
    msgBox.style.color = 'var(--accent-red)';
    msgBox.textContent = `Network Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = currentLang === 'de' ? 'Weiter zu Stripe Checkout →' : 'Proceed to Stripe Checkout →';
  }
}

function handleContactSubmit(e) {
  e.preventDefault();
  const msgEl = document.getElementById('contact-success-msg');
  if (msgEl) {
    msgEl.style.display = 'block';
  }
}

async function runPlaygroundPrompt() {
  const modelEl = document.getElementById('playground-model');
  const inputEl = document.getElementById('playground-input');
  const outputEl = document.getElementById('playground-output');
  const statsEl = document.getElementById('playground-stats');
  const btnEl = document.getElementById('playground-btn');

  if (!modelEl || !inputEl || !outputEl || !statsEl) return;

  const model = modelEl.value;
  const prompt = inputEl.value.trim();
  if (!prompt) return;

  outputEl.textContent = "";
  statsEl.textContent = "Connecting to distributed mesh...";
  statsEl.style.color = "var(--primary)";
  if (btnEl) btnEl.disabled = true;

  const startTime = performance.now();
  let tokenCount = 0;

  try {
    const response = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer cm_live_playground_guest_token'
      },
      body: JSON.stringify({
        model: model,
        messages: [{ role: 'user', content: prompt }],
        stream: true
      })
    });

    if (!response.ok) {
      const errText = await response.text();
      outputEl.textContent = `Error (${response.status}): ${errText}`;
      statsEl.textContent = "Inference Failed";
      statsEl.style.color = "var(--accent-red)";
      if (btnEl) btnEl.disabled = false;
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith("data: ")) {
          const dataStr = trimmed.slice(6);
          if (dataStr === "[DONE]") {
            break;
          }
          try {
            const parsed = JSON.parse(dataStr);
            const delta = parsed.choices?.[0]?.delta?.content || "";
            if (delta) {
              outputEl.textContent += delta;
              tokenCount++;
              const elapsedSec = (performance.now() - startTime) / 1000;
              const tps = (tokenCount / elapsedSec).toFixed(1);
              statsEl.textContent = `Streaming: ${tokenCount} tokens • ${tps} tok/s`;
            }
          } catch (e) {
            // Ignore partial SSE JSON parse
          }
        }
      }
    }

    const totalElapsedSec = ((performance.now() - startTime) / 1000).toFixed(2);
    const finalTps = (tokenCount / (totalElapsedSec > 0 ? totalElapsedSec : 1)).toFixed(1);
    statsEl.textContent = `✓ Completed in ${totalElapsedSec}s • ${tokenCount} tokens • ${finalTps} tok/s • Cost: ~$0.0001`;
    statsEl.style.color = "var(--accent-emerald)";
  } catch (err) {
    outputEl.textContent = `Network Error: Could not connect to API gateway.\n${err.message}`;
    statsEl.textContent = "Connection Error";
    statsEl.style.color = "var(--accent-red)";
  } finally {
    if (btnEl) btnEl.disabled = false;
  }
}

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  const savedLang = localStorage.getItem('cm_portal_lang') || 'en';
  switchLanguage(savedLang);
  
  document.getElementById('slider-tokens')?.addEventListener('input', updateCalculators);
  document.getElementById('select-model')?.addEventListener('change', updateCalculators);
  document.getElementById('select-rig')?.addEventListener('change', updateCalculators);
  document.getElementById('slider-hours')?.addEventListener('input', updateCalculators);
  
  updateCalculators();
});
