import asyncio
import inspect
from types import SimpleNamespace

import pytest

import app.services.claims_audit as claims_audit


class FakeFinding:
    def __init__(
        self,
        claim_text,
        claim_category,
        source_field="ai_extracted_candidate",
        evidence_status="UNSUPPORTED",
        allowed_source="",
        reason="baseline unsupported",
    ):
        self.claim_text = claim_text
        self.claim_category = claim_category
        self.source_field = source_field
        self.evidence_status = evidence_status
        self.allowed_source = allowed_source
        self.reason = reason

    def model_copy(self, update=None):
        data = {
            "claim_text": self.claim_text,
            "claim_category": self.claim_category,
            "source_field": self.source_field,
            "evidence_status": self.evidence_status,
            "allowed_source": self.allowed_source,
            "reason": self.reason,
        }
        data.update(update or {})
        return FakeFinding(**data)


class FakeResult:
    def __init__(self, findings):
        self.findings = list(findings)

    def model_copy(self, update=None):
        data = {"findings": self.findings}
        data.update(update or {})
        return FakeResult(**data)


def verified():
    return SimpleNamespace(
        verified_description=(
            "LuLuLun Hydra EX facial sheet mask, exact 7-sheet pouch "
            "variant. Manufacturer sales name: Face Mask LuLuLun EX 1FS."
        ),
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
            "Manufacturer describes the sheet as a Melty Feel Sheet",
            "Colorant-free",
            "Fragrance-free",
            "Mineral-oil-free",
            "Alcohol-free",
        ],
        verified_benefits=[],
        verified_usage=(
            "Apply the sheet around the eyes and mouth, press to remove "
            "air, fit the cheek cuts along the face and press with the "
            "palms. After removing, use the folded mask for gentle pats "
            "and follow with emulsion or cream."
        ),
        verified_size="7 sheets / essence 150 mL",
        verified_variant="Face Mask LuLuLun EX 1FS - 7-sheet pouch",
        verified_price=None,
        verified_availability=None,
        verified_country_of_origin=None,
        verified_claims=[
            "7-sheet pouch containing 150 mL of essence",
            (
                "Contains human adipose-derived mesenchymal cell exosomes "
                "as a manufacturer-listed skin-conditioning ingredient; "
                "manufacturer states stem cells are not contained"
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
        prohibited_claims=[
            "Do not claim the product contains stem cells",
            "Do not claim clinical proof",
        ],
        missing_information=[],
    )


LIVE_V328_CASES = [
    ("C01", "LuLuLun Hydra EX 7 Sheets como exemplo concreto de f\u00f3rmula rica em ingredientes nomeados.", "product ingredients/contents", "ai_extracted_candidate", False),
    ("C02", "pouch com 7 sheet masks", "product format/contents", "ai_extracted_candidate", True),
    ("C03", "M\u00e1scara facial tipo sheet (Melty Feel Sheet, descri\u00e7\u00e3o do fabricante)", "product format/description", "ai_extracted_candidate", True),
    ("C04", "Cont\u00e9m exossomos de c\u00e9lulas mesenquimais derivadas de tecido adiposo humano como ingrediente de condicionamento da pele, conforme o fabricante, que tamb\u00e9m afirma que n\u00e3o h\u00e1 c\u00e9lulas-tronco contidas nesse ingrediente", "product ingredients/contents", "ai_extracted_candidate", True),
    ("C05", "Exossomos derivados de c\u00e9lula mesenquimal de gordura humana, listados pelo fabricante como ingrediente de condicionamento da pele. O fabricante informa que esses exossomos n\u00e3o cont\u00eam c\u00e9lulas-tronco", "product ingredients/contents", "ai_extracted_candidate", True),
    ("C06", "Essa sheet mask traz uma lista clara de ingredientes espec\u00edficos, que voc\u00ea consegue ler e pesquisar por conta pr\u00f3pria", "product description", "ai_extracted_candidate", False),
    ("C07", "A pr\u00f3pria embalagem j\u00e1 diz que n\u00e3o tem corante, fragr\u00e2ncia, \u00f3leo mineral nem \u00e1lcool na f\u00f3rmula", "product ingredients/absence", "ai_extracted_candidate", False),
    ("C08", "O tecido \u00e9 descrito pelo fabricante como \u201cMelty Feel Sheet\u201d, ent\u00e3o o tipo de folha tamb\u00e9m \u00e9 uma escolha de projeto, n\u00e3o um detalhe gen\u00e9rico", "product description", "ai_extracted_candidate", False),
    ("C09", "Pressionar para tirar o ar preso", "usage/directions", "ai_extracted_candidate", True),
    ("C10", "Pressionar a m\u00e1scara inteira com as palmas das m\u00e3os para aderir", "usage/directions", "ai_extracted_candidate", True),
    ("C11", "Depois de remover, o fabricante sugere dobrar a m\u00e1scara para usar como pano para leves batidinhas", "usage/directions", "ai_extracted_candidate", True),
    ("C12", "Em seguida, o fabricante sugere finalizar com emuls\u00e3o ou creme", "usage/directions", "ai_extracted_candidate", True),
    ("C13", "Categoria: m\u00e1scara facial em tecido (sheet mask)", "product category", "copy.pt-BR.caption", True),
    ("C14", "Conte\u00fado: 150 mL de ess\u00eancia no total", "product format/contents", "copy.pt-BR.caption", True),
    ("C15", "F\u00f3rmula sem corante, sem fragr\u00e2ncia, sem \u00f3leo mineral e sem \u00e1lcool, de acordo com o fabricante", "product ingredients/absence", "copy.pt-BR.caption", True),
    ("C16", "Exossomos derivados de c\u00e9lula mesenquimal de gordura humana, listados como ingrediente de condicionamento da pele; o pr\u00f3prio fabricante informa que esses exossomos n\u00e3o cont\u00eam c\u00e9lulas\u2011tronco", "product ingredients/contents", "copy.pt-BR.caption", True),
    ("C17", "Foto editorial da embalagem LuLuLun Hydra EX Mask 7 Sheets de frente, em close, sobre fundo limpo e claro", "imagery depiction", "copy.pt-BR.alt_text", True),
    ("C18", "A pouch est\u00e1 em p\u00e9, com o logo LuLuLun e o nome Hydra EX n\u00edtidos", "imagery depiction", "copy.pt-BR.alt_text", True),
    ("C19", "gotas de ess\u00eancia sugerindo os 150 mL presentes no pacote", "product format/contents", "copy.pt-BR.alt_text", True),
    ("C20", "texto \u201ccolorant-free, fragrance-free, mineral-oil-free, alcohol-free\u201d reproduzido da embalagem", "product ingredients/absence", "copy.pt-BR.alt_text", False),
    ("C21", "Inclui exossomos de c\u00e9lulas mesenquimais derivadas de tecido adiposo humano como ingrediente de condicionamento da pele, sem c\u00e9lulas-tronco, conforme o fabricante", "product ingredients/contents", "ai_extracted_candidate", True),
]


def reconcile(text, category, source="ai_extracted_candidate"):
    result = FakeResult(
        [
            FakeFinding(
                text,
                category,
                source,
            )
        ]
    )
    return (
        claims_audit
        ._build6r_v329_reconcile_live_taxonomy(
            result,
            verified(),
            {},
        )
        .findings[0]
    )


@pytest.mark.parametrize(
    "claim_id,text,category,source,expected_supported",
    LIVE_V328_CASES,
)
def test_exact_v328_live_failure_matrix(
    claim_id,
    text,
    category,
    source,
    expected_supported,
):
    finding = reconcile(
        text,
        category,
        source,
    )
    assert (
        finding.evidence_status == "SUPPORTED"
    ) is expected_supported, claim_id


def test_exact_live_matrix_has_21_cases_with_16_supported_and_5_blocked():
    assert len(LIVE_V328_CASES) == 21
    assert sum(1 for *_, expected in LIVE_V328_CASES if expected) == 16
    assert sum(1 for *_, expected in LIVE_V328_CASES if not expected) == 5


def test_wrong_live_quantity_remains_fail_closed():
    finding = reconcile(
        "Conteudo: 200 mL de essencia no total",
        "product format/contents",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_unknown_live_ingredient_remains_fail_closed():
    finding = reconcile(
        "A formula contem glutationa e niacinamida",
        "product ingredients/contents",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_exosome_without_same_field_safety_remains_fail_closed():
    finding = reconcile(
        (
            "Exossomos derivados de celula mesenquimal de gordura humana, "
            "listados como ingrediente de condicionamento da pele"
        ),
        "product ingredients/contents",
    )
    assert finding.evidence_status == "UNSUPPORTED"


@pytest.mark.parametrize(
    "text",
    [
        "A propria embalagem ja diz que nao tem corante nem alcool",
        (
            "texto colorant-free, fragrance-free, mineral-oil-free, "
            "alcohol-free reproduzido da embalagem"
        ),
    ],
)
def test_package_provenance_invention_remains_fail_closed(text):
    finding = reconcile(
        text,
        "product ingredients/absence",
    )
    assert finding.evidence_status == "UNSUPPORTED"


@pytest.mark.parametrize(
    "text",
    [
        "Produto clinicamente comprovado para clareamento",
        "Produto superior a outras sheet masks",
        "Preco especial com desconto",
        "Estoque limitado e restock garantido",
        "Guia internacional recomenda este produto",
    ],
)
def test_protected_factual_families_remain_fail_closed(text):
    finding = reconcile(
        text,
        "product category",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_imagery_wrong_quantity_remains_fail_closed():
    finding = reconcile(
        "gotas de essencia sugerindo os 200 mL presentes no pacote",
        "imagery depiction",
        "copy.pt-BR.alt_text",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_imagery_unknown_result_residue_remains_fail_closed():
    finding = reconcile(
        "foto do pouch com pele radiante e resultado anti aging",
        "imagery depiction",
        "copy.pt-BR.alt_text",
    )
    assert finding.evidence_status == "UNSUPPORTED"


def test_unique_verbatim_ai_candidate_recovers_source_then_reconciles():
    result = FakeResult(
        [
            FakeFinding(
                "Conteudo: 150 mL de essencia no total",
                "product format/contents",
            )
        ]
    )
    fields = {
        "copy.pt-BR.caption":
            "Conteudo: 150 mL de essencia no total"
    }
    recovered = (
        claims_audit
        ._build6r_v329_enforce_ai_candidate_faithfulness(
            result,
            fields,
            enabled=True,
        )
    )
    assert len(recovered.findings) == 1
    assert (
        recovered.findings[0].source_field
        == "copy.pt-BR.caption"
    )
    reconciled = (
        claims_audit
        ._build6r_v329_reconcile_live_taxonomy(
            recovered,
            verified(),
            fields,
        )
    )
    assert reconciled.findings[0].evidence_status == "SUPPORTED"


def test_unfaithful_ai_paraphrase_is_discarded_not_promoted_or_hard_failed():
    result = FakeResult(
        [
            FakeFinding(
                "pouch com 7 sheet masks",
                "product format/contents",
            )
        ]
    )
    filtered = (
        claims_audit
        ._build6r_v329_enforce_ai_candidate_faithfulness(
            result,
            {
                "copy.pt-BR.caption":
                    "Conteudo: 150 mL de essencia no total"
            },
            enabled=True,
        )
    )
    assert filtered.findings == []


def test_ambiguous_verbatim_ai_candidate_remains_synthetic_and_fail_closed():
    result = FakeResult(
        [
            FakeFinding(
                "Conteudo: 150 mL de essencia no total",
                "product format/contents",
            )
        ]
    )
    fields = {
        "copy.pt-BR.caption":
            "Conteudo: 150 mL de essencia no total",
        "copy.pt-BR.body":
            "Conteudo: 150 mL de essencia no total",
    }
    filtered = (
        claims_audit
        ._build6r_v329_enforce_ai_candidate_faithfulness(
            result,
            fields,
            enabled=True,
        )
    )
    assert len(filtered.findings) == 1
    assert (
        filtered.findings[0].source_field
        == "ai_extracted_candidate_ambiguous"
    )
    reconciled = (
        claims_audit
        ._build6r_v329_reconcile_live_taxonomy(
            filtered,
            verified(),
            fields,
        )
    )
    assert reconciled.findings[0].evidence_status == "UNSUPPORTED"


def test_v329_wrapper_executes_v328_chain_once_and_enforces_faithfulness(
    monkeypatch,
):
    calls = []

    class ProviderShape:
        async def generate_structured(self, *args, **kwargs):
            raise AssertionError("sealed previous chain should own provider call")

    async def previous(*args, **kwargs):
        calls.append("previous")
        return FakeResult(
            [
                FakeFinding(
                    "Conteudo: 150 mL de essencia no total",
                    "product format/contents",
                ),
                FakeFinding(
                    "synthetic paraphrase not present in fields",
                    "product format/contents",
                ),
            ]
        )

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v329",
        previous,
    )

    result = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            ProviderShape(),
            fields={
                "copy.pt-BR.caption":
                    "Conteudo: 150 mL de essencia no total"
            },
            verified=verified(),
            brand=None,
            model="zero-cost-test",
            existing=FakeResult([]),
        )
    )

    assert calls == ["previous"]
    assert len(result.findings) == 1
    assert (
        result.findings[0].source_field
        == "copy.pt-BR.caption"
    )
    assert (
        result.findings[0].evidence_status
        == "SUPPORTED"
    )


def test_v329_faithfulness_disabled_preserves_identity():
    result = FakeResult(
        [
            FakeFinding(
                "synthetic historical candidate",
                "product format/contents",
            )
        ]
    )

    returned = (
        claims_audit
        ._build6r_v329_enforce_ai_candidate_faithfulness(
            result,
            {
                "copy.pt-BR.caption":
                    "different source text"
            },
            enabled=False,
        )
    )

    assert returned is result


def test_v329_faithfulness_empty_result_preserves_identity():
    result = FakeResult([])

    returned = (
        claims_audit
        ._build6r_v329_enforce_ai_candidate_faithfulness(
            result,
            {
                "copy.pt-BR.caption":
                    "source text"
            },
            enabled=True,
        )
    )

    assert returned is result


@pytest.mark.parametrize(
    "category",
    [
        "product benefits/effects",
        "product identification",
        "format_or_quantity",
        "ingredients_or_composition",
        "product_format_or_quantity",
        "ingredients_contents",
    ],
)
def test_v329_faithfulness_does_not_reinterpret_sealed_historical_categories(
    category,
):
    finding = FakeFinding(
        "historical synthetic fixture",
        category,
    )
    result = FakeResult([finding])

    returned = (
        claims_audit
        ._build6r_v329_enforce_ai_candidate_faithfulness(
            result,
            {
                "copy.pt-BR.caption":
                    "different text"
            },
            enabled=True,
        )
    )

    assert returned is result
    assert returned.findings[0] is finding


def test_v329_wrapper_with_no_provider_preserves_previous_empty_result_identity(
    monkeypatch,
):
    original = FakeResult([])

    async def previous(*args, **kwargs):
        return original

    monkeypatch.setattr(
        claims_audit,
        "_build6r_augment_before_v329",
        previous,
    )

    returned = asyncio.run(
        claims_audit.augment_with_ai_extraction(
            None,
            fields={
                "copy.pt-BR.caption":
                    "source text"
            },
            verified=verified(),
            brand=None,
            model="zero-cost-test",
            existing=FakeResult([]),
        )
    )

    assert returned is original


def test_v329_wrapper_preserves_varargs_contract_and_historical_markers():
    signature = str(
        inspect.signature(
            claims_audit.augment_with_ai_extraction
        )
    )
    assert signature == "(*args, **kwargs)"

    source = inspect.getsource(
        claims_audit.augment_with_ai_extraction
    )
    for marker in (
        "_build6r_augment_before_v324",
        "_build6r_v324_reconcile_residual_canonical_semantic_atoms",
        "_build6r_augment_before_v325",
        "_build6r_v325_reconcile_bounded_usage_and_nonfactual_directives",
        "_build6r_augment_before_v326",
        "_build6r_v326_reconcile_residual_taxonomy_and_nonclaims",
        "_build6r_augment_before_v327",
        "_build6r_v327_reconcile_usage_ingredients_and_meta_provenance",
        "_build6r_augment_before_v328",
        "_build6r_v328_reconcile_live_taxonomy",
        "_build6r_augment_before_v329",
        "_build6r_v329_enforce_ai_candidate_faithfulness",
        "_build6r_v329_reconcile_live_taxonomy",
    ):
        assert marker in source


def test_v329_production_layer_is_product_agnostic_zero_cost():
    source = inspect.getsource(claims_audit)
    marker = "BUILD6R_V329_LIVE_CLAIM_TAXONOMY_AUDITOR_PROVENANCE_HARDENING"
    tail = source[source.index(marker):].lower()

    for forbidden in (
        "lululun",
        "hydra",
        "campaign_id",
        "product_id",
        "openai",
        "httpx.",
        "requests.",
        "sqlite3",
        "rapidfuzz",
        "difflib",
        "sequencematcher",
        "embedding",
        "cosine",
        "generate_structured(",
        "generate_image(",
        "edit_image(",
    ):
        assert forbidden not in tail
