"""Offline integration: canonical tactics -> exact claims -> format briefs/export."""
from copy import deepcopy
import json
import pytest
from app.schemas.campaign_creative_strategy import CampaignCreativeStrategyRequest
from app.services import campaign_creative_strategy as strategy
from app.services.marketing_claims import load_library
from app.services.premium_handoff import export_strategy_planning_package

PRODUCT = 'a5ea2272a1f89d743c089461bb2fb50f'


def request(**changes):
    categories = [('hydration', 'principal_benefit', 'ex-hydration'),
                  ('softness', 'secondary_benefit', 'ex-softness'),
                  ('radiance', 'secondary_benefit', 'ex-radiance'),
                  ('sheet', 'technology', 'ex-sheet'),
                  ('layers', 'differentiation', 'ex-sheet-layers'),
                  ('formula', 'formula', 'ex-formula'),
                  ('vitamin_c', 'formula', 'ex-vitamin-c'),
                  ('hyaluronic', 'formula', 'ex-hyaluronic'),
                  ('daily', 'usage', 'ex-daily'),
                  ('toner', 'usage', 'ex-toner'),
                  ('application', 'usage', 'ex-apply'),
                  ('after', 'usage', 'ex-after'),
                  ('pack', 'pack', 'ex-pack'),
                  ('fragrance', 'proof', 'ex-free-fragrance')]
    data = dict(product_id=PRODUCT, objective='education', audience='Adults interested in Japanese skincare',
                funnel_stage='consideration', tactic_key='educational_campaign', angle='evidence-led product education',
                hook_claim_id='editorial-1', primary_claim_id='ex-hydration', secondary_claim_ids=['ex-softness', 'ex-radiance'],
                proof_claim_ids=['ex-sheet-layers'], cta_claim_id='editorial-2',
                funnel_cta_claim_ids={'awareness': 'editorial-1', 'consideration': 'editorial-2', 'conversion': 'editorial-4'},
                formats=['INSTAGRAM_CAROUSEL_5', 'INSTAGRAM_CAROUSEL_10', 'META_PAID_SOCIAL',
                         'INSTAGRAM_STORIES', 'REEL_SHORT_VIDEO', 'INSTAGRAM_STATIC', 'FACEBOOK_STATIC'],
                coverage=[dict(key=k, category=c, priority='PRIMARY' if c == 'principal_benefit' else 'SUPPORTING' if k in ('vitamin_c', 'hyaluronic', 'application', 'after', 'fragrance') else 'SECONDARY', claim_id=i)
                          for k, c, i in categories], visual_benchmark='owner-selected-slide2-quality-reference', complexity='high')
    data.update(changes)
    return CampaignCreativeStrategyRequest.model_validate(data)


@pytest.fixture
def library():
    return load_library(PRODUCT)


def test_inventory_reuses_all_64_tactics_and_ten_archetypes():
    inventory = strategy.tactic_inventory()
    assert len(inventory['tactics']) == 64
    assert len(inventory['archetypes']) == 10
    assert len({t['key'] for t in inventory['tactics']}) == 64


def test_five_and_ten_roles_and_deeper_actual_coverage(library):
    p = strategy.plan_campaign(request(), library)['formats']
    five, ten = p['INSTAGRAM_CAROUSEL_5'], p['INSTAGRAM_CAROUSEL_10']
    assert [a['role'] for a in five['assets']] == list(strategy.SEQUENCES['education'][0])
    assert len(ten['assets']) == 10
    assert ten['coverage_percent'] > five['coverage_percent']
    assert {'ex-apply', 'ex-after'} <= {c for a in ten['assets'] for c in a['approved_claim_ids'].values()}


@pytest.mark.parametrize('key', ['problem_solution_campaign', 'discovery_campaign', 'product_selection', 'paid_ads'])
def test_distinct_existing_tactics_have_distinct_sequences(library, key):
    fmt = ['INSTAGRAM_CAROUSEL_5']
    a = strategy.plan_campaign(request(formats=fmt), library)
    b = strategy.plan_campaign(request(formats=fmt, tactic_key=key), library)
    assert [x['role'] for x in a['formats'][fmt[0]]['assets']] != [x['role'] for x in b['formats'][fmt[0]]['assets']]
    assert a['archetype'] != b['archetype']


def test_roas_axes_are_independent_not_reused_carousel_images(library):
    ads = strategy.plan_campaign(request(), library)['formats']['META_PAID_SOCIAL']['assets']
    assert len(ads) == 16
    assert len({a['angle_id'] for a in ads}) == 4
    for angle in {a['angle_id'] for a in ads}:
        selected = [a for a in ads if a['angle_id'] == angle]
        assert len({a['hook_claim_id'] for a in selected}) == 2
        assert len({a['visual_execution'] for a in selected}) == 2
    assert not any('image_path' in a for a in ads)


def test_story_video_static_platform_adaptation(library):
    f = strategy.plan_campaign(request(), library)['formats']
    story = f['INSTAGRAM_STORIES']['assets']
    assert len(story) == 5 and story[0]['role'] == 'story_hook'
    video = f['REEL_SHORT_VIDEO']['assets']
    assert video[0]['time_seconds'] == [0, 3]
    assert video[-1]['time_seconds'] == [26, 30]
    assert all(v['voiceover'] and v['on_screen_copy'] and v['required_product_shot'] for v in video)
    assert video[0]['first_seconds_visual']
    for fmt in ('INSTAGRAM_STATIC', 'FACEBOOK_STATIC'):
        assert len(f[fmt]['assets']) == 1
        assert set(f[fmt]['assets'][0]['approved_claim_ids'].values()) == {'ex-hydration', 'editorial-2'}
    assert f['INSTAGRAM_STATIC']['assets'][0]['visual_intent'] != f['FACEBOOK_STATIC']['assets'][0]['visual_intent']
    assert f['META_PAID_SOCIAL']['channel_mode'] == 'paid'
    assert f['INSTAGRAM_STORIES']['channel_mode'] == 'organic'


def test_actual_coverage_and_intentional_omission_denominator(library):
    r = request(formats=['INSTAGRAM_CAROUSEL_5'])
    raw = r.model_dump()
    raw['coverage'][-1].update(relevant=False, omission_reason='Not needed for this short education sequence')
    plan = strategy.plan_campaign(CampaignCreativeStrategyRequest.model_validate(raw), library)
    fmt = plan['formats']['INSTAGRAM_CAROUSEL_5']
    assert fmt['coverage_denominator'] == len(r.coverage) - 1
    for c in fmt['coverage']:
        matches = [a['asset_id'] for a in fmt['assets'] if c['claim_id'] in a['approved_claim_ids'].values()]
        assert c['assigned_slide_or_asset'] == matches
        assert c['used_in_campaign'] == bool(matches)


@pytest.mark.parametrize('field', ['objective', 'audience', 'funnel_stage', 'tactic_key', 'angle',
                                 'hook_claim_id', 'primary_claim_id', 'proof_claim_ids', 'cta_claim_id'])
def test_missing_strategy_component_blocks(field):
    data = request().model_dump()
    del data[field]
    with pytest.raises(ValueError):
        CampaignCreativeStrategyRequest.model_validate(data)


@pytest.mark.parametrize('cid', ['not-a-claim', 'ex-exosomes', 'unsupported-whitening'])
def test_unknown_unreviewed_claim_cannot_enter_any_brief(library, cid):
    with pytest.raises(ValueError):
        strategy.plan_campaign(request(primary_claim_id=cid), library)


def test_review_revocation_and_bad_qualifier_fail_closed(library):
    claims = list(library.claims)
    index = next(i for i, c in enumerate(claims) if c.claim_id == 'ex-radiance')
    for update in ({'review_status': 'NEEDS_REVIEW'}, {'approved_pt_br_wording': {'STANDARD': 'Luminosidade'}}):
        changed = list(claims)
        changed[index] = claims[index].model_copy(update=update)
        with pytest.raises(ValueError):
            strategy.plan_campaign(request(), library.model_copy(update={'claims': tuple(changed)}))


def test_export_contains_strategy_qualified_claims_quality_and_no_execution(tmp_path, library):
    plan = strategy.plan_campaign(request(), library)
    assert plan['planning_only'] and not plan['creative_release_allowed']
    assert plan['owner_review_status'] == 'PENDING'
    directory = export_strategy_planning_package(plan, library, tmp_path / 'planning')
    exported = json.loads((directory / 'CAMPAIGN_STRATEGY_CREATIVE_PLAN.json').read_text(encoding='utf-8'))
    for f in exported['formats'].values():
        for a in f['assets']:
            assert a['tactic'] and a['objective'] and a['audience'] and a['funnel_stage']
            assert a['angle'] and a['hook'] and a['approved_copy'] and a['approved_claim_ids']
            assert a['visual_benchmark'] and a['prohibited_wording'] and a['quality_gate']
            assert not a['benchmark_layout_locked']
            if 'ex-radiance' in a['approved_claim_ids'].values():
                assert 'causada pelo ressecamento' in ' '.join(a['approved_copy'].values())
    assert 'PLANNING ONLY' in (directory / 'PREMIUM_CREATIVE_PLANNING_INSTRUCTION.txt').read_text(encoding='utf-8')


@pytest.mark.parametrize('mutation', ['copy', 'coverage', 'ready', 'strategy', 'library'])
def test_mutation_and_stale_library_cannot_export(tmp_path, library, mutation):
    plan = deepcopy(strategy.plan_campaign(request(), library))
    if mutation == 'copy':
        plan['formats']['INSTAGRAM_STATIC']['assets'][0]['approved_copy']['copy_0'] = 'Cura a pele'
    elif mutation == 'coverage':
        plan['formats']['INSTAGRAM_STATIC']['coverage_percent'] = 100
    elif mutation == 'ready':
        plan['creative_release_allowed'] = True
    elif mutation == 'strategy':
        plan['canonical_strategy']['angle'] = 'silent substitute'
    else:
        library = library.model_copy(update={'version': 2})
    with pytest.raises(ValueError):
        export_strategy_planning_package(plan, library, tmp_path / mutation)
    assert not (tmp_path / mutation).exists()


@pytest.mark.parametrize('key', ['competitor_comparison', 'flash_sale', 'social_proof_campaign', 'invented_tactic'])
def test_missing_comparative_or_operational_proof_is_not_invented(library, key):
    with pytest.raises(ValueError):
        strategy.plan_campaign(request(tactic_key=key), library)


def test_rationale_diversity_and_missing_history_disclosure(library):
    r = request(history=[dict(tactic_key='educational_campaign', hook_claim_id='editorial-1',
                              angle='evidence-led product education', primary_claim_id='ex-hydration',
                              layout_family='product_hero')] * 3)
    p = strategy.plan_campaign(r, library)
    assert len(p['diversity']['recommendations']) == 5
    assert p['recommendations'][0]['rationale']
    assert not strategy.plan_campaign(request(), library)['diversity']['history_supplied']


def test_real_api_entry_point_uses_same_planner_without_database(library):
    from app.api.strategy import premium_campaign_plan
    plan = premium_campaign_plan(request(formats=['INSTAGRAM_STATIC']))
    assert plan == strategy.plan_campaign(request(formats=['INSTAGRAM_STATIC']), library)


def test_unknown_category_and_wrong_product_do_not_silently_fallback(library):
    with pytest.raises(ValueError):
        strategy.plan_campaign(request(product_id='different-product'), library)
    with pytest.raises(ValueError):
        strategy.plan_campaign(request(tactic_key='cultural_campaign'), library)


def test_repeated_information_cannot_inflate_coverage():
    data = request().model_dump(mode='json')
    data['coverage'].append({**data['coverage'][0], 'key': 'same_fact_new_name'})
    with pytest.raises(ValueError, match='inflate coverage'):
        CampaignCreativeStrategyRequest.model_validate(data)


def test_usage_snapshot_is_proposed_not_false_executed_history(tmp_path, library):
    plan = strategy.plan_campaign(request(), library)
    directory = export_strategy_planning_package(plan, library, tmp_path / 'usage')
    usage = json.loads((directory / 'PROPOSED_MESSAGE_USAGE.json').read_text(encoding='utf-8'))
    assert 'PROPOSED_NOT_EXECUTED' in usage['status']
    assert usage['usage']['tactic_key'] == request().tactic_key
    assert usage['usage']['primary_claim_id'] == 'ex-hydration'


def test_http_schema_and_real_route_without_app_startup():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.strategy import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        payload = request(formats=['INSTAGRAM_STATIC']).model_dump(mode='json')
        response = client.post('/api/strategy-library/premium-campaign-plan', json=payload)
        assert response.status_code == 200
        assert response.json()['planning_only']
        payload['tactic_key'] = 'invented'
        assert client.post('/api/strategy-library/premium-campaign-plan', json=payload).status_code == 422
        del payload['objective']
        assert client.post('/api/strategy-library/premium-campaign-plan', json=payload).status_code == 422


def test_v1210_five_distinct_jobs_pack_and_one_hydration_primary(library):
    plan = strategy.plan_campaign(request(tactic_key='problem_solution_campaign'), library)
    f = plan['formats']['INSTAGRAM_CAROUSEL_5']
    aa = f['assets']
    assert len({a['role'] for a in aa}) == 5
    assert len({a['primary_information_job'] for a in aa}) == 5
    primary = [next(iter(a['approved_claim_ids'].values())) for a in aa]
    assert len(set(primary)) == 5 and primary.count('ex-hydration') == 1
    assert 'ex-pack' in aa[3]['approved_claim_ids'].values()
    assert 'ex-sheet-layers' in aa[2]['approved_claim_ids'].values()
    assert 'ex-toner' in aa[4]['approved_claim_ids'].values()
    assert f['high_priority_coverage_percent'] == 100


def test_v1210_ten_increments_include_application_and_aftercare(library):
    f = strategy.plan_campaign(request(), library)['formats']['INSTAGRAM_CAROUSEL_10']
    assert len(f['assets']) == 10
    assert all(a['incremental_value'] in ('HIGH', 'MEDIUM') for a in f['assets'])
    assert len({next(iter(a['approved_claim_ids'].values())) for a in f['assets']}) == 10
    used = {c for a in f['assets'] for c in a['approved_claim_ids'].values()}
    assert {'ex-apply', 'ex-after', 'ex-pack', 'ex-free-fragrance'} <= used
    assert f['high_priority_coverage_percent'] == 100
    assert f['coverage_percent'] < 100  # no ingredient filler to maximize a score


def test_v1210_hook_entry_points_differ_in_supported_meaning(library):
    ads = strategy.plan_campaign(request(), library)['formats']['META_PAID_SOCIAL']['assets']
    expected = {'primary_benefit': {'ex-hydration', 'ex-radiance'},
                'differentiation': {'ex-sheet-layers', 'ex-toner'},
                'secondary_benefit': {'ex-softness', 'ex-apply'},
                'formula': {'ex-formula', 'ex-free-fragrance'}}
    for angle, hooks in expected.items():
        selected = [a for a in ads if a['angle_id'] == angle]
        assert {a['hook_claim_id'] for a in selected} == hooks
        assert len({a['customer_motivation'] for a in selected}) == 2
        assert not any(a['hook'] == 'Descubra' for a in selected)
        for h in hooks:
            pair = [a for a in selected if a['hook_claim_id'] == h]
            assert len(pair) == 2
            assert len({a['visual_concept'] if 'visual_concept' in a else a['visual_execution'] for a in pair}) == 2
            assert len({a['funnel_stage'] for a in pair}) == 1
            assert pair[0]['approved_copy'] == pair[1]['approved_copy']


def test_v1210_funnel_behavior_destinations_priorities_and_test_design(library):
    ads = strategy.plan_campaign(request(), library)['formats']['META_PAID_SOCIAL']['assets']
    assert {a['funnel_stage'] for a in ads} == {'awareness', 'consideration', 'conversion'}
    assert len({a['funnel_behavior'] for a in ads}) == 3
    assert len({a['cta_claim_id'] for a in ads}) == 3
    assert all(a['what_is_being_tested'] and a['production_priority'] for a in ads)
    initial = [a for a in ads if a['initial_test_set']]
    assert len(initial) == 8 and len({a['angle_id'] for a in initial}) == 4
    assert all('OWNER_CONFIGURATION_REQUIRED' in a['destination_status'] for a in ads)
    assert all('not a causal hook A/B test' in a['what_is_being_tested'] for a in ads)
    for a in ads:
        if a['funnel_stage'] == 'conversion':
            assert 'ex-pack' in a['approved_claim_ids'].values()


@pytest.mark.parametrize('policies', [{}, {'awareness': 'editorial-1'},
                                    {'awareness': 'ex-hydration', 'consideration': 'editorial-2', 'conversion': 'editorial-4'}])
def test_v1210_missing_or_non_editorial_stage_cta_fails_closed(library, policies):
    with pytest.raises(ValueError):
        strategy.plan_campaign(request(funnel_cta_claim_ids=policies), library)


def test_v1210_reel_is_action_led_with_readable_temporal_progression(library):
    aa = strategy.plan_campaign(request(), library)['formats']['REEL_SHORT_VIDEO']['assets']
    assert aa[0]['role'] == 'material_motion_hook'
    assert 'unfolds' in aa[0]['visual_action'] and 'static title card' in aa[0]['visual_action']
    assert len({a['visual_action'] for a in aa}) == 6
    assert all(a['scene_purpose'] and a['transition_reason'] and a['voiceover_or_audio_role'] for a in aa)
    assert all(a['product_visibility'] for a in aa)
    assert all(0 < a['estimated_voiceover_wpm'] <= 180 for a in aa)
    assert all(aa[i]['time_seconds'][1] == aa[i+1]['time_seconds'][0] for i in range(5))
    assert 'ex-apply' in aa[4]['approved_claim_ids'].values()


def test_v1210_artwork_does_not_force_roles_or_change_good_story_static(library):
    p = strategy.plan_campaign(request(), library)
    assert p['current_slide_2_reuse_decision'] == 'QUALITY_REFERENCE_ONLY'
    assert p['existing_artwork_does_not_determine_roles']
    changed = strategy.plan_campaign(request(visual_benchmark='different-quality-reference'), library)
    for fmt in ('INSTAGRAM_CAROUSEL_5', 'INSTAGRAM_CAROUSEL_10'):
        assert [a['role'] for a in p['formats'][fmt]['assets']] == [a['role'] for a in changed['formats'][fmt]['assets']]
    story = p['formats']['INSTAGRAM_STORIES']['assets']
    assert [a['role'] for a in story] == ['story_hook', 'benefit', 'proof', 'usage', 'story_cta']
    assert [tuple(a['approved_claim_ids'].values()) for a in story] == [('editorial-1',), ('ex-hydration',), ('ex-sheet-layers',), ('ex-daily',), ('editorial-2',)]
    for fmt in ('INSTAGRAM_STATIC', 'FACEBOOK_STATIC'):
        assert tuple(p['formats'][fmt]['assets'][0]['approved_claim_ids'].values()) == ('ex-hydration', 'editorial-2')


def test_v1210_high_priority_score_uses_caller_priorities_without_demotion(library):
    raw = request(tactic_key='problem_solution_campaign').model_dump(mode='json')
    for c in raw['coverage']:
        c['priority'] = 'SECONDARY'
    f = strategy.plan_campaign(CampaignCreativeStrategyRequest.model_validate(raw), library)['formats']['INSTAGRAM_CAROUSEL_5']
    assert f['high_priority_denominator'] == 14
    assert f['high_priority_coverage_percent'] == 64.29
    assert all(c['priority'] == 'SECONDARY' for c in f['coverage'])


def test_v1210_prepared_information_order_cannot_swap_usage_or_benefit_jobs(library):
    original = request()
    reversed_input = original.model_copy(update={'coverage': tuple(reversed(original.coverage))})
    a = strategy.plan_campaign(original, library)
    b = strategy.plan_campaign(reversed_input, library)
    # Formula selection intentionally follows the declared primary formula fact;
    # the application/aftercare and benefit jobs must remain semantic, not ordinal.
    for fmt in ('REEL_SHORT_VIDEO',):
        assert a['formats'][fmt]['assets'] == b['formats'][fmt]['assets']
