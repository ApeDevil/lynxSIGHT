"""Parameter-level checks that need no Blender: python3 -m unittest discover -s tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lynx_mount.params import DEFAULT, fastener_stacks  # noqa: E402
from lynx_mount.plates import pack, place  # noqa: E402


class FastenerStacks(unittest.TestCase):
    def test_every_screw_engages_enough_thread(self):
        for name, s in fastener_stacks(DEFAULT).items():
            with self.subTest(joint=name):
                self.assertGreaterEqual(s["engagement"], DEFAULT.fasteners.min_engagement)

    def test_thread_flanks_print_without_support(self):
        f = DEFAULT.fasteners
        flank = (1 - f.crest - f.root) / 2 * f.pitch
        self.assertGreaterEqual(flank, f.depth - 1e-9)  # at most 45 degrees from vertical

    def test_screw_passes_its_clearance_holes(self):
        f = DEFAULT.fasteners
        self.assertGreater(f.shank_clearance, f.major)
        self.assertLessEqual(f.shank_clearance, DEFAULT.slot_width)

    def test_no_screw_tip_hits_a_part(self):
        for name, s in fastener_stacks(DEFAULT).items():
            with self.subTest(joint=name):
                self.assertGreaterEqual(s["tip_room"], 0.0)


class Ranges(unittest.TestCase):
    p = DEFAULT

    def test_baseline_scale_covers_the_target_range(self):
        ticks = [b for b, _ in self.p.baseline_ticks()]
        self.assertEqual(ticks[0], self.p.baseline_min)
        self.assertEqual(ticks[-1], self.p.baseline_max)
        self.assertIn(self.p.baseline_nominal, ticks)

    def test_tick_position_is_half_the_baseline(self):
        for b, x in self.p.baseline_ticks():
            self.assertAlmostEqual(2 * x, b)

    def test_carriages_fit_on_the_rail_at_both_ends_of_the_range(self):
        self.assertLessEqual(self.p.carriage_width, self.p.baseline_min)
        self.assertLessEqual(self.p.baseline_max / 2 + self.p.carriage_width / 2, self.p.rail_length / 2)

    def test_rail_fits_the_reference_bed(self):
        bed = self.p.printing.bed_xyz[0] - 2 * self.p.printing.bed_margin
        self.assertLessEqual(self.p.rail_length, bed)

    def test_clamp_grips_thin_and_thick_monitors(self):
        lo, hi = self.p.monitor_depth_range
        self.assertLessEqual(lo, 15.0)
        self.assertGreaterEqual(hi, 70.0)

    def test_standoffs_clear_the_assumed_rear_components(self):
        self.assertGreater(self.p.standoff_height, self.p.camera.rear_component_height.value)

    def test_tunnel_holds_a_nut_without_letting_it_spin(self):
        f = self.p.fasteners
        corners = f.nut_af / (3 ** 0.5 / 2)
        self.assertGreater(self.p.tunnel_width, f.nut_af)
        self.assertLess(self.p.tunnel_width, corners)

    def test_angle_scales_are_symmetric(self):
        t = self.p.angle_ticks(self.p.yaw_range)
        self.assertEqual(t, [-x for x in reversed(t)])
        self.assertEqual(max(t), self.p.yaw_range)


def _box(w, d, h):
    import numpy as np
    v = np.array([(x, y, z) for z in (0, h) for y in (0, d) for x in (0, w)], float)
    t = np.array([(0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6), (0, 1, 4), (1, 5, 4),
                  (2, 6, 3), (3, 6, 7), (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5)])
    return v, t


class Plates(unittest.TestCase):
    def test_nested_parts_stay_on_the_bed_and_apart(self):
        pr = DEFAULT.printing
        parts = [("rail", *_box(216, 28, 22))] + [(f"knob_{i}", *_box(18, 18, 8)) for i in range(10)] \
            + [(f"arm_{i}", *_box(94, 70, 6)) for i in range(2)]
        layout = pack(parts, pr.bed_xyz[:2], pr.bed_margin, pr.plate_gap)
        meshes = {n: (v, t) for n, v, t in parts}
        placed = []
        for plate in layout:
            boxes = []
            for name, turns, corner in plate:
                v = place(meshes[name][0], turns, corner)
                lo, hi = v.min(axis=0), v.max(axis=0)
                self.assertGreaterEqual(min(lo[:2]), pr.bed_margin - 1e-9)
                self.assertTrue((hi[:2] <= [b - pr.bed_margin + 1e-9 for b in pr.bed_xyz[:2]]).all())
                for blo, bhi in boxes:
                    gap = max(lo[0] - bhi[0], blo[0] - hi[0], lo[1] - bhi[1], blo[1] - hi[1])
                    self.assertGreaterEqual(gap, pr.plate_gap - 1e-9, name)
                boxes.append((lo, hi))
                placed.append(name)
        self.assertEqual(len(layout), 1)
        self.assertCountEqual(placed, meshes)


if __name__ == "__main__":
    unittest.main()
