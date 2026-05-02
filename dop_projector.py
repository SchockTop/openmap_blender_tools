"""dop_projector.py — single source of truth for ortho UV projection.

Creates a Blender Empty named 'DOPProjector' at the DOP UDIM origin,
scaled to the bbox dimensions. Roof and ground materials reference this
Empty via `Texture Coordinate.Object` so they sample the orthophoto using
identical world-XY coordinates → no color seam at building edges.

Drag the Empty in the scene to re-align both layers together.
"""
from __future__ import annotations

PROJECTOR_NAME = "DOPProjector"


def ensure_dop_projector(bpy, bbox_utm32n):
    """Create or reuse the DOPProjector Empty for the given UTM32N bbox.

    bbox_utm32n: (min_x, min_y, max_x, max_y) in meters.
    Returns the Blender Object (Empty type).
    """
    if PROJECTOR_NAME in bpy.data.objects:
        return bpy.data.objects[PROJECTOR_NAME]

    min_x, min_y, max_x, max_y = bbox_utm32n
    empty = bpy.data.objects.new(PROJECTOR_NAME, None)
    if hasattr(empty, "empty_display_type"):
        empty.empty_display_type = "ARROWS"
    empty.location = (float(min_x), float(min_y), 0.0)
    empty.scale = (float(max_x - min_x), float(max_y - min_y), 1.0)

    try:
        bpy.context.scene.collection.objects.link(empty)
    except Exception:
        pass
    return empty
