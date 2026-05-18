"""
SSH DataSource 集成测试。
运行前需要：
1. 复制 config.example.yaml 为 config.yaml 并填入真实 SSH 信息
2. pip install pytest pytest-asyncio
3. pytest tests/test_ssh_datasource.py -v
"""
import pytest
import pytest_asyncio
from pathlib import Path

# 跳过条件：config.yaml 不存在时跳过（CI 环境）
CONFIG_EXISTS = (Path(__file__).parent.parent / "config.yaml").exists()
skip_no_config = pytest.mark.skipif(not CONFIG_EXISTS, reason="需要 config.yaml")


@pytest.fixture
def settings():
    from app.core.settings import load_settings
    return load_settings()


@pytest.fixture
def datasource(settings):
    from app.core.datasource.factory import create_datasource
    return create_datasource(settings)


@skip_no_config
@pytest.mark.asyncio
async def test_health_check(datasource):
    result = await datasource.health_check()
    assert result["status"] == "ok", f"健康检查失败: {result}"


@skip_no_config
@pytest.mark.asyncio
async def test_search_returns_result(datasource):
    result = await datasource.search(query="", limit=10)
    assert result.total >= 0
    assert result.took_ms >= 0


@skip_no_config
@pytest.mark.asyncio
async def test_search_with_keyword(datasource):
    result = await datasource.search(query="ERROR", level="ERROR", limit=20)
    for entry in result.entries:
        assert entry.level in ("ERROR", "UNKNOWN"), f"意外的级别: {entry.level}"


@skip_no_config
@pytest.mark.asyncio
async def test_aggregate_level(datasource):
    counts = await datasource.aggregate(field="level")
    assert isinstance(counts, dict)


@skip_no_config
@pytest.mark.asyncio
async def test_time_series(datasource):
    series = await datasource.time_series(interval="1h")
    assert isinstance(series, list)
    for point in series:
        assert "timestamp" in point
        assert "count" in point
