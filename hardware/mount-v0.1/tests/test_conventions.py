"""Rig-frame conventions shared with the diagnostics software. Needs bpy (mathutils):
uv run python -m unittest discover -s tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import bpy  # noqa: F401  (provides mathutils)
    from mathutils import Vector
    from lynx_mount import assembly as asm
    from lynx_mount.params import DEFAULT
except ImportError:  # plain python3 without bpy
    asm = None


def axis(side, yaw=0.0, pitch=0.0, baseline=100.0):
    pose = asm.Pose(baseline, asm.Setting(yaw, pitch), asm.Setting(yaw, pitch))
    M = asm.camera_matrices(DEFAULT, pose)[side]
    return (M.to_3x3() @ Vector((0, 0, 1))), M.translation


@unittest.skipIf(asm is None, "needs bpy")
class Conventions(unittest.TestCase):
    def test_cam_left_is_on_the_users_left(self):
        _, left = axis("left")
        _, right = axis("right")
        self.assertLess(left.x, 0)
        self.assertGreater(right.x, 0)
        self.assertAlmostEqual(right.x - left.x, 100.0)

    def test_zero_angles_look_at_the_user(self):
        for side in ("left", "right"):
            a, _ = axis(side)
            self.assertAlmostEqual(a.z, 1.0)

    def test_positive_yaw_turns_toward_the_rig_centre(self):
        self.assertGreater(axis("left", yaw=10)[0].x, 0)
        self.assertLess(axis("right", yaw=10)[0].x, 0)

    def test_positive_pitch_turns_up(self):
        for side in ("left", "right"):
            self.assertGreater(axis(side, pitch=10)[0].y, 0)

    def test_pivots_hold_the_optical_centre(self):
        for side in ("left", "right"):
            _, c0 = axis(side)
            _, c1 = axis(side, yaw=25, pitch=-25)
            self.assertAlmostEqual((c1 - c0).length, 0.0)


if __name__ == "__main__":
    unittest.main()
