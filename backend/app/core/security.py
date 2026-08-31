"""安全模块：bcrypt 密码哈希、JWT 认证、Token 黑名单、AES-256-CBC 加解密。

对应架构文档 6.5 / 14 章、PRD 9.3 安全要求。
注意：passlib 1.7.4 与 bcrypt>=4.1 不兼容，requirements.txt 已锁定 bcrypt<4.1。
"""

import base64
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.core.redis_client import redis_client
from app.schemas.errors import TOKEN_BLACKLISTED, UNAUTHORIZED, BizException

# bcrypt 哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT 黑名单 Redis Key 前缀（文档 5.1）
TOKEN_BLACKLIST_PREFIX = "df:token:blacklist:"


# ── 密码哈希 ─────────────────────────────────────────────────


def get_password_hash(password: str) -> str:
    """生成 bcrypt 密码哈希。"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与 bcrypt 哈希是否匹配。"""
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT 生成与校验 ────────────────────────────────────────────


def create_access_token(user_id: int, permissions: list[str]) -> str:
    """生成 JWT Token（7 天有效，含 jti 用于黑名单）。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "permissions": permissions,
        "jti": str(uuid4()),  # JWT ID，登出时加入黑名单
        "exp": now + timedelta(days=settings.JWT_EXPIRE_DAYS),
        "iat": now,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def invalidate_token(jti: str, ttl_seconds: int) -> None:
    """主动失效 Token：jti 写入 Redis 黑名单，TTL 为 Token 剩余有效期。"""
    if ttl_seconds > 0:
        await redis_client.setex(f"{TOKEN_BLACKLIST_PREFIX}{jti}", ttl_seconds, "1")


async def is_token_blacklisted(jti: str) -> bool:
    """检查 jti 是否在黑名单中。"""
    return bool(await redis_client.exists(f"{TOKEN_BLACKLIST_PREFIX}{jti}"))


async def verify_token(token: str) -> dict:
    """校验 JWT 并检查黑名单，返回 payload。

    Raises:
        BizException: 1001 Token 无效或过期；1006 Token 已被主动失效。
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as e:
        raise BizException(UNAUTHORIZED) from e
    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        raise BizException(TOKEN_BLACKLISTED)
    return payload


# ── AES-256-CBC 加解密（数据源密码加密存储，PRD 9.3）─────────────


def _get_aes_key() -> bytes:
    """AES_KEY 为 base64 编码的 32 字节密钥（文档 14.2 生成方式）。"""
    try:
        key = base64.b64decode(settings.AES_KEY)
    except Exception as e:
        raise ValueError("AES_KEY 必须是 base64 编码的 32 字节密钥") from e
    if len(key) != 32:
        raise ValueError("AES_KEY 解码后必须为 32 字节（AES-256）")
    return key


def encrypt_aes(plaintext: str) -> str:
    """AES-256-CBC 加密。密文格式：base64(iv + ciphertext)，PKCS7 填充。"""
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(_get_aes_key()), modes.CBC(iv))
    encryptor = cipher.encryptor()
    data = plaintext.encode("utf-8")
    pad_len = 16 - (len(data) % 16)
    data += bytes([pad_len] * pad_len)
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode("utf-8")


def decrypt_aes(ciphertext_b64: str) -> str:
    """AES-256-CBC 解密。输入格式：base64(iv + ciphertext)。"""
    raw = base64.b64decode(ciphertext_b64)
    iv, ciphertext = raw[:16], raw[16:]
    cipher = Cipher(algorithms.AES(_get_aes_key()), modes.CBC(iv))
    decryptor = cipher.decryptor()
    data = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = data[-1]
    return data[:-pad_len].decode("utf-8")
