from tools.check_commit_messages import validate_subject


def test_accepts_project_commit_titles() -> None:
    assert validate_subject("feat: initialize tool") is None
    assert validate_subject("fix(cli): preserve output order") is None
    assert validate_subject("feat(parser)!: remove legacy format") is None
    assert validate_subject("chore(data): publish 2026-08-22 snapshot") is None


def test_rejects_nonconventional_commit_titles() -> None:
    assert validate_subject("Update files") is not None
    assert validate_subject("fix: trailing period.") is not None
    assert validate_subject("fix(UPPER): invalid scope") is not None
