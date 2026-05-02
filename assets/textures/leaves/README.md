# Leaves texture override directory

Drop higher-resolution leaf textures here to override the bundled ones in
`trees.blend`. Filename convention: `<species>_color.png` and
`<species>_alpha.png` (lowercase species names: oak, beech, spruce, birch).

The bundled trees come with leaf+alpha textures packed inside `trees.blend`
already — this directory is for users who want to upgrade.

To swap globally for a region, place files in `data/<region>/textures/leaves/`
instead (the pipeline checks the per-region path first).
