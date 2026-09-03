"""AES 密钥轮换工具：更换 AES_KEY 前，先把库里的密文用旧密钥解密、新密钥重新加密

df_datasource.password 使用 AES-256-CBC 加密（app.core.security）。
部署环境更换 AES_KEY 而不重加密密文，会导致数据源密码解不开（造数/同步全部失败）。

用法（在 backend/ 目录下执行）：
    # 方式一：命令行参数
    python scripts/rekey_aes.py --old-key <旧KEY_base64> --new-key <新KEY_base64>
    # 方式二：环境变量（避免密钥出现在 shell 历史）
    AES_KEY_OLD=<旧> AES_KEY_NEW=<新> python scripts/rekey_aes.py

流程：逐行解密 df_datasource.password（用旧 KEY）→ 用新 KEY 加密回写 → 校验可解 → 汇总输出。
任一行解密失败会中止（不写入），可修复后重跑（已轮换的行用新 KEY 能解密，幂等）。
"""
from __future__ import annotations

import argparse
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select, text, update

from app.config import settings
from app.models.datasource import Datasource


def _make_fns(key_b64: str):
    """按给定密钥生成加解密函数（复用 security 的算法，密钥不入全局状态）"""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = base64.b64decode(key_b64)
    if len(key) != 32:
        raise ValueError("AES_KEY 必须是 base64 编码的 32 字节")

    def decrypt(ciphertext_b64: str) -> str:
        raw = base64.b64decode(ciphertext_b64)
        iv, ciphertext = raw[:16], raw[16:]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        data = decryptor.update(ciphertext) + decryptor.finalize()
        pad_len = data[-1]
        if pad_len < 1 or pad_len > 16:
            raise ValueError("padding 非法（密钥不匹配）")
        text_out = data[:-pad_len].decode("utf-8")
        # 错误密钥有小概率解出"合法 padding 的乱码"，用可打印性拦截
        if not all(ch.isprintable() or ch in "\r\n\t" for ch in text_out):
            raise ValueError("明文不可打印（密钥不匹配）")
        return text_out

    def encrypt(plaintext: str) -> str:
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        data = plaintext.encode("utf-8")
        pad_len = 16 - (len(data) % 16)
        data += bytes([pad_len] * pad_len)
        ciphertext = encryptor.update(data) + encryptor.finalize()
        return base64.b64encode(iv + ciphertext).decode("utf-8")

    return decrypt, encrypt


def main() -> None:
    parser = argparse.ArgumentParser(description="AES 密钥轮换（df_datasource.password 重加密）")
    parser.add_argument("--old-key", default=os.environ.get("AES_KEY_OLD"), help="旧 AES_KEY（base64）")
    parser.add_argument("--new-key", default=os.environ.get("AES_KEY_NEW"), help="新 AES_KEY（base64）")
    args = parser.parse_args()
    if not args.old_key or not args.new_key:
        parser.error("请通过 --old-key/--new-key 或环境变量 AES_KEY_OLD/AES_KEY_NEW 提供密钥")
    if args.old_key == args.new_key:
        print("新旧密钥相同，无需轮换")
        return

    decrypt_old, _ = _make_fns(args.old_key)
    _, encrypt_new = _make_fns(args.new_key)
    decrypt_new, _ = _make_fns(args.new_key)

    engine = create_engine(settings.SYNC_DATABASE_URL)
    with engine.begin() as conn:
        rows = conn.execute(select(Datasource.id, Datasource.name, Datasource.password)).all()
        if not rows:
            print("df_datasource 为空，无需处理")
            return
        print(f"共 {len(rows)} 个数据源，开始轮换…")
        rotated = skipped = 0
        for ds_id, name, password_enc in rows:
            # 幂等：能用新 KEY 解开的行视为已轮换，跳过
            try:
                decrypt_new(password_enc)
                skipped += 1
                print(f"  [跳过] id={ds_id} {name}（已是新密钥）")
                continue
            except Exception:
                pass
            try:
                plain = decrypt_old(password_enc)
            except Exception as exc:
                print(f"  [失败] id={ds_id} {name}：旧密钥无法解密（{exc}），已中止，请检查密钥后重跑")
                sys.exit(1)
            conn.execute(
                update(Datasource).where(Datasource.id == ds_id).values(password=encrypt_new(plain))
            )
            rotated += 1
            print(f"  [已轮换] id={ds_id} {name}")
        print(f"完成：轮换 {rotated} 个，跳过 {skipped} 个。现在可以把 .env 的 AES_KEY 换成新密钥并重启服务了。")


if __name__ == "__main__":
    main()
