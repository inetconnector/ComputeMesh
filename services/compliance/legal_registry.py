"""Legal Rule Registry for ComputeMesh EU Digital Regulation Compliance.

Centralizes formal legal citations, official EUR-Lex references, and verification timestamps
for EU Regulations and Directives governing digital platform operations, trader traceability,
data protection, and platform-to-business relations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class LegalRuleCitation:
    rule_id: str
    short_title: str
    official_title: str
    norm_identifier: str
    articles: list[str]
    source_url: str
    last_verified: str
    scope_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LegalRuleRegistry:
    """Registry of official legal citations and normative foundations."""

    RULES: dict[str, LegalRuleCitation] = {
        "dsa_article_30": LegalRuleCitation(
            rule_id="dsa_article_30",
            short_title="DSA Art. 30 (Traceability of Traders)",
            official_title="Regulation (EU) 2022/2065 on a Single Market For Digital Services (Digital Services Act)",
            norm_identifier="Regulation (EU) 2022/2065",
            articles=["Article 30", "Article 31"],
            source_url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32022R2065",
            last_verified="2026-09-08",
            scope_summary="Applies to online platforms that allow consumers to conclude distance contracts with traders. Mandates traceability information (name, address, email, phone, business register) and self-certification before platform access is granted.",
        ),
        "dsa_article_29": LegalRuleCitation(
            rule_id="dsa_article_29",
            short_title="DSA Art. 29 (Exemption for Micro and Small Enterprises)",
            official_title="Regulation (EU) 2022/2065 on a Single Market For Digital Services (Digital Services Act)",
            norm_identifier="Regulation (EU) 2022/2065",
            articles=["Article 29"],
            source_url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32022R2065",
            last_verified="2026-09-08",
            scope_summary="Exempts online platforms that qualify as micro or small enterprises within the meaning of Recommendation 2003/361/EC (<50 staff, <=EUR 10m turnover/balance sheet) from Section 3 obligations including Art. 30 and 31.",
        ),
        "gdpr_general": LegalRuleCitation(
            rule_id="gdpr_general",
            short_title="GDPR (Data Protection & Privacy by Design)",
            official_title="Regulation (EU) 2016/679 on the protection of natural persons with regard to the processing of personal data (GDPR)",
            norm_identifier="Regulation (EU) 2016/679",
            articles=["Article 5", "Article 6", "Article 13", "Article 14", "Article 25", "Article 32"],
            source_url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679",
            last_verified="2026-09-08",
            scope_summary="Governs purpose limitation, data minimization, lawfulness of processing, privacy by design, and security of processing for natural person provider identity records.",
        ),
        "p2b_transparency": LegalRuleCitation(
            rule_id="p2b_transparency",
            short_title="P2B Regulation (Platform-to-Business Transparency)",
            official_title="Regulation (EU) 2019/1150 on promoting fairness and transparency for business users of online intermediation services",
            norm_identifier="Regulation (EU) 2019/1150",
            articles=["Article 3", "Article 4"],
            source_url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32019R1150",
            last_verified="2026-09-08",
            scope_summary="Requires transparent operational terms, objective grounds for suspension or restriction of business users, and clear statements of reasons prior to or at the time of restriction.",
        ),
        "dac7_scope": LegalRuleCitation(
            rule_id="dac7_scope",
            short_title="DAC7 (Tax Reporting on Digital Platforms)",
            official_title="Council Directive (EU) 2021/514 amending Directive 2011/16/EU on administrative cooperation in the field of taxation",
            norm_identifier="Directive (EU) 2021/514",
            articles=["Article 8ac", "Annex V"],
            source_url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32021L0514",
            last_verified="2026-09-08",
            scope_summary="Defines 'Relevant Activities' (sale of goods, personal services, rental of immovable property, rental of transport). Automated compute/GPU capacity provisioning is evaluated under the dynamic product scope trigger.",
        ),
        "sme_recommendation": LegalRuleCitation(
            rule_id="sme_recommendation",
            short_title="EC SME Recommendation 2003/361/EC",
            official_title="Commission Recommendation 2003/361/EC concerning the definition of micro, small and medium-sized enterprises",
            norm_identifier="Recommendation 2003/361/EC",
            articles=["Annex Article 2"],
            source_url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32003H0361",
            last_verified="2026-09-08",
            scope_summary="Defines micro-enterprises (<10 staff, <=EUR 2m turnover/balance sheet) and small enterprises (<50 staff, <=EUR 10m turnover/balance sheet) referenced by DSA Art. 29.",
        ),
    }

    @classmethod
    def get_citation(cls, rule_id: str) -> LegalRuleCitation | None:
        return cls.RULES.get(rule_id)

    @classmethod
    def all_citations(cls) -> list[LegalRuleCitation]:
        return list(cls.RULES.values())
