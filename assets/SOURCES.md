# Tree asset sources

All bundled tree models in `assets/trees.blend` come from [Polyhaven](https://polyhaven.com/), license **CC0** ([details](https://polyhaven.com/license)).

| `TreeTpl_*` name | Polyhaven slug | URL |
|---|---|---|
| TreeTpl_Oak    | `island_tree_02` | <https://polyhaven.com/a/island_tree_02> |
| TreeTpl_Beech  | `island_tree_03` | <https://polyhaven.com/a/island_tree_03> |
| TreeTpl_Spruce | `fir_tree_01`    | <https://polyhaven.com/a/fir_tree_01>    |
| TreeTpl_Birch  | `jacaranda_tree` | <https://polyhaven.com/a/jacaranda_tree> |

Species labels are advisory — what matters for the scene is silhouette diversity.

## What was modified vs the originals

Polyhaven trees ship LOD0-quality (millions of polys, 1k×1k PBR map sets). For
aerial/drone scatter that's overkill. The bundled `trees.blend` has been
reduced to:

- **Geometry**: ~5% of LOD0 polycount via two compounding Decimate passes
  (modifier kept applied so users don't see the modifier; original geometry
  is reproducible by re-running `assets/build_trees.py`).
- **Textures**: only the `_diff` (color + alpha) maps survive. Normal,
  roughness, AO, and displacement maps are disconnected (their TexImage
  nodes still exist in the material graph with `image=None`, so users
  can re-attach higher-res maps).
- **Resolution**: leaf textures kept at 1024² (silhouette critical).
  Trunk/branch textures downsized to 512² (not visible at typical
  drone distance).

To reproduce or upgrade: open `assets/build_trees.py` in Blender and run.
