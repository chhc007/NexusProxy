from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseSearchModule(ABC):
    """所有搜索模块必须继承此基类"""
    
    # 模块名称，用于日志和配置
    name: str = "base"

    def __init__(self, http_client):
        self.http_client = http_client

    @abstractmethod
    async def search(self, keyword: str) -> List[Dict[str, Any]]:
        """
        执行搜索，必须返回标准格式的字典列表。
        每个字典必须包含: title, download, torrent_id, size, filesize, seeders, leechers, year
        {
    "source": "jackett",
    "title": "...",
    "download": "magnet:?xt=urn:btih:xxxx",
    "torrent_id": "magnet:?xt=urn:btih:xxxx",
    "size": "274.20 MB",
    "filesize": 287519552,
    "seeders": 0,
    "leechers": 1,
    "year": "1920"
        }
        """
        pass
