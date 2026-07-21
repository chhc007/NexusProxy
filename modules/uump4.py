import os
import time
import logging
import tempfile
import httpx
import asyncio
import re
from bs4 import BeautifulSoup
import hashlib
import bencodepy
import urllib.parse
from datetime import datetime, timedelta
from .base import BaseSearchModule
from utils import format_size, extract_year

logger = logging.getLogger("NexusProxy.uump4")

class uump4Module(BaseSearchModule):
    name = "uump4"

    def __init__(self, http_client):
        super().__init__(http_client)
        self.url = os.getenv("UUMP4_URL", "https://www.uump4.cc").rstrip('/')
        
        # 限制并发数，防止被目标站点封禁
        self.semaphore = asyncio.Semaphore(int(os.getenv("UUMP4_CONCURRENCY", "5")))

        # 优先读取插件专用代理
        proxy = ""
        
        # 客户端配置：忽略 SSL 验证，伪造真实浏览器 Header
        client_kwargs = {
            "timeout": httpx.Timeout(60.0, connect=15.0),
            "follow_redirects": True,
            "verify": True,  # 关键：忽略 SSL 证书校验，防止握手失败导致 ConnectError
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
        }
        
        if proxy:
            client_kwargs["proxy"] = proxy
            logger.info(f"[uump4] 使用代理: {proxy}")
            
        # 强制创建独立的 AsyncClient，确保配置生效
        self.http_client = httpx.AsyncClient(**client_kwargs)

        logger.info(f"[uump4] 初始化完成 URL: {self.url}")

    def _encode_keyword(self, text):
        """对中文和特殊字符进行 URL 编码"""
        return "".join("_%02X" % b if b >= 128 else chr(b) for b in text.encode())

    def _parse_date(self, date_str):
        """解析相对时间（如3月前）和绝对时间（如2025-1-7）"""
        if not date_str:
            return ""
            
        date_str = date_str.strip()
        now = datetime.now()
        
        # 1. 处理相对时间 (如: 3月前, 2年前, 5天前, 10小时前, 30分钟前)
        rel_match = re.search(r'(\d+)\s*(年|月|周|天|小时|分钟|秒)前', date_str)
        if rel_match:
            num = int(rel_match.group(1))
            unit = rel_match.group(2)
            if unit == '年': delta = timedelta(days=num * 365)
            elif unit == '月': delta = timedelta(days=num * 30)
            elif unit == '周': delta = timedelta(weeks=num)
            elif unit == '天': delta = timedelta(days=num)
            elif unit == '小时': delta = timedelta(hours=num)
            elif unit == '分钟': delta = timedelta(minutes=num)
            elif unit == '秒': delta = timedelta(seconds=num)
            else: delta = timedelta()
            return (now - delta).strftime("%Y-%m-%d %H:%M:%S")
            
        if '刚刚' in date_str or '今天' in date_str:
            return now.strftime("%Y-%m-%d %H:%M:%S")
        if '昨天' in date_str:
            return (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        if '前天' in date_str:
            return (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")

        # 2. 处理绝对时间 (如: 2025-1-7, 2025/01/07, 2025年1月7日)
        clean_str = date_str.replace('年', '-').replace('月', '-').replace('日', '')
        abs_match = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', clean_str)
        if abs_match:
            y, m, d = int(abs_match.group(1)), int(abs_match.group(2)), int(abs_match.group(3))
            try:
                # 如果原字符串没有具体时间，就补充当前时间
                dt = datetime(y, m, d, now.hour, now.minute, now.second)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
                
        # 实在解析不出，返回空字符串（main.py 中有兜底默认时间 2000-01-01）
        return ""

    async def _request_with_retry(self, url, retries=2):
        """带重试机制的请求方法，应对网络抖动"""
        for i in range(retries + 1):
            try:
                r = await self.http_client.get(url)
                return r
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if i == retries:
                    raise  # 最后一次重试失败，抛出异常
                logger.warning(f"[uump4] 请求 {url} 失败 ({type(e).__name__})，1s 后重试 ({i+1}/{retries})...")
                await asyncio.sleep(1)

    async def search(self, keyword):
        start = time.time()
        try:
            url = f"{self.url}/search-{self._encode_keyword(keyword)}-1.htm"
            r = await self._request_with_retry(url)
            logger.info(f"[uump4] 页面长度: {len(r.text)}")
            if r.status_code != 200:
                logger.warning(f"[uump4] 搜索页请求失败，状态码: {r.status_code}")
                return []

            threads = self._parse_search(r.text)
            if not threads:
                logger.info("[uump4] 搜索页未找到相关帖子")
                return []
                
            logger.info(f"[uump4] 找到 {len(threads)} 个帖子，开始并发获取详情...")

            # 1. 并发获取所有帖子的详情页和种子列表
            detail_tasks = [self._fetch_thread_details(thread) for thread in threads]
            thread_details = await asyncio.gather(*detail_tasks, return_exceptions=True)

            # 2. 收集所有需要下载的种子任务
            magnet_tasks = []
            for detail in thread_details:
                if isinstance(detail, Exception):
                    continue
                for torrent in detail:
                    magnet_tasks.append(self._fetch_magnet(torrent))

            if not magnet_tasks:
                logger.info("[uump4] 帖子中未找到可下载的种子附件")
                return []
                
            logger.info(f"[uump4] 找到 {len(magnet_tasks)} 个种子，开始并发获取磁力...")

            # 3. 并发获取所有磁力链接
            magnet_results = await asyncio.gather(*magnet_tasks, return_exceptions=True)

            # 4. 整合并过滤失败的结果
            results = []
            for res in magnet_results:
                if isinstance(res, Exception):
                    continue
                if res is not None:
                    results.append(res)

            logger.info(f"[uump4] 完成 {len(results)} 条 耗时 {time.time()-start:.2f}s")
            return results

        except httpx.ConnectError:
            logger.error(f"[uump4] ❌ 网络连接被重置 (ConnectError)。")
            return []
        except httpx.TimeoutException:
            logger.error(f"[uump4] ❌ 请求超时 (Timeout)。")
            return []
        except Exception as e:
            logger.exception(f"[uump4] 搜索发生未预期异常: {e}")
            return []

    async def _fetch_thread_details(self, thread):
        """并发任务：获取单个帖子的详情页并解析种子列表"""
        async with self.semaphore:
            try:
                detail = await self._request_with_retry(thread["url"])
                if detail.status_code != 200:
                    return []
                torrents = self._parse_detail(detail.text)
                for t in torrents:
                    t["thread_title"] = thread["title"]
                    t["thread_date"] = thread.get("date", "")  # 【新增】将搜索页解析到的时间传递给种子
                return torrents
            except Exception as e:
                logger.warning(f"[uump4] 解析详情页失败 {thread['url']}: {e}")
                return []

    async def _fetch_magnet(self, torrent):
        async with self.semaphore:
            try:
                r = await self._request_with_retry(torrent["url"])
                if r.status_code != 200:
                    return None

                try:
                    meta = bencodepy.decode(r.content)
                except Exception:
                    logger.warning(f"[uump4] 下载内容不是torrent: {torrent['url']}")
                    return None

                info = meta[b"info"]
                info_hash = hashlib.sha1(bencodepy.encode(info)).hexdigest()
                name = info.get(b"name", b"unknown").decode("utf-8", errors="ignore")
                magnet = "magnet:?xt=urn:btih:" + info_hash + "&dn=" + urllib.parse.quote(name)

                # 解析torrent真实大小
                actual_size = 0
                try:
                    if b"length" in info:
                        actual_size = int(info[b"length"])
                    elif b"files" in info:
                        actual_size = sum(int(x.get(b"length", 0)) for x in info[b"files"])
                except Exception as e:
                    logger.warning(f"[uump4] torrent大小解析失败: {e}")

                # 如果torrent没有大小，尝试从标题获取
                if actual_size == 0:
                    m = re.search(r'(\d+(?:\.\d+)?)\s*(TB|GB|MB|KB)', torrent["thread_title"], re.I)
                    if m:
                        size = float(m.group(1))
                        unit = m.group(2).upper()
                        if unit == "TB": actual_size = int(size * 1024 ** 4)
                        elif unit == "GB": actual_size = int(size * 1024 ** 3)
                        elif unit == "MB": actual_size = int(size * 1024 ** 2)
                        elif unit == "KB": actual_size = int(size * 1024)

                return {
                    "source": self.name,
                    "title": name or torrent["thread_title"],
                    "download": magnet,
                    "torrent_id": info_hash,
                    "size": format_size(actual_size),
                    "filesize": actual_size,
                    "seeders": 0,        
                    "leechers": 0,       
                    "completed": 0,      
                    "date": torrent.get("thread_date", ""), # 【新增】使用解析到的帖子发布时间
                    "promotion": "free",  # 【核心修改】强制全免费
                    "year": extract_year(name) or extract_year(torrent["thread_title"]) or ""
                }

            except Exception as e:
                logger.warning(f"[uump4] 获取磁力失败 {torrent['url']}: {e}")
                return None

    def _parse_search(self, html):
        soup = BeautifulSoup(html, "html.parser")
        data = {}
        
        # 优先尝试解析包含时间的完整 li 结构
        for li in soup.select("li.media.thread"):
            a_tag = li.select_one("a[href^='thread-']")
            if not a_tag:
                continue
                
            href = a_tag.get("href")
            if not href:
                continue
                
            url = f"{self.url}/{href}"
            title = a_tag.get_text(" ", strip=True)
            
            # 提取时间
            date_span = li.select_one("span.date.text-grey")
            raw_date = date_span.get_text(strip=True) if date_span else ""
            parsed_date = self._parse_date(raw_date)
            
            if url not in data:
                data[url] = {
                    "title": title,
                    "url": url,
                    "date": parsed_date
                }
                
        # 兜底逻辑：如果上面的 li 选择器没匹配到（防备网页结构微调），使用原来的简单逻辑
        if not data:
            for a in soup.select("a[href^='thread-']"):
                href = a.get("href")
                if href:
                    url = f"{self.url}/{href}"
                    if url not in data:
                        data[url] = {
                            "title": a.get_text(" ", strip=True),
                            "url": url,
                            "date": "" # 兜底时没有具体时间
                        }
                        
        return list(data.values())

    def _parse_detail(self, html):
        soup = BeautifulSoup(html, "html.parser")
        result = []

        for a in soup.select(".attachlist a"):
            href = a.get("href")

            if href and href.endswith(".torrent"):
                result.append({
                    "name": a.get_text(" ", strip=True),
                    "url": href
                })

        return result

    async def debug(self, keyword):
        print("=" * 50)
        print("[uump4 Debug]", keyword)

        result = await self.search(keyword)

        print("结果数量:", len(result))

        for x in result[:10]:
            print("\n标题:", x["title"])
            print("大小:", x["size"])
            print("时间:", x["date"])
            print("MAGNET:", x["download"])

        return result
