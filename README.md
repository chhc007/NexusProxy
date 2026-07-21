# 本项目由AI辅助完成
# NexusProxy

**NexusProxy** 是一个专为 [MoviePilot](https://github.com/jxxghp/MoviePilot) (MP) 设计的通用搜索代理框架。它能够将 Jackett 的 Torznab API 响应，实时转换为 MoviePilot 完美兼容的 NexusPHP 模拟站点 HTML 格式。

通过创新的“主程序 + 插件化模块”架构，它不仅彻底解决了公共 BT 站点中文搜索 Fallback（返回无关最新列表）导致 MP 匹配失败的痛点，还提供了极高的扩展性，让你能轻松接入各种数据源。

## ✨ 核心特性

- 🎯 **完美兼容 MoviePilot**：严格遵循 NexusPHP HTML 结构，确保 MP 解析器 100% 成功抓取标题、大小、做种和种子下载直链。
- 🛡️ **智能 Fallback 拦截**：内置拦截算法，可自行开关。自动过滤 Jackett 在搜不到中文时返回的垃圾数据，彻底杜绝下错电影。对插件返回的内容也有效。
- 🧩 **插件化热插拔架构**：主程序与搜索模块完全解耦。通过映射 `modules` 目录，无需重新构建镜像即可热更新或添加新的搜索源（如 Prowlarr、自定义爬虫）。可在插件目录下配置插件的是否启用。
- ⚡ **高性能与高可用**：全局 HTTP 连接池复用、自定义分钟防抖内存缓存、失败自动重试机制，大幅提升搜索速度与稳定性。
- 📦 **开箱即用**：首次运行自动释放基础模块到本地映射目录，支持无缝热更新。

---

## 🚀 快速部署 (Docker)

推荐使用 Docker Compose 进行部署。

### 1. 准备目录结构
在你的 NAS 或服务器上创建一个目录（例如 `/opt/jackett-proxy`），并在其中创建 `docker-compose.yml`：

[配置示例](docker-compose.yml)


### 2. 启动服务
```bash
docker-compose up -d
```

*首次启动时，容器会自动将基础的 `jackett.py` 等模块释放到你本地的 `modules` 目录中。*

> ⚠️ **安全警告**：此代理站点目前**无认证限制**，请勿将其直接暴露到公网，建议仅在家庭内网或通过内网穿透（带鉴权）使用。

---

## ⚙️ MoviePilot 接入指南

部署完成后，你将得到一个代理站点地址，例如：`http://192.168.123.189:9118/`。请按照以下步骤将其接入 MoviePilot：

### 第一步：安装自定义索引插件
在 MoviePilot 的 **插件市场** 中，搜索并安装官方插件：**自定义索引站点**。

### 第二步：生成站点配置 Base64
1. 复制以下 JSON 配置，并将其中的 `"domain"` 替换为你的实际代理站点地址（**注意：必须以 `/` 结尾**）。`"id"`不可重复。`"name"`为站点名称(每站单独插件时你可以用插件名来区分)。 其他内容实际无关紧要，都可以在网页上设置。
```json
{
  "id": "nexusproxy1",
  "name": "NexusProxy",
  "domain": "http://192.168.123.189:9118/",
  "encoding": "UTF-8",
  "public": true,
  "proxy": false,
  "result_num": 500,
  "timeout": 120,
  "search": {
    "paths": [
      {
        "path": "torrents.php?search={keyword}"
      }
    ]
  },
  "torrents": {
    "list": {
      "selector": "table.torrents tr.torrent"
    },
    "fields": {
      "title": {
        "selector": "td:nth-child(2) a",
        "attribute": "title"
      },
      "details": {
        "selector": "td:nth-child(2) a",
        "attribute": "href"
      },
      "download": {
        "selector": "td:nth-child(3) a",
        "attribute": "href"
      },
      "size": {
        "selector": "td:nth-child(4)"
      },
      "seeders": {
        "selector": "td:nth-child(5)"
      },
      "leechers": {
        "selector": "td:nth-child(6)"
      },
      "completed": {
        "selector": "td:nth-child(7)"
      },
      "date": {
        "selector": "td:nth-child(8) span",
        "attribute": "title"
      },
      "downloadvolumefactor": {
        "case": {
          "img.pro_free": 0,
          "img.pro_free2up": 0,
          "img.pro_50pctdown": 0.5,
          "img.pro_50pctdown2up": 0.5,
          "img.pro_30pctdown": 0.3,
          "*": 1
        }
      },
      "uploadvolumefactor": {
        "case": {
          "img.pro_2up": 2,
          "img.pro_free2up": 2,
          "img.pro_50pctdown2up": 2,
          "*": 1
        }
      }
    }
  }
}

```

2. 将修改后的 JSON 转换为 Base64 编码（可使用在线工具如 [ToolHelper Base64](https://www.toolhelper.cn/EncodeDecode/Base64)）。
3. 在生成的 Base64 字符串**最前面**加上你的 `IP:端口|`。
   - 格式：`IP:端口|Base64字符串`
   - 示例：`192.168.123.189:9118|ewogICJpZCI6ICJqYWNrZXR0X3Byb3h5IiwKICAibmFtZSI6ICJKYWNrZXR0IFByb3h5IiwKICAiZG9tYWluIjogImh0dHA6Ly8xOTIuMTY4LjEyMy4xODk6OTExOC8iLAogICJlbmNvZGluZyI6ICJVVEYtOCIsCiAgInB1YmxpYyI6IHRydWUsCiAgInByb3h5IjogdHJ1ZSwKICAicmVzdWx0X251bSI6IDEwMCwKICAidGltZW91dCI6IDEyMCwKICAic2VhcmNoIjogewogICAgInBhdGhzIjogWwogICAgICB7CiAgICAgICAgInBhdGgiOiAidG9ycmVudHMucGhwP3NlYXJjaD17a2V5d29yZH0iCiAgICAgIH0KICAgIF0KICB9LAogICJ0b3JyZW50cyI6IHsKICAgICJsaXN0IjogewogICAgICAic2VsZWN0b3IiOiAidGFibGUudG9ycmVudHMgdHIudG9ycmVudCIKICAgIH0sCiAgICAiZmllbGRzIjogewogICAgICAidGl0bGUiOiB7CiAgICAgICAgInNlbGVjdG9yIjogInRkOm50aC1jaGlsZCgxKSBhIgogICAgICB9LAogICAgICAiZG93bmxvYWQiOiB7CiAgICAgICAgInNlbGVjdG9yIjogInRkOm50aC1jaGlsZCgyKSBhIiwKICAgICAgICAiYXR0cmlidXRlIjogImhyZWYiCiAgICAgIH0sCiAgICAgICJzZWVkZXJzIjogewogICAgICAgICJzZWxlY3RvciI6ICJ0ZDpudGgtY2hpbGQoMykiCiAgICAgIH0sCiAgICAgICJsZWVjaGVycyI6IHsKICAgICAgICAic2VsZWN0b3IiOiAidGQ6bnRoLWNoaWxkKDQpIgogICAgICB9LAogICAgICAic2l6ZSI6IHsKICAgICAgICAic2VsZWN0b3IiOiAidGQ6bnRoLWNoaWxkKDUpIgogICAgICB9LAogICAgICAiZGV0YWlscyI6IHsKICAgICAgICAic2VsZWN0b3IiOiAidGQ6bnRoLWNoaWxkKDEpIGEiLAogICAgICAgICJhdHRyaWJ1dGUiOiAiaHJlZiIKICAgICAgfQogICAgfQogIH0KfQ==`

4. 将这一长串字符粘贴到 **自定义索引站点** 插件的配置框中，保存并启动插件。

### 第三步：添加站点
1. 进入 MoviePilot 的 **站点管理**，点击添加站点。
2. **URL** 填写你的代理站点地址：`http://192.168.123.189:9118/`
3. **超时时间**：推荐设置为 **60-180秒**（请根据你 Jackett 和其他插件的实际返回速度按需调整）。
4. 保存并测试连通性。

🎉 **完成！** 现在你的 MoviePilot 已经可以通过此代理站点完美调用 Jackett 进行搜索和下载了。

**PS：** 如果你的搜索结果都是英文为主的，那就不用管，中文搜索失败后MP自然会切换英文搜。 如果你的的插件们有的中文有的英文，那就要去MP的设定-搜索 & 下载设置里 打开 **多名称资源搜索** 功能。要么你就多开几个容器，一个插件一个容器，搜索时自行选择不同站点区分。 

**多容器部署法：** 如果你希望每个nexusproxy使用不同的插件搜索，就新建多个容器，用不同的ip和端口，MP里把自定义索引插件分身几个出来，就可以添加了。

---

## 🛠️ 环境变量说明

自己看compose文件，写的很清楚了~

---

## 🧩 进阶：自定义搜索模块！！！！

本项目采用模块化设计，你可以非常方便地编写自己的 Python 搜索模块（例如接入 Prowlarr、TMDb 直接搜索、或特定的 PT 站点 API）。

1. 在本地映射的 `./modules` 目录下新建一个 Python 文件（如 `prowlarr.py`）。
2. 继承 `BaseSearchModule` 并实现 `search` 方法：
样例模块：[模块示例](modules/example_module.py)

**PS:** 我推荐你的模块写成多线程操作，增加速度，可以参考我写的lou.py模块。


3. 修改 `modules` 文件夹中的 enabled_plugins.txt 文件来设置启用的模块名称,不是模块文件名，是模块里面`name`定义的值如name = "example" 就是example，一行一个。还有，如果你的模块用了其他的python依赖，可以在`modules` 文件夹新增一个叫`requirements.模块名.txt`的文件,写入格式为`bencodepy==0.9.5` ，每行一条。这样每次重建会自动安装。

4. 重启容器：`docker-compose restart`。主程序会自动扫描并加载新模块！
---

## ❓ 常见问题 (FAQ)

**Q: 为什么日志显示搜到了数据，但 MoviePilot 里显示 0 个结果？**
> **A:** 基本上是因为**超时**导致的。Jackett 搜索多个 Indexer 时可能耗时较长，如果超过了你在 MP 站点设置中配置的超时时间（如 30s），MP 会直接断开连接。
> **解决办法**：在 MP 站点设置中调大超时时间（推荐 60s-120s），或在 Jackett 中禁用那些响应极慢的垃圾 Indexer。

**Q: 搜索速度很慢怎么办？**
> **A:** 代理本身只做轻量级的数据转换，**快速的关键在于你得有一个流畅使用的 Jackett 或别的搜索插件**。请优化你的 Jackett 配置，清理无效的 Indexer，并确保网络环境良好。更换更快速的代理或模块。

**Q: 为什么搜索中文没结果，但搜索英文有？**
> **A:** 这是正常的。Jackett 中的公共 BT 站点（如 1337x）不支持中文搜索。当搜索中文时，代理会智能拦截这些站点返回的“最新上传”垃圾数据（Fallback），迫使 MP 自动使用 TMDB 获取的英文原名（如 *星际穿越 Interstellar*）进行二次搜索，从而获取精准结果。

---

## ⚠️ 注意事项与免责声明

- 本项目仅用于技术交流与个人学习，请勿用于任何商业用途。
- 请遵守当地法律法规，不要下载和传播受版权保护的非法内容。
- 如果本项目解决了你的痛点，欢迎点个 **Star ⭐** 支持一下！
