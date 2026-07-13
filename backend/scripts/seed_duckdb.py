"""
DuckDB 演示数据生成脚本
生成仿真 Spring Boot 微服务日志，用于 LogMind 离线演示

使用方式：
  cd /Users/panshilong/logmind/backend
  source .venv/bin/activate
  DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib python scripts/seed_duckdb.py
"""

import os
import sys
import random
from datetime import datetime, timedelta

import duckdb

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "logmind.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

SERVICES = [
    "trade-biz", "crm-biz", "gateway", "payment-service",
    "user-center", "erp-biz", "agent-biz", "message-service",
]

ERROR_TEMPLATES = [
    (
        "java.lang.NullPointerException: Cannot invoke method on null object\n"
        "\tat cn.pangu.vend.module.{svc}.service.impl.OrderServiceImpl.createOrder(OrderServiceImpl.java:{line})\n"
        "\tat cn.pangu.vend.module.{svc}.controller.OrderController.submit(OrderController.java:{line2})\n"
        "\tat sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)"
    ),
    (
        "【请求地址】：https://api.example.com/v2/payment/create\n"
        "【请求方式】：POST\n"
        "【请求参数】：{{\"orderId\":\"{order_id}\",\"amount\":{amount}}}\n"
        "【异常信息】：java.net.SocketTimeoutException: connect timed out\n"
        "\tat java.net.PlainSocketImpl.socketConnect(Native Method)\n"
        "\tat cn.pangu.vend.module.{svc}.client.PaymentClient.doPost(PaymentClient.java:{line})"
    ),
    (
        "org.springframework.dao.DataIntegrityViolationException: could not execute statement; "
        "SQL [insert into vend_order ...]; constraint [uk_order_no]; "
        "nested exception is org.hibernate.exception.ConstraintViolationException\n"
        "\tat cn.pangu.vend.module.{svc}.dal.mysql.OrderMapper.insert(OrderMapper.java:{line})"
    ),
    (
        "Redis connection timeout: Unable to connect to redis://192.168.10.50:6379\n"
        "io.lettuce.core.RedisConnectionException: Unable to connect to 192.168.10.50:6379\n"
        "\tat io.lettuce.core.RedisConnectionException.create(RedisConnectionException.java:78)\n"
        "\tat cn.pangu.vend.module.{svc}.cache.RedisCacheManager.get(RedisCacheManager.java:{line})"
    ),
    (
        "【请求地址】：https://oapi.dingtalk.com/robot/send?access_token=xxx\n"
        "【请求方式】：POST\n"
        "【响应结果】：{{\"errcode\":310000,\"errmsg\":\"sign not match\"}}\n"
        "【异常信息】：cn.pangu.vend.framework.common.exception.ServiceException: 钉钉消息发送失败"
    ),
    (
        "Feign client call failed: {svc} -> user-center GET /api/user/info/{user_id}\n"
        "feign.RetryableException: Read timed out executing GET http://user-center/api/user/info/{user_id}\n"
        "\tat feign.FeignException.errorExecuting(FeignException.java:249)\n"
        "\tat cn.pangu.vend.module.{svc}.remote.UserCenterClient.getUserInfo(UserCenterClient.java:{line})"
    ),
]

WARN_TEMPLATES = [
    "Slow SQL detected: SELECT * FROM vend_device_info WHERE tenant_id = {tid} took {ms}ms (threshold: 200ms)",
    "Thread pool [async-executor] is 80% full: active={active}, max=200. Consider increasing pool size.",
    "API rate limit approaching: {svc} has used {used}/1000 requests in current window",
    "Cache miss rate too high for key pattern 'device:info:*': {rate}% (threshold: 30%)",
    "MQ consumer lag detected: queue={svc}.order.queue, lag={lag} messages, consumer count=2",
    "JWT token will expire in 5 minutes for user {user_id}, session auto-renewal triggered",
]

INFO_TEMPLATES = [
    "【请求地址】：https://api.{svc}.internal/v1/order/list\n【请求方式】：GET\n【响应结果】：{{\"code\":0,\"data\":{{\"total\":{total},\"page\":{page}}}}}",
    "Order created successfully: orderId={order_id}, userId={user_id}, amount=¥{amount}, payChannel=wechat",
    "Device heartbeat received: deviceId=VD-{device_id}, status=ONLINE, temperature={temp}°C, signal={signal}%",
    "Scheduled task [dailySalesReport] completed in {ms}ms, processed {count} devices",
    "User login: userId={user_id}, ip=192.168.{ip1}.{ip2}, device=iPhone, location=北京市朝阳区",
    "Sale plan generated for device VD-{device_id}: {sku_count} SKUs, total capacity {cap} slots",
    "Inventory sync completed: warehouse=WH-{wh_id}, synced {count} items, {diff} differences found",
    "Payment callback received: orderId={order_id}, transactionId=T{tx_id}, status=SUCCESS, amount=¥{amount}",
]

DEBUG_TEMPLATES = [
    "SQL: SELECT d.* FROM vend_device_info d WHERE d.tenant_id = {tid} AND d.status = 1 LIMIT 50 -- took {ms}ms",
    "HTTP request: {method} /api/{svc}/v1/resource/{res_id} -> 200 ({ms}ms)",
    "Cache hit: key=device:stock:{device_id}, ttl=298s",
    "MQ message published: exchange={svc}.exchange, routingKey=order.created, messageId={msg_id}",
]


def gen_error(ts, svc):
    tpl = random.choice(ERROR_TEMPLATES)
    msg = tpl.format(
        svc=svc.replace("-", "."),
        line=random.randint(50, 500),
        line2=random.randint(30, 200),
        order_id=f"ORD{random.randint(100000, 999999)}",
        amount=round(random.uniform(1, 500), 2),
        user_id=random.randint(10000, 99999),
    )
    return (ts, "ERROR", msg, svc, f"[{ts}] [ERROR] [{svc}] {msg[:200]}")


def gen_warn(ts, svc):
    tpl = random.choice(WARN_TEMPLATES)
    msg = tpl.format(
        svc=svc, tid=random.randint(1, 50), ms=random.randint(200, 3000),
        active=random.randint(140, 195), used=random.randint(700, 990),
        rate=random.randint(30, 65), lag=random.randint(100, 5000),
        user_id=random.randint(10000, 99999),
    )
    return (ts, "WARN", msg, svc, f"[{ts}] [WARN] [{svc}] {msg[:200]}")


def gen_info(ts, svc):
    tpl = random.choice(INFO_TEMPLATES)
    msg = tpl.format(
        svc=svc, total=random.randint(1, 500), page=random.randint(1, 10),
        order_id=f"ORD{random.randint(100000, 999999)}",
        user_id=random.randint(10000, 99999),
        amount=round(random.uniform(1, 500), 2),
        device_id=random.randint(10000, 99999),
        temp=random.randint(15, 45), signal=random.randint(40, 100),
        ms=random.randint(10, 2000), count=random.randint(10, 500),
        ip1=random.randint(1, 255), ip2=random.randint(1, 255),
        sku_count=random.randint(5, 30), cap=random.randint(20, 60),
        wh_id=random.randint(1, 20), diff=random.randint(0, 10),
        tx_id=random.randint(10000000, 99999999),
    )
    return (ts, "INFO", msg, svc, f"[{ts}] [INFO] [{svc}] {msg[:200]}")


def gen_debug(ts, svc):
    tpl = random.choice(DEBUG_TEMPLATES)
    msg = tpl.format(
        svc=svc, tid=random.randint(1, 50), ms=random.randint(1, 100),
        method=random.choice(["GET", "POST", "PUT"]),
        res_id=random.randint(1, 9999),
        device_id=random.randint(10000, 99999),
        msg_id=f"MSG{random.randint(100000, 999999)}",
    )
    return (ts, "DEBUG", msg, svc, f"[{ts}] [DEBUG] [{svc}] {msg[:200]}")


def main():
    conn = duckdb.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id      BIGINT PRIMARY KEY,
            ts      TIMESTAMP,
            level   VARCHAR,
            message TEXT,
            source  VARCHAR,
            raw     TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON logs(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_level ON logs(level)")
    conn.execute("DELETE FROM logs")

    now = datetime.now()
    start = now - timedelta(hours=48)
    rows = []
    log_id = 1

    # 模拟 48 小时的日志，ERROR 集中在某些时段制造波动
    error_spike_hours = {
        (now - timedelta(hours=3)).hour,
        (now - timedelta(hours=8)).hour,
        (now - timedelta(hours=24)).hour,
    }

    current = start
    while current <= now:
        hour = current.hour
        minute_logs = random.randint(5, 15)

        for _ in range(minute_logs):
            ts = current + timedelta(seconds=random.randint(0, 59))
            svc = random.choice(SERVICES)

            if hour in error_spike_hours and random.random() < 0.3:
                row = gen_error(ts, svc)
            elif random.random() < 0.05:
                row = gen_error(ts, svc)
            elif random.random() < 0.1:
                row = gen_warn(ts, svc)
            elif random.random() < 0.15:
                row = gen_debug(ts, svc)
            else:
                row = gen_info(ts, svc)

            rows.append((log_id, *row))
            log_id += 1

        current += timedelta(minutes=1)

    conn.executemany("INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?)", rows)

    total = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    errors = conn.execute("SELECT COUNT(*) FROM logs WHERE level = 'ERROR'").fetchone()[0]
    warns = conn.execute("SELECT COUNT(*) FROM logs WHERE level = 'WARN'").fetchone()[0]
    services = conn.execute("SELECT DISTINCT source FROM logs").fetchall()

    print(f"✅ 数据生成完成！")
    print(f"   数据库：{DB_PATH}")
    print(f"   总条数：{total}")
    print(f"   ERROR：{errors}")
    print(f"   WARN：{warns}")
    print(f"   服务数：{len(services)} ({', '.join(r[0] for r in services)})")
    print(f"   时间范围：{start.strftime('%Y-%m-%d %H:%M')} ~ {now.strftime('%Y-%m-%d %H:%M')}")
    print()
    print(f"接下来修改 config.yaml 的 datasource.type 为 duckdb 即可启动")

    conn.close()


if __name__ == "__main__":
    main()
