# Search Indexing Runbook

**Canonical host:** `https://computemesh.inetconnector.com/`  
**Primary sitemap:** `https://computemesh.inetconnector.com/sitemap.xml`  
**Crawler policy:** `https://computemesh.inetconnector.com/robots.txt`

This runbook records the supported publication path for making the ComputeMesh public portal discoverable by Google and other search engines.

## Implemented crawl signals

- `portal/google55d49cbebf6659d4.html` keeps the Google Search Console URL-prefix property verified through the HTML-file method. Do not remove it from production deployments.
- `portal/robots.txt` allows crawling and advertises the sitemap URL.
- `portal/sitemap.xml` lists the public canonical portal pages with real `lastmod` dates.
- Public HTML pages include canonical URLs and `index,follow` robots metadata.
- The homepage includes OpenGraph/Twitter metadata and `Organization` JSON-LD.
- `services/portal/server.py` serves `robots.txt` and `sitemap.xml` with stable text/XML content types for local and packaged portal deployments.

## Live verification

Use these checks after every production portal deployment:

```powershell
curl.exe -I https://computemesh.inetconnector.com/
curl.exe -I https://computemesh.inetconnector.com/robots.txt
curl.exe -s https://computemesh.inetconnector.com/robots.txt
curl.exe -I https://computemesh.inetconnector.com/sitemap.xml
curl.exe -s https://computemesh.inetconnector.com/sitemap.xml
```

Expected:

- `/`, `/robots.txt`, and `/sitemap.xml` return `200 OK`.
- `/google55d49cbebf6659d4.html` returns `200 OK` and contains the Google verification token.
- `robots.txt` contains `Sitemap: https://computemesh.inetconnector.com/sitemap.xml`.
- `sitemap.xml` is valid XML and lists only canonical public HTTPS URLs.

## Google submission path

Google's supported paths for this portal are:

1. Keep the sitemap discoverable through `robots.txt`.
2. Verify the domain or URL-prefix property in Google Search Console.
3. Submit `https://computemesh.inetconnector.com/sitemap.xml` in the Search Console Sitemaps report.
4. Use URL Inspection in Search Console for critical URLs and request indexing when needed.

Current status as of 2026-08-23:

- URL-prefix property `https://computemesh.inetconnector.com/` is verified in Google Search Console account `mail@inetconnector.com` by HTML file.
- Sitemap `/sitemap.xml` is submitted.
- Search Console reports sitemap status `Erfolgreich` with 8 detected pages and 0 videos.

Important boundaries:

- Sitemap submission is a crawl hint, not an indexing guarantee.
- Google's unauthenticated sitemap ping endpoint is deprecated and should not be used.
- Google's Indexing API is officially limited to `JobPosting` pages and `BroadcastEvent` pages embedded in `VideoObject`; the ComputeMesh portal is normal product/documentation content, so Search Console + sitemap is the correct channel.

Official references:

- <https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap>
- <https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl>
- <https://support.google.com/webmasters/answer/9012289>
- <https://developers.google.com/search/apis/indexing-api/v3/quickstart>
- <https://developers.google.com/search/blog/2023/06/sitemaps-lastmod-ping>
