"""Parameter-level checks that need no Blender: python3 -m unittest discover -s tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lynx_mount.params import DEFAULT, fastener_stacks  # noqa: E402


class FastenerStacks(unittest.TestCase):
    def test_every_joint_fully_engages_its_nut(self):
        for name, s in fastener_stacks(DEFAULT).items():
            with self.subTest(joint=name):
                self.assertGreaterEqual(s["engagement"], DEFAULT.fasteners.min_thread_engagement)

    def test_no_bolt_tip_hits_a_part(self):
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
        corners = f.m4_nut_af / (3 ** 0.5 / 2)
        self.assertGreater(self.p.tunnel_width, f.m4_nut_af)
        self.assertLess(self.p.tunnel_width, corners)

    def test_angle_scales_are_symmetric(self):
        t = self.p.angle_ticks(self.p.yaw_range)
        self.assertEqual(t, [-x for x in reversed(t)])
        self.assertEqual(max(t), self.p.yaw_range)


if __name__ == "__main__":
    unittest.main()
