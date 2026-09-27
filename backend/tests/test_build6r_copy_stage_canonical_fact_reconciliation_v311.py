from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import app.services.claims_audit as claims_audit


SAFE = {
    1, 2, 4, 5, 6, 7, 8, 9,
    10, 11, 12, 13, 14, 16, 17, 18,
}

BLOCKED = {3, 15}


def _verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact "
            "7-sheet pouch variant. Manufacturer sales name: "
            "Face Mask LuLuLun EX 1FS."
        ),
        verified_usage=(
            "Manufacturer usage guidance: unfold the mask and fit it "
            "around the eyes and mouth, press out trapped air, lift "
            "the cheek cut sections along the face line, then press "
            "the whole mask into place with the palms. After removal, "
            "the manufacturer suggests folding the mask for "
            "wiping/light patting and following with an emulsion or "
            "cream. Manufacturer describes it as usable morning or "
            "evening in place of toner."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant="Face Mask LuLuLun EX 1FS",
        verified_features=[
            "7-sheet pouch variant",
            "Contains 150 mL of essence",
            "Manufacturer describes the sheet as a Melty Feel Sheet",
            "Colorant-free",
            "Fragrance-free",
            "Mineral-oil-free",
            "Alcohol-free",
        ],
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Contains human adipose-derived mesenchymal cell "
                "exosomes as a manufacturer-listed skin-conditioning "
                "ingredient; manufacturer states stem cells are not "
                "contained"
            ),
        ],
        verified_ingredients=[
            (
                "Human adipose-derived mesenchymal cell exosomes "
                "(manufacturer-listed skin-conditioning ingredient; "
                "manufacturer states stem cells are not contained)"
            ),
            "Glutathione",
            "Arbutin",
            "Ascorbyl palmitate (vitamin C derivative)",
            "Ceramide AP",
            "Ceramide NP",
            "Atelocollagen",
            "Hydroxypropyltrimonium hyaluronate",
        ],
        verified_benefits=[],
    )


TARGETS = {
    1: "Produto de skincare voltado ao rosto",
    2: (
        "Formato: pouch com 7 sheet masks, com "
        "150 mL de ess\u00eancia no total"
    ),
    3: (
        "Ingredientes listados como condicionadores "
        "de pele e de f\u00f3rmula"
    ),
    4: "Sem corantes adicionados (colorant-free)",
    5: "Sem fragr\u00e2ncia adicionada (fragrance-free)",
    6: (
        "Sobre o tecido: o fabricante descreve a sheet "
        "como \u201cMelty Feel Sheet\u201d"
    ),
    7: (
        "O fabricante descreve que pode ser usada de "
        "manh\u00e3 ou \u00e0 noite no lugar do "
        "t\u00f4nico/lo\u00e7\u00e3o"
    ),
    8: "Variante em pouch com 7 m\u00e1scaras",
    9: "Cont\u00e9m 150 mL de ess\u00eancia no total",
    10: (
        "Exossomos derivados de c\u00e9lulas mesenquimais "
        "de tecido adiposo humano como ingrediente de cuidado "
        "da pele \u2014 e o pr\u00f3prio fabricante destaca "
        "que N\u00c3O cont\u00e9m c\u00e9lulas-tronco"
    ),
    11: "Colorant-free (sem corante adicionado)",
    12: "Fragrance-free (sem fragr\u00e2ncia adicionada)",
    13: "Formato: pouch com 7 sheet masks",
    14: "Quantidade de ess\u00eancia: 150 mL no total",
    15: (
        "O fabricante lista estes ingredientes "
        "na f\u00f3rmula da Hydra EX"
    ),
    16: (
        "Segundo o fabricante, a Hydra EX: "
        "\u2022 \u00c9 colorant-free (sem corantes adicionados) "
        "\u2022 \u00c9 fragrance-free (sem fragr\u00e2ncia adicionada) "
        "\u2022 \u00c9 mineral-oil-free (sem \u00f3leo mineral) "
        "\u2022 \u00c9 alcohol-free (sem \u00e1lcool)"
    ),
    17: (
        "Sobre o tecido, o fabricante descreve a sheet "
        "como \u201cMelty Feel Sheet\u201d"
    ),
    18: (
        "Pode ser usada de manh\u00e3 ou \u00e0 noite "
        "no lugar do t\u00f4nico/lo\u00e7\u00e3o, "
        "segundo o fabricante"
    ),
}


def _finding(index):
    return claims_audit.ClaimFinding(
        claim_text=TARGETS[index],
        claim_category="synthetic",
        source_field="copy.pt-BR.synthetic",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="pre-v311",
    )


def test_v311_exact_live_18_classification():
    actual = {
        i
        for i, text in TARGETS.items()
        if (
            claims_audit
            ._build6r_v311_copy_stage_claim_supported(
                text,
                _verified(),
            )
        )
    }

    assert actual == SAFE
    assert set(TARGETS) - actual == BLOCKED


def test_v311_wrapper_reconciles_only_safe_16(monkeypatch):
    async def previous(*args, **kwargs):
        return claims_audit.ClaimAuditResult(
            findings=[
                _finding(i)
                for i in TARGETS
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v311",
        previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            fields={},
            verified=_verified(),
            brand=None,
            model="synthetic",
            existing=claims_audit.ClaimAuditResult(
                findings=[]
            ),
        )
    )

    actual = {
        i
        for i, finding in zip(
            TARGETS,
            result.findings,
        )
        if finding.evidence_status == "SUPPORTED"
    }

    assert actual == SAFE


def test_v311_two_unsafe_live_claims_stay_blocked():
    for i in BLOCKED:
        assert not (
            claims_audit
            ._build6r_v311_copy_stage_claim_supported(
                TARGETS[i],
                _verified(),
            )
        )


def test_v311_mixed_new_benefit_fails_closed():
    assert not (
        claims_audit
        ._build6r_v311_copy_stage_claim_supported(
            (
                "Formato: pouch com 7 sheet masks, com "
                "150 mL de ess\u00eancia no total e hidrata "
                "profundamente a pele"
            ),
            _verified(),
        )
    )


def test_v311_unknown_claim_families_fail_closed():
    samples = (
        "A f\u00f3rmula cont\u00e9m retinol",
        "Produto n\u00famero 1 no Jap\u00e3o",
        "Mais vendido da categoria",
        "Agora por 990 ienes",
        "Estoque limitado",
        (
            "Pesquisas mostram que consumidores japoneses "
            "preferem este formato"
        ),
    )

    for text in samples:
        assert not (
            claims_audit
            ._build6r_v311_copy_stage_claim_supported(
                text,
                _verified(),
            )
        )


def test_v311_missing_canonical_atom_fails_closed():
    verified = _verified()

    verified.verified_features = [
        item
        for item in verified.verified_features
        if item != "Fragrance-free"
    ]

    assert not (
        claims_audit
        ._build6r_v311_copy_stage_claim_supported(
            "Fragrance-free (sem fragr\u00e2ncia adicionada)",
            verified,
        )
    )


def test_v311_existing_supported_finding_is_immutable():
    finding = claims_audit.ClaimFinding(
        claim_text="already supported",
        claim_category="other",
        source_field="copy.pt-BR.caption",
        evidence_status="SUPPORTED",
        allowed_source="verified_product_facts",
        reason="existing",
    )

    result = (
        claims_audit
        ._build6r_v311_reconcile_copy_stage_canonical_findings(
            claims_audit.ClaimAuditResult(
                findings=[finding]
            ),
            _verified(),
        )
    )

    assert result.findings[0] == finding


def test_v311_wrapper_preserves_all_sealed_source_contracts():
    source = inspect.getsource(
        claims_audit.augment_with_ai_extraction
    )

    markers = (
        "_build6r_augment_before_v32",
        "_build6r_reconcile_generated_semantic_findings_v32",
        "_build6r_augment_before_v33",
        "_build6r_reconcile_generated_semantic_findings_v33",
        "_build6r_augment_before_v34",
        "_build6r_reconcile_generated_semantic_findings_v34",
        "_build6r_augment_before_v35",
        "_build6r_reconcile_generated_semantic_findings_v35",
        "_build6r_augment_before_v311",
        "_build6r_v311_reconcile_copy_stage_canonical_findings",
    )

    for marker in markers:
        assert marker in source


def test_v311_helper_is_zero_cost():
    source = "\n".join(
        (
            inspect.getsource(
                claims_audit
                ._build6r_v311_copy_stage_claim_supported
            ),
            inspect.getsource(
                claims_audit
                ._build6r_v311_reconcile_copy_stage_canonical_findings
            ),
        )
    )

    forbidden = (
        "generate_structured",
        "generate_image",
        "edit_image",
        "responses.",
        "images.",
        "httpx",
        "requests.",
        "socket.",
        "research_provider",
    )

    assert all(
        item not in source
        for item in forbidden
    )
