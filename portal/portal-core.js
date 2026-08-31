/* ==============================================================================
   ComputeMesh Portal Client Logic: i18n (DE/EN), Calculators & Subpages
   ============================================================================== */

const translations = {
  en: {
    // Navigation & Common
    nav_home: "Home",
    nav_features: "Features",
    nav_pricing: "Pricing",
    nav_downloads: "Downloads",
    nav_docs: "API Docs",
    nav_benchmarks: "Benchmarks",
    nav_status: "Status",
    nav_register: "API Key",
    nav_topup: "💳 Top Up",
    nav_playground: "⚡ Playground",
    nav_legal: "Legal",
    nav_privacy: "Privacy",
    nav_terms: "Terms",
    nav_impressum: "Impressum",
    nav_support: "Support",
    back_to_home: "← Back to Home",
    footer_brand_desc: "Pre-production distributed-inference engineering with public provider/runtime interoperability and private production policy.",
    footer_col_platform: "Platform",
    footer_col_resources: "Resources",
    footer_col_legal: "Legal & Company",
    footer_rights: "All rights reserved. Decentralized AI Mesh Architecture.",
    footer_tech_status: "Technical status: pre-production engineering",

    // Hero Section
    hero_tagline: "⚡ Many graphics cards. One AI network.",
    hero_title: "AI should not only run in huge data centers.<br><span class=\"gradient-text\">ComputeMesh connects idle graphics cards.</span>",
    hero_sub: "The idea is simple: send an AI request to ComputeMesh, let the system find suitable hardware, run the work and measure honestly what already works today. Developers can test AI through one gateway, and hardware owners can register their machines as providers. Still pre-production: available models, speed and cost depend on the real setup.",
    btn_start_inferencing: "⚡ Try the playground",
    btn_provide_compute: "Offer hardware",
    ticker_vram: "Live VRAM from connected GPUs",
    ticker_gpus: "Live GPUs online",
    ticker_tokens: "Two machines tested together",
    ticker_uptime: "More LAN/WAN tests still missing",
    ticker_proof_val: "Lab proof",
    ticker_preprod_val: "Still being built",

    // Playground Section
    pg_tag: "Gateway playground",
    pg_title: "Test the <span class=\"gradient-text\">configured gateway</span>",
    pg_sub: "The playground works only when its backend and selected model are actually configured. It is not evidence that a public distributed mesh or every listed model is currently available.",
    pg_model_lbl: "Model:",
    pg_quota_pill: "Demo quota",
    pg_cluster_pending: "Gateway status pending",
    pg_ai_author: "ComputeMesh AI",
    pg_ai_badge: "GATEWAY",
    pg_ai_welcome: "If the configured demo backend is available, requests sent here use that gateway path. Check the engineering status and benchmark pages for what has actually been validated.",
    pg_status_lbl: "Status:",
    pg_status_ready: "Ready",
    pg_speed_lbl: "Speed:",
    pg_latency_lbl: "Latency:",
    pg_tokens_lbl: "Tokens:",
    qp_explain_mesh: "⚡ What is ComputeMesh?",
    qp_python_fastapi: "🐍 Write a FastAPI endpoint",
    qp_gpu_sharding: "🧩 Explain Pipeline Sharding",
    qp_compare_costs: "💰 Explain cost variables",
    pg_prompt_placeholder: "Ask anything... (Enter to send, Shift+Enter for newline)",
    pg_send_btn: "Send Prompt",
    pg_ollama_title: "Ollama-compatible endpoint",
    pg_ollama_badge: "Deployment-dependent demo",
    pg_ollama_desc: "Gateway operators may configure a private Ollama-compatible demo upstream. A configured demo backend is distinct from evidence of distributed execution.",

    // Features Section
    features_tag: "Current architecture",
    features_title: "Implemented foundations with explicit readiness limits",
    features_sub: "ComputeMesh separates public execution/protocol/provider code from private production placement/data/policy.",
    feat1_title: "Measured layer splitting",
    feat1_desc: "Contiguous two-node layer splits are researched and validated per exact model/runtime/hardware/network evidence. No universal speedup is assumed.",
    feat2_title: "Heterogeneous provider foundations",
    feat2_desc: "Hardware inventory and CUDA/ROCm/Vulkan-related tooling exist, but production support is validated per actual target rather than claimed for arbitrary GPU mixes.",
    feat3_title: "Private production placement",
    feat3_desc: "The public runtime receives a signed execution plan; production ranking, empirical performance, reputation/fraud and economics remain private.",
    feat4_title: "OpenAI-compatible gateway",
    feat4_desc: "Supported OpenAI-style endpoints are implemented. This is not a claim of compatibility with every OpenAI API or SDK behavior.",
    feat5_title: "Provider/NodeOS tooling",
    feat5_desc: "Windows/Linux/provider and appliance tooling exists for supported engineering targets. Exact driver/GPU combinations still require validation.",
    feat6_title: "Evidence & accounting foundations",
    feat6_desc: "Execution evidence, provider attestations, durable feedback and double-entry ledger foundations exist. Settlement/payout policy is deployment- and private-policy-dependent.",

    // Pricing / Calculator Section
    calc_tag: "Illustrative economics UI",
    calc_title: "Explore variables — not a production price quote",
    calc_sub: "The existing calculator remains available as an interface experiment. Its computed values are illustrative and must not be treated as a live quote, guaranteed saving or guaranteed provider income. Production pricing/settlement policy is private and deployment-dependent.",
    tab_developer: "Illustrative developer estimate",
    tab_provider: "Illustrative provider estimate",
    lbl_monthly_tokens: "Monthly inference volume (million tokens)",
    lbl_model_tier: "Illustrative model tier",
    lbl_computemesh_cost: "Illustrative computed value",
    lbl_cloud_cost: "Comparison input:",
    lbl_your_savings: "Not a production quote or guaranteed saving.",
    lbl_gpu_setup: "Illustrative hardware profile",
    lbl_hours_online: "Uptime assumption",
    lbl_est_earnings: "Illustrative computed value",
    lbl_payout_note: "Real earnings require paid customer demand, verified execution, current private pricing/settlement policy and successful provider payout eligibility.",
    lbl_provider_threshold_info: "💡 <strong>Credits & Settlement:</strong> Earned Compute Credits (CM) represent verified micro-units ($0.000001 USD) in the double-entry ledger. Hardware providers receive 75% of model-dependent customer revenue. Payouts are executed via Stripe Connect from $25.00.",
    commercial_plans_title: "Commercial plans",
    commercial_plans_desc: "No public SLA, fixed discount, dedicated-cluster guarantee, model entitlement or provider revenue percentage is established by this engineering page. Contact the operator for an actual offer; technical capabilities remain subject to the current status and measured deployment.",
    btn_contact_sales: "Contact",

    // Downloads Section
    dl_tag: "Provider tooling",
    dl_title: "Installers & appliance artifacts",
    dl_sub: "Use only artifacts appropriate to your target and verify the published/current deployment instructions. Installer availability does not imply that every GPU/driver topology is production-supported.",
    dl_win_title: "Windows Provider Agent",
    dl_win_desc: "Windows provider/installer path for supported engineering targets with tray GUI and background daemon.",
    dl_win_btn: "Download for Windows (.exe)",
    dl_linux_title: "Linux Headless Agent",
    dl_linux_desc: "Headless provider setup path. Review the current repository setup/provider documentation before use.",
    dl_linux_btn: "Copy Install Command",
    dl_rig_title: "Mining Rig Appliance (NodeOS)",
    dl_rig_desc: "Experimental appliance artifacts for 4–12 GPU rigs with AMD & NVIDIA auto-detection.",
    dl_rig_iso_btn: "Download Bootable ISO (.iso)",
    dl_rig_btn: "Download Flash Image (.img.xz)",

    // API Section
    api_tag: "Integration",
    api_title: "OpenAI-compatible supported surface",
    api_sub: "Point a compatible client at the deployment's `/v1` base URL, use a registered API key and choose an actually exposed model. Check `/v1/models` and current API documentation rather than assuming every OpenAI endpoint exists.",

    // Modals
    modal_title: "Get Started with ComputeMesh",
    modal_sub: "Current account registration is B2B-only. Provider availability and earnings are not guaranteed.",
    modal_role_lbl: "I want to:",
    role_consumer: "Use the Developer API",
    role_provider: "Register provider hardware",
    modal_email_lbl: "Email Address",
    modal_wallet_lbl: "Provider payout wallet (optional metadata)",
    modal_wallet_placeholder: "0x... (EVM / Ethereum / Polygon / Arbitrum)",
    modal_wallet_help: "Where enabled, this is payout-destination metadata only; it is not a customer payment method.",
    modal_submit_btn: "Generate Credentials",
    modal_key_result_lbl: "Your Generated Key:",
    modal_copy_btn: "Copy Key",
    topup_modal_title: "💳 Top Up Compute Credits",
    topup_modal_sub: "When Stripe Checkout is configured, this form can request a checkout session. Displayed deposit amounts do not promise a specific token count or model price.",
    topup_key_lbl: "Your API Key:",
    topup_select_amount_lbl: "Select deposit amount:",
    btn_topup_proceed: "Proceed to configured Checkout →",
    conv_tag: "Gateway options",
    conv_title: "Continue with an API key or register a provider",
    conv_sub: "Availability, prices and provider revenue depend on the configured deployment and verified workload.",
    conv_opt1_badge: "Developer",
    conv_opt1_title: "🔑 API credentials",
    conv_opt1_desc: "Use the supported gateway surface with a registered key and active model catalog.",
    conv_opt1_btn: "Generate API Key →",
    conv_opt2_badge: "Provider",
    conv_opt2_title: "⚡ Register hardware",
    conv_opt2_desc: "Provider eligibility and earnings require compatible measured hardware/runtime, successful enrollment and paid demand.",
    conv_opt2_btn: "Register Node",
    conv_opt2_dl: "Downloads",

    // Documentation Page (docs.html)
    docs_page_tag: "Developer Preview Documentation",
    docs_main_title: "ComputeMesh Architecture & Integration Guide",
    docs_main_sub: "Documentation for the currently implemented gateway/provider foundations and the validated research/live development path. ComputeMesh is still pre-production; examples are deployment-dependent and do not imply universal model, hardware, latency or availability support.",
    docs_readiness_alert: "<strong style=\"color: var(--text-main);\">Readiness boundary:</strong> a narrow physical two-machine shared-runtime proof and substantial control/gateway foundations exist, but broad LAN/WAN validation, production data-plane security, provider-enforced leases and production key/session hardening remain open. Upstream llama.cpp RPC must not be exposed directly to an untrusted/public network.",
    docs_toc_title: "Contents",
    docs_toc_1: "1. Gateway/API quickstart",
    docs_toc_2: "2. Distributed architecture",
    docs_toc_3: "3. Layer-sharding research",
    docs_toc_4: "4. Provider node setup",
    docs_toc_5: "5. Mining Rig NodeOS",
    docs_toc_6: "6. Ledger & billing foundations",
    docs_sec1_h2: "1. OpenAI-compatible gateway quickstart",
    docs_sec1_p: "The gateway implements an OpenAI-compatible surface for supported endpoints such as chat completions and model listing. It is not a claim of 100% compatibility with every OpenAI API endpoint or SDK behavior. Configure <code>base_url</code>, use a registered ComputeMesh API key, and select a model that the active deployment actually exposes.",
    docs_playground_h3: "⚡ In-browser gateway playground",
    docs_playground_badge: "Availability depends on the deployed gateway/catalog",
    docs_playground_send: "▶ Run Inference",
    playground_send: "▶ Run Inference",
    docs_playground_ph: "Enter your prompt here...",
    docs_terminal_title: "Gateway Response Terminal",
    docs_terminal_ready: "Ready",
    docs_terminal_init: "If the configured gateway/model is available, click \"Run Inference\" to send the request.",
    docs_sec2_h2: "2. Distributed mesh architecture",
    docs_sec2_p: "ComputeMesh is designed to select feasible execution placements across heterogeneous providers. The current live development path uses an authenticated provider-control channel, a private production placement service, a public executor and a two-node llama.cpp shared-runtime path. It does not yet imply arbitrary peer-to-peer execution across every registered GPU.",
    docs_sec3_h2: "3. Pipeline layer-sharding research",
    docs_sec3_p: "Contiguous layer splitting can reduce per-device model-memory requirements, but end-to-end performance depends on the exact model, quantization, runtime build, split, GPU pair and network path. ComputeMesh therefore records real baseline/shared measurements and network byte/timing evidence instead of treating a theoretical activation-size calculation as a universal latency result. Any PCIe or WAN performance number must be tied to a named measured configuration.",
    docs_sec4_h2: "4. Hardware provider node setup",
    docs_sec4_p: "A runnable public provider agent and Ed25519 enrollment/session path exist. Actual runtime support is hardware-, driver-, backend-, model- and llama.cpp-build-dependent; ComputeMesh does not claim that every modern NVIDIA, AMD or Intel GPU is production-supported. Provider private keys are generated/retained on the provider in the current SSH operator path, while production OS-protected key storage remains a hardening item.",
    docs_sec4_note: "Only use a published installer after verifying that it corresponds to the documented release/deployment path for your system.",
    docs_sec5_h2: "5. Mining Rig NodeOS appliance",
    docs_sec5_p: "NodeOS/appliance tooling exists for headless provider experiments, including hardware/backend detection and a local dashboard. Exact AMD/NVIDIA generations, driver combinations and multi-GPU topologies require per-target validation; the appliance is not evidence that every mining-rig configuration is production-ready.",
    docs_sec6_h2: "6. Ledger & billing foundations",
    docs_sec6_p: "The public code contains an auditable double-entry ledger foundation plus fail-closed Stripe Checkout/Webhook and provider-settlement integration paths when configured. Production quote, marketplace, margin/take-rate and settlement-hold policy belong to the private control plane and are not defined by a universal percentage on this documentation page. MetaMask/EVM addresses, where used by the current provider UI, are payout-destination metadata rather than a mechanism for buying compute credits.",

    // Status Page (status.html)
    status_main_h2: "Pre-production engineering & validation",
    status_main_p: "ComputeMesh has implemented gateway, provider-control, provider-agent, orchestration, private placement and measured-evidence foundations. It is not yet presented as a generally production-ready public distributed-inference network.",
    status_reviewed_date: "Documentation status reviewed 2026-08-27 UTC",
    status_tick1_val: "Implemented",
    status_tick1_lbl: "Authenticated provider-control foundation",
    status_tick2_val: "Verified narrow proof",
    status_tick2_lbl: "Two-machine trusted-lab shared runtime",
    status_tick3_val: "Live Cluster",
    status_tick3_lbl: "Authenticated live global capacity metric",
    status_tick4_val: "Open gate",
    status_tick4_lbl: "Broad LAN/WAN production validation",
    status_boundaries_h3: "Validated and remaining boundaries",
    status_card1_h4: "✅ Software foundations",
    status_card1_p: "Authenticated gateway/provider-control paths, runnable public provider agent, durable orchestration/recovery mechanics, signed private placement decisions, execution evidence/attestations and measured-outcome feedback are implemented foundations.",
    status_card2_h4: "🔬 Physical evidence",
    status_card2_p: "A narrow trusted-lab two-machine llama.cpp shared-runtime proof is recorded for its exact hardware/model/runtime/topology. It is not a universal performance or production-readiness claim.",
    status_card3_h4: "🔒 Runtime security boundary",
    status_card3_p: "Upstream llama.cpp RPC remains experimental and is not a public ComputeMesh security boundary. Current development bring-up contains it behind trusted/private networking or SSH tunnels.",
    status_card4_h4: "🧪 Remaining readiness gates",
    status_card4_p: "Representative LAN/WAN measurement matrices, provider-enforced resource leases, production data-plane and key/session hardening, adversarial/system testing, calibrated private performance prediction and production operations/HA remain open.",
    status_metrics_h3: "About status metrics",
    status_metrics_p: "This page deliberately does not display placeholder global VRAM, GPU count, uptime or gateway-latency numbers as though they were live. Such metrics appear only when sourced from an authenticated current registry/telemetry path in real time.",

    // Benchmarks Page (benchmarks.html)
    bench_page_tag: "Measured Engineering Evidence",
    bench_main_h1: "Recorded ComputeMesh Benchmarks",
    bench_main_p: "Only measurements recorded in the engineering evidence are shown as measured facts. Results are specific to their model, hardware, runtime build and topology and must not be generalized to other configurations.",
    bench_ttft_alert: "<strong style=\"color: var(--text-main);\">TTFT note:</strong> the current non-streaming measured-feedback path records prefill, decode and end-to-end request duration but does not directly measure true time-to-first-token. This page therefore does not publish invented TTFT values.",
    bench_th_evidence: "Evidence",
    bench_th_hw: "Hardware / topology",
    bench_th_model: "Model scope",
    bench_th_prefill: "Prefill",
    bench_th_decode: "Decode",
    bench_th_interp: "Interpretation",
    bench_row1_title: "Local llama.cpp benchmark",
    bench_row1_hw: "Windows / RTX 3080 Laptop GPU, CUDA",
    bench_row1_model: "7B Q4 benchmark artifact recorded 2026-08-21",
    bench_row1_interp: "Local single-host evidence only",
    bench_row2_title: "Local llama.cpp smoke benchmark",
    bench_row2_hw: "Debian 13 / CPU-only server",
    bench_row2_model: "0.5B Q4 smoke artifact recorded 2026-08-21",
    bench_row2_interp: "Different model from the RTX run; do not combine into one distributed result",
    bench_row3_title: "Physical shared-runtime proof",
    bench_row3_hw: "Two-machine trusted-lab topology",
    bench_row3_model: "Exact model/runtime/topology bound in repository evidence",
    bench_row3_prefill: "See bound proof artifact",
    bench_row3_decode: "See bound proof artifact",
    bench_row3_interp: "Exact output/token correctness was verified for that narrow proof; not a universal throughput claim",
    bench_net_h3: "Network evidence",
    bench_net_p: "A historical Windows-to-Linux engineering TCP measurement recorded RTT p50 11.884 ms, p95 13.369 ms, upload p50 42.276 Mbit/s and download p50 226.597 Mbit/s. That internet-path measurement is not itself a shared-inference benchmark. The current matrix tooling can perform real controlled delay/jitter shared-runtime experiments; broader bandwidth, packet-loss/reordering and WAN result matrices remain readiness work until recorded.",
    bench_repro_h3: "Reproducibility rule",
    bench_repro_p: "A benchmark is meaningful only with the exact model digest/size, llama.cpp build identity, hardware/profile revision, topology, split and network evidence. Marketing estimates and hypothetical hardware combinations are not benchmark results.",

    // Contact Page (contact.html)
    contact_tag: "Get in Touch",
    contact_title: "Support & Community Helpdesk",
    contact_sub: "Have questions about running a provider mining rig, integrating our OpenAI API, or purchasing enterprise compute credits?",
    contact_name_lbl: "Your Name",
    contact_topic_lbl: "Topic",
    contact_msg_lbl: "Message",
    contact_send_btn: "Send Message",
    contact_opt_provider: "Mining Rig & Hardware Provider Support",
    contact_opt_developer: "Developer API & Integration",
    contact_opt_billing: "Billing & Credit Top-up",
    contact_opt_enterprise: "Custom Enterprise Deployment",
    contact_success: "✓ Your message has been sent successfully! Our engineering team will respond within 24 hours."
  },

  de: {
    // Navigation & Allgemein
    nav_home: "Startseite",
    nav_features: "Funktionen",
    nav_pricing: "Preise & Rechner",
    nav_downloads: "Downloads",
    nav_docs: "API-Docs",
    nav_benchmarks: "Benchmarks",
    nav_status: "Systemstatus",
    nav_register: "API-Key",
    nav_topup: "💳 Guthaben",
    nav_playground: "⚡ Playground",
    nav_legal: "Rechtliches",
    nav_privacy: "Datenschutz",
    nav_terms: "AGB",
    nav_impressum: "Impressum",
    nav_support: "Support",
    back_to_home: "← Zurück zur Startseite",
    footer_brand_desc: "Pre-Production Distributed-Inference Engineering mit öffentlicher Provider/Runtime-Interoperabilität und privater Produktionsrichtlinie.",
    footer_col_platform: "Plattform",
    footer_col_resources: "Ressourcen",
    footer_col_legal: "Rechtliches & Unternehmen",
    footer_rights: "Alle Rechte vorbehalten. Dezentrale KI-Mesh-Architektur.",
    footer_tech_status: "Technischer Status: Pre-Production Engineering",

    // Hero Section
    hero_tagline: "⚡ Viele Grafikkarten. Ein KI-Netzwerk.",
    hero_title: "KI soll nicht nur in riesigen Rechenzentren laufen.<br><span class=\"gradient-text\">ComputeMesh verbindet freie Grafikkarten.</span>",
    hero_sub: "Die Idee ist einfach: Du schickst eine KI-Anfrage an ComputeMesh. Das System sucht passende Hardware, führt die Arbeit aus und misst ehrlich, was heute schon funktioniert. Entwickler können KI über ein Gateway testen, und Hardware-Besitzer können ihre Rechner als Provider registrieren. Noch Pre-Production: verfügbare Modelle, Tempo und Kosten hängen vom echten Setup ab.",
    btn_start_inferencing: "⚡ Playground testen",
    btn_provide_compute: "Hardware anbieten",
    ticker_vram: "Live-VRAM verbundener GPUs",
    ticker_gpus: "Live-GPUs online",
    ticker_tokens: "Zwei Rechner gemeinsam getestet",
    ticker_uptime: "Mehr LAN/WAN-Tests fehlen noch",
    ticker_proof_val: "Laborbeleg",
    ticker_preprod_val: "Noch im Aufbau",

    // Playground Section
    pg_tag: "Gateway-Playground",
    pg_title: "Das <span class=\"gradient-text\">konfigurierte Gateway</span> testen",
    pg_sub: "Der Playground funktioniert nur, wenn Backend und ausgewähltes Modell tatsächlich konfiguriert sind. Er ist kein Beleg dafür, dass ein öffentliches verteiltes Mesh oder jedes gelistete Modell aktuell verfügbar ist.",
    pg_model_lbl: "Modell:",
    pg_quota_pill: "Demo-Kontingent",
    pg_cluster_pending: "Gateway-Status ausstehend",
    pg_ai_author: "ComputeMesh KI",
    pg_ai_badge: "GATEWAY",
    pg_ai_welcome: "Wenn das konfigurierte Demo-Backend verfügbar ist, laufen Anfragen von hier über diesen Gateway-Pfad. Prüfe Status- und Benchmark-Seiten, um zu sehen, was tatsächlich validiert wurde.",
    pg_status_lbl: "Status:",
    pg_status_ready: "Bereit",
    pg_speed_lbl: "Geschwindigkeit:",
    pg_latency_lbl: "Latenz:",
    pg_tokens_lbl: "Tokens:",
    qp_explain_mesh: "⚡ Was ist ComputeMesh?",
    qp_python_fastapi: "🐍 Schreibe einen FastAPI-Endpunkt",
    qp_gpu_sharding: "🧩 Erkläre Pipeline-Sharding",
    qp_compare_costs: "💰 Erkläre Kostenfaktoren",
    pg_prompt_placeholder: "Stelle eine Frage... (Enter zum Senden, Shift+Enter für neue Zeile)",
    pg_send_btn: "Prompt senden",
    pg_ollama_title: "Ollama-kompatibler Endpunkt",
    pg_ollama_badge: "Deployment-abhängige Demo",
    pg_ollama_desc: "Gateway-Betreiber können ein privates Ollama-kompatibles Demo-Upstream konfigurieren. Ein konfiguriertes Demo-Backend ist kein Beleg für verteilte Ausführung.",

    // Features Section
    features_tag: "Aktuelle Architektur",
    features_title: "Implementierte Grundlagen mit expliziten Reifegrenzen",
    features_sub: "ComputeMesh trennt öffentlichen Execution/Protocol/Provider-Code von privatem Produktions-Placement, privaten Daten und privaten Richtlinien.",
    feat1_title: "Gemessenes Layer-Splitting",
    feat1_desc: "Kontinuierliche Zwei-Knoten-Layer-Splits werden pro konkretem Modell, Runtime, Hardware und Netzwerkpfad erforscht und validiert. Es wird kein universeller Speedup angenommen.",
    feat2_title: "Grundlagen für heterogene Provider",
    feat2_desc: "Hardware-Inventar und CUDA/ROCm/Vulkan-nahe Werkzeuge existieren; Produktionsunterstützung wird aber pro konkretem Ziel validiert und nicht für beliebige GPU-Mischungen behauptet.",
    feat3_title: "Privates Produktions-Placement",
    feat3_desc: "Die öffentliche Runtime erhält einen signierten Ausführungsplan; Produktions-Ranking, empirische Performance, Reputation/Fraud und Wirtschaftlichkeit bleiben privat.",
    feat4_title: "OpenAI-kompatibles Gateway",
    feat4_desc: "Unterstützte OpenAI-artige Endpunkte sind implementiert. Das ist keine Behauptung vollständiger Kompatibilität mit jedem OpenAI-API- oder SDK-Verhalten.",
    feat5_title: "Provider/NodeOS-Werkzeuge",
    feat5_desc: "Windows-, Linux-, Provider- und Appliance-Werkzeuge existieren für unterstützte Engineering-Ziele. Konkrete Treiber/GPU-Kombinationen benötigen weiterhin Validierung.",
    feat6_title: "Grundlagen für Evidenz & Accounting",
    feat6_desc: "Ausführungsevidenz, Provider-Attestierungen, dauerhaftes Feedback und Double-Entry-Ledger-Grundlagen existieren. Settlement- und Auszahlungspolitik sind deployment- und private-policy-abhängig.",

    // Pricing / Calculator Section
    calc_tag: "Illustrative Wirtschaftsoberfläche",
    calc_title: "Variablen erkunden - kein Produktionspreisangebot",
    calc_sub: "Der bestehende Rechner bleibt als Interface-Experiment verfügbar. Berechnete Werte sind illustrativ und dürfen nicht als Live-Angebot, garantierte Ersparnis oder garantierte Provider-Einnahmen verstanden werden. Produktionspreise und Settlement-Policy sind privat und deployment-abhängig.",
    tab_developer: "Illustrative Entwickler-Schätzung",
    tab_provider: "Illustrative Provider-Schätzung",
    lbl_monthly_tokens: "Monatliches Inferenzvolumen (Millionen Tokens)",
    lbl_model_tier: "Illustrative Modellklasse",
    lbl_computemesh_cost: "Illustrativer berechneter Wert",
    lbl_cloud_cost: "Vergleichseingabe:",
    lbl_your_savings: "Kein Produktionsangebot und keine garantierte Ersparnis.",
    lbl_gpu_setup: "Illustratives Hardwareprofil",
    lbl_hours_online: "Uptime-Annahme",
    lbl_est_earnings: "Illustrativer berechneter Wert",
    lbl_payout_note: "Reale Einnahmen erfordern bezahlte Kundennachfrage, verifizierte Ausführung, aktuelle private Preis-/Settlement-Policy und erfolgreiche Provider-Auszahlungsberechtigung.",
    lbl_provider_threshold_info: "💡 <strong>Credits & Settlement:</strong> Verdiente Compute Credits (CM) stehen für verifizierte Micro-Units ($0.000001 USD) im Double-Entry-Ledger. Hardware-Provider erhalten 75% des modellabhängigen Kundenumsatzes. Auszahlungen laufen ab $25.00 über Stripe Connect.",
    commercial_plans_title: "Gewerbliche Pläne",
    commercial_plans_desc: "Diese Engineering-Seite begründet kein öffentliches SLA, keinen festen Rabatt, keine Garantie für dedizierte Cluster, keinen Modellanspruch und keinen Provider-Umsatzanteil. Für ein tatsächliches Angebot den Betreiber kontaktieren; technische Fähigkeiten bleiben vom aktuellen Status und gemessenen Deployment abhängig.",
    btn_contact_sales: "Kontakt",

    // Downloads Section
    dl_tag: "Provider-Werkzeuge",
    dl_title: "Installer & Appliance-Artefakte",
    dl_sub: "Nutze nur Artefakte, die zu deinem Zielsystem passen, und prüfe die veröffentlichten/aktuellen Deployment-Anleitungen. Installer-Verfügbarkeit bedeutet nicht, dass jede GPU/Treiber-Topologie produktionsunterstützt ist.",
    dl_win_title: "Windows Provider Agent",
    dl_win_desc: "Windows-Provider/Installer-Pfad für unterstützte Engineering-Ziele mit Tray-GUI und Hintergrunddienst.",
    dl_win_btn: "Für Windows herunterladen (.exe)",
    dl_linux_title: "Linux Headless Agent",
    dl_linux_desc: "Headless-Provider-Setup-Pfad. Prüfe vor der Nutzung die aktuelle Repository-Setup-/Provider-Dokumentation.",
    dl_linux_btn: "Installationsbefehl kopieren",
    dl_rig_title: "Mining-Rig Appliance (NodeOS)",
    dl_rig_desc: "Experimentelle Appliance-Artefakte für 4-12-GPU-Rigs mit AMD- & NVIDIA-Autoerkennung.",
    dl_rig_iso_btn: "Bootfähiges ISO herunterladen (.iso)",
    dl_rig_btn: "Flash-Image herunterladen (.img.xz)",

    // API Section
    api_tag: "Integration",
    api_title: "OpenAI-kompatible unterstützte Oberfläche",
    api_sub: "Richte einen kompatiblen Client auf die `/v1`-Base-URL des Deployments, nutze einen registrierten API-Key und wähle ein tatsächlich exponiertes Modell. Prüfe `/v1/models` und die aktuelle API-Dokumentation, statt anzunehmen, dass jeder OpenAI-Endpunkt existiert.",

    // Modals
    modal_title: "Mit ComputeMesh starten",
    modal_sub: "Aktuelle Kontoregistrierung ist nur für B2B. Provider-Verfügbarkeit und Einnahmen sind nicht garantiert.",
    modal_role_lbl: "Ich möchte:",
    role_consumer: "Developer API nutzen",
    role_provider: "Provider-Hardware registrieren",
    modal_email_lbl: "E-Mail-Adresse",
    modal_wallet_lbl: "Provider-Auszahlungswallet (optionale Metadaten)",
    modal_wallet_placeholder: "0x... (EVM / Ethereum / Polygon / Arbitrum)",
    modal_wallet_help: "Wo aktiviert, ist dies nur Auszahlungsziel-Metadatum; es ist keine Kundenzahlungsmethode.",
    modal_submit_btn: "Zugangsdaten generieren",
    modal_key_result_lbl: "Dein generierter Schlüssel:",
    modal_copy_btn: "Schlüssel kopieren",
    topup_modal_title: "💳 Rechenguthaben aufladen",
    topup_modal_sub: "Wenn Stripe Checkout konfiguriert ist, kann dieses Formular eine Checkout-Session anfordern. Angezeigte Einzahlungsbeträge versprechen keine bestimmte Token-Anzahl oder Modellpreise.",
    topup_key_lbl: "Dein API-Schlüssel:",
    topup_select_amount_lbl: "Aufladebetrag auswählen:",
    btn_topup_proceed: "Weiter zum konfigurierten Checkout →",
    conv_tag: "Gateway-Optionen",
    conv_title: "Mit API-Key fortfahren oder Provider registrieren",
    conv_sub: "Verfügbarkeit, Preise und Provider-Einnahmen hängen vom konfigurierten Deployment und verifizierten Workload ab.",
    conv_opt1_badge: "Entwickler",
    conv_opt1_title: "🔑 API-Zugangsdaten",
    conv_opt1_desc: "Nutze die unterstützte Gateway-Oberfläche mit registriertem Key und aktivem Modellkatalog.",
    conv_opt1_btn: "API-Key generieren →",
    conv_opt2_badge: "Provider",
    conv_opt2_title: "⚡ Hardware registrieren",
    conv_opt2_desc: "Provider-Eignung und Einnahmen erfordern kompatible gemessene Hardware/Runtime, erfolgreiche Registrierung und bezahlte Nachfrage.",
    conv_opt2_btn: "Node registrieren",
    conv_opt2_dl: "Downloads",

    // Documentation Page (docs.html)
    docs_page_tag: "Developer-Preview-Dokumentation",
    docs_main_title: "ComputeMesh Architektur- & Integrationshandbuch",
    docs_main_sub: "Dokumentation der aktuell implementierten Gateway/Provider-Grundlagen und des validierten Forschungs-/Live-Entwicklungspfads. ComputeMesh ist weiterhin Pre-Production; Beispiele sind deployment-abhängig und bedeuten keine universelle Modell-, Hardware-, Latenz- oder Verfügbarkeitsunterstützung.",
    docs_readiness_alert: "<strong style=\"color: var(--text-main);\">Reifegrenze:</strong> Ein eng begrenzter physischer Zwei-Maschinen-Shared-Runtime-Beleg und substanzielle Control/Gateway-Grundlagen existieren; breite LAN/WAN-Validierung, Produktions-Dataplane-Sicherheit, provider-erzwungene Leases und Produktions-Key/Session-Härtung bleiben offen. Upstream llama.cpp RPC darf nicht direkt in einem nicht vertrauenswürdigen/öffentlichen Netzwerk exponiert werden.",
    docs_toc_title: "Inhalt",
    docs_toc_1: "1. Gateway/API-Schnellstart",
    docs_toc_2: "2. Verteilte Architektur",
    docs_toc_3: "3. Layer-Sharding-Forschung",
    docs_toc_4: "4. Provider-Node-Setup",
    docs_toc_5: "5. Mining-Rig NodeOS",
    docs_toc_6: "6. Ledger- & Billing-Grundlagen",
    docs_sec1_h2: "1. OpenAI-kompatibler Gateway-Schnellstart",
    docs_sec1_p: "Das Gateway implementiert eine OpenAI-kompatible Oberfläche für unterstützte Endpunkte wie Chat Completions und Modellauflistung. Das ist keine Behauptung von 100% Kompatibilität mit jedem OpenAI-API-Endpunkt oder SDK-Verhalten. Konfiguriere <code>base_url</code>, nutze einen registrierten ComputeMesh API-Key und wähle ein Modell, das das aktive Deployment tatsächlich exponiert.",
    docs_playground_h3: "⚡ Gateway-Playground im Browser",
    docs_playground_badge: "Verfügbarkeit hängt vom deployten Gateway/Katalog ab",
    docs_playground_send: "▶ Inferenz starten",
    playground_send: "▶ Inferenz starten",
    docs_playground_ph: "Prompt hier eingeben...",
    docs_terminal_title: "Gateway Antwort-Terminal",
    docs_terminal_ready: "Bereit",
    docs_terminal_init: "Wenn Gateway/Modell konfiguriert verfügbar sind, klicke auf \"Inferenz starten\", um die Anfrage zu senden.",
    docs_sec2_h2: "2. Verteilte Mesh-Architektur",
    docs_sec2_p: "ComputeMesh ist darauf ausgelegt, machbare Ausführungsplacements über heterogene Provider zu wählen. Der aktuelle Live-Entwicklungspfad nutzt einen authentifizierten Provider-Control-Kanal, einen privaten Produktions-Placement-Service, einen öffentlichen Executor und einen Zwei-Knoten llama.cpp Shared-Runtime-Pfad. Das bedeutet noch keine beliebige Peer-to-Peer-Ausführung über jede registrierte GPU.",
    docs_sec3_h2: "3. Pipeline-Layer-Sharding-Forschung",
    docs_sec3_p: "Kontinuierliches Layer-Splitting kann den Modell-Speicherbedarf pro Gerät senken, aber End-to-End-Performance hängt von exaktem Modell, Quantisierung, Runtime-Build, Split, GPU-Paar und Netzwerkpfad ab. ComputeMesh zeichnet deshalb reale Baseline-/Shared-Messungen und Netzwerk-Byte/Timing-Evidenz auf, statt eine theoretische Aktivierungsgröße als universelles Latenzergebnis zu behandeln. Jede PCIe- oder WAN-Performancezahl muss an eine benannte gemessene Konfiguration gebunden sein.",
    docs_sec4_h2: "4. Provider-Node einrichten",
    docs_sec4_p: "Ein ausführbarer öffentlicher Provider-Agent und ein Ed25519-Enrollment/Session-Pfad existieren. Tatsächliche Runtime-Unterstützung ist hardware-, treiber-, backend-, modell- und llama.cpp-build-abhängig; ComputeMesh behauptet nicht, dass jede moderne NVIDIA-, AMD- oder Intel-GPU produktionsunterstützt ist. Provider-Private-Keys werden im aktuellen SSH-Operator-Pfad beim Provider erzeugt/aufbewahrt; OS-geschützter Produktions-Key-Speicher bleibt ein Härtungspunkt.",
    docs_sec4_note: "Nutze veröffentlichte Installer nur, nachdem du geprüft hast, dass sie zum dokumentierten Release-/Deployment-Pfad für dein System passen.",
    docs_sec5_h2: "5. Mining-Rig NodeOS Appliance",
    docs_sec5_p: "NodeOS/Appliance-Werkzeuge existieren für Headless-Provider-Experimente, inklusive Hardware-/Backend-Erkennung und lokalem Dashboard. Exakte AMD/NVIDIA-Generationen, Treiberkombinationen und Multi-GPU-Topologien benötigen Zielsystem-Validierung; die Appliance ist kein Beleg dafür, dass jede Mining-Rig-Konfiguration produktionsreif ist.",
    docs_sec6_h2: "6. Ledger- & Billing-Grundlagen",
    docs_sec6_p: "Der öffentliche Code enthält eine auditierbare Double-Entry-Ledger-Grundlage sowie fail-closed Stripe Checkout/Webhook- und Provider-Settlement-Integrationspfade, wenn konfiguriert. Produktionsangebot, Marketplace, Margin/Take-Rate und Settlement-Hold-Policy gehören zur privaten Control Plane und werden auf dieser Dokumentationsseite nicht durch einen universellen Prozentsatz definiert. MetaMask/EVM-Adressen sind, wo sie in der aktuellen Provider-UI verwendet werden, Auszahlungsziel-Metadaten und kein Mechanismus zum Kauf von Rechenguthaben.",

    // Status Page (status.html)
    status_main_h2: "Pre-Production Engineering & Validierung",
    status_main_p: "ComputeMesh hat Gateway-, Provider-Control-, Provider-Agent-, Orchestrierungs-, Private-Placement- und gemessene Evidenz-Grundlagen implementiert. Es wird noch nicht als allgemein produktionsreifes öffentliches Distributed-Inference-Netzwerk dargestellt.",
    status_reviewed_date: "Dokumentationsstatus geprüft am 27. August 2026 UTC",
    status_tick1_val: "Implementiert",
    status_tick1_lbl: "Authentifizierte Provider-Control-Grundlage",
    status_tick2_val: "Eng begrenzter Beleg verifiziert",
    status_tick2_lbl: "Zwei-Maschinen-Shared-Runtime im vertrauenswürdigen Labor",
    status_tick3_val: "Live Cluster",
    status_tick3_lbl: "Authentifizierte Live-Metrik globaler Kapazität",
    status_tick4_val: "Offenes Gate",
    status_tick4_lbl: "Breite LAN/WAN-Produktionsvalidierung",
    status_boundaries_h3: "Validierte und verbleibende Grenzen",
    status_card1_h4: "✅ Software-Grundlagen",
    status_card1_p: "Authentifizierte Gateway/Provider-Control-Pfade, ausführbarer öffentlicher Provider-Agent, dauerhafte Orchestrierungs-/Recovery-Mechaniken, signierte private Placement-Entscheidungen, Ausführungsevidenz/Attestierungen und gemessenes Outcome-Feedback sind implementierte Grundlagen.",
    status_card2_h4: "🔬 Physische Messungen",
    status_card2_p: "Ein eng begrenzter Zwei-Maschinen llama.cpp Shared-Runtime-Beleg im vertrauenswürdigen Labor ist für seine exakte Hardware-, Modell-, Runtime- und Topologiebindung aufgezeichnet. Das ist keine universelle Performance- oder Produktionsreife-Behauptung.",
    status_card3_h4: "🔒 Runtime-Sicherheitsgrenze",
    status_card3_p: "Upstream llama.cpp RPC bleibt experimentell und ist keine öffentliche ComputeMesh-Sicherheitsgrenze. Aktueller Entwicklungs-Bring-up hält ihn hinter vertrauenswürdigen/privaten Netzwerken oder SSH-Tunneln.",
    status_card4_h4: "🧪 Verbleibende Reife-Gates",
    status_card4_p: "Repräsentative LAN/WAN-Messmatrizen, provider-erzwungene Ressourcen-Leases, Produktions-Dataplane- und Key/Session-Härtung, adversariales/System-Testing, kalibrierte private Performance-Prognose und Produktionsbetrieb/HA bleiben offen.",
    status_metrics_h3: "Über Statusmetriken",
    status_metrics_p: "Diese Seite zeigt bewusst keine Platzhalter für globale VRAM-, GPU-, Uptime- oder Gateway-Latenzwerte als wären sie live. Solche Metriken erscheinen nur, wenn sie in Echtzeit aus einem authentifizierten aktuellen Registry-/Telemetriepfad stammen.",

    // Benchmarks Page (benchmarks.html)
    bench_page_tag: "Gemessene Engineering-Evidenz",
    bench_main_h1: "Aufgezeichnete ComputeMesh-Benchmarks",
    bench_main_p: "Nur Messungen, die in der Engineering-Evidenz aufgezeichnet wurden, werden als gemessene Fakten gezeigt. Ergebnisse sind spezifisch für Modell, Hardware, Runtime-Build und Topologie und dürfen nicht auf andere Konfigurationen verallgemeinert werden.",
    bench_ttft_alert: "<strong style=\"color: var(--text-main);\">TTFT-Hinweis:</strong> Der aktuelle nicht-streamende Measured-Feedback-Pfad zeichnet Prefill, Decode und End-to-End-Anfragedauer auf, misst aber nicht direkt echte Time-to-First-Token. Diese Seite veröffentlicht deshalb keine erfundenen TTFT-Werte.",
    bench_th_evidence: "Evidenz",
    bench_th_hw: "Hardware / Topologie",
    bench_th_model: "Modellumfang",
    bench_th_prefill: "Prefill",
    bench_th_decode: "Decode",
    bench_th_interp: "Interpretation",
    bench_row1_title: "Lokaler llama.cpp-Benchmark",
    bench_row1_hw: "Windows / RTX 3080 Laptop GPU, CUDA",
    bench_row1_model: "7B-Q4-Benchmark-Artefakt aufgezeichnet am 21. August 2026",
    bench_row1_interp: "Nur lokale Single-Host-Evidenz",
    bench_row2_title: "Lokaler llama.cpp-Smoke-Benchmark",
    bench_row2_hw: "Debian 13 / CPU-only-Server",
    bench_row2_model: "0.5B-Q4-Smoke-Artefakt aufgezeichnet am 21. August 2026",
    bench_row2_interp: "Anderes Modell als der RTX-Lauf; nicht zu einem verteilten Ergebnis kombinieren",
    bench_row3_title: "Physischer Shared-Runtime-Beleg",
    bench_row3_hw: "Zwei-Maschinen-Topologie im vertrauenswürdigen Labor",
    bench_row3_model: "Exaktes Modell/Runtime/Topologie in Repository-Evidenz gebunden",
    bench_row3_prefill: "Siehe gebundenes Beleg-Artefakt",
    bench_row3_decode: "Siehe gebundenes Beleg-Artefakt",
    bench_row3_interp: "Exakte Ausgabe-/Token-Korrektheit wurde für diesen engen Beleg verifiziert; keine universelle Durchsatzbehauptung",
    bench_net_h3: "Netzwerk-Evidenz",
    bench_net_p: "Eine historische Windows-zu-Linux Engineering-TCP-Messung zeichnete RTT p50 11.884 ms, p95 13.369 ms, Upload p50 42.276 Mbit/s und Download p50 226.597 Mbit/s auf. Diese Internetpfad-Messung ist selbst kein Shared-Inference-Benchmark. Die aktuelle Matrix-Tooling kann echte kontrollierte Delay/Jitter-Shared-Runtime-Experimente ausführen; breitere Bandbreiten-, Paketverlust/Reordering- und WAN-Ergebnismatrizen bleiben Reifearbeit, bis sie aufgezeichnet sind.",
    bench_repro_h3: "Reproduzierbarkeitsregel",
    bench_repro_p: "Ein Benchmark ist nur mit exaktem Modell-Digest/-Größe, llama.cpp-Build-Identität, Hardware/Profil-Revision, Topologie, Split und Netzwerk-Evidenz aussagekräftig. Marketing-Schätzungen und hypothetische Hardwarekombinationen sind keine Benchmark-Ergebnisse.",

    // Contact Page (contact.html)
    contact_tag: "Kontakt aufnehmen",
    contact_title: "Support & Community Helpdesk",
    contact_sub: "Fragen zum Betrieb eines Provider-Mining-Rigs, zur Integration der OpenAI-API oder zum Erwerb von Enterprise-Rechenguthaben?",
    contact_name_lbl: "Dein Name",
    contact_topic_lbl: "Thema",
    contact_msg_lbl: "Nachricht",
    contact_send_btn: "Nachricht absenden",
    contact_opt_provider: "Mining-Rig & Hardware-Provider Support",
    contact_opt_developer: "Entwickler-API & Integration",
    contact_opt_billing: "Abrechnung & Guthabenaufladung",
    contact_opt_enterprise: "Individuelles Enterprise-Deployment",
    contact_success: "✓ Deine Nachricht wurde erfolgreich gesendet. Unser Engineering-Team antwortet innerhalb von 24 Stunden."
  }
};
window.portalTranslations = translations;

let currentLang = 'de';

function detectInitialLanguage() {
  try {
    const urlLang = new URLSearchParams(window.location.search).get('lang');
    if (urlLang === 'de' || urlLang === 'en') {
      localStorage.setItem('cm_portal_lang', urlLang);
      return urlLang;
    }
    const saved = localStorage.getItem('cm_portal_lang');
    if (saved === 'de' || saved === 'en') {
      return saved;
    }
  } catch (e) {}

  const browserLangs = [
    ...(Array.isArray(navigator.languages) ? navigator.languages : []),
    navigator.language,
    navigator.userLanguage
  ].filter(Boolean).map(lang => String(lang).toLowerCase());

  let timeZone = '';
  try {
    timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch (e) {}

  if (browserLangs.some(lang => lang.startsWith('de')) || timeZone === 'Europe/Berlin' || location.hostname.endsWith('.de')) {
    return 'de';
  }

  return 'de';
}

function switchLanguage(lang) {
  if (!lang || (lang !== 'de' && lang !== 'en')) {
    lang = 'de';
  }
  currentLang = lang;
  window.currentLang = lang;
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (translations[lang] && translations[lang][key] !== undefined) {
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        if (el.getAttribute('placeholder')) {
          el.setAttribute('placeholder', translations[lang][key]);
        } else {
          el.value = translations[lang][key];
        }
      } else if (el.tagName === 'OPTION') {
        el.textContent = translations[lang][key];
      } else {
        el.innerHTML = translations[lang][key];
      }
    }
  });
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    const key = el.getAttribute('data-i18n-ph');
    if (translations[lang] && translations[lang][key] !== undefined) {
      el.setAttribute('placeholder', translations[lang][key]);
    }
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (translations[lang] && translations[lang][key] !== undefined) {
      el.setAttribute('title', translations[lang][key]);
    }
  });
  const btn = document.getElementById('lang-toggle-btn');
  if (btn) {
    btn.textContent = lang === 'en' ? '🇩🇪 Deutsch' : '🇬🇧 English';
  }
  try {
    localStorage.setItem('cm_portal_lang', lang);
  } catch (e) {}
  updateCalculators();
  if (typeof window.syncComplianceLanguage === 'function') {
    window.syncComplianceLanguage(lang);
  }
  if (typeof window.syncPortalStaticLanguage === 'function') {
    window.syncPortalStaticLanguage(lang);
  }
}

function toggleLanguage() {
  const nextLang = currentLang === 'en' ? 'de' : 'en';
  switchLanguage(nextLang);
}

window.detectInitialLanguage = detectInitialLanguage;
window.switchLanguage = switchLanguage;
window.toggleLanguage = toggleLanguage;

// Canonical Pricing State
let CM_PRICING = {
  '8b': { blended: 0.175, cloud: 0.75 },
  '14b': { blended: 0.375, cloud: 1.50 },
  '32b': { blended: 0.60, cloud: 2.50 },
  '70b': { blended: 1.20, cloud: 5.00 },
};

async function loadCanonicalPricing() {
  try {
    const res = await fetch('/api/v1/pricing');
    if (res.ok) {
      const data = await res.json();
      if (data && data.tiers) {
        if (data.tiers['meta-llama/llama-3.1-8b-instruct']) {
          CM_PRICING['8b'].blended = data.tiers['meta-llama/llama-3.1-8b-instruct'].blended_usd_per_million;
          CM_PRICING['8b'].cloud = data.tiers['meta-llama/llama-3.1-8b-instruct'].cloud_reference_usd_per_million;
        }
        if (data.tiers['qwen/qwen2.5-14b-instruct']) {
          CM_PRICING['14b'].blended = data.tiers['qwen/qwen2.5-14b-instruct'].blended_usd_per_million;
          CM_PRICING['14b'].cloud = data.tiers['qwen/qwen2.5-14b-instruct'].cloud_reference_usd_per_million;
        }
        if (data.tiers['qwen/qwen2.5-32b-instruct']) {
          CM_PRICING['32b'].blended = data.tiers['qwen/qwen2.5-32b-instruct'].blended_usd_per_million;
          CM_PRICING['32b'].cloud = data.tiers['qwen/qwen2.5-32b-instruct'].cloud_reference_usd_per_million;
        }
        if (data.tiers['llama/llama-3.1-70b-instruct']) {
          CM_PRICING['70b'].blended = data.tiers['llama/llama-3.1-70b-instruct'].blended_usd_per_million;
          CM_PRICING['70b'].cloud = data.tiers['llama/llama-3.1-70b-instruct'].cloud_reference_usd_per_million;
        }
        updateCalculators();
      }
    }
  } catch (e) {}
}

// Pricing Calculators
function updateCalculators() {
  // Developer Calculator
  const tokensM = parseFloat(document.getElementById('slider-tokens')?.value || 50);
  const modelTier = document.getElementById('select-model')?.value || '8b';
  
  const tierCfg = CM_PRICING[modelTier] || CM_PRICING['8b'];
  const ratePerMillion = tierCfg.blended;
  const cloudRate = tierCfg.cloud;
  
  const cmCost = (tokensM * ratePerMillion).toFixed(2);
  const cloudCost = (tokensM * cloudRate).toFixed(2);
  
  const cmEl = document.getElementById('calc-cm-cost');
  const cloudEl = document.getElementById('calc-cloud-cost');
  const tokensVal = document.getElementById('tokens-val');
  
  if (cmEl) cmEl.textContent = `$${cmCost}`;
  if (cloudEl) cloudEl.textContent = `$${cloudCost}`;
  if (tokensVal) tokensVal.textContent = `${tokensM} M`;

  // Provider Calculator (75% net revenue payout from processed tokens)
  const rigType = document.getElementById('select-rig')?.value || '5x8gb';
  const hours = parseFloat(document.getElementById('slider-hours')?.value || 24);
  
  let monthlyYield = 145.0; // 5x 8GB base (~$145 net/month)
  if (rigType === 'rtx3080') monthlyYield = 65.0;
  else if (rigType === 'rtx4090') monthlyYield = 195.0;
  else if (rigType === '8x3070') monthlyYield = 310.0;
  
  const estEarnings = ((monthlyYield * (hours / 24))).toFixed(2);
  const earnedCredits = Math.round(Number(estEarnings) * 1000000); // 1 USD = 1,000,000 Credits (Micro-Units)
  const earnEl = document.getElementById('calc-provider-earnings');
  const hoursVal = document.getElementById('hours-val');
  
  if (earnEl) earnEl.innerHTML = `${(earnedCredits / 1000000).toFixed(2)}M CM <span style="font-size: 1.1rem; color: var(--accent-emerald); font-weight: 600;">($${estEarnings} / Mo)</span>`;
  if (hoursVal) hoursVal.textContent = currentLang === 'de' ? `${hours} h/Tag` : `${hours} h/day`;
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

async function handleRegistration(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const role = document.getElementById('modal-role').value;
  const email = form.querySelector('input[type="email"]')?.value || '';
  const wallet = form.querySelector('input[data-i18n="modal_wallet_placeholder"]')?.value || '';
  const keyInput = document.getElementById('generated-key-val');
  const resBox = document.getElementById('modal-result-box');
  if (keyInput) keyInput.value = currentLang === 'de' ? 'Registrierung läuft...' : 'Registering...';
  if (resBox) resBox.style.display = 'block';

  try {
    const resp = await fetch('/api/v1/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, role, wallet })
    });
    const data = await resp.json();
    if (!resp.ok || !data.api_key) {
      throw new Error(data.error || 'registration_failed');
    }
    if (keyInput) keyInput.value = data.api_key;
  } catch (err) {
    if (keyInput) {
      keyInput.value = currentLang === 'de'
        ? 'Registrierung fehlgeschlagen. Bitte später erneut versuchen.'
        : 'Registration failed. Please try again later.';
    }
  }
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

/* ==============================================================================
   Interactive AI Playground & Live Teaser Studio Controller
   ============================================================================== */

let playgroundChatHistory = [];
let teaserRequestsRemaining = 20;
let teaserResetAtMs = 0;
let isPlaygroundInferencing = false;

const QUICK_PROMPTS = {
  explain_mesh: "In 2 concise sentences, what is ComputeMesh and how does it achieve 80% lower inference costs?",
  python_fastapi: "Write a high-performance Python FastAPI server endpoint that forwards requests to an OpenAI-compatible /v1/chat/completions gateway with streaming.",
  gpu_sharding: "Explain how pipeline layer sharding works across multiple consumer GPUs connected via PCIe 1x mining risers.",
  compare_costs: "Provide a quick comparison table: ComputeMesh decentralized inference vs AWS Bedrock vs OpenAI API on 10M tokens."
};

function formatChatMarkdown(text) {
  if (!text) return "";
  // Escape basic HTML
  let escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  
  // Format code blocks ```python ... ```
  escaped = escaped.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
    const langLabel = lang ? `<div style="font-size:0.7rem; color:var(--accent-cyan); text-transform:uppercase; margin-bottom:0.25rem;">${lang}</div>` : '';
    return `<pre>${langLabel}<code>${code.trim()}</code></pre>`;
  });

  // Format inline code `...`
  escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Format bold **...**
  escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  // Format line breaks
  escaped = escaped.replace(/\n/g, '<br>');

  return escaped;
}

function formatResetDuration(ms) {
  const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.ceil((totalSeconds % 3600) / 60);
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return currentLang === 'de' ? `${Math.max(1, minutes)} Min.` : `${Math.max(1, minutes)} min`;
}

function updateTeaserQuota(remaining, limit, resetSeconds = 0, resetAt = "") {
  if (typeof remaining === 'number' && !isNaN(remaining)) {
    teaserRequestsRemaining = remaining;
    const parsedResetSeconds = parseInt(resetSeconds || "0", 10);
    const parsedResetAt = resetAt ? Date.parse(resetAt) : 0;
    teaserResetAtMs = parsedResetAt || (parsedResetSeconds > 0 ? Date.now() + parsedResetSeconds * 1000 : 0);
    const quotaTextEl = document.getElementById('pg-quota-text');
    if (quotaTextEl) {
      if (remaining <= 0 && teaserResetAtMs > Date.now()) {
        quotaTextEl.textContent = currentLang === 'de'
          ? `Pause: ${formatResetDuration(teaserResetAtMs - Date.now())}`
          : `Paused: ${formatResetDuration(teaserResetAtMs - Date.now())}`;
      } else if (currentLang === 'de') {
        quotaTextEl.textContent = `${remaining} Gratis-Anfragen übrig`;
      } else {
        quotaTextEl.textContent = `${remaining} Free Requests Left`;
      }
    }
  }
}

function openTeaserConversionModal() {
  const modal = document.getElementById('teaser-conversion-modal');
  if (modal) {
    modal.style.display = 'flex';
    modal.classList.add('active');
  }
}

function closeTeaserConversionModal() {
  const modal = document.getElementById('teaser-conversion-modal');
  if (modal) {
    modal.style.display = 'none';
    modal.classList.remove('active');
  }
}

function copyCliCommand(btn, cmd) {
  navigator.clipboard.writeText(cmd).then(() => {
    const originalText = btn.textContent;
    btn.textContent = "✓";
    setTimeout(() => { btn.textContent = originalText; }, 2000);
  }).catch(() => {
    alert("Copied: " + cmd);
  });
}

function clearPlaygroundChat() {
  playgroundChatHistory = [];
  const streamEl = document.getElementById('playground-chat-stream');
  if (streamEl) {
    const welcomeMsg = currentLang === 'de'
      ? "Willkommen bei ComputeMesh! Du kannst das Live-Gateway direkt hier mit 20 kostenlosen Anfragen pro 4-Stunden-Fenster ausprobieren. Stelle Programmierfragen, fasse Texte zusammen oder teste den Token-Durchsatz."
      : "Welcome to ComputeMesh! You can test the live gateway directly here with 20 free requests per 4-hour window. Ask a coding question, summarize text, or benchmark token throughput.";

    streamEl.innerHTML = `
      <div class="chat-msg chat-msg-ai">
        <div class="chat-avatar">🤖</div>
        <div class="chat-bubble">
          <div class="chat-author">ComputeMesh AI <span class="chat-badge">${currentLang === 'de' ? 'LIVE MESH' : 'LIVE MESH'}</span></div>
          <div class="chat-body">${welcomeMsg}</div>
        </div>
      </div>
    `;
  }
  const statusEl = document.getElementById('pg-metric-status');
  const tpsEl = document.getElementById('pg-metric-tps');
  const latEl = document.getElementById('pg-metric-latency');
  const tokEl = document.getElementById('pg-metric-tokens');
  if (statusEl) statusEl.textContent = currentLang === 'de' ? 'Bereit' : 'Ready';
  if (tpsEl) tpsEl.textContent = '— tok/s';
  if (latEl) latEl.textContent = '— ms';
  if (tokEl) tokEl.textContent = '0';
}

function applyQuickPrompt(promptKey) {
  const prompt = QUICK_PROMPTS[promptKey];
  const inputEl = document.getElementById('playground-prompt-input');
  if (prompt && inputEl) {
    inputEl.value = prompt;
    inputEl.focus();
    sendPlaygroundMessage();
  }
}

function handlePlaygroundKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendPlaygroundMessage();
  }
}

async function runPlaygroundPrompt() {
  const modelEl = document.getElementById('playground-model');
  const inputEl = document.getElementById('playground-input');
  const outputEl = document.getElementById('playground-output');
  const statsEl = document.getElementById('playground-stats');
  const btnEl = document.getElementById('playground-btn');

  if (!modelEl || !inputEl || !outputEl) return;

  const promptText = inputEl.value.trim();
  if (!promptText) return;

  const lang = currentLang === 'de' ? 'de' : 'en';
  if (btnEl) btnEl.disabled = true;
  if (statsEl) statsEl.textContent = lang === 'de' ? 'Anfrage läuft...' : 'Running request...';
  outputEl.textContent = lang === 'de' ? 'Gateway wird angefragt...' : 'Contacting gateway...';

  try {
    const started = performance.now();
    const response = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: modelEl.value,
        messages: [{ role: 'user', content: promptText }],
        stream: false
      })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error?.message || data.error || response.statusText);

    const answer = data.choices?.[0]?.message?.content || data.message?.content || '';
    const elapsedMs = Math.round(performance.now() - started);
    outputEl.textContent = answer || (lang === 'de' ? 'Keine Antwort erhalten.' : 'No response received.');
    if (statsEl) statsEl.textContent = `${elapsedMs} ms`;
  } catch (error) {
    outputEl.textContent = lang === 'de'
      ? `Gateway-Anfrage fehlgeschlagen: ${error.message || 'unbekannter Fehler'}`
      : `Gateway request failed: ${error.message || 'unknown error'}`;
    if (statsEl) statsEl.textContent = lang === 'de' ? 'Fehlgeschlagen' : 'Failed';
  } finally {
    if (btnEl) btnEl.disabled = false;
  }
}

window.runPlaygroundPrompt = runPlaygroundPrompt;

async function sendPlaygroundMessage() {
  if (isPlaygroundInferencing) return;

  const inputEl = document.getElementById('playground-prompt-input');
  const modelEl = document.getElementById('playground-model-select');
  const streamEl = document.getElementById('playground-chat-stream');
  const sendBtn = document.getElementById('playground-send-btn');
  const sendBtnText = document.getElementById('pg-send-btn-text');
  const statusEl = document.getElementById('pg-metric-status');
  const tpsEl = document.getElementById('pg-metric-tps');
  const latEl = document.getElementById('pg-metric-latency');
  const tokEl = document.getElementById('pg-metric-tokens');

  if (!inputEl || !modelEl || !streamEl) return;

  const promptText = inputEl.value.trim();
  if (!promptText) return;

  // Check quota limit
  if (teaserRequestsRemaining <= 0 && teaserResetAtMs > Date.now()) {
    openTeaserConversionModal();
    return;
  }

  // Clear input
  inputEl.value = "";
  inputEl.style.height = "44px";

  // Append user message to UI
  const userMsgHtml = `
    <div class="chat-msg chat-msg-user">
      <div class="chat-avatar">👤</div>
      <div class="chat-bubble">
        <div class="chat-author" style="color: #c7d2fe;">You</div>
        <div class="chat-body">${formatChatMarkdown(promptText)}</div>
      </div>
    </div>
  `;
  streamEl.insertAdjacentHTML('beforeend', userMsgHtml);

  // Append AI placeholder bubble
  const aiMsgId = 'ai-msg-' + Date.now();
  const aiMsgHtml = `
    <div class="chat-msg chat-msg-ai">
      <div class="chat-avatar">🤖</div>
      <div class="chat-bubble">
        <div class="chat-author">ComputeMesh AI <span class="chat-badge">LIVE MESH</span></div>
        <div class="chat-body" id="${aiMsgId}"><span class="chat-cursor"></span></div>
      </div>
    </div>
  `;
  streamEl.insertAdjacentHTML('beforeend', aiMsgHtml);
  streamEl.scrollTop = streamEl.scrollHeight;

  const aiBodyEl = document.getElementById(aiMsgId);

  // Lock UI state
  isPlaygroundInferencing = true;
  if (sendBtn) sendBtn.disabled = true;
  if (sendBtnText) sendBtnText.textContent = currentLang === 'de' ? 'Generiere...' : 'Inferencing...';
  if (statusEl) {
    statusEl.textContent = currentLang === 'de' ? 'Routing Mesh...' : 'Routing Mesh...';
    statusEl.className = 'pg-metric-val';
  }

  const model = modelEl.value;
  playgroundChatHistory.push({ role: 'user', content: promptText });

  const startTime = performance.now();
  let firstTokenTime = 0;
  let rawAiText = "";
  let tokenCount = 0;

  try {
    const response = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-ComputeMesh-Client': 'web-playground-v1.2.19'
      },
      body: JSON.stringify({
        model: model,
        messages: playgroundChatHistory.slice(-6),
        stream: true,
        temperature: 0.7
      })
    });

    // Extract teaser remaining headers
    const remainingHdr = response.headers.get('X-ComputeMesh-Teaser-Remaining');
    const limitHdr = response.headers.get('X-ComputeMesh-Teaser-Limit');
    const resetSecondsHdr = response.headers.get('X-ComputeMesh-Teaser-Reset-Seconds');
    const resetAtHdr = response.headers.get('X-ComputeMesh-Teaser-Reset-At');
    if (remainingHdr) {
      updateTeaserQuota(parseInt(remainingHdr, 10), parseInt(limitHdr || '20', 10), resetSecondsHdr || "0", resetAtHdr || "");
    } else {
      teaserRequestsRemaining = Math.max(0, teaserRequestsRemaining - 1);
      updateTeaserQuota(teaserRequestsRemaining, 20);
    }

    if (response.status === 402 || response.status === 429) {
      const errJson = await response.json().catch(() => ({}));
      const retryAfter = parseInt(response.headers.get('Retry-After') || errJson.teaser?.retry_after_seconds || "0", 10);
      if (retryAfter > 0) {
        teaserResetAtMs = Date.now() + retryAfter * 1000;
      }
      const fallbackMsg = currentLang === 'de'
        ? `Kostenloses Demo-Limit erreicht. Deine Anfragen werden in ${formatResetDuration((retryAfter || 3600) * 1000)} automatisch freigeschaltet.`
        : `Free demo limit reached. Your requests refresh automatically in ${formatResetDuration((retryAfter || 3600) * 1000)}.`;
      const errMsg = errJson.message || errJson.error?.message || fallbackMsg;
      if (aiBodyEl) {
        aiBodyEl.innerHTML = `<span style="color: #f87171;">${errMsg}</span>`;
      }
      openTeaserConversionModal();
      return;
    }

    if (!response.ok) {
      const errText = await response.text();
      if (aiBodyEl) {
        aiBodyEl.innerHTML = `<span style="color: #f87171;">Inference error (${response.status}): ${errText}</span>`;
      }
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
          if (dataStr === "[DONE]") break;
          try {
            const parsed = JSON.parse(dataStr);
            const delta = parsed.choices?.[0]?.delta?.content || "";
            if (delta) {
              if (!firstTokenTime) {
                firstTokenTime = performance.now();
                const latencyMs = Math.round(firstTokenTime - startTime);
                if (latEl) latEl.textContent = `${latencyMs} ms`;
              }
              rawAiText += delta;
              tokenCount++;
              if (aiBodyEl) {
                aiBodyEl.innerHTML = formatChatMarkdown(rawAiText) + '<span class="chat-cursor"></span>';
              }
              streamEl.scrollTop = streamEl.scrollHeight;

              const elapsedSec = (performance.now() - (firstTokenTime || startTime)) / 1000;
              const tps = (tokenCount / Math.max(elapsedSec, 0.05)).toFixed(1);
              if (tpsEl) tpsEl.textContent = `${tps} tok/s`;
              if (tokEl) tokEl.textContent = `${tokenCount}`;
            }
          } catch (e) {
            // Ignore SSE json chunk split
          }
        }
      }
    }

    // Finalize message rendering
    if (aiBodyEl) {
      aiBodyEl.innerHTML = formatChatMarkdown(rawAiText);
    }
    playgroundChatHistory.push({ role: 'assistant', content: rawAiText });

    const totalElapsedSec = ((performance.now() - startTime) / 1000).toFixed(2);
    const finalTps = (tokenCount / Math.max(parseFloat(totalElapsedSec), 0.05)).toFixed(1);
    if (statusEl) {
      statusEl.textContent = currentLang === 'de' ? 'Abgeschlossen' : 'Completed';
      statusEl.className = 'pg-metric-val emerald';
    }
    if (tpsEl) tpsEl.textContent = `${finalTps} tok/s`;
    if (tokEl) tokEl.textContent = `${tokenCount}`;

  } catch (err) {
    if (aiBodyEl) {
      aiBodyEl.innerHTML = `<span style="color: #f87171;">Connection error: ${err.message}</span>`;
    }
    if (statusEl) {
      statusEl.textContent = currentLang === 'de' ? 'Fehler' : 'Error';
      statusEl.className = 'pg-metric-val';
    }
  } finally {
    isPlaygroundInferencing = false;
    if (sendBtn) sendBtn.disabled = false;
    if (sendBtnText) sendBtnText.textContent = currentLang === 'de' ? 'Prompt senden' : 'Send Prompt';
    streamEl.scrollTop = streamEl.scrollHeight;
  }
}

function parseMeshTelemetryPayload(data) {
  if (!data || typeof data !== 'object') return null;

  if (data.global_mesh && data.global_mesh.source === 'authenticated_registry') {
    return {
      source: data.global_mesh.source,
      totalVramGb: Number(data.global_mesh.total_vram_gb || 0),
      activeGpus: Number(data.global_mesh.total_gpus_active || 0),
      totalNodes: Number(data.global_mesh.total_nodes_online || 0)
    };
  }

  return {
    source: data.source,
    totalVramGb: Number(data.total_vram_gb || 0),
    activeGpus: Number(data.active_gpus || 0),
    totalNodes: Number(data.total_nodes || 0)
  };
}

function updateMeshTelemetryTicker(stats) {
  const vramEl = document.getElementById('portal-ticker-vram');
  const gpusEl = document.getElementById('portal-ticker-gpus');
  const hasLiveCapacity = stats
    && stats.source
    && stats.source !== 'not_configured'
    && (stats.totalVramGb > 0 || stats.activeGpus > 0);

  if (!hasLiveCapacity) {
    if (vramEl) vramEl.textContent = currentLang === 'de' ? 'Keine Live-Daten' : 'No live data';
    if (gpusEl) gpusEl.textContent = currentLang === 'de' ? 'Keine GPU online' : 'No GPU online';
    return;
  }

  const locale = currentLang === 'de' ? 'de-DE' : 'en-US';
  const gpuWord = stats.activeGpus === 1 ? 'GPU' : 'GPUs';
  if (vramEl) {
    vramEl.textContent = `${stats.totalVramGb.toLocaleString(locale, { maximumFractionDigits: 1 })} GB`;
  }
  if (gpusEl) {
    gpusEl.textContent = currentLang === 'de'
      ? `${stats.activeGpus} ${gpuWord} online`
      : `${stats.activeGpus} ${gpuWord} online`;
  }
}

async function fetchMeshTelemetry() {
  const endpoints = ['/api/v1/mesh/stats', '/mesh/stats', '/api/status'];
  try {
    for (const endpoint of endpoints) {
      const res = await fetch(endpoint, { cache: 'no-store' });
      if (!res.ok) continue;
      const stats = parseMeshTelemetryPayload(await res.json());
      if (stats) {
        updateMeshTelemetryTicker(stats);
        return;
      }
    }
    updateMeshTelemetryTicker(null);
  } catch (e) {
    updateMeshTelemetryTicker(null);
  }
}

// Initialize on DOM load or immediately if already loaded
let _portalInitialized = false;
function initPortal() {
  if (_portalInitialized) return;
  _portalInitialized = true;

  const initialLang = detectInitialLanguage();
  switchLanguage(initialLang);
  
  document.getElementById('slider-tokens')?.addEventListener('input', updateCalculators);
  document.getElementById('select-model')?.addEventListener('change', updateCalculators);
  document.getElementById('select-rig')?.addEventListener('change', updateCalculators);
  document.getElementById('slider-hours')?.addEventListener('input', updateCalculators);
  
  updateCalculators();
  loadCanonicalPricing();
  fetchMeshTelemetry();
  setInterval(fetchMeshTelemetry, 15000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initPortal);
} else {
  initPortal();
}

window.initPortal = initPortal;
