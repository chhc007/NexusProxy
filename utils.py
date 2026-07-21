import re
import difflib
import logging

logger = logging.getLogger("NexusProxy.utils")

def format_size(size):
    if not size: return "0 B"
    try: size = float(size)
    except: return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {units[i]}"

def extract_year(title):
    m = re.search(r"(19\d{2}|20\d{2})", title)
    return m.group(1) if m else None

def is_bad_title(title):
    bad = ["xfans", "porn", "xxx", "bellesa", "horny", "sex", "erotic", "hentai"]
    t = title.lower()
    return any(b in t for b in bad)

def calculate_similarity(s1, s2):
    return difflib.SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


logger = logging.getLogger("NexusProxy.utils")

# 常见的无意义后缀/停用词，在匹配时应当忽略，防止干扰
STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'in', 'to', 'for', 'with', 'on', 'at', 'by',
    '1080p', '720p', '2160p', '4k', '8k', 'bluray', 'blu-ray', 'web-dl', 'webdl', 
    'x264', 'x265', 'h264', 'h265', 'hevc', 'aac', 'flac', 'mkv', 'mp4', 'avi',
    'chs', 'cht', 'eng', 'dual', 'multi', 'sub', 'subs', 'hd', 'fhd', 'uhd', 'remux'
}

def extract_core_keywords(keyword: str) -> list:
    """提取核心关键词，过滤停用词，并按长度降序排列（长词优先，权重更高）"""
    # 将常见的分隔符替换为空格
    clean_kw = re.sub(r'[\.\-_\/\+\[\]\(\)]+', ' ', keyword)
    # 提取所有字母数字和中文
    tokens = re.findall(r'[a-zA-Z0-9]+|[\u4e00-\u9fa5]+', clean_kw)
    
    core_words = []
    for t in tokens:
        t_lower = t.lower()
        if t_lower in STOP_WORDS:
            continue
        # 过滤掉单字母或单数字（中文单字保留）
        if len(t_lower) < 2 and not re.search(r'[\u4e00-\u9fa5]', t_lower):
            continue 
        core_words.append(t_lower)
        
    # 去重并按长度降序排列（越长的词区分度越高，越应该优先匹配）
    core_words = sorted(list(set(core_words)), key=len, reverse=True)
    return core_words

def check_title_match(title: str, core_keywords: list) -> bool:
    """检查单个标题是否与核心关键词匹配（基于权重占比）"""
    if not title or not core_keywords:
        return False
        
    title_lower = title.lower()
    
    matched_weight = 0
    total_weight = 0
    
    for kw in core_keywords:
        weight = len(kw)  # 词越长，权重越大
        total_weight += weight
        
        # 1. 直接包含（最靠谱）
        if kw in title_lower:
            matched_weight += weight
            continue
            
        # 2. 中文连续词块匹配（针对中文搜索词）
        if re.search(r'[\u4e00-\u9fa5]', kw) and len(kw) >= 2:
            # 提取所有连续的中文字符块（长度>=2）
            zh_blocks = re.findall(r'[\u4e00-\u9fa5]{2,}', kw)
            if zh_blocks:
                zh_matched = False
                for block in zh_blocks:
                    # 只要有一个长度>=2的中文块在标题里，就算这个中文词匹配了
                    if block in title_lower:
                        zh_matched = True
                        break
                if zh_matched:
                    matched_weight += weight
                    continue
                    
    # 如果匹配的权重占总权重的 50% 以上，认为该标题匹配
    # 例如搜 "流浪地球 2019"，核心词是 ["流浪地球", "2019"]
    # 如果标题只有 "流浪地球"，匹配了权重4，总权重8，占比50%，算匹配。
    if total_weight > 0 and (matched_weight / total_weight) >= 0.5:
        return True
        
    return False

def is_fallback(keyword: str, items: list, sample_size: int = 15, threshold: float = 0.3) -> bool:
    """
    智能 Fallback 拦截：防止站点搜索失效时返回无关的最新列表。
    采用“抽样投票制”，而非“一票放行制”。
    
    :param keyword: 搜索关键词
    :param items: 搜索结果列表
    :param sample_size: 抽样检查的数量（默认前15条）
    :param threshold: 匹配率阈值，低于此值则触发拦截（默认 0.3，即30%）
    :return: True 表示触发拦截（丢弃结果），False 表示放行
    """
    if not keyword or not items:
        logger.debug("[Fallback] 关键词为空或列表为空，跳过拦截")
        return False
        
    core_keywords = extract_core_keywords(keyword)
    if not core_keywords:
        logger.debug(f"[Fallback] 未提取到有效核心关键词 (原词: {keyword})，跳过拦截")
        return False
        
    logger.debug(f"[Fallback] 提取到的核心关键词(按权重): {core_keywords}")
    
    # 抽样检查（最多检查 sample_size 条，如果结果不足则检查全部）
    check_items = items[:sample_size]
    match_count = 0
    valid_sample_count = 0
    
    for idx, item in enumerate(check_items):
        title = (item.get("title") or "").strip()
        if not title:
            continue
            
        valid_sample_count += 1
        if check_title_match(title, core_keywords):
            match_count += 1
            logger.debug(f"[Fallback] ✅ 第 {idx+1} 条匹配: {title}")
        else:
            logger.debug(f"[Fallback] ❌ 第 {idx+1} 条未匹配: {title}")
            
    if valid_sample_count == 0:
        return False
        
    # 计算匹配率
    match_rate = match_count / valid_sample_count
    logger.info(f"[Fallback] 抽样 {valid_sample_count} 条，匹配 {match_count} 条，匹配率: {match_rate:.2%} (阈值: {threshold:.0%})")
    
    if match_rate < threshold:
        logger.warning(f"[Fallback] 🚨 匹配率过低，判定为无效搜索（可能返回了最新列表），触发拦截！")
        return True
        
    return False
