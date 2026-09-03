/* ==============================================================================
   ComputeMesh Portal Client Logic: i18n (DE/EN), Calculators & Subpages
   ============================================================================== */

const translations = {
  en: {
    // Navigation & Common
    nav_home: "Home",
    nav_features: "Features",
    nav_pricing: "Pricing & Calculator",
    nav_downloads: "Downloads",
    nav_docs: "API Docs",
    nav_benchmarks: "Benchmarks",
    nav_status: "Network Status",
    nav_register: "Get API Key",
    nav_topup: "💳 Credits",
    nav_playground: "⚡ Live Playground",
    nav_legal: "Legal",
    nav_security: "🛡️ Security & GDPR",
    nav_privacy: "Privacy",
    nav_terms: "Terms",
    nav_impressum: "Legal Notice",
    nav_support: "Support",
    back_to_home: "← Back to Home",
    footer_brand_desc: "Decentralized high-performance GPU compute fabric for next-generation AI workloads. Scale effortlessly with OpenAI-compatible APIs.",
    footer_col_platform: "Platform",
    footer_col_resources: "Resources",
    footer_col_legal: "Legal & Compliance",
    footer_rights: "All rights reserved. Decentralized AI Mesh Architecture.",
    footer_tech_status: "Network Status: Operational",

    // Hero Section
    hero_tagline: "⚡ Distributed GPU Compute. Infinite AI Scale.",
    hero_title: "High-Performance AI Inference.<br><span class=\"gradient-text\">Decentralized. Scalable. 80% Lower Cost.</span>",
    hero_sub: "ComputeMesh unifies distributed GPUs into an ultra-fast, resilient compute fabric. Deploy open-source LLMs through our drop-in OpenAI-compatible API at a fraction of hyperscaler pricing, or monetize your idle GPUs with automated payouts.",
    btn_start_inferencing: "⚡ Launch Live Playground",
    btn_provide_compute: "🖥️ Monetize GPUs",
    ticker_vram: "Active Mesh VRAM",
    ticker_gpus: "Connected GPUs Online",
    ticker_tflops: "Mesh Compute Power",
    ticker_nodes: "Distributed Cluster Nodes",

    // Playground Section
    pg_tag: "INTERACTIVE DEMO",
    pg_title: "Experience <span class=\"gradient-text\">Real-Time Mesh Inference</span>",
    pg_sub: "Test our low-latency distributed GPU network directly in your browser. Choose an open-source model and start streaming responses instantly.",
    pg_model_lbl: "Model:",
    pg_quota_pill: "Free Demo Credits",
    pg_cluster_pending: "Connecting to Mesh...",
    pg_ai_author: "ComputeMesh AI",
    pg_ai_badge: "LIVE MESH",
    pg_ai_welcome: "Welcome to ComputeMesh! Our distributed inference cluster is online and ready. How can I assist you with your project today?",
    pg_status_lbl: "Status:",
    pg_status_ready: "Ready",
    pg_speed_lbl: "Generation Speed:",
    pg_latency_lbl: "TTFT / Latency:",
    pg_tokens_lbl: "Tokens Streamed:",
    qp_explain_mesh: "⚡ What makes ComputeMesh unique?",
    qp_python_fastapi: "🐍 Write a streaming FastAPI client",
    qp_gpu_sharding: "🧩 How does pipeline layer sharding work?",
    qp_compare_costs: "💰 Estimate my cost savings",
    pg_prompt_placeholder: "Type a prompt or test inference speed... (Enter to send, Shift+Enter for newline)",
    pg_send_btn: "Send Prompt",
    pg_ollama_title: "Ollama & OpenAI Compatible Endpoint",
    pg_ollama_badge: "Instant Drop-in",
    pg_ollama_desc: "Use ComputeMesh with any existing OpenAI client library, LangChain, LlamaIndex, or Ollama CLI by simply pointing your base URL to our gateway.",
    pg_copy_cmd_btn: "📋 Copy Command",
    pg_copy_code_btn: "📋 Copy Code",

    // Features Section
    features_tag: "ENTERPRISE ARCHITECTURE",
    features_title: "Next-Generation Distributed AI Infrastructure",
    features_sub: "Engineered from the ground up for low-latency inference, dynamic load balancing, and cryptographic verification across global GPU nodes.",
    feat1_title: "Intelligent Pipeline Sharding",
    feat1_desc: "Large language models are dynamically partitioned across distributed GPUs with optimized tensor streaming, maximizing token throughput while minimizing network overhead.",
    feat2_title: "Heterogeneous GPU Pooling",
    feat2_desc: "Seamlessly combine NVIDIA (CUDA), AMD (ROCm), and Apple Silicon hardware into a unified compute fabric, maximizing total cluster efficiency.",
    feat3_title: "Smart Latency-Aware Placement",
    feat3_desc: "Our real-time routing engine matches incoming inference requests to the optimal GPU nodes based on live latency, bandwidth, and available VRAM.",
    feat4_title: "100% Drop-in OpenAI API",
    feat4_desc: "Zero migration effort: Compatible with official OpenAI SDKs, LangChain, AutoGPT, and LiteLLM. Just update your base URL and API key.",
    feat5_title: "One-Click Provider Agent",
    feat5_desc: "Turn idle gaming PCs, workstations, and mining rigs into revenue streams with our native, auto-configuring installers for Windows and Linux.",
    feat6_title: "Cryptographic Attestation & Ledger",
    feat6_desc: "Every inference execution is verified with Ed25519 signatures. Our tamper-proof double-entry ledger guarantees transparent accounting and automated payouts.",

    // Pricing / Calculator Section
    calc_tag: "TRANSPARENT PRICING",
    calc_title: "Calculate Your Savings & Provider Revenue",
    calc_sub: "Save up to 80% compared to traditional cloud hyperscalers, or turn your compute hardware into a predictable monthly revenue stream.",
    tab_developer: "👨‍💻 Developers: Cost Savings Calculator",
    tab_provider: "⚡ Providers: Earnings Calculator",
    lbl_monthly_tokens: "Monthly Inference Volume (Million Tokens)",
    lbl_model_tier: "Model Size / Class",
    lbl_computemesh_cost: "Estimated ComputeMesh Cost",
    lbl_cloud_cost: "Traditional Cloud Cost:",
    lbl_your_savings: "Save up to 80% on AI compute costs",
    lbl_gpu_setup: "Hardware Setup / GPU Tier",
    lbl_hours_online: "Daily Online Time",
    lbl_est_earnings: "Estimated Monthly Revenue",
    lbl_payout_note: "Payouts are calculated in real time based on verified compute units. Automatic transfers via Stripe Connect or crypto starting from $25.00.",
    lbl_provider_threshold_info: "💡 <strong>Automated Payouts:</strong> Hardware providers receive 75% of customer revenue. Earnings are credited directly to your account ledger and paid out automatically.",
    commercial_plans_title: "Custom Enterprise Solutions",
    commercial_plans_desc: "Need dedicated private GPU clusters, guaranteed enterprise SLAs, custom model fine-tuning endpoints, or on-premise deployments? Our team is here to help.",
    btn_contact_sales: "Contact Enterprise Sales",

    // Downloads Section
    dl_tag: "PROVIDER SOFTWARE",
    dl_title: "Start Earning with Your Hardware in Minutes",
    dl_sub: "Download our native provider agents to connect your GPUs to the decentralized mesh and earn automated payouts for every processed token.",
    dl_win_title: "Windows Provider Agent",
    dl_win_desc: "Complete desktop application with system tray status, GPU auto-detection, and silent background daemon.",
    dl_win_btn: "Download for Windows (.exe)",
    dl_linux_title: "Linux Headless Daemon",
    dl_linux_desc: "High-performance daemon optimized for Ubuntu, Debian, mining rigs, and Docker containers.",
    dl_linux_btn: "Copy Install Command",
    dl_rig_title: "Mining Rig Appliance (NodeOS)",
    dl_rig_desc: "Dedicated bootable bare-metal OS for multi-GPU mining rigs (4–12 GPUs) with zero-configuration setup.",
    dl_rig_iso_btn: "Download Bootable ISO (.iso)",
    dl_rig_img_btn: "Download Flash Image (.img.xz)",
    dl_rig_tar_btn: "Download Linux Package (.tar.gz)",
    dl_rig_guide_btn: "NodeOS Setup Guide",

    // API Section
    api_tag: "DEVELOPER INTEGRATION",
    api_title: "Two Lines of Code. Zero Migration Overhead.",
    api_sub: "Use your existing OpenAI client libraries without rewriting your application. Simply swap the base URL and authenticate with your ComputeMesh API key.",

    // Modals
    modal_title: "Get Started with ComputeMesh",
    modal_sub: "Create your API key in seconds for high-speed AI inference or connect your hardware.",
    modal_role_lbl: "Account Type:",
    role_consumer: "Developer API (Run AI Inference)",
    role_provider: "Hardware Provider (Monetize GPUs)",
    modal_email_lbl: "Business Email Address",
    modal_country_lbl: "Operating Country (EEA Region)",
    modal_country_select: "Select Country…",
    modal_wallet_lbl: "Payout Destination / Wallet (Optional)",
    modal_wallet_placeholder: "0x... (EVM / Polygon / Arbitrum)",
    modal_wallet_help: "For automated provider earnings payouts via crypto or Stripe Connect.",
    modal_submit_btn: "🚀 Generate API Key",
    modal_key_result_lbl: "Your Personal API Key:",
    modal_copy_btn: "Copy Key",
    compliance_combined: "I agree to the <a href=\"/terms\" target=\"_blank\" rel=\"noopener\">Terms of Service v2.1</a> & <a href=\"/privacy\" target=\"_blank\" rel=\"noopener\">Privacy Policy</a> and confirm business (B2B) use.",
    topup_modal_title: "💳 Top Up Compute Credits",
    topup_modal_sub: "Add inference credits securely via Stripe Checkout. Credits never expire and are billed per actual token generated.",
    topup_key_lbl: "Your API Key:",
    topup_select_amount_lbl: "Select deposit amount:",
    btn_topup_proceed: "Proceed to Secure Checkout →",
    conv_tag: "Start Building",
    conv_title: "Ready to Accelerate Your AI Workloads?",
    conv_sub: "Get your API key today or join our growing network of global GPU providers.",
    conv_opt1_badge: "Developer",
    conv_opt1_title: "🔑 Instant API Access",
    conv_opt1_desc: "Start inferencing with high-throughput open-source models in under 60 seconds.",
    conv_opt1_btn: "Get Free API Key →",
    conv_opt2_badge: "Hardware Provider",
    conv_opt2_title: "⚡ Monetize Compute",
    conv_opt2_desc: "Connect your GPUs and earn passive income with automatic weekly payouts.",
    conv_opt2_btn: "Register GPU Node",
    conv_opt2_dl: "View Downloads",

    // Documentation Page (docs.html)
    docs_page_tag: "DEVELOPER GUIDE",
    docs_main_title: "ComputeMesh Architecture & Integration Guide",
    docs_main_sub: "Comprehensive guide to integrating the OpenAI-compatible gateway, setting up distributed GPU nodes, and optimizing inference workloads.",
    docs_readiness_alert: "<strong style=\"color: var(--text-main);\">Live Mesh Gateway:</strong> ComputeMesh provides high-speed, cryptographically verified AI inference. Point your OpenAI SDK or LangChain client directly to our gateway endpoint.",
    docs_toc_title: "Table of Contents",
    docs_toc_1: "1. Quickstart & OpenAI API",
    docs_toc_2: "2. Distributed Mesh Architecture",
    docs_toc_3: "3. Pipeline Layer Sharding",
    docs_toc_4: "4. Provider Node Setup",
    docs_toc_5: "5. Multi-GPU Mining Rig OS",
    docs_toc_6: "6. Ledger & Billing Mechanics",
    docs_sec1_h2: "1. OpenAI-Compatible API Quickstart",
    docs_sec1_p: "ComputeMesh implements a 100% OpenAI-compatible `/v1` REST API for chat completions and model discovery. Simply update `base_url` and use your ComputeMesh API key in any language SDK (Python, Node.js, Go, Rust, cURL).",
    docs_playground_h3: "⚡ Interactive Browser Playground",
    docs_playground_badge: "Live Streaming",
    docs_playground_send: "▶ Run Inference",
    playground_send: "▶ Run Inference",
    docs_playground_ph: "Enter your prompt here...",
    docs_terminal_title: "Gateway Response Terminal",
    docs_terminal_ready: "Connected",
    docs_terminal_init: "Click \"Run Inference\" to stream live tokens directly from the mesh.",
    docs_sec2_h2: "2. Distributed Mesh Architecture",
    docs_sec2_p: "ComputeMesh connects independent GPU nodes into a unified, high-throughput compute fabric. Requests are routed dynamically based on live latency, available VRAM, and model availability.",
    docs_sec3_h2: "3. Pipeline Layer-Sharding Technology",
    docs_sec3_p: "Our intelligent tensor-splitting engine partitions large parameter models across multiple GPUs with optimized peer-to-peer pipelining, allowing massive models to run smoothly across consumer hardware.",
    docs_sec4_h2: "4. Hardware Provider Node Setup",
    docs_sec4_p: "Join the mesh in minutes using our native provider daemon. Available for Windows (with desktop tray icon) and Linux (headless daemon and Docker containers).",
    docs_sec4_note: "All provider communications are secured using mTLS and Ed25519 cryptographic keys.",
    docs_sec5_h2: "5. Mining Rig NodeOS Appliance",
    docs_sec5_p: "NodeOS is a lightweight, dedicated Linux OS designed specifically for multi-GPU mining rigs (4 to 12 GPUs). It features automatic hardware detection, optimal driver tuning, and zero-touch mesh enrollment.",
    docs_sec6_h2: "6. Transparent Ledger & Automated Billing",
    docs_sec6_p: "Inference workloads and provider rewards are accounted for in an immutable, double-entry ledger. Hardware providers receive 75% of customer token fees with automatic Stripe Connect or cryptocurrency payouts.",

    // Status Page (status.html)
    status_main_h2: "System & Network Status",
    status_main_p: "Real-time telemetry, node availability, and operational health across the global ComputeMesh infrastructure.",
    status_reviewed_date: "All systems operational",
    status_tick1_val: "Operational",
    status_tick1_lbl: "Gateway & API Endpoints",
    status_tick2_val: "Operational",
    status_tick2_lbl: "Distributed GPU Mesh Fabric",
    status_tick3_val: "Live Telemetry",
    status_tick3_lbl: "Active Mesh Capacity",
    status_tick4_val: "Verified",
    status_tick4_lbl: "Ed25519 Execution Attestations",
    status_boundaries_h3: "Network Infrastructure Overview",
    status_card1_h4: "✅ Core Ingestion & Gateway",
    status_card1_p: "High-throughput OpenAI-compatible API gateway with edge load balancing, rate limiting, and mTLS verification.",
    status_card2_h4: "⚡ Distributed GPU Placement Engine",
    status_card2_p: "Latency-aware request placement matching workloads to optimal GPU node clusters in real time.",
    status_card3_h4: "🔒 Cryptographic Security & Isolation",
    status_card3_p: "Isolated execution sandboxes with zero prompt persistence, DPAPI node key protection, and cryptographic execution proofs.",
    status_card4_h4: "💳 Real-time Ledger & Settlement",
    status_card4_p: "High-precision micro-unit double-entry ledger supporting instant balance deductions and automated provider earnings distribution.",
    status_metrics_h3: "Live Infrastructure Metrics",
    status_metrics_p: "Telemetry data is updated in real time directly from active cluster nodes.",

    // Benchmarks Page (benchmarks.html)
    bench_page_tag: "PERFORMANCE BENCHMARKS",
    bench_main_h1: "ComputeMesh Performance & Throughput",
    bench_main_p: "Empirical performance benchmarks across leading open-source models, GPU architectures, and distributed node configurations.",
    bench_ttft_alert: "<strong style=\"color: var(--text-main);\">High-Throughput Streaming:</strong> ComputeMesh optimizes both Time-to-First-Token (TTFT) and sustained token generation speed across distributed node clusters.",
    bench_th_evidence: "Configuration",
    bench_th_hw: "Hardware Topology",
    bench_th_model: "Model Architecture",
    bench_th_prefill: "Time to First Token",
    bench_th_decode: "Generation Speed",
    bench_th_interp: "Performance Tier",
    bench_row1_title: "Single-Node High-Speed Inferenz",
    bench_row1_hw: "NVIDIA RTX 4090 / 3080 GPU, CUDA 12",
    bench_row1_model: "Llama 3.1 8B (Q4_K_M)",
    bench_row1_interp: "Ultra-Fast Edge Inference",
    bench_row2_title: "CPU & Edge Baseline",
    bench_row2_hw: "Server CPU Architecture (x86_64)",
    bench_row2_model: "Qwen 2.5 7B (Q4_K_M)",
    bench_row2_interp: "Reliable Fallback Compute",
    bench_row3_title: "Distributed Pipeline Sharding",
    bench_row3_hw: "Multi-Node Mesh Cluster",
    bench_row3_model: "Llama 3.1 70B (Pipeline Split)",
    bench_row3_prefill: "< 120 ms",
    bench_row3_decode: "45+ tok/s",
    bench_row3_interp: "Enterprise Distributed Scale",
    bench_net_h3: "Network Routing & Throughput",
    bench_net_p: "Our low-overhead binary RPC wire protocol and optimized tensor streaming ensure that distributed inference runs with minimal communication latency.",
    bench_repro_h3: "Reproducible Benchmarks",
    bench_repro_p: "All benchmark figures reflect real-world execution metrics captured on active mesh nodes with standardized prompt lengths.",

    // Contact Page (contact.html)
    contact_tag: "GET IN TOUCH",
    contact_title: "Enterprise & Developer Support",
    contact_sub: "Have questions about integrating the ComputeMesh API, running a high-yield provider node, or deploying private compute clusters?",
    contact_name_lbl: "Your Name / Company",
    contact_topic_lbl: "Topic",
    contact_msg_lbl: "Message",
    contact_send_btn: "Send Message",
    contact_opt_provider: "Hardware Provider & Mining Rig Setup",
    contact_opt_developer: "Developer API & Platform Integration",
    contact_opt_billing: "Billing & Enterprise Invoicing",
    contact_opt_enterprise: "Custom Enterprise GPU Clusters & SLAs",
    contact_success: "✓ Thank you! Your message has been received. Our engineering team will respond within 24 hours.",

    // Security & GDPR Page (security.html)
    sec_page_tag: "ENTERPRISE COMPLIANCE & CRYPTOGRAPHY",
    sec_main_title: "Security & <span class=\"gradient-emerald\">GDPR Architecture</span>",
    sec_main_sub: "ComputeMesh was engineered under the strict principle of <strong>ephemeral zero-knowledge streaming (Privacy by Design under Art. 25 GDPR)</strong>. Input prompts and generated responses are mathematically immune to eavesdropping in transit and are never stored on disk.",
    sec_pill_1_title: "100% Eavesdropping Immune",
    sec_pill_1_desc: "End-to-end encryption via <strong>TLS 1.3 with Perfect Forward Secrecy (PFS)</strong>. An ephemeral single-use session key is generated for every inference request. Retroactive interception or decryption is mathematically impossible.",
    sec_pill_2_title: "Encrypted RAM & Zero-Retention",
    sec_pill_2_desc: "Prompts are held exclusively in volatile RAM inside <strong>ephemeral AES-256-GCM memory envelopes</strong> with OS page locking (<code>mlock</code>) and immediate <code>SecureZeroMemory</code> bitwise wiping upon completion.",
    sec_pill_3_title: "Zero Model Training",
    sec_pill_3_desc: "Neither your prompts nor AI outputs are ever used to train, retrain, or fine-tune models. Your data and intellectual property remain 100% yours.",
    sec_sec1_title: "<span>🔒</span> 1. Protection Against Eavesdropping & Interception (Transport Encryption)",
    sec_sec1_intro: "All communication between your client applications (OpenAI SDK, LangChain, Python, Browser) and our gateway is enforced using state-of-the-art cryptographic cipher suites:",
    sec_sec1_li1: "<strong>TLS 1.3 & Elliptic Curves:</strong> Key exchange via X25519 with authenticated AES-256-GCM and ChaCha20-Poly1305 ciphers.",
    sec_sec1_li2: "<strong>Perfect Forward Secrecy (PFS):</strong> Even in the theoretical future event of primary certificate compromise, past captured traffic can never be decrypted.",
    sec_sec1_li3: "<strong>HSTS Preload:</strong> Strict Transport Security enforced across all subdomains (2-year preload cache), preventing downgrade or man-in-the-middle attacks.",
    sec_sec1_li4: "<strong>RAM-Only Reverse Proxy Streaming:</strong> Nginx directive <code>proxy_max_temp_file_size 0;</code> guarantees that request/response streams never buffer to disk.",
    sec_sec2_title: "<span>⚡</span> 2. Volatile RAM Processing & Storage Limitation (Art. 5 GDPR)",
    sec_sec2_intro: "Our gateway architecture (<code>computemesh-gateway</code>) is explicitly implemented at source code level to eliminate prompt payload logging:",
    sec_sec2_li1: "<strong>No Database Logging of Text:</strong> The billing ledger exclusively tracks anonymous numerical counters (e.g. <code>Prompt: 45 Tokens</code>, <code>Completion: 128 Tokens</code>, <code>Cost: $0.0001</code>) — never your raw text.",
    sec_sec2_li2: "<strong>Instant Purge:</strong> As soon as the final token chunk is transmitted via Server-Sent Events (SSE) (<code>data: [DONE]</code>), all buffer memory is immediately freed.",
    sec_sec3_title: "<span>🧩</span> 3. Blinded Split-Inference, mTLS & Hardware Attestation",
    sec_sec3_intro: "Communication between the central orchestrator and distributed GPU nodes is strictly isolated via mutual mTLS, node keys (Ed25519), and orthogonal tensor blinding:",
    sec_sec3_li1: "<strong>Blinded Split-Inference:</strong> Layer-0 embeddings are mathematically blinded ($h' = h \\cdot R$) before dispatching to worker nodes. Remote nodes process pure numerical tensors without access to vocabulary or plain text.",
    sec_sec3_li2: "<strong>Confidential Computing (TEE):</strong> For highly confidential enterprise jobs, ComputeMesh supports hardware attestation (AMD SEV-SNP / Intel TDX), ensuring computation occurs inside encrypted hardware enclaves.",
    sec_sec3_li3: "<strong>Fail-Closed Routing:</strong> Workloads marked for strict confidentiality are never silently downgraded to untrusted nodes.",
    sec_sec4_title: "<span>📋</span> 4. EU GDPR Compliance Matrix",
    sec_tbl_col1: "GDPR Article",
    sec_tbl_col2: "Legal Requirement",
    sec_tbl_col3: "ComputeMesh Technical Implementation",
    sec_tbl_r1_req: "Data Minimization",
    sec_tbl_r1_impl: "No tracking pixels, no advertising cookies, zero persistent storage of prompt payloads.",
    sec_tbl_r2_req: "Storage Limitation",
    sec_tbl_r2_impl: "Zero-Disk-Retention: Prompts exist solely for milliseconds in volatile RAM.",
    sec_tbl_r3_req: "Integrity & Confidentiality",
    sec_tbl_r3_impl: "TLS 1.3 with PFS, node-bound mTLS, AES-256-GCM encrypted vault, systemd sandboxing.",
    sec_tbl_r4_req: "Privacy by Design & Default",
    sec_tbl_r4_impl: "Architectural decoupling of billing metrics and inference payload; fail-closed security logic.",
    sec_tbl_r5_req: "Data Processing Agreement (DPA)",
    sec_tbl_r5_impl: "Standard Art. 28 GDPR DPA agreement available for all B2B business customers.",
    sec_tbl_r6_req: "Security of Processing",
    sec_tbl_r6_impl: "Multi-layer technical and organizational measures (TOMs) meeting state-of-the-art industry benchmarks.",
    sec_sec5_title: "<span>🏰</span> 5. Server Sandboxing & Payment Data Isolation",
    sec_sec5_li1: "<strong>Linux Systemd Sandboxing:</strong> Gateway daemon runs under Debian 13 with strict kernel restrictions (<code>ProtectSystem=strict</code>, <code>PrivateTmp=true</code>, <code>NoNewPrivileges=true</code>).",
    sec_sec5_li2: "<strong>Stripe PCI-DSS Level 1:</strong> Credit card and payment details are never processed or held by ComputeMesh servers, passing exclusively through Stripe.",
    sec_sec5_li3: "<strong>AES-256-GCM Secret Vault:</strong> Internal credentials and control secrets are secured within a hardened cryptographic vault.",
    sec_cta_title: "Ready for Maximum Security and Unmatched Performance?",
    sec_cta_sub: "Leverage our high-speed OpenAI-compatible API with full European GDPR data protection.",
    sec_cta_playground_btn: "⚡ Launch Live Playground",
    sec_cta_register_btn: "🚀 Generate API Key"
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
    nav_register: "API-Key holen",
    nav_topup: "💳 Guthaben",
    nav_playground: "⚡ Live-Playground",
    nav_legal: "Rechtliches",
    nav_security: "🛡️ Sicherheit & DSGVO",
    nav_privacy: "Datenschutz",
    nav_terms: "AGB",
    nav_impressum: "Impressum",
    nav_support: "Support",
    back_to_home: "← Zurück zur Startseite",
    footer_brand_desc: "Dezentrale High-Performance GPU-Rechenleistung für moderne KI-Workloads. Nahtlos skalieren mit OpenAI-kompatibler API.",
    footer_col_platform: "Plattform",
    footer_col_resources: "Ressourcen",
    footer_col_legal: "Rechtliches & Compliance",
    footer_rights: "Alle Rechte vorbehalten. Dezentrale KI-Mesh-Architektur.",
    footer_tech_status: "Systemstatus: Voll einsatzbereit",

    // Hero Section
    hero_tagline: "⚡ Verteilte GPU-Power. Unendliche KI-Skalierung.",
    hero_title: "High-Performance KI-Inferenz.<br><span class=\"gradient-text\">Dezentral. Skalierbar. 80% günstiger.</span>",
    hero_sub: "ComputeMesh bündelt verteilte GPU-Rechenleistung zu einem nahtlosen, extrem schnellen Inferenz-Netzwerk. Nutze modernste Open-Source-LLMs über unsere OpenAI-kompatible High-Speed-API zu einem Bruchteil herkömmlicher Cloud-Preise oder verdiene attraktive Erträge mit deinen eigenen Grafikkarten.",
    btn_start_inferencing: "⚡ Live-Playground testen",
    btn_provide_compute: "🖥️ Hardware anbieten",
    ticker_vram: "Aktiver Mesh-VRAM",
    ticker_gpus: "Verbundene GPUs online",
    ticker_tflops: "Mesh-Rechenleistung",
    ticker_nodes: "Verteilte Cluster-Knoten",

    // Playground Section
    pg_tag: "INTERAKTIVE DEMO",
    pg_title: "Erlebe die <span class=\"gradient-text\">Geschwindigkeit des Meshs</span>",
    pg_sub: "Teste unsere ultra-schnelle Streaming-Inferenz direkt im Browser. Wähle ein Open-Source-Modell und sende deinen ersten Prompt.",
    pg_model_lbl: "Modell:",
    pg_quota_pill: "Kostenloses Demo-Guthaben",
    pg_cluster_pending: "Verbinde mit Mesh-Cluster...",
    pg_ai_author: "ComputeMesh AI",
    pg_ai_badge: "LIVE MESH",
    pg_ai_welcome: "Willkommen bei ComputeMesh! Unser dezentrales Inferenz-Netzwerk ist online. Wie kann ich dir heute bei deinem Projekt helfen?",
    pg_status_lbl: "Status:",
    pg_status_ready: "Bereit",
    pg_speed_lbl: "Geschwindigkeit:",
    pg_latency_lbl: "TTFT / Latenz:",
    pg_tokens_lbl: "Generierte Tokens:",
    qp_explain_mesh: "⚡ Was macht ComputeMesh einzigartig?",
    qp_python_fastapi: "🐍 Schreibe einen Streaming FastAPI-Endpunkt",
    qp_gpu_sharding: "🧩 Wie funktioniert Pipeline-Layer-Sharding?",
    qp_compare_costs: "💰 Berechne meine Kostenersparnis",
    pg_prompt_placeholder: "Stelle eine Frage oder teste die Inferenz-Geschwindigkeit... (Enter zum Senden, Shift+Enter für neue Zeile)",
    pg_send_btn: "Prompt senden",
    pg_ollama_title: "Ollama & OpenAI-kompatibler Endpunkt",
    pg_ollama_badge: "Sofort einsatzbereit",
    pg_ollama_desc: "Nutze ComputeMesh mit jedem bestehenden OpenAI SDK, LangChain, LlamaIndex oder dem Ollama CLI – passe einfach deine Base-URL an.",
    pg_copy_cmd_btn: "📋 Befehl kopieren",
    pg_copy_code_btn: "📋 Code kopieren",

    // Features Section
    features_tag: "ENTERPRISE-ARCHITEKTUR",
    features_title: "Modernste Technologie für maximale Performance",
    features_sub: "Von intelligentem Layer-Splitting bis hin zu kryptografischen Ausführungsnachweisen – gebaut für höchste Zuverlässigkeit und minimale Latenzen.",
    feat1_title: "Intelligentes Pipeline-Sharding",
    feat1_desc: "Große Modelle werden dynamisch und verlustfrei über mehrere GPUs und Standorte aufgeteilt. Unser intelligentes Sharding minimiert Latenzen und maximiert den Token-Durchsatz.",
    feat2_title: "Heterogenes GPU-Pooling",
    feat2_desc: "Kombiniere NVIDIA (CUDA), AMD (ROCm) und Apple Silicon in einem einheitlichen Rechencluster für optimale Hardware-Auslastung.",
    feat3_title: "Smart Latency-Aware Placement",
    feat3_desc: "Unser Placement-Optimizer platziert Anfragen in Echtzeit auf den geografisch und bandbreitentechnisch optimalen Knoten für unübertroffene Reaktionszeiten.",
    feat4_title: "100% OpenAI-kompatible API",
    feat4_desc: "Nahtloser Drop-in-Ersatz für OpenAI SDKs, LangChain, LlamaIndex und AutoGPT. Einfach die Base-URL ändern und sofort bis zu 80% Kosten sparen.",
    feat5_title: "One-Click Provider Node",
    feat5_desc: "Einfachste Einrichtung für Hardware-Besitzer: Unser Installer für Windows und Linux erkennt Grafikkarten automatisch und bindet sie sicher ein.",
    feat6_title: "Kryptografische Sicherheit & Ledger",
    feat6_desc: "Jede Inferenz wird durch Ed25519-Signaturen attestiert. Unser transparenter Double-Entry-Ledger garantiert faire Abrechnungen und pünktliche Auszahlungen.",

    // Pricing / Calculator Section
    calc_tag: "TRANSPARENTE PREISE",
    calc_title: "Faire Preise & lukrative Provider-Erträge",
    calc_sub: "Spare bis zu 80% gegenüber herkömmlichen Cloud-Anbietern oder verwandle ungenutzte Grafikkarten in eine kontinuierliche Einnahmequelle.",
    tab_developer: "👨‍💻 Entwickler: Kostenersparnis berechnen",
    tab_provider: "⚡ Provider: Einnahmen berechnen",
    lbl_monthly_tokens: "Monatliches Inferenzvolumen (Millionen Tokens)",
    lbl_model_tier: "Modellgröße / Klasse",
    lbl_computemesh_cost: "Geschätzte ComputeMesh-Kosten",
    lbl_cloud_cost: "Traditionelle Hyperscaler-Kosten:",
    lbl_your_savings: "Bis zu 80% Ersparnis gegenüber AWS & Azure",
    lbl_gpu_setup: "Hardware-Konfiguration / GPU-Klasse",
    lbl_hours_online: "Tägliche Online-Zeit",
    lbl_est_earnings: "Geschätzte monatliche Einnahmen",
    lbl_payout_note: "Verdiente Credits werden in Echtzeit berechnet und transparent verbucht. Automatische Auszahlungen ab $25.00 via Stripe Connect oder Krypto.",
    lbl_provider_threshold_info: "💡 <strong>Automatische Auszahlungen:</strong> Hardware-Provider erhalten 75% des gesamten Kundenumsatzes. Auszahlungen erfolgen automatisiert auf dein hinterlegtes Konto.",
    commercial_plans_title: "Individuelle Enterprise-Lösungen",
    commercial_plans_desc: "Du benötigst dedizierte GPU-Cluster, garantierte SLAs oder On-Premise-Deployments? Unser Enterprise-Team erstellt gerne ein maßgeschneidertes Angebot.",
    btn_contact_sales: "Enterprise-Beratung anfragen",

    // Downloads Section
    dl_tag: "PROVIDER-SOFTWARE",
    dl_title: "Starte als Hardware-Provider in wenigen Minuten",
    dl_sub: "Lade den passenden Agenten für dein System herunter und mache deine Grafikkarten sofort zu einer profitablen Einnahmequelle.",
    dl_win_title: "Windows Provider Agent",
    dl_win_desc: "Vollständige Desktop-App mit System-Tray-Status, automatischer GPU-Erkennung und unauffälligem Hintergrunddienst.",
    dl_win_btn: "Für Windows herunterladen (.exe)",
    dl_linux_title: "Linux Headless Daemon",
    dl_linux_desc: "High-Performance-Daemon optimiert für Ubuntu, Debian, Mining-Rigs und Server. Einzeilige Installation.",
    dl_linux_btn: "Installationsbefehl kopieren",
    dl_rig_title: "Mining-Rig Appliance (NodeOS)",
    dl_rig_desc: "Eigenständiges, bootfähiges Linux-Betriebssystem für Multi-GPU-Mining-Rigs (4–12 GPUs) mit Zero-Touch-Konfiguration.",
    dl_rig_iso_btn: "Bootfähige ISO herunterladen (.iso)",
    dl_rig_img_btn: "Flash-Image herunterladen (.img.xz)",
    dl_rig_tar_btn: "Linux-Paket herunterladen (.tar.gz)",
    dl_rig_guide_btn: "NodeOS Setup Guide",

    // API Section
    api_tag: "ENTWICKLER-SCHNITTSTELLE",
    api_title: "Zwei Zeilen Code. Sofort einsatzbereit.",
    api_sub: "Binde ComputeMesh nahtlos in jede bestehende Anwendung ein – 100% kompatibel mit den offiziellen OpenAI-SDKs.",

    // Modals
    modal_title: "Mit ComputeMesh starten",
    modal_sub: "Erstelle deinen API-Key in wenigen Sekunden für blitzschnelle KI-Inferenz.",
    modal_role_lbl: "Konto-Typ:",
    role_consumer: "Developer-API nutzen (KI-Inferenz ausführen)",
    role_provider: "Hardware-Provider werden (GPUs monetarisieren)",
    modal_email_lbl: "Geschäftliche E-Mail-Adresse",
    modal_country_lbl: "Provider-Betriebsland (EWR/EU)",
    modal_country_select: "Land auswählen…",
    modal_wallet_lbl: "Auszahlungsziel / Wallet (Optional)",
    modal_wallet_placeholder: "0x... (EVM / Polygon / Arbitrum)",
    modal_wallet_help: "Für automatisierte Auszahlungen deiner Provider-Einnahmen via Stripe oder Krypto.",
    modal_submit_btn: "🚀 API-Key generieren",
    modal_key_result_lbl: "Dein persönlicher API-Key:",
    modal_copy_btn: "Schlüssel kopieren",
    compliance_combined: "Ich akzeptiere die <a href=\"/terms\" target=\"_blank\" rel=\"noopener\">Nutzungsbedingungen v2.1</a> & <a href=\"/privacy\" target=\"_blank\" rel=\"noopener\">Datenschutzerklärung</a> und bestätige die geschäftliche Nutzung (B2B).",
    topup_modal_title: "💳 Rechenguthaben aufladen",
    topup_modal_sub: "Lade dein Inferenzguthaben sicher über Stripe Checkout auf. Guthaben verfällt nie und wird nur bei erfolgreicher Token-Generierung abgerechnet.",
    topup_key_lbl: "Dein API-Schlüssel:",
    topup_select_amount_lbl: "Aufladebetrag auswählen:",
    btn_topup_proceed: "Weiter zum sicheren Checkout →",
    conv_tag: "Jetzt durchstarten",
    conv_title: "Bereit für High-Speed KI-Inferenz?",
    conv_sub: "Generiere deinen API-Key oder werde Teil unseres globalen GPU-Netzwerks.",
    conv_opt1_badge: "Entwickler",
    conv_opt1_title: "🔑 Sofortiger API-Zugang",
    conv_opt1_desc: "Starte in unter 60 Sekunden mit leistungsstarken Open-Source-Modellen.",
    conv_opt1_btn: "Kostenlosen API-Key holen →",
    conv_opt2_badge: "Hardware-Provider",
    conv_opt2_title: "⚡ Rechenleistung monetarisieren",
    conv_opt2_desc: "Schließe deine Grafikkarten an und profitiere von automatischen Auszahlungen.",
    conv_opt2_btn: "GPU-Node registrieren",
    conv_opt2_dl: "Downloads ansehen",

    // Documentation Page (docs.html)
    docs_page_tag: "ENTWICKLER-DOKUMENTATION",
    docs_main_title: "ComputeMesh Architektur- & Integrationshandbuch",
    docs_main_sub: "Umfassende Dokumentation zur Integration des OpenAI-kompatiblen Gateways, zur Einrichtung von Provider-Knoten und zur Skalierung von Workloads.",
    docs_readiness_alert: "<strong style=\"color: var(--text-main);\">Live Mesh Gateway:</strong> ComputeMesh bietet blitzschnelle, kryptografisch verifizierte KI-Inferenz. Richte dein OpenAI SDK oder deinen LangChain-Client direkt an unser Gateway.",
    docs_toc_title: "Inhalt",
    docs_toc_1: "1. Schnellstart & OpenAI API",
    docs_toc_2: "2. Verteilte Mesh-Architektur",
    docs_toc_3: "3. Pipeline-Layer-Sharding",
    docs_toc_4: "4. Provider-Node einrichten",
    docs_toc_5: "5. Mining-Rig NodeOS",
    docs_toc_6: "6. Ledger & Abrechnung",
    docs_sec1_h2: "1. OpenAI-kompatibler Gateway-Schnellstart",
    docs_sec1_p: "Das Gateway implementiert eine vollständige OpenAI-kompatible `/v1`-REST-Schnittstelle. Passe einfach die `base_url` an und nutze deinen ComputeMesh API-Key in Python, TypeScript, Go oder cURL.",
    docs_playground_h3: "⚡ Interaktiver Browser-Playground",
    docs_playground_badge: "Live Streaming",
    docs_playground_send: "▶ Inferenz starten",
    playground_send: "▶ Inferenz starten",
    docs_playground_ph: "Prompt hier eingeben...",
    docs_terminal_title: "Gateway Antwort-Terminal",
    docs_terminal_ready: "Verbunden",
    docs_terminal_init: "Klicke auf \"Inferenz starten\", um Tokens live aus dem Mesh zu streamen.",
    docs_sec2_h2: "2. Verteilte Mesh-Architektur",
    docs_sec2_p: "ComputeMesh verbindet unabhängige GPU-Knoten zu einem einheitlichen Rechennetzwerk. Anfragen werden dynamisch nach Latenz, VRAM und Durchsatz geroutet.",
    docs_sec3_h2: "3. Pipeline-Layer-Sharding-Technologie",
    docs_sec3_p: "Unsere Sharding-Engine teilt große Sprachmodelle dynamisch auf mehrere GPUs auf, sodass auch sehr große Modelle auf handelsüblicher Hardware mit maximaler Geschwindigkeit laufen.",
    docs_sec4_h2: "4. Provider-Node einrichten",
    docs_sec4_p: "Tritt dem Netzwerk in wenigen Minuten bei. Unser nativer Agent steht für Windows (mit übersichtlicher Tray-App) und Linux (als Server-Daemon und Docker) zur Verfügung.",
    docs_sec4_note: "Alle Verbindungen sind Ende-zu-Ende über mTLS und Ed25519-Schlüssel gesichert.",
    docs_sec5_h2: "5. Mining-Rig NodeOS Appliance",
    docs_sec5_p: "NodeOS ist ein maßgeschneidertes, bootfähiges Linux-Betriebssystem für Multi-GPU-Mining-Rigs (4 bis 12 GPUs) mit automatischer Treiber-Konfiguration und Plug-and-Play-Anbindung.",
    docs_sec6_h2: "6. Transparenter Ledger & automatische Abrechnung",
    docs_sec6_p: "Alle Inferenz-Abrechnungen und Provider-Vergütungen werden in einem manipulationssicheren Double-Entry-Ledger geführt. Hardware-Provider erhalten 75% des Kundenumsatzes mit automatischen Auszahlungen.",

    // Status Page (status.html)
    status_main_h2: "System- & Netzwerkstatus",
    status_main_p: "Echtzeit-Telemetrie, Knotenverfügbarkeit und Betriebszustand der globalen ComputeMesh-Infrastruktur.",
    status_reviewed_date: "Alle Systeme voll einsatzbereit",
    status_tick1_val: "Einsatzbereit",
    status_tick1_lbl: "Gateway & API-Endpunkte",
    status_tick2_val: "Einsatzbereit",
    status_tick2_lbl: "Verteiltes GPU-Inferenz-Mesh",
    status_tick3_val: "Live-Telemetrie",
    status_tick3_lbl: "Aktive Mesh-Kapazität",
    status_tick4_val: "Verifiziert",
    status_tick4_lbl: "Ed25519 Ausführungs-Attestierungen",
    status_boundaries_h3: "Infrastruktur-Übersicht",
    status_card1_h4: "✅ Ingestion & Gateway-Layer",
    status_card1_p: "Hochperformantes OpenAI-kompatibles Gateway mit dynamischem Lastenausgleich und mTLS-Sicherheit.",
    status_card2_h4: "⚡ Dezentrale GPU-Placement-Engine",
    status_card2_p: "Latenzoptimiertes Echtzeit-Matching von Inferenzanfragen auf die besten GPU-Knoten.",
    status_card3_h4: "🔒 Kryptografische Isolation & Sicherheit",
    status_card3_p: "Isolierte Ausführungsumgebungen ohne Speicherung von Prompt-Inhalten und mit OS-geschützten Schlüsseln (Windows DPAPI / POSIX).",
    status_card4_h4: "💳 Echtzeit-Ledger & Abrechnung",
    status_card4_p: "Mikro-Einheiten-Double-Entry-Ledger für sekundengenaue Verbuchung und automatisierte Provider-Auszahlungen.",
    status_metrics_h3: "Live-Infrastruktur-Metriken",
    status_metrics_p: "Telemetriedaten werden in Echtzeit von den aktiven Cluster-Knoten bezogen.",

    // Benchmarks Page (benchmarks.html)
    bench_page_tag: "PERFORMANCE-BENCHMARKS",
    bench_main_h1: "ComputeMesh Geschwindigkeit & Durchsatz",
    bench_main_p: "Reale Leistungsmessungen über führende Open-Source-Modelle, GPU-Architekturen und verteilte Knoten-Konfigurationen.",
    bench_ttft_alert: "<strong style=\"color: var(--text-main);\">High-Throughput Streaming:</strong> ComputeMesh optimiert sowohl die Time-to-First-Token (TTFT) als auch die kontinuierliche Generierungsgeschwindigkeit.",
    bench_th_evidence: "Konfiguration",
    bench_th_hw: "Hardware-Topologie",
    bench_th_model: "Modell-Architektur",
    bench_th_prefill: "Time to First Token",
    bench_th_decode: "Generierungstempo",
    bench_th_interp: "Performance-Klasse",
    bench_row1_title: "Single-Node High-Speed Inferenz",
    bench_row1_hw: "NVIDIA RTX 4090 / 3080 GPU, CUDA 12",
    bench_row1_model: "Llama 3.1 8B (Q4_K_M)",
    bench_row1_interp: "Ultra-Fast Edge Inference",
    bench_row2_title: "CPU & Edge Baseline",
    bench_row2_hw: "Server CPU-Architektur (x86_64)",
    bench_row2_model: "Qwen 2.5 7B (Q4_K_M)",
    bench_row2_interp: "Zuverlässige Ausweich-Rechenleistung",
    bench_row3_title: "Verteiltes Pipeline-Sharding",
    bench_row3_hw: "Multi-Node Mesh-Cluster",
    bench_row3_model: "Llama 3.1 70B (Pipeline Split)",
    bench_row3_prefill: "< 120 ms",
    bench_row3_decode: "45+ tok/s",
    bench_row3_interp: "Enterprise Distributed Scale",
    bench_net_h3: "Netzwerk-Routing & Latenz",
    bench_net_p: "Unser binäres RPC-Wire-Protokoll und optimiertes Tensor-Streaming stellen sicher, dass verteilte Inferenz ohne spürbaren Netzwerk-Overhead läuft.",
    bench_repro_h3: "Verifizierbare Messungen",
    bench_repro_p: "Alle Benchmark-Daten basieren auf realen Messungen im aktiven Mesh-Netzwerk mit standardisierten Prompt-Längen.",

    // Contact Page (contact.html)
    contact_tag: "KONTAKT AUFNEHMEN",
    contact_title: "Support & Enterprise-Beratung",
    contact_sub: "Hast du Fragen zur API-Integration, zum Betrieb eines Provider-Mining-Rigs oder zu dedizierten Enterprise-Clustern?",
    contact_name_lbl: "Dein Name / Unternehmen",
    contact_topic_lbl: "Thema",
    contact_msg_lbl: "Nachricht",
    contact_send_btn: "Nachricht absenden",
    contact_opt_provider: "Hardware-Provider & Mining-Rig Setup",
    contact_opt_developer: "Entwickler-API & Plattform-Integration",
    contact_opt_billing: "Abrechnung & Guthabenaufladung",
    contact_opt_enterprise: "Individuelle Enterprise-GPU-Cluster & SLAs",
    contact_success: "✓ Vielen Dank! Deine Nachricht wurde empfangen. Unser Engineering-Team antwortet innerhalb von 24 Stunden.",

    // Security & GDPR Page (security.html)
    sec_page_tag: "ENTERPRISE COMPLIANCE & KRYPTOGRAFIE",
    sec_main_title: "Sicherheits- & <span class=\"gradient-emerald\">DSGVO-Architektur</span>",
    sec_main_sub: "ComputeMesh wurde nach dem strikten Prinzip des <strong>flüchtigen Zero-Knowledge-Streamings (Privacy-by-Design nach Art. 25 DSGVO)</strong> entwickelt. Eingegebene Prompts und generierte Antworten sind auf dem Transportweg mathematisch abhörsicher und werden niemals auf Festplatten gespeichert.",
    sec_pill_1_title: "100% Abhörsicher",
    sec_pill_1_desc: "End-to-End-Verschlüsselung via <strong>TLS 1.3 mit Perfect Forward Secrecy (PFS)</strong>. Für jede Inferenz-Sitzung wird ein Einmalschlüssel erzeugt. Ein nachträgliches Mitschneiden oder Entschlüsseln ist mathematisch unmöglich.",
    sec_pill_2_title: "Verschlüsselter RAM & Zero-Retention",
    sec_pill_2_desc: "Prompts existieren ausschließlich im flüchtigen RAM in <strong>ephemeren AES-256-GCM Umschlägen</strong> mit OS-Speichersperren (<code>mlock</code> Anti-Swap) und sofortigem <code>SecureZeroMemory</code> Überschreiben.",
    sec_pill_3_title: "Kein Modell-Training",
    sec_pill_3_desc: "Weder deine Prompts noch die KI-Antworten werden jemals zum Trainieren, Nachtrainieren oder Feintunen von Modellen genutzt. Deine Daten und dein IP bleiben zu 100% dein Eigentum.",
    sec_sec1_title: "<span>🔒</span> 1. Schutz vor Datenabfangen & Mitlesen (Transportverschlüsselung)",
    sec_sec1_intro: "Jede Verbindung zwischen deinen Anwendungen (OpenAI SDK, LangChain, Python, Browser) und unserem Gateway wird über hochsichere kryptografische Cipher-Suites abgewickelt:",
    sec_sec1_li1: "<strong>TLS 1.3 & Elliptische Kurven:</strong> Schlüsselaustausch über X25519 mit AES-256-GCM und ChaCha20-Poly1305.",
    sec_sec1_li2: "<strong>Perfect Forward Secrecy (PFS):</strong> Selbst bei einer theoretischen Kompromittierung des Hauptzertifikats in der Zukunft kann vergangener Datenverkehr niemals entschlüsselt werden.",
    sec_sec1_li3: "<strong>HSTS Preload:</strong> Erzwingt HTTPS über alle Subdomains (2 Jahre Cache) und verhindert jegliche Downgrade-Angriffe.",
    sec_sec1_li4: "<strong>RAM-Only Proxy-Streaming:</strong> Die Nginx-Direktive <code>proxy_max_temp_file_size 0;</code> garantiert, dass keine Request-Bodies auf Festplatten-Puffer ausgelagert werden.",
    sec_sec2_title: "<span>⚡</span> 2. Flüchtige RAM-Verarbeitung & Speicherbegrenzung (Art. 5 DSGVO)",
    sec_sec2_intro: "Unsere Gateway-Architektur (<code>computemesh-gateway</code>) ist im Quellcode so programmiert, dass sie keine Protokolle über Prompt-Inhalte führt:",
    sec_sec2_li1: "<strong>Keine Datenbank-Speicherung:</strong> Die Abrechnungsdatenbank erfasst ausschließlich anonymisierte Zählerwerte (z. B. <code>Prompt: 45 Tokens</code>, <code>Antwort: 128 Tokens</code>, <code>Kosten: $0.0001</code>) — niemals deinen Text.",
    sec_sec2_li2: "<strong>Sofortige Freigabe:</strong> Sobald der letzte Token-Chunk per Server-Sent Events (SSE) an deinen Client übermittelt wurde (<code>data: [DONE]</code>), wird der belegte Arbeitsspeicher sofort freigegeben.",
    sec_sec3_title: "<span>🧩</span> 3. Blinded Split-Inference, mTLS & Hardware-Attestierung",
    sec_sec3_intro: "Die Kommunikation zwischen Orchestrator und verteilten GPU-Knoten ist durch mTLS, Ed25519-Signaturen und orthogonale Tensor-Verschleierung isoliert:",
    sec_sec3_li1: "<strong>Blinded Split-Inference:</strong> Layer-0 Embeddings werden mathematisch rotiert ($h' = h \\cdot R$), bevor Shards an Nodes gesendet werden. Externe Nodes rechnen rein numerisch ohne Vokabular- oder Text-Zugriff.",
    sec_sec3_li2: "<strong>Confidential Computing (TEE):</strong> Für vertrauliche Unternehmensanfragen unterstützt ComputeMesh Hardware-Attestierung (AMD SEV-SNP / Intel TDX), wodurch Berechnungen in hardware-verschlüsselten Enklaven ausgeführt werden.",
    sec_sec3_li3: "<strong>Fail-Closed Routing:</strong> Vertrauliche Anfragen werden niemals heimlich auf ungesicherte Knoten umgeleitet.",
    sec_sec4_title: "<span>📋</span> 4. EU-DSGVO Konformitätsmatrix",
    sec_tbl_col1: "DSGVO-Artikel",
    sec_tbl_col2: "Gesetzliche Anforderung",
    sec_tbl_col3: "Technische Umsetzung bei ComputeMesh",
    sec_tbl_r1_req: "Datenminimierung",
    sec_tbl_r1_impl: "Keine Werbe-Tracker, keine Cookies, keine dauerhafte Speicherung von Nutzdaten.",
    sec_tbl_r2_req: "Speicherbegrenzung",
    sec_tbl_r2_impl: "Zero-Disk-Retention: Prompts existieren nur für Millisekunden im flüchtigen RAM.",
    sec_tbl_r3_req: "Integrität & Vertraulichkeit",
    sec_tbl_r3_impl: "TLS 1.3 mit PFS, mTLS-Knotenbindung, AES-256-GCM Vault, Systemd-Sandbox.",
    sec_tbl_r4_req: "Privacy by Design",
    sec_tbl_r4_impl: "Architektonische Trennung von Abrechnung und Inhalten; Fail-Closed-Sicherheitslogik.",
    sec_tbl_r5_req: "Auftragsverarbeitung (AVV)",
    sec_tbl_r5_impl: "Vertrag zur Auftragsverarbeitung (DPA) für B2B-Kunden verfügbar.",
    sec_tbl_r6_req: "Sicherheit der Verarbeitung",
    sec_tbl_r6_impl: "Mehrstufige technische und organisatorische Maßnahmen (TOMs) nach aktuellem Stand der Technik.",
    sec_sec5_title: "<span>🏰</span> 5. Server-Sandboxing & Zahlungsdaten-Isolierung",
    sec_sec5_li1: "<strong>Linux-Systemd-Sandboxing:</strong> Der Gateway-Dienst läuft unter Debian 13 mit strikten Kernel-Restriktionen (<code>ProtectSystem=strict</code>, <code>PrivateTmp=true</code>, <code>NoNewPrivileges=true</code>).",
    sec_sec5_li2: "<strong>Stripe PCI-DSS Level 1:</strong> Zahlungen und Kreditkartendaten werden niemals über ComputeMesh-Server geleitet, sondern direkt durch Stripe verarbeitet.",
    sec_sec5_li3: "<strong>AES-256-GCM Vault:</strong> Alle internen Secrets sind im kryptografischen Vault abgesichert.",
    sec_cta_title: "Bereit für maximale Sicherheit und höchste Performance?",
    sec_cta_sub: "Nutze unsere OpenAI-kompatible High-Speed-API mit vollem Datenschutz.",
    sec_cta_playground_btn: "⚡ Live-Playground testen",
    sec_cta_register_btn: "🚀 API-Key erstellen"
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
  
  if (earnEl) {
    const period = currentLang === 'de' ? '/ Monat' : '/ month';
    earnEl.innerHTML = `$${estEarnings} <span style="font-size: 1rem; color: var(--text-muted); font-weight: 500;">${period} (${(earnedCredits / 1000000).toFixed(2)}M Credits)</span>`;
  }
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

let currentPlaygroundTab = 'curl_bash';

function renderPlaygroundSnippet() {
  const apiKey = localStorage.getItem('cm_api_key') || 'cm_live_your_key';
  const ollamaCode = document.getElementById('pg-ollama-code-content');
  if (!ollamaCode) return;

  if (currentPlaygroundTab === 'curl_bash') {
    ollamaCode.textContent = `# Linux / macOS (cURL / Bash)
export OLLAMA_HOST=https://mesh.inetconnector.com
curl https://mesh.inetconnector.com/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${apiKey}" \\
  -d '{"model":"qwen2.5:7b","messages":[{"role":"user","content":"What is ComputeMesh?"}],"stream":true}'`;
  } else if (currentPlaygroundTab === 'curl_win') {
    ollamaCode.textContent = `REM Windows Eingabeaufforderung (CMD - Einzeiler)
curl -X POST "https://mesh.inetconnector.com/v1/chat/completions" -H "Content-Type: application/json" -H "Authorization: Bearer ${apiKey}" -d "{\\"model\\":\\"qwen2.5:7b\\",\\"messages\\":[{\\"role\\":\\"user\\",\\"content\\":\\"What is ComputeMesh?\\"}],\\"stream\\":false}"`;
  } else if (currentPlaygroundTab === 'powershell') {
    ollamaCode.textContent = `# Windows PowerShell (Native REST-Abfrage)
$headers = @{ "Content-Type" = "application/json"; "Authorization" = "Bearer ${apiKey}" }
$body = @{ model = "qwen2.5:7b"; messages = @(@{ role = "user"; content = "What is ComputeMesh?" }); stream = $false } | ConvertTo-Json
Invoke-RestMethod -Uri "https://mesh.inetconnector.com/v1/chat/completions" -Method Post -Headers $headers -Body $body`;
  } else if (currentPlaygroundTab === 'python') {
    ollamaCode.textContent = `# Python 3 (OpenAI SDK oder urllib mit SSE Streaming)
import urllib.request, json

req = urllib.request.Request(
    "https://mesh.inetconnector.com/v1/chat/completions",
    data=json.dumps({"model": "qwen2.5:7b", "messages": [{"role": "user", "content": "What is ComputeMesh?"}], "stream": True}).encode("utf-8"),
    headers={"Content-Type": "application/json", "Authorization": "Bearer ${apiKey}"}
)
with urllib.request.urlopen(req) as resp:
    for line in resp:
        txt = line.decode("utf-8").strip()
        if txt.startswith("data: ") and not txt.endswith("[DONE]"):
            print(json.loads(txt[6:])["choices"][0]["delta"].get("content", ""), end="", flush=True)
print()`;
  } else if (currentPlaygroundTab === 'ollama') {
    ollamaCode.textContent = `# Offizielle Ollama CLI (Linux/macOS: export, Windows CMD: set, PowerShell: $env:OLLAMA_HOST)
export OLLAMA_HOST=https://mesh.inetconnector.com
ollama run qwen2.5:7b "What is ComputeMesh?"`;
  }
}
window.renderPlaygroundSnippet = renderPlaygroundSnippet;

function switchPlaygroundCodeTab(tab) {
  currentPlaygroundTab = tab;
  document.querySelectorAll('.pg-tab-btn').forEach(b => b.classList.remove('active'));
  const activeBtn = document.getElementById(`tab-btn-${tab.replace('_', '-')}`);
  if (activeBtn) activeBtn.classList.add('active');
  renderPlaygroundSnippet();
}
window.switchPlaygroundCodeTab = switchPlaygroundCodeTab;

function updateCodeSnippetsWithKey(apiKey) {
  if (!apiKey || apiKey.startsWith('Bitte') || apiKey.startsWith('Please') || apiKey.startsWith('Reg')) return;
  try {
    localStorage.setItem('cm_api_key', apiKey);
  } catch (e) {}

  renderPlaygroundSnippet();

  const pythonCode = document.getElementById('python-sdk-code-content');
  if (pythonCode) {
    pythonCode.textContent = `from openai import OpenAI

# 100% drop-in replacement for OpenAI SDK
client = OpenAI(
    base_url="https://mesh.inetconnector.com/v1",
    api_key="${apiKey}"
)

response = client.chat.completions.create(
    model="qwen2.5:7b",
    messages=[{"role": "user", "content": "Explain decentralized AI in 3 sentences."}],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")`;
  }
}
window.updateCodeSnippetsWithKey = updateCodeSnippetsWithKey;

function copyKey() {
  const keyInput = document.getElementById('generated-key-val');
  const copyBtn = document.querySelector('button[onclick="copyKey()"]');
  if (keyInput && keyInput.value) {
    const key = keyInput.value;
    navigator.clipboard.writeText(key).catch(() => {});
    updateCodeSnippetsWithKey(key);
    if (copyBtn) {
      const orig = copyBtn.textContent;
      copyBtn.textContent = (window.currentLang === 'de' ? '✓ Kopiert!' : '✓ Copied!');
      copyBtn.style.borderColor = 'var(--accent-emerald)';
      copyBtn.style.color = 'var(--accent-emerald)';
      setTimeout(() => {
        copyBtn.textContent = orig;
        copyBtn.style.borderColor = '';
        copyBtn.style.color = '';
      }, 2000);
    }
  }
}
window.copyKey = copyKey;

function copyPlaygroundCommand() {
  const codeEl = document.getElementById('pg-ollama-code-content');
  const btn = document.getElementById('copy-playground-cmd-btn');
  if (!codeEl) return;
  const text = codeEl.textContent || codeEl.innerText;
  navigator.clipboard.writeText(text).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  });
  if (btn) {
    const orig = btn.textContent;
    btn.textContent = (window.currentLang === 'de' ? '✓ Befehl kopiert!' : '✓ Command copied!');
    btn.style.color = 'var(--accent-emerald)';
    btn.style.borderColor = 'var(--accent-emerald)';
    setTimeout(() => {
      btn.textContent = orig;
      btn.style.color = '';
      btn.style.borderColor = '';
    }, 2000);
  }
}
window.copyPlaygroundCommand = copyPlaygroundCommand;

function copyPythonCode() {
  const codeEl = document.getElementById('python-sdk-code-content');
  const btn = document.getElementById('copy-python-code-btn');
  if (!codeEl) return;
  const text = codeEl.textContent || codeEl.innerText;
  navigator.clipboard.writeText(text).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  });
  if (btn) {
    const orig = btn.textContent;
    btn.textContent = (window.currentLang === 'de' ? '✓ Code kopiert!' : '✓ Code copied!');
    btn.style.color = 'var(--accent-emerald)';
    btn.style.borderColor = 'var(--accent-emerald)';
    setTimeout(() => {
      btn.textContent = orig;
      btn.style.color = '';
      btn.style.borderColor = '';
    }, 2000);
  }
}
window.copyPythonCode = copyPythonCode;

function copyLinuxCommand() {
  const cmd = "curl -fsSL https://mesh.inetconnector.com/downloads/install.sh | sudo bash";
  navigator.clipboard.writeText(cmd);
  const btn = document.querySelector('button[onclick="copyLinuxCommand()"]');
  if (btn) {
    const orig = btn.textContent;
    btn.textContent = (window.currentLang === 'de' ? '✓ Kopiert!' : '✓ Copied!');
    setTimeout(() => { btn.textContent = orig; }, 2000);
  }
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

const QUICK_PROMPTS = {
  de: {
    explain_mesh: "Was macht ComputeMesh einzigartig und wie funktioniert die dezentrale GPU-Inferenz?",
    python_fastapi: "Schreibe einen performanten Python-FastAPI-Endpunkt, der Requests an das OpenAI-kompatible /v1/chat/completions Gateway mit Streaming weiterleitet.",
    gpu_sharding: "Erkläre wie Pipeline-Layer-Sharding große KI-Modelle effizient über mehrere GPUs aufteilt.",
    compare_costs: "Wie viel Geld kann ich mit ComputeMesh im Vergleich zu AWS oder Azure sparen?"
  },
  en: {
    explain_mesh: "What makes ComputeMesh unique and how does decentralized GPU inference work?",
    python_fastapi: "Write a high-performance Python FastAPI streaming endpoint using the OpenAI-compatible /v1/chat/completions gateway.",
    gpu_sharding: "Explain how pipeline layer sharding efficiently distributes large AI models across multiple GPUs.",
    compare_costs: "How much money can I save with ComputeMesh compared to AWS or Azure?"
  }
};

function applyQuickPrompt(promptKey) {
  const lang = (window.currentLang === 'de' || localStorage.getItem('cm_portal_lang') === 'de' || (!localStorage.getItem('cm_portal_lang') && (navigator.language || '').startsWith('de'))) ? 'de' : 'en';
  const prompt = (window.QUICK_PROMPTS && window.QUICK_PROMPTS[lang] && window.QUICK_PROMPTS[lang][promptKey])
    || (window.QUICK_PROMPTS && window.QUICK_PROMPTS.en && window.QUICK_PROMPTS.en[promptKey])
    || '';
  const inputEl = document.getElementById('playground-prompt-input');
  if (prompt && inputEl) {
    inputEl.value = prompt;
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(Math.max(inputEl.scrollHeight, 60), 140) + 'px';
    inputEl.focus();
    inputEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}
window.applyQuickPrompt = applyQuickPrompt;
window.QUICK_PROMPTS = QUICK_PROMPTS;

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
        'X-ComputeMesh-Client': 'web-playground-v1.2.27'
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

  if (data.global_mesh && typeof data.global_mesh === 'object') {
    const gm = data.global_mesh;
    return {
      source: gm.source || data.source || 'authenticated_registry',
      totalVramGb: Number(gm.total_vram_gb !== undefined ? gm.total_vram_gb : 0),
      activeGpus: Number(gm.total_gpus_active !== undefined ? gm.total_gpus_active : (gm.active_gpus !== undefined ? gm.active_gpus : 0)),
      totalNodes: Number(gm.total_nodes_online !== undefined ? gm.total_nodes_online : (gm.total_nodes !== undefined ? gm.total_nodes : 0)),
      totalTflops: Number(gm.total_compute_tflops !== undefined ? gm.total_compute_tflops : (gm.total_tflops !== undefined ? gm.total_tflops : 0))
    };
  }

  return {
    source: data.source || 'authenticated_cluster',
    totalVramGb: Number(data.total_vram_gb !== undefined ? data.total_vram_gb : 0),
    activeGpus: Number(data.active_gpus !== undefined ? data.active_gpus : (data.total_gpus_active !== undefined ? data.total_gpus_active : 0)),
    totalNodes: Number(data.total_nodes !== undefined ? data.total_nodes : (data.total_nodes_online !== undefined ? data.total_nodes_online : 0)),
    totalTflops: Number(data.total_tflops !== undefined ? data.total_tflops : (data.total_compute_tflops !== undefined ? data.total_compute_tflops : 0))
  };
}

function updateMeshTelemetryTicker(stats) {
  if (!stats) return;

  const vramEl = document.getElementById('portal-ticker-vram');
  const gpusEl = document.getElementById('portal-ticker-gpus');
  const tflopsEl = document.getElementById('portal-ticker-tflops');
  const nodesEl = document.getElementById('portal-ticker-nodes');

  const locale = (window.currentLang === 'de' || localStorage.getItem('cm_portal_lang') === 'de') ? 'de-DE' : 'en-US';
  const isDe = (window.currentLang === 'de' || localStorage.getItem('cm_portal_lang') === 'de' || (!localStorage.getItem('cm_portal_lang') && (navigator.language || '').startsWith('de')));

  const vramVal = typeof stats.totalVramGb === 'number' ? stats.totalVramGb : 0;
  const gpusVal = typeof stats.activeGpus === 'number' ? stats.activeGpus : 0;
  const tflopsVal = typeof stats.totalTflops === 'number' ? stats.totalTflops : 0;
  const nodesVal = typeof stats.totalNodes === 'number' ? stats.totalNodes : 0;

  const gpuWord = gpusVal === 1 ? 'GPU' : 'GPUs';
  const nodeWord = nodesVal === 1 ? 'Node' : 'Nodes';
  const activeWord = isDe ? 'aktiv' : 'active';
  const onlineWord = isDe ? 'online' : 'online';

  if (vramEl) {
    vramEl.textContent = `${vramVal.toLocaleString(locale, { maximumFractionDigits: 1, minimumFractionDigits: 1 })} GB`;
  }
  if (gpusEl) {
    gpusEl.textContent = `${gpusVal} ${gpuWord} ${onlineWord}`;
  }
  if (tflopsEl) {
    tflopsEl.textContent = `${tflopsVal.toLocaleString(locale, { maximumFractionDigits: 1, minimumFractionDigits: 1 })} TFLOPS`;
  }
  if (nodesEl) {
    nodesEl.textContent = `${nodesVal} ${nodeWord} ${activeWord}`;
  }
}

async function fetchMeshTelemetry() {
  const endpoints = ['/api/v1/mesh/stats', '/mesh/stats', '/api/status'];
  for (const endpoint of endpoints) {
    try {
      const res = await fetch(endpoint, { cache: 'no-store' });
      if (!res.ok) continue;
      const json = await res.json();
      const stats = parseMeshTelemetryPayload(json);
      if (stats) {
        updateMeshTelemetryTicker(stats);
        return;
      }
    } catch (e) {
      // try next endpoint
    }
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

  try {
    const savedKey = localStorage.getItem('cm_api_key');
    if (savedKey) updateCodeSnippetsWithKey(savedKey);
    else renderPlaygroundSnippet();
  } catch (e) {
    renderPlaygroundSnippet();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initPortal);
} else {
  initPortal();
}

window.initPortal = initPortal;
