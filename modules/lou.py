import os
import time
import logging
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

logger = logging.getLogger("NexusProxy.lou")

class LouModule(BaseSearchModule):
    name = "lou"

    def __init__(self, http_client):
        super().__init__(http_client)
        self.url = os.getenv("LOU_URL", "https://www.1lou.me").rstrip('/')
        
        # 限制并发数，防止被目标站点封禁
        self.semaphore = asyncio.Semaphore(int(os.getenv("LOU_CONCURRENCY", "5")))
        self.max_page = int(os.getenv("LOU_MAX_PAGE", "3")) # 最大翻页数，默认3页
        
        # 优先读取插件专用代理
        proxy = os.getenv("PLUGIN_HTTP_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
        
        # 客户端配置：忽略 SSL 验证，伪造真实浏览器 Header
        client_kwargs = {
            "timeout": httpx.Timeout(60.0, connect=15.0),
            "follow_redirects": True,
            "verify": False,  # 忽略 SSL 证书校验
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
            logger.info(f"[Lou] 使用代理: {proxy}")
        else:
            logger.warning("[Lou] ⚠️ 未配置代理 (PLUGIN_HTTP_PROXY)，直连 1lou 极大概率失败 (ConnectError)！")
            
        self.http_client = httpx.AsyncClient(**client_kwargs)
        logger.info(f"[Lou] 初始化完成 URL: {self.url} | 最大翻页: {self.max_page}")

    def _encode_keyword(self, text):
        """对中文和特殊字符进行 URL 编码"""
        return "".join("_%02X" % b if b >= 128 else chr(b) for b in text.encode())

    def _parse_date(self, date_str):
        """解析相对时间（如3月前）和绝对时间（如2023-12-09 20:21）"""
        if not date_str: return ""
        date_str = date_str.strip()
        now = datetime.now()
        
        # 1. 处理相对时间
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
            
        if '刚刚' in date_str or '今天' in date_str: return now.strftime("%Y-%m-%d %H:%M:%S")
        if '昨天' in date_str: return (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        # 2. 处理绝对时间 (如: 2023-12-09 20:21)
        abs_match = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?:\s+(\d{1,2}):(\d{1,2}))?', date_str)
        if abs_match:
            y, m, d = int(abs_match.group(1)), int(abs_match.group(2)), int(abs_match.group(3))
            hour = int(abs_match.group(4)) if abs_match.group(4) else now.hour
            minute = int(abs_match.group(5)) if abs_match.group(5) else now.minute
            try:
                return datetime(y, m, d, hour, minute, 0).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        return ""

    def _extract_size_from_text(self, text):
        """从文本中提取文件大小并转换为字节"""
        if not text: return 0
        m = re.search(r'(\d+(?:\.\d+)?)\s*(TB|GB|MB|KB)', text, re.I)
        if m:
            size = float(m.group(1))
            unit = m.group(2).upper()
            if unit == "TB": return int(size * 1024 ** 4)
            if unit == "GB": return int(size * 1024 ** 3)
            if unit == "MB": return int(size * 1024 ** 2)
            if unit == "KB": return int(size * 1024)
        return 0

    async def _request_with_retry(self, url, retries=2):
        """带重试机制的请求方法"""
        for i in range(retries + 1):
            try:
                return await self.http_client.get(url)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if i == retries: raise
                logger.warning(f"[Lou] 请求 {url} 失败 ({type(e).__name__})，1s 后重试 ({i+1}/{retries})...")
                await asyncio.sleep(1)

    async def search(self, keyword):
        start = time.time()
        try:
            base_keyword = self._encode_keyword(keyword)
            threads = []

            # 翻页获取搜索结果
            for page in range(1, self.max_page + 1):
                if page == 1:
                    url = f"{self.url}/search-{base_keyword}-1.htm"
                else:
                    url = f"{self.url}/search-{base_keyword}-1-{page}.htm"

                logger.info(f"[Lou] 正在请求第 {page} 页: {url}")
                r = await self._request_with_retry(url)

                if r.status_code != 200:
                    logger.warning(f"[Lou] 第 {page} 页请求失败，状态码: {r.status_code}，停止翻页")
                    break

                page_threads = self._parse_search(r.text)

                if not page_threads:
                    logger.info(f"[Lou] 第 {page} 页无结果，停止翻页")
                    break

                logger.info(f"[Lou] 第 {page} 页找到 {len(page_threads)} 个帖子")
                threads.extend(page_threads)

            # 去重
            unique_threads = {thread["url"]: thread for thread in threads}
            threads = list(unique_threads.values())

            if not threads:
                logger.info("[Lou] 搜索页未找到相关帖子")
                return []

            logger.info(f"[Lou] 共找到 {len(threads)} 个帖子，开始并发获取详情...")

            # 1. 并发获取详情页
            detail_tasks = [self._fetch_thread_details(thread) for thread in threads]
            thread_details = await asyncio.gather(*detail_tasks, return_exceptions=True)

            # 2. 收集种子任务
            magnet_tasks = []
            for detail in thread_details:
                if isinstance(detail, Exception): continue
                for torrent in detail:
                    magnet_tasks.append(self._fetch_magnet(torrent))

            if not magnet_tasks:
                logger.info("[Lou] 帖子中未找到可下载的种子附件")
                return []

            logger.info(f"[Lou] 找到 {len(magnet_tasks)} 个种子，开始并发获取磁力...")

            # 3. 获取磁力
            magnet_results = await asyncio.gather(*magnet_tasks, return_exceptions=True)

            # 4. 整理结果
            results = [res for res in magnet_results if not isinstance(res, Exception) and res is not None]

            logger.info(f"[Lou] 完成 {len(results)} 条 耗时 {time.time()-start:.2f}s")
            return results

        except httpx.ConnectError:
            logger.error("[Lou] ❌ 网络连接失败，请检查代理和网络")
            return []
        except httpx.TimeoutException:
            logger.error("[Lou] ❌ 请求超时")
            return []
        except Exception as e:
            logger.exception(f"[Lou] 搜索发生异常: {e}")
            return []

    async def _fetch_thread_details(self, thread):
        """获取详情页并解析种子列表"""
        async with self.semaphore:
            try:
                detail = await self._request_with_retry(thread["url"])
                if detail.status_code != 200: return []
                torrents = self._parse_detail(detail.text)
                for t in torrents:
                    t["thread_title"] = thread["title"]
                    t["thread_date"] = thread.get("date", "") # 传递时间
                return torrents
            except Exception as e:
                logger.warning(f"[Lou] 解析详情页失败 {thread['url']}: {e}")
                return []

    async def _fetch_magnet(self, torrent):
        """下载 torrent 并解析磁力与大小"""
        async with self.semaphore:
            try:
                r = await self._request_with_retry(torrent["url"])
                if r.status_code != 200: return None

                if not r.content.startswith(b"d"):
                    logger.warning(f"[Lou] 下载内容不是torrent: {torrent['url']}")
                    return None

                # 内存直读解析
                meta = bencodepy.decode(r.content)
                info = meta[b"info"]
                info_hash = hashlib.sha1(bencodepy.encode(info)).hexdigest()
                name = info.get(b"name", b"unknown").decode("utf-8", errors="ignore")
                magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(name)}"

                # 多级大小解析策略
                actual_size = self._extract_size_from_text(torrent.get("thread_title", ""))
                if actual_size == 0:
                    actual_size = self._extract_size_from_text(torrent.get("name", ""))
                if actual_size == 0:
                    try:
                        if b"length" in info: actual_size = int(info[b"length"])
                        elif b"files" in info: actual_size = sum(int(x.get(b"length", 0)) for x in info[b"files"])
                    except Exception: pass

                return {
                    "source": self.name,
                    "title": name if name != "unknown" else torrent["thread_title"],
                    "download": magnet,
                    "torrent_id": info_hash,
                    "size": format_size(actual_size),
                    "filesize": actual_size,
                    "seeders": 0,
                    "leechers": 0,
                    "completed": 0,
                    "date": torrent.get("thread_date", ""),
                    "promotion": "free",
                    "year": extract_year(name) or extract_year(torrent["thread_title"]) or ""
                }
            except Exception as e:
                logger.warning(f"[Lou] 获取磁力失败 {torrent['url']}: {e}")
                return None

    def _parse_search(self, html):
        """解析搜索页，提取帖子链接与时间"""
        soup = BeautifulSoup(html, "html.parser")
        data = {}
        
        for a in soup.select("a[href*='thread-']"):
            href = a.get("href")
            if not href or "thread-create" in href: continue
            
            m = re.search(r'(thread-\d+\.htm)', href)
            if not m: continue
            
            url = f"{self.url}/{m.group(1)}"
            if url in data: continue
            
            title = a.get_text(" ", strip=True)
            if not title: continue
            
            # 向上追溯 DOM 查找时间
            date_str = ""
            parent = a.parent
            for _ in range(6):
                if parent is None: break
                date_span = parent.select_one("span.date.text-grey")
                if date_span:
                    date_str = date_span.get_text(strip=True)
                    break
                parent = parent.parent
                
            data[url] = {
                "title": title,
                "url": url,
                "date": self._parse_date(date_str)
            }
            
        return list(data.values())

    def _parse_detail(self, html):
        """解析详情页附件"""
        soup = BeautifulSoup(html, "html.parser")
        result = []
        for a in soup.select(".attachlist a"):
            href = a.get("href")
            if href and (href.endswith(".torrent") or "attach-download" in href):
                if not href.startswith("http"):
                    href = f"{self.url}/{href}"
                
                # 提取纯文本，排除 <i> 图标标签干扰
                name = "".join(child for child in a.children if isinstance(child, str)).strip()
                if not name: name = a.get_text(strip=True)
                    
                result.append({"name": name, "url": href})
        return result

    async def debug(self, keyword):
        print("=" * 50)
        print("[Lou Debug]", keyword)
        result = await self.search(keyword)
        print("结果数量:", len(result))
        for x in result[:10]:
            print(f"\n标题: {x['title']}\n大小: {x['size']}\n时间: {x['date']}\nMAGNET: {x['download']}")
        return result
