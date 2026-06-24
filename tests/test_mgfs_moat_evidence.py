from sentinel.mgfs.moat_evidence import MoatEvidenceAuditor


def test_moat_evidence_auditor_accepts_complete_evidence():
    report = MoatEvidenceAuditor().audit_config(
        {
            "companies": {
                "600519": {
                    "base_score": {
                        "brand_premium": {
                            "score": 95,
                            "note": "高端白酒定价权",
                            "source": "2025 annual report",
                            "as_of": "2026-05-01",
                            "confidence": 0.86,
                            "bear_case": "渠道库存持续恶化会削弱品牌溢价",
                        },
                        "franchise_barrier": {
                            "score": 90,
                            "note": "地理标志和产能约束",
                            "source": ["2025 annual report", "industry dataset"],
                            "as_of": "2026-05-02",
                            "confidence": 0.8,
                            "bear_case": "监管限制价格体系会压缩超额利润",
                        },
                    }
                }
            }
        }
    )

    assert report.total_items == 2
    assert report.required_fields == 8
    assert report.missing_count == 0
    assert report.invalid_count == 0
    assert report.coverage == 1.0
    assert report.issues == []


def test_moat_evidence_auditor_reports_missing_legacy_fields():
    report = MoatEvidenceAuditor().audit_config(
        {
            "companies": {
                "600519": {
                    "base_score": {
                        "brand_premium": {
                            "score": 95,
                            "note": "高端白酒定价权",
                        }
                    }
                }
            }
        }
    )

    assert report.total_items == 1
    assert report.required_fields == 4
    assert report.missing_count == 4
    assert report.invalid_count == 0
    assert report.coverage == 0.0
    assert {issue.field for issue in report.issues} == {
        "source",
        "as_of",
        "confidence",
        "bear_case",
    }
    assert all(issue.symbol == "600519" for issue in report.issues)
    assert all(issue.dimension == "brand_premium" for issue in report.issues)


def test_moat_evidence_auditor_reports_invalid_confidence_and_date():
    report = MoatEvidenceAuditor().audit_config(
        {
            "companies": {
                "600519": {
                    "base_score": {
                        "brand_premium": {
                            "score": 95,
                            "source": "research note",
                            "as_of": "2026/05/01",
                            "confidence": 1.3,
                            "bear_case": "竞品价格带下移",
                        }
                    }
                }
            }
        }
    )

    assert report.total_items == 1
    assert report.required_fields == 4
    assert report.missing_count == 0
    assert report.invalid_count == 2
    assert report.coverage == 0.5
    assert {issue.field for issue in report.issues} == {"as_of", "confidence"}
