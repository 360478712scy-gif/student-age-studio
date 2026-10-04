"""Add the unmodified Microsoft offline installer to a verified Windows ZIP.

This never runs the installer. Original ZIP members and their compressed data
remain unchanged; added prerequisites have their own integrity manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile


INSTALLER_NAME = "NDP48-x86-x64-AllOS-ENU.exe"
INSTALLER_SHA256 = "0a3a390c47e639d0f7fc65b21195fee6b7f65b066f80f70c60fab191d14b7e40"
INSTALLER_URL = "https://go.microsoft.com/fwlink/?linkid=2088631"
INSTALLER_DIRECT_URL = "https://download.microsoft.com/download/f/3/a/f3a6af84-da23-40a5-8d1c-49cc10c8e76f/NDP48-x86-x64-AllOS-ENU.exe"
README = """微软 .NET Framework 4.8 离线安装组件

能正常打开拾光工坊的电脑无需操作。程序不会自动运行此安装器，也不会因附带此目录而修改系统。

仅在拾光工坊启动失败、诊断明确显示 .NET Framework 缺失或版本过旧时，手动双击本目录的 NDP48-x86-x64-AllOS-ENU.exe，按微软安装器提示安装，再重新打开拾光工坊。
若 .NET 已被移除，导致拾光工坊启动器本身无法打开，仍可直接运行这个原生微软安装器；安装器会检查本机是否适用。
安装可能需要管理员确认。请阅读微软许可条款，按安装器提示决定是否重启；工坊不会自动安装或重启电脑。

此安装器用于补装 .NET Framework，不修复工坊安装包中的缺失或损坏文件，也不解除工坊 DLL 的下载限制。上述情况请使用启动诊断中的对应修复入口，或将官方完整包重新解压到新目录。
WebView2 是另一项依赖，缺少时使用启动诊断中的微软 WebView2 安装入口。
安装器和工坊均不会因此删除用户模组、草稿或配置；无需覆盖既有模组目录。

附带文件为微软原版 .NET Framework 4.8 Runtime 离线安装器，未作修改。
官方来源：https://go.microsoft.com/fwlink/?linkid=2088631
SHA256：{installer_sha256}
微软下载页：https://dotnet.microsoft.com/en-us/download/dotnet-framework/net48
"""


def digest(path: Path, limit: int | None = None) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = limit
        while remaining is None or remaining > 0:
            block = stream.read(1024 * 1024 if remaining is None else min(1024 * 1024, remaining))
            if not block:
                break
            value.update(block)
            if remaining is not None:
                remaining -= len(block)
        if remaining not in (None, 0):
            raise ValueError(f"File truncated: {path}")
    return value.hexdigest()


def check_sha(path: Path, expected: str) -> str:
    expected = expected.lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("SHA256 pin must contain exactly 64 hexadecimal characters")
    actual = digest(path)
    if actual != expected:
        raise ValueError(f"SHA256 mismatch: {path.name}; expected {expected}, got {actual}")
    return actual


def prepare_directory(package: Path, installer: Path, installer_sha256: str) -> dict:
    """Used by build.ps1 after Windows Authenticode verification."""
    actual = check_sha(installer, installer_sha256)
    target = package / "prerequisites"
    target.mkdir(parents=True, exist_ok=True)
    copied = target / INSTALLER_NAME
    shutil.copyfile(installer, copied)
    check_sha(copied, actual)
    readme = target / "使用说明.txt"
    readme.write_text(README.format(installer_sha256=actual), encoding="utf-8-sig")
    manifest = {
        "component": "Microsoft .NET Framework 4.8 Runtime offline installer",
        "source": INSTALLER_URL,
        "directSource": INSTALLER_DIRECT_URL,
        "files": {INSTALLER_NAME: actual, readme.name: digest(readme)},
        "installation": "manual-only; never run by the application or this tool",
    }
    (target / "SHA256SUMS.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def package_prefix(names: list[str]) -> str:
    if len(names) != len(set(names)):
        raise ValueError("Base ZIP contains duplicate member names")
    for name in names:
        path = PurePosixPath(name)
        if "\\" in name or path.is_absolute() or ".." in path.parts or ":" in name:
            raise ValueError(f"Unsafe ZIP member: {name}")
    launchers = [name for name in names if name == "拾光工坊.exe" or name.endswith("/拾光工坊.exe")]
    prefixes = [name.removesuffix("拾光工坊.exe") for name in launchers]
    prefixes = [prefix for prefix in prefixes if prefix + "runtime/StudioEngine.exe" in names]
    if len(prefixes) != 1:
        raise ValueError("Expected one package containing 拾光工坊.exe and runtime/StudioEngine.exe")
    prefix = prefixes[0]
    if any(not name.startswith(prefix) for name in names):
        raise ValueError("Base ZIP contains files outside the package directory")
    if any(name.startswith(prefix + "prerequisites/") for name in names):
        raise ValueError("Base ZIP already contains prerequisites; refusing to replace files")
    return prefix


def bundle(base_zip: Path, installer: Path, output: Path, installer_sha256: str, base_sha256: str | None = None) -> dict:
    base_zip, installer, output = (path.resolve() for path in (base_zip, installer, output))
    if output in (base_zip, installer):
        raise ValueError("Output must be separate from the base ZIP and installer")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    actual_installer_sha = check_sha(installer, installer_sha256)
    actual_base_sha = check_sha(base_zip, base_sha256) if base_sha256 else digest(base_zip)
    with zipfile.ZipFile(base_zip) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        prefix = package_prefix(names)
        original_data_end = archive.start_dir
        original_comment = archive.comment
        original_metadata = [(info.filename, info.CRC, info.file_size, info.compress_size, info.header_offset) for info in infos]
    original_data_sha = digest(base_zip, original_data_end)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(base_zip, temporary)
        with tempfile.TemporaryDirectory(prefix="studio-netfx-") as work:
            component = Path(work)
            prepare_directory(component, installer, actual_installer_sha)
            # Append preserves all original local headers and compressed payloads.
            with zipfile.ZipFile(temporary, "a", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for name in (INSTALLER_NAME, "使用说明.txt", "SHA256SUMS.json"):
                    archive.write(component / "prerequisites" / name, prefix + "prerequisites/" + name)
            if digest(temporary, original_data_end) != original_data_sha:
                raise ValueError("Original ZIP member data changed during append")
            with zipfile.ZipFile(temporary) as archive:
                updated_metadata = [(info.filename, info.CRC, info.file_size, info.compress_size, info.header_offset) for info in archive.infolist()[:len(infos)]]
                if updated_metadata != original_metadata or archive.comment != original_comment:
                    raise ValueError("Original ZIP member metadata or archive comment changed")
                for name in (INSTALLER_NAME, "使用说明.txt", "SHA256SUMS.json"):
                    expected = digest(component / "prerequisites" / name)
                    with archive.open(prefix + "prerequisites/" + name) as stream:
                        actual = hashlib.sha256()
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            actual.update(block)
                    if actual.hexdigest() != expected:
                        raise ValueError(f"Added member mismatch: {name}")
        output_sha = digest(temporary)
        # Link without replacement, so another writer cannot be overwritten.
        os.link(temporary, output)
        source_count = sum("/standalone/" in "/" + name and not name.endswith("/") for name in names)
        result = {
            "result": "WINDOWS_NETFX_BUNDLE_OK", "baseZip": str(base_zip), "baseSha256": actual_base_sha,
            "outputZip": str(output), "outputSha256": output_sha, "installerSha256": actual_installer_sha,
            "packagePrefix": prefix, "originalMembersPreserved": len(infos), "standaloneFilesPreserved": source_count,
            "originalCompressedDataPreserved": True, "addedMembers": 3,
            "authenticode": "must be verified on Windows before supplying installer",
        }
        Path(str(output) + ".sha256").write_text(f"{output_sha}  {output.name}\n", encoding="ascii")
        Path(str(output) + ".bundle.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-zip", type=Path)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--installer-sha256", default=INSTALLER_SHA256)
    parser.add_argument("--base-sha256", help="Optional previously verified base ZIP SHA256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prepare-directory", type=Path, help="Populate a future build directory after Windows signature verification")
    args = parser.parse_args()
    if args.prepare_directory:
        if args.base_zip or args.output or args.base_sha256:
            parser.error("--prepare-directory cannot be combined with ZIP options")
        result = prepare_directory(args.prepare_directory.resolve(), args.installer.resolve(), args.installer_sha256)
    else:
        if not args.base_zip or not args.output:
            parser.error("--base-zip and --output are required for ZIP bundling")
        result = bundle(args.base_zip, args.installer, args.output, args.installer_sha256, args.base_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
