# ComputeMesh Free Teaser Playground & Ollama / OpenAI Integration Guide

## 1. Übersicht & Zielsetzung

ComputeMesh bietet einen sofortigen, reibungsfreien Einstieg („Zero-Friction Teaser“) für Entwickler und KI-Nutzer:
- **Keine Registrierung oder API-Key nötig:** Nutzer können Modelle direkt via Standard Ollama CLI oder OpenAI Python SDK anfragen.
- **Konfigurierbare Test-Quota:** Standardmäßig **20 kostenlose Anfragen** (konfigurierbar über `COMPUTEMESH_TEASER_MAX_REQUESTS` in der Konfiguration).
- **Graceful Paywall & Onboarding:** Nach Aufbrauchen der 20 kostenlosen Anfragen wird eine strukturierte Anleitung zurückgegeben, wie man entweder einen Consumer API-Key erwirbt oder seinen eigenen Server/GPU als Provider einhängt.
- **Provider-Vorteil (0% Plattformgebühr):** Wenn Nutzer eigene Hardware im Mesh betreiben, nutzen sie das Cluster für eigene Anfragen ohne Plattform-Aufschlag (reiner Selbstkostenpreis / Provider Self-Compute).

---

## 2. Architektur & Modularer Aufbau (`services/gateway/`)

Das Gateway ist in schlanke, spezialisierte Module unterteilt:

```
services/gateway/
├── catalog.py            # Model-Katalog, Kontext-Fenster, Pricing-Tiers & Provider-Anteile
├── teaser.py             # TeaserQuotaManager, TeaserSession, Paywall-Konstruktor
├── dashboard.py          # Node-Telemetrie-Registry & HTML-Remote-Dashboard-Renderer
├── inference.py          # InferenceEngine, Token-Schätzung, OpenAI SSE & Ollama ndjson Streaming
├── metrics_exporter.py   # Prometheus-Metriken Registry & Exporter
└── server.py             # Schlanker GatewayHandler, HTTP-Routing, Auth-Tiers & Lifecycle
```

---

## 3. Zentrale Konfiguration (`config.py` & `TeaserConfig`)

Die Teaser-Limits sind zentral in `TeaserConfig` definiert und über Umgebungsvariablen steuerbar:

```python
@dataclass
class TeaserConfig:
    enabled: bool = True
    max_free_requests: int = int(os.environ.get("COMPUTEMESH_TEASER_MAX_REQUESTS", "20"))
    max_free_tokens: int = int(os.environ.get("COMPUTEMESH_TEASER_MAX_TOKENS", "8192"))
    initial_grant_micro_units: int = int(os.environ.get("COMPUTEMESH_TEASER_INITIAL_GRANT", "20000000"))
```

---

## 4. Nutzung via Ollama CLI (Teaser Playground)

### 4.1. Verbindung konfigurieren
```bash
# Gateway-Host setzen (keine Registrierung erforderlich)
export OLLAMA_HOST="computemesh.inetconnector.com:443"

# Verfügbare Modelle auflisten
ollama list
```

### 4.2. Modell testen
```bash
ollama run qwen2.5-7b-instruct "Erkläre mir die Vorteile von verteiltem Rechnen."
```

Jede Antwort enthält einen Teaser-Banner mit den verbleibenden freien Anfragen:
`⚡ ComputeMesh Free Teaser: Noch 19/20 Anfragen übrig | 🟢 Cluster-Verbund: 24.0 GB VRAM | computemesh.inetconnector.com`

---

## 5. Nutzung via OpenAI SDK (Python)

```python
from openai import OpenAI

# Unauthentifizierter Teaser-Client (20 kostenlose Anfragen)
client = OpenAI(
    base_url="https://computemesh.inetconnector.com/v1",
    api_key="teaser-free",  # Beliebiger String
)

response = client.chat.completions.create(
    model="qwen/qwen2.5-7b-instruct",
    messages=[{"role": "user", "content": "Hallo ComputeMesh Cluster!"}],
)

print(response.choices[0].message.content)
```

---

## 6. Provider Self-Compute (0% Plattform-Aufschlag)

Für Hardware-Provider, die eigene Rigs im Mesh betreiben:
1. Registrierung des Rigs via One-Line-Installer:
   ```bash
   curl -sSL https://computemesh.inetconnector.com/install.sh | bash
   ```
2. Lokaler Node generiert einen Provider-Token: `cm_provider_<node_id>`.
3. Bei Anfragen mit `Authorization: Bearer cm_provider_<node_id>` entfällt der 25%-Plattformaufschlag (`fee_bps = 0`), sodass Provider eigene Lasten zum reinen Selbstkostenpreis über das Netzwerk abrechnen.

---

## 7. Paywall & Conversion-Mechanik

Sobald das Kontingent von 20 Anfragen aufgebraucht ist, liefert das Gateway automatisch die strukturierte Conversion-Nachricht aus:

```markdown
🚀 **ComputeMesh Free Teaser-Limit erreicht (20 kostenlose Test-Anfragen)!**

Du hast den dezentralen ComputeMesh-Cluster erfolgreich im Free-Playground getestet.
Um das globale Mesh unbegrenzt und mit voller GPU-Beschleunigung zu nutzen, wähle eine der folgenden Optionen:

1. 🔑 Eigenen API-Key erstellen (Consumer):
   * Registriere dich unter https://computemesh.inetconnector.com und hole dir deinen persönlichen API-Key.
   * Binde den Key in Ollama oder OpenAI SDK ein.

2. 💰 Eigene GPU/Server als Provider connecten (Geld verdienen):
   * Verbinde dein Linux-/Windows-Rig mit einem einzigen Befehl:
     `curl -sSL https://computemesh.inetconnector.com/install.sh | bash`
   * Verdiene bis zu 75% aller Inferenz-Umsätze auf deiner Hardware!
   * Auszahlungen erfolgen automatisiert via Stripe Connect aufs Bankkonto oder in Krypto.

3. ⚡ Eigener Server = 0% Plattform-Aufschlag (Provider-Rabatt):
   Wenn du deinen eigenen Server im Mesh betreibst, rechnest du eigene Anfragen ohne Plattformgebühr zum reinen Selbstkostenpreis direkt über deine eigene Hardware ab!
```
