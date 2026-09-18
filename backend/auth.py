import os
import datetime
import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt import PyJWKClient

import clerk

CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL")

jwks_client = PyJWKClient(CLERK_JWKS_URL) if CLERK_JWKS_URL else None
security = HTTPBearer()

# Allow up to 60 s of clock skew between Clerk's servers and this machine.
# This prevents "The token is not yet valid (iat)" errors caused by slight
# differences between the two clocks.
CLOCK_SKEW_LEEWAY = datetime.timedelta(seconds=60)

def verify_clerk_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Dependency to extract and verify the Clerk JWT.
    """
    if not jwks_client:
        raise HTTPException(status_code=500, detail="CLERK_JWKS_URL environment variable is not configured.")

    token = credentials.credentials
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            leeway=CLOCK_SKEW_LEEWAY,          # <-- tolerates clock skew
            options={"verify_aud": False},      # Clerk doesn't use aud by default
        )

        clerk_user_id = payload.get("sub")
        if not clerk_user_id:
            raise HTTPException(status_code=401, detail="Invalid JWT: missing 'sub' claim.")

        return {
            "clerk_user_id": clerk_user_id,
            # Clerk's DEFAULT session token carries no email claim at all — it
            # is only present if a custom JWT template adds one, and templates
            # spell it several ways. When it is absent the address is fetched
            # from Clerk's Backend API on demand (see clerk.py); relying on
            # this claim alone is what left every user row with email=NULL and
            # stopped rate alerts from ever mailing anyone.
            "email": clerk.email_from_claims(payload),
        }
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

def verify_admin_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    user = verify_clerk_token(credentials)
    admin_ids = [s.strip() for s in os.environ.get("ADMIN_CLERK_IDS", "").split(",") if s.strip()]
    if not admin_ids or user["clerk_user_id"] not in admin_ids:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
