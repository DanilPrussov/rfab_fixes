#!/usr/bin/env python3
"""Узкое исследование TES5-плагинов только для чтения; не редактор ESP.

FormID выводятся как записаны в файле, без разрешения masters/load order.
Структура сверялась с TES5Edit dev-4.1.6, Core/wbDefinitionsTES5.pas.
Разбор границ записей не заменяет валидацию ссылок и проверку в xEdit.
"""

import argparse
import json
from pathlib import Path
import struct
import zlib


def records(data, start=0, end=None):
    end = len(data) if end is None else end
    pos = start
    while pos < end:
        if pos + 24 > end:
            raise ValueError(f"Неполный заголовок: {pos}")
        kind = data[pos:pos + 4].decode("ascii")
        size, flags, formid = struct.unpack_from("<III", data, pos + 4)
        if kind == "GRUP":
            if size < 24 or pos + size > end:
                raise ValueError(f"Неверный размер GRUP: {pos}")
            yield from records(data, pos + 24, pos + size)
            pos += size
            continue
        finish = pos + 24 + size
        if finish > end:
            raise ValueError(f"Запись выходит за границы: {pos}")
        payload = data[pos + 24:finish]
        if flags & 0x40000:
            expected, = struct.unpack_from("<I", payload)
            payload = zlib.decompress(payload[4:])
            if len(payload) != expected:
                raise ValueError(f"Неверный размер распаковки: {pos}")
        yield kind, formid, flags, subrecords(payload)
        pos = finish
    if pos != end:
        raise ValueError("Неверная граница группы")


def subrecords(data):
    result, pos, extended = [], 0, None
    while pos < len(data):
        if pos + 6 > len(data):
            raise ValueError("Неполный заголовок подзаписи")
        kind = data[pos:pos + 4].decode("ascii")
        size, = struct.unpack_from("<H", data, pos + 4)
        pos += 6
        if kind == "XXXX":
            if size != 4 or pos + 4 > len(data):
                raise ValueError("Некорректная XXXX")
            extended, = struct.unpack_from("<I", data, pos)
            pos += 4
            continue
        size = extended if extended is not None else size
        extended = None
        if pos + size > len(data):
            raise ValueError("Подзапись выходит за границы")
        result.append((kind, data[pos:pos + size]))
        pos += size
    if extended is not None:
        raise ValueError("XXXX без следующей подзаписи")
    return result


def string(data):
    data = data.rstrip(b"\0")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def describe(record, full=False):
    kind, formid, flags, subs = record
    result = {"type": kind, "formid": f"{formid:08X}", "flags": f"{flags:08X}"}
    result.update({key: string(value) for key, value in subs
                   if key in {"EDID", "FULL", "DESC", "CNAM", "SNAM"}
                   and (key not in {"CNAM", "SNAM"} or kind == "TES4")})
    if kind == "TES4":
        result["masters"] = [string(value) for key, value in subs if key == "MAST"]
    if full:
        result["subrecords"] = [
            {"type": key, "size": len(value), "hex": value.hex()}
            for key, value in subs
            if key not in {"EDID", "FULL", "DESC", "MAST"}
        ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", type=Path)
    parser.add_argument("--search", action="append", default=[])
    parser.add_argument("--id", action="append", default=[])
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    ids = {int(value, 16) for value in args.id}
    queries = [value.casefold() for value in args.search]
    for record in records(args.plugin.read_bytes()):
        summary = describe(record)
        searchable = " ".join(str(value) for value in summary.values()).casefold()
        if record[1] in ids or any(value in searchable for value in queries):
            print(json.dumps(describe(record, args.full), ensure_ascii=False))


if __name__ == "__main__":
    main()
