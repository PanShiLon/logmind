from typing import TYPE_CHECKING
from ..settings import Settings

if TYPE_CHECKING:
    from .base import LogDataSource


def create_datasource(settings: Settings) -> "LogDataSource":
    ds_type = settings.datasource.type

    match ds_type:
        case "ssh":
            from .ssh import SSHDataSource
            return SSHDataSource(settings.servers)

        case "elasticsearch" | "es":
            from .es import ESDataSource
            return ESDataSource(settings.datasource)

        case "duckdb":
            from .duckdb import DuckDBDataSource
            return DuckDBDataSource(settings.datasource)

        case "loki":
            from .loki import LokiDataSource
            return LokiDataSource(settings.datasource)

        case _:
            raise ValueError(
                f"不支持的 datasource.type: {ds_type}，"
                f"可选值: ssh | elasticsearch | duckdb | loki"
            )
