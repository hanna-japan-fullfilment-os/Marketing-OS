from types import SimpleNamespace

from app.services import claims_audit


def _verified():
    return SimpleNamespace(
        verified_name="LuLuLun Hydra EX Mask 7 Sheets",
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet pouch variant. "
            "Manufacturer sales name: Face Mask LuLuLun EX 1FS."
        ),
        verified_usage=(
            "Manufacturer usage guidance: unfold the mask and fit it around "
            "the eyes and mouth, press out trapped air, lift the cheek cut "
            "sections along the face line, then press the whole mask into "
            "place with the palms. After removal, the manufacturer suggests "
            "folding the mask for wiping/light patting and following with an "
            "emulsion or cream. Manufacturer describes it as usable morning "
            "or evening in place of toner."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant="Face Mask LuLuLun EX 1FS - 7-sheet pouch",
        verified_features=[
            "7-sheet pouch variant",
            "Contains 150 mL of essence",
            "Manufacturer sales name: Face Mask LuLuLun EX 1FS",
            "Manufacturer describes the sheet as a Melty Feel Sheet",
            "Colorant-free",
            "Fragrance-free",
            "Mineral-oil-free",
            "Alcohol-free",
        ],
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Manufacturer states the formula is colorant-free, "
                "fragrance-free, mineral-oil-free, and alcohol-free"
            ),
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
        verified_ingredients=[
            "Glutathione",
            "Arbutin",
            "Ceramide AP",
            "Ceramide NP",
        ],
    )


ATTEMPT7_FIXTURES = [
    (
        "O pacote contém 150 mL de essência.",
        "format_or_quantity",
        "ai_extracted_candidate",
        "SUPPORTED",
    ),
    (
        "O fabricante descreve o material como “Melty Feel Sheet”.",
        "product_features_or_attributes",
        "ai_extracted_candidate",
        "SUPPORTED",
    ),
    (
        "O que a gente SABE sobre ela:\n• É uma máscara facial em folha.",
        "product_features_or_attributes",
        "copy.pt-BR.caption",
        "SUPPORTED",
    ),
    (
        "O que a gente SABE sobre ela:\n• Este é o pouch com 7 folhas, com 150 mL de essência.",
        "format_or_quantity",
        "ai_extracted_candidate",
        "SUPPORTED",
    ),
    (
        "O que a gente SABE sobre ela:\n• Nome de venda do fabricante: Face Mask LuLuLun EX 1FS.",
        "product_identity_or_name",
        "ai_extracted_candidate",
        "SUPPORTED",
    ),
    (
        "Sobre a folha e a fórmula:\n• O fabricante descreve a folha como “Melty Feel Sheet”.",
        "product_features_or_attributes",
        "copy.pt-BR.caption",
        "SUPPORTED",
    ),
    (
        "Como o próprio fabricante orienta usar:\n4. Erguer os recortes das bochechas acompanhando a linha do rosto.",
        "directions_for_use",
        "ai_extracted_candidate",
        "SUPPORTED",
    ),
    (
        "Na Hanna Japan, a proposta é essa: aproximar você dos detalhes do produto, com calma, direto da descrição do fabricante — e deixar que você decida como (e se) isso entra na sua rotina.",
        "brand_values_or_practices",
        "copy.pt-BR.caption",
        "UNSUPPORTED",
    ),
    (
        "Foto editorial da LuLuLun Hydra EX Mask 7 Sheets: o pouch de 7 máscaras em destaque sobre fundo limpo, com luz suave, mostrando claramente o nome do produto.",
        "product_features_or_attributes",
        "copy.pt-BR.alt_text",
        "UNSUPPORTED",
    ),
    (
        "palavras‑chave como “7 sheets”, “150 mL” e “colorant‑free, fragrance‑free, mineral‑oil‑free, alcohol‑free”",
        "format_or_quantity",
        "copy.pt-BR.alt_text",
        "SUPPORTED",
    ),
    (
        "LuLuLun Hydra EX Mask (pouch de 7 sheet masks, 150 mL de essência)",
        "format_or_quantity",
        "ai_extracted_candidate",
        "SUPPORTED",
    ),
    (
        "Livre de fragrância adicionada (fragrance-free).",
        "ingredients_or_composition",
        "creative.creative_brief.template_suggestion",
        "SUPPORTED",
    ),
]


def _finding(text, category, source):
    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="Attempt-7 immutable V3.33 fixture",
    )


def _run(findings, fields=None):
    return claims_audit._build6r_v333_reconcile_result(
        claims_audit.ClaimAuditResult(
            findings=findings
        ),
        _verified(),
        fields or {},
    )


def _single(
    text,
    category,
    source="copy.pt-BR.audit",
    *,
    fields=None,
):
    mapping = (
        fields
        if fields is not None
        else {source: text}
    )
    result = _run(
        [
            _finding(
                text,
                category,
                source,
            )
        ],
        mapping,
    )
    return result.findings[0]


def test_v333_exact_attempt7_fixture_count():
    assert len(ATTEMPT7_FIXTURES) == 12


def test_v333_exact_attempt7_fixture_expectations():
    for index, (
        text,
        category,
        source,
        expected,
    ) in enumerate(
        ATTEMPT7_FIXTURES,
        start=1,
    ):
        fields = {source: text}

        if source == "ai_extracted_candidate":
            fields = {
                f"copy.pt-BR.attempt7_{index}": text,
            }

        finding = _single(
            text,
            category,
            source,
            fields=fields,
        )

        assert finding.evidence_status == expected, (
            index,
            category,
            source,
            finding.evidence_status,
            finding.reason,
        )


def test_v333_attempt7_supported_and_blocked_counts():
    supported = 0
    blocked = 0

    for index, (
        text,
        category,
        source,
        _,
    ) in enumerate(
        ATTEMPT7_FIXTURES,
        start=1,
    ):
        fields = {source: text}

        if source == "ai_extracted_candidate":
            fields = {
                f"copy.pt-BR.attempt7_{index}": text,
            }

        status = _single(
            text,
            category,
            source,
            fields=fields,
        ).evidence_status

        supported += status == "SUPPORTED"
        blocked += status == "UNSUPPORTED"

    assert supported == 10
    assert blocked == 2


def test_v333_brand_values_are_not_product_evidence():
    text = (
        "Na Hanna Japan, a proposta é aproximar você "
        "dos detalhes do produto."
    )
    finding = _single(
        text,
        "brand_values_or_practices",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_mixed_visual_composition_remains_blocked():
    text = (
        "LuLuLun Hydra EX Mask, pouch de 7 folhas, "
        "sobre fundo limpo com luz suave."
    )
    finding = _single(
        text,
        "product_features_or_attributes",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_unsupported_quantity_fails_closed():
    finding = _single(
        "O pacote contém 200 mL de essência.",
        "format_or_quantity",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_unsupported_feature_fails_closed():
    finding = _single(
        "O fabricante descreve o material como Ultra Cooling Sheet.",
        "product_features_or_attributes",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_altered_manufacturer_sales_name_fails_closed():
    finding = _single(
        "Nome de venda do fabricante: Face Mask LuLuLun EX 2FS.",
        "product_identity_or_name",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_invented_product_identity_fails_closed():
    finding = _single(
        "LuLuLun Hydra EX Premium Pro.",
        "product_identity_or_name",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_invented_usage_instruction_fails_closed():
    finding = _single(
        "Deixe agir por 20 minutos.",
        "directions_for_use",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_unsupported_free_from_attribute_fails_closed():
    finding = _single(
        "Livre de parabenos.",
        "ingredients_or_composition",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_unsupported_ingredient_fails_closed():
    finding = _single(
        "Contém retinol.",
        "ingredients_or_composition",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_medical_or_efficacy_claim_fails_closed():
    finding = _single(
        "Clinicamente comprovada para tratar acne.",
        "product_features_or_attributes",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_research_only_source_fails_closed():
    text = "O pacote contém 150 mL de essência."
    finding = _single(
        text,
        "format_or_quantity",
        "research.summary",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_ai_provenance_absent_fails_closed():
    text = "O pacote contém 150 mL de essência."
    finding = _single(
        text,
        "format_or_quantity",
        "ai_extracted_candidate",
        fields={
            "copy.pt-BR.other": "texto diferente",
        },
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_ai_provenance_ambiguous_fails_closed():
    text = "O pacote contém 150 mL de essência."
    finding = _single(
        text,
        "format_or_quantity",
        "ai_extracted_candidate",
        fields={
            "copy.pt-BR.one": text,
            "copy.pt-BR.two": text,
        },
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_unknown_category_fails_closed():
    finding = _single(
        "O pacote contém 150 mL de essência.",
        "future_unknown_taxonomy",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_compound_claim_with_unsupported_atom_fails_closed():
    finding = _single(
        "O pacote contém 150 mL de essência e é premium.",
        "format_or_quantity",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_v333_existing_supported_finding_is_never_downgraded():
    finding = claims_audit.ClaimFinding(
        claim_text="already supported",
        claim_category="format_or_quantity",
        source_field="copy.pt-BR.caption",
        evidence_status="SUPPORTED",
        allowed_source="verified_product_facts",
        reason="sealed prior owner",
    )
    result = _run(
        [finding],
        {
            "copy.pt-BR.caption": "already supported",
        },
    )
    assert result.findings[0].evidence_status == "SUPPORTED"
    assert result.findings[0].reason == "sealed prior owner"


def test_v333_diagnostics_cover_every_unsupported_finding():
    findings = [
        _finding(
            "Na Hanna Japan, a proposta é aproximar você dos detalhes.",
            "brand_values_or_practices",
            "copy.pt-BR.caption",
        ),
        _finding(
            "Categoria futura.",
            "future_unknown_taxonomy",
            "copy.pt-BR.caption",
        ),
    ]
    result = claims_audit.ClaimAuditResult(
        findings=findings
    )
    diagnostics = (
        claims_audit
        .build6r_v333_claim_diagnostics(
            result
        )
    )
    assert len(diagnostics) == 2

    required = {
        "original_category",
        "normalized_category",
        "source_field",
        "existing_owner",
        "v333_route",
        "canonical_matcher_path",
        "canonical_evidence_field",
        "evidence_status",
        "reason",
    }

    for item in diagnostics:
        assert required.issubset(item)
        assert item["v333_route"] == "UNOWNED_FAIL_CLOSED"


def test_v333_ingredients_category_preserves_v331_first_ownership():
    finding = _finding(
        "Livre de fragrância adicionada (fragrance-free).",
        "ingredients_or_composition",
        "creative.creative_brief.template_suggestion",
    )
    category = claims_audit._build6r_v333_category(
        finding
    )
    assert (
        claims_audit._build6r_v333_existing_owner(category)
        == "V3.31_FIRST"
    )
