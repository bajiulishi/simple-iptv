import json
import requests
import time
import re
from collections import defaultdict


def fetch_raw_m3u(url):
    """从指定URL获取M3U内容"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"⚠️ 获取源数据失败: {url} - {str(e)}")
        return ""


def parse_m3u(m3u_text):
    """解析M3U文本，返回频道元数据和URL的列表"""
    parsed_channels = []
    lines = m3u_text.strip().splitlines()

    # 检查是否是有效的M3U文件
    if not lines or not lines[0].startswith("#EXTM3U"):
        print("❌ 无效的M3U文件格式")
        return parsed_channels

    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            # 保存原始元数据行
            metadata = lines[i]
            url = ""

            # 下一个应该是URL
            if i + 1 < len(lines) and not lines[i + 1].startswith("#"):
                url = lines[i + 1].strip()
                parsed_channels.append({
                    "metadata": metadata,
                    "url": url
                })
                i += 1  # 跳过URL行
        i += 1

    return parsed_channels


def load_json_data(filename):
    """从JSON文件加载数据"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ 加载JSON文件失败 {filename}: {str(e)}")
        return None


def load_channels():
    """加载频道列表并保留原始顺序，同时检测重复频道"""
    channels_data = load_json_data('channels.json')
    if not channels_data:
        print("❌ 没有找到有效的频道列表或格式错误")
        return None, None, None

    # 支持新格式（分组结构）
    if 'channel_groups' in channels_data:
        channel_list = []
        channel_to_group = {}  # 频道到分组的映射
        duplicate_channels = defaultdict(list)  # 记录重复频道及其所在分组

        for group in channels_data['channel_groups']:
            group_title = group['group_title']
            for channel in group['channels']:
                channel_list.append(channel)
                # 检查是否已经存在该频道
                if channel in channel_to_group:
                    duplicate_channels[channel].append(group_title)
                channel_to_group[channel] = group_title

        # 打印重复频道报告
        if duplicate_channels:
            print("\n⚠️ 发现重复频道:")
            for channel, groups in duplicate_channels.items():
                original_group = channel_to_group[channel]
                all_groups = [original_group] + groups
                print(f"  频道 '{channel}' 出现在多个分组: {', '.join(all_groups)}")
        else:
            print("\n✅ 没有发现重复频道")

        print(f"需要查找的频道 ({len(channel_list)})")
        return channel_list, channel_to_group, duplicate_channels

    print("❌ 频道列表格式错误")
    return None, None, None


def load_sources():
    """加载源列表"""
    sources_data = load_json_data('sources.json')
    if not sources_data or 'sources' not in sources_data:
        print("❌ 没有找到有效的源列表或格式错误")
        return None

    sources = sources_data['sources']
    if not sources:
        print("❌ 源列表为空")
        return None

    print(f"\n可用的源 ({len(sources)})")
    return sources


def is_channel_match(channel_name, metadata):
    """
    精确匹配频道名称（忽略大小写）
    匹配规则（按优先级排序）：
    1. 检查tvg-id属性是否匹配频道名称
    2. 检查tvg-name属性是否匹配频道名称
    3. 检查频道名称是否在元数据末尾（逗号后的部分）
    4. 避免部分匹配（如"CCTV1"不应匹配"CCTV10"）
    """
    # 1. 匹配tvg-id属性（最高优先级）
    tvg_id_match = re.search(r'tvg-id="([^"]*)"', metadata, re.IGNORECASE)
    if tvg_id_match:
        tvg_id = tvg_id_match.group(1)
        # 精确匹配tvg-id（使用正则忽略大小写）
        if re.fullmatch(re.escape(channel_name), tvg_id, re.IGNORECASE):
            return True
        # 检查tvg-id是否包含频道名称（但避免部分匹配）
        if re.search(rf'\b{re.escape(channel_name)}\b', tvg_id, re.IGNORECASE):
            return True

    # 2. 匹配tvg-name属性
    tvg_name_match = re.search(r'tvg-name="([^"]*)"', metadata, re.IGNORECASE)
    if tvg_name_match:
        tvg_name = tvg_name_match.group(1)
        # 精确匹配tvg-name（使用正则忽略大小写）
        if re.fullmatch(re.escape(channel_name), tvg_name, re.IGNORECASE):
            return True
        # 检查tvg-name是否包含频道名称（但避免部分匹配）
        if re.search(rf'\b{re.escape(channel_name)}\b', tvg_name, re.IGNORECASE):
            return True

    # 3. 匹配元数据末尾的频道名称（逗号后的部分）
    if ',' in metadata:
        display_name = metadata.split(',')[-1].strip()
        # 精确匹配显示名称（使用正则忽略大小写）
        if re.fullmatch(re.escape(channel_name), display_name, re.IGNORECASE):
            return True
        # 检查显示名称是否包含频道名称
        if re.search(rf'\b{re.escape(channel_name)}\b', display_name, re.IGNORECASE):
            return True

    # 4. 在整个元数据中搜索（作为最后的手段）
    if re.search(rf'\b{re.escape(channel_name)}\b', metadata, re.IGNORECASE):
        return True

    return False


def find_channels(sources, channel_list):
    """在源列表中查找频道，返回查找结果"""
    found_channel_urls = defaultdict(list)  # 频道名称到URL列表的映射
    channel_metadata_map = {}  # 频道名称到元数据的映射
    found_channels = set()  # 已找到的频道

    print("\n🔍 开始查找频道...")

    for source in sources:
        print(f"\n📡 正在搜索源: {source}")
        m3u_text = fetch_raw_m3u(source)
        if not m3u_text:
            continue

        # 解析当前源的M3U内容
        source_channels = parse_m3u(m3u_text)

        # 当前源中找到的新频道
        found_in_source = []

        # 查找当前源中是否有需要的频道
        for channel_name in channel_list:
            # 在当前源的所有频道中查找匹配项
            for entry in source_channels:
                # 检查元数据是否包含频道名称
                if is_channel_match(channel_name, entry["metadata"]):
                    # 添加到找到的频道URL列表
                    found_channel_urls[channel_name].append(entry["url"])

                    # 保存元数据（如果还没有保存过）
                    if channel_name not in channel_metadata_map:
                        channel_metadata_map[channel_name] = entry["metadata"]

                    # 标记为已找到
                    if channel_name not in found_channels:
                        found_channels.add(channel_name)
                        found_in_source.append(channel_name)
                    break

        # 输出当前源中找到的频道
        if found_in_source:
            channels_str = ", ".join(found_in_source)
            print(f"✅ 找到频道: {channels_str}")
        else:
            print("⚠️ 在此源中未找到新频道")

        # 避免请求过快
        time.sleep(1)

    # 计算缺失频道
    missing_channel_list = [ch for ch in channel_list if ch not in found_channels]

    return found_channel_urls, channel_metadata_map, missing_channel_list


def extract_tvg_name(metadata):
    """从元数据中提取tvg-name"""
    match = re.search(r'tvg-name="([^"]*)"', metadata)
    if match:
        return match.group(1)
    return None


def set_group_title(metadata, group_title):
    """设置或替换元数据中的group-title属性，确保完全移除原有的group-title"""
    # 首先移除所有现有的group-title属性（包括单引号和双引号）
    metadata = re.sub(r'group-title=[\'"][^\'"]*[\'"]', '', metadata)
    metadata = re.sub(r'\s+', ' ', metadata).strip()

    # 在逗号前添加新的group-title属性
    if ',' in metadata:
        parts = metadata.split(',', 1)
        new_metadata = f'{parts[0]} group-title="{group_title}",{parts[1]}'
    else:
        new_metadata = f'{metadata} group-title="{group_title}"'

    return new_metadata


def generate_unique_tvg_name(metadata, source_index):
    """生成唯一的tvg-name，避免重复"""
    # 提取原始tvg-name
    original_tvg_name = extract_tvg_name(metadata)

    if original_tvg_name:
        # 移除现有的tvg-name
        metadata = re.sub(r'tvg-name="[^"]*"', '', metadata)
        metadata = re.sub(r'\s+', ' ', metadata).strip()

        # 添加带源编号的唯一tvg-name
        if ',' in metadata:
            parts = metadata.split(',', 1)
            new_metadata = f'{parts[0]} tvg-name="{original_tvg_name}_源{source_index}",{parts[1]}'
        else:
            new_metadata = f'{metadata} tvg-name="{original_tvg_name}_源{source_index}"'
    else:
        # 如果没有tvg-name，在频道名称中添加源标识
        if ',' in metadata:
            parts = metadata.split(',', 1)
            new_metadata = f'{parts[0]} tvg-name="频道_源{source_index}",{parts[1]}'
        else:
            new_metadata = f'{metadata} tvg-name="频道_源{source_index}"'

    return new_metadata


def generate_m3u_file(found_channel_urls, channel_list, channel_metadata_map, channel_to_group):
    """生成最终的M3U文件，包含所有找到的频道URL"""
    print("\n📝 生成结果文件...")
    with open('simple.m3u', 'w', encoding='utf-8') as f:
        # 写入M3U头部
        f.write("#EXTM3U\n")

        # 按照原始顺序写入频道
        for channel_name in channel_list:
            if channel_name in found_channel_urls:
                # 获取分组名称（如果有）
                group_title = channel_to_group.get(channel_name) if channel_to_group else None

                # 获取该频道的所有URL
                urls = found_channel_urls[channel_name]

                # 为每个URL写入一个条目
                for i, url in enumerate(urls):
                    # 检查是否有元数据
                    if channel_name in channel_metadata_map:
                        metadata = channel_metadata_map[channel_name]

                        # 如果有分组名称，设置或替换group-title
                        if group_title:
                            metadata = set_group_title(metadata, group_title)

                        # 确保tvg-name唯一性
                        metadata = generate_unique_tvg_name(metadata, i + 1)

                        # 使用处理后的元数据格式
                        f.write(f"{metadata}\n")
                    else:
                        # 如果没有元数据，创建新的元数据行
                        if group_title:
                            f.write(
                                f'#EXTINF:-1 group-title="{group_title}" tvg-name="{channel_name}_源{i + 1}", {channel_name}\n')
                        else:
                            f.write(
                                f'#EXTINF:-1 tvg-name="{channel_name}_源{i + 1}", {channel_name}\n')

                    f.write(f"{url}\n")


def print_report(found_channel_urls, channel_list, missing_channel_list):
    """打印详细报告"""
    found_count = len(found_channel_urls)
    total_count = len(channel_list)

    # 计算总URL数量
    total_urls = sum(len(urls) for urls in found_channel_urls.values())

    # 打印每个频道找到的源数量
    print("\n📊 各频道源数量统计:")
    for channel_name in sorted(found_channel_urls.keys()):
        url_count = len(found_channel_urls[channel_name])
        print(f"  {channel_name}: {url_count}个源")

    print("\n" + "=" * 50)
    print(f"🔍 查找结果统计:")
    print(f"  找到频道: {found_count}/{total_count}")
    print(f"  总URL数量: {total_urls}")
    print(f"  未找到频道: {len(missing_channel_list)}")

    if missing_channel_list:
        print("\n⚠️ 未找到的频道列表:")
        for idx, channel_name in enumerate(missing_channel_list, 1):
            print(f"  {idx}. {channel_name}")
    else:
        print("\n🎉 恭喜！所有频道均已成功找到")

    print("=" * 50)


def main():
    # 1. 加载频道列表和分组映射及重复频道信息
    channel_list, channel_to_group, duplicate_channels = load_channels()
    if not channel_list:
        return

    # 2. 加载源列表
    sources = load_sources()
    if not sources:
        return

    # 3. 在源中查找频道
    found_channel_urls, channel_metadata_map, missing_channel_list = find_channels(sources,
                                                                                   channel_list)

    # 4. 生成M3U文件
    generate_m3u_file(found_channel_urls, channel_list, channel_metadata_map, channel_to_group)

    # 5. 打印报告
    print_report(found_channel_urls, channel_list, missing_channel_list)


if __name__ == '__main__':
    main()