# Deployment- und SSOT-Richtlinie für die ComputeMesh-Webseite

## Strikte Entwicklungs- und Deployment-Reihenfolge (Single Source of Truth)

1. **Lokale Führendheit (Local First / Git as SSOT):**
   - **Niemals direkt auf dem Server editieren:** Änderungen an HTML, CSS, JavaScript, Bildern oder Server-Routen dürfen **unter keinen Umständen** direkt auf dem Plesk-Server vorgenommen werden.
   - **Immer zuerst lokal ändern:** Jede Änderung muss zuerst im lokalen Arbeitsbereich in `portal/` bzw. `services/portal/` vorgenommen und lokal getestet werden.

2. **Versionskontrolle & Synchronisation:**
   - Nach erfolgreichem lokalem Test werden die Änderungen im Git-Repository committet und auf GitHub (`origin/main`) gepusht.
   - GitHub ist die alleinige, verbindliche Quelle der Wahrheit (Single Source of Truth / SSOT).

3. **Geregeltes Deployment auf den Server:**
   - Das Einspielen auf den Server erfolgt ausschließlich über das standardisierte Deployment-Skript `deploy/sync_plesk_portal.sh` (oder `git pull origin main` in `/opt/computemesh` gefolgt von der automatisierten Synchronisation in die Plesk Document Roots `/var/www/vhosts/inetconnector.com/site2` und `/var/www/vhosts/inetconnector.com/httpdocs`).
   - Binäre Installer in `downloads/` (`.iso`, `.apk`, `.exe` etc.) verbleiben auf dem Server und werden durch das Deployment-Skript geschützt und nicht überschrieben.
