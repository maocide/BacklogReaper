import os
from cryptography.fernet import Fernet
import core.paths as paths

SECRET_KEY_FILE = str(paths.get_base_dir() / "secret.key")

def _init_fernet() -> Fernet:
    """Initializes the Fernet cipher, repairing or regenerating the key if invalid or corrupted."""
    paths.ensure_dirs()
    if os.path.exists(SECRET_KEY_FILE):
        try:
            with open(SECRET_KEY_FILE, "rb") as key_file:
                key = key_file.read().strip()
            return Fernet(key)
        except Exception as e:
            print(f"[Crypto] Corrupted or invalid secret.key detected ({e}). Backing up and generating a fresh master key.")
            try:
                os.replace(SECRET_KEY_FILE, SECRET_KEY_FILE + ".bak")
            except Exception:
                pass

    key = Fernet.generate_key()
    with open(SECRET_KEY_FILE, "wb") as key_file:
        key_file.write(key)
    return Fernet(key)

_fernet = _init_fernet()

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
