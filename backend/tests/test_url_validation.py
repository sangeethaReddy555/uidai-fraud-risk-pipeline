import pytest

from app.utils.url_validation import UnsafeCallbackURL, validate_callback_url


def test_public_https_url_ok_with_fake_resolver():
    assert validate_callback_url("https://partner.example.com/cb", resolver=lambda h, p: ["93.184.216.34"])


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.1.2.3", "192.168.0.9", "169.254.169.254", "100.64.0.1", "::1", "::ffff:127.0.0.1", "fe80::1"])
def test_dns_answers_pointing_to_private_space_are_blocked(addr):
    with pytest.raises(UnsafeCallbackURL):
        validate_callback_url("https://rebind.example.com/cb", resolver=lambda h, p: ["93.184.216.34", addr])


def test_unresolvable_host_rejected():
    def boom(h, p):
        raise OSError("nxdomain")

    with pytest.raises(UnsafeCallbackURL):
        validate_callback_url("https://nope.example.com/cb", resolver=boom)


@pytest.mark.parametrize("url", ["http://example.com", "ftp://example.com", "https://0x7f.0.0.1/", "https://0177.0.0.1/", "https://[::ffff:7f00:1]/", "https://service.internal/", "https://example.com:22/", "https://a@example.com/"])
def test_obvious_bad_urls(url):
    with pytest.raises(UnsafeCallbackURL):
        validate_callback_url(url, resolve=False)


def test_dev_flags_allow_local_sink():
    assert validate_callback_url("http://localhost:8000/api/v1/dev/callback-sink", allow_http=True, allow_private=True)
