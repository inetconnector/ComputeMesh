# ComputeMesh Sicherheits-, Verschlüsselungs- und DSGVO-Architektur

**Version:** 2.2 · **Klassifizierung:** Technisches Sicherheits-Whitepaper & Compliance-Dokumentation  
**Betreiber / Control Plane:** Herbert Daniel Frede · InetConnector.com  
**Anwendbare Standards:** EU-DSGVO (Art. 5, 25, 28, 32) · TLS 1.3 (RFC 8446) · ISO/IEC 27001 Controls · BSI IT-Grundschutz

---

## 1. Management-Zusammenfassung & Kernprinzipien

ComputeMesh basiert auf dem Grundsatz des **flüchtigen Zero-Knowledge-Streamings (Privacy-by-Design nach Art. 25 DSGVO)**. Die Architektur garantiert mathematisch und technisch:

1. **Vollständige Abhörsicherheit (Eavesdropping Immunity):** Jegliche Kommunikation über das öffentliche Internet sowie zwischen den Rechenknoten ist durch **TLS 1.3 mit Perfect Forward Secrecy (PFS)** und gegenseitiger Zertifikatsvalidierung (**mTLS**) verschlüsselt. Niemand im Internet kann Anfragen oder KI-Antworten mitlesen.
2. **Zero-Disk-Logging (Keine Speicherung von Prompts auf Festplatten):** Prompts, Chats und generierte Antworten werden **ausschließlich im flüchtigen Arbeitsspeicher (RAM)** verarbeitet. Es findet keinerlei Protokollierung von Inferenz-Inhalten in Server-Logs, Dateisystemen oder Datenbanken statt.
3. **Kein Modell-Training mit Kundendaten:** Eingegebene Prompts und Antworten werden unter keinen Umständen für das Training oder Feintuning von KI-Modellen verwendet.
4. **Strikte Datenminimierung (Art. 5 Abs. 1 lit. c DSGVO):** Es gibt keine Werbe-Tracker, keine Cookies von Drittanbietern und keine dauerhafte Speicherung personenbezogener Anfragedaten.

---

## 2. Schutzschicht 1: Transportverschlüsselung & Netzwerksicherheit

### 2.1 TLS 1.3 mit Perfect Forward Secrecy (PFS)
- **Schlüsselaustausch:** ECDHE über elliptische Kurven (X25519 / secp256r1).
- **Verschlüsselung:** Authenticated Encryption via AES-256-GCM und ChaCha20-Poly1305.
- **PFS-Garantie:** Jede Inferenz-Session erzeugt temporäre Einmalschlüssel. Selbst wenn ein Angreifer verschlüsselten Datenverkehr mitschneidet, kann er diesen niemals entschlüsseln.

### 2.2 Gehärtete Sicherheits-Header am Edge Proxy (Nginx)
```nginx
# 2 Jahre erzwungenes HTTPS inkl. Preload
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

# Schutz vor MIME-Sniffing & Clickjacking
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), interest-cohort=()" always;
```

### 2.3 Speicherpufferung ohne Festplatten-Zwischenspeicherung
Durch die Nginx-Direktive `proxy_max_temp_file_size 0;` wird verhindert, dass der Reverse-Proxy Anfragedaten auf die Festplatte (`/var/cache/nginx`) auslagert. Alle Tokens fließen direkt über RAM-Netzwerkpuffer.

---

## 3. Schutzschicht 2: Flüchtige RAM-Verarbeitung & Null-Protokollierung

### 3.1 Eliminierung von Prompt-Logs
Im Gateway-Server (`services/gateway/server.py`) ist das Protokollieren von Request-Bodies explizit überschrieben und deaktiviert:

```python
class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        """Verhindert jegliche Protokollierung von Prompts oder Parametern im Server-Log."""
        pass
```

### 3.2 Sofortige Speicherbereinigung
Sobald das finale Streaming-Signal (`data: [DONE]`) an den Client gesendet wurde:
- Werden alle Speicherreferenzen auf die Prompt-Nachrichten im Python-Runtime gelöscht.
- Die Garbage Collection gibt den belegten RAM-Speicher sofort frei.
- Die Datenbank speichert **ausschließlich Abrechnungs-Metadaten** (z. B. `Account-ID`, `Timestamp`, `Prompt-Tokens: 45`, `Completion-Tokens: 128`), niemals den Text.

---

## 4. Schutzschicht 3: Internes Mesh-Netzwerk & Confidential Computing

### 4.1 Gegenseitige TLS-Authentifizierung (mTLS) mit Ed25519
Die Kommunikation zwischen Orchestrator und Rechenknoten (GPUs) ist über **mTLS** abgesichert. Jeder Knoten besitzt ein individuelles kryptografisches Schlüsselpaar. Unberechtigte Dritte oder gefälschte Server können dem Cluster nicht beitreten oder Daten abfangen.

### 4.2 Fail-Closed Privacy-Klassen
In `services/compliance/mesh_policy.py` sind Vertrauensstufen und Datenschutzklassen definiert:
- `PUBLIC`: Standard-Inferenz auf geprüften GPU-Knoten.
- `CONFIDENTIAL`: Erfordert Hardware-Attestierung (AMD SEV-SNP / Intel TDX) und garantierte Protokollfreiheit.
- `CRYPTO_PRIVATE`: Vollständig verschlüsselte Tensor-Berechnung.

> **Sicherheitsgarantie:** Ein vertraulicher Job wird niemals heimlich auf einen ungesicherten Knoten umgeleitet. Ist kein passender Knoten frei, bricht die Anfrage deterministisch mit einem Sicherheitsfehler ab.

---

## 5. Schutzschicht 4: Server-Härtung & Vault-Verschlüsselung

### 5.1 Linux-Systemd-Sandboxing (Debian 13)
Der Dienst `computemesh-gateway.service` läuft unter strengen Sandboxing-Restriktionen:
- `ProtectSystem=strict`: Das Betriebssystem (`/usr`, `/etc`, `/boot`) ist für den Dienst schreibgeschützt.
- `ProtectHome=true`: Kein Zugriff auf private Benutzerverzeichnisse.
- `PrivateTmp=true`: Isolierter `/tmp`-Namensraum (kein Auslesen fremder temporärer Dateien möglich).
- `NoNewPrivileges=true`: Verhindert Rechteausweitung (Privilege Escalation).

### 5.2 Vault-Sicherheit & Zahlungsentkopplung
- Sensible Plattform-Schlüssel sind im Vault mit **AES-256-GCM** verschlüsselt.
- Kreditkartendaten und Zahlungsabwicklungen sind zu **100 % an Stripe (PCI-DSS Level 1 zertifiziert)** ausgelagert. ComputeMesh speichert niemals Zahlungskarten.

---

## 6. DSGVO-Konformitätsmatrix (EU-Recht)

| DSGVO-Artikel | Gesetzliche Anforderung | Technische Umsetzung bei ComputeMesh |
| :--- | :--- | :--- |
| **Art. 5 Abs. 1 lit. a** | Rechtmäßigkeit & Transparenz | Klare AGB (`/terms`) und DSGVO-Datenschutzerklärung (`/privacy`). |
| **Art. 5 Abs. 1 lit. b** | Zweckbindung | Inferenzdaten dienen ausschließlich der Erzeugung der Antwort. Keine Weitergabe oder Profilbildung. |
| **Art. 5 Abs. 1 lit. c** | Datenminimierung | Keine Tracking-Cookies, keine Werbepixel. Reine RAM-Verarbeitung. |
| **Art. 5 Abs. 1 lit. e** | Speicherbegrenzung | Zero-Disk-Retention: Prompts existieren nur für Millisekunden im RAM während der Inferenz. |
| **Art. 5 Abs. 1 lit. f** | Integrität & Vertraulichkeit | TLS 1.3 mit PFS, mTLS-Knotenbindung, AES-256-GCM Vault, Systemd-Sandbox. |
| **Art. 25** | Privacy by Design | Technische Trennung von Abrechnungszählern und Inhalten; Fail-Closed-Sicherheitslogik. |
| **Art. 28** | Auftragsverarbeitung (AVV / DPA) | Vollständige AVV-Grundlage für gewerbliche B2B-Kunden verfügbar. |
| **Art. 32** | Sicherheit der Verarbeitung (TOMs) | Mehrstufige technische und organisatorische Maßnahmen nach Stand der Technik. |

---

## 7. Fazit für Betreiber & Geschäftskunden

Durch die Kombination aus **TLS 1.3 mit Perfect Forward Secrecy**, **strenger flüchtiger RAM-Verarbeitung (Zero-Disk-Logging)**, **mTLS-Clusterbindung** und **Linux-Kernel-Sandboxing** ist sichergestellt:

- Ein Mitlesen oder Abhören über das Internet ist **mathematisch ausgeschlossen**.
- Auf dem Server verbleiben **keine gespeicherten Prompts oder Chatverläufe**.
- Die gesamte Plattform erfüllt alle Anforderungen der **EU-DSGVO (Art. 5, 25, 28, 32)** und ist revisionssicher aufgestellt.
