"""Tests for blender_tools.terrain_setup.

Pure-Python helpers are tested directly.
bpy-dependent functions are tested via unittest.mock.MagicMock injected into
sys.modules["bpy"] so tests run in standard CPython (no Blender needed).
"""
from __future__ import annotations

import sys
import importlib
import pytest
from unittest.mock import MagicMock, patch, call


from blender_tools.terrain_setup import (
    compute_plane_dimensions,
    apply_anchor_shift,
    heightmap_material_settings,
)


# ---------------------------------------------------------------------------
# TestComputePlaneDimensions
# ---------------------------------------------------------------------------


class TestComputePlaneDimensions:
    def test_level_0(self):
        """Level-0 → 1 segment → 2 vertices per side."""
        x, y, verts = compute_plane_dimensions((1000.0, 1000.0), 0)
        assert (x, y) == (1000.0, 1000.0)
        assert verts == 2  # 2**0 + 1

    def test_level_1(self):
        """Level-1 → 2 segments → 3 vertices per side."""
        _, _, verts = compute_plane_dimensions((500.0, 200.0), 1)
        assert verts == 3  # 2**1 + 1

    def test_level_11_standard(self):
        """Standard terrain subdivision level used by the playbook."""
        x, y, verts = compute_plane_dimensions((10000.0, 4000.0), 11)
        assert (x, y) == (10000.0, 4000.0)
        assert verts == (1 << 11) + 1  # 2049

    def test_level_14_maximum(self):
        """Level 14 is the documented maximum."""
        _, _, verts = compute_plane_dimensions((1.0, 1.0), 14)
        assert verts == (1 << 14) + 1  # 16385

    def test_returns_exact_input_dimensions(self):
        """Dimensions in the return value must be identical to the inputs."""
        x, y, _ = compute_plane_dimensions((123.456, 789.012), 5)
        assert x == pytest.approx(123.456)
        assert y == pytest.approx(789.012)

    def test_rejects_negative_subdivisions(self):
        with pytest.raises(ValueError, match="subdivisions out of range"):
            compute_plane_dimensions((1000.0, 1000.0), -1)

    def test_rejects_huge_subdivisions(self):
        with pytest.raises(ValueError, match="subdivisions out of range"):
            compute_plane_dimensions((1000.0, 1000.0), 15)

    def test_rejects_zero_x_size(self):
        with pytest.raises(ValueError, match="size_meters must be positive"):
            compute_plane_dimensions((0.0, 1000.0), 5)

    def test_rejects_zero_y_size(self):
        with pytest.raises(ValueError, match="size_meters must be positive"):
            compute_plane_dimensions((1000.0, 0.0), 5)

    def test_rejects_negative_size(self):
        with pytest.raises(ValueError, match="size_meters must be positive"):
            compute_plane_dimensions((-1000.0, 1000.0), 5)

    def test_rejects_negative_y_size(self):
        with pytest.raises(ValueError, match="size_meters must be positive"):
            compute_plane_dimensions((1000.0, -500.0), 5)


# ---------------------------------------------------------------------------
# TestApplyAnchorShift
# ---------------------------------------------------------------------------


class TestApplyAnchorShift:
    def test_zero_anchor_identity(self):
        """Zero anchor → output equals input."""
        result = apply_anchor_shift((100.0, 200.0, 50.0), (0.0, 0.0, 0.0))
        assert result == (100.0, 200.0, 50.0)

    def test_bavarian_shift(self):
        """Munich city centre E=690000 N=5334000 shifted by corridor anchor."""
        shifted = apply_anchor_shift(
            (690000.0, 5334000.0, 520.0),
            (700000.0, 5335000.0, 0.0),
        )
        assert shifted == (-10000.0, -1000.0, 520.0)

    def test_full_anchor_subtraction(self):
        """All three components are independently subtracted."""
        result = apply_anchor_shift((10.0, 20.0, 30.0), (1.0, 2.0, 3.0))
        assert result == (9.0, 18.0, 27.0)

    def test_result_is_tuple(self):
        """Return type is a tuple, not a list or generator."""
        result = apply_anchor_shift((1.0, 2.0, 3.0), (0.0, 0.0, 0.0))
        assert isinstance(result, tuple)

    def test_negative_anchor_adds(self):
        """Negative anchor values effectively add to the world coordinate."""
        result = apply_anchor_shift((0.0, 0.0, 0.0), (-100.0, -200.0, -50.0))
        assert result == (100.0, 200.0, 50.0)


# ---------------------------------------------------------------------------
# TestHeightmapMaterialSettings
# ---------------------------------------------------------------------------


class TestHeightmapMaterialSettings:
    def test_returns_required_keys(self):
        settings = heightmap_material_settings()
        assert "colorspace" in settings
        assert "interpolation" in settings
        assert "extension" in settings

    def test_colorspace_is_non_color(self):
        """Non-Color prevents gamma shift on linear elevation data."""
        assert heightmap_material_settings()["colorspace"] == "Non-Color"

    def test_interpolation_is_cubic(self):
        """Cubic prevents faceted terraces on grazing slopes."""
        assert heightmap_material_settings()["interpolation"] == "Cubic"

    def test_extension_is_extend(self):
        """EXTEND prevents seam artefacts at corridor edges."""
        assert heightmap_material_settings()["extension"] == "EXTEND"

    def test_no_unexpected_keys(self):
        """Settings dict must contain exactly the three documented keys."""
        assert set(heightmap_material_settings().keys()) == {"colorspace", "interpolation", "extension"}

    def test_returns_new_dict_each_call(self):
        """Each call returns a fresh dict; mutations don't propagate."""
        s1 = heightmap_material_settings()
        s2 = heightmap_material_settings()
        s1["colorspace"] = "sRGB"
        assert s2["colorspace"] == "Non-Color"


# ---------------------------------------------------------------------------
# TestBuildTerrainUnderMockedBpy
# ---------------------------------------------------------------------------


class TestBuildTerrainUnderMockedBpy:
    """Tests for build_terrain_from_heightmap using a mocked bpy module.

    The fixture installs a MagicMock at sys.modules["bpy"] so the function
    can be imported and executed without a real Blender installation.
    """

    @pytest.fixture(autouse=True)
    def mock_bpy(self):
        """Install a minimal bpy mock and reload the module so _require_bpy picks it up."""
        fake_bpy = MagicMock()

        # Scene with subscript assignment tracking.
        fake_scene = MagicMock()
        fake_bpy.context.scene = fake_scene

        # Collections: first call to .get returns None (→ new collection created).
        fake_bpy.data.collections.get.return_value = None
        fake_bpy.data.collections.new.return_value = MagicMock()

        # Texture factory.
        fake_bpy.data.textures.new.return_value = MagicMock()

        # Image factory: empty existing images list; load returns a mock with colorspace.
        fake_bpy.data.images.__iter__ = lambda self_: iter([])
        loaded_image = MagicMock()
        loaded_image.colorspace_settings = MagicMock()
        fake_bpy.data.images.load.return_value = loaded_image

        # active_object (the plane) with modifier side-effects.
        fake_plane = MagicMock()
        subsurf_mod = MagicMock()
        displace_mod = MagicMock()

        def _modifier_factory(name, type):  # noqa: A002
            if type == "SUBSURF":
                return subsurf_mod
            if type == "DISPLACE":
                return displace_mod
            return MagicMock()

        fake_plane.modifiers.new.side_effect = _modifier_factory
        fake_plane.users_collection = []  # no collections to unlink from
        fake_bpy.context.active_object = fake_plane

        # Expose sub-mocks for assertions in tests.
        fake_bpy._test_plane = fake_plane
        fake_bpy._test_subsurf_mod = subsurf_mod
        fake_bpy._test_displace_mod = displace_mod
        fake_bpy._test_loaded_image = loaded_image

        sys.modules["bpy"] = fake_bpy
        yield fake_bpy
        sys.modules.pop("bpy", None)  # tolerates tests that already removed it

    def _call(self, **kwargs):
        """Import (or re-import) after bpy mock is in place and call the function."""
        # Force fresh import so _require_bpy resolves the mocked sys.modules entry.
        import importlib
        import blender_tools.terrain_setup as mod
        importlib.reload(mod)
        defaults = dict(
            heightmap_exr="out/test.exr",
            size_meters=(10000.0, 4000.0),
            subdivisions=3,
            anchor_utm32n=(701000.0, 5338000.0, 500.0),
        )
        defaults.update(kwargs)
        return mod.build_terrain_from_heightmap(**defaults), mod

    def test_anchor_stored_on_scene(self, mock_bpy):
        """utm32n_anchor must be written as a list to scene custom props."""
        self._call(anchor_utm32n=(701000.0, 5338000.0, 500.0))
        mock_bpy.context.scene.__setitem__.assert_any_call(
            "utm32n_anchor", [701000.0, 5338000.0, 500.0]
        )

    def test_subsurf_modifier_is_simple(self, mock_bpy):
        """Subsurf modifier subdivision_type must be set to SIMPLE."""
        self._call(subdivisions=3)
        subsurf = mock_bpy._test_subsurf_mod
        assert subsurf.subdivision_type == "SIMPLE"

    def test_subsurf_levels_match_subdivisions(self, mock_bpy):
        """Subsurf levels and render_levels must match the requested subdivisions."""
        self._call(subdivisions=7)
        subsurf = mock_bpy._test_subsurf_mod
        assert subsurf.levels == 7
        assert subsurf.render_levels == 7

    def test_displace_strength(self, mock_bpy):
        """Displace modifier strength must match the argument."""
        self._call(strength=2.5)
        displace = mock_bpy._test_displace_mod
        assert displace.strength == 2.5

    def test_displace_mid_level(self, mock_bpy):
        """Displace modifier mid_level must match the argument."""
        self._call(mid_level=0.5)
        displace = mock_bpy._test_displace_mod
        assert displace.mid_level == 0.5

    def test_displace_texture_coords_uv(self, mock_bpy):
        """Displace modifier must use UV texture coordinates."""
        self._call()
        assert mock_bpy._test_displace_mod.texture_coords == "UV"

    def test_heightmap_image_loaded(self, mock_bpy):
        """bpy.data.images.load must be called when no existing image matches."""
        self._call(heightmap_exr="out/test.exr")
        mock_bpy.data.images.load.assert_called_once()

    def test_heightmap_colorspace_non_color(self, mock_bpy):
        """Loaded image colorspace must be set to Non-Color."""
        self._call()
        assert mock_bpy._test_loaded_image.colorspace_settings.name == "Non-Color"

    def test_new_collection_created_when_absent(self, mock_bpy):
        """A new Blender collection is created when it doesn't already exist."""
        mock_bpy.data.collections.get.return_value = None
        self._call(collection_name="Terrain")
        mock_bpy.data.collections.new.assert_called_once_with("Terrain")

    def test_existing_collection_reused(self, mock_bpy):
        """If a collection with the name exists, no new one is created."""
        existing_coll = MagicMock()
        mock_bpy.data.collections.get.return_value = existing_coll
        self._call(collection_name="Terrain")
        mock_bpy.data.collections.new.assert_not_called()

    def test_returns_plane_object(self, mock_bpy):
        """build_terrain_from_heightmap must return the created plane object."""
        result, _ = self._call()
        assert result is mock_bpy._test_plane

    def test_raises_helpful_error_outside_blender(self):
        """_require_bpy raises RuntimeError with 'blender' when bpy is not available."""
        # Ensure bpy is NOT in sys.modules for this test.
        sys.modules.pop("bpy", None)
        import importlib
        import blender_tools.terrain_setup as mod
        importlib.reload(mod)
        with pytest.raises(RuntimeError) as exc:
            mod._require_bpy()
        assert "blender" in str(exc.value).lower()

    def test_import_succeeds_without_bpy(self):
        """The module must be importable in plain CPython (bpy import is lazy)."""
        sys.modules.pop("bpy", None)
        import importlib
        import blender_tools.terrain_setup as mod
        importlib.reload(mod)
        # If we get here without ImportError, the guard is working correctly.
        assert callable(mod.compute_plane_dimensions)
        assert callable(mod.build_terrain_from_heightmap)


# ---------------------------------------------------------------------------
# Shared ortho-drape test helpers
# ---------------------------------------------------------------------------


class FakeSocket:
    def __init__(self, name): self.name = name; self.default_value = None


_TYPE_MAP = {
    "ShaderNodeOutputMaterial": "OUTPUT_MATERIAL",
    "ShaderNodeBsdfPrincipled": "BSDF_PRINCIPLED",
    "ShaderNodeTexImage": "TEX_IMAGE",
    "ShaderNodeUVMap": "UVMAP",
}


class FakeNode:
    def __init__(self, t):
        self.type = _TYPE_MAP.get(t, t)
        self.image = None; self.extension = None
        self.uv_map = ""
        self.inputs = _SocketDict()
        self.outputs = _SocketDict()


class _SocketDict(dict):
    def __getitem__(self, k):
        if not dict.__contains__(self, k):
            dict.__setitem__(self, k, FakeSocket(k))
        return dict.__getitem__(self, k)
    def __contains__(self, k):
        return True


class FakeNodeList(list):
    def new(self, t):
        n = FakeNode(t); self.append(n); return n
    def remove(self, n):
        list.remove(self, n)


class FakeLinkList(list):
    def new(self, a, b):
        self.append((a, b)); return (a, b)


class FakeNodeTree:
    def __init__(self):
        self.nodes = FakeNodeList(); self.links = FakeLinkList()


class FakeMaterial:
    def __init__(self, name):
        self.name = name; self.use_nodes = False
        self.node_tree = FakeNodeTree()


class FakeImage:
    def __init__(self, name):
        self.name = name; self.source = None; self.tiles = FakeTileList()


class FakeTileList(list):
    def new(self, tile_number=0, label=""):
        self.append({"tile_number": tile_number, "label": label})


class FakeUVLoop:
    def __init__(self, u, v):
        self.uv = type("Vec", (), {"x": u, "y": v})()


class FakeUVLayer:
    def __init__(self, loops):
        self.data = loops


class FakeUVLayers:
    """Mimics bpy mesh.uv_layers with .new(), .active, and truthiness."""

    def __init__(self, layers=None):
        self._layers = layers or []
        self.active = self._layers[0] if self._layers else None

    def __bool__(self):
        return len(self._layers) > 0

    def new(self, name=""):
        # Blender's uv_layers.new() creates a layer with the same loop count.
        loop_count = len(self.active.data) if self.active else 0
        new_loops = [FakeUVLoop(0.0, 0.0) for _ in range(loop_count)]
        layer = FakeUVLayer(new_loops)
        layer.name = name
        self._layers.append(layer)
        return layer

    def __iter__(self):
        return iter(self._layers)

    def __len__(self):
        return len(self._layers)


def _make_ortho_drape_fakes(uv_loops=None):
    """Build fake bpy + mesh object with optional UV data for ortho-drape tests."""
    captured = {}

    class FakeData:
        def __init__(self): self.materials = self; self.images = self
        def new(self, name): captured["last"] = FakeMaterial(name); return captured["last"]
        def load(self, fp, check_existing=False): return FakeImage(fp)

    class FakeMesh:
        def __init__(self):
            self.materials = []
            if uv_loops is not None:
                base_layer = FakeUVLayer(uv_loops)
                base_layer.name = "UVMap"
                self.uv_layers = FakeUVLayers([base_layer])
            else:
                self.uv_layers = FakeUVLayers()

    class FakeObj:
        def __init__(self): self.data = FakeMesh()

    fake_bpy = type("B", (), {"data": FakeData()})()
    return fake_bpy, FakeObj(), captured


# ---------------------------------------------------------------------------
# TestApplyOrthoDrape
# ---------------------------------------------------------------------------


def test_apply_ortho_drape_builds_udim_material(monkeypatch, tmp_path):
    """apply_ortho_drape attaches a Principled BSDF + UDIM Image Texture."""
    from blender_tools import terrain_setup

    for udim in (1001, 1002, 1011):
        (tmp_path / f"ortho.{udim}.jpg").write_bytes(b"fake")

    fake_bpy, obj, _ = _make_ortho_drape_fakes()
    monkeypatch.setattr(terrain_setup, "_require_bpy", lambda: fake_bpy)
    mat = terrain_setup.apply_ortho_drape(obj, tmp_path)
    assert mat.use_nodes is True
    types = [n.type for n in mat.node_tree.nodes]
    assert "TEX_IMAGE" in types
    assert "BSDF_PRINCIPLED" in types
    assert "OUTPUT_MATERIAL" in types


def test_apply_ortho_drape_ortho_uv_scaled_for_multi_tile(monkeypatch, tmp_path):
    """OrthoUV layer must be scaled to span the full UDIM grid.

    For a 2x2 grid, the OrthoUV at (1.0, 1.0) must become (2.0, 2.0).
    """
    from blender_tools import terrain_setup

    for udim in (1001, 1002, 1011, 1012):
        (tmp_path / f"ortho.{udim}.jpg").write_bytes(b"fake")

    loops = [
        FakeUVLoop(0.0, 0.0),
        FakeUVLoop(1.0, 0.0),
        FakeUVLoop(1.0, 1.0),
        FakeUVLoop(0.0, 1.0),
    ]
    fake_bpy, obj, _ = _make_ortho_drape_fakes(uv_loops=loops)
    monkeypatch.setattr(terrain_setup, "_require_bpy", lambda: fake_bpy)
    terrain_setup.apply_ortho_drape(obj, tmp_path)

    ortho_layer = [l for l in obj.data.uv_layers if l.name == "OrthoUV"][0]
    assert ortho_layer.data[0].uv.x == pytest.approx(0.0)
    assert ortho_layer.data[0].uv.y == pytest.approx(0.0)
    assert ortho_layer.data[1].uv.x == pytest.approx(2.0)
    assert ortho_layer.data[1].uv.y == pytest.approx(0.0)
    assert ortho_layer.data[2].uv.x == pytest.approx(2.0)
    assert ortho_layer.data[2].uv.y == pytest.approx(2.0)
    assert ortho_layer.data[3].uv.x == pytest.approx(0.0)
    assert ortho_layer.data[3].uv.y == pytest.approx(2.0)


def test_apply_ortho_drape_single_tile_ortho_uv_stays_0_1(monkeypatch, tmp_path):
    """With only tile 1001 (1x1 grid), OrthoUV should stay in the 0-1 range."""
    from blender_tools import terrain_setup

    (tmp_path / "ortho.1001.jpg").write_bytes(b"fake")

    loops = [FakeUVLoop(0.5, 0.5), FakeUVLoop(1.0, 1.0)]
    fake_bpy, obj, _ = _make_ortho_drape_fakes(uv_loops=loops)
    monkeypatch.setattr(terrain_setup, "_require_bpy", lambda: fake_bpy)
    terrain_setup.apply_ortho_drape(obj, tmp_path)

    ortho_layer = [l for l in obj.data.uv_layers if l.name == "OrthoUV"][0]
    assert ortho_layer.data[0].uv.x == pytest.approx(0.5)
    assert ortho_layer.data[0].uv.y == pytest.approx(0.5)
    assert ortho_layer.data[1].uv.x == pytest.approx(1.0)
    assert ortho_layer.data[1].uv.y == pytest.approx(1.0)


def test_apply_ortho_drape_wide_grid_scales_u_only(monkeypatch, tmp_path):
    """A 4x1 grid should scale OrthoUV U by 4, leave V at 1."""
    from blender_tools import terrain_setup

    for u in range(4):
        (tmp_path / f"ortho.{1001 + u}.jpg").write_bytes(b"fake")

    loops = [FakeUVLoop(1.0, 1.0)]
    fake_bpy, obj, _ = _make_ortho_drape_fakes(uv_loops=loops)
    monkeypatch.setattr(terrain_setup, "_require_bpy", lambda: fake_bpy)
    terrain_setup.apply_ortho_drape(obj, tmp_path)

    ortho_layer = [l for l in obj.data.uv_layers if l.name == "OrthoUV"][0]
    assert ortho_layer.data[0].uv.x == pytest.approx(4.0)
    assert ortho_layer.data[0].uv.y == pytest.approx(1.0)


def test_apply_ortho_drape_image_set_to_tiled(monkeypatch, tmp_path):
    """The loaded image must have source set to TILED for UDIM."""
    from blender_tools import terrain_setup

    for udim in (1001, 1002):
        (tmp_path / f"ortho.{udim}.jpg").write_bytes(b"fake")

    captured_images = []

    class TrackingImage(FakeImage):
        def __init__(self, name):
            super().__init__(name)
            captured_images.append(self)

    fake_bpy, obj, _ = _make_ortho_drape_fakes()
    # Patch the load method to track the created image.
    fake_bpy.data.load = lambda fp, check_existing=False: TrackingImage(fp)
    monkeypatch.setattr(terrain_setup, "_require_bpy", lambda: fake_bpy)
    terrain_setup.apply_ortho_drape(obj, tmp_path)

    assert len(captured_images) == 1
    assert captured_images[0].source == "TILED"


def test_apply_ortho_drape_registers_extra_tiles(monkeypatch, tmp_path):
    """Tiles beyond 1001 must be registered on the image's tiles collection."""
    from blender_tools import terrain_setup

    for udim in (1001, 1002, 1003, 1011):
        (tmp_path / f"ortho.{udim}.jpg").write_bytes(b"fake")

    fake_bpy, obj, _ = _make_ortho_drape_fakes()
    loaded_img = None

    class CapturingData:
        def __init__(self): self.materials = self; self.images = self
        def new(self, name): return FakeMaterial(name)
        def load(self, fp, check_existing=False):
            nonlocal loaded_img
            loaded_img = FakeImage(fp)
            return loaded_img

    fake_bpy.data = CapturingData()
    monkeypatch.setattr(terrain_setup, "_require_bpy", lambda: fake_bpy)
    terrain_setup.apply_ortho_drape(obj, tmp_path)

    registered_udims = [t["tile_number"] for t in loaded_img.tiles]
    assert 1002 in registered_udims
    assert 1003 in registered_udims
    assert 1011 in registered_udims
    assert 1001 not in registered_udims  # implicit first tile


def test_apply_ortho_drape_does_not_modify_original_uvs(monkeypatch, tmp_path):
    """Original UV layer (used by displacement) must NOT be modified.

    This is the bug that caused height data to get scrambled when ortho was
    applied after heightmap: the displacement modifier samples via the same
    UV layer, so scaling it to UDIM range breaks heightmap sampling.
    """
    from blender_tools import terrain_setup

    for udim in (1001, 1002, 1011, 1012):
        (tmp_path / f"ortho.{udim}.jpg").write_bytes(b"fake")

    original_loops = [
        FakeUVLoop(0.0, 0.0),
        FakeUVLoop(0.5, 0.0),
        FakeUVLoop(1.0, 1.0),
        FakeUVLoop(0.0, 1.0),
    ]
    fake_bpy, obj, _ = _make_ortho_drape_fakes(uv_loops=original_loops)
    monkeypatch.setattr(terrain_setup, "_require_bpy", lambda: fake_bpy)
    terrain_setup.apply_ortho_drape(obj, tmp_path)

    # Original UVs must be untouched (still 0-1 range for displacement).
    assert original_loops[0].uv.x == pytest.approx(0.0)
    assert original_loops[0].uv.y == pytest.approx(0.0)
    assert original_loops[1].uv.x == pytest.approx(0.5)
    assert original_loops[1].uv.y == pytest.approx(0.0)
    assert original_loops[2].uv.x == pytest.approx(1.0)
    assert original_loops[2].uv.y == pytest.approx(1.0)
    assert original_loops[3].uv.x == pytest.approx(0.0)
    assert original_loops[3].uv.y == pytest.approx(1.0)


def test_apply_ortho_drape_creates_separate_uv_layer(monkeypatch, tmp_path):
    """A new UV layer named 'OrthoUV' must be created for UDIM sampling."""
    from blender_tools import terrain_setup

    for udim in (1001, 1002):
        (tmp_path / f"ortho.{udim}.jpg").write_bytes(b"fake")

    loops = [FakeUVLoop(0.0, 0.0), FakeUVLoop(1.0, 1.0)]
    fake_bpy, obj, _ = _make_ortho_drape_fakes(uv_loops=loops)
    monkeypatch.setattr(terrain_setup, "_require_bpy", lambda: fake_bpy)
    terrain_setup.apply_ortho_drape(obj, tmp_path)

    layer_names = [l.name for l in obj.data.uv_layers]
    assert "UVMap" in layer_names, "Original UV layer must still exist"
    assert "OrthoUV" in layer_names, "Ortho UV layer must be created"


def test_apply_ortho_drape_material_references_ortho_uv(monkeypatch, tmp_path):
    """The UVMap node in the material must reference the OrthoUV layer."""
    from blender_tools import terrain_setup

    for udim in (1001, 1002):
        (tmp_path / f"ortho.{udim}.jpg").write_bytes(b"fake")

    loops = [FakeUVLoop(0.0, 0.0), FakeUVLoop(1.0, 1.0)]
    fake_bpy, obj, _ = _make_ortho_drape_fakes(uv_loops=loops)
    monkeypatch.setattr(terrain_setup, "_require_bpy", lambda: fake_bpy)
    mat = terrain_setup.apply_ortho_drape(obj, tmp_path)

    uv_nodes = [n for n in mat.node_tree.nodes if n.type == "UVMAP"]
    assert len(uv_nodes) == 1
    assert uv_nodes[0].uv_map == "OrthoUV"


# ---------------------------------------------------------------------------
# TestAutoSubdivisionCalculation
# ---------------------------------------------------------------------------


class TestAutoSubdivisionCalculation:
    """Test the auto-subdivision logic from the heightmap import operator.

    The formula: subdivisions = ceil(log2(max_dim_m / pixel_res)), clamped [6, 14].
    We test the math directly since the operator is bpy-dependent.
    """

    @staticmethod
    def _calc_auto_subdivisions(size_x, size_y, pixel_x, pixel_y):
        import math
        max_dim_m = max(size_x, size_y)
        pixel_res = min(pixel_x, pixel_y)
        vertices_needed = max_dim_m / pixel_res
        return max(6, min(14, int(math.ceil(math.log2(vertices_needed)))))

    def test_8km_dgm1_gets_13(self):
        """8km DGM1 (1m pixels) → 8000 vertices needed → log2(8000) ≈ 13."""
        assert self._calc_auto_subdivisions(8000, 4000, 1.0, 1.0) == 13

    def test_2km_dgm1_gets_11(self):
        """2km DGM1 (1m pixels) → 2000 vertices → log2(2000) ≈ 11."""
        assert self._calc_auto_subdivisions(2000, 1000, 1.0, 1.0) == 11

    def test_2km_dgm5_gets_9(self):
        """2km DGM5 (5m pixels) → 400 vertices → log2(400) ≈ 9."""
        assert self._calc_auto_subdivisions(2000, 1000, 5.0, 5.0) == 9

    def test_50m_scene_clamps_to_6(self):
        """Tiny 50m scene → 50 vertices → log2(50) ≈ 6. Clamped at minimum 6."""
        assert self._calc_auto_subdivisions(50, 50, 1.0, 1.0) == 6

    def test_huge_scene_clamps_to_14(self):
        """100km DGM1 → 100000 vertices → log2(100000) ≈ 17. Clamped at 14."""
        assert self._calc_auto_subdivisions(100000, 50000, 1.0, 1.0) == 14

    def test_uses_max_dimension(self):
        """The longer axis determines subdivision level."""
        sub_wide = self._calc_auto_subdivisions(8000, 1000, 1.0, 1.0)
        sub_tall = self._calc_auto_subdivisions(1000, 8000, 1.0, 1.0)
        assert sub_wide == sub_tall == 13

    def test_uses_finer_pixel_resolution(self):
        """When pixel_x != pixel_y, the finer resolution is used."""
        sub = self._calc_auto_subdivisions(4000, 4000, 1.0, 5.0)
        assert sub == 12  # 4000/1.0 = 4000, log2(4000) ≈ 12

    def test_exact_power_of_two(self):
        """1024m at 1m/px → exactly 1024 vertices → log2(1024) = 10."""
        assert self._calc_auto_subdivisions(1024, 512, 1.0, 1.0) == 10
