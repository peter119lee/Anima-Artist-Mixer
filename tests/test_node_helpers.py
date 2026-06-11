"""Parsing / formatting / preset helper tests for the anima_mixer package."""

import os
import sys
import types
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from anima_mixer import chain_tools, constants, options, parsing, patching, recipe  # noqa: E402
from anima_mixer.nodes_ui import (  # noqa: E402
    AnimaArtistChainBuilder,
    AnimaArtistInspector,
    AnimaArtistRecipeLoad,
    AnimaArtistRecipeSave,
    AnimaArtistStarter,
)


class ArtistRoutingHelpersTest(unittest.TestCase):
    def test_artist_timing_layers_and_weights_parse_together(self):
        parts = parsing.split_artist_chain(
            "::@wlop::1.2@0,2,4%0.0-0.45, "
            "::(krenz:1.1)::0.8@9，18%0.45-0.85, "
            "@hiten"
        )

        parts, timings = parsing.parse_artist_timing_routes(parts)
        parts, layers = parsing.parse_artist_layer_routes(parts)
        names, weights, explicit = parsing.parse_artist_weights(parts)

        self.assertTrue(explicit)
        self.assertEqual(names, ["@wlop", "(krenz:1.1)", "@hiten"])
        self.assertEqual(weights, [1.2, 0.8, 1.0])
        self.assertEqual(layers, ["0,2,4", "9，18", ""])
        self.assertEqual(timings, ["0.0-0.45", "0.45-0.85", ""])

        resolved_layers, has_layers = parsing.resolve_artist_layer_routes(layers, 28)
        self.assertTrue(has_layers)
        self.assertEqual(resolved_layers[0], {0, 2, 4})
        self.assertEqual(resolved_layers[1], {9, 18})

        resolved, has_timings = parsing.resolve_artist_timing_routes(timings)
        self.assertTrue(has_timings)
        self.assertEqual(resolved[0], (0.0, 0.45, 0.0))
        self.assertEqual(resolved[1], (0.45, 0.85, 0.0))
        self.assertIsNone(resolved[2])

    def test_negative_weight_parses_as_style_subtraction(self):
        names, weights, explicit = parsing.parse_artist_weights(["::wlop::-0.5", "krenz"])

        self.assertTrue(explicit)
        self.assertEqual(names, ["wlop", "krenz"])
        self.assertEqual(weights, [-0.5, 1.0])

    def test_weight_clamps_to_range(self):
        _, weights, _ = parsing.parse_artist_weights(["::a::9.5", "::b::-9.5"])
        self.assertEqual(weights, [constants.WEIGHT_MAX, constants.WEIGHT_MIN])

    def test_timing_fade_syntax_parses(self):
        self.assertEqual(parsing.parse_timing_filter("0.0-0.45~0.1"), (0.0, 0.45, 0.1))
        self.assertEqual(parsing.parse_timing_filter("0.0-0.45"), (0.0, 0.45, 0.0))
        self.assertIsNone(parsing.parse_timing_filter("0.0-0.45~x"))
        self.assertIsNone(parsing.parse_timing_filter("0.0-0.45~0.1~0.2"))
        self.assertIsNone(parsing.parse_timing_filter("0.5-0.5~0.1"))

    def test_timing_route_with_fade_attaches_to_artist(self):
        clean, timing = parsing.parse_artist_timing_route("wlop%0.0-0.45~0.1")
        self.assertEqual(clean, "wlop")
        self.assertEqual(timing, "0.0-0.45~0.1")

    def test_invalid_timing_suffix_stays_in_artist_text(self):
        clean, timing = parsing.parse_artist_timing_route("artist%0.5-0.5")
        self.assertEqual(clean, "artist%0.5-0.5")
        self.assertEqual(timing, "")

    def test_compatibility_safe_preset_overrides_risky_settings(self):
        payload = options.build_preset_payload(constants.PRESET_COMPATIBILITY_SAFE)
        self.assertEqual(payload["combine_mode"], constants.COMBINE_CONCAT)
        self.assertEqual(payload["fusion_mode"], constants.FUSION_CONCAT_WITH_BASE)
        self.assertTrue(payload["advanced_options"]["compatibility_mode"])

        combine_mode, fusion_mode, _, adv, _ = options.merge_runtime_options(
            constants.COMBINE_OUTPUT_AVG,
            constants.FUSION_INTERPOLATE,
            1.0,
            {
                "compatibility_mode": True,
                "artist_ema_alpha": 0.5,
                "artist_static_capture": True,
                "artist_anchor_q": True,
            },
            None,
        )

        self.assertEqual(combine_mode, constants.COMBINE_CONCAT)
        self.assertEqual(fusion_mode, constants.FUSION_CONCAT_WITH_BASE)
        self.assertEqual(adv["artist_ema_alpha"], 0.0)
        self.assertFalse(adv["artist_static_capture"])
        self.assertFalse(adv["artist_anchor_q"])

        combine_mode, fusion_mode, _, adv, _ = options.merge_runtime_options(
            constants.COMBINE_OUTPUT_AVG,
            constants.FUSION_INTERPOLATE,
            1.0,
            {"compatibility_mode": False, "artist_static_capture": True},
            payload,
        )
        self.assertEqual(combine_mode, constants.COMBINE_CONCAT)
        self.assertEqual(fusion_mode, constants.FUSION_CONCAT_WITH_BASE)
        self.assertTrue(adv["compatibility_mode"])
        self.assertFalse(adv["artist_static_capture"])

    def test_base_advanced_options_includes_new_keys(self):
        adv = options.base_advanced_options()
        self.assertIn("max_batch_artists", adv)
        self.assertIn("low_vram_cache", adv)
        self.assertEqual(adv["max_batch_artists"], 0)
        self.assertFalse(adv["low_vram_cache"])

    def test_block_map_groups_layers_and_keeps_timing_visible(self):
        block_map = chain_tools.format_artist_block_map(
            ["wlop", "krenz", "hiten"],
            ["0-1", "2-3", ""],
            ["0.0-0.5", "0.5-1.0", ""],
            num_blocks=4,
            target_blocks=[0, 1, 2, 3],
        )

        self.assertIn("L0-L1: wlop%0.00-0.50, hiten", block_map)
        self.assertIn("L2-L3: krenz%0.50-1.00, hiten", block_map)

    def test_external_cross_attention_wrapper_is_reported(self):
        class PlainCrossAttn:
            context_dim = 1024

        class ExternalWrapper:
            def __init__(self):
                self.original = PlainCrossAttn()

        class Block:
            def __init__(self, cross_attn):
                self.cross_attn = cross_attn

        dm = types.SimpleNamespace(blocks=[Block(PlainCrossAttn()), Block(ExternalWrapper())])
        hints = patching.describe_external_cross_attn_patches(dm, [0, 1])

        self.assertEqual(len(hints), 1)
        self.assertIn("L1", hints[0])
        self.assertIn("ExternalWrapper", hints[0])


class ChainBuilderTest(unittest.TestCase):
    def test_chain_builder_creates_layer_scheduled_chain(self):
        chain, report = chain_tools.build_artist_chain_from_rows(
            constants.CHAIN_LAYOUT_LAYER_SCHEDULED,
            [
                ("@wlop", 1.2, "", ""),
                ("krenz", 0.8, "", ""),
                ("", 1.0, "", ""),
            ],
            num_blocks=28,
        )

        self.assertEqual(
            chain,
            "::@wlop::1.2@0-8%0.0-0.45\n::krenz::0.8@9-18%0.35-0.85",
        )
        self.assertIn("L0-L8: @wlop%0.00-0.45", report)
        self.assertIn("L9-L18: krenz%0.35-0.85", report)

    def test_chain_preview_reports_invalid_timing_before_clip_encoding(self):
        cleaned, report = chain_tools.format_artist_chain_preview(
            "wlop@0,2,4%0.0-0.5, bad%0.5-0.5",
            num_blocks=28,
        )

        self.assertEqual(cleaned, "wlop@0,2,4%0.0-0.5\nbad%0.5-0.5")
        self.assertIn("L0: wlop%0.00-0.50", report)
        self.assertIn("invalid timing", report)

    def test_chain_preview_flags_negative_weights(self):
        _, report = chain_tools.format_artist_chain_preview(
            "::wlop::-0.5, krenz", num_blocks=28,
        )
        self.assertIn("negative ::weight detected", report)

    def test_chain_builder_ignores_invalid_manual_routes(self):
        chain, report = chain_tools.build_artist_chain_from_rows(
            constants.CHAIN_LAYOUT_MANUAL,
            [("wlop", 1.0, "abc", "0.2-0.2")],
            num_blocks=28,
        )

        self.assertEqual(chain, "wlop")
        self.assertIn("invalid layer route ignored", report)
        self.assertIn("invalid timing route ignored", report)

    def test_chain_builder_table_supports_more_than_three_artists(self):
        rows = chain_tools.parse_builder_artist_table(
            "@a | 1.2\n"
            "b | 0.8\n"
            "c\n"
            "d"
        )
        chain, report = chain_tools.build_artist_chain_from_rows(
            constants.CHAIN_LAYOUT_LAYER_SCHEDULED,
            rows,
            num_blocks=28,
        )
        lines = chain.splitlines()

        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], "::@a::1.2@0-6%0.00-0.33")
        self.assertEqual(lines[-1], "d@21-27%0.67-1.00")
        self.assertIn("artists: 4", report)

    def test_chain_builder_node_accepts_table_artists(self):
        result = AnimaArtistChainBuilder().build(
            constants.CHAIN_LAYOUT_LAYER_SCHEDULED,
            "a\nb\nc\nd\ne",
            "",
            1.0,
            "",
            1.0,
            "",
            1.0,
            num_blocks=28,
        )
        chain, report = result["result"]

        self.assertEqual(len(chain.splitlines()), 5)
        self.assertIn("artists: 5", report)
        self.assertIn("e@22-27%0.72-1.00", chain)

    def test_chain_builder_reports_invalid_table_weight(self):
        rows, warnings = chain_tools.parse_builder_artist_table(
            "wlop | not-a-number",
            return_warnings=True,
        )
        chain, report = chain_tools.build_artist_chain_from_rows(
            constants.CHAIN_LAYOUT_MANUAL,
            rows,
            extra_warnings=warnings,
        )

        self.assertEqual(chain, "wlop")
        self.assertIn("status: CHECK", report)
        self.assertIn("invalid weight for wlop", report)

    def test_chain_builder_reports_empty_artist_chain(self):
        chain, report = chain_tools.build_artist_chain_from_rows(
            constants.CHAIN_LAYOUT_LAYER_SCHEDULED,
            [],
        )

        self.assertEqual(chain, "")
        self.assertIn("status: CHECK", report)
        self.assertIn("no artists", report)

    def test_starter_recipe_outputs_connectable_payloads(self):
        result = AnimaArtistStarter().build(
            constants.PRESET_COMPATIBILITY_SAFE,
            "a\nb\nc\nd",
            constants.CHAIN_LAYOUT_LAYER_SCHEDULED,
            1.0,
            normalize_weights=True,
            layer_mode=constants.LAYER_MODE_AUTO,
            custom_layer_filter="",
            num_blocks=28,
        )
        chain, preset, advanced_options, guide = result["result"]

        self.assertEqual(len(chain.splitlines()), 4)
        self.assertEqual(preset["preset"], constants.PRESET_COMPATIBILITY_SAFE)
        self.assertTrue(advanced_options["compatibility_mode"])
        self.assertIn("artist_chain -> AnimaArtistPack.artist_chain", guide)
        self.assertIn("status: OK", guide)


class InspectorTest(unittest.TestCase):
    def _pack(self, **overrides):
        pack = {
            "labels": ["wlop"],
            "weights": [1.0],
            "layer_routes": [""],
            "timing_routes": [""],
            "has_explicit_weights": False,
            "base_prompt": "portrait",
        }
        pack.update(overrides)
        return pack

    def test_inspector_has_ok_status_without_forced_warning(self):
        report = AnimaArtistInspector().inspect(self._pack())["result"][0]

        self.assertIn("status: OK", report)
        self.assertIn("warnings:\n  - no obvious configuration risk", report)
        self.assertIn("notes:", report)

    def test_inspector_notes_negative_weights(self):
        report = AnimaArtistInspector().inspect(
            self._pack(labels=["wlop", "bad"], weights=[1.0, -0.5],
                       layer_routes=["", ""], timing_routes=["", ""],
                       has_explicit_weights=True),
        )["result"][0]

        self.assertIn("negative weights present", report)

    def test_inspector_notes_embed_avg(self):
        report = AnimaArtistInspector().inspect(
            self._pack(), combine_mode=constants.COMBINE_EMBED_AVG,
        )["result"][0]

        self.assertIn("embed_avg mixes in the LLMAdapter embedding space", report)


class RecipeTest(unittest.TestCase):
    def test_recipe_roundtrip(self):
        adv = options.base_advanced_options()
        adv["artist_ema_alpha"] = 0.25
        adv["low_vram_cache"] = True
        text = recipe.serialize_recipe(
            "wlop, ::krenz::0.8", constants.COMBINE_LOWRANK_AVG,
            constants.FUSION_BASE_PRESERVE, 1.4, adv, notes="my mix",
        )
        payload, warnings = recipe.deserialize_recipe(text)

        self.assertEqual(warnings, [])
        self.assertEqual(payload["artist_chain"], "wlop, ::krenz::0.8")
        self.assertEqual(payload["combine_mode"], constants.COMBINE_LOWRANK_AVG)
        self.assertEqual(payload["fusion_mode"], constants.FUSION_BASE_PRESERVE)
        self.assertAlmostEqual(payload["strength"], 1.4)
        self.assertEqual(payload["advanced_options"]["artist_ema_alpha"], 0.25)
        self.assertTrue(payload["advanced_options"]["low_vram_cache"])
        self.assertEqual(payload["notes"], "my mix")

    def test_recipe_rejects_garbage(self):
        with self.assertRaises(ValueError):
            recipe.deserialize_recipe("not json at all {")

    def test_recipe_unknown_modes_fall_back_with_warning(self):
        payload, warnings = recipe.deserialize_recipe(
            '{"format": "anima-artist-recipe", "version": 1, '
            '"artist_chain": "a", "combine_mode": "wat", "fusion_mode": "huh"}'
        )
        self.assertEqual(payload["combine_mode"], constants.COMBINE_OUTPUT_AVG)
        self.assertEqual(payload["fusion_mode"], constants.FUSION_INTERPOLATE)
        self.assertTrue(any("combine_mode" in w for w in warnings))
        self.assertTrue(any("fusion_mode" in w for w in warnings))

    def test_recipe_nodes_roundtrip(self):
        save_result = AnimaArtistRecipeSave().save(
            "wlop\nkrenz", constants.COMBINE_OUTPUT_AVG,
            constants.FUSION_INTERPOLATE, 1.0,
        )
        recipe_json = save_result["result"][0]
        chain, preset, adv, summary = AnimaArtistRecipeLoad().load(recipe_json)["result"]

        self.assertEqual(chain, "wlop\nkrenz")
        self.assertEqual(preset["combine_mode"], constants.COMBINE_OUTPUT_AVG)
        self.assertEqual(preset["fusion_mode"], constants.FUSION_INTERPOLATE)
        self.assertIn("status: OK", summary)


class RegistryTest(unittest.TestCase):
    def test_node_mappings_complete(self):
        import anima_mixer
        self.assertEqual(
            set(anima_mixer.NODE_CLASS_MAPPINGS),
            set(anima_mixer.NODE_DISPLAY_NAME_MAPPINGS),
        )
        self.assertIn("AnimaArtistCrossAttn", anima_mixer.NODE_CLASS_MAPPINGS)
        self.assertIn("AnimaArtistRecipeSave", anima_mixer.NODE_CLASS_MAPPINGS)
        self.assertIn("AnimaArtistProbe", anima_mixer.NODE_CLASS_MAPPINGS)


if __name__ == "__main__":
    unittest.main()
