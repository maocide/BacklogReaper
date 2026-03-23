import os
from cryptography.fernet import Fernet
import core.paths as paths

SECRET_KEY_FILE = str(paths.get_base_dir() / "secret.key")

def _get_key():
    """Retrieves the encryption key. If it doesn't exist, generates and saves a new one."""
    paths.ensure_dirs()
    if not os.path.exists(SECRET_KEY_FILE):
        key = Fernet.generate_key()
        with open(SECRET_KEY_FILE, "wb") as key_file:
            key_file.write(key)
    else:
        with open(SECRET_KEY_FILE, "rb") as key_file:
            key = key_file.read()
    return key

_fernet = Fernet(_get_key())

def encrypt(data: str) -> str:
    """Encrypts a string and returns the encrypted token as a string."""
    if not data:
        return data
    try:
        token = _fernet.encrypt(data.encode('utf-8'))
        return token.decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}")
        return data

def decrypt(token: str) -> str:
    """Decrypts a token string and returns the original string.
    If it fails to decrypt (e.g., plain text), it returns the token unchanged.
    """
    if not token:
        return token
    try:
        decrypted_data = _fernet.decrypt(token.encode('utf-8'))
        return decrypted_data.decode('utf-8')
    except Exception as e:
        # Fails gracefully if the data was not encrypted
        return token
