import pymysql
from flask import request

def get_conn():
    return pymysql.connect(
        host='hk-cdb-1ix6cirn.sql.tencentcdb.com',
        port=63961,
        user='Yuri',
        password='81A6b47D3C',
        database='ai',
        charset='utf8mb4',
        autocommit=True,
    )

def get_client_ip():
    # 如果后面用 nginx / traefik，可在这里统一处理 X-Forwarded-For
    return request.headers.get('X-Forwarded-For', '').split(',')[0].strip() \
           or request.remote_addr or ''
