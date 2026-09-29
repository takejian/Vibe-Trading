"""Operator-only third-party finance skill package import and sync.

Two entry points:

* :func:`import_zip_bytes` — validate and install one uploaded zip archive
  (or none/all: every packaged skill must pass the gate or the whole archive
  is rejected and nothing is installed).
* :func:`sync_from_source` — one-click sync from a configured local directory
  or an http(s) zip URL; a manifest records which packages sync owns so a
  delisted package can be removed without ever touching bundled skills or
  manually imported ones.

Installed packages land in ``<runtime_root>/skills/user/<skill-slug>/`` and
are picked up by :class:`src.agent.skills.SkillsLoader` immediately. Packages
are documentation only — nothing inside is executed during import.

Gate (BDD 3.9): every package needs ``SKILL.md`` with non-empty name,
description and body, and must be finance-related (keyword hit on
name/description/category/body, or frontmatter ``finance: true``); otherwise
assembly refuses with per-package reasons.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass

from src.agent.frontmatter import parse_frontmatter
from src.config.paths import (
    get_skill_approvals_file,
    get_skill_sync_manifest_file,
    get_user_skills_dir,
)
from src.swarm.skill_catalog import is_finance_related

#: Archive safety limits.
_MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
_MAX_ARCHIVE_FILES = 300
_MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
_MAX_SKILL_NAME_LEN = 80
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


class SkillPackageError(ValueError):
    """Package failed the assembly gate; ``reasons`` lists every problem."""

    def __init__(self, reasons: str | list[str]) -> None:
        self.reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass
class InstalledPackage:
    name: str
    slug: str
    sha: str
    kind: str  # "installed" (new/updated via import) | "added" | "updated"


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug[:80] or "skill"


def _validate_package_dir(path: str) -> tuple[str, str, str]:
    """Validate one extracted package directory.

    Returns ``(name, slug, sha256)``. Raises :class:`SkillPackageError` with
    all collected reasons.
    """
    reasons: list[str] = []
    skill_file = os.path.join(path, "SKILL.md")
    if not os.path.isfile(skill_file):
        raise SkillPackageError("缺少 SKILL.md")
    try:
        text = open(skill_file, encoding="utf-8").read()
    except UnicodeDecodeError:
        raise SkillPackageError("SKILL.md 必须为 UTF-8 文本") from None

    meta, body = parse_frontmatter(text)
    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()
    category = str(meta.get("category", "")).strip()

    if not name:
        reasons.append("SKILL.md frontmatter 缺少 name")
    elif len(name) > _MAX_SKILL_NAME_LEN:
        reasons.append(f"技能名称超过 {_MAX_SKILL_NAME_LEN} 字符")
    if not description:
        reasons.append("SKILL.md frontmatter 缺少 description")
    if not body.strip():
        reasons.append("SKILL.md 正文为空")

    if name and not is_finance_related(name, description, category, body, meta):
        reasons.append(
            "技能与金融业务无关（名称/描述/正文未命中金融领域关键词，"
            "可在 frontmatter 设置 finance: true 显式声明）"
        )

    if reasons:
        label = name or os.path.basename(path)
        raise SkillPackageError([f"[{label}] {reason}" for reason in reasons])

    sha = hashlib.sha256()
    for root, _dirs, files in os.walk(path):
        for filename in sorted(files):
            file_path = os.path.join(root, filename)
            rel = os.path.relpath(file_path, path)
            sha.update(rel.encode("utf-8"))
            with open(file_path, "rb") as handle:
                sha.update(handle.read())
    return name, _slugify(name), sha.hexdigest()


def _safe_extract_zip(archive: zipfile.ZipFile, dest: str) -> None:
    """Extract a zip refusing traversal, absolute paths, symlinks and bombs."""
    total_size = 0
    for member in archive.infolist():
        name = member.filename
        if name.endswith("/"):
            continue
        if len(archive.infolist()) > _MAX_ARCHIVE_FILES:
            raise SkillPackageError(f"压缩包文件数超过上限 {_MAX_ARCHIVE_FILES}")
        if os.path.isabs(name) or name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/"):
            raise SkillPackageError(f"压缩包含非法路径: {name!r}")
        # Reject symlinks/hardlinks (Unix mode high bits: S_IFLNK=0xA000).
        mode = (member.external_attr >> 16) & 0xFFFF
        if mode and (mode & 0o170000) == 0o120000:
            raise SkillPackageError(f"压缩包不允许包含符号链接: {name!r}")
        total_size += member.file_size
        if total_size > _MAX_UNCOMPRESSED_BYTES:
            raise SkillPackageError("压缩包解压后体积超过上限")
        target = os.path.join(dest, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with archive.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)


def _package_dirs(root: str) -> list[str]:
    """Find package directories (each holding SKILL.md) under root."""
    if os.path.isfile(os.path.join(root, "SKILL.md")):
        return [root]
    found: list[str] = []
    for entry in sorted(os.listdir(root)):
        candidate = os.path.join(root, entry)
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "SKILL.md")):
            found.append(candidate)
    return found


def _install_package_dir(src_dir: str) -> InstalledPackage:
    name, slug, sha = _validate_package_dir(src_dir)
    target_root = get_user_skills_dir()
    os.makedirs(target_root, exist_ok=True)
    dest = os.path.join(target_root, slug)
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src_dir, dest)
    return InstalledPackage(name=name, slug=slug, sha=sha, kind="installed")


def import_zip_bytes(payload: bytes) -> list[InstalledPackage]:
    """Validate and install packages from an uploaded zip (all-or-nothing).

    Raises:
        SkillPackageError: Any package fails the gate, or the archive itself
            is unsafe; nothing is installed in that case.
    """
    if not payload:
        raise SkillPackageError("上传内容为空")
    if len(payload) > _MAX_ARCHIVE_BYTES:
        raise SkillPackageError(f"压缩包体积超过上限 {_MAX_ARCHIVE_BYTES // (1024 * 1024)}MB")

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile:
        raise SkillPackageError("文件不是合法的 zip 压缩包") from None

    with tempfile.TemporaryDirectory(prefix="skill-import-") as work:
        try:
            _safe_extract_zip(archive, work)
        finally:
            archive.close()
        package_dirs = _package_dirs(work)
        if not package_dirs:
            raise SkillPackageError("压缩包内未找到包含 SKILL.md 的技能目录")

        # Validate everything first → atomic all-or-nothing assembly.
        planned: list[tuple[str, str, str]] = []
        all_reasons: list[str] = []
        for directory in package_dirs:
            try:
                planned.append(_validate_package_dir(directory))
            except SkillPackageError as exc:
                all_reasons.extend(exc.reasons)
        if all_reasons:
            raise SkillPackageError(all_reasons)

        installed: list[InstalledPackage] = []
        target_root = get_user_skills_dir()
        os.makedirs(target_root, exist_ok=True)
        for directory, (name, slug, sha) in zip(package_dirs, planned):
            dest = os.path.join(target_root, slug)
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(directory, dest)
            installed.append(InstalledPackage(name=name, slug=slug, sha=sha, kind="installed"))
        return installed


# ---------------------------------------------------------------------------
# One-click sync
# ---------------------------------------------------------------------------


def _read_manifest() -> dict:
    path = get_skill_sync_manifest_file()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"packages": {}}
    if not isinstance(data, dict) or not isinstance(data.get("packages"), dict):
        return {"packages": {}}
    return data


def _write_manifest(data: dict) -> None:
    path = get_skill_sync_manifest_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".sync-manifest-", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _remove_approval(name: str) -> None:
    """Drop a delisted skill's approval so a later re-add starts unapproved."""
    path = get_skill_approvals_file()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if isinstance(data, dict) and name in data:
        data.pop(name, None)
        fd, tmp_name = tempfile.mkstemp(prefix=".approvals-", suffix=".json", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


def sync_from_source(source: str) -> dict:
    """Synchronize finance skill packages from a configured source.

    Args:
        source: A local directory containing package directories or a
            ``http(s)://`` URL to a zip archive.

    Returns:
        ``{"added": [...], "updated": [...], "removed": [...],
           "rejected": [{name, reasons}]}``.
    """
    source = (source or "").strip()
    if not source:
        raise SkillPackageError("未配置技能同步源（VIBE_TRADING_SKILL_SYNC_SOURCE）")

    manifest = _read_manifest()
    owned: dict = dict(manifest.get("packages", {}))
    added: list[str] = []
    updated: list[str] = []
    removed: list[str] = []
    rejected: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="skill-sync-") as work:
        if source.startswith(("http://", "https://")):
            payload = _download_zip(source)
            archive_path = os.path.join(work, "source.zip")
            with open(archive_path, "wb") as handle:
                handle.write(payload)
            extract_dir = os.path.join(work, "src")
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(archive_path) as archive:
                _safe_extract_zip(archive, extract_dir)
            source_root = extract_dir
        elif os.path.isdir(os.path.expanduser(source)):
            source_root = os.path.expanduser(source)
        else:
            raise SkillPackageError(f"同步源不可访问（既非目录也非 http(s) zip 地址）: {source!r}")

        package_dirs = _package_dirs(source_root)
        present: dict[str, tuple[str, str, str]] = {}  # name -> (dir, slug, sha)
        for directory in package_dirs:
            try:
                name, slug, sha = _validate_package_dir(directory)
            except SkillPackageError as exc:
                rejected.append({"package": os.path.basename(directory), "reasons": exc.reasons})
                continue
            present[name] = (directory, slug, sha)

        target_root = get_user_skills_dir()
        os.makedirs(target_root, exist_ok=True)

        # Add / update.
        for name, (directory, slug, sha) in present.items():
            previous = owned.get(name)
            dest = os.path.join(target_root, slug)
            if previous is None:
                shutil.rmtree(dest, ignore_errors=True)
                shutil.copytree(directory, dest)
                owned[name] = {"slug": slug, "sha": sha}
                added.append(name)
            elif previous.get("sha") != sha or not os.path.isdir(dest):
                # Content changed (or the directory was lost): refresh files
                # but keep approval state untouched.
                shutil.rmtree(dest, ignore_errors=True)
                shutil.copytree(directory, dest)
                owned[name] = {"slug": slug, "sha": sha}
                updated.append(name)
            # unchanged → nothing

        # Remove packages this sync source previously owned but no longer ships.
        for name, record in list(owned.items()):
            if name in present:
                continue
            slug = str(record.get("slug") or _slugify(name))
            shutil.rmtree(os.path.join(target_root, slug), ignore_errors=True)
            owned.pop(name, None)
            _remove_approval(name)
            removed.append(name)

    manifest["packages"] = owned
    _write_manifest(manifest)
    return {
        "added": sorted(added),
        "updated": sorted(updated),
        "removed": sorted(removed),
        "rejected": rejected,
    }


def _download_zip(url: str) -> bytes:
    """Fetch a sync zip with stdlib urllib (no new runtime dependency)."""
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "vibe-trading-skill-sync"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            payload = response.read(_MAX_ARCHIVE_BYTES + 1)
    except OSError as exc:
        raise SkillPackageError(f"下载同步源失败: {exc}") from None
    if len(payload) > _MAX_ARCHIVE_BYTES:
        raise SkillPackageError("同步源压缩包体积超过上限")
    return payload
