import os
import boto3
from botocore.exceptions import ClientError

bucket_name = "xxxxx"

try:
    # 2. 直接將憑證帶入 boto3 實例
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_RO_ACCESS"),
        aws_secret_access_key=os.getenv("AWS_RO_SECRET_ACCESS"),
        region_name="ap-northeast-1" # 如果儲存桶有特定區域，可在這裡指定
    )
   
    #已確認會access denied
    #response = s3.list_objects_v2(Bucket=bucket_name)
    #print(response)

    #已確認會access denied
    #s3.upload_file("test.txt", bucket_name,"temp/test.txt")

    # 3. 執行下載
    print("正在從 S3 下載檔案...")
    s3.download_file(bucket_name, "temp/test.txt", "test_dl.txt")
    print("下載成功!")

except ClientError as e:
    # 擷取 AWS 權限或檔案不存在等錯誤
    print(f"AWS 發生錯誤：{e.response['Error']['Message']}")
except Exception as e:
    print(f"發生其他錯誤：{e}")
