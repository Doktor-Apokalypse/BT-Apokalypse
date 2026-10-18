from apokalypse.security import hash_password, protect_secret, unprotect_secret, verify_password


def test_password_hash_verification() -> None:
    encoded = hash_password("a-secure-password")
    assert "a-secure-password" not in encoded
    assert verify_password("a-secure-password", encoded) is True
    assert verify_password("wrong-password", encoded) is False


def test_protected_secret_round_trip() -> None:
    protected = protect_secret("proxy-secret")
    assert "proxy-secret" not in protected
    assert unprotect_secret(protected) == "proxy-secret"
