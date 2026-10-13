"""Private ciphertext only. No HTTP media route or embedding serializers."""
import json
import os
import uuid
from pathlib import Path
from cryptography.fernet import Fernet
from django.conf import settings

def cipher(): return Fernet(settings.BIOMETRIC_KEY.encode())
def encrypt(data): return cipher().encrypt(data)
def decrypt(data): return cipher().decrypt(bytes(data))
def encode_embedding(vector): return encrypt(json.dumps(vector).encode())
def decode_embedding(data): return json.loads(decrypt(data))

def private_path(name):
    root = Path(settings.PRIVATE_STORAGE).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root): raise ValueError('Invalid private storage path')
    return path

def write_private(data, folder='frames'):
    name = f'{folder}/{uuid.uuid4().hex}.fernet'
    path = private_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'xb') as f:
        os.chmod(path, 0o600)
        f.write(encrypt(data))
    return name

def read_private(name): return decrypt(private_path(name).read_bytes())
def delete_private(name):
    if name: private_path(name).unlink(missing_ok=True)

def invalidate_classifier():
    # Removing encrypted coefficients also honors withdrawal/retention of biometric-derived data.
    private_path('classifier.fernet').unlink(missing_ok=True)
