# 💰 ComputeMesh Network Operator Monetization & Fee Architecture
## Leitfaden zur Betreiber-Vergütung (20% – 30% Plattform-Marge)

---

### 🇩🇪 Deutsch: Wo & wie verdient der Netzwerk-Betreiber seine 20% – 30%?

Als Betreiber des dezentralen **ComputeMesh**-Netzwerks verdienst du an jeder einzelnen KI-Inferenzanfrage, die über dein Netzwerk geroutet und von den Miner- und Provider-Nodes berechnet wird.

#### 1. Wo ist das im Code geregelt?
Die Abrechnung und Aufteilung erfolgt im mathematisch strikten Double-Entry Ledger (Doppelte Buchführung mit Micro-Unit-Präzision) in:
* 📄 **[`services/billing/ledger.py`](file:///c:/Users/frede/Projekte/ComputeMesh/services/billing/ledger.py)**
  * **Zeile 20:** `DEFAULT_NETWORK_FEE_BPS = 2500` (2500 Basis-Punkte = **25.00% Plattform-Gebühr**)
  * **Zeilen 185–205 (`record_job_execution`):** Bei jedem abgeschlossenen Inferenz-Job wird der Gesamtbetrag automatisch gesplittet:
    $$\text{Network Fee (Betreiber)} = \frac{\text{Total Charge} \times \text{network\_fee\_bps}}{10000}$$
    $$\text{Provider Pool (Miner)} = \text{Total Charge} - \text{Network Fee}$$
  * **Konto `revenue:network_fee`:** Die Betreiber-Gebühr wird unveränderlich auf das Ertragskonto `revenue:network_fee` gutgeschrieben.

#### 2. Welche Einstellungen & Keys steuern deine Betreiber-Marge?
Du kannst die prozentuale Marge und deine Auszahlungsadresse flexibel über Umgebungsvariablen oder Konfigurationsdateien steuern:

| Konfigurations-Key / Env-Variable | Standardwert | Bedeutung |
| :--- | :--- | :--- |
| `COMPUTEMESH_OPERATOR_FEE_BPS` | `2500` (25%) | Betreiber-Marge in Basis-Punkten (`2000` = 20%, `2500` = 25%, `3000` = 30%). |
| `COMPUTEMESH_OPERATOR_TREASURY_WALLET` | `0x...` | Deine persönliche Ethereum / Polygon Wallet-Adresse für automatische USDT/ETH-Auszahlungen. |
| `MINIMUM_PAYOUT_MICRO_UNITS` | `25_000_000` ($25.00) | Mindestbetrag für automatisierte Settlement-Überweisungen. |

#### 3. Wie kommst du an dein Geld (Auszahlung)?
1. **Automatische Ansammlung:** Bei jedem API-Aufruf (z. B. via OpenAI-kompatiblen Endpoint `/v1/chat/completions`) zahlen Entwickler/Kunden z. B. $0.20 pro 1M Tokens. Davon fließen **$0.05 (25%)** direkt in deinen Betreiber-Pool und **$0.15 (75%)** an die GPUs.
2. **Auszahlung auslösen:** Über die Funktion `ledger.create_operator_treasury_payout(wallet_address)` wird das Guthaben von `revenue:network_fee` auf deine Ziel-Wallet übertragen.
3. **Audit & Sicherheit:** Die Methode `ledger.reconcile()` prüft jederzeit cent-genau die mathematische Bilanzgleichheit ($\sum \text{Debits} == \sum \text{Credits}$).

---

### 🇬🇧 English: Network Operator Fee & Revenue Settlement Guide

#### 1. Code Implementation & Split Logic
All financial splits are executed with micro-unit precision ($1.00 = 1,000,000$ micro-units) in:
* 📄 **[`services/billing/ledger.py`](file:///c:/Users/frede/Projekte/ComputeMesh/services/billing/ledger.py)**
  * **Line 20:** `DEFAULT_NETWORK_FEE_BPS = 2500` ($25.00\%$ platform coordination fee).
  * **Lines 185–205 (`record_job_execution`):** Automated per-job revenue splitting:
    $$\text{Operator Cut} = \frac{\text{Customer Payment} \times \text{network\_fee\_bps}}{10000}$$
  * **Account `revenue:network_fee`:** Credits are accumulated in the operator's revenue account.

#### 2. Configuration Keys
* `COMPUTEMESH_OPERATOR_FEE_BPS`: Set to `2000` (20%), `2500` (25%), or `3000` (30%).
* `COMPUTEMESH_OPERATOR_TREASURY_WALLET`: The operator's EVM wallet address (`0x...`) receiving treasury payouts.

#### 3. Treasury Payout
* Call `ledger.create_operator_treasury_payout()` to execute an auditable transfer to your treasury wallet.
