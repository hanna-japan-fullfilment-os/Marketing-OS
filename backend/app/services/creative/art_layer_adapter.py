"""Narrow request translation only. No network/client, retries or budget changes."""
import json


def gpt_image_2_art_request(plan):
    """Use with the existing guarded ImageProvider, only under live authorization.

    V9.3 calls this pure translator in tests/debug only. It never dispatches.
    """
    if plan.crop['native_size'] != [1024,1536]:
        raise ValueError('Bounded GPT Image 2 art plan requires 1024x1536 native')
    spec=plan.art_layer_prompt_spec
    if (spec['generative_text_allowed'] or spec['generative_logo_allowed']
            or spec['generative_product_allowed']):
        raise ValueError('Art layer must exclude deterministic content')
    prompt=('ENVIRONMENT ONLY. Do not generate any product, packaging, readable text, logo, CTA or badge. '
        'Reserve the scene zones below for later deterministic rendering. Geometry is in final canvas pixels. '
        'Map it into the central crop of the native image; crop allowance is not composition space. '
        'Generate only ART_LAYER-owned treatments. Code owns all contact shadows, product halos, '
        'editorial lines and light arcs; do not duplicate them. No additional motifs.\n'
        +json.dumps(dict(art_layer=spec,crop=plan.crop,ownership=plan.ownership),ensure_ascii=False,sort_keys=True))
    request=dict(model='gpt-image-2',quality='high',size='1024x1536',n=1,partial_images=0,prompt=prompt)
    from ..ai.openai_provider import _gpt_image_2_reservation
    if _gpt_image_2_reservation('generate',request)!=.265:
        raise ValueError('Existing bounded request contract changed')
    return request
