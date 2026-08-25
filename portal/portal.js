/* ==============================================================================
   ComputeMesh Portal Client Logic: i18n (DE/EN), Calculators & Subpages
   ============================================================================== */

const translations = {
  en: {
    nav_home: "Home",
    nav_features: "Features",
    nav_pricing: "Pricing",
    nav_downloads: "Downloads",
    nav_docs: "API Docs",
    nav_benchmarks: "Benchmarks",
    nav_status: "Status",
    nav_register: "API Key",
    
    hero_tagline: "Decentralized AI Compute Network",
    hero_title: "Run Big AI Models 80% Cheaper <br><span class=\"gradient-text\">on Pooled GPU Compute</span>",
    hero_sub: "Execute open-source AI models (Llama, DeepSeek & more) at a fraction of cloud costs or earn revenue by sharing your idle graphics cards and mining rigs.",
    btn_start_inferencing: "Run AI Models (API)",
    btn_provide_compute: "Provide GPU & Earn",
    
    ticker_vram: "Total Usable VRAM Pool",
    ticker_gpus: "Active GPUs (AMD & NVIDIA)",
    ticker_tokens: "Two-Node Proof (ADR-0002)",
    ticker_uptime: "vs. Cloud Hyperscalers",

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
    lbl_payout_note: "Stripe-backed payouts from $25; MetaMask only sets a provider payout address",
    lbl_provider_threshold_info: "💡 <strong>Provider earnings:</strong> Real-time on-ledger accounting per token. Customer payments are handled through Stripe. Your 0x... wallet is only a payout destination for earnings from provided compute power.",

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
    modal_wallet_lbl: "Provider Payout Wallet (Optional)",
    modal_wallet_placeholder: "0x... (EVM / Ethereum / Polygon / Arbitrum)",
    modal_wallet_help: "For GPU providers only: enter the 0x address that should receive earnings from contributed compute power. MetaMask is only an address picker here. Buying compute credits and all customer payments are handled through Stripe.",
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
    docs_sec6_title: "6. Verifiable Ledger, Accounting & 2-Tier Settlement Rules",
    docs_sec6_desc: "ComputeMesh operates an auditable, append-only double-entry financial ledger. For every token generated by a hardware node, micro-units are credited directly to the provider's balance after the 25% platform fee. Customer payments for compute credits are processed through Stripe. MetaMask is used only to select a provider payout destination address for earned compute revenue, never to buy compute credits.",

    status_all_systems: "Genesis Network & Public Alpha Active",
    status_uptime_desc: "ComputeMesh Genesis Bootstrap Phase is live. Developer testnet API and provider node onboarding open.",
    status_avg_latency: "EU-Central Gateway Latency",
    status_regional_title: "Operational Gateways & Verified Clusters",

    benchmarks_tag: "Performance Metrics",
    benchmarks_title: "Decentralized Model Inference Benchmarks",
    benchmarks_sub: "Empirical tokens/second throughput and time-to-first-token (TTFT) across multi-GPU mining rigs and distributed coordinator-worker pairs.",

    terms_title: "Terms of Service & Provider Settlement Rules",
    terms_sec1_title: "1. Acceptance of Terms",
    terms_sec1_text: "By accessing or using the ComputeMesh decentralized compute platform, API gateway, or provider node software, you agree to be bound by these Terms of Service.",
    terms_sec2_title: "2. API Usage & Compute Credits (Consumers)",
    terms_sec2_text: "Developers and enterprise customers purchase prepaid compute credits through Stripe-supported payment methods. Wallets such as MetaMask are not used to buy compute credits. Consumption is billed strictly per processed token metered by our verifiable double-entry ledger.",
    terms_sec3_title: "3. Hardware Provider Obligations",
    terms_sec3_text: "Hardware providers supply GPU compute capacity using official ComputeMesh binaries. Providers are responsible for maintaining stable connectivity and truthful node telemetry during active sessions.",
    terms_sec4_title: "4. Provider Earnings, Real-Time Accounting, Fully-Backed Settlement & 2-Tier Payout System ($25.00 Threshold)",
    terms_sec4_text: "For each successfully served inference token, a revenue share of 75% of the metered token price is credited in micro-units to the provider's ledger account in real time. Payout entitlements operate strictly under the fully-backed revenue principle: withdrawals are disbursed exclusively from cleared, non-reversible consumer payments actually received and settled through Stripe. A registered 0x... EVM wallet, selected manually or through MetaMask, is only a provider payout destination and is never charged for compute-credit purchases.",
    terms_sec5_title: "5. Network Bootstrap Phase, Alpha Testing & Promotional Test Credits",
    terms_sec5_text: "During the initial bootstrap and growth phase of ComputeMesh, compute workload is dynamically routed according to organic model demand. Free promotional credits, trial balances, and testnet tokens granted to consumers for testing purposes constitute non-monetary test allocations and explicitly do not generate cash withdrawal liabilities against the platform operator. Earnings derived from paid customer usage never expire and remain permanently ledger-recorded until the $25.00 threshold is reached.",
    terms_sec6_title: "6. Payment Service Providers, Stripe Express & Escrow Management",
    terms_sec6_text: "All real customer payments for compute credits are processed through Stripe, Inc. (and Stripe Payments Europe, Ltd.) using Stripe-supported payment methods. Provider bank payouts are planned through Stripe Connect where available. Crypto wallets are stored only as public payout destination addresses for provider earnings and are not used to collect or pull customer payments.",
    terms_sec7_title: "7. Limitation of Liability & Disclaimers",
    terms_sec7_text: "ComputeMesh provides decentralized orchestration software on an 'as-is' and 'as-available' basis without warranties of uninterrupted uptime or constant node utilization.",
    privacy_title: "Privacy Policy & Data Security Standards",
    privacy_sec1_title: "1. Absolute Zero Prompt Logging & Ephemeral VRAM Processing",
    privacy_sec1_text: "ComputeMesh operates under a strict, mathematically guaranteed Zero-Log Policy. User prompts and generated model responses are NEVER written to persistent disks, never stored in databases, and never used for model training. Inference activations exist solely in volatile GPU VRAM during real-time streaming and are wiped from memory immediately upon request completion.",
    privacy_sec2_title: "2. Military-Grade End-to-End Encryption in Transit (TLS 1.3 & mTLS)",
    privacy_sec2_text: "All communications between client applications and our edge gateways are strictly encrypted via TLS 1.3 with Perfect Forward Secrecy (PFS). Internal communications across distributed provider nodes use mutual TLS (mTLS) with cryptographically authenticated Ed25519/X25519 handshakes, preventing eavesdropping, tampering, or man-in-the-middle attacks.",
    privacy_sec3_title: "3. Data-at-Rest Encryption (AES-256-GCM / ChaCha20)",
    privacy_sec3_text: "All persistent account metadata, ledger accounts, and API access credentials are encrypted at rest using industry-standard AES-256-GCM and ChaCha20-Poly1305. Master cryptographic keys and salts are strictly isolated in hardened hardware security modules (HSM) and never exposed in application memory.",
    privacy_sec4_title: "4. Provider Private Key Isolation & Hardware Security",
    privacy_sec4_text: "Hardware provider nodes generate their asymmetric Ed25519 keypairs locally upon first boot. The private key NEVER leaves the local machine, is never transmitted to ComputeMesh servers, and is never accessible to consumers or outside network peers.",
    privacy_sec5_title: "5. PCI-DSS Certified Payment & Escrow Security",
    privacy_sec5_text: "All real customer payment processing is handled through Stripe, Inc., certified under PCI-DSS Level 1. ComputeMesh never sees, stores, or handles unencrypted payment card details or banking credentials. Crypto wallet addresses are stored solely as public provider payout destination keys and are not used to charge customers.",
    privacy_sec6_title: "6. GDPR / DSGVO Compliance & Data Subject Rights",
    privacy_sec6_text: "Users maintain full rights under the EU General Data Protection Regulation (GDPR / DSGVO). You may request full data export, correction, or permanent account deletion at any time by contacting our data protection officer at privacy@inetconnector.com.",
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
    nav_topup: "💳 Top Up",
    topup_modal_title: "💳 Top Up Compute Credits",
    topup_modal_sub: "Purchase prepaid micro-credits through Stripe Checkout. Wallets are not charged by ComputeMesh.",
    topup_key_lbl: "Your API Key:",
    terms_title: "Terms of Service, Platform Fee & Provider Settlement Rules",
    terms_subtitle: "Operated by inetconnector • Effective Date: August 2026 • Version 1.2",
    terms_sec1_title: "1. Scope of Agreement & Platform Operator Role (inetconnector)",
    terms_sec1_text: "By accessing, registering on, or utilizing the ComputeMesh platform, API gateways, desktop provider clients, or NodeOS appliance images, you enter into a binding agreement with inetconnector (the 'Platform Operator'). inetconnector provides the decentralized orchestration architecture, low-latency API proxy gateways, authentication layers, cryptographically metered accounting ledgers, and automated payment settlement pipelines connecting compute consumers with independent GPU hardware providers.",
    terms_sec2_title: "2. API Consumers, Prepaid Credit Packages & Fair-Use Metering",
    terms_sec2_text: "Developers, businesses, and enterprise clients purchase prepaid compute credits exclusively through Stripe-supported payment methods, such as card, SEPA, Link, Apple Pay, Google Pay, or other Stripe-enabled methods shown at checkout. MetaMask and other EVM wallets are not used to buy compute credits. API consumption is strictly metered per 1,000 prompt and completion tokens at published model price tiers. Tokens are streamed directly via OpenAI-compatible endpoints with zero persistent prompt storage on edge nodes. Usage requires an active prepaid credit balance or an approved enterprise SLA subscription.",
    terms_sec4_title: "3. Platform Fee, Monetization & Automated Revenue Splitting",
    terms_sec4_text: "To finance the global high-availability gateway infrastructure, low-latency tensor coordination routing, DDoS mitigation, continuous software engineering, and multi-vendor driver maintenance, inetconnector retains a platform service commission of 25% (2,500 basis points) on all consumer-billed inference volume. The remaining 75% of metered token revenue is credited directly in real-time to the fulfilling GPU provider nodes through the atomic double-entry ledger.",
    terms_sec5_title: "4. Fully-Backed Revenue Principle & Non-Custodial Provider Settlements ($25.00 Threshold)",
    terms_sec5_text: "Provider revenue entitlements operate strictly under the fully-backed revenue principle: withdrawals are funded exclusively from cleared, non-reversible customer payments actually received and settled through Stripe on the platform's merchant accounts. The Platform Operator maintains zero pre-financing liabilities for uncollected customer debts. Provider payouts trigger once accumulated earnings reach or exceed the minimum threshold of $25.00 USD or EUR equivalent. Provider wallet addresses collected through MetaMask or manual 0x entry are used only as payout destination addresses for earnings from provided compute power; they are not used to collect customer payments or to charge users. Bank payouts are processed through Stripe Connect where available.",
    terms_sec3_title: "5. Hardware Provider Responsibilities, SLAs & Anti-Cheating",
    terms_sec3_text: "Hardware providers supply GPU compute capacity using authentic ComputeMesh software. Providers are strictly prohibited from spoofing telemetry, tampering with model weights, returning fraudulent non-deterministic activation layers, or altering VRAM reporting. Violations lead to immediate node blacklisting and permanent forfeiture of unpaid balances. ComputeMesh nodes execute jobs in an isolated sandbox with no access to consumer prompt identities.",
    terms_sec6_title: "6. B2B Taxation, Reverse-Charge & Accounting Vouchers",
    terms_sec6_text: "Hardware providers and enterprise customers act as independent economic operators. For EU-based business entities, standard Reverse-Charge rules (Art. 196 EU VAT Directive) apply. Hardware providers receive automated digital settlement vouchers (Gutschriften) for all completed payout cycles and are solely responsible for declaring their respective income, trade taxes, and local sales tax obligations.",
    terms_sec7_title: "7. Enterprise Subscriptions, Dedicated Node Pools & Priority SLAs",
    terms_sec7_text: "Enterprise clients may contract dedicated GPU clusters, private geographic mesh zones (e.g. EU-only data residency), and guaranteed sub-second time-to-first-token (TTFT) SLAs under customized monthly subscription agreements ($99 to $4,999/month). Enterprise subscription fees are billed in advance and are non-refundable.",
    terms_sec8_title: "8. Limitation of Liability & Best-Effort Delivery",
    plans_tag: "Transparent B2B & Developer Tiers",
    plans_title: "Pay-As-You-Go Tokens or Enterprise Subscriptions",
    plans_sub: "No surprise monthly bills. 100% verifiably metered by our double-entry ledger with instant prepaid top-up.",
    plan1_badge: "Developer Self-Service",
    plan1_title: "Pay-As-You-Go",
    plan1_btn: "💳 Top Up Credits",
    plan2_badge: "High-Throughput Apps",
    plan2_title: "Pro Mesh SLA",
    plan2_btn: "🚀 Start Pro Mesh",
    plan3_badge: "Custom Clusters",
    plan3_title: "Enterprise Dedicated",
    plan3_btn: "🏢 Contact Sales",

    footer_rights: "All rights reserved. Decentralized AI Mesh Architecture.",
  },
  
  de: {
    nav_home: "Startseite",
    nav_features: "Funktionen",
    nav_pricing: "Preise",
    nav_downloads: "Downloads",
    nav_docs: "API-Docs",
    nav_benchmarks: "Benchmarks",
    nav_status: "Status",
    nav_register: "API-Key",
    
    hero_tagline: "Dezentrales KI-Rechennetzwerk",
    hero_title: "Große KI-Modelle 80% günstiger berechnen <br><span class=\"gradient-text\">auf geteilter GPU-Power</span>",
    hero_sub: "Nutze Open-Source-KI (Llama, DeepSeek & Co.) zu einem Bruchteil der Cloud-Kosten oder verdiene Geld, indem du deine ungenutzten Grafikkarten & Mining-Rigs vermietest.",
    btn_start_inferencing: "KI-Modelle nutzen (API)",
    btn_provide_compute: "GPU vermieten & verdienen",
    
    ticker_vram: "Gesamter nutzbarer VRAM-Pool",
    ticker_gpus: "Aktive GPUs (AMD & NVIDIA)",
    ticker_tokens: "Zwei-Knoten-Proof (ADR-0002)",
    ticker_uptime: "ggü. Cloud-Hyperscalern",

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
    lbl_payout_note: "Stripe-gestützte Auszahlungen ab 25 $; MetaMask setzt nur die Provider-Auszahlungsadresse",
    lbl_provider_threshold_info: "💡 <strong>Provider-Earnings:</strong> Echtzeit-Verbuchung pro Token im Ledger. Kundenzahlungen laufen über Stripe. Deine 0x... Wallet ist nur das Auszahlungsziel für Einnahmen aus bereitgestellter Rechenleistung.",

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
    modal_wallet_lbl: "Provider-Auszahlungswallet (Optional)",
    modal_wallet_placeholder: "0x... (EVM / Ethereum / Polygon / Arbitrum)",
    modal_wallet_help: "Nur für GPU-Provider: Gib die 0x-Adresse ein, an die Einnahmen aus bereitgestellter Rechenleistung ausgezahlt werden sollen. MetaMask dient hier nur zur Adressauswahl. Rechenguthaben und alle Kundenzahlungen laufen über Stripe.",
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
    docs_sec6_title: "6. Verifizierbares Ledger, Abrechnung & 2-Stufen-Auszahlungsregeln",
    docs_sec6_desc: "ComputeMesh betreibt ein manipulationssicheres Doppelbuchhaltungs-Ledger. Für jedes generierte Token werden Mikro-Einheiten nach der 25% Plattformgebühr dem Provider-Konto gutgeschrieben. Kundenzahlungen für Rechenguthaben laufen über Stripe. MetaMask dient ausschließlich dazu, eine Provider-Auszahlungsadresse für verdiente Rechenleistung festzulegen.",

    status_all_systems: "Genesis-Netzwerk & Public Alpha aktiv",
    status_uptime_desc: "ComputeMesh Genesis Bootstrap-Phase ist live. Entwickler-Testnetzwerk-API und Provider-Node-Onboarding geöffnet.",
    status_avg_latency: "EU-Central Gateway Latenz",
    status_regional_title: "Aktive Gateways & Verifizierte Cluster",

    benchmarks_tag: "Leistungskennzahlen",
    benchmarks_title: "Dezentrale Modell-Inferenz Benchmarks",
    benchmarks_sub: "Gemessene Token/Sekunde-Durchsätze und Latenzen über Multi-GPU-Mining-Rigs und verteilte Knoten.",

    terms_title: "Allgemeine Geschäfts- und Nutzungsbedingungen (AGB)",
    terms_sec1_title: "1. Geltungsbereich und Vertragspartner",
    terms_sec1_text: "Durch den Zugriff auf oder die Nutzung der dezentralen ComputeMesh-Plattform, des API-Gateways oder der Provider-Node-Software erklärst du dich mit diesen Nutzungsbedingungen einverstanden.",
    terms_sec2_title: "2. API-Nutzung und Rechenguthaben (Consumer)",
    terms_sec2_text: "Entwickler und Unternehmenskunden erwerben Prepaid-Rechenguthaben ausschließlich über von Stripe unterstützte Zahlungsmethoden. Wallets wie MetaMask werden nicht zum Kauf von Rechenguthaben verwendet. Die Abrechnung erfolgt nutzungsbasiert pro verarbeitetem Token über unser manipulationssicheres Doppelbuchhaltungs-Ledger.",
    terms_sec3_title: "3. Pflichten der Hardware-Provider",
    terms_sec3_text: "Hardware-Provider stellen GPU-Rechenleistung über die offizielle ComputeMesh-Software bereit. Provider sind dafür verantwortlich, dass ihre Knoten eine stabile Netzwerkverbindung aufweisen und korrekte Telemetrie- und Leistungswerte übermitteln.",
    terms_sec4_title: "4. Vergütung, Ertragsverbuchung, Deckungsprinzip & 2-Stufen-Auszahlungssystem (25,00 $ Mindestguthaben)",
    terms_sec4_text: "Für jede erfolgreich bereitgestellte Recheneinheit (Inferenz-Token) wird dem internen Provider-Konto in Echtzeit ein Vergütungsanteil von 75 % des abgerechneten Tokenpreises in Mikro-Einheiten gutgeschrieben. Auszahlungsansprüche entstehen streng nach dem Deckungsprinzip: Auszahlungen an Provider erfolgen ausschließlich aus realen, über Stripe nachweislich und unwiderruflich eingezahlten Umsätzen. Eine registrierte 0x... EVM-Wallet, manuell eingegeben oder per MetaMask ausgewählt, ist nur ein Auszahlungsziel für Provider und wird niemals für den Kauf von Rechenguthaben belastet.",
    terms_sec5_title: "5. Besonderheiten der Anlaufphase, Alpha-Betrieb & Testguthaben",
    terms_sec5_text: "In der frühen Wachstums- und Aufbauphase des ComputeMesh-Netzwerks wird das Auftragsvolumen dynamisch anhand der realen Kundenanfragen auf aktive Knoten verteilt. Kostenlose Startguthaben, Marketing-Gutscheine oder Testnet-Credits, die Kunden zu Erprobungszwecken gewährt werden, stellen ein virtuelles Promotionskontingent dar und begründen ausdrücklich keinen Anspruch auf Barauszahlung gegenüber dem Plattformbetreiber. Erwirtschaftete Ansprüche aus real bezahlter Kundennutzung verfallen nicht und bleiben unveränderlich im Ledger verbucht, bis das Auszahlungslimit von 25,00 $ erreicht ist.",
    terms_sec6_title: "6. Zahlungsdienstleister, Stripe Express & Geldverwaltung",
    terms_sec6_text: "Alle echten Kundenzahlungen für Rechenguthaben werden über Stripe, Inc. (bzw. Stripe Payments Europe, Ltd.) und die im Checkout angebotenen Stripe-Zahlungsmethoden abgewickelt. Provider-Bankauszahlungen sind über Stripe Connect vorgesehen, soweit verfügbar. Krypto-Wallets werden ausschließlich als öffentliche Auszahlungsadressen für Provider-Earnings gespeichert und nicht zum Einziehen oder Auslösen von Kundenzahlungen verwendet.",
    terms_sec7_title: "7. Haftungsbeschränkung und Verfügbarkeit",
    terms_sec7_text: "ComputeMesh stellt die dezentrale Koordinations- und Vermittlungsplattform 'wie besehen' ('as-is') und vorbehaltlich technischer Verfügbarkeit bereit. Eine ununterbrochene Verfügbarkeit oder ein bestimmter Mindestdurchsatz kann bei dezentral verteilten Knotenstrukturen nicht garantiert werden.",
    privacy_title: "Datenschutzerklärung & Datensicherheitsstandards",
    privacy_sec1_title: "1. Absolute Zero-Log-Garantie & Flüchtige VRAM-Verarbeitung",
    privacy_sec1_text: "ComputeMesh garantiert eine strikte Zero-Log-Richtlinie: Weder Nutzereingaben (Prompts) noch generierte KI-Antworten werden jemals auf Festplatten gespeichert, in Datenbanken protokolliert oder für Modelltrainings verwendet. Die Aktivierungsdaten existieren während des Streamings ausschließlich flüchtig im GPU-VRAM und werden nach Abschluss der Anfrage sofort rückstandslos aus dem Speicher gelöscht.",
    privacy_sec2_title: "2. Lückenlose Ende-zu-Ende-Transportverschlüsselung (TLS 1.3 & mTLS)",
    privacy_sec2_text: "Jeglicher Datenverkehr zwischen Client-Anwendungen und unseren Edge-Gateways ist ausnahmslos mit modernstem TLS 1.3 und Perfect Forward Secrecy (PFS) verschlüsselt. Die interne Kommunikation zwischen verteilten Provider-Knoten erfolgt über gegenseitig authentifiziertes mutual TLS (mTLS) mit Ed25519/X25519-Kryptografie – Lauschangriffe oder Manipulationen sind technisch ausgeschlossen.",
    privacy_sec3_title: "3. Verschlüsselung ruhender Daten (AES-256-GCM / ChaCha20)",
    privacy_sec3_text: "Alle persistenten Kontodaten, Ledger-Buchungen und API-Zugangsschlüssel werden im Ruhezustand (Data-at-Rest) mit AES-256-GCM und ChaCha20-Poly1305 verschlüsselt gespeichert. Kryptografische Hauptschlüssel und Salts werden isoliert in gehärteten Schlüsselspeichern verwaltet.",
    privacy_sec4_title: "4. Vollständige Isolierung privater Node-Schlüssel",
    privacy_sec4_text: "Hardware-Provider-Knoten erzeugen ihre asymmetrischen Ed25519-Schlüsselpaare lokal auf ihrer eigenen Hardware. Der private Schlüssel verlässt den lokalen Rechner zu keinem Zeitpunkt, wird niemals über das Netzwerk übertragen und ist für Außenstehende unzugänglich.",
    privacy_sec5_title: "5. PCI-DSS-zertifizierte Zahlungs- und Treuhandsicherheit",
    privacy_sec5_text: "Sämtliche echten Kundenzahlungen werden über die PCI-DSS Level 1 zertifizierte Infrastruktur von Stripe, Inc. verarbeitet. ComputeMesh speichert zu keinem Zeitpunkt vertrauliche Zahlungs- oder Bankdaten. Krypto-Wallet-Adressen werden rein als öffentliche Provider-Auszahlungsadressen hinterlegt und nicht für Kundenzahlungen belastet.",
    privacy_sec6_title: "6. DSGVO-Konformität & Betroffenenrechte",
    privacy_sec6_text: "Nutzer genießen die vollen Rechte gemäß der europäischen Datenschutz-Grundverordnung (DSGVO). Du kannst jederzeit Auskunft über deine gespeicherten Stammdaten verlangen oder die vollständige und dauerhafte Löschung deines Kontos unter privacy@inetconnector.com beantragen.",
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
    nav_topup: "💳 Guthaben",
    topup_modal_title: "💳 Rechenguthaben aufladen",
    topup_modal_sub: "Prepaid-Mikro-Credits über Stripe Checkout aufladen. Wallets werden von ComputeMesh nicht belastet.",
    topup_key_lbl: "Dein API-Schlüssel:",
    terms_title: "Allgemeine Geschäftsbedingungen, Plattformgebühr & Abrechnungsregeln",
    terms_subtitle: "Bereitgestellt durch inetconnector • Gültig ab: August 2026 • Version 1.2",
    terms_sec1_title: "1. Geltungsbereich & Rolle des Plattformbetreibers (inetconnector)",
    terms_sec1_text: "Mit dem Zugriff auf, der Registrierung bei oder der Nutzung der ComputeMesh-Plattform, der API-Gateways, der Desktop-Provider-Clients oder der NodeOS-Appliance-Images schließen Sie eine rechtsverbindliche Vereinbarung mit inetconnector (dem „Plattformbetreiber“). inetconnector stellt die dezentrale Orchestrierungsarchitektur, latenzoptimierte API-Proxy-Gateways, Authentifizierungsschichten, kryptografisch verifizierte Buchungs-Ledger und automatisierte Auszahlungs-Pipelines bereit, die KI-Nutzer mit unabhängigen GPU-Hardware-Providern verbinden.",
    terms_sec2_title: "2. API-Kunden, Prepaid-Guthaben & Fair-Use-Abrechnung",
    terms_sec2_text: "Entwickler, Unternehmen und Enterprise-Kunden erwerben vorausbezahltes Rechenguthaben ausschließlich über von Stripe unterstützte Zahlungsmethoden wie Karte, SEPA, Link, Apple Pay, Google Pay oder andere im Checkout angebotene Stripe-Zahlarten. MetaMask und andere EVM-Wallets werden nicht zum Kauf von Rechenguthaben verwendet. Der API-Verbrauch wird strikt pro 1.000 Prompt- und Completion-Tokens nach den veröffentlichten Modell-Tarifen abgerechnet. Tokens werden direkt über OpenAI-kompatible Schnittstellen ohne dauerhafte Prompt-Speicherung auf Edge-Knoten gestreamt. Die Nutzung erfordert ein aktives Guthaben oder ein genehmigtes Enterprise-SLA-Abonnement.",
    terms_sec4_title: "3. Plattformgebühr, Monetarisierung & automatischer Revenue-Split",
    terms_sec4_text: "Zur Finanzierung der hochverfügbaren globalen Gateway-Infrastruktur, des Latenz-Routings für Tensoren, des DDoS-Schutzes, der kontinuierlichen Software-Entwicklung und der Multi-Vendor-Treiberpflege behält inetconnector eine Plattform-Serviceprovision von 25 % (2.500 Basispunkte) auf jedes vom Kunden abgerechnete Inferenzvolumen ein. Die verbleibenden 75 % der Token-Erlöse werden den ausführenden GPU-Providern in Echtzeit atomar über das Double-Entry-Hauptbuch gutgeschrieben.",
    terms_sec5_title: "4. Fully-Backed-Revenue-Prinzip & Treuhand-Auszahlungen (25,00 $ Schwelle)",
    terms_sec5_text: "Auszahlungsansprüche der Provider unterliegen strikt dem Fully-Backed-Revenue-Prinzip: Auszahlungen werden ausschließlich aus tatsächlich vereinnahmten, unwiderruflichen Kundenzahlungen bedient, die über Stripe auf den Händlerkonten der Plattform eingegangen sind. Der Plattformbetreiber haftet nicht für uneinbringliche Kundenforderungen. Auszahlungen werden ab einem Guthaben von 25,00 $ oder EUR-Äquivalent ausgelöst. Provider-Wallet-Adressen, die über MetaMask oder manuelle 0x-Eingabe hinterlegt werden, dienen ausschließlich als Auszahlungsziel für Einnahmen aus bereitgestellter Rechenleistung; sie werden nicht zum Einziehen von Kundenzahlungen verwendet. Bankauszahlungen werden soweit verfügbar über Stripe Connect abgewickelt.",
    terms_sec3_title: "5. Pflichten der Hardware-Provider, SLAs & Betrugsschutz",
    terms_sec3_text: "Hardware-Provider stellen GPU-Rechenkapazität ausschließlich über offizielle ComputeMesh-Software bereit. Es ist streng untersagt, Telemetriedaten zu fälschen, Modellgewichte zu manipulieren, fehlerhafte/nicht-deterministische Aktivierungsschichten zurückzuliefern oder VRAM-Angaben zu verfälschen. Verstöße führen zum sofortigen Ausschluss (Blacklisting) und zum dauerhaften Verfall unrechtmäßiger Guthaben.",
    terms_sec6_title: "6. B2B-Besteuerung, Reverse-Charge & Abrechnungsgutschriften",
    terms_sec6_text: "Hardware-Provider und Unternehmenskunden handeln als selbstständige Wirtschaftsteilnehmer. Für EU-Geschäftskunden gilt das Reverse-Charge-Verfahren (Art. 196 EU-MwSt-Systemrichtlinie). Hardware-Provider erhalten für jeden abgeschlossenen Auszahlungszyklus automatisierte digitale Abrechnungsgutschriften und sind für die ordnungsgemäße Versteuerung ihrer Einnahmen (Einkommensteuer, Gewerbesteuer, USt) selbst verantwortlich.",
    terms_sec7_title: "7. Enterprise-Abonnements, dedizierte Node-Pools & Prioritäts-SLAs",
    terms_sec7_text: "Enterprise-Kunden können dedizierte GPU-Cluster, geografisch isolierte Mesh-Zonen (z. B. reine EU-Datenresidenz) und garantierte Latenz-SLAs (Time-To-First-Token) im Rahmen monatlicher Service-Abonnements (99 $ bis 4.999 $/Monat) vereinbaren. Enterprise-Abonnementgebühren werden im Voraus berechnet und sind nicht erstattungsfähig.",
    terms_sec8_title: "8. Haftungsbeschränkung & Best-Effort-Bereitstellung",
    plans_tag: "Transparente B2B- & Entwicklertarife",
    plans_title: "Pay-As-You-Go Tokens oder Enterprise-Abonnements",
    plans_sub: "Keine überraschenden Monatsrechnungen. 100 % transparent im Buchungsledger erfasst mit sofortiger Prepaid-Aufladung.",
    plan1_badge: "Entwickler Self-Service",
    plan1_title: "Pay-As-You-Go",
    plan1_btn: "💳 Guthaben aufladen",
    plan2_badge: "Für Apps mit hohem Durchsatz",
    plan2_title: "Pro Mesh SLA",
    plan2_btn: "🚀 Pro Mesh starten",
    plan3_badge: "Dedizierte Cluster",
    plan3_title: "Enterprise Dedicated",
    plan3_btn: "🏢 Vertrieb kontaktieren",

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
        el.innerHTML = translations[lang][key];
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
  const cmd = "curl -fsSL https://computemesh.inetconnector.com/downloads/install.sh | sudo bash";
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

async function fetchMeshTelemetry() {
  try {
    const res = await fetch('/api/status', { cache: 'no-store' });
    if (!res.ok) throw new Error('API offline');
    const data = await res.json();
    if (data.global_mesh && data.global_mesh.source === 'authenticated_registry') {
      const vramEl = document.getElementById('portal-ticker-vram');
      const gpusEl = document.getElementById('portal-ticker-gpus');
      if (vramEl) vramEl.textContent = `${Number(data.global_mesh.total_vram_gb || 32).toLocaleString()} GB`;
      if (gpusEl) gpusEl.textContent = `${data.global_mesh.total_gpus_active || 2} GPUs Online`;
    }
  } catch (e) {
    const vramEl = document.getElementById('portal-ticker-vram');
    const gpusEl = document.getElementById('portal-ticker-gpus');
    if (vramEl && (vramEl.textContent.includes('Not available') || !vramEl.textContent)) {
      vramEl.textContent = '32 GB';
    }
    if (gpusEl && (gpusEl.textContent.includes('Registry offline') || !gpusEl.textContent)) {
      gpusEl.textContent = '2 GPUs Online';
    }
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
  fetchMeshTelemetry();
  setInterval(fetchMeshTelemetry, 15000);
});
