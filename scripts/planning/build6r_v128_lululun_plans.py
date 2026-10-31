"""Generate the V12.8 owner-review package offline; never artwork or DB writes.

Usage: python -B scripts/planning/build6r_v128_lululun_plans.py NEW_OUTPUT_DIRECTORY --benchmark SLIDE2_IMAGE
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.schemas.campaign_creative_strategy import CampaignCreativeStrategyRequest
from app.services.campaign_creative_strategy import plan_campaign, tactic_inventory
from app.services.marketing_claims import load_library
from app.services.premium_handoff import export_strategy_planning_package


def build(directory, benchmark):
    library = load_library('a5ea2272a1f89d743c089461bb2fb50f')
    benchmark = Path(benchmark)
    benchmark_sha = hashlib.sha256(benchmark.read_bytes()).hexdigest()
    categories = [
        ('hydration', 'principal_benefit', 'PRIMARY', 'ex-hydration'),
        ('softness', 'secondary_benefit', 'SECONDARY', 'ex-softness'),
        ('radiance', 'secondary_benefit', 'SECONDARY', 'ex-radiance'),
        ('sheet', 'technology', 'SECONDARY', 'ex-sheet'),
        ('layers', 'differentiation', 'SECONDARY', 'ex-sheet-layers'),
        ('formula', 'formula', 'SECONDARY', 'ex-formula'),
        ('vitamin_c', 'formula', 'SUPPORTING', 'ex-vitamin-c'),
        ('hyaluronic', 'formula', 'SUPPORTING', 'ex-hyaluronic'),
        ('daily', 'usage', 'SECONDARY', 'ex-daily'),
        ('toner', 'usage', 'SECONDARY', 'ex-toner'),
        ('application', 'usage', 'SUPPORTING', 'ex-apply'),
        ('after', 'usage', 'SUPPORTING', 'ex-after'),
        ('pack', 'pack', 'SECONDARY', 'ex-pack'),
        ('fragrance', 'proof', 'SUPPORTING', 'ex-free-fragrance'),
    ]
    base = dict(product_id=library.product_id, objective='consideration',
                audience='Adultos interessados em skincare japonês e em conhecer a máscara LuLuLun Hydra EX de 7 unidades.',
                funnel_stage='consideration', tactic_key='problem_solution_campaign',
                angle='Hidratação e experiência do tecido; sem extrapolar ingredientes para eficácia clínica.',
                hook_claim_id='editorial-1', primary_claim_id='ex-hydration',
                secondary_claim_ids=['ex-softness', 'ex-radiance'], proof_claim_ids=['ex-sheet-layers'],
                cta_claim_id='editorial-2',
                funnel_cta_claim_ids={'awareness': 'editorial-1', 'consideration': 'editorial-2', 'conversion': 'editorial-4'},
                visual_benchmark=f'Owner-selected latest Slide 2 SHA256={benchmark_sha}: purple/gold lighting, staging, typography and integration; quality direction only, not layout or approval authority.',
                product_novelty='established', complexity='high',
                objections=['Qual é a textura do tecido?', 'Como encaixar na rotina?', 'O que vem na embalagem?'],
                coverage=[dict(key=k, category=c, priority=p, claim_id=i) for k, c, p, i in categories])
    specs = [
        ('LULULUN_5_SLIDE_CAMPAIGN_PLAN', 'INSTAGRAM_CAROUSEL_5', {},
         'Benefit-led consideration: quickly explain the main proposition, tactile difference and formula without a product-page collage.'),
        ('LULULUN_10_SLIDE_CAMPAIGN_PLAN', 'INSTAGRAM_CAROUSEL_10',
         dict(tactic_key='educational_campaign', objective='education'),
         'Long-form education: ten distinct learning/decision jobs, including application and aftercare; no isolated low-value ingredient filler.'),
        ('LULULUN_META_ROAS_PLAN', 'META_PAID_SOCIAL',
         dict(tactic_key='paid_ads', objective='conversion', funnel_stage='conversion'),
         'Paid concept testing: distinct benefit, sheet differentiation, formula and sensory hypotheses. No media launch or promised ROAS.'),
        ('LULULUN_STORIES_PLAN', 'INSTAGRAM_STORIES', dict(tactic_key='discovery_campaign', objective='discovery'),
         'Vertical tap sequence, one idea per frame, with a routine frame because the supplied complexity is high.'),
        ('LULULUN_REEL_PLAN', 'REEL_SHORT_VIDEO', dict(tactic_key='educational_campaign', objective='education'),
         'A 30-second moving-sheet-to-application narrative with category recognition, exact approved voiceover and scene-specific transitions.'),
        ('LULULUN_STATIC_SOCIAL_PLAN', 'INSTAGRAM_STATIC', dict(tactic_key='discovery_campaign', objective='awareness'),
         'Single hydration proposition with an editorial learn-more CTA; Facebook receives its own contextual execution.'),
    ]
    plans = {}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'VISUAL_BENCHMARK_REFERENCE.json').write_text(json.dumps({
        'path': str(benchmark.resolve()), 'sha256': benchmark_sha,
        'role': 'owner-selected quality-direction benchmark', 'layout_locked': False,
        'quality_locked': True, 'historical_QA_reclassified': False}, indent=2), encoding='utf-8')
    for name, fmt, changes, reason in specs:
        formats = [fmt] if fmt != 'INSTAGRAM_STATIC' else [fmt, 'FACEBOOK_STATIC']
        request = CampaignCreativeStrategyRequest.model_validate({**base, **changes, 'formats': formats})
        plan = plan_campaign(request, library)
        export_strategy_planning_package(plan, library, directory / name)
        plans[name] = plan
        (directory / (name + '.json')).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        lines = [f'# {name}', '', '**PLANNING ONLY — owner review pending. No artwork or publication authorization.**', '',
                 f'Why this tactic: {reason}', f"Canonical tactic: `{request.tactic_key}` — {plan['selected_tactic_name']}",
                 f'Objective: {request.objective}; funnel: {request.funnel_stage}; audience: {request.audience}',
                 f'Angle: {request.angle}', '', 'Marketing copy below is exact V12.4 wording. Metadata/headings are not visible advertising copy.',
                 'Proof is manufacturer/product evidence with its actual scope; it is not independent clinical or testimonial proof.', '']
        for format_id, output in plan['formats'].items():
            lines += [f'## {format_id}', f"Coverage: {output['coverage_numerator']}/{output['coverage_denominator']} relevant information items ({output['coverage_percent']}%).", '']
            lines += [f"High-priority coverage (PRIMARY + SECONDARY): {output['high_priority_numerator']}/{output['high_priority_denominator']} = {output['high_priority_coverage_percent']}%.", '']
            for a in output['assets']:
                lines += [f"### {a['asset_id']} — {a['role']}"]
                if a.get('angle_id'):
                    lines += [f"Angle: {a['angle_id']}; hook: {a['hook']}; execution: {a['visual_execution']}",
                              f"Test: {a['hypothesis']}", f"Audience: {a['audience']}; funnel: {a['funnel_stage']}",
                              f"Customer motivation: {a['customer_motivation']}",
                              f"What is being tested: {a['what_is_being_tested']}",
                              f"Priority: {a['production_priority']}; initial set: {a['initial_test_set']}",
                              f"Destination: {a['destination_intent']} — {a['destination_status']}",
                              f"Formats: {', '.join(a['recommended_formats'])}"]
                if a['time_seconds']:
                    lines += [f"Timing: {a['time_seconds'][0]}–{a['time_seconds'][1]} seconds", f"Shot: {a['required_product_shot']}",
                              f"Opening visual: {a['first_seconds_visual'] or 'continue the shot sequence'}",
                              f"Purpose: {a['scene_purpose']}; action: {a['visual_action']}",
                              f"Product visible: {a['product_visibility']}; transition reason: {a['transition_reason']}",
                              f"Voiceover estimate: {a['estimated_voiceover_wpm']} words/minute; {a['voiceover_or_audio_role']}",
                              'Voiceover uses only the exact approved copy below.']
                if 'primary_information_job' in a:
                    lines += [f"Primary information job: {a['primary_information_job']}; incremental value: {a['incremental_value']}",
                              a['incremental_value_reason'], a['secondary_message_treatment']]
                lines += ['Visible copy:'] + [f'- **{cid}**: {a["approved_copy"][field]}' for field, cid in a['approved_claim_ids'].items()]
                lines += [f"CTA: {a['cta'] or 'none on this asset'}", f"Art direction: {a['visual_intent']}",
                          f"Quality target: {', '.join(a['quality_gate'])}; exact product/packaging, no panel fallback.",
                          'Proof: ' + '; '.join(f"{p['claim_id']} — {p['scope']} — {p['source']}" for p in a['proof']), '']
            lines += ['### Information coverage', '| Item | Claim | Priority | Used | Assigned assets | Omission rationale |',
                      '|---|---|---|---|---|---|']
            for c in output['coverage']:
                lines.append(f"| {c['key']} | {c['claim_id']} | {c['priority']} | {c['used_in_campaign']} | {', '.join(c['assigned_slide_or_asset'])} | {c['omission_reason']} |")
        lines += ['', '## Prohibited wording', *('- ' + p for p in library.prohibited_language),
                  '', 'No human approval, previous campaign history, current offer, price, stock, shipping promise, testimonial or competitor metric is inferred.']
        (directory / (name + '.md')).write_text('\n'.join(lines), encoding='utf-8')
    inventory = tactic_inventory()
    (directory / 'MARKETING_OS_TACTIC_INVENTORY.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    for name in ('MARKETING_OS_TACTIC_INVENTORY.md', 'MARKETING_OS_CAMPAIGN_STRATEGY_TO_CREATIVE_FLOW.md'):
        (directory / name).write_bytes((ROOT / 'docs' / name).read_bytes())
    coverage = {name: {fmt: output['coverage'] for fmt, output in p['formats'].items()} for name, p in plans.items()}
    (directory / 'LULULUN_PRODUCT_INFORMATION_COVERAGE_MATRIX.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding='utf-8')
    short = plans['LULULUN_5_SLIDE_CAMPAIGN_PLAN']['formats']['INSTAGRAM_CAROUSEL_5']
    long = plans['LULULUN_10_SLIDE_CAMPAIGN_PLAN']['formats']['INSTAGRAM_CAROUSEL_10']
    lines = ['# Product information coverage', '',
             f"Five-slide: {short['coverage_numerator']}/{short['coverage_denominator']} = {short['coverage_percent']}%.",
             f"Ten-slide: {long['coverage_numerator']}/{long['coverage_denominator']} = {long['coverage_percent']}%.",
             'Both use the same declared set of relevant consideration/education facts; deeper education covers more. This percentage measures coverage, not creative quality or approval.',
             'Unused information is intentionally omitted for role/density, not flagged as a failure. Origin claims, prices, urgency, comparative proof and testimonials are unavailable and not fabricated.', '',
             '| Format | Relevant item | Claim | Used | Actual asset assignments |', '|---|---|---|---|---|']
    for name, formats in coverage.items():
        for fmt, rows in formats.items():
            for c in rows:
                lines.append(f"| {fmt} | {c['key']} | {c['claim_id']} | {c['used_in_campaign']} | {', '.join(c['assigned_slide_or_asset'])} |")
    (directory / 'LULULUN_PRODUCT_INFORMATION_COVERAGE_MATRIX.md').write_text('\n'.join(lines), encoding='utf-8')
    summary = {'FIVE_SLIDE_COVERAGE_PERCENT': short['coverage_percent'], 'TEN_SLIDE_COVERAGE_PERCENT': long['coverage_percent'],
               'HIGH_PRIORITY_5_SLIDE_COVERAGE_PERCENT': short['high_priority_coverage_percent'],
               'HIGH_PRIORITY_10_SLIDE_COVERAGE_PERCENT': long['high_priority_coverage_percent'],
               'ROAS_ANGLE_COUNT': len({a['angle_id'] for a in plans['LULULUN_META_ROAS_PLAN']['formats']['META_PAID_SOCIAL']['assets']}),
               'owner_review_status': 'PENDING', 'artwork_created': 0}
    (directory / 'PACKAGE_SUMMARY.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_directory')
    parser.add_argument('--benchmark', required=True, help='Exact owner-selected latest Slide 2 image')
    args = parser.parse_args()
    print(json.dumps(build(args.output_directory, args.benchmark), indent=2))
