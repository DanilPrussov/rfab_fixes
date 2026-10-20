#!/usr/bin/env python3
"""Create, validate and package isolated Skyrim Data fixes (Python 3 stdlib)."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIX_ID = re.compile(r"[0-9]{4,}-[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
INVALID_WINDOWS = re.compile(r'[<>:"\\|?*\x00-\x1f]')
RESERVED_WINDOWS = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
RESERVED_WINDOWS.update(
    prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³"
)
NATIVE_SUFFIXES = {".dll", ".exe", ".dylib", ".so", ".pyd", ".asi"}
REQUIRED_DOCS = ("README.md", "TESTING.md", "UPSTREAM.md")


class FixError(Exception):
    pass


def fix_path(root, fix_id):
    if not FIX_ID.fullmatch(fix_id):
        raise FixError("ID must look like 0001-short-lowercase-name (4+ digits).")
    if (root / "fixes").is_symlink():
        raise FixError("fixes/ must not be a symlink.")
    path = root / "fixes" / fix_id
    if path.is_symlink():
        raise FixError(f"{path}: symlinks are forbidden.")
    return path


def entries(directory):
    """Yield entries without following directory symlinks."""
    def fail(error):
        raise error

    for base, directories, files in os.walk(directory, followlinks=False, onerror=fail):
        directories.sort()
        for name in sorted(directories + files):
            yield Path(base) / name


def create_fix(root, fix_id):
    target = fix_path(root, fix_id)
    if target.exists():
        raise FixError(f"Already exists: {target}")
    template = root / "templates" / "fix"
    if (root / "templates").is_symlink() or template.is_symlink():
        raise FixError("The template must not be a symlink.")
    if not template.is_dir():
        raise FixError(f"Missing template: {template}")
    for path in entries(template):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise FixError(f"Unsupported template entry: {path}")
    shutil.copytree(template, target)
    for path in entries(target):
        if path.is_file() and path.suffix.lower() == ".md":
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("{{FIX_ID}}", fix_id), encoding="utf-8")
    print(f"Created {target}")


def name_problem(name):
    if (
        INVALID_WINDOWS.search(name)
        or name.endswith((".", " "))
        or name.split(".", 1)[0].rstrip(" .").upper() in RESERVED_WINDOWS
    ):
        return "unsafe Windows name"
    if name.casefold() in {".ds_store", "__macosx"} or name.startswith("._"):
        return "macOS metadata"
    return None


def check_fix(root, fix_id):
    target = fix_path(root, fix_id)
    problems = []
    if not target.is_dir():
        raise FixError(f"Missing fix directory: {target}")
    for name in REQUIRED_DOCS:
        path = target / name
        if path.is_symlink() or not path.is_file():
            problems.append(f"{name}: must be a regular file")
    payload = target / "payload"
    if payload.is_symlink() or not payload.is_dir():
        problems.append("payload/: must be a real directory")
        raise FixError("\n".join(problems))
    files, seen = [], {}
    for path in entries(payload):
        relative = path.relative_to(payload)
        label = relative.as_posix()
        if path.is_symlink():
            problems.append(f"{label}: symlinks are forbidden")
            continue
        if not (path.is_dir() or path.is_file()):
            problems.append(f"{label}: not a regular file or directory")
            continue
        if path.is_file() and path.name == ".gitkeep":
            continue
        key = label.casefold()
        if key in seen:
            problems.append(f"{label}: case collision with {seen[key]}")
        else:
            seen[key] = label
        problem = name_problem(path.name)
        if problem:
            problems.append(f"{label}: {problem}")
        if len(relative.parts) == 1 and path.name.casefold() == "data":
            problems.append(f"{label}: payload must contain Data contents directly")
        if path.is_file():
            lower = path.name.lower()
            if path.suffix.lower() in NATIVE_SUFFIXES or ".so." in lower:
                problems.append(f"{label}: native binaries are outside this project")
            files.append(path)
    if not files:
        problems.append("payload/: no files to ship (.gitkeep does not count)")
    if problems:
        raise FixError("\n".join(problems))
    return payload, sorted(files, key=lambda path: path.relative_to(payload).as_posix())


def package_fix(root, fix_id):
    payload, files = check_fix(root, fix_id)
    destination = root / "dist"
    if destination.is_symlink():
        raise FixError("dist/ must not be a symlink.")
    destination.mkdir(exist_ok=True)
    archive = destination / f"{fix_id}.zip"
    created = False
    try:
        with archive.open("xb") as stream:
            created = True
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as output:
                for path in files:
                    output.write(path, path.relative_to(payload).as_posix())
    except BaseException:
        if created:
            archive.unlink(missing_ok=True)
        raise
    checksum = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    print(f"Created {archive}\nFiles: {len(files)}\nSHA256: {checksum.hexdigest()}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("new", "check", "package"))
    parser.add_argument("fix_id", help="e.g. 0001-example-fix")
    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            create_fix(ROOT, args.fix_id)
        elif args.command == "check":
            _, files = check_fix(ROOT, args.fix_id)
            print(f"OK: {args.fix_id}; {len(files)} payload file(s). Structural check only.")
        else:
            package_fix(ROOT, args.fix_id)
    except (FixError, OSError, UnicodeError, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
