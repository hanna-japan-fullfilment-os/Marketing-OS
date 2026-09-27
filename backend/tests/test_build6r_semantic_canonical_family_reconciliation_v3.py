from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


AI_SOURCE = "ai_extracted_candidate"


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
            "the manufacturer suggests folding the mask for wiping/"
            "light patting and following with an emulsion or cream. "
            "Manufacturer describes it as usable morning or evening "
            "in place of toner."
        ),

        verified_size=(
            "7 sheets / essence 150 mL"
        ),

        verified_variant=(
            "Face Mask LuLuLun EX 1FS - 7-sheet pouch"
        ),

        verified_price="",
        verified_availability="",
        verified_country_of_origin="",

        verified_ingredients=[
            (
                "Human adipose-derived mesenchymal cell exosomes "
                "(manufacturer-listed skin-conditioning ingredient; "
                "manufacturer states stem cells are not contained)"
            ),
            "Glutathione",
            "Arbutin",
            "Ascorbyl palmitate (vitamin C derivative)",
            "Human recombinant oligopeptide-1 (EGF)",
            "Ceramide AP",
            "Ceramide NP",
            "Atelocollagen",
            "Hydroxypropyltrimonium hyaluronate",
        ],

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

        verified_benefits=[],

        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Contains human adipose-derived mesenchymal cell "
                "exosomes as a manufacturer-listed skin-conditioning "
                "ingredient; manufacturer states stem cells are not contained"
            ),
            (
                "Contains glutathione, arbutin, and the vitamin C "
                "derivative ascorbyl palmitate"
            ),
            (
                "Contains Ceramide AP, Ceramide NP, atelocollagen, "
                "hydroxypropyltrimonium hyaluronate, and human "
                "recombinant oligopeptide-1"
            ),
            (
                "Manufacturer states the formula is colorant-free, "
                "fragrance-free, mineral-oil-free, and alcohol-free"
            ),
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
    )


def _finding(
    text,
    category,
    source_field=AI_SOURCE,
):

    return claims_audit.ClaimFinding(
        claim_text=text,
        claim_category=category,
        source_field=source_field,
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="synthetic unsupported",
    )


def _status(
    text,
    category,
    source_field=AI_SOURCE,
):

    result = (
        claims_audit
        .ClaimAuditResult(
            findings=[
                _finding(
                    text,
                    category,
                    source_field,
                )
            ]
        )
    )

    return (
        claims_audit
        ._build6r_reconcile_ai_extracted_canonical_fact_families_v31(
            result,
            _verified(),
        )
        .findings[0]
        .evidence_status
    )


SUPPORTED = [
    (
        (
            "Na Hydra EX, o fabricante descreve esse "
            "tecido como um \u201cMelty Feel Sheet\u201d"
        ),
        "ingredients/contents",
    ),
    (
        (
            "A orienta\u00e7\u00e3o do fabricante \u00e9: "
            "desdobrar a m\u00e1scara, encaixar em volta "
            "dos olhos e da boca, tirar o ar que fica preso "
            "entre o tecido e a pele, levantar os recortes "
            "da bochecha acompanhando o contorno do rosto "
            "e ent\u00e3o pressionar a m\u00e1scara inteira "
            "com as palmas das m\u00e3os para ela ficar "
            "bem aderida"
        ),
        "directions for use",
    ),
    (
        (
            "Na Hydra EX, aparecem, entre outros: "
            "exossomos derivados de c\u00e9lulas "
            "mesenquimais do tecido adiposo humano, "
            "glutathione, arbutin, ascorbyl palmitate, "
            "ceramide AP, ceramide NP, atelocollagen, "
            "hydroxypropyltrimonium hyaluronate e "
            "human recombinant oligopeptide-1 (EGF)"
        ),
        "ingredients/contents",
    ),
    (
        (
            "O fabricante descreve a f\u00f3rmula como "
            "livre de corante, livre de fragr\u00e2ncia, "
            "sem \u00f3leo mineral e sem \u00e1lcool"
        ),
        "ingredients/contents",
    ),
]


BLOCKED_EXACT = [
    (
        (
            "A LuLuLun Hydra EX 7 Sheets \u00e9 um pouch "
            "com 7 m\u00e1scaras de tecido mergulhadas "
            "em 150 mL de ess\u00eancia"
        ),
        "ingredients/contents",
    ),
    (
        (
            "Quando voc\u00ea abre o pouch, cada m\u00e1scara "
            "j\u00e1 est\u00e1 dobrada e encharcada de "
            "ess\u00eancia"
        ),
        "product features",
    ),
    (
        (
            "A ess\u00eancia \u00e9 o l\u00edquido em que "
            "as 7 m\u00e1scaras ficam mergulhadas"
        ),
        "ingredients/contents",
    ),
    (
        (
            "a Hydra EX vem em um pouch com 7 folhas "
            "dentro do mesmo pacote, mergulhadas nos "
            "150 mL de ess\u00eancia"
        ),
        "product features",
    ),
]


NEGATIVE_CONTROLS = [
    (
        "Na Hydra EX aparecem glutathione e retinol",
        "ingredients/contents",
    ),
    (
        (
            "O fabricante descreve a formula como "
            "livre de corante e contem alcool"
        ),
        "ingredients/contents",
    ),
    (
        (
            "O fabricante descreve o tecido como "
            "Melty Feel Sheet e garante resultados visiveis"
        ),
        "ingredients/contents",
    ),
    (
        "garante rejuvenescimento visivel",
        "product benefits/effects",
    ),
    (
        "#1 bestseller",
        "ranking_bestseller",
    ),
    (
        "preco promocional e estoque garantido",
        "price/stock",
    ),
]


@pytest.mark.parametrize(
    "text,category",
    SUPPORTED,
)
def test_exact_supported_families(
    text,
    category,
):

    assert (
        _status(
            text,
            category,
        )
        == "SUPPORTED"
    )


@pytest.mark.parametrize(
    "text,category",
    BLOCKED_EXACT,
)
def test_exact_residue_candidates_remain_blocked(
    text,
    category,
):

    assert (
        _status(
            text,
            category,
        )
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "text,category",
    NEGATIVE_CONTROLS,
)
def test_negative_controls_remain_blocked(
    text,
    category,
):

    assert (
        _status(
            text,
            category,
        )
        == "UNSUPPORTED"
    )


def test_non_ai_source_is_not_reconciled():

    assert (
        _status(
            (
                "Na Hydra EX, o fabricante descreve esse "
                "tecido como um Melty Feel Sheet"
            ),
            "ingredients/contents",
            "copy.caption",
        )
        == "UNSUPPORTED"
    )


def test_no_provider_or_network_boundary():

    source = inspect.getsource(
        claims_audit
        ._build6r_reconcile_ai_extracted_canonical_fact_families_v31
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
        marker not in source
        for marker
        in forbidden
    )


def test_product_features_not_broadly_enabled():

    source = inspect.getsource(
        claims_audit
        ._build6r_v31_ai_candidate_supported
    )

    assert (
        '"product features"'
        not in source
    )


def test_real_final_wrapper_supports_melty_and_blocks_unknown(
    monkeypatch,
):

    supported_text = (
        "Na Hydra EX, o fabricante descreve esse "
        "tecido como um Melty Feel Sheet"
    )

    blocked_text = (
        "Na Hydra EX aparecem glutathione e retinol"
    )

    async def fake_previous(
        *args,
        **kwargs,
    ):

        return claims_audit.ClaimAuditResult(
            findings=[
                _finding(
                    supported_text,
                    "ingredients/contents",
                ),
                _finding(
                    blocked_text,
                    "ingredients/contents",
                ),
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_without_semantic_contents_repair",
        fake_previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            fields={
                "copy.caption":
                    supported_text
                    + " "
                    + blocked_text,
            },
            verified=_verified(),
            brand=None,
            model="synthetic",
            existing=(
                claims_audit
                .ClaimAuditResult(
                    findings=[]
                )
            ),
        )
    )

    supported = [
        finding
        for finding
        in result.findings
        if (
            supported_text
            == finding.claim_text
        )
    ]

    blocked = [
        finding
        for finding
        in result.findings
        if (
            blocked_text
            == finding.claim_text
        )
    ]

    assert len(supported) == 1
    assert len(blocked) == 1

    assert (
        supported[0].evidence_status
        == "SUPPORTED"
    )

    assert (
        blocked[0].evidence_status
        == "UNSUPPORTED"
    )
