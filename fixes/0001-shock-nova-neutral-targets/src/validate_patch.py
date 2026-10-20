#!/usr/bin/env python3
"""Только чтение: независимая проверка узкого MGEF-патча Mutagen.

Сверяет все исходные подзаписи, разрешая FormID через MAST, и допускает
только добавленное условие. Не пишет ESP и не заменяет игровой тест/xEdit.
Схема полей: TES5Edit dev-4.1.6, Core/wbDefinitionsTES5.pas, MGEF/CTDA.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys


SOURCE_SHA256 = "a5b03f58aeefeb806f7c4e44981d4f3ba0bc125419d488d3fcc7a896768d3401"
SOURCE_NAME = "RFAB.esp"
PATCH_NAME = "RFAB-ShockNova-NeutralTargets.esp"
LOCAL_ID = 0x1124AF
DATA_FORM_OFFSETS = (
    8, 24, 32, 36, 72, 76, 92, 96, 100, 108, 116, 120, 124, 128, 132, 136,
)
BASE_TAGS = ("EDID", "FULL", "MDOB", "DATA", "SNDD", "DNAM")

_spec = importlib.util.spec_from_file_location(
    "shock_nova_inspect", Path(__file__).with_name("inspect_records.py"))
_reader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_reader)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def resolve_formid(value, masters, plugin_name, source=False):
    """Приводит файловый индекс к (имя владельца, local ID), ноль — NULL."""
    if not value:
        return None
    index = value >> 24
    if index < len(masters):
        owner = masters[index]
    elif index == len(masters) or source:
        # RFAB содержит старые self-индексы выше числа MAST. xEdit трактует
        # их как self. Для создаваемого патча такая неоднозначность запрещена.
        owner = plugin_name
    else:
        raise ValueError(f"FormID {value:08X}: индекс за границей MAST")
    return owner.casefold(), value & 0xFFFFFF


def get_masters(header):
    require(header[0] == "TES4" and header[1] == 0, "Нет корректного TES4")
    subs = header[3]
    masters = []
    for index, (tag, value) in enumerate(subs):
        if tag != "MAST":
            continue
        require(value.endswith(b"\0"), "MAST без завершающего нуля")
        name = value[:-1].decode("ascii")
        require(name and "/" not in name and "\\" not in name, "Неверное имя MAST")
        require(index + 1 < len(subs) and subs[index + 1][0] == "DATA"
                and len(subs[index + 1][1]) == 8, "MAST без DATA размером 8")
        masters.append(name)
    require(len(set(x.casefold() for x in masters)) == len(masters),
            "Дублированный MAST")
    return masters


def normalized_subrecord(tag, data, masters, name, source):
    """Сравнивает все байты, заменяя лишь поля ссылок логическими FormID."""
    if tag == "MDOB":
        require(len(data) == 4, "MDOB: ожидается 4 байта")
        offsets = (0,)
    elif tag == "DATA":
        require(len(data) == 152, "Неизвестный формат MGEF DATA")
        require(struct.unpack_from("<I", data, 64)[0] == 5,
                "Неожиданный архетип MGEF; нужна повторная диагностика")
        offsets = DATA_FORM_OFFSETS
    elif tag == "SNDD":
        require(len(data) > 0 and len(data) % 8 == 0, "Неверный размер SNDD")
        offsets = range(4, len(data), 8)
    else:
        require(tag in BASE_TAGS, f"Неподдержанная подзапись MGEF: {tag}")
        return data
    pieces = []
    previous = 0
    for offset in offsets:
        pieces.append(data[previous:offset])
        value, = struct.unpack_from("<I", data, offset)
        pieces.append(resolve_formid(value, masters, name, source))
        previous = offset + 4
    pieces.append(data[previous:])
    return tuple(pieces)


def validate_condition(data, masters):
    require(len(data) == 32, "CTDA: ожидается ровно 32 байта")
    flags, padding, value, function, padding2, actor, unused, run_on, reference, param3 = (
        struct.unpack("<B3sfH2sIIIIi", data))
    require(flags == 0, "CTDA: нужно сравнение == без OR и прочих флагов")
    require(padding == b"\0" * 3 and padding2 == b"\0" * 2,
            "CTDA: ненулевые служебные поля")
    require(value == 1.0, "CTDA: нужно сравнение с 1")
    require(function == 719, "CTDA: нужна функция IsHostileToActor (719)")
    require(resolve_formid(actor, masters, PATCH_NAME) == ("skyrim.esm", 0x14),
            "CTDA: параметр должен ссылаться на Skyrim.esm:000014 PlayerRef")
    require(run_on == 0, "CTDA: Run On должен быть Subject")
    require(unused == 0 and reference == 0 and param3 == -1,
            "CTDA: неожиданные дополнительные параметры")


def validate_patch_layout(data):
    """Патч: TES4 + одна top-level GRUP MGEF + один MGEF, без иных записей."""
    require(len(data) >= 72, "Патч слишком короткий")
    require(data[:4] == b"TES4", "Первой записью должен быть TES4")
    header_size, header_flags = struct.unpack_from("<II", data, 4)
    require(header_flags == 0, "Патч должен быть обычным ESP без ESM/ESL/Localized")
    group_at = 24 + header_size
    require(group_at + 24 <= len(data), "Отсутствует группа MGEF")
    require(data[group_at:group_at + 4] == b"GRUP", "Ожидается GRUP после TES4")
    group_size, label, group_type = struct.unpack_from("<I4sI", data, group_at + 4)
    require(group_size >= 48 and group_at + group_size == len(data),
            "Патч должен содержать ровно одну группу без хвостовых данных")
    require(label == b"MGEF" and group_type == 0, "Неверная группа MGEF")
    record_at = group_at + 24
    require(data[record_at:record_at + 4] == b"MGEF", "В группе должен быть MGEF")
    size, = struct.unpack_from("<I", data, record_at + 4)
    require(record_at + 24 + size == len(data), "В патче должна быть одна запись MGEF")
    return record_at


def source_record_header(data, wanted_id):
    """Находит заголовок через границы записей; поиск байтов сигнатуры не нужен."""
    def visit(start, end):
        pos = start
        while pos < end:
            require(pos + 24 <= end, "Неполный заголовок исходника")
            size, = struct.unpack_from("<I", data, pos + 4)
            if data[pos:pos + 4] == b"GRUP":
                require(size >= 24 and pos + size <= end, "Неверная исходная GRUP")
                result = visit(pos + 24, pos + size)
                if result is not None:
                    return result
                pos += size
            else:
                finish = pos + 24 + size
                require(finish <= end, "Исходная запись выходит за границы")
                formid, = struct.unpack_from("<I", data, pos + 12)
                if data[pos:pos + 4] == b"MGEF" and formid == wanted_id:
                    return data[pos:pos + 24]
                pos = finish
        return None
    result = visit(0, len(data))
    require(result is not None, "Не найден исходный заголовок MGEF")
    return result


def validate_plugins(source, patch, expected_source_sha256=SOURCE_SHA256):
    source_hash = hashlib.sha256(source).hexdigest()
    require(source_hash == expected_source_sha256,
            "SHA-256 RFAB.esp не совпадает с исследованной базой; сборка запрещена")
    patch_record_at = validate_patch_layout(patch)
    source_records = _reader.records(source)
    source_header = next(source_records, None)
    require(source_header is not None, "Пустой исходный плагин")
    source_masters = get_masters(source_header)
    matches = [
        record for record in source_records
        if record[0] == "MGEF"
        and resolve_formid(record[1], source_masters, SOURCE_NAME, True)
        == (SOURCE_NAME.casefold(), LOCAL_ID)
    ]
    require(len(matches) == 1, "В исходнике нужен ровно один целевой MGEF")
    original = matches[0]
    patch_records = list(_reader.records(patch))
    require(len(patch_records) == 2, "В патче должны быть только TES4 и один MGEF")
    header, override = patch_records
    masters = get_masters(header)
    require(masters == ["Skyrim.esm", SOURCE_NAME], "Неожиданный состав или порядок MAST")
    hedr = [value for tag, value in header[3] if tag == "HEDR"]
    require(len(hedr) == 1 and len(hedr[0]) == 12, "Некорректный HEDR")
    version, count, _ = struct.unpack("<fII", hedr[0])
    require(abs(version - 1.7) < 0.0001 and count == 2,
            "HEDR: нужна версия 1.7 и счётчик 2 (GRUP + MGEF)")
    require(override[0] == "MGEF" and
            resolve_formid(override[1], masters, PATCH_NAME) ==
            (SOURCE_NAME.casefold(), LOCAL_ID), "Подменена целевая запись override")
    require(original[2] & ~0x40000 == override[2] & ~0x40000,
            "Изменены флаги записи MGEF")
    original_header = source_record_header(source, original[1])
    require(original_header[16:24] == patch[patch_record_at + 16:patch_record_at + 24],
            "Изменены служебные поля / версия записи MGEF")
    require(tuple(tag for tag, _ in original[3]) == BASE_TAGS,
            "Изменился состав/порядок исходного MGEF; нужна повторная диагностика")
    require(tuple(tag for tag, _ in override[3]) == BASE_TAGS + ("CTDA",),
            "Допускается только добавление одной CTDA в конец MGEF")
    for (tag, before), (_, after) in zip(original[3], override[3]):
        old = normalized_subrecord(tag, before, source_masters, SOURCE_NAME, True)
        new = normalized_subrecord(tag, after, masters, PATCH_NAME, False)
        require(old == new, f"Помимо CTDA изменено содержимое MGEF/{tag}")
    validate_condition(override[3][-1][1], masters)
    return {
        "result": "ok",
        "source_sha256": source_hash,
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "masters": masters,
        "override": "RFAB.esp:1124AF",
        "records": 1,
        "change": "CTDA IsHostileToActor(Skyrim.esm:000014) == 1; Run On Subject",
        "game_test": "не выполнен",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Исходный RFAB.esp")
    parser.add_argument("patch", type=Path, help="Собранный патч ESP")
    args = parser.parse_args()
    try:
        require(args.source.name.casefold() == SOURCE_NAME.casefold(),
                "Исходный файл должен называться RFAB.esp")
        require(args.patch.name.casefold() == PATCH_NAME.casefold(),
                f"Патч должен называться {PATCH_NAME}")
        report = validate_plugins(args.source.read_bytes(), args.patch.read_bytes())
    except (ValueError, OSError, struct.error, UnicodeError) as exc:
        print(f"Ошибка проверки: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
