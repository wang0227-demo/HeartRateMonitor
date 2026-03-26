# config.py

import json
import os
import shutil

CONFIG_FILE = "config.json"
TEMP_FILE = CONFIG_FILE + ".tmp"
BACKUP_FILE = CONFIG_FILE + ".bak"

def save_config(config: dict):
    """
    原子化保存配置，并支持美化缩进。
    """
    try:
        # 1. 写入临时文件，显式指定 utf-8 和缩进，方便人工查看
        with open(TEMP_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        
        # 2. (可选) 如果原文件存在，先做个备份，防止 os.replace 失败
        if os.path.exists(CONFIG_FILE):
            shutil.copy2(CONFIG_FILE, BACKUP_FILE)
            
        # 3. 替换目标文件
        os.replace(TEMP_FILE, CONFIG_FILE)
    except Exception as e:
        print(f"配置文件保存失败: {e}")

def load_config() -> dict:
    """
    从文件加载配置，带异常处理。
    """
    if not os.path.exists(CONFIG_FILE):
        return {}
    
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        # 如果主文件损坏，尝试从备份恢复
        if os.path.exists(BACKUP_FILE):
            try:
                with open(BACKUP_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {}
