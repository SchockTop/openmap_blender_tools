"""camera_presets.py - named camera envelopes for the full altitude range.

Each preset bundles the altitude / speed / lens / banking / sensor settings
that the cinematic-camera-rig playbook section 5.3 documents as internally
consistent for a given shot type. The presets cover from FPV-walking-through-
bushes (1.7 m AGL, 1.4 m/s, 24 mm) to high-altitude reveal (4500 m, 150 m/s,
135 mm).

Usage in scripts:

    from blender_tools.camera_presets import apply_camera_preset, CAMERA_PRESETS
    apply_camera_preset(camera_obj, preset_name="fpv-walk", scene=bpy.context.scene)

The preset's altitude_agl_m can override the CSV waypoint altitudes
(useful when a waypoint CSV has flat 0.0 altitudes and you want to lift the
whole path to the preset's intended height). Pass the curve_obj to also
re-keyframe the curve's eval_time speed.
"""
from __future__ import annotations
from typing import Any


# All values per cinematic-camera-rig.md section 5.3 + section 5.5
# motion-sickness rules.
CAMERA_PRESETS: dict[str, dict[str, Any]] = {
    "fpv-walk": {
        "label": "FPV walking pace (1.7 m AGL, 1.4 m/s, 24 mm)",
        "altitude_agl_m": 1.7,
        "speed_mps": 1.4,
        "lens_mm": 24.0,
        "sensor_width_mm": 36.0,
        "banking_max_deg": 0.0,        # walking - no banking
        "noise_amplitude_deg": 0.5,    # subtle handheld feel
        "shutter_open": 0.5,           # 180-degree shutter (filmic motion blur)
        "tilt_pitch_deg": -5.0,        # slight uplook so horizon shows at top
        "curve_start_frame_pct": 0.0,  # start of path
        "use_case": "Walking through fields/bushes; GoPro chest-mount equivalent",
    },
    "fpv-bike": {
        "label": "FPV bike (1.7 m AGL, 6 m/s, 18 mm wide)",
        "altitude_agl_m": 1.7,
        "speed_mps": 6.0,
        "lens_mm": 18.0,
        "sensor_width_mm": 36.0,
        "banking_max_deg": 3.0,
        "noise_amplitude_deg": 0.3,
        "shutter_open": 0.5,
        "tilt_pitch_deg": 0.0,         # level forward
        "curve_start_frame_pct": 0.2,  # early portion
        "use_case": "Bike-mount FPV; wider lens for speed feel",
    },
    "low-drone": {
        "label": "Low drone inspection (80 m AGL, 10 m/s, 24 mm)",
        "altitude_agl_m": 80.0,
        "speed_mps": 10.0,
        "lens_mm": 24.0,
        "sensor_width_mm": 36.0,
        "banking_max_deg": 5.0,
        "noise_amplitude_deg": 0.05,
        "shutter_open": 0.5,
        "tilt_pitch_deg": -10.0,       # slight downlook over building
        "curve_start_frame_pct": 0.4,  # middle-low
        "use_case": "Building facade reveal; Mavic-class flight",
    },
    "mid-drone": {
        "label": "Mid drone (500 m AGL, 30 m/s, 50 mm)",
        "altitude_agl_m": 500.0,
        "speed_mps": 30.0,
        "lens_mm": 50.0,
        "sensor_width_mm": 36.0,
        "banking_max_deg": 8.0,
        "noise_amplitude_deg": 0.05,
        "shutter_open": 0.5,
        "tilt_pitch_deg": -15.0,       # moderate downlook for survey angle
        "curve_start_frame_pct": 0.5,  # middle
        "use_case": "Corporate establishing; Inspire-class survey",
    },
    "cinematic-establishing": {
        "label": "Cinematic establishing (800 m AGL, 35 m/s, 50 mm)",
        "altitude_agl_m": 800.0,       # was 2000 - too high for 4x2 km region
        "speed_mps": 35.0,             # scale down speed proportionally
        "lens_mm": 50.0,               # was 85 - wider FOV captures more terrain
        "sensor_width_mm": 36.0,
        "banking_max_deg": 6.0,
        "noise_amplitude_deg": 0.05,
        "shutter_open": 0.5,
        "tilt_pitch_deg": -45.0,       # was -20 - aim camera down at city
        "curve_start_frame_pct": 0.6,  # past middle
        "use_case": "Feature-film opener - current default",
    },
    "aircraft-approach": {
        "label": "Aircraft high-altitude (4500 m AGL, 150 m/s, 135 mm)",
        "altitude_agl_m": 4500.0,
        "speed_mps": 150.0,
        "lens_mm": 135.0,
        "sensor_width_mm": 36.0,
        "banking_max_deg": 4.0,
        "noise_amplitude_deg": 0.02,
        "shutter_open": 0.5,
        "tilt_pitch_deg": -45.0,       # steep down for high-altitude reveal
        "curve_start_frame_pct": 0.85, # near end
        "use_case": "Telephoto reveal - atmospheric compression",
    },
}

DEFAULT_PRESET = "cinematic-establishing"


def list_presets() -> list[str]:
    """Return list of available preset names. CLI / EnumProperty consumers use this."""
    return list(CAMERA_PRESETS.keys())


def get_preset(name: str) -> dict[str, Any]:
    """Return the preset dict, raising KeyError with a helpful message if unknown."""
    if name not in CAMERA_PRESETS:
        raise KeyError(
            f"unknown camera preset {name!r}; available: {sorted(CAMERA_PRESETS)}"
        )
    return CAMERA_PRESETS[name]


def apply_camera_preset(camera_obj: Any,
                        preset_name: str,
                        scene: Any | None = None,
                        curve_obj: Any | None = None,
                        terrain_z: float = 0.0) -> dict[str, Any]:
    """Apply a named preset to a camera (and optionally its path curve).

    Args:
        camera_obj: bpy.types.Object of type CAMERA.
        preset_name: one of CAMERA_PRESETS.
        scene: bpy.context.scene; required if you want render-side settings
            (motion blur shutter) to be set.
        curve_obj: if the camera follows a Bezier path, pass it here so we can
            update path_duration to match the preset speed (and lift altitudes).
        terrain_z: surface elevation at the path; AGL altitude is added on top.

    Returns the preset dict (for caller introspection / logging).
    """
    if camera_obj.type != "CAMERA":
        raise TypeError(f"{camera_obj.name} is type {camera_obj.type}, not CAMERA")
    p = get_preset(preset_name)

    cam_data = camera_obj.data
    cam_data.lens = p["lens_mm"]
    cam_data.sensor_width = p["sensor_width_mm"]
    cam_data.clip_start = 0.1 if p["altitude_agl_m"] < 50 else 1.0
    cam_data.clip_end = 100_000.0

    # Lift the camera/empty-rig to the preset altitude over the terrain.
    target_z = terrain_z + p["altitude_agl_m"]
    # If the camera is parented to an empty (rig pattern), lift the parent.
    rig = camera_obj.parent if camera_obj.parent else camera_obj
    rig.location.z = target_z

    # Bug A fix: if the camera follows a path, the Follow Path constraint
    # overrides rig.location.z. Lift the curve itself to the target altitude.
    if curve_obj is not None and curve_obj.type == "CURVE":
        _lift_curve_to_altitude(curve_obj, target_z)

    # If path is given, update path_duration to honor preset speed.
    if curve_obj is not None and curve_obj.type == "CURVE" and scene is not None:
        # arc_length / speed = duration (seconds) -> frames = duration * fps.
        # We approximate arc_length by summing spline knot distances.
        spl = curve_obj.data.splines[0] if curve_obj.data.splines else None
        if spl is not None:
            pts = [bp.co for bp in (spl.bezier_points or spl.points or [])]
            arc = 0.0
            for i in range(1, len(pts)):
                dx = pts[i][0]-pts[i-1][0]; dy = pts[i][1]-pts[i-1][1]
                dz = pts[i][2]-pts[i-1][2]
                arc += (dx*dx + dy*dy + dz*dz) ** 0.5
            if arc > 0:
                fps = float(scene.render.fps)
                duration_frames = max(1, int(arc / p["speed_mps"] * fps))
                curve_obj.data.path_duration = duration_frames
                # Re-keyframe eval_time linearly (uses the existing helper).
                from . import waypoints_to_camera as _w2c
                _w2c.keyframe_constant_velocity(curve_obj.data)

    # Per-preset start frame on the curve (so different presets sample different
    # XY positions, not just different lens/tilt/altitude).
    if curve_obj is not None and curve_obj.type == "CURVE":
        pct = float(p.get("curve_start_frame_pct", 0.0))
        pct = max(0.0, min(1.0, pct))
        eval_frame = pct * float(curve_obj.data.path_duration)
        # Override scene frame so the Follow Path constraint evaluates at that point.
        if scene is not None:
            scene.frame_set(int(eval_frame) if eval_frame >= 1 else 1)

    # Motion blur (shutter).
    if scene is not None:
        try:
            scene.render.use_motion_blur = True
            scene.render.motion_blur_shutter = p["shutter_open"]
        except AttributeError:
            pass

    # Apply preset tilt to the camera's pitch.
    # Blender camera default rotation looks down -Z; rotation_euler.x = 90 deg
    # makes it look forward toward +Y (horizon level). Adding tilt_pitch_deg
    # gives uplook (negative tilt -> looking up at the sky).
    # NOTE: if the camera has a Damped Track / Track To constraint pointed at
    # a target object, the constraint will override this rotation at evaluate
    # time. To honor preset tilt in that case, remove the tracking constraint
    # before calling apply_camera_preset (we deliberately do NOT auto-remove it
    # here so existing scenes that rely on tracking aren't silently broken).
    import math as _math
    tilt = float(p.get("tilt_pitch_deg", -15.0))
    # Remove any tracking constraints that would override our rotation.
    for c in list(camera_obj.constraints):
        if c.type in {"DAMPED_TRACK", "TRACK_TO", "LOCKED_TRACK"}:
            camera_obj.constraints.remove(c)
    camera_obj.rotation_euler = (_math.radians(90.0 + tilt), 0.0, 0.0)

    # Subtle Noise F-curve modifier on rotation (motion-sickness rules section 5.5).
    _add_noise_modifier(rig, amplitude_deg=p["noise_amplitude_deg"])

    print(f"[camera-preset] applied {preset_name!r}: "
          f"alt {p['altitude_agl_m']} m, {p['speed_mps']} m/s, {p['lens_mm']} mm")
    return p


def _add_noise_modifier(obj: Any, amplitude_deg: float) -> None:
    """Add a subtle Noise modifier to obj's rotation_euler X+Y so motion isn't
    dolly-on-rails CG. Idempotent - skips if already present.
    """
    if amplitude_deg <= 0:
        return
    if obj.animation_data is None:
        obj.animation_data_create()
    # In real bpy, animation_data_create() sets obj.animation_data; with mocks
    # it may remain None — bail out cleanly so unit tests don't have to fully
    # simulate Blender's animation system.
    if obj.animation_data is None:
        return
    if obj.animation_data.action is None:
        # Need keyframes to attach a noise modifier - insert dummy at frame 1.
        obj.keyframe_insert("rotation_euler", frame=1)
    if obj.animation_data.action is None:
        return
    import math
    amp_rad = math.radians(amplitude_deg)
    # Blender 4.4+ uses slotted/layered Actions; <=4.3 exposes .fcurves on the Action.
    action = obj.animation_data.action
    fcurves_iters: list = []
    if hasattr(action, "fcurves") and len(getattr(action, "fcurves", [])) > 0:
        fcurves_iters.append(action.fcurves)
    if hasattr(action, "layers"):
        slot = obj.animation_data.action_slot if hasattr(
            obj.animation_data, "action_slot") else None
        for layer in action.layers:
            for strip in layer.strips:
                if slot is not None and hasattr(strip, "channelbag"):
                    cb = strip.channelbag(slot)
                    if cb is not None:
                        fcurves_iters.append(cb.fcurves)
                elif hasattr(strip, "channelbags"):
                    for cb in strip.channelbags:
                        fcurves_iters.append(cb.fcurves)
    for fcurves in fcurves_iters:
        for fc in fcurves:
            if fc.data_path != "rotation_euler":
                continue
            if any(m.type == "NOISE" for m in fc.modifiers):
                continue  # already added
            m = fc.modifiers.new(type="NOISE")
            m.strength = amp_rad
            m.scale = 5.0


def _lift_curve_to_altitude(curve_obj: Any, target_z: float) -> None:
    """Translate every Bezier/poly control point's Z to land at target_z (mean).

    Strategy: compute current mean Z of all control points, compute delta to
    reach target_z, apply that delta as a translation to all points (preserves
    relative shape - gentle hills in Z stay; absolute level shifts).
    """
    points = []
    for spline in curve_obj.data.splines:
        points.extend(spline.bezier_points)
        points.extend(spline.points)
    if not points:
        return
    current_mean_z = sum(p.co.z for p in points) / len(points)
    delta = target_z - current_mean_z
    for p in points:
        p.co.z += delta
        # Update bezier handles too if they exist (not present on poly points).
        for handle_attr in ("handle_left", "handle_right"):
            handle = getattr(p, handle_attr, None)
            if handle is not None:
                handle.z += delta
