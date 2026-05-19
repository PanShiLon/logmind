from pathlib import Path
from typing import Optional, List

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.settings import CONFIG_PATH, reload_settings, DatasourceConfig, SSHServerConfig

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config():
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config.yaml 不存在，请先完成配置")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if "llm" in raw:
        raw["llm"]["api_key"] = "***"
    for s in raw.get("servers", []):
        if s.get("password"):
            s["password"] = "***"
    if raw.get("datasource", {}).get("password"):
        raw["datasource"]["password"] = "***"
    return raw


class ConfigUpdateRequest(BaseModel):
    content: str


@router.put("")
async def update_config(req: ConfigUpdateRequest):
    try:
        parsed = yaml.safe_load(req.content)
        if not isinstance(parsed, dict):
            raise ValueError("配置必须是 YAML 字典")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YAML 格式错误: {e}")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(req.content)

    try:
        reload_settings()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"配置校验失败: {e}")

    return {"message": "配置已保存并生效"}


@router.get("/example")
async def get_example_config():
    example = CONFIG_PATH.parent / "config.example.yaml"
    if not example.exists():
        raise HTTPException(status_code=404, detail="示例配置文件不存在")
    return {"content": example.read_text(encoding="utf-8")}


# ── 测试连接 ──────────────────────────────────────────────────

class SSHTestRequest(BaseModel):
    host: str
    port: int = 22
    username: str
    password: Optional[str] = None
    private_key_path: Optional[str] = None
    log_paths: List[str] = []


class ESTestRequest(BaseModel):
    hosts: List[str]
    username: Optional[str] = None
    password: Optional[str] = None
    index: str = "app-logs-*"
    verify_certs: bool = True


class DuckDBTestRequest(BaseModel):
    db_path: str


@router.post("/test-connection/ssh")
async def test_ssh(req: SSHTestRequest):
    try:
        import asyncssh
        connect_kwargs = {
            "host": req.host,
            "port": req.port,
            "username": req.username,
            "known_hosts": None,
        }
        if req.password:
            connect_kwargs["password"] = req.password
        elif req.private_key_path:
            connect_kwargs["client_keys"] = [req.private_key_path]

        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run("echo ok", check=True)

        # 验证日志路径是否存在
        missing = []
        if req.log_paths:
            async with asyncssh.connect(**connect_kwargs) as conn:
                for p in req.log_paths:
                    r = await conn.run(f"test -f {p} && echo exists || echo missing", check=False)
                    if "missing" in (r.stdout or ""):
                        missing.append(p)

        msg = "SSH 连接成功"
        if missing:
            msg += f"，但以下路径不存在: {', '.join(missing)}"
        return {"ok": True, "message": msg}
    except Exception as e:
        return {"ok": False, "message": f"连接失败: {str(e)}"}


@router.post("/test-connection/elasticsearch")
async def test_es(req: ESTestRequest):
    try:
        from elasticsearch import AsyncElasticsearch
        es_client = AsyncElasticsearch(
            hosts=req.hosts,
            basic_auth=(req.username, req.password) if (req.username and req.password) else None,
            verify_certs=req.verify_certs,
        )
        try:
            resp = await es_client.count(index=req.index)
            count = resp.get("count", 0)
            return {"ok": True, "message": f"ES 连接成功，索引 {req.index} 共 {count:,} 条日志"}
        except Exception:
            await es_client.ping()
            return {"ok": True, "message": f"ES 连接成功（索引 {req.index} 查询受限，但连接正常）"}
        finally:
            await es_client.close()
    except Exception as e:
        return {"ok": False, "message": f"连接失败: {str(e)}"}


@router.get("/stats")
async def get_datasource_stats():
    """首页状态栏：读取内部 config，自动探测数据源类型并返回统计。"""
    if not CONFIG_PATH.exists():
        return {"ok": False}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    ds = raw.get("datasource", {})
    ds_type = ds.get("type", "")

    if ds_type == "elasticsearch":
        try:
            from elasticsearch import AsyncElasticsearch
            username = ds.get("username")
            password = ds.get("password")
            es_client = AsyncElasticsearch(
                hosts=ds.get("hosts", []),
                basic_auth=(username, password) if (username and password) else None,
                verify_certs=ds.get("verify_certs", True),
            )
            index = ds.get("default_index", "app-logs-*")
            try:
                total = (await es_client.count(index=index)).get("count", 0)
                error_count = 0
                for level_field in ("app.level.keyword", "app.level", "level.keyword", "level"):
                    try:
                        r = await es_client.count(index=index, body={"query": {"term": {level_field: "ERROR"}}})
                        error_count = r.get("count", 0)
                        if error_count > 0:
                            break
                    except Exception:
                        continue
                error_ratio = round(error_count / total * 100, 1) if total > 0 else 0
                return {"ok": True, "type": "elasticsearch", "total": total,
                        "error_count": error_count, "error_ratio": error_ratio}
            finally:
                await es_client.close()
        except Exception as e:
            return {"ok": False, "type": "elasticsearch", "message": str(e)}

    if ds_type == "ssh":
        servers = raw.get("servers", [])
        log_path_count = sum(len(s.get("log_paths", [])) for s in servers)
        return {"ok": True, "type": "ssh", "server_count": len(servers), "log_path_count": log_path_count}

    if ds_type == "duckdb":
        db_path = ds.get("db_path", "")
        if db_path and Path(db_path).exists():
            try:
                import duckdb
                con = duckdb.connect(db_path, read_only=True)
                tables = con.execute("SHOW TABLES").fetchall()
                con.close()
                return {"ok": True, "type": "duckdb", "table_count": len(tables)}
            except Exception as e:
                return {"ok": False, "type": "duckdb", "message": str(e)}
        return {"ok": False, "type": "duckdb"}

    return {"ok": False}


@router.post("/preview/elasticsearch")
async def preview_es(req: ESTestRequest):
    """测试连接成功后调用，返回服务列表/总量/ERROR 占比，用于配置页预览。"""
    try:
        from elasticsearch import AsyncElasticsearch
        es_client = AsyncElasticsearch(
            hosts=req.hosts,
            basic_auth=(req.username, req.password) if (req.username and req.password) else None,
            verify_certs=req.verify_certs,
        )
        try:
            # 总文档数
            count_resp = await es_client.count(index=req.index)
            total = count_resp.get("count", 0)

            # ERROR 数量
            # 尝试多个常见 level 字段名
            error_count = 0
            for level_field in ("app.level.keyword", "app.level", "level.keyword", "level"):
                try:
                    error_resp = await es_client.count(
                        index=req.index,
                        body={"query": {"term": {level_field: "ERROR"}}},
                    )
                    error_count = error_resp.get("count", 0)
                    if error_count > 0:
                        break
                except Exception:
                    continue

            # 各服务文档数（取 top 20），尝试多个常见服务字段名
            buckets = []
            for svc_field in ("app.service_name.keyword", "app.service_name", "service.keyword", "service"):
                try:
                    agg_resp = await es_client.search(
                        index=req.index,
                        body={
                            "size": 0,
                            "aggs": {
                                "services": {
                                    "terms": {"field": svc_field, "size": 20}
                                }
                            },
                        },
                    )
                    buckets = agg_resp.get("aggregations", {}).get("services", {}).get("buckets", [])
                    if buckets:
                        break
                except Exception:
                    continue
            buckets = buckets
            services = [{"name": b["key"], "count": b["doc_count"]} for b in buckets]

            error_ratio = round(error_count / total * 100, 1) if total > 0 else 0
            return {
                "ok": True,
                "total": total,
                "error_count": error_count,
                "error_ratio": error_ratio,
                "services": services,
            }
        finally:
            await es_client.close()
    except Exception as e:
        msg = str(e)
        if "401" in msg or "authentication" in msg.lower() or "credentials" in msg.lower():
            msg = "索引需要认证，请在密码框填入 ES 密码后重试"
        return {"ok": False, "message": f"预览数据失败: {msg}"}


class LLMTestRequest(BaseModel):
    provider: str
    api_key: str
    model: str
    base_url: str


@router.post("/test-connection/llm")
async def test_llm(req: LLMTestRequest):
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=req.api_key, base_url=req.base_url)
        resp = await client.chat.completions.create(
            model=req.model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        reply = resp.choices[0].message.content or ""
        return {"ok": True, "message": f"连接成功，模型 {req.model} 响应正常"}
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg or "invalid" in msg.lower():
            msg = "API Key 无效或已过期"
        elif "404" in msg:
            msg = f"模型 {req.model} 不存在，请确认模型名称"
        elif "Connection" in msg or "connect" in msg.lower():
            msg = f"无法连接到 {req.base_url}，请检查 Base URL"
        return {"ok": False, "message": f"连接失败: {msg}"}


@router.post("/test-connection/duckdb")
async def test_duckdb(req: DuckDBTestRequest):
    try:
        import duckdb
        p = Path(req.db_path)
        if not p.exists():
            return {"ok": False, "message": f"文件不存在: {req.db_path}"}
        con = duckdb.connect(str(p), read_only=True)
        tables = con.execute("SHOW TABLES").fetchall()
        con.close()
        return {"ok": True, "message": f"DuckDB 连接成功，共 {len(tables)} 张表"}
    except Exception as e:
        return {"ok": False, "message": f"连接失败: {str(e)}"}
