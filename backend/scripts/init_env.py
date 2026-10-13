"""Generate backend/.env without logging secrets. Existing files are preserved."""
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    print('Existing backend/.env preserved.')
else:
    content = (root / '.env.example').read_text()
    content = content.replace('replace-with-random-secret', secrets.token_urlsafe(48))
    content = content.replace('generate-a-fernet-key', Fernet.generate_key().decode())
    target.write_text(content)
    print('Created backend/.env with random encryption and application keys.')
