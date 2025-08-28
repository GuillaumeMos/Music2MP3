# token_store.py (optionnel)
try:
    import keyring
except ImportError:
    keyring = None

class RefreshTokenStore:
    def __init__(self, service="spotify2mp3", user="default"):
        self.service, self.user = service, user
    def get(self):
        if not keyring: return None
        return keyring.get_password(self.service, self.user)
    def set(self, token: str):
        if keyring:
            keyring.set_password(self.service, self.user, token)
