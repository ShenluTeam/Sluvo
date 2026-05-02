from passlib.context import CryptContext
from hashids import Hashids
from fastapi import HTTPException
from core.config import settings

# ==========================================
# Hashids ID 混淆配置
# ==========================================
hashids = Hashids(salt=settings.HASH_SALT, min_length=6)

def encode_id(raw_id: int) -> str:
    """把真实的整形ID转化为混淆的英文字符串"""
    if not raw_id: return ""
    return hashids.encode(raw_id)

def decode_id(hash_id: str) -> int:
    """把前端传来的混淆字符串还原成真实整形ID"""
    if not hash_id: raise HTTPException(status_code=400, detail="无效的资源标识符")
    # 安全防线：拒绝纯数字，防止用户手动在URL输入原始数字ID绕过加密
    if hash_id.isdigit():
        raise HTTPException(status_code=400, detail="无效的资源标识符")
    decoded = hashids.decode(hash_id)
    if not decoded:
        # 解码失败(伪造或错误的hash_id)会返回空元组
        raise HTTPException(status_code=400, detail="无效的资源标识符")
    return decoded[0]

# ==========================================
# 密码加密配置 (Bcrypt)
# ==========================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)
