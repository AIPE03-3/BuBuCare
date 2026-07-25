# backend/core/s3.py
# 把 DB 存的 s3://bucket/key 換成前端能播放的限時網址（presigned URL）。
# bucket 保持私有，網址帶簽章、TTL 秒後失效。
from functools import lru_cache

import boto3

from backend.core.config import (
    S3_ACCESS_KEY_ID,
    S3_REGION,
    S3_SECRET_ACCESS_KEY,
    S3_URL_TTL,
)

'''
端點收到請求 → 呼叫函式 3 → 函式 3 用函式 2 拆地址、用函式 1 拿通行證 → 跟 AWS 換一張限時網址 → 回給前端播放。
'''

# 通行證讓 generate_presigned_url 可以拿到限時網址
@lru_cache  # client 建一次就好；lazy：第一次真的要發網址時才建，import 當下不建（測試才好換掉）
def get_s3_client():
    return boto3.client(
        "s3",
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
    )


# 把 URI 拆成 bucket 跟 key，讓 generate_presigned_url 讀
def parse_s3_uri(uri):
    """s3://bucket/key → (bucket, key)；不是 s3:// 或缺 key 就回 None。"""
    if not isinstance(uri, str) or not uri.startswith("s3://"):
        return None
    bucket, _, key = uri[len("s3://"):].partition("/")
    if not bucket or not key:
        return None
    return (bucket, key)


# 發一張限時鑰匙網址
def generate_presigned_url(s3_uri, expires=S3_URL_TTL):
    """把 s3:// 換成限時網址；非 s3://（如舊本機路徑）或空值回 None。"""
    parsed = parse_s3_uri(s3_uri)
    if parsed is None:
        return None
    bucket, key = parsed
    return get_s3_client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires,
    )

