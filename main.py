import os
import sys
import time
import asyncio
import logging
import importlib
import pkgutil
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import random

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import httpx
from urllib.parse import urlparse

# 尝试导入 utils，如果不存在则使用默认 fallback
try:
    import utils
    HAS_UTILS = True
except ImportError:
    HAS_UTILS = False

from modules.base import BaseSearchModule

# ================= 环境变量读取 =================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
ENABLE_FALLBACK = os.getenv("ENABLE_FALLBACK", "true").lower() in ("true", "1", "yes")
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() in ("true", "1", "yes")

PLUGIN_HTTP_PROXY = os.getenv("PLUGIN_HTTP_PROXY", os.getenv("HTTP_PROXY", ""))

# ================= 日志配置 =================
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("NexusProxy.main")

def print_env_vars():
    logger.info("========== 当前程序环境变量配置 ==========")
    used_env_vars = {
        "LOG_LEVEL": "INFO", "CACHE_TTL": "300", "ENABLE_FALLBACK": "true",
        "DEBUG_MODE": "false", "PLUGIN_HTTP_PROXY": "", "HTTP_PROXY": ""
    }
    sensitive_keys = ["SECRET", "KEY", "TOKEN", "PASSWORD", "PASS", "API", "COOKIE", "PROXY"]

    for k, default_v in used_env_vars.items():
        v = os.getenv(k)
        if v is None:
            display_v = f"<未设置, 使用默认值: {default_v}>" if default_v else "<未设置>"
        else:
            if any(s in k.upper() for s in sensitive_keys):
                if "PROXY" in k.upper() and "://" in v and "@" in v:
                    try:
                        parsed = urlparse(v)
                        if parsed.username or parsed.password:
                            masked_netloc = f"{parsed.username or ''}:********@{parsed.hostname}"
                            if parsed.port: masked_netloc += f":{parsed.port}"
                            v = parsed._replace(netloc=masked_netloc).geturl()
                        else:
                            v = f"{v[:4]}{'*' * 8}{v[-4:]}" if len(v) > 8 else "********"
                    except Exception:
                        v = f"{v[:4]}{'*' * 8}{v[-4:]}" if len(v) > 8 else "********"
                else:
                    v = f"{v[:2]}{'*' * 8}{v[-2:]}" if len(v) > 4 else "********"
            display_v = v
        logger.info(f"{k}: {display_v}")
    logger.info("==========================================")

# ================= 全局状态 =================
http_client = None
search_cache = {}
search_modules = {}

def clean_expired_cache():
    current_time = time.time()
    keys_to_delete = [k for k, (t, _) in search_cache.items() if current_time - t > CACHE_TTL]
    for k in keys_to_delete:
        del search_cache[k]

# ================= 模块加载 =================
def load_modules(client):
    global search_modules
    modules_dir = os.path.join(os.path.dirname(__file__), "modules")
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)

    try:
        import modules
    except ImportError:
        logger.error("未找到 modules 目录，请检查项目结构")
        return

    config_file = os.path.join(modules_dir, "enabled_plugins.txt")
    enabled_plugins = set()
    if os.path.exists(config_file):
        with open(config_file, "r", encoding="utf-8") as f:
            enabled_plugins = {x.strip().lower() for x in f if x.strip() and not x.startswith("#")}

    if not enabled_plugins:
        enabled_plugins = {"jackett", "mock"} # 默认开启mock

    logger.info(f"启用搜索模块配置: {enabled_plugins}")

    for _, module_name, _ in pkgutil.iter_modules(modules.__path__):
        if module_name == "base": continue
        try:
            mod = importlib.import_module(f"modules.{module_name}")
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if not isinstance(attr, type) or not issubclass(attr, BaseSearchModule) or attr is BaseSearchModule:
                    continue
                plugin_name = getattr(attr, "name", attr_name).lower()
                if plugin_name not in enabled_plugins: continue
                
                instance = attr(client)
                search_modules[plugin_name] = instance
                logger.info(f"✅ 加载搜索模块: {plugin_name}")
        except Exception as e:
            logger.exception(f"❌ 加载模块 {module_name} 失败: {e}")

    # 调试模式兜底 Mock 模块
    if DEBUG_MODE and not search_modules:
        logger.warning("⚠️ 调试模式下未找到任何可用插件，自动注入 Mock 模拟模块！")
        class MockSearchModule(BaseSearchModule):
            name = "mock"
            async def search(self, keyword):
                await asyncio.sleep(0.5)
                promotions = ["normal", "free", "2up", "free2up", "50pctdown", "50pctdown2up", "30pctdown"]
                results = []
                for i in range(5):
                    pub_time = datetime.now() - timedelta(days=random.randint(0, 15), hours=random.randint(0, 23))
                    results.append({
                        "torrent_id": f"999{i}",
                        "title": f"[Mock] {keyword} - 2023 1080p BluRay x264 DTS-HD - Group{i}",
                        "download": f"download.php?id=999{i}&passkey=mock_passkey",
                        "size": f"{round(random.uniform(5.0, 80.0), 2)} GB",
                        "seeders": random.randint(10, 500), "leechers": random.randint(0, 50),
                        "completed": random.randint(100, 5000),
                        "date": pub_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "promotion": random.choice(promotions)
                    })
                # 添加磁力测试
                results.append({
                    "torrent_id": "magnet_001", "title": f"[Mock Magnet] {keyword} - 2160p WEB-DL",
                    "download": "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a",
                    "size": "45.2 GB", "seeders": 50, "leechers": 5, "completed": 120,
                    "date": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    "promotion": "free"
                })
                return results
        search_modules["mock"] = MockSearchModule(client)

    if not search_modules:
        logger.error("⚠️ 没有加载任何搜索模块，搜索功能将不可用！")
    else:
        logger.info(f"🚀 当前已就绪搜索模块: {list(search_modules.keys())}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    print_env_vars()
    logger.info("正在初始化全局 HTTP 连接池...")
    http_client = httpx.AsyncClient(
        timeout=30.0, 
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        trust_env=False 
    )
    load_modules(http_client)
    logger.info("NexusProxy 启动完成，准备接收请求！")
    yield
    logger.info("正在关闭 HTTP 连接池...")
    await http_client.aclose()

app = FastAPI(lifespan=lifespan)

# ================= 核心搜索与策略 =================
async def execute_search(keyword: str):
    req_start = time.time()
    cache_key = keyword.strip().lower()

    clean_expired_cache()
    if cache_key in search_cache:
        cached_time, cached_result = search_cache[cache_key]
        if time.time() - cached_time < CACHE_TTL:
            logger.info(f"命中缓存: {keyword}")
            return cached_result

    if not search_modules: return []
    logger.info(f"🔍 开始搜索: {keyword}, 模块={list(search_modules.keys())}")

    async def safe_search(module, kw, name):
        try:
            if asyncio.iscoroutinefunction(module.search):
                res = await module.search(kw)
            else:
                res = await asyncio.to_thread(module.search, kw)
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.error(f"模块 {name} 搜索时发生严重错误: {e}", exc_info=True)
            return []

    tasks = [safe_search(module, keyword, name) for name, module in search_modules.items()]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for name, result in zip(search_modules.keys(), responses):
        if isinstance(result, Exception): continue
        if not isinstance(result, list): result = []
        if not result: continue

        if ENABLE_FALLBACK and HAS_UTILS and hasattr(utils, 'is_fallback'):
            try:
                if utils.is_fallback(keyword, result):
                    logger.warning(f"⚠️ 模块 {name} 触发 Fallback 策略，丢弃低质量结果")
                    continue
            except Exception as e:
                logger.error(f"模块 {name} 执行 Fallback 过滤异常: {e}")

        results.extend(result)

    results.sort(key=lambda x: x.get("seeders", 0), reverse=True)
    search_cache[cache_key] = (time.time(), results)
    logger.info(f"✅ 搜索完成 {keyword}: 最终整合 {len(results)} 条, 耗时 {time.time()-req_start:.2f}s")
    return results

# ================= HTML 渲染 (严格兼容 MP/Nastool 解析) =================
def render_html(items):
    render_start = time.time()
    rows = ""
    for t in items:
        # 1. 链接处理
        download_url = t.get("download") or f"download.php?id={t['torrent_id']}"
        details_url = f"details.php?id={t['torrent_id']}"
        
        # 2. 促销标签处理 (MP 强依赖 class 前缀 pro_)
        promotion = t.get("promotion", "normal").lower()
        promo_html = ""
        if promotion == "free":
            promo_html = '<img class="pro_free" src="pic/trans.gif" alt="Free" title="免费">'
        elif promotion == "2up":
            promo_html = '<img class="pro_2up" src="pic/trans.gif" alt="2X" title="2X上传">'
        elif promotion == "free2up":
            promo_html = '<img class="pro_free2up" src="pic/trans.gif" alt="Free2X" title="免费&2X上传">'
        elif promotion == "50pctdown":
            promo_html = '<img class="pro_50pctdown" src="pic/trans.gif" alt="50%" title="50%下载">'
        elif promotion == "50pctdown2up":
            promo_html = '<img class="pro_50pctdown2up" src="pic/trans.gif" alt="50%2X" title="50%下载&2X上传">'
        elif promotion == "30pctdown":
            promo_html = '<img class="pro_30pctdown" src="pic/trans.gif" alt="30%" title="30%下载">'

        # 3. 时间与大小
        pub_date = t.get("date", "2000-01-01 00:00:00")
        size_str = str(t.get("size", "Unknown"))
        
        rows += f"""
        <tr class="torrent">
            <td class="rowfollow" align="center"><img src="pic/cat_movie.gif" alt="Movie"></td>
            <td class="rowfollow" align="left">
                <a href="{details_url}" title="{t['title']}"><b>{t['title']}</b></a>
                <br>{promo_html}
            </td>
            <td class="rowfollow" align="center"><a href="{download_url}">下载</a></td>
            <td class="rowfollow" align="center">{size_str}</td>
            <td class="rowfollow" align="center">{t.get('seeders', 0)}</td>
            <td class="rowfollow" align="center">{t.get('leechers', 0)}</td>
            <td class="rowfollow" align="center">{t.get('completed', 0)}</td>
            <td class="rowfollow" align="center"><span title="{pub_date}">{pub_date}</span></td>
        </tr>"""
        
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Torrents</title></head>
<body>
<div class="user-info-side">
    <a href="/userdetails.php?id=1">NexusUser</a> | <a href="/logout.php">退出</a>
</div>
<table class="torrents" cellspacing="0" cellpadding="5" width="100%">
    <thead>
        <tr>
            <td class="colhead">类型</td>
            <td class="colhead">名称</td>
            <td class="colhead">下载</td>
            <td class="colhead">大小</td>
            <td class="colhead">做种</td>
            <td class="colhead">下载</td>
            <td class="colhead">完成</td>
            <td class="colhead">发布时间</td>
        </tr>
    </thead>
    <tbody>{rows}</tbody>
</table>
</body>
</html>"""
    logger.debug(f"HTML 渲染完成: {len(items)} 条数据, 耗时 {(time.time()-render_start)*1000:.1f}ms")
    return html

# ================= 路由与中间件 =================
@app.middleware("http")
async def log_request(request: Request, call_next):
    start_time = time.time()
    logger.info(f"➡️ 收到请求: {request.method} {request.url}")
    response = await call_next(request)
    elapsed = (time.time() - start_time) * 1000
    logger.info(f"⬅️ 响应完成: {request.method} {request.url.path} | 状态码: {response.status_code} | 耗时: {elapsed:.1f}ms")
    return response

@app.get("/", response_class=HTMLResponse)
async def index():
    return "<html><body><h1>NexusPHP Proxy Framework</h1><p>Service is running.</p></body></html>"

@app.get("/torrents.php", response_class=HTMLResponse)
async def torrents(search: str = ""):
    if not search: return render_html([])
    result = await execute_search(search)
    return render_html(result)

@app.get("/details.php", response_class=HTMLResponse)
async def details(id: str = ""):
    return f"<html><body><h1>Details for {id}</h1></body></html>"

# ================= 启动入口 =================
if __name__ == "__main__":
    import uvicorn
    DEBUG_MODE=True
    reload_flag = DEBUG_MODE
    log_level_uvicorn = "debug" if DEBUG_MODE else "info"
    logger.info(f"启动 Uvicorn 服务 | 调试模式: {DEBUG_MODE} | 热重载: {reload_flag}")
    uvicorn.run("main:app", host="0.0.0.0", port=9118, reload=reload_flag, log_level=log_level_uvicorn)
