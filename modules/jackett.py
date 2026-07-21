import os
import time
import logging
from xml.etree import ElementTree
from datetime import datetime
from email.utils import parsedate_to_datetime  # 用于解析 RSS 标准时间格式
from .base import BaseSearchModule
from utils import format_size, extract_year, is_bad_title

logger = logging.getLogger("NexusProxy.jackett")

class JackettModule(BaseSearchModule):
    name = "jackett"

    def __init__(self, http_client):
        super().__init__(http_client)
        self.url = os.getenv("JACKETT_URL", "http://192.168.123.146:9117").rstrip('/')
        self.apikey = os.getenv("JACKETT_APIKEY", "mpabshnoihxmj3sjpfy1qxuf5obbt66w")
        logger.info(f"[Jackett] 初始化完成, URL: {self.url}")

    def _get_attr(self, item, name):
        """从 torznab 扩展属性中获取值"""
        for attr in item.findall(".//{http://torznab.com/schemas/2015/feed}attr"):
            if attr.attrib.get("name") == name: 
                return attr.attrib.get("value")
        for attr in item.findall(".//attr"):
            if attr.attrib.get("name") == name: 
                return attr.attrib.get("value")
        return None

    async def search(self, keyword: str):
        if not self.apikey:
            logger.error("[Jackett] 未配置 JACKETT_APIKEY 环境变量！")
            return []

        params = {
            "apikey": self.apikey, "t": "search", "q": keyword,
            "limit": 400, "offset": 0, "sort": "seeders", "dir": "desc"
        } #此处可以设置返回总数，速度快的可以多一点
        
        url = f"{self.url}/api/v2.0/indexers/all/results/torznab/api"
        logger.info(f"[Jackett] 发起搜索请求: {url} | 参数: q={keyword}")
        
        start_time = time.time()
        r = await self.http_client.get(url, params=params, timeout=300)
        elapsed = time.time() - start_time
        
        logger.info(f"[Jackett] 响应状态: {r.status_code} | 耗时: {elapsed:.2f}s | 数据大小: {len(r.text)} bytes")
        
        if r.status_code != 200:
            logger.error(f"[Jackett] 请求失败，响应内容前500字符: {r.text[:500]}")
            raise Exception(f"Jackett 返回状态码 {r.status_code}")

        try:
            root = ElementTree.fromstring(r.text)
        except Exception as e:
            logger.error(f"[Jackett] XML 解析失败: {e}")
            return []
            
        items = root.findall(".//item")
        logger.debug(f"[Jackett] XML 解析出原始 item 数量: {len(items)}")
        
        torrents = []
        bad_count = 0
        no_dl_count = 0
        
        for item in items:
            raw_title = item.findtext("title") or "Unknown"
            if is_bad_title(raw_title): 
                bad_count += 1
                logger.debug(f"[Jackett] 过滤不良标题: {raw_title}")
                continue

            enclosure = item.find("enclosure")
            download = enclosure.attrib.get("url", "") if enclosure is not None else ""
            if not download: 
                download = item.findtext("link") or ""
            if not download: 
                no_dl_count += 1
                logger.debug(f"[Jackett] 过滤无下载链接: {raw_title}")
                continue

            # 解析基础数据
            try: size = int(item.findtext("size") or self._get_attr(item, "size") or 0)
            except: size = 0
            try: seeders = int(self._get_attr(item, "seeders") or 0)
            except: seeders = 0
            try: leechers = int(self._get_attr(item, "peers") or self._get_attr(item, "leechers") or 0)
            except: leechers = 0
            
            # 【新增】解析完成数 (grabs)
            try: completed = int(item.findtext("grabs") or self._get_attr(item, "grabs") or 0)
            except: completed = 0

            # 【新增】解析发布时间 (pubDate) 并格式化
            pub_date_str = item.findtext("pubDate") or ""
            formatted_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # 兜底当前时间
            if pub_date_str:
                try:
                    # 解析 RSS 标准时间格式 (如: Sun, 14 May 2023 12:00:00 +0000)
                    dt = parsedate_to_datetime(pub_date_str)
                    formatted_date = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            torrents.append({
                "source": self.name,
                "title": raw_title,
                "download": download,
                "torrent_id": item.findtext("guid") or str(abs(hash(download))),
                "size": format_size(size),
                "filesize": size,
                "seeders": seeders,
                "leechers": leechers,
                "completed": completed,           
                "date": formatted_date,          
                "promotion": "free",             
                "year": extract_year(raw_title) or ""
            })
            
        logger.info(f"[Jackett] 解析完成: 原始 {len(items)} 条 -> 过滤不良 {bad_count} 条, 无链接 {no_dl_count} 条 -> 最终有效 {len(torrents)} 条")
        return torrents
