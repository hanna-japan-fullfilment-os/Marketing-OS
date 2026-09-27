from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


def _verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet "
            "pouch variant. Manufacturer sales name: "
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
        verified_size="7 sheets / essence 150 mL",
        verified_variant="Face Mask LuLuLun EX 1FS - 7-sheet pouch",
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
                "Manufacturer states the formula is colorant-free, "
                "fragrance-free, mineral-oil-free, and alcohol-free"
            ),
            "Manufacturer describes the sheet as a Melty Feel Sheet",
        ],
    )


def _status(
    text,
    category,
    source_field="ai_extracted_candidate",
):
    result = claims_audit.ClaimAuditResult(
        findings=[
            claims_audit.ClaimFinding(
                claim_text=text,
                claim_category=category,
                source_field=source_field,
                evidence_status="UNSUPPORTED",
                allowed_source="",
                reason="synthetic live failure",
            )
        ]
    )

    result = (
        claims_audit
        ._build6r_reconcile_semantic_contents_findings(
            result,
            _verified(),
        )
    )

    return result.findings[0].evidence_status


SUPPORTED_CASES = [
    (
        "O pr\u00f3prio fabricante descreve o tecido como um "
        "\u201cMelty Feel Sheet\u201d, e a f\u00f3rmula \u00e9 livre de "
        "corantes, fragr\u00e2ncia, \u00f3leo mineral e \u00e1lcool.",
        "ingredients/omissions",
        "ai_extracted_candidate",
    ),
    (
        "O LuLuLun Hydra EX vem em um pouch com "
        "7 m\u00e1scaras faciais e 150 mL de essence.",
        "product composition/format",
        "copy.pt-BR.caption",
    ),
    (
        "f\u00f3rmula livre de corantes, fragr\u00e2ncia, "
        "\u00f3leo mineral e \u00e1lcool, segundo o fabricante",
        "ingredients/omissions",
        "copy.pt-BR.caption",
    ),
    (
        "pode ser usada de manh\u00e3 ou \u00e0 noite no lugar "
        "do t\u00f4nico, seguindo a orienta\u00e7\u00e3o do fabricante",
        "directions for use",
        "copy.pt-BR.caption",
    ),
    (
        "LuLuLun Hydra EX Mask 7 Sheets. 7 folhas em um "
        "\u00fanico pouch, com 150 mL de essence.",
        "product composition/format",
        "ai_extracted_candidate",
    ),
    (
        "Pouch com 7 sheets e 150 mL de essence.",
        "product composition/format",
        "ai_extracted_candidate",
    ),
    (
        "Cont\u00e9m human adipose-derived mesenchymal cell "
        "exosomes como ingrediente de condicionamento da pele "
        "(sem stem cells, segundo o fabricante).",
        "ingredients/contents",
        "ai_extracted_candidate",
    ),
    (
        "Sheet descrito pelo fabricante como "
        "\u2018Melty Feel Sheet\u2019.",
        "product feature/quality",
        "ai_extracted_candidate",
    ),
    (
        "F\u00f3rmula sem corantes, sem fragr\u00e2ncia, "
        "sem \u00f3leo mineral e sem \u00e1lcool, segundo o fabricante.",
        "ingredients/omissions",
        "ai_extracted_candidate",
    ),
]


BLOCKED_CASES = [
    (
        "O LuLuLun Hydra EX 7 sheets vai em outra dire\u00e7\u00e3o: "
        "\u00e9 um pouch com 7 m\u00e1scaras faciais e 150 mL de "
        "essence, pensado para entrar na sua rotina como sequ\u00eancia, "
        "n\u00e3o como souvenir de farm\u00e1cia.",
        "product composition/format",
        "ai_extracted_candidate",
    ),
    (
        "Em vez de um monte de sach\u00ea perdido na gaveta, voc\u00ea "
        "tem um pacote \u00fanico, organizado, com as 7 folhas ali, "
        "prontas pra alguns dias de cuidado seguido \u2014 quando voc\u00ea "
        "quiser encaixar: manh\u00e3 ou noite.",
        "directions for use / usage pattern",
        "ai_extracted_candidate",
    ),
    (
        "\u00c9 um formato criado pra uso cont\u00ednuo: v\u00e1rias folhas "
        "planejadas no mesmo pacote, em vez de um monte de envelope "
        "avulso espalhado por a\u00ed.",
        "product benefit/effect",
        "copy.pt-BR.caption",
    ),
    (
        "7 folhas no mesmo pouch \u2013 voc\u00ea olha e j\u00e1 visualiza "
        "v\u00e1rios dias de uso, n\u00e3o \u201cuma noite especial\u201d s\u00f3",
        "product composition/format",
        "copy.pt-BR.caption",
    ),
    (
        "o fabricante descreve o tecido como Melty Feel Sheet, "
        "com aquele toque confort\u00e1vel de mask bem feita",
        "product feature/quality",
        "copy.pt-BR.caption",
    ),
    (
        "Em vez de comprar folha por folha no impulso, voc\u00ea tem "
        "7 m\u00e1scaras organizadas em um s\u00f3 pacote LuLuLun Hydra EX.",
        "product benefit/effect",
        "ai_extracted_candidate",
    ),
    (
        "O fabricante indica o uso do sheet mask ajustando ao redor "
        "dos olhos e boca, pressionando suavemente e, ap\u00f3s remover, "
        "seguindo com emulsion ou cream.",
        "directions for use",
        "ai_extracted_candidate",
    ),
    (
        "LuLuLun Hydra EX Mask 7 Sheets: um pacote pensado para "
        "acompanhar v\u00e1rios dias de cuidado, em vez de compras "
        "soltas e aleat\u00f3rias.",
        "product benefit/effect",
        "ai_extracted_candidate",
    ),
]


@pytest.mark.parametrize(
    "text,category,source_field",
    SUPPORTED_CASES,
)
def test_exact_live_canonical_cases_are_supported(
    text,
    category,
    source_field,
):
    assert _status(
        text,
        category,
        source_field,
    ) == "SUPPORTED"


@pytest.mark.parametrize(
    "text,category,source_field",
    BLOCKED_CASES,
)
def test_exact_live_unsupported_residue_remains_blocked(
    text,
    category,
    source_field,
):
    assert _status(
        text,
        category,
        source_field,
    ) == "UNSUPPORTED"


def test_product_benefit_category_remains_fail_closed():
    assert _status(
        "produto pensado para varios dias de resultado",
        "product benefit/effect",
    ) == "UNSUPPORTED"


def test_unknown_ingredient_remains_fail_closed():
    assert _status(
        "formula com retinol",
        "ingredients/contents",
    ) == "UNSUPPORTED"


def test_specific_manufacturer_free_from_phrase_has_no_residue():
    translated = (
        claims_audit
        ._build6r_translate_ptbr_verified_fact_vocabulary_v2(
            (
                "f\u00f3rmula livre de corantes, fragr\u00e2ncia, "
                "\u00f3leo mineral e \u00e1lcool, segundo o fabricante"
            )
        )
    )

    assert (
        translated
        == (
            "manufacturer states the formula is colorant free "
            "fragrance free mineral oil free alcohol free"
        )
    )
