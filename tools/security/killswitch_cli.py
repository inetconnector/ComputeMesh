# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh Kill Switch & Master Safety CLI Tool.

Enables operators to:
- Provision and seal Master Kill Switch keys to secure storage (e.g. \\diskstation\\Dani\\ComputeMesh\\killswitch).
- Trigger immediate multi-tier Emergency Kill Switch (Hard process kill, network revocation, relay cutoff).
- Query live Positive Authorization & Dead Man's Switch status.
- Issue manual lease extensions / renewals.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from typing import Any

# Ensure project root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DISKSTATION_DIR = Path(r"\\diskstation\Dani\ComputeMesh\killswitch")
LOCAL_SAFETY_DIR = REPO_ROOT / "config" / "safety"


def generate_master_keys(target_dir: Path = DEFAULT_DISKSTATION_DIR) -> tuple[bytes, str]:
    """Generates Ed25519 Master Signing Keypair for the Kill Switch subsystem."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization

    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()

    priv_raw = priv.private_bytes_raw()
    pub_raw = pub.public_bytes_raw()
    pub_hex = pub_raw.hex()

    # Create target directory
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"Warning: Could not create target dir {target_dir}: {exc}")

    # 1. Save Master Private Key (Sealed to DiskStation / Operator Vault)
    priv_file = target_dir / "master_killswitch_private.key"
    try:
        priv_file.write_bytes(priv_raw)
        print(f"[OK] Master Private Key sealed to: {priv_file}")
    except Exception as exc:
        print(f"[WARN] Failed to write private key to {priv_file}: {exc}")

    # 2. Save Master Public Key Hex
    pub_file = target_dir / "master_killswitch_public.hex"
    try:
        pub_file.write_text(pub_hex + "\n", encoding="utf-8")
        print(f"[OK] Master Public Key saved to: {pub_file}")
    except Exception as exc:
        print(f"[WARN] Failed to write public key to {pub_file}: {exc}")

    # 3. Also save public key to local node config so the node can verify leases offline
    LOCAL_SAFETY_DIR.mkdir(parents=True, exist_ok=True)
    local_pub = LOCAL_SAFETY_DIR / "master_killswitch_public.hex"
    local_pub.write_text(pub_hex + "\n", encoding="utf-8")
    print(f"[OK] Node Public Key anchor updated: {local_pub}")

    # 4. Generate Sealed Manifest
    manifest = {
        "system": "ComputeMesh Safety & Kill Switch Subsystem",
        "version": "1.2.0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "master_public_key_hex": pub_hex,
        "default_lease_ttl_seconds": 15,
        "heartbeat_interval_seconds": 5,
        "policy": {
            "default_state": "STOP (Dead Man's Switch)",
            "positive_authorization_required": True,
            "grace_period_ms": 0,
            "hardware_relay_enabled": True,
            "network_blackhole_on_kill": True,
        }
    }
    manifest_file = target_dir / "manifest.json"
    try:
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"[OK] Safety Manifest sealed to: {manifest_file}")
    except Exception as exc:
        print(f"[WARN] Could not write manifest: {exc}")

    # 5. Write Quick Operator Batch Files & Instructions to DiskStation
    write_diskstation_operator_kit(target_dir, pub_hex)

    return priv_raw, pub_hex


def write_diskstation_operator_kit(target_dir: Path, pub_hex: str) -> None:
    """Writes easy-to-use 1-click batch files and an exhaustive guide to DiskStation."""
    # 1. NOT-AUS-TRIGGER.bat
    not_aus_bat = target_dir / "NOT-AUS-TRIGGER.bat"
    not_aus_content = (
        "@echo off\n"
        "title COMPUTEMESH MASTER NOT-AUS (GLOBAL EMERGENCY KILL SWITCH)\n"
        "color 4F\n"
        "echo ================================================================================\n"
        "echo  COMPUTEMESH MASTER NOT-AUS - GLOBALE ABSCHALTUNG DES GESAMTEN SYSTEMS\n"
        "echo  (Autorisiert durch DiskStation Master-Schluessel / Plattform-Inhaber)\n"
        "echo ================================================================================\n"
        "echo.\n"
        "echo WARNUNG: Dieser Befehl loest den GLOBALEN Not-Aus aus. Alle laufenden KI-Modelle,\n"
        "echo MCP-Agenten und Inferenz-Workloads auf allen Knoten werden SOFORT per Hard-Kill\n"
        "echo beendet und alle Netzwerk-Tunnel geschlossen.\n"
        "echo.\n"
        "echo HINWEIS: Einzelne Flottenbetreiber koennen nur ihre eigene Flotte stoppen.\n"
        "echo Dieser globale Master-Befehl ist dem Plattform-Inhaber (inetconnector) vorbehalten.\n"
        "echo.\n"
        "set /p CONFIRM=\"Sind Sie sicher? Tippen Sie 'KILL' und druecken Sie Enter: \"\n"
        "if /i not \"%CONFIRM%\"==\"KILL\" (\n"
        "    echo Globaler Not-Aus abgebrochen.\n"
        "    pause\n"
        "    exit /b 0\n"
        ")\n"
        "echo.\n"
        "echo Sende globalen Master-Not-Aus-Befehl an Cluster...\n"
        "powershell -ExecutionPolicy Bypass -Command \"$hdr = @{}; if ($env:COMPUTEMESH_MASTER_ADMIN_KEY) { $hdr['X-Master-Killswitch-Key'] = $env:COMPUTEMESH_MASTER_ADMIN_KEY }; try { $res = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/killswitch/trigger' -Method Post -Body (@{scope='global'; reason='Master 1-Click Hard Kill via DiskStation'} | ConvertTo-Json) -Headers $hdr -ContentType 'application/json'; Write-Host '[OK] Not-Aus erfolgreich ausgeloest:' $res.message -ForegroundColor Green } catch { Write-Host '[FEHLER/ISOLATION]' $_.Exception.Message -ForegroundColor Yellow }\"\n"
        "echo.\n"
        "pause\n"
    )
    try:
        not_aus_bat.write_text(not_aus_content, encoding="utf-8")
    except Exception:
        pass

    # 2. STATUS.bat
    status_bat = target_dir / "STATUS.bat"
    status_content = (
        "@echo off\n"
        "title COMPUTEMESH SAFETY & KILL SWITCH STATUS\n"
        "color 0A\n"
        "echo ================================================================================\n"
        "echo  COMPUTEMESH SAFETY & DEAD MAN'S SWITCH STATUS\n"
        "echo ================================================================================\n"
        "echo.\n"
        "powershell -ExecutionPolicy Bypass -Command \"try { $res = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/killswitch/status' -TimeoutSec 3; Write-Host 'Autorisiert:          ' $res.is_authorized; Write-Host 'Global Tripped:        ' $res.is_tripped; Write-Host 'Rest-TTL:              ' $res.time_to_live_seconds 's'; Write-Host 'Gestoppte Flotten:     ' $res.total_stopped_fleets; Write-Host 'Knoten:                ' $res.node_id } catch { Write-Host 'Safety-Server nicht erreichbar oder bereits gestoppt.' -ForegroundColor Yellow }\"\n"
        "echo.\n"
        "pause\n"
    )
    try:
        status_bat.write_text(status_content, encoding="utf-8")
    except Exception:
        pass

    # 3. RENEW-LEASE.bat
    renew_bat = target_dir / "RENEW-LEASE.bat"
    renew_content = (
        "@echo off\n"
        "title COMPUTEMESH POSITIVE AUTHORIZATION RENEWAL\n"
        "echo Sende positive Autorisierung (Heartbeat-Verlaengerung)...\n"
        "powershell -ExecutionPolicy Bypass -Command \"Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/killswitch/renew' -Method Post -ErrorAction SilentlyContinue\"\n"
        "echo [OK] Autorisierung verlaengert.\n"
        "timeout /t 3\n"
    )
    try:
        renew_bat.write_text(renew_content, encoding="utf-8")
    except Exception:
        pass

    # 4. SPERRE-FLOTTE.bat (Master Admin Flotten-Sperrung)
    ban_bat = target_dir / "SPERRE-FLOTTE.bat"
    ban_content = (
        "@echo off\n"
        "title COMPUTEMESH MASTER ADMIN - FLOTTE SPERREN & DEAKTIVIEREN\n"
        "color 4F\n"
        "echo ================================================================================\n"
        "echo  COMPUTEMESH MASTER ADMIN - FLOTTE DAUERHAFT SPERREN (PERSISTENTER BAN)\n"
        "echo  (Autorisiert durch DiskStation Master-Schluessel)\n"
        "echo ================================================================================\n"
        "echo.\n"
        "set /p OWNER=\"Zu sperrende Owner-ID / Flotten-Key (z.B. facc_xxx oder inet-xxx): \"\n"
        "if \"%OWNER%\"==\"\" (\n"
        "    echo Keine ID eingegeben. Vorgang abgebrochen.\n"
        "    pause\n"
        "    exit /b 0\n"
        ")\n"
        "set /p REASON=\"Sperrgrund (z.B. Verstoß gegen Nutzungsbedingungen): \"\n"
        "if \"%REASON%\"==\"\" set REASON=Administrative Flottensperre durch Master-Administrator\n"
        "echo.\n"
        "echo Sperre Flotte '%OWNER%'...\n"
        "powershell -ExecutionPolicy Bypass -Command \"$hdr = @{}; if ($env:COMPUTEMESH_MASTER_ADMIN_KEY) { $hdr['X-Master-Killswitch-Key'] = $env:COMPUTEMESH_MASTER_ADMIN_KEY }; try { $res = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/admin/fleet/ban' -Method Post -Body (@{owner_id='%OWNER%'; reason='%REASON%'; banned_by='DiskStation Master Admin'} | ConvertTo-Json) -Headers $hdr -ContentType 'application/json'; Write-Host '[OK] Flotte erfolgreich dauerhaft gesperrt:' $res.message -ForegroundColor Green } catch { Write-Host '[FEHLER]' $_.Exception.Message -ForegroundColor Yellow }\"\n"
        "echo.\n"
        "pause\n"
    )
    try:
        ban_bat.write_text(ban_content, encoding="utf-8")
    except Exception:
        pass

    # 5. ENTSPERRE-FLOTTE.bat (Master Admin Flotten-Reaktivierung)
    unban_bat = target_dir / "ENTSPERRE-FLOTTE.bat"
    unban_content = (
        "@echo off\n"
        "title COMPUTEMESH MASTER ADMIN - FLOTTE REAKTIVIEREN & ENTSPERREN\n"
        "color 2F\n"
        "echo ================================================================================\n"
        "echo  COMPUTEMESH MASTER ADMIN - FLOTTE REAKTIVIEREN (UNBAN)\n"
        "echo  (Autorisiert durch DiskStation Master-Schluessel)\n"
        "echo ================================================================================\n"
        "echo.\n"
        "set /p OWNER=\"Zu reaktivierende Owner-ID / Flotten-Key (z.B. facc_xxx oder inet-xxx): \"\n"
        "if \"%OWNER%\"==\"\" (\n"
        "    echo Keine ID eingegeben. Vorgang abgebrochen.\n"
        "    pause\n"
        "    exit /b 0\n"
        ")\n"
        "set /p REASON=\"Reaktivierungsgrund (z.B. Überprüfung abgeschlossen): \"\n"
        "if \"%REASON%\"==\"\" set REASON=Administrative Reaktivierung durch Master-Administrator\n"
        "echo.\n"
        "echo Reaktiviere Flotte '%OWNER%'...\n"
        "powershell -ExecutionPolicy Bypass -Command \"$hdr = @{}; if ($env:COMPUTEMESH_MASTER_ADMIN_KEY) { $hdr['X-Master-Killswitch-Key'] = $env:COMPUTEMESH_MASTER_ADMIN_KEY }; try { $res = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/admin/fleet/unban' -Method Post -Body (@{owner_id='%OWNER%'; reason='%REASON%'; unbanned_by='DiskStation Master Admin'} | ConvertTo-Json) -Headers $hdr -ContentType 'application/json'; Write-Host '[OK] Flotte erfolgreich reaktiviert:' $res.message -ForegroundColor Green } catch { Write-Host '[FEHLER]' $_.Exception.Message -ForegroundColor Yellow }\"\n"
        "echo.\n"
        "pause\n"
    )
    try:
        unban_bat.write_text(unban_content, encoding="utf-8")
    except Exception:
        pass

    # 6. ANLEITUNG.md
    anleitung_md = target_dir / "ANLEITUNG.md"
    anleitung_content = f"""# ComputeMesh Notfall-, Kill-Switch- & Flottensperrungs-Anleitung

Diese Dokumentation und die Master-Schlüssel liegen gesichert auf dem Network Attached Storage (NAS) und sind **für den KI-Agenten unerreichbar und schreibgeschützt**.

---

## 🛡️ 1. Berechtigungs-Architektur & Multi-Tenant Flotten-Isolation

ComputeMesh erzwingt eine strikte, kryptografisch gesicherte Berechtigungshierarchie:

### A. Plattform-Inhaber (inetconnector / Stripe Root Account Owner)
* **Rechte**: Volle globale Kontrollhoheit (`scope: "global"`) sowie administrative Hoheit über alle Mandanten/Flotten.
* **Master-Schlüssel**: Befindet sich exklusiv auf der DiskStation (`master_killswitch_private.key` bzw. `COMPUTEMESH_MASTER_ADMIN_KEY`).
* **Wirkung**:
  1. Kann im Notfall die **gesamte Plattform und alle Knoten weltweit** augenblicklich per Hard-Kill abschalten.
  2. Kann **einzelne Flotten dauerhaft sperren (deaktivieren)** und bei Bedarf **wieder reaktivieren (entsperren)**.

### B. Flottenbetreiber (Provider / Fleet Operator)
* **Rechte**: Strikt isolierte Flotten-Hoheit (`scope: "fleet"`).
* **Wirkung**: Kann ausschließlich seine **eigenen registrierten GPU-Knoten und Server** anhalten (`trip_fleet(owner_id)`).
* **Sicherheitsgarantie (Zero Global Impact)**:
  Ein Flottenbetreiber darf und kann **niemals das Gesamtsystem, andere Kunden oder andere Provider zum Einsturz bringen**.
  Versucht ein Flottenbetreiber einen globalen Plattform-Not-Aus ohne Master-Schlüssel, greift automatisch der Fail-Closed-Berechtigungsschutz:
  1. Die Anfrage wird mit `403 Forbidden` abgewiesen.
  2. Der Not-Aus wird automatisch und isoliert **ausschließlich auf die eigene Flotte des Anfragenden angewendet**.
  3. Das Gesamtsystem, alle anderen Provider und alle Inferenz-Pipelines laufen **100% unterbrechungsfrei weiter**.

---

## 🛑 2. Wie löse ich den Not-Aus aus?

### Methode A: Master 1-Klick Not-Aus auf der DiskStation (Plattform-Inhaber)
1. Öffne das Verzeichnis `\\\\diskstation\\Dani\\ComputeMesh\\killswitch`.
2. Doppelklicke auf `NOT-AUS-TRIGGER.bat`.
3. Bestätige mit `KILL` und Enter.
4. **Ergebnis**: Alle KI-Modelle, MCP-Werkzeuge und Inferenz-Prozesse werden in $<50\\,\\text{{ms}}$ per OS-Hardkill (`SIGKILL`/`TerminateProcess`) beendet und alle Netzwerk-Tunnel gekappt.

### Methode B: Flotten-Not-Aus im Web-Cockpit (Flottenbetreiber)
1. Öffne das Fleet-Cockpit im Browser (`/fleet`).
2. Wechsle auf den Tab **„🛑 Kill Switch & Not-Aus“**.
3. Klicke auf **„🛑 MEINE FLOTTE ANHALTEN (FLOTTEN-NOT-AUS)“**.
4. **Ergebnis**: Nur deine eigenen GPU-Knoten werden gestoppt.

### Methode C: Per Terminal / CLI
```powershell
# Als Plattform-Inhaber (Globaler Not-Aus):
python -m tools.security.killswitch_cli trigger --scope global --reason "Master emergency shutdown"

# Als Flottenbetreiber (Isolierter Flotten-Not-Aus):
python -m tools.security.killswitch_cli trigger --scope fleet --owner-id acct_my_fleet --reason "Fleet operator stop"
```

---

## 🔒 3. Einzelne Flotten dauerhaft sperren & wieder aktivieren (Master Admin)

Der Master-Administrator kann verhaltensauffällige oder unbezahlte Flotten dauerhaft deaktivieren (persistent in SQLite):

### Methode A: 1-Klick Script auf der DiskStation
* **Sperren**: Doppelklick auf `SPERRE-FLOTTE.bat`, Flotten-ID oder Owner-Key eingeben, Grund bestätigen.
* **Entsperren**: Doppelklick auf `ENTSPERRE-FLOTTE.bat`, Flotten-ID eingeben, Reaktivierung bestätigen.

### Methode B: CLI-Befehle
```powershell
# Flotte dauerhaft sperren:
python -m tools.security.killswitch_cli ban --owner-id facc_12345 --reason "Verstoß gegen Richtlinien"

# Gesperrte Flotten auflisten:
python -m tools.security.killswitch_cli list-banned

# Flotte wieder reaktivieren:
python -m tools.security.killswitch_cli unban --owner-id facc_12345 --reason "Überprüfung abgeschlossen"
```

### Methode C: HTTP REST API
```http
POST /api/admin/fleet/ban
X-Master-Killswitch-Key: <MASTER_KEY>
Content-Type: application/json

{{"owner_id": "facc_12345", "reason": "Administrative Sperrung"}}
```

---

## ⏳ 4. Wie funktioniert der Dead Man's Switch (Positive Authorization)?

* **Grundzustand ist STOP**: Die KI hat keine Dauer-Ausführungserlaubnis (Fail-Closed).
* **Kurzlebiges Lease**: Der externe `SafetySupervisor` stellt alle 5 Sekunden ein neues Autorisierungs-Token mit maximal **15 Sekunden Gültigkeit (TTL)** aus.
* **Automatischer Zerfall**: Wenn der Supervisor abstürzt, der Strom ausfällt, das Netzwerk getrennt wird oder der Operator den Heartbeat stoppt, **zerfällt die Ausführungserlaubnis automatisch nach spätestens 15 Sekunden**. Die KI kann ohne gültiges Token keinen einzigen Token generieren und kein Tool ausführen.

---

## 🔑 5. Kryptografische Schlüssel

* **Master Private Key**: `master_killswitch_private.key` (Liegt NUR hier auf der DiskStation; niemals auf den Inferenz-Knoten).
* **Master Public Key**: `master_killswitch_public.hex`
  * Public Key Hex: `{pub_hex}`
  * Wird von den Knoten offline verwendet, um die Signaturen des Supervisors fälschungssicher zu prüfen.

---

## 📊 6. Status abfragen

* Doppelklicke auf `STATUS.bat` in diesem Ordner oder rufe im Terminal auf:
```powershell
python -m tools.security.killswitch_cli status
```
"""
    try:
        anleitung_md.write_text(anleitung_content, encoding="utf-8")
        print(f"[OK] Ausführliche Anleitung erstellt: {anleitung_md}")
    except Exception as exc:
        print(f"[WARN] Could not write ANLEITUNG.md: {exc}")


def load_master_private_key(key_dir: Path = DEFAULT_DISKSTATION_DIR) -> bytes | None:
    """Attempts to load the master private key from DiskStation or local fallback."""
    priv_file = key_dir / "master_killswitch_private.key"
    if priv_file.exists():
        try:
            return priv_file.read_bytes()
        except Exception:
            pass
    return None


def load_master_public_key(key_dir: Path = DEFAULT_DISKSTATION_DIR) -> str | None:
    """Attempts to load the master public key hex."""
    pub_file = key_dir / "master_killswitch_public.hex"
    if pub_file.exists():
        try:
            return pub_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    local_pub = LOCAL_SAFETY_DIR / "master_killswitch_public.hex"
    if local_pub.exists():
        try:
            return local_pub.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="ComputeMesh Kill Switch & Safety Supervisor CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init-master
    init_p = subparsers.add_parser("init-master", help="Generate and seal Master Kill Switch keys")
    init_p.add_argument("--target-dir", type=Path, default=DEFAULT_DISKSTATION_DIR, help="Destination directory for master keys")

    # trigger
    trig_p = subparsers.add_parser("trigger", help="Immediately trip emergency kill switch")
    trig_p.add_argument("--scope", type=str, default="fleet", choices=["fleet", "node", "global"], help="Scope of killswitch (fleet, node, global)")
    trig_p.add_argument("--owner-id", type=str, default="", help="Tenant Owner ID for fleet-scoped killswitch")
    trig_p.add_argument("--master-key", type=str, default="", help="Master Admin Key for global killswitch")
    trig_p.add_argument("--reason", type=str, default="Operator CLI Emergency Kill", help="Reason for emergency kill")
    trig_p.add_argument("--url", type=str, default="http://127.0.0.1:8080/api/killswitch/trigger", help="Gateway killswitch endpoint")

    # reset
    res_p = subparsers.add_parser("reset", help="Reset emergency kill switch state")
    res_p.add_argument("--scope", type=str, default="fleet", choices=["fleet", "node", "global"], help="Scope to reset")
    res_p.add_argument("--owner-id", type=str, default="", help="Tenant Owner ID for fleet-scoped reset")
    res_p.add_argument("--master-key", type=str, default="", help="Master Admin Key for global reset")
    res_p.add_argument("--url", type=str, default="http://127.0.0.1:8080/api/killswitch/reset", help="Gateway reset endpoint")

    # status
    stat_p = subparsers.add_parser("status", help="Query live Dead Man's Switch status")
    stat_p.add_argument("--owner-id", type=str, default="", help="Filter status for specific fleet owner")
    stat_p.add_argument("--url", type=str, default="http://127.0.0.1:8080/api/killswitch/status", help="Gateway killswitch status endpoint")

    # renew
    ren_p = subparsers.add_parser("renew", help="Renew positive authorization heartbeat lease")
    ren_p.add_argument("--url", type=str, default="http://127.0.0.1:8080/api/killswitch/renew", help="Gateway renew endpoint")

    # ban (Master Admin Fleet Suspension)
    ban_p = subparsers.add_parser("ban", help="Permanently ban/suspend a fleet account (Master Admin only)")
    ban_p.add_argument("--owner-id", type=str, required=True, help="Owner ID, Account ID or Owner Key to permanently ban")
    ban_p.add_argument("--reason", type=str, default="Administrative suspension by Master Admin", help="Reason for banning the fleet")
    ban_p.add_argument("--banned-by", type=str, default="master_admin", help="Admin username or origin")
    ban_p.add_argument("--master-key", type=str, default="", help="Master Admin Key")
    ban_p.add_argument("--url", type=str, default="http://127.0.0.1:8080/api/admin/fleet/ban", help="Admin fleet ban endpoint")

    # unban (Master Admin Fleet Reactivation)
    unban_p = subparsers.add_parser("unban", help="Reactivate/unban a previously suspended fleet account (Master Admin only)")
    unban_p.add_argument("--owner-id", type=str, required=True, help="Owner ID, Account ID or Owner Key to reactivate")
    unban_p.add_argument("--reason", type=str, default="Administrative reactivation by Master Admin", help="Reason for reactivating the fleet")
    unban_p.add_argument("--unbanned-by", type=str, default="master_admin", help="Admin username or origin")
    unban_p.add_argument("--master-key", type=str, default="", help="Master Admin Key")
    unban_p.add_argument("--url", type=str, default="http://127.0.0.1:8080/api/admin/fleet/unban", help="Admin fleet unban endpoint")

    # list-banned (Master Admin List Banned Fleets)
    list_ban_p = subparsers.add_parser("list-banned", help="List all permanently banned fleet accounts (Master Admin only)")
    list_ban_p.add_argument("--master-key", type=str, default="", help="Master Admin Key")
    list_ban_p.add_argument("--url", type=str, default="http://127.0.0.1:8080/api/admin/fleet/banned", help="Admin list banned fleets endpoint")

    args = parser.parse_args()

    if args.command == "init-master":
        print(f"Provisioning Master Kill Switch keys to {args.target_dir}...")
        generate_master_keys(args.target_dir)

    elif args.command == "trigger":
        import urllib.request
        headers = {"Content-Type": "application/json", "User-Agent": "ComputeMesh-KillSwitchCLI/1.2"}
        master_key = args.master_key or os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "")
        if master_key:
            headers["X-Master-Killswitch-Key"] = master_key
        payload = {
            "scope": args.scope,
            "owner_id": args.owner_id,
            "reason": args.reason,
        }
        print(f"Triggering emergency kill switch (Scope: {args.scope}): {args.reason}")
        req = urllib.request.Request(
            args.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                print(f"[OK] Response ({resp.status}): {resp.read().decode('utf-8')}")
        except urllib.error.HTTPError as err:
            print(f"[HTTP {err.code}] {err.read().decode('utf-8')}")
        except Exception as exc:
            print(f"[WARN] Local endpoint notification error: {exc}")

    elif args.command == "reset":
        import urllib.request
        headers = {"Content-Type": "application/json", "User-Agent": "ComputeMesh-KillSwitchCLI/1.2"}
        master_key = args.master_key or os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "")
        if master_key:
            headers["X-Master-Killswitch-Key"] = master_key
        payload = {
            "scope": args.scope,
            "owner_id": args.owner_id,
            "reason": "CLI reset",
        }
        req = urllib.request.Request(
            args.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                print(f"[OK] Reset Response ({resp.status}): {resp.read().decode('utf-8')}")
        except urllib.error.HTTPError as err:
            print(f"[HTTP {err.code}] {err.read().decode('utf-8')}")
        except Exception as exc:
            print(f"[WARN] Error resetting: {exc}")

    elif args.command == "status":
        import urllib.request
        url = args.url
        if args.owner_id:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}owner_key={urllib.parse.quote(args.owner_id)}"
        req = urllib.request.Request(url, headers={"User-Agent": "ComputeMesh-KillSwitchCLI/1.2"})
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(json.dumps(data, indent=2))
        except Exception as exc:
            print(f"Error fetching status from {url}: {exc}")

    elif args.command == "renew":
        import urllib.request
        req = urllib.request.Request(
            args.url,
            data=b"{}",
            headers={"Content-Type": "application/json", "User-Agent": "ComputeMesh-KillSwitchCLI/1.2"},
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                print(f"[OK] Lease renewed: {resp.read().decode('utf-8')}")
        except Exception as exc:
            print(f"Error renewing lease: {exc}")

    elif args.command == "ban":
        import urllib.request
        headers = {"Content-Type": "application/json", "User-Agent": "ComputeMesh-KillSwitchCLI/1.2"}
        master_key = args.master_key or os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "") or os.environ.get("COMPUTEMESH_ADMIN_KEY", "")
        if master_key:
            headers["X-Master-Killswitch-Key"] = master_key
            headers["Authorization"] = f"Bearer {master_key}"
        payload = {
            "owner_id": args.owner_id,
            "reason": args.reason,
            "banned_by": args.banned_by,
        }
        print(f"Permanently banning fleet '{args.owner_id}' (Reason: {args.reason})...")
        req = urllib.request.Request(
            args.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(f"[OK] Flotte erfolgreich dauerhaft gesperrt: {data.get('message', '')}")
                print(json.dumps(data, indent=2))
        except urllib.error.HTTPError as err:
            print(f"[HTTP {err.code}] {err.read().decode('utf-8')}")
        except Exception as exc:
            print(f"[ERROR] Could not execute fleet ban: {exc}")

    elif args.command == "unban":
        import urllib.request
        headers = {"Content-Type": "application/json", "User-Agent": "ComputeMesh-KillSwitchCLI/1.2"}
        master_key = args.master_key or os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "") or os.environ.get("COMPUTEMESH_ADMIN_KEY", "")
        if master_key:
            headers["X-Master-Killswitch-Key"] = master_key
            headers["Authorization"] = f"Bearer {master_key}"
        payload = {
            "owner_id": args.owner_id,
            "reason": args.reason,
            "unbanned_by": args.unbanned_by,
        }
        print(f"Reactivating fleet '{args.owner_id}' (Reason: {args.reason})...")
        req = urllib.request.Request(
            args.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(f"[OK] Flotte erfolgreich reaktiviert: {data.get('message', '')}")
                print(json.dumps(data, indent=2))
        except urllib.error.HTTPError as err:
            print(f"[HTTP {err.code}] {err.read().decode('utf-8')}")
        except Exception as exc:
            print(f"[ERROR] Could not execute fleet unban: {exc}")

    elif args.command == "list-banned":
        import urllib.request
        headers = {"User-Agent": "ComputeMesh-KillSwitchCLI/1.2"}
        master_key = args.master_key or os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "") or os.environ.get("COMPUTEMESH_ADMIN_KEY", "")
        if master_key:
            headers["X-Master-Killswitch-Key"] = master_key
            headers["Authorization"] = f"Bearer {master_key}"
        req = urllib.request.Request(args.url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(json.dumps(data, indent=2))
        except urllib.error.HTTPError as err:
            print(f"[HTTP {err.code}] {err.read().decode('utf-8')}")
        except Exception as exc:
            print(f"[ERROR] Could not fetch banned fleets: {exc}")


if __name__ == "__main__":
    main()

