
from app.directory_crawler import is_safe_public_url


def test_rejects_localhost():
    assert not is_safe_public_url("http://127.0.0.1")


def test_rejects_private_ipv4():
    assert not is_safe_public_url("http://192.168.1.1")
    assert not is_safe_public_url("http://10.0.0.1")


def test_rejects_invalid_scheme():
    assert not is_safe_public_url("file:///etc/passwd")


def test_rejects_invalid_url():
    assert not is_safe_public_url("not-a-url")
