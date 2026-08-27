# Privacy-by-design external-resource policy

Status: current for the public portal.

The ComputeMesh portal must operate without advertising, behavioral tracking, third-party font delivery or general-purpose third-party CDN dependencies unless a later feature has been separately assessed and, where legally required, placed behind valid consent.

Enforcement exists in both supported delivery paths:

- the Python gateway/portal security headers restrict browser CSP resource origins to `self` (plus inline script/style currently required by the existing portal implementation);
- `portal/.htaccess` applies the same first-party policy for static Apache delivery.

Consequences:

- Google Fonts and other third-party font resources are not permitted to load;
- generic external scripts/CDNs are not permitted to load;
- browser API connections are limited to the same origin;
- advertising pixels and cross-site tracking resources are not part of the approved portal surface.

Legacy HTML resource hints or references that remain in old templates are inert under the enforced CSP and should be removed opportunistically when those templates are otherwise edited. They must not be used as a reason to relax the CSP.

Any future external analytics, support widget, captcha, payment embed, font host, CDN or similar browser-side third party requires before deployment:

1. documented purpose and legal basis;
2. update of the RoPA/VVT and privacy notice where applicable;
3. processor/controller and transfer assessment;
4. Art. 28 DPA where required;
5. consent management where required by GDPR/TDDDG;
6. explicit CSP allow-list change reviewed together with the privacy change.
