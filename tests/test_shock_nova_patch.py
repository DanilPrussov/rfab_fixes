"""Проверки read-only валидатора на синтетических записях, без MO2 и игры."""

import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest
import zlib


VALIDATOR = (
    Path(__file__).resolve().parents[1] / "fixes" /
    "0001-shock-nova-neutral-targets" / "src" / "validate_patch.py"
)
spec = importlib.util.spec_from_file_location("validate_shock_patch", VALIDATOR)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def subrecord(tag, value):
    return tag.encode("ascii") + struct.pack("<H", len(value)) + value


def record(tag, formid, payload, compressed=False):
    if compressed:
        payload = struct.pack("<I", len(payload)) + zlib.compress(payload)
    return struct.pack("<4sIIIIHH", tag.encode("ascii"), len(payload),
                       0x40000 if compressed else 0, formid, 0, 44, 0) + payload


def group(payload):
    return struct.pack("<4sI4sIHHI", b"GRUP", len(payload) + 24,
                       b"MGEF", 0, 0, 0, 0) + payload


def make_plugin(masters, self_index, condition=None, *, damage=0.5,
                explosion=0x1124B0, actor_owner=0, extra=b"", compressed=False):
    header = subrecord("HEDR", struct.pack("<fII", 1.7, 2, 0x800))
    for name in masters:
        header += subrecord("MAST", name.encode("ascii") + b"\0")
        header += subrecord("DATA", bytes(8))
    fields = bytearray(152)
    struct.pack_into("<I", fields, 0, 0x205)
    struct.pack_into("<f", fields, 48, damage)
    struct.pack_into("<I", fields, 64, 5)
    struct.pack_into("<I", fields, 76, self_index << 24 | explosion)
    struct.pack_into("<I", fields, 24, actor_owner << 24 | 0x57C68)
    effect = b"".join((
        subrecord("EDID", b"Test_Effect\0"),
        subrecord("FULL", "Молния\0".encode("utf-8")),
        subrecord("MDOB", struct.pack("<I", actor_owner << 24 | 0x9FA64)),
        subrecord("DATA", fields),
        subrecord("SNDD", struct.pack("<IIII", 0, actor_owner << 24 | 0x3F208,
                                     3, self_index << 24 | 0x115E21)),
        subrecord("DNAM", "<mag> урона\0".encode("utf-8")),
    ))
    if condition is not None:
        effect += subrecord("CTDA", condition)
    effect += extra
    return record("TES4", 0, header) + group(
        record("MGEF", self_index << 24 | validator.LOCAL_ID, effect, compressed))


def condition(**changes):
    values = dict(flags=0, padding=bytes(3), value=1.0, function=719,
                  padding2=bytes(2), actor=0x14, unused=0, run_on=0,
                  reference=0, param3=-1)
    values.update(changes)
    return struct.pack("<B3sfH2sIIIIi", *values.values())


class ShockNovaPatchTests(unittest.TestCase):
    def setUp(self):
        self.source = make_plugin(
            ["Skyrim.esm", "Update.esm", "Other.esp"], 3, compressed=True)
        self.patch = make_plugin(["Skyrim.esm", "RFAB.esp"], 1, condition())
        self.expected_hash = hashlib.sha256(self.source).hexdigest()

    def validate(self, patch=None):
        return validator.validate_plugins(
            self.source, self.patch if patch is None else patch, self.expected_hash)

    def test_remapped_references_and_compressed_source_are_equal(self):
        report = self.validate()
        self.assertEqual(report["records"], 1)
        self.assertEqual(report["patch_sha256"], hashlib.sha256(self.patch).hexdigest())

    def test_changed_source_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            validator.validate_plugins(self.source, self.patch, "0" * 64)

    def test_changed_unrelated_value_or_reference_is_rejected(self):
        for changes in ({"damage": 0.75}, {"explosion": 0x1124B1}, {"actor_owner": 1}):
            with self.subTest(changes=changes):
                patch = make_plugin(["Skyrim.esm", "RFAB.esp"], 1, condition(), **changes)
                with self.assertRaisesRegex(ValueError, "содержимое MGEF"):
                    self.validate(patch)

    def test_wrong_condition_semantics_are_rejected(self):
        changes = (
            {"flags": 1}, {"value": 0.0}, {"function": 718},
            {"actor": 0x01000014}, {"run_on": 1}, {"reference": 0x14},
            {"param3": 0}, {"unused": 1},
        )
        for change in changes:
            with self.subTest(change=change):
                patch = make_plugin(["Skyrim.esm", "RFAB.esp"], 1, condition(**change))
                with self.assertRaisesRegex(ValueError, "CTDA"):
                    self.validate(patch)

    def test_missing_or_extra_conditions_are_rejected(self):
        for patch in (
            make_plugin(["Skyrim.esm", "RFAB.esp"], 1),
            make_plugin(["Skyrim.esm", "RFAB.esp"], 1, condition(),
                        extra=subrecord("CTDA", condition())),
        ):
            with self.assertRaisesRegex(ValueError, "одной CTDA"):
                self.validate(patch)

    def test_extra_records_wrong_masters_and_truncation_are_rejected(self):
        cases = (
            self.patch + record("SPEL", 0x01001234, b""),
            make_plugin(["Skyrim.esm", "Unrelated.esp"], 1, condition()),
            self.patch[:-1],
        )
        for patch in cases:
            with self.subTest(size=len(patch)):
                with self.assertRaises(ValueError):
                    self.validate(patch)

    def test_out_of_range_patch_reference_is_rejected(self):
        patch = make_plugin(["Skyrim.esm", "RFAB.esp"], 1, condition(), actor_owner=7)
        with self.assertRaisesRegex(ValueError, "индекс за границей"):
            self.validate(patch)

    def test_unknown_subrecord_is_rejected(self):
        patch = make_plugin(["Skyrim.esm", "RFAB.esp"], 1, condition(),
                            extra=subrecord("VMAD", b"unreviewed"))
        with self.assertRaisesRegex(ValueError, "одной CTDA"):
            self.validate(patch)


if __name__ == "__main__":
    unittest.main()
