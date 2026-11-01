"""End-to-end encryption for the phone-to-PC bridge. The phone uses the same scheme in
frontend/src/remote/crypto.ts (Web Crypto); tests check that both sides agree.

- Keys: ECDH P-256. Public keys travel as the raw uncompressed point, base64url (87 characters).
- Pairing code: first 4 bytes of SHA-256("mtrini-pair-v1" || pc_pub || phone_pub) as a big-endian
  integer, mod 1,000,000, zero-padded to 6 digits. Both screens show it; a swapped key changes it.
- Message key: HKDF-SHA256(ECDH secret, salt=SHA-256(pc_pub || phone_pub), info="mtrini-bridge-v1"), 32 bytes.
- Message: AES-256-GCM, random 12-byte IV, associated data "<from>><to>" (device ids), so a message can't
  be bounced back or redirected. The plaintext carries `ts` (ms) and a unique `id`; receivers drop
  anything older than MAX_AGE or already seen (no replays).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAX_AGE = 120  # seconds a message stays valid


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def new_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def private_to_str(key: ec.EllipticCurvePrivateKey) -> str:
    return b64u(key.private_numbers().private_value.to_bytes(32, "big"))


def private_from_str(s: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(unb64u(s), "big"), ec.SECP256R1())


def public_str(key: ec.EllipticCurvePrivateKey) -> str:
    return b64u(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))


def pairing_code(pc_pub: str, phone_pub: str) -> str:
    d = hashlib.sha256(b"mtrini-pair-v1" + unb64u(pc_pub) + unb64u(phone_pub)).digest()
    return f"{int.from_bytes(d[:4], 'big') % 1_000_000:06d}"


def shared_key(private: ec.EllipticCurvePrivateKey, peer_pub: str, pc_pub: str, phone_pub: str) -> bytes:
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(peer_pub))
    secret = private.exchange(ec.ECDH(), peer)
    salt = hashlib.sha256(unb64u(pc_pub) + unb64u(phone_pub)).digest()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"mtrini-bridge-v1").derive(secret)


def seal(key: bytes, sender: str, receiver: str, payload: dict) -> dict:
    body = {**payload, "ts": int(time.time() * 1000), "id": b64u(os.urandom(12))}
    iv = os.urandom(12)
    c = AESGCM(key).encrypt(iv, json.dumps(body, separators=(",", ":")).encode(), f"{sender}>{receiver}".encode())
    return {"v": 1, "iv": b64u(iv), "c": b64u(c)}


class Opener:
    """Decrypts messages from one peer and refuses old or repeated ones."""

    def __init__(self, key: bytes, sender: str, receiver: str):
        self.key, self.aad = key, f"{sender}>{receiver}".encode()
        self.seen: dict[str, float] = {}

    def open(self, box: dict) -> dict:
        if not isinstance(box, dict) or box.get("v") != 1:
            raise ValueError("unknown message format")
        body = json.loads(AESGCM(self.key).decrypt(unb64u(box["iv"]), unb64u(box["c"]), self.aad))
        now = time.time()
        if abs(now - body.get("ts", 0) / 1000) > MAX_AGE:
            raise ValueError("message too old")
        mid = body.get("id")
        if not mid or mid in self.seen:
            raise ValueError("replayed message")
        self.seen = {k: t for k, t in self.seen.items() if now - t < MAX_AGE * 2}
        self.seen[mid] = now
        return body
