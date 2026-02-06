class AuthService:
    def validate_session(self, token: str) -> bool:
        if not token:
            return False
        return token.startswith("sess_")

def login(username, password):
    if username == "admin" and password == "admin":
        return "sess_123"
    return None
