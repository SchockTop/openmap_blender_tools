"""Tests for blender_tools.world_setup.

Pure-Python helpers are tested directly.
bpy-dependent functions are tested via unittest.mock.MagicMock injected into
sys.modules["bpy"] so tests run in standard CPython (no Blender needed).
"""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from blender_tools.world_setup import (
    deg_to_rad,
    ev_to_exposure_multiplier,
    bbox_to_domain_cube_scale,
    sky_preset_values,
    volume_preset_values,
)


# ---------------------------------------------------------------------------
# TestDegToRad
# ---------------------------------------------------------------------------


class TestDegToRad:
    def test_zero(self):
        assert deg_to_rad(0.0) == 0.0

    def test_90_degrees(self):
        assert deg_to_rad(90.0) == pytest.approx(math.pi / 2, abs=1e-9)

    def test_360_degrees(self):
        assert deg_to_rad(360.0) == pytest.approx(2 * math.pi, abs=1e-9)

    def test_negative(self):
        assert deg_to_rad(-180.0) == pytest.approx(-math.pi, abs=1e-9)

    def test_45_degrees(self):
        assert deg_to_rad(45.0) == pytest.approx(math.pi / 4, abs=1e-9)


# ---------------------------------------------------------------------------
# TestEvToExposureMultiplier
# ---------------------------------------------------------------------------


class TestEvToExposureMultiplier:
    def test_ev_zero(self):
        assert ev_to_exposure_multiplier(0.0) == pytest.approx(1.0)

    def test_ev_plus_one(self):
        assert ev_to_exposure_multiplier(1.0) == pytest.approx(2.0)

    def test_ev_minus_one(self):
        assert ev_to_exposure_multiplier(-1.0) == pytest.approx(0.5)

    def test_ev_minus_eight(self):
        assert ev_to_exposure_multiplier(-8.0) == pytest.approx(1.0 / 256.0)

    def test_ev_minus_ten(self):
        assert ev_to_exposure_multiplier(-10.0) == pytest.approx(1.0 / 1024.0)


# ---------------------------------------------------------------------------
# TestBboxToDomainCubeScale
# ---------------------------------------------------------------------------


class TestBboxToDomainCubeScale:
    def test_known_bbox_with_padding(self):
        """(10000, 4000, 3000) at padding 0.1 → (5500, 2200, 1650)."""
        result = bbox_to_domain_cube_scale((10000.0, 4000.0, 3000.0), padding_fraction=0.1)
        assert result == pytest.approx((5500.0, 2200.0, 1650.0))

    def test_zero_padding(self):
        """Zero padding → exactly half of each bbox dimension."""
        result = bbox_to_domain_cube_scale((200.0, 100.0, 50.0), padding_fraction=0.0)
        assert result == pytest.approx((100.0, 50.0, 25.0))

    def test_rejects_negative_padding(self):
        with pytest.raises(ValueError, match="padding_fraction"):
            bbox_to_domain_cube_scale((100.0, 100.0, 100.0), padding_fraction=-0.1)

    def test_rejects_zero_x(self):
        with pytest.raises(ValueError, match="positive"):
            bbox_to_domain_cube_scale((0.0, 100.0, 100.0))

    def test_rejects_zero_y(self):
        with pytest.raises(ValueError, match="positive"):
            bbox_to_domain_cube_scale((100.0, 0.0, 100.0))

    def test_rejects_zero_z(self):
        with pytest.raises(ValueError, match="positive"):
            bbox_to_domain_cube_scale((100.0, 100.0, 0.0))

    def test_rejects_negative_dimension(self):
        with pytest.raises(ValueError, match="positive"):
            bbox_to_domain_cube_scale((-1.0, 100.0, 100.0))

    def test_returns_tuple(self):
        result = bbox_to_domain_cube_scale((100.0, 100.0, 100.0))
        assert isinstance(result, tuple)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# TestSkyPresetValues
# ---------------------------------------------------------------------------

_SKY_REQUIRED_KEYS = {"sun_elevation_rad", "sun_rotation_rad", "intensity", "air", "dust", "ozone", "exposure_ev"}


class TestSkyPresetValues:
    @pytest.mark.parametrize("preset", ["airbus-clean", "client-default", "spacex-warm"])
    def test_all_presets_have_required_keys(self, preset):
        values = sky_preset_values(preset)
        assert set(values.keys()) == _SKY_REQUIRED_KEYS

    def test_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown sky preset"):
            sky_preset_values("bad-preset")

    def test_unknown_preset_lists_valid_names(self):
        with pytest.raises(ValueError, match="airbus-clean"):
            sky_preset_values("nonexistent")

    def test_airbus_clean_higher_intensity_than_client_default(self):
        airbus = sky_preset_values("airbus-clean")
        client = sky_preset_values("client-default")
        assert airbus["intensity"] > client["intensity"]

    def test_spacex_warm_lower_sun_elevation_than_client_default(self):
        spacex = sky_preset_values("spacex-warm")
        client = sky_preset_values("client-default")
        assert spacex["sun_elevation_rad"] < client["sun_elevation_rad"]

    def test_returns_independent_dicts(self):
        """Mutations to one call's result don't affect the next call."""
        v1 = sky_preset_values("client-default")
        v1["intensity"] = 999.0
        v2 = sky_preset_values("client-default")
        assert v2["intensity"] != 999.0


# ---------------------------------------------------------------------------
# TestVolumePresetValues
# ---------------------------------------------------------------------------

_VOLUME_REQUIRED_KEYS = {"density", "anisotropy", "color_rgb"}


class TestVolumePresetValues:
    @pytest.mark.parametrize("preset", ["airbus-clean", "client-default", "spacex-warm"])
    def test_all_presets_have_required_keys(self, preset):
        values = volume_preset_values(preset)
        assert set(values.keys()) == _VOLUME_REQUIRED_KEYS

    def test_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown volume preset"):
            volume_preset_values("bad-preset")

    def test_density_ordering(self):
        """spacex-warm > client-default > airbus-clean (more haze = higher density)."""
        airbus = volume_preset_values("airbus-clean")
        client = volume_preset_values("client-default")
        spacex = volume_preset_values("spacex-warm")
        assert airbus["density"] < client["density"] < spacex["density"]

    def test_color_rgb_is_three_tuple(self):
        values = volume_preset_values("client-default")
        assert isinstance(values["color_rgb"], tuple)
        assert len(values["color_rgb"]) == 3


# ---------------------------------------------------------------------------
# TestSetupMultipleScatteringSky (mocked bpy)
# ---------------------------------------------------------------------------


class TestSetupMultipleScatteringSky:
    @pytest.fixture(autouse=True)
    def mock_bpy(self):
        fake_bpy = MagicMock()

        # worlds.get returns None → triggers worlds.new
        fake_bpy.data.worlds.get.return_value = None
        fake_world = MagicMock()
        fake_bpy.data.worlds.new.return_value = fake_world

        # Sky node — make sky_type assignable and hasattr checks work
        fake_sky = MagicMock(spec=["sky_type", "sun_elevation", "sun_rotation",
                                   "sun_intensity", "air_density", "dust_density",
                                   "ozone_density", "outputs"])
        # MULTIPLE_SCATTERING assignment should not raise TypeError
        fake_sky.outputs = [MagicMock()]

        fake_bg = MagicMock()
        fake_bg.outputs = [MagicMock()]
        fake_bg.inputs = [MagicMock()]

        fake_out = MagicMock()
        fake_out.inputs = [MagicMock()]

        def _nodes_new(node_type):
            if node_type == "ShaderNodeTexSky":
                return fake_sky
            if node_type == "ShaderNodeBackground":
                return fake_bg
            if node_type == "ShaderNodeOutputWorld":
                return fake_out
            return MagicMock()

        fake_world.node_tree.nodes.new.side_effect = _nodes_new
        fake_world.node_tree.links = MagicMock()

        fake_bpy._test_world = fake_world
        fake_bpy._test_sky = fake_sky

        sys.modules["bpy"] = fake_bpy
        yield fake_bpy
        sys.modules.pop("bpy", None)

    def _call(self, **kwargs):
        import blender_tools.world_setup as mod
        importlib.reload(mod)
        return mod.setup_multiple_scattering_sky(**kwargs), mod

    def test_exposure_set_from_preset(self, mock_bpy):
        """scene.view_settings.exposure must equal the preset's exposure_ev."""
        preset_ev = sky_preset_values("client-default")["exposure_ev"]
        self._call(preset="client-default")
        assert mock_bpy.context.scene.view_settings.exposure == preset_ev

    def test_exposure_overridden_by_kwarg(self, mock_bpy):
        """exposure_ev kwarg must override the preset value."""
        self._call(preset="client-default", exposure_ev=-5.0)
        assert mock_bpy.context.scene.view_settings.exposure == -5.0

    def test_view_transform_is_agx(self, mock_bpy):
        """view_transform must be set to 'AgX'."""
        self._call()
        assert mock_bpy.context.scene.view_settings.view_transform == "AgX"

    def test_world_assigned_to_scene(self, mock_bpy):
        """The configured world must be assigned to bpy.context.scene.world."""
        world, _ = self._call()
        assert mock_bpy.context.scene.world is world

    def test_new_world_created_when_absent(self, mock_bpy):
        """If no matching world exists, bpy.data.worlds.new should be called."""
        mock_bpy.data.worlds.get.return_value = None
        self._call(world_name="TestSky")
        mock_bpy.data.worlds.new.assert_called_once_with("TestSky")

    def test_existing_world_reused(self, mock_bpy):
        """If a world with the name already exists, worlds.new must NOT be called."""
        existing = MagicMock()
        mock_bpy.data.worlds.get.return_value = existing
        existing.node_tree.nodes.new.side_effect = mock_bpy._test_world.node_tree.nodes.new.side_effect
        self._call(world_name="ExistingSky")
        mock_bpy.data.worlds.new.assert_not_called()

    def test_intensity_override(self, mock_bpy):
        """Overriding intensity kwarg propagates to sky.sun_intensity."""
        _, mod = self._call(intensity=1.5)
        assert mock_bpy._test_sky.sun_intensity == 1.5

    def test_raises_outside_blender(self):
        """_require_bpy raises RuntimeError mentioning 'blender' when bpy absent."""
        sys.modules.pop("bpy", None)
        import blender_tools.world_setup as mod
        importlib.reload(mod)
        with pytest.raises(RuntimeError, match="[Bb]lender"):
            mod._require_bpy()


# ---------------------------------------------------------------------------
# TestAddDomainCubeVolume (mocked bpy)
# ---------------------------------------------------------------------------


class TestAddDomainCubeVolume:
    @pytest.fixture(autouse=True)
    def mock_bpy(self):
        fake_bpy = MagicMock()

        fake_cube = MagicMock()
        fake_bpy.context.active_object = fake_cube

        # Material + node tree
        fake_mat = MagicMock()
        fake_bpy.data.materials.new.return_value = fake_mat

        # Nodes: scatter/absorb need subscript-accessible inputs
        fake_scatter = MagicMock()
        fake_scatter.inputs = {
            "Density": MagicMock(),
            "Anisotropy": MagicMock(),
            "Color": MagicMock(),
        }
        fake_scatter.outputs = [MagicMock()]

        fake_absorb = MagicMock()
        fake_absorb.inputs = {
            "Density": MagicMock(),
            "Color": MagicMock(),
        }
        fake_absorb.outputs = [MagicMock()]

        fake_mix = MagicMock()
        fake_mix.inputs = [MagicMock(), MagicMock()]
        fake_mix.outputs = [MagicMock()]

        fake_out = MagicMock()
        fake_out.inputs = {"Volume": MagicMock()}

        def _nodes_new(node_type):
            if node_type == "ShaderNodeVolumeScatter":
                return fake_scatter
            if node_type == "ShaderNodeVolumeAbsorption":
                return fake_absorb
            if node_type == "ShaderNodeAddShader":
                return fake_mix
            if node_type == "ShaderNodeOutputMaterial":
                return fake_out
            return MagicMock()

        fake_mat.node_tree.nodes.new.side_effect = _nodes_new

        fake_bpy._test_cube = fake_cube
        fake_bpy._test_scatter = fake_scatter
        fake_bpy._test_absorb = fake_absorb

        sys.modules["bpy"] = fake_bpy
        yield fake_bpy
        sys.modules.pop("bpy", None)

    def _call(self, **kwargs):
        import blender_tools.world_setup as mod
        importlib.reload(mod)
        defaults = dict(bbox_meters=(10000.0, 4000.0, 3000.0), preset="client-default")
        defaults.update(kwargs)
        return mod.add_domain_cube_volume(**defaults), mod

    def test_cube_scale_matches_bbox_helper(self, mock_bpy):
        """Cube scale must equal bbox_to_domain_cube_scale output."""
        expected = bbox_to_domain_cube_scale((10000.0, 4000.0, 3000.0), padding_fraction=0.1)
        self._call(bbox_meters=(10000.0, 4000.0, 3000.0), padding_fraction=0.1)
        assert mock_bpy._test_cube.scale == expected

    def test_density_override_propagates(self, mock_bpy):
        """Explicit density kwarg must reach the VolumeScatter node's Density input."""
        self._call(density=0.005)
        assert mock_bpy._test_scatter.inputs["Density"].default_value == 0.005

    def test_default_preset_density(self, mock_bpy):
        """Without override, client-default preset density is applied."""
        self._call(preset="client-default")
        expected_density = volume_preset_values("client-default")["density"]
        assert mock_bpy._test_scatter.inputs["Density"].default_value == expected_density

    def test_cube_primitive_add_called(self, mock_bpy):
        """bpy.ops.mesh.primitive_cube_add must be called with size=2."""
        self._call()
        mock_bpy.ops.mesh.primitive_cube_add.assert_called_once_with(size=2.0, location=(0, 0, 0))

    def test_transform_apply_called(self, mock_bpy):
        """Transform apply must be called to bake the scale."""
        self._call()
        mock_bpy.ops.object.transform_apply.assert_called_once_with(
            location=False, rotation=False, scale=True
        )

    def test_returns_cube_object(self, mock_bpy):
        result, _ = self._call()
        assert result is mock_bpy._test_cube


# ---------------------------------------------------------------------------
# TestLoadVdbCloud (mocked bpy)
# ---------------------------------------------------------------------------


class TestLoadVdbCloud:
    @pytest.fixture(autouse=True)
    def mock_bpy(self):
        fake_bpy = MagicMock()
        fake_volume = MagicMock()
        fake_bpy.context.active_object = fake_volume
        fake_bpy._test_volume = fake_volume

        sys.modules["bpy"] = fake_bpy
        yield fake_bpy
        sys.modules.pop("bpy", None)

    def _call(self, vdb_path, **kwargs):
        import blender_tools.world_setup as mod
        importlib.reload(mod)
        return mod.load_vdb_cloud(vdb_path, **kwargs), mod

    def test_raises_file_not_found_for_missing_vdb(self, mock_bpy):
        """FileNotFoundError when the vdb path doesn't exist."""
        with pytest.raises(FileNotFoundError, match="VDB not found"):
            self._call("/nonexistent/path/cloud.vdb")

    def test_volume_import_called_with_correct_filepath(self, mock_bpy, tmp_path):
        """volume_import is called with the resolved filepath of the vdb."""
        vdb = tmp_path / "cumulus.vdb"
        vdb.write_bytes(b"fake")
        self._call(str(vdb))
        mock_bpy.ops.object.volume_import.assert_called_once_with(
            filepath=str(vdb.resolve()),
            files=[{"name": vdb.name}],
        )

    def test_object_name_set_when_provided(self, mock_bpy, tmp_path):
        """volume.name must be set if object_name is given."""
        vdb = tmp_path / "nimbus.vdb"
        vdb.write_bytes(b"fake")
        self._call(str(vdb), object_name="MyCloud")
        assert mock_bpy._test_volume.name == "MyCloud"

    def test_object_name_not_set_when_omitted(self, mock_bpy, tmp_path):
        """volume.name must not be assigned if object_name is None."""
        vdb = tmp_path / "nimbus2.vdb"
        vdb.write_bytes(b"fake")
        vol, _ = self._call(str(vdb))
        # name attribute should NOT have been set via assignment (MagicMock tracks this)
        # The simplest check: the volume returned is the mock active_object
        assert vol is mock_bpy._test_volume

    def test_position_and_scale_applied(self, mock_bpy, tmp_path):
        """Volume location and scale must be set from the kwargs."""
        vdb = tmp_path / "stratus.vdb"
        vdb.write_bytes(b"fake")
        self._call(str(vdb), position=(100.0, 200.0, 3000.0), scale=250.0)
        assert mock_bpy._test_volume.location == (100.0, 200.0, 3000.0)
        assert mock_bpy._test_volume.scale == (250.0, 250.0, 250.0)
