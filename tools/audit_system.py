#!/usr/bin/env python3
"""ComputeMesh System Verification & Live Endpoint Audit."""
import ssl
import sys
import urllib.request

def main() -> int:
    ctx = ssl._create_unverified_context()
    endpoints = [
        "",
        "docs",
        "status",
        "benchmarks",
        "terms",
        "privacy",
        "impressum",
        "contact",
        "portal.css",
        "portal.js",
        "downloads/ComputeMesh-Setup-x64.exe",
        "downloads/computemesh-nodeos-x86_64.img.xz",
        "downloads/computemesh-nodeos-x86_64.iso",
        "downloads/install.sh",
    ]
    print("=" * 70)
    print("AUDITING LIVE SERVER (https://mesh.inetconnector.com)")
    print("=" * 70)
    failed = 0
    for ep in endpoints:
        url = f"https://89.58.11.237/{ep}"
        req = urllib.request.Request(url, headers={"Host": "mesh.inetconnector.com"})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                status = resp.status
                ct = resp.headers.get("Content-Type", "").split(";")[0]
                length = resp.headers.get("Content-Length", "?")
                print(f"  [OK]   /{ep:42} -> {status} OK  [{ct}, {length} bytes]")
        except Exception as e:
            print(f"  [FAIL] /{ep:42} -> FAILED: {e}")
            failed += 1

    print("=" * 70)
    if failed > 0:
        print(f"Audit completed with {failed} failures.")
        return 1
    print("Audit completed successfully. All endpoints 100% operational!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
