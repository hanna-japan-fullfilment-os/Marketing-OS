# V11.1 locked-product scene editing

V10 live acceptance remains FAIL. V11 reuses the V10 package, approved reference
selection, guide, direct Images Edit adapter, exact-copy contracts and hard-budget
interfaces. It changes who owns final pixels, not the provider architecture.
There is no live request or persistent campaign/asset mutation in this build.

## Preparation

Resolve canonical authority as in V10, then `resolve_locked_delivery`. This keeps
the V10 deterministic text regions and enlarges the post-crop logo region inside
the retained 1024×1280 canvas. Model-integrated final text is rejected in V11.

`canonical_product_layer` requires an explicit existing approved RGBA master and
its exact SHA256, validated with the existing canonical-master inspector. Alpha
is taken from that asset, including holes and soft edges, not guessed as a box.
Only transparent padding is trimmed. The cutout is uniformly scaled to fit the
resolved product region and anchored lower-right before scene creation. No
rotation, recoloring, label repair, relighting or new product reconstruction is
performed. The historic provenance of an already approved reconstructed master
remains explicit; V11 does not turn it into original photography.

The rendered RGBA product layer and alpha receive pixel hashes. Geometry records
source alpha bounds, final box and native box (+128 y for the prepared crop).
`scene_layers` builds the locked base, product protection mask and editable ring.
Protection margin and ring width are configurable and validated. The environment
mask uses opaque alpha to protect and transparent alpha to permit editing. The
ring extends beyond the protection margin and remains editable. No deterministic
drop shadow is added; interaction shadows/reflections belong to the edited scene.
Regions intersecting the protected silhouette or grounding ring fail before a
provider request. Artifacts are written exclusively to a caller-authorized folder.

## Existing direct-edit boundary

The existing adapter accepts optional typed `SceneEditAssets`. It revalidates the
canonical source, exact geometry, masks and exported artifacts. The locked base
is first in the multipart image list, with the alpha environment mask applied to
that first image. The V10 reference legend is renumbered so actual product/context,
composition and brand inputs remain unambiguous. V10's canonical handoff is reused
without dropping facts/copy. V11 ownership instructions replace generative final
product/text/logo responsibility; references still direct premium scene design.

The model is instructed to design lighting, ground/surface, shadow, reflections,
framing, atmosphere and depth around the known upright product position. It may
not generate another product, final marketing text or the final logo. The prompt
contains exact native/final product geometry, crop, light direction, text/logo
regions, protection margin and editable ring width. Masking remains guidance,
never the integrity guarantee. Unknown image input costs (including base and mask)
remain unresolved and block dispatch through the unchanged general budget policy.

## Delivery and proof

Order is fixed: native scene -> prepared final crop -> canonical alpha restore ->
deterministic text -> canonical logo -> CTA -> QA. No later crop can remove the
final logo or text. Product restoration changes only alpha-supported pixels;
scene pixels outside that silhouette, including the whole grounding ring, remain
intact. Soft edges use canonical alpha blending, while opaque product interiors
come exactly from the scaled canonical asset. `require_product_integrity` compares
the expected composition over all alpha support and independently checks the ring.
Position, label identity and variant now depend on canonical-layer integrity,
not whether the image model reproduced the package correctly.

Final typography measures actual background contrast. If needed, a bounded,
glyph-local tonal fade provides at least 4.5:1 core-ink contrast. A reserved region
is never filled as a large opaque card, copy is not shortened, and fonts never
silently fall back. Text/product and text/text overlaps fail. Existing approved
V9 matte extraction is reused only to derive transparent canonical logo artwork;
the V9 compositor is never used. Canonical logo RGB artwork/source file remains
unchanged, and the full mark/wordmark is fitted after crop. Unsupported opaque
logo backgrounds fail instead of creating a white tile.

Pixel/contrast/edge QA proves technical correctness, not premium visual quality.
`require_locked_scene_acceptance` rechecks final pixels against the deterministic
delivery and reuses V10's bound product/copy/visual review. Explicit additional
findings must rule out generated product pixels outside the canonical layer,
stray final marketing text/logos and duplicate shadows, and affirm postability.
Future scene QA must still reject generated duplicate products/logos/text, poor
grounding, competing shadows, incoherent style or unpostable composition. A locked
product restore cannot prove the rest of a model-generated scene is acceptable.
V11.2, separately authorized, is the only live visual test; this build does not
reuse V10's consumed one-time cost-policy exception.
