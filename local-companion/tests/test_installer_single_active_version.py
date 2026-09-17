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
    assert 'ExeCommand="--prepare-major-upgrade --target-version [ProductVersion]"' in prepare
    assert 'Execute="immediate"' in prepare
    assert 'Return="check"' in prepare
    assert '<Custom Action="PrepareInstall" Before="InstallInitialize" Condition=\'NOT (REMOVE="ALL")\' />' in source

    verify = _action(source, "VerifyInstalledTarget")
    assert 'BinaryRef="TDACompanionMaintenanceUpgradeBinary"' in verify
    assert 'ExeCommand="--verify-installed-target --target-version [ProductVersion]"' in verify
    assert 'Execute="deferred"' in verify
    assert 'Return="check"' in verify
    assert '<Custom Action="VerifyInstalledTarget" After="InstallFiles" Condition=\'NOT (REMOVE="ALL")\' />' in source


def test_transaction_queues_candidate_cleanup_on_rollback_and_guard_cleanup_on_commit():
    source = _wxs()

    rollback = _action(source, "RollbackInstallationGuard")
    commit = _action(source, "CommitInstallationGuard")
    assert 'ExeCommand="--rollback-major-upgrade"' in rollback
    assert 'Execute="rollback"' in rollback
    assert 'ExeCommand="--finish-major-upgrade"' in commit
    assert 'Execute="commit"' in commit
    assert '<Custom Action="RollbackInstallationGuard" After="InstallInitialize"' in source
    assert '<Custom Action="CommitInstallationGuard" Before="InstallFinalize"' in source


def test_process_cleanup_and_candidate_health_failures_are_never_ignored():
    source = _wxs()

    prepare = _action(source, "PrepareInstall")
    verify = _action(source, "VerifyInstalledTarget")
    uninstall = _action(source, "PrepareUninstall")
    assert 'Return="check"' in prepare
    assert 'Return="check"' in verify
    assert 'Return="check"' in uninstall


def test_cached_old_product_uninstall_does_not_run_new_package_guard_actions():
    source = _wxs()

    assert 'Condition=\'(REMOVE="ALL") AND (NOT UPGRADINGPRODUCTCODE)\'' in source
    assert 'Condition=\'NOT (REMOVE="ALL") AND (NOT UPGRADINGPRODUCTCODE)\'' in source
