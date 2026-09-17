from __future__ import annotations

from pathlib import Path


def _wxs() -> str:
    return (
        Path(__file__).parents[1]
        / "packaging"
        / "TDACompanion.wxs"
    ).read_text(encoding="utf-8")


def test_major_upgrade_embeds_new_maintenance_helper_before_removing_old_product():
    source = _wxs()

    assert 'Id="TDACompanionMaintenanceUpgradeBinary"' in source
    assert 'SourceFile="!(bindpath.App)\\TDACompanionMaintenance.exe"' in source
    assert 'Id="PrepareMajorUpgrade"' in source
    assert 'BinaryRef="TDACompanionMaintenanceUpgradeBinary"' in source
    assert 'ExeCommand="--prepare-uninstall"' in source
    assert '<Custom Action="PrepareMajorUpgrade" Before="RemoveExistingProducts" Condition="WIX_UPGRADE_DETECTED" />' in source


def test_process_cleanup_failure_is_never_ignored_by_installer():
    source = _wxs()

    prepare_upgrade = source.split('Id="PrepareMajorUpgrade"', 1)[1].split("/>", 1)[0]
    prepare_uninstall = source.split('Id="PrepareUninstall"', 1)[1].split("/>", 1)[0]
    assert 'Return="check"' in prepare_upgrade
    assert 'Return="check"' in prepare_uninstall
    assert 'Condition=\'REMOVE="ALL"\'' in source
    assert "NOT UPGRADINGPRODUCTCODE" not in source
