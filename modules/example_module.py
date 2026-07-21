import logging
from .base import BaseSearchModule

logger = logging.getLogger("NexusProxy.example")

class ExampleModule(BaseSearchModule):
    # 插件名称，必须在 modules/enabled_plugins.txt 中配置才能加载
    name = "example"

    def __init__(self, http_client):
        super().__init__(http_client)
        logger.info("[Example] 示例/测试插件初始化完成")

    async def search(self, keyword):
        """
        核心搜索方法。
        :param keyword: 搜索关键词
        :return: 包含搜索结果字典的列表。无论是否有结果，都必须返回列表（空列表为 []）。
        """
        logger.info(f"[Example] 收到搜索请求: {keyword}，返回固定模板数据")

        # 直接返回固定的模板数据，涵盖普通种子、免费种子、2X上传种子和磁力链接
        results = [
            {
                # ================= 必填核心字段 =================
                "title": f"[Example] {keyword} 2023 1080p BluRay x264 DTS-HD", # 完整标题
                "download": "download.php?id=1001&passkey=mock_passkey",        # .torrent 下载链接（相对或绝对路径均可）
                "torrent_id": "1001",                                           # 种子唯一 ID，用于生成详情页链接
                "year": "2023",                                                  # 提取出的年份，辅助 MP 过滤
                # ================= 可选辅助字段 =================
                "size": "15.50 GB",                                             # 人类可读的文件大小
                "filesize": 16642998272,                                        # 纯数字的文件大小（字节），MP 用于排序和过滤
                "seeders": 150,                                                 # 做种人数
                "leechers": 10,                                                 # 下载人数
                "completed": 520,                                               # 完成/抓取人数（MP 判断种子健康度需要）
                "date": "2023-10-25 14:30:00",                                  # 发布时间，必须严格使用 YYYY-MM-DD HH:MM:SS 格式
                "promotion": "normal"                                          # 促销状态：normal(普通), free(免费), 2up(2倍上传), free2up, 50pctdown, 30pctdown
                
            },
            {
                "title": f"[Example Free] {keyword} 2024 2160p WEB-DL",
                "download": "download.php?id=1002&passkey=mock_passkey",
                "torrent_id": "1002",
                "size": "45.20 GB",
                "filesize": 48532101120,
                "seeders": 300,
                "leechers": 50,
                "completed": 1200,
                "date": "2024-01-15 09:00:00",
                "promotion": "free",      # 标记为免费，MP 会将其下载体积系数设为 0
                "year": "2024"
            },
            {
                "title": f"[Example 2X] {keyword} 2022 Remastered 1080p",
                "download": "download.php?id=1003&passkey=mock_passkey",
                "torrent_id": "1003",
                "size": "8.00 GB",
                "filesize": 8589934592,
                "seeders": 20,
                "leechers": 2,
                "completed": 50,
                "date": "2022-05-10 18:20:00",
                "promotion": "2up",       # 标记为 2倍上传，MP 会将其上传体积系数设为 2
                "year": "2022"
            },
            {
                # ================= 磁力链接示例 =================
                "title": f"[Example Magnet] {keyword} 720p HDTV",
                "download": "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a&dn=Test", # 磁力链接直接填 magnet:?xt=...
                "torrent_id": "c12fe1c06bba254a9dc9f519b335aa7c1367a88a",      # 磁力链接通常用 info_hash 作为 ID
                "size": "2.50 GB",
                "filesize": 2684354560,
                "seeders": 0,
                "leechers": 0,
                "completed": 0,
                "date": "2024-02-01 12:00:00",
                "promotion": "normal",
                "year": ""
            }
        ]

        return results
