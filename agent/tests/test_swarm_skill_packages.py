"""Tests for operator-only finance skill package import and sync.

Covers zip safety (traversal/symlink/bomb-ish limits), the SKILL.md +
finance gate, all-or-nothing assembly into the user skills directory, and
the sync lifecycle (add=unapproved / update=approval kept / delist=removed
with approval revoked while bundled and manually imported packages stay
untouched).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from src.agent.skills import SkillsLoader
from src.swarm import skill_packages
from src.swarm.skill_approvals import SkillApprovalStore
from src.swarm.skill_packages import (
    SkillPackageError,
    import_zip_bytes,
    sync_from_source,
)


def _skill_md(name: str, *, description: str = "股票市场宏观流动性分析技能", body: str = "# 步骤\n\n跟踪利率与通胀。") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "category: macro\n"
        "---\n\n"
        f"{body}\n"
    )


def _zip_bytes(files: dict[str, str | bytes], *, symlinks: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for member, content in files.items():
            archive.writestr(member, content.encode() if isinstance(content, str) else content)
        for member, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(member)
            info.create_system = 3  # Unix
            info.external_attr = 0o120777 << 16  # S_IFLNK
            archive.writestr(info, target)
    return buffer.getvalue()


@pytest.fixture
def locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    user_dir = tmp_path / "skills" / "user"
    manifest_file = tmp_path / "skills" / "sync-manifest.json"
    approvals_file = tmp_path / "skills" / "approvals.json"
    user_dir.mkdir(parents=True)
    monkeypatch.setattr(skill_packages, "get_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr(
        skill_packages, "get_skill_sync_manifest_file", lambda: manifest_file
    )
    monkeypatch.setattr(
        skill_packages, "get_skill_approvals_file", lambda: approvals_file
    )
    return user_dir, manifest_file, approvals_file


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def test_import_valid_packaged_skill(locations) -> None:
    user_dir, _manifest, _approvals = locations
    payload = _zip_bytes(
        {
            "macro-radar/SKILL.md": _skill_md("macro-radar"),
            "macro-radar/examples.md": "# 示例\n\nA股择时示例",
        }
    )

    installed = import_zip_bytes(payload)
    assert [item.name for item in installed] == ["macro-radar"]
    assert (user_dir / "macro-radar" / "SKILL.md").exists()
    assert (user_dir / "macro-radar" / "examples.md").exists()

    loader = SkillsLoader(user_skills_dir=user_dir)
    assert {skill.name for skill in loader.skills} >= {"macro-radar"}


def test_import_accepts_skill_md_at_archive_root(locations) -> None:
    user_dir, _m, _a = locations
    installed = import_zip_bytes(_zip_bytes({"SKILL.md": _skill_md("root-radar")}))
    assert installed[0].name == "root-radar"
    assert (user_dir / "root-radar" / "SKILL.md").exists()


def test_import_rejects_non_zip_and_empty(locations) -> None:
    with pytest.raises(SkillPackageError):
        import_zip_bytes(b"not a zip at all")
    with pytest.raises(SkillPackageError):
        import_zip_bytes(b"")


def test_import_rejects_archive_without_skill_md(locations) -> None:
    with pytest.raises(SkillPackageError):
        import_zip_bytes(_zip_bytes({"readme.txt": "hello"}))


@pytest.mark.parametrize(
    "files",
    [
        {"p/SKILL.md": "---\ndescription: x\n---\n\nbody 股票\n"},  # no name
        {"p/SKILL.md": "---\nname: p\n---\n\n   \n"},  # empty body
        {
            "p/SKILL.md": "---\nname: weather\ndescription: 每日天气预报\n---\n\n出门带伞"
        },  # not finance
    ],
)
def test_import_rejects_incomplete_or_non_finance_packages(locations, files) -> None:
    user_dir, _m, _a = locations
    with pytest.raises(SkillPackageError):
        import_zip_bytes(_zip_bytes(files))
    assert not any(user_dir.iterdir())


def test_import_rejects_path_traversal(locations) -> None:
    payload = _zip_bytes(
        {
            "../evil/SKILL.md": _skill_md("evil"),
            "good/SKILL.md": _skill_md("good-skill"),
        }
    )
    with pytest.raises(SkillPackageError):
        import_zip_bytes(payload)


def test_import_rejects_symlink_members(locations) -> None:
    payload = _zip_bytes(
        {"p/SKILL.md": _skill_md("symlink-skill")},
        symlinks={"p/link": "/etc/passwd"},
    )
    with pytest.raises(SkillPackageError):
        import_zip_bytes(payload)


def test_import_is_all_or_nothing(locations) -> None:
    user_dir, _m, _a = locations
    payload = _zip_bytes(
        {
            "good/SKILL.md": _skill_md("good-skill"),
            "bad/SKILL.md": "---\nname: bad\n---\n\nrecipe book",  # non-finance
        }
    )
    with pytest.raises(SkillPackageError):
        import_zip_bytes(payload)
    assert not (user_dir / "good").exists()
    assert not (user_dir / "bad").exists()


# ---------------------------------------------------------------------------
# Sync from a local directory source
# ---------------------------------------------------------------------------


def _make_source_package(source_dir: Path, slug: str, body: str = "v1 body 股票分析") -> None:
    package_dir = source_dir / slug
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "SKILL.md").write_text(_skill_md(slug, body=body), encoding="utf-8")


def test_sync_add_update_delist_cycle(locations, tmp_path: Path) -> None:
    user_dir, _manifest, approvals_file = locations
    source = tmp_path / "sync-source"
    source.mkdir()
    approvals = SkillApprovalStore(path=approvals_file)

    # First sync: package added, unapproved by default.
    _make_source_package(source, "alpha-radar", body="v1: 利率股票择时")
    result = sync_from_source(str(source))
    assert result["added"] == ["alpha-radar"]
    assert result["updated"] == []
    assert result["removed"] == []
    assert not approvals.is_approved("alpha-radar")
    assert (user_dir / "alpha-radar" / "SKILL.md").exists()

    # A successful trial approves the skill globally.
    approvals.mark_approved("alpha-radar", source_run_id="swarm-trial-1")

    # Unchanged sync is a no-op.
    assert sync_from_source(str(source)) == {
        "added": [],
        "updated": [],
        "removed": [],
        "rejected": [],
    }

    # Content update: package reinstalled, approval state retained.
    _make_source_package(source, "alpha-radar", body="v2: 利率+通胀股票择时")
    result = sync_from_source(str(source))
    assert result["updated"] == ["alpha-radar"]
    assert approvals.is_approved("alpha-radar")
    assert "v2" in (user_dir / "alpha-radar" / "SKILL.md").read_text(encoding="utf-8")

    # Manually imported package must survive a sync that does not list it.
    manual = user_dir / "manual-skill"
    manual.mkdir()
    (manual / "SKILL.md").write_text(_skill_md("manual-skill"), encoding="utf-8")

    # Delist alpha, introduce beta: alpha removed + approval revoked; beta
    # added unapproved; the manual package stays untouched.
    (source / "alpha-radar").rename(source / "beta-radar")
    _make_source_package(source, "beta-radar", body="beta: 期货对冲")
    result = sync_from_source(str(source))
    assert result["added"] == ["beta-radar"]
    assert result["removed"] == ["alpha-radar"]
    assert not (user_dir / "alpha-radar").exists()
    assert not approvals.is_approved("alpha-radar")
    assert not approvals.is_approved("beta-radar")
    assert (user_dir / "manual-skill" / "SKILL.md").exists()
    assert (user_dir / "beta-radar" / "SKILL.md").exists()


def test_sync_reports_rejected_packages_without_blocking_others(
    locations, tmp_path: Path
) -> None:
    user_dir, _m, _a = locations
    source = tmp_path / "sync-source"
    source.mkdir()
    _make_source_package(source, "good-fin")
    bad = source / "cookbook"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\nname: cookbook\ndescription: cookie recipes\n---\n\nbake cookies",
        encoding="utf-8",
    )

    result = sync_from_source(str(source))
    assert result["added"] == ["good-fin"]
    assert len(result["rejected"]) == 1
    assert "cookbook" in result["rejected"][0]["package"]
    assert not (user_dir / "cookbook").exists()


def test_sync_empty_source_raises(locations) -> None:
    with pytest.raises(SkillPackageError):
        sync_from_source("")
    with pytest.raises(SkillPackageError):
        sync_from_source("   ")


def test_sync_missing_path_raises(locations, tmp_path: Path) -> None:
    with pytest.raises(SkillPackageError):
        sync_from_source(str(tmp_path / "does-not-exist"))
