from __future__ import annotations

from pathlib import Path


def _wxs() -> str:
    return (
        Path(__file__).parents[1]
        / "packaging"
        / "TDACompanion.wxs"
    ).read_text(encoding="utf-8")


def _action(source: str, action_id: str) -> str:
    return source.split(f'Id="{action_id}"', 1)[1].split("/>", 1)[0]


def test_every_install_is_guarded_before_transaction_and_candidate_verified_before_commit():
    source = _wxs()

    assert 'Id="TDACompanionMaintenanceUpgradeBinary"' in source
    assert 'SourceFile="!(bindpath.App)\\TDACompanionMaintenance.exe"' in source

    prepare = _action(source, "PrepareInstall")
    assert 'BinaryRef="TDACompanionMaintenanceUpgradeBinary"' in prepare
    assert 'ExeCommand="--prepare-major-upgrade --target-version $(Version)"' in prepare
    assert 'Execute="immediate"' in prepare
    assert 'Return="check"' in prepare
    assert '<Custom Action="PrepareInstall" Before="InstallInitialize" Condition=\'NOT (REMOVE="ALL")\' />' in source

    verify = _action(source, "VerifyInstalledTarget")
    assert 'BinaryRef="TDACompanionMaintenanceUpgradeBinary"' in verify
    assert 'ExeCommand="--verify-installed-target --target-version $(Version)"' in verify
    assert '[ProductVersion]' not in verify
    assert 'Execute="deferred"' in verify
    assert 'Return="check"' in verify
    assert '<Custom Action="VerifyInstalledTarget" After="InstallFiles" Condition=\'NOT (REMOVE="ALL")\' />' in source


def test_direct_uninstall_is_guarded_before_transaction_and_proved_again_before_removefiles():
    source = _wxs()

    prepare = _action(source, "PrepareExplicitUninstall")
    assert 'BinaryRef="TDACompanionMaintenanceUpgradeBinary"' in prepare
    assert 'ExeCommand="--prepare-explicit-uninstall"' in prepare
    assert 'Execute="immediate"' in prepare
    assert 'Return="check"' in prepare
    assert '<Custom Action="PrepareExplicitUninstall" Before="InstallInitialize" Condition=\'(REMOVE="ALL") AND (NOT UPGRADINGPRODUCTCODE)\' />' in source

    final_check = _action(source, "PrepareUninstall")
    assert 'FileRef="TDACompanionMaintenanceExe"' in final_check
    assert 'Execute="deferred"' in final_check
    assert 'Return="check"' in final_check
    assert '<Custom Action="PrepareUninstall" Before="RemoveFiles" Condition=\'(REMOVE="ALL") AND (NOT UPGRADINGPRODUCTCODE)\' />' in source


def test_transaction_queues_guard_cleanup_for_install_and_explicit_uninstall():
    source = _wxs()

    rollback = _action(source, "RollbackInstallationGuard")
    commit = _action(source, "CommitInstallationGuard")
    uninstall_rollback = _action(source, "RollbackUninstallGuard")
    uninstall_commit = _action(source, "CommitUninstallGuard")

    assert 'ExeCommand="--rollback-major-upgrade"' in rollback
    assert 'Execute="rollback"' in rollback
    assert 'ExeCommand="--finish-major-upgrade"' in commit
    assert 'Execute="commit"' in commit
    assert 'ExeCommand="--rollback-major-upgrade"' in uninstall_rollback
    assert 'Execute="rollback"' in uninstall_rollback
    assert 'ExeCommand="--finish-major-upgrade"' in uninstall_commit
    assert 'Execute="commit"' in uninstall_commit

    assert '<Custom Action="RollbackInstallationGuard" After="InstallInitialize"' in source
    assert '<Custom Action="CommitInstallationGuard" Before="InstallFinalize"' in source
    assert '<Custom Action="RollbackUninstallGuard" After="InstallInitialize"' in source
    assert '<Custom Action="CommitUninstallGuard" Before="InstallFinalize"' in source


def test_destructive_cleanup_and_candidate_health_failures_are_never_ignored():
    source = _wxs()

    prepare = _action(source, "PrepareInstall")
    prepare_uninstall = _action(source, "PrepareExplicitUninstall")
    verify = _action(source, "VerifyInstalledTarget")
    final_uninstall = _action(source, "PrepareUninstall")
    assert 'Return="check"' in prepare
    assert 'Return="check"' in prepare_uninstall
    assert 'Return="check"' in verify
    assert 'Return="check"' in final_uninstall


def test_cached_old_product_uninstall_cannot_touch_new_package_guard():
    source = _wxs()

    direct_uninstall = '(REMOVE="ALL") AND (NOT UPGRADINGPRODUCTCODE)'
    install_commit = 'NOT (REMOVE="ALL") AND (NOT UPGRADINGPRODUCTCODE)'
    assert direct_uninstall in source
    assert install_commit in source
