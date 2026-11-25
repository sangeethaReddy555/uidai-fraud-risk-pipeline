"""Print sample DEVELOPMENT tokens (Partner A, Partner B, unauthorized user).

NOT production credentials: signed with the development secret from your .env / defaults.
Usage:  python scripts/generate_dev_tokens.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import get_settings  # noqa: E402
from app.utils.tokens import make_dev_tokens  # noqa: E402

if __name__ == "__main__":
    s = get_settings()
    if not s.is_development:
        raise SystemExit("Refusing to mint dev tokens outside ENVIRONMENT=development")
    print("# DEVELOPMENT TOKENS - NOT PRODUCTION CREDENTIALS (valid 24h)\n")
    for key, t in make_dev_tokens(s).items():
        print(f"{t['label']}  partner_id={t['partner_id']}  scope='{t['scope']}'\n{t['token']}\n")
