"""Password hashing, sessions, roles and permissions."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

from .db import tx
from .util import ApiError, bad, v_str, v_choice, jdump

PBKDF2_ITERATIONS = 240_000
SESSION_DAYS = 7
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 10

# Permissions that can be granted to staff. Capital, settings, users, opening
# balances and the audit log are owner-only and never grantable.
PERMISSIONS = {
    "sales.create": "Record sales",
    "sales.view_all": "View sales recorded by others",
    "returns.create": "Record sales returns",
    "purchases.create": "Record purchases",
    "purchases.view": "View full purchase history",
    "inventory.view": "View stock quantities",
    "inventory.cost": "View cost prices and inventory value",
    "inventory.adjust": "Record damage / stock corrections",
    "products.manage": "Add and edit products",
    "suppliers.manage": "Add and edit suppliers",
    "customers.manage": "Add and edit customers",
    "payments.record": "Record supplier payments and customer receipts",
    "expenses.create": "Record expenses",
    "reports.view": "View financial dashboard, profit and reports",
    "transactions.void": "Void finalised transactions",
}

DEFAULT_STAFF_PERMISSIONS = [
    "sales.create", "returns.create", "purchases.create", "inventory.view",
    "products.manage", "customers.manage",
]


def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ITERATIONS, salt.hex(), dk.hex())


def verify_password(password, stored):
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def validate_password(pw, field="password"):
    if not isinstance(pw, str) or len(pw) < 8:
        raise bad("Password must be at least 8 characters", field)
    if len(pw) > 200:
        raise bad("Password is too long", field)
    return pw


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _utcnow():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def public_user(row):
    if row is None:
        return None
    perms = json.loads(row["permissions"] or "[]")
    if row["role"] == "owner":
        perms = list(PERMISSIONS.keys())
    return {
        "id": row["id"], "username": row["username"], "full_name": row["full_name"],
        "role": row["role"], "permissions": perms, "active": bool(row["active"]),
    }


def audit(conn, user, action, entity=None, entity_id=None, details=None):
    conn.execute(
        "INSERT INTO audit_log (user_id, action, entity, entity_id, details) VALUES (?, ?, ?, ?, ?)",
        (user["id"] if user else None, action, entity, entity_id, jdump(details) if details is not None else None),
    )


def has_users(conn):
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0


def create_owner(conn, data):
    with tx(conn):
        if has_users(conn):
            raise ApiError(409, "Owner account already exists")
        full_name = v_str(data.get("full_name"), "full_name", required=True, max_len=80, label="Your name")
        username = _v_username(data.get("username"))
        password = validate_password(data.get("password"))
        shop = v_str(data.get("shop_name"), "shop_name", required=True, max_len=100, label="Shop name")
        cur = conn.execute(
            "INSERT INTO users (username, full_name, role, password_hash) VALUES (?, ?, 'owner', ?)",
            (username, full_name, hash_password(password)),
        )
        conn.execute("UPDATE settings SET value = ? WHERE key = 'shop_name'", (shop,))
        user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        audit(conn, user, "owner.create", "users", user["id"], {"username": username})
    return user


def _v_username(value):
    username = v_str(value, "username", required=True, max_len=40, label="Username").lower()
    if not all(c.isalnum() or c in "._-" for c in username) or len(username) < 3:
        raise bad("Username must be 3+ characters: letters, numbers, . _ -", "username")
    return username


def login(conn, username, password):
    username = (username or "").strip().lower()
    failure = None
    with tx(conn):
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and user["locked_until"] and user["locked_until"] > _utcnow():
            raise ApiError(429, "Too many failed attempts. Try again in a few minutes.")
        if not user or not user["active"] or not verify_password(password or "", user["password_hash"]):
            failure = ApiError(401, "Incorrect username or password")
            if user:
                fails = user["failed_logins"] + 1
                locked = None
                if fails >= MAX_FAILED_LOGINS:
                    locked = (datetime.utcnow() + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
                    fails = 0
                conn.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                             (fails, locked, user["id"]))
                audit(conn, user, "login.failed", "users", user["id"])
    if failure:  # raised after commit so the failed-attempt counter is kept
        raise failure
    with tx(conn):
        conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (user["id"],))
        token = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                     (_token_hash(token), user["id"], expires))
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_utcnow(),))
        audit(conn, user, "login", "users", user["id"])
    return token, user


def logout(conn, token):
    if token:
        with tx(conn):
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def user_for_token(conn, token):
    if not token:
        return None
    return conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1",
        (_token_hash(token), _utcnow()),
    ).fetchone()


def can(user, perm):
    if user is None:
        return False
    if user["role"] == "owner":
        return True
    if perm == "owner":
        return False
    return perm in json.loads(user["permissions"] or "[]")


def require(user, *perms):
    """Require any one of the given permissions."""
    if user is None:
        raise ApiError(401, "Please sign in")
    if not any(can(user, p) for p in perms):
        raise ApiError(403, "You do not have permission for this action")


def list_users(conn):
    return [public_user(r) for r in conn.execute("SELECT * FROM users ORDER BY role, full_name").fetchall()]


def save_user(conn, actor, data, user_id=None):
    full_name = v_str(data.get("full_name"), "full_name", required=True, max_len=80, label="Name")
    perms = data.get("permissions") or []
    if not isinstance(perms, list) or any(p not in PERMISSIONS for p in perms):
        raise bad("Invalid permissions", "permissions")
    active = 1 if data.get("active", True) else 0
    with tx(conn):
        if user_id is None:
            username = _v_username(data.get("username"))
            password = validate_password(data.get("password"))
            role = v_choice(data.get("role", "staff"), "role", ("staff",), "role")
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ApiError(409, "That username is already taken", "username")
            cur = conn.execute(
                "INSERT INTO users (username, full_name, role, password_hash, permissions, active) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (username, full_name, role, hash_password(password), json.dumps(sorted(perms)), active),
            )
            user_id = cur.lastrowid
            audit(conn, actor, "user.create", "users", user_id, {"username": username, "permissions": perms})
        else:
            target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not target:
                raise ApiError(404, "User not found")
            if target["role"] == "owner":
                active = 1
                perms = []
            conn.execute("UPDATE users SET full_name = ?, permissions = ?, active = ? WHERE id = ?",
                         (full_name, json.dumps(sorted(perms)), active, user_id))
            if data.get("password"):
                validate_password(data["password"])
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                             (hash_password(data["password"]), user_id))
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            if not active:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            audit(conn, actor, "user.update", "users", user_id,
                  {"permissions": perms, "active": active, "password_reset": bool(data.get("password"))})
    return public_user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def change_password(conn, user, current, new):
    if not verify_password(current or "", user["password_hash"]):
        raise bad("Current password is incorrect", "current_password")
    validate_password(new, "new_password")
    with tx(conn):
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), user["id"]))
        audit(conn, user, "password.change", "users", user["id"])
