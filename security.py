from passlib.context import CryptContext  # 用來統一管理密碼雜湊（Hashing）演算法、驗證邏輯與無縫升級機制

# 設定加密方式 : bcrypt（業界常用、安全性高的密碼雜湊演算法）
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

# 登入的時候，.verify 把使用者輸入的密碼，跟資料庫裡存的加密密碼做比對，回傳 True 或 False
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)