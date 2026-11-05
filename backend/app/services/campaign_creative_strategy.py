"""Deterministic campaign strategy -> premium external creative planning bridge.

Reuses canonical tactic IDs, archetypes and V12.4 exact-wording/provenance checks.
No models, DB sessions, rendering, external requests or commercial-import checks.
"""
from ..data.strategy_library import STRATEGY_TYPES
from ..data.campaign_archetypes import CAMPAIGN_ARCHETYPES
from ..schemas.campaign_creative_strategy import CampaignCreativeStrategyRequest
from ..schemas.creative_bridge import CopyField
from .marketing_claims import USABLE, resolve_copy, normalized

TACTICS = {t['key']: t for t in STRATEGY_TYPES}
QUALITY_GATE = ('premium_quality', 'product_fidelity', 'typography_hierarchy',
                'scene_integration', 'brand_cohesion', 'postability')
# Profiles adapt existing tactics; these are NOT new tactic IDs or seed rows.
PROFILES = {
    'educational_campaign': ('education', 'feature_demo'),
    'product_selection': ('guide', 'variant_choice'),
    'competitor_comparison': ('comparison', 'variant_choice'),
    'counter_marketing': ('comparison', 'variant_choice'),
    'cultural_campaign': ('story', 'origin_story'),
    'japan_experience': ('story', 'origin_story'),
    'storytelling_campaign': ('story', 'origin_story'),
    'problem_solution_campaign': ('benefit', 'problem_solution'),
    'discovery_campaign': ('discovery', 'premium_discovery'),
    'paid_ads': ('conversion', 'sensory_experience'),
}
SEQUENCES = {
    'benefit': (('tactile_proposition', 'core_benefits', 'sheet_construction', 'formula_pack', 'routine_decision_cta'),
                ('product_identity', 'hydration', 'qualified_radiance', 'tactile_experience', 'sheet_construction', 'selected_formula', 'formulation_choice', 'application', 'routine_aftercare', 'learning_cta')),
    'education': (('tactile_proposition', 'sheet_construction', 'core_benefits', 'formula_pack', 'routine_decision_cta'),
                  ('product_identity', 'hydration', 'qualified_radiance', 'tactile_experience', 'sheet_construction', 'selected_formula', 'formulation_choice', 'application', 'routine_aftercare', 'learning_cta')),
    'guide': (('selection_question', 'selection_criteria', 'technology', 'usage', 'decision_cta'),
              ('selection_question', 'selection_criteria', 'principal_benefit', 'secondary_benefit', 'technology', 'formula', 'ingredients', 'usage', 'pack', 'decision_cta')),
    'story': (('story_hook', 'origin', 'technology', 'principal_benefit', 'discovery_cta'),
              ('story_hook', 'origin', 'context', 'technology', 'sheet_detail', 'formula', 'ingredients', 'principal_benefit', 'usage', 'discovery_cta')),
    'discovery': (('discovery_hook', 'principal_benefit', 'technology', 'pack', 'discovery_cta'),
                  ('discovery_hook', 'context', 'principal_benefit', 'secondary_benefit', 'technology', 'sheet_detail', 'formula', 'usage', 'pack', 'discovery_cta')),
    'conversion': (('desire_hook', 'principal_benefit', 'proof', 'pack', 'decision_cta'),
                   ('desire_hook', 'context', 'principal_benefit', 'secondary_benefit', 'proof', 'technology', 'formula', 'usage', 'pack', 'decision_cta')),
    'comparison': (('comparison_scope', 'criterion', 'verified_contrast', 'proof', 'decision_cta'),
                   ('comparison_scope', 'criterion', 'principal_benefit', 'technology', 'formula', 'verified_contrast', 'proof', 'usage', 'pack', 'decision_cta')),
}
ROLE_CATEGORY = {'context': 'secondary_benefit', 'selection_criteria': 'principal_benefit',
                 'sheet_detail': 'differentiation', 'ingredients': 'formula', 'criterion': 'differentiation',
                 'verified_contrast': 'differentiation'}


def tactic_inventory():
    return {'tactics': [dict(t) for t in STRATEGY_TYPES],
            'archetypes': {k: {'purpose': v.purpose, 'visual_logic': v.visual_logic}
                           for k, v in CAMPAIGN_ARCHETYPES.items()}}


def _claim(library, claim_id):
    matches = [c for c in library.claims if c.claim_id == claim_id]
    if len(matches) != 1:
        raise ValueError('Unknown/duplicate exact-product claim ID')
    c = matches[0]
    if c.claim_class not in USABLE or c.review_status != 'APPROVED' or c.language_review != 'VERIFIED':
        raise ValueError('Unapproved claim cannot enter strategy output')
    return c


def _wording(library, claim_id):
    c = _claim(library, claim_id)
    text = c.approved_pt_br_wording.get('STANDARD') or c.approved_pt_br_wording.get('SHORT')
    if not text:
        raise ValueError('No exact reviewed wording')
    if c.mandatory_qualifier and normalized(c.mandatory_qualifier) not in normalized(text):
        raise ValueError('Selected wording lacks mandatory qualifier')
    return text


def _profile(request):
    if request.tactic_key not in TACTICS:
        raise ValueError('Select an existing canonical tactic key')
    # Operational tactics need real offer/customer/competitor evidence; this
    # product-library-only bridge must not fabricate discounts, stock or quotes.
    if request.tactic_key not in PROFILES:
        raise ValueError('Tactic requires additional operational evidence/adapter; no generic fallback')
    return PROFILES[request.tactic_key]


def recommend_tactics(request, library):
    """Evidence-aware, stable ranking; never random rotation or auto-selection."""
    categories = {c.category for c in request.coverage if c.relevant}
    suggestions = []
    for key, (profile, _) in PROFILES.items():
        if profile == 'comparison' or (profile == 'story' and 'origin' not in categories):
            continue
        score = 0
        reasons = []
        if request.objective in ('education', 'authority') and profile == 'education':
            score += 4; reasons.append('education/authority objective')
        if request.objective in ('awareness', 'discovery') and profile == 'discovery':
            score += 4; reasons.append('discovery/awareness objective')
        if request.funnel_stage == 'conversion' and profile == 'conversion':
            score += 4; reasons.append('conversion funnel')
        if request.product_novelty == 'new' and profile == 'discovery':
            score += 2; reasons.append('new product needs introduction')
        if request.complexity == 'high' and profile == 'education':
            score += 2; reasons.append('complexity needs explanation')
        if request.objections and profile == 'guide':
            score += 2; reasons.append('decision questions need a buying guide')
        if profile == 'benefit' and any(_claim(library, c.claim_id).evidence_scope == 'PRODUCT_BENEFIT'
                                      for c in request.coverage if c.relevant):
            score += 2; reasons.append('verified finished-product benefit available')
        uses = sum(h.tactic_key == key for h in request.history)
        score -= uses
        reasons.append(f'{uses} prior supplied uses; history is caller-provided')
        suggestions.append({'tactic_key': key, 'score': score, 'rationale': reasons})
    return sorted(suggestions, key=lambda t: (-t['score'], t['tactic_key']))


def composition_for_purpose(role, message):
    """Existing families selected by communication job, never position in a deck.

    This is a proposal, not permission to depict product behavior or materials.
    Unknown roles require preparation rather than a generic fallback.
    """
    if not message.strip():
        raise ValueError('A concrete approved message is required')
    routine = {'usage', 'application', 'routine_aftercare', 'routine_decision_cta', 'routine_fit', 'application_action'}
    detail = {'sheet_construction', 'sheet_detail', 'technology', 'formula_pack', 'selected_formula',
              'formulation_choice', 'formula', 'ingredients', 'proof', 'pack', 'origin',
              'selection_criteria', 'criterion', 'verified_contrast', 'comparison_scope'}
    hero = {'cover', 'cta', 'product_identity', 'hydration', 'qualified_radiance', 'tactile_experience',
            'tactile_proposition', 'core_benefits', 'principal_benefit', 'secondary_benefit', 'context',
            'selection_question', 'question', 'story_hook', 'discovery_hook', 'desire_hook',
            'decision_cta', 'discovery_cta', 'learning_cta', 'single_message_cta', 'story_cta',
            'benefit', 'ad_cta', 'video_cta', 'material_motion_hook', 'tactile_handling', 'product_reveal'}
    if role in routine:
        family = 'ritual_context'
        mechanism = ('Place the exact pouch on a real supporting surface; motivated warm/cool light '
                     'communicates routine context while the approved usage copy carries the instruction. '
                     'No simulated application or product performance demonstration.')
    elif role in detail:
        family = 'editorial_detail'
        mechanism = ('Pair the exact pouch with an editorial hierarchy of the supplied factual copy; '
                     'use controlled geometric accents to connect the information to the hero. '
                     'Do not visualize ingredients, physical layers or efficacy as evidence.')
    elif role in hero:
        family = 'product_hero'
        mechanism = ('Ground the exact pouch as the dominant subject; direct the light and copy reading '
                     'path toward it, with supporting text subordinate to the product. '
                     'Communicate the benefit through approved copy, not invented results.')
    else:
        raise ValueError(f'Unprepared communication purpose: {role}')
    return {'composition_family': family, 'communication_objective': message,
            'visual_mechanism': mechanism,
            'composition_rationale': f'{family} supports the {role} communication job and its approved message',
            'owner_review_status': 'PENDING'}


def plan_campaign(request: CampaignCreativeStrategyRequest, library, *, execution_contract=False):
    if request.product_id != library.product_id:
        raise ValueError('Exact-product strategy/library mismatch')
    profile, archetype = _profile(request)
    requested = {request.hook_claim_id, request.primary_claim_id, request.cta_claim_id,
                 *request.secondary_claim_ids, *request.proof_claim_ids,
                 *request.funnel_cta_claim_ids.values(),
                 *(c.claim_id for c in request.coverage)}
    for key in requested:
        _wording(library, key)
    if _claim(library, request.cta_claim_id).evidence_scope != 'EDITORIAL':
        raise ValueError('CTA must be reviewed editorial wording')
    if profile == 'comparison':
        raise ValueError('Comparative campaign requires separately reviewed counterpart/metric evidence; no inferred comparison')
    relevant = [c for c in request.coverage if c.relevant]
    if not relevant or request.primary_claim_id not in {c.claim_id for c in relevant}:
        raise ValueError('Primary proposition must be represented in relevant coverage')
    suggestions = recommend_tactics(request, library)
    layout = CAMPAIGN_ARCHETYPES[archetype].visual_logic
    layout_families = ('product_hero', 'editorial_detail', 'material_closeup', 'ritual_context', 'negative_space_caption')

    def asset(fmt, index, role, ids, *, hook=None, angle=None, execution=None, time=None, cta_id=None):
        ids = list(dict.fromkeys(ids))
        if not ids:
            raise ValueError('Role has no verified information; choose a supported tactic/coverage')
        fields = tuple(CopyField(key=f'copy_{n}', text=_wording(library, cid)) for n, cid in enumerate(ids))
        bindings = resolve_copy(library, fields)
        if set(bindings.values()) != set(ids):
            raise ValueError('Copy/claim binding is ambiguous')
        q = {cid: _claim(library, cid).mandatory_qualifier for cid in ids if _claim(library, cid).mandatory_qualifier}
        return {'asset_id': f'{fmt}:{index}', 'format': fmt, 'role': role,
                'tactic': request.tactic_key, 'objective': request.objective,
                'audience': request.audience, 'funnel_stage': request.funnel_stage,
                'angle': angle or request.angle, 'hook': _wording(library, hook or request.hook_claim_id),
                'hook_claim_id': hook or request.hook_claim_id,
                'primary_message': _wording(library, ids[0]),
                'secondary_messages': [_wording(library, c) for c in ids[1:]],
                'approved_copy': {f.key: f.text for f in fields}, 'approved_claim_ids': bindings,
                'mandatory_qualifiers': q, 'product_information_to_show': ids,
                'proof': [{'claim_id': c, 'source': _claim(library, c).source_reference,
                           'scope': _claim(library, c).evidence_scope} for c in ids],
                'cta': _wording(library, cta_id or request.cta_claim_id) if role.endswith('cta') or 'STATIC' in fmt or fmt == 'META_PAID_SOCIAL' else '',
                'cta_claim_id': cta_id or request.cta_claim_id,
                'visual_priority': ['product fidelity', role, 'clear hierarchy', 'restrained supporting detail'],
                'visual_intent': layout + '; ' + (execution or layout_families[(index - 1) % len(layout_families)]),
                'layout_family': execution or layout_families[(index - 1) % len(layout_families)],
                'visual_benchmark': request.visual_benchmark, 'benchmark_layout_locked': False,
                'benchmark_quality_locked': True, 'benchmark_is_approval_evidence': False,
                'prohibited_wording': sorted(set(library.prohibited_language).union(
                    p for cid in ids for p in _claim(library, cid).prohibited_variants)),
                'quality_gate': list(QUALITY_GATE), 'owner_review_status': 'PENDING',
                'output_size': [1080, 1920] if fmt in ('INSTAGRAM_STORIES', 'REEL_SHORT_VIDEO') else [1080, 1350],
                'time_seconds': time, 'creation_source': 'external_chatgpt_creative_workflow'}

    def pick(category, index=0):
        # Prepared information keys carry the job; array order must never turn
        # routine wording into an application instruction or swap benefit roles.
        semantic_keys = {'secondary_benefit': ('softness', 'radiance'),
                         'usage': ('daily', 'toner', 'application', 'after')}
        if category in semantic_keys:
            key = semantic_keys[category][index]
            match = next((c.claim_id for c in relevant if c.category == category and c.key == key), None)
            if match is None:
                raise ValueError(f'Missing prepared information job {category}/{key}')
            return match
        choices = [c.claim_id for c in relevant if c.category == category]
        if index >= len(choices):
            raise ValueError(f'Missing reviewed information for {category}:{index}')
        return choices[index]

    def for_role(role, count):
        repaired = {
            'tactile_proposition': lambda: [pick('secondary_benefit'), request.hook_claim_id],
            'core_benefits': lambda: [request.primary_claim_id, pick('secondary_benefit', 1)],
            'sheet_construction': lambda: [pick('differentiation'), pick('technology')],
            'formula_pack': lambda: [pick('formula'), pick('pack')],
            'routine_decision_cta': lambda: [pick('usage'), pick('usage', 1), request.cta_claim_id],
            'product_identity': lambda: [pick('pack'), request.hook_claim_id],
            'hydration': lambda: [request.primary_claim_id],
            'qualified_radiance': lambda: [pick('secondary_benefit', 1)],
            'tactile_experience': lambda: [pick('secondary_benefit')],
            'selected_formula': lambda: [pick('formula')],
            'formulation_choice': lambda: [pick('proof')],
            'application': lambda: [pick('usage', 2)],
            'routine_aftercare': lambda: [pick('usage'), pick('usage', 1), pick('usage', 3)],
            'learning_cta': lambda: [request.cta_claim_id],
        }
        if role in repaired:
            return repaired[role]()
        if role.endswith('cta'):
            return [request.primary_claim_id, request.cta_claim_id]
        if 'hook' in role or role in ('question', 'selection_question'):
            return [request.hook_claim_id, request.primary_claim_id]
        if role == 'proof':
            return list(request.proof_claim_ids)
        cat = ROLE_CATEGORY.get(role, role)
        matches = [c.claim_id for c in relevant if c.category == cat]
        # Deliberately select a small subset for short-form. Coverage measures
        # the actual IDs used rather than assigning invisible/unrendered facts.
        if matches:
            if role == 'principal_benefit' and count == 5 and profile == 'benefit':
                return matches[:1] + list(request.secondary_claim_ids[:2])
            if role == 'ingredients' and len(matches) > 2:
                return matches[2:4]
            return matches[:2 if count >= 10 else 1]
        if role == 'secondary_benefit' and request.secondary_claim_ids:
            return list(request.secondary_claim_ids[:1])
        raise ValueError(f'No evidence for selected tactic role: {role}')

    formats = {}
    for fmt in request.formats:
        if fmt.startswith('INSTAGRAM_CAROUSEL'):
            count = 5 if fmt.endswith('_5') else 10
            roles = SEQUENCES[profile][0 if count == 5 else 1]
            assets = [asset(fmt, i, role, for_role(role, count)) for i, role in enumerate(roles, 1)]
            seen = set()
            for a in assets:
                ids = list(a['approved_claim_ids'].values())
                new_ids = set(ids) - seen
                a.update(primary_information_job=a['role'],
                         incremental_value='HIGH' if len(new_ids) > 1 else 'MEDIUM' if new_ids else 'LOW',
                         incremental_value_reason=f"Adds {', '.join(sorted(new_ids)) or 'no new information'}; job={a['role']}",
                         secondary_message_treatment='Subordinate caption; never equal weight to the primary communication job')
                if not new_ids:
                    a['narrative_reason'] = 'Requires review: repeated information without a unique learning or decision job'
                seen.update(ids)
        elif fmt in ('INSTAGRAM_STATIC', 'FACEBOOK_STATIC'):
            # One proposition, plus an editorial CTA. No product-page collage.
            assets = [asset(fmt, 1, 'single_message_cta', [request.primary_claim_id, request.cta_claim_id],
                            execution='mobile_product_hero' if fmt == 'INSTAGRAM_STATIC' else 'feed_context_hero')]
        elif fmt == 'INSTAGRAM_STORIES':
            roles = [('story_hook', [request.hook_claim_id]), ('benefit', [request.primary_claim_id]),
                     ('proof', list(request.proof_claim_ids[:1])), ('story_cta', [request.cta_claim_id])]
            if request.complexity == 'high':
                roles.insert(3, ('usage', for_role('usage', 5)))
            assets = [asset(fmt, i, role, ids, execution='vertical_tap_progression')
                      for i, (role, ids) in enumerate(roles, 1)]
        elif fmt == 'REEL_SHORT_VIDEO':
            roles = [
                ('material_motion_hook', [pick('differentiation')], (0, 3), 'A wet sheet unfolds across frame beside the canonical pouch; immediate mask recognition, no static title card.', 'Match the unfolding movement to the product reveal.'),
                ('product_identity', [pick('pack')], (3, 8), 'Camera pulls back from sheet to the exact pouch and its quantity marking; show the complete product.', 'Cut from pack identification to the moisturizing proposition.'),
                ('hydration', [request.primary_claim_id], (8, 12), 'One restrained water ripple meets the grounded pouch; communicate cosmetic hydration without a before/after result.', 'Sound bridge from water to the tactile fabric close-up.'),
                ('tactile_experience', [pick('secondary_benefit')], (12, 17), 'Hands gently unfold and handle the sheet; macro texture moves in focus, with pouch visible at frame edge.', 'Match hand movement into the application step.'),
                ('application', [pick('usage', 2)], (17, 26), 'Demonstrate unfolding and adjusting around eyes and mouth with a faithful product shot inset; no fabricated skin transformation.', 'Complete the action before a deliberate product close.'),
                ('video_cta', [request.cta_claim_id], (26, 30), 'Return to a stable premium pouch hero and the reviewed CTA; leave room for the separately confirmed destination.', 'Hold the end frame long enough to read the CTA.'),
            ]
            assets = []
            for i, (role, ids, timing, action, transition) in enumerate(roles, 1):
                a = asset(fmt, i, role, ids, execution=action, time=list(timing))
                a.update(first_seconds_visual=action if i == 1 else '',
                         required_product_shot=role, voiceover=list(a['approved_copy'].values()),
                         on_screen_copy=a['approved_copy'], transitions=transition,
                         scene_purpose=role, visual_action=action, product_visibility=True,
                         voiceover_or_audio_role='Read exact approved copy; restrained fabric/water foley, no added slogan',
                         transition_reason=transition,
                         estimated_voiceover_wpm=round(60 * sum(len(t.split()) for t in a['approved_copy'].values()) / (timing[1] - timing[0])))
                assets.append(a)
        else:  # META_PAID_SOCIAL: separate angle/hook/execution axes, no images.
            if set(request.funnel_cta_claim_ids) != {'awareness', 'consideration', 'conversion'}:
                raise ValueError('Paid plan requires explicit reviewed CTA choices for all three funnel policies')
            for cid in request.funnel_cta_claim_ids.values():
                if _claim(library, cid).evidence_scope != 'EDITORIAL':
                    raise ValueError('Funnel CTA must be reviewed editorial wording')
            candidates = [
                ('primary_benefit', request.primary_claim_id, (request.primary_claim_id, pick('secondary_benefit', 1)),
                 ('awareness', 'consideration'), ('Hydration interest', 'Dryness-related appearance concern'),
                 ('Grounded pouch in one restrained water reflection; hydration text is the sole visual proposition.', 'Editorial dryness-context caption paired with the complete qualified radiance wording; no altered skin or before/after comparison.')),
                ('differentiation', pick('differentiation'), (pick('differentiation'), pick('usage', 1)),
                 ('consideration', 'consideration'), ('Understand material construction', 'Understand routine substitution'),
                 ('Product-detail construction story: faithful pouch beside a clearly illustrative three-layer material diagram, not a clinical result.', 'Routine editorial sequence: show where the mask enters the care ritual; product and exact toner-replacement wording lead.')),
                ('secondary_benefit', pick('secondary_benefit'), (pick('secondary_benefit'), pick('usage', 2)),
                 ('awareness', 'consideration'), ('Seek a pleasant tactile experience', 'See how manageable application is'),
                 ('Sensory fabric handling: hands unfolding a soft wet sheet near the canonical pouch; no fabricated efficacy demonstration.', 'Step-led application editorial: exact unfolding/eye-and-mouth adjustment action with generous negative space, not another static pack hero.')),
                ('formula', pick('formula'), (pick('formula'), pick('proof')),
                 ('consideration', 'conversion'), ('Explore named ingredients', 'Check a formulation preference before choosing'),
                 ('Ingredient-presence editorial: exact named-ingredient captions around a faithful pouch; no molecular efficacy diagram.', 'Decision-led product detail: formulation fact and verified pack quantity near a clean pouch hero; no unverified price or urgency.')),
            ]
            assets = []
            for angle, cid, hooks, stages, motivations, concepts in candidates:
                if len(set(hooks)) != 2:
                    raise ValueError('Paid hook entry points require different evidence, not duplicate wording')
                for hi, hook_id in enumerate(hooks):
                    stage = stages[hi]
                    cta = request.funnel_cta_claim_ids[stage]
                    for ei, execution in enumerate(concepts):
                        # Both execution families remain compatible with either
                        # hook: only their communication mode changes in a pair.
                        # Both modes get the same factual payload. Order changes
                        # only for the independently specified hook entry point.
                        ids = [hook_id, cid, *hooks, cta]
                        if stage == 'conversion' or angle == 'formula':
                            ids.append(pick('pack'))
                        a = asset(fmt, len(assets) + 1, 'ad_cta', ids,
                                  hook=hook_id, angle=angle, execution=execution, cta_id=cta)
                        a.update(angle_id=angle, hook_claim_id=hook_id, visual_execution=execution,
                                 visual_concept=execution,
                                 customer_motivation=motivations[hi], funnel_stage=stage,
                                 audience=request.audience + '; motivation segment: ' + motivations[hi],
                                 funnel_behavior={'awareness': 'Immediate category recognition and low-friction discovery', 'consideration': 'Show evidence and practical differentiation before a details visit', 'conversion': 'Help a product-aware shopper choose using formulation and pack facts; product-detail/purchase-options destination'}[stage],
                                 destination_intent={'awareness': 'product introduction', 'consideration': 'exact-product evidence/details', 'conversion': 'exact-product details and purchase options'}[stage],
                                 destination_status='OWNER_CONFIGURATION_REQUIRED; no live URL or purchase availability asserted',
                                 primary_benefit=_wording(library, cid),
                                 what_is_being_tested=f'Within {stage} and motivation {motivations[hi]}, test communication mode A versus B for the same {hook_id} hook. Compare hooks across stages descriptively only; not a causal hook A/B test.',
                                 hook_test_design='Hook entry point and funnel/motivation are intentionally paired; hold both fixed for the execution A/B test',
                                 hypothesis=f'{angle}: {motivations[hi]} entry point with execution {ei + 1}; no ROAS guarantee',
                                 production_priority='PRIORITY_1' if hi == 0 else 'PRIORITY_2' if angle in ('primary_benefit', 'formula') else 'PRIORITY_3',
                                 initial_test_set=(hi == 0),
                                 recommended_formats=['INSTAGRAM_STATIC', 'FACEBOOK_STATIC', 'INSTAGRAM_STORIES'],
                                 measurement=['outbound CTR', 'landing-page conversion', 'ROAS after sufficient attributable purchases'])
                        assets.append(a)
        if execution_contract:
            for a in assets:
                proposal = composition_for_purpose(a['role'], a['primary_message'])
                a['execution_proposal'] = proposal
                a['layout_family'] = proposal['composition_family']
                a['visual_intent'] = proposal['visual_mechanism']
                # Do not leak legacy material/action concepts into the new safe
                # execution proposal. Visible copy and timing remain untouched.
                for field in ('visual_execution', 'visual_concept', 'visual_action'):
                    if field in a:
                        a[field] = proposal['visual_mechanism']
                if 'voiceover_or_audio_role' in a:
                    a['voiceover_or_audio_role'] = 'Read exact approved copy; no simulated product/material sounds'
                    a['first_seconds_visual'] = proposal['visual_mechanism'] if a['time_seconds'][0] == 0 else ''
                    a['transitions'] = a['transition_reason'] = 'Motivated change of framing around the same exact product; no material demonstration'
        used = {c for a in assets for c in a['approved_claim_ids'].values()}
        coverage = []
        for c in request.coverage:
            assignments = [a['asset_id'] for a in assets if c.claim_id in a['approved_claim_ids'].values()]
            coverage.append({**c.model_dump(), 'used_in_campaign': bool(assignments),
                             'assigned_format': fmt if assignments else None,
                             'assigned_slide_or_asset': assignments,
                             'omission_reason': c.omission_reason or ('' if assignments else 'Intentionally omitted to respect tactic role and format density')})
        denominator = sum(c.relevant for c in request.coverage)
        numerator = sum(c.relevant and c.claim_id in used for c in request.coverage)
        high = [c for c in request.coverage if c.relevant and c.priority in ('PRIMARY', 'SECONDARY')]
        high_used = sum(c.claim_id in used for c in high)
        formats[fmt] = {'assets': assets, 'coverage': coverage,
                        'coverage_percent': round(100 * numerator / denominator, 2),
                        'coverage_numerator': numerator, 'coverage_denominator': denominator,
                        'high_priority_coverage_percent': round(100 * high_used / len(high), 2) if high else None,
                        'high_priority_numerator': high_used, 'high_priority_denominator': len(high),
                        'high_priority_definition': 'All relevant PRIMARY and SECONDARY items; fixed before assignment, never demoted to improve score',
                        'coverage_basis': 'Relevant declared product-information items, counted once each by actual visible claim binding; no omission penalty for irrelevant items',
                        'channel_mode': 'paid' if fmt == 'META_PAID_SOCIAL' else 'organic',
                        'density_policy': 'one proposition' if 'STATIC' in fmt else 'tactic-appropriate sequential detail'}
    repeats = {field: sum(getattr(h, field) == value for h in request.history)
               for field, value in [('tactic_key', request.tactic_key), ('hook_claim_id', request.hook_claim_id),
                                    ('angle', request.angle), ('primary_claim_id', request.primary_claim_id),
                                    ('layout_family', layout_families[0])]}
    warnings = [f'Diversify {k}: repeated {n} times in supplied history' for k, n in repeats.items() if n >= 2]
    usage_snapshot = {'tactic_key': request.tactic_key, 'hook_claim_id': request.hook_claim_id,
                      'angle': request.angle, 'primary_claim_id': request.primary_claim_id,
                      'layout_family': layout_families[0]}
    result = {'version': 1, 'product_id': library.product_id, 'jan': library.jan,
            'claim_library_sha256': library.digest(), 'canonical_strategy': request.model_dump(mode='json'),
            'selected_tactic_name': TACTICS[request.tactic_key]['name'], 'archetype': archetype,
            'tactic_selection_rationale': {'selected_by': 'operator', 'objective': request.objective,
                'funnel': request.funnel_stage, 'audience': request.audience, 'available_evidence': sorted(requested),
                'reason': f'{profile} roles support this tactic; alternatives ranked using objective, funnel, novelty, complexity, objections and supplied usage'},
            'recommendations': suggestions, 'diversity': {'history_supplied': bool(request.history),
                'repetition_counts': repeats, 'recommendations': warnings}, 'formats': formats,
            'planning_only': True, 'creative_release_allowed': False, 'owner_review_status': 'PENDING',
            'commercial_import_gate': 'NOT_PART_OF_MARKETING_PLANNING',
            'creative_model_claim_invention_allowed': False,
            'strategy_metadata_is_not_ad_copy': True, 'quality_gate': list(QUALITY_GATE),
            'message_usage_snapshot': usage_snapshot,
            'current_slide_2_classification': 'HYBRID_BENEFIT_FORMULA_VISUAL',
            'current_slide_2_reuse_decision': 'QUALITY_REFERENCE_ONLY',
            'existing_artwork_does_not_determine_roles': True,
            'message_usage_snapshot_status': 'PROPOSED_NOT_EXECUTED; add to history only after owner adoption'}
    if execution_contract:
        result['execution_contract_version'] = 1
        actual_family = next(iter(formats.values()))['assets'][0]['layout_family']
        result['message_usage_snapshot']['layout_family'] = actual_family
        result['diversity']['repetition_counts']['layout_family'] = sum(
            h.layout_family == actual_family for h in request.history)
        result['diversity']['recommendations'] = [
            f'Diversify {k}: repeated {n} times in supplied history'
            for k, n in result['diversity']['repetition_counts'].items() if n >= 2]
    return result


def validate_plan(plan, library):
    """Rebuild from trusted inputs; rejects edited copy, roles, coverage or gates."""
    request = CampaignCreativeStrategyRequest.model_validate(plan['canonical_strategy'])
    if 'execution_contract_version' in plan and plan['execution_contract_version'] != 1:
        raise ValueError('Unsupported execution contract version')
    if plan != plan_campaign(request, library, execution_contract='execution_contract_version' in plan):
        raise ValueError('Strategy/claim/coverage plan changed; rebuild and review')
    return plan
