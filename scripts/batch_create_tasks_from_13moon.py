"""
how to use:
python -m scripts.batch_create_tasks_from_13moon

"""
import re
import sys
from pathlib import Path

# 添加 scripts 目录到 Python 路径
sys.path.append(str(Path(__file__).parent))

from utils.api_auth import load_env_from_root, login_with_env
from utils.api_client import ApiClient

# --- 配置区 ---

# 任务的固定参数，请根据您的需求修改
VISION_ID = "d9ed42fb-de78-4ce5-853a-b16e68452726" # super me
PARENT_TASK_ID = "71ccf1c7-335b-4826-b534-db6fdbeefae2" #4月
TASK_PRIORITY = 5

# 笔记的固定参数，请根据您的需求修改
NOTE_TAG_IDS = [
    "96361a20-fcc2-4304-b066-0f3c10d1e452", #ai-13月亮历
    ]

# --- 待处理的数据 ---
# 将您的所有数据粘贴到下面的多行字符串中
raw_data = """


2025年10月21日 星期二
Kin 211, 电力的蓝猴 (Electric Blue Monkey)

关键词：服务、启动、连结

核心提问：我如何才能更好地服务？

能量解读：在经历了挑战之后，今天的能量转向了“启动”与“连结”。电力的调性是关于“活化”的。而蓝猴，代表着游戏、魔法与轻松。这是一个非常适合用“玩”的心态来为你的生活和工作“服务”的日子。它邀请你，在那些让你感到沉重的任务中，找到一种轻松连结的方式，活化你的内在创造力。问问自己：今天，我可以通过哪个具体的“游戏”，来最好地“启动”我的服务之心？

2025年10月22日 星期三
Kin 212, 自我存在的黄人 (Self-Existing Yellow Human)

关键词：形式、定义、衡量

核心提问：我的服务的形式是什么？

能量解读：今天，我们再次回到了这个月的主题能量——自我存在的调性。它邀请我们去“定义”和“衡量”。而黄人，代表着自由意志、智慧与影响。这是一个将你内在的“智慧”，用一个清晰的“形式”表达出来的强大日子。它非常适合你去为自己的工作流、生活节律，设计一个更符合你“自由意志”的结构。问问自己：我那股想要影响世界的智慧，今天将以怎样的“形式”被呈现出来？

"""

def parse_date_from_title(title):
    """从标题中解析出 YYYY-MM-DD 格式的日期"""
    match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', title)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return None

def split_data_by_date(data):
    """根据日期模式分割数据"""
    # 使用正则表达式匹配日期行
    date_pattern = re.compile(r'^\d{4}年\d{1,2}月\d{1,2}日')

    entries = []
    current_entry = []
    lines = data.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 如果这一行是日期行，开始新的条目
        if date_pattern.match(line):
            # 如果当前条目不为空，保存它
            if current_entry:
                entries.append('\n'.join(current_entry))
            # 开始新条目
            current_entry = [line]
        else:
            # 添加到当前条目
            current_entry.append(line)

    # 保存最后一个条目
    if current_entry:
        entries.append('\n'.join(current_entry))

    return entries

def process_data(data):
    """主处理函数"""
    # 初始化 API 客户端
    print("正在登录...")
    load_env_from_root()
    session, base_url, _token = login_with_env(timeout_s=15)
    client = ApiClient(session=session, base_url=base_url)
    print("登录成功！")

    # 1. 根据日期模式分割数据
    entries = split_data_by_date(data)

    if not entries:
        print("没有找到有效的数据条目。")
        return

    print(f"检测到 {len(entries)} 条数据，开始处理...")

    for i, entry in enumerate(entries):
        print("-" * 40)
        print(f"正在处理第 {i+1} 条数据...")

        lines = entry.split('\n')
        # 构建完整的任务标题：日期 + Kin信息
        task_title = f"{lines[0].strip()}\n{lines[1].strip()}" if len(lines) > 1 else lines[0].strip()
        note_content = entry.strip()

        # 2. 从标题解析日期
        start_date = parse_date_from_title(lines[0].strip())
        if not start_date:
            print(f"[错误] 无法从标题 '{lines[0].strip()}' 中解析出日期，跳过此条目。")
            continue

        print(f"任务标题: {task_title}")
        print(f"规划日期: {start_date}")

        try:
            print("正在创建任务...")
            # 3. 创建任务 (Task)
            task = client.create_task(
                content=task_title,
                vision_id=VISION_ID,
                priority=TASK_PRIORITY,
                parent_task_id=PARENT_TASK_ID,
                person_ids=[],
                planning_cycle_type="day",
                planning_cycle_days=1,
                planning_cycle_start_date=start_date,
                display_order=0
            )

            print(f"任务创建成功！ID: {task.id}")

            # 4. 创建笔记 (Note)
            print(f"正在为任务 ID {task.id} 创建关联笔记...")
            note = client.create_note(
                content=note_content,
                tag_ids=NOTE_TAG_IDS,
                task_id=task.id
            )

            print("笔记创建成功！")

        except Exception as e:
            print(f"[严重错误] 处理数据时发生错误: {e}")
            break # 发生错误时，终止脚本

    print("-" * 40)
    print("所有任务处理完毕！")

if __name__ == "__main__":
    process_data(raw_data)
