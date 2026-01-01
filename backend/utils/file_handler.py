"""文件处理工具"""

import os
import shutil
import zipfile
import tarfile
import hashlib
from typing import List, Tuple, Optional
from pathlib import Path

from config import settings
from utils.logger import log_info, log_error
from utils.exceptions import FileUploadError

def get_file_hash(file_path: str) -> str:
    """计算文件MD5哈希值"""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        log_error(f"计算文件哈希失败: {str(e)}")
        raise

def extract_archive(archive_path: str, extract_to: str) -> List[str]:
    """解压缩文件"""
    extracted_files = []
    
    try:
        if archive_path.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
                extracted_files = zip_ref.namelist()
        elif archive_path.endswith(('.tar', '.tar.gz', '.tgz')):
            with tarfile.open(archive_path, 'r:*') as tar_ref:
                tar_ref.extractall(extract_to)
                extracted_files = tar_ref.getnames()
        else:
            # 单个文件直接复制
            filename = os.path.basename(archive_path)
            dest_path = os.path.join(extract_to, filename)
            shutil.copy2(archive_path, dest_path)
            extracted_files = [filename]
        
        log_info(f"解压文件成功: {len(extracted_files)} 个文件")
        return extracted_files
        
    except Exception as e:
        log_error(f"解压文件失败: {str(e)}")
        raise FileUploadError(f"解压文件失败: {str(e)}")

def find_cpp_files(directory: str) -> List[Tuple[str, str]]:
    """查找C++文件"""
    cpp_extensions = settings.ALLOWED_EXTENSIONS
    cpp_files = []
    
    try:
        for root, dirs, files in os.walk(directory):
            for file in files:
                if any(file.lower().endswith(ext.lower()) for ext in cpp_extensions):
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, directory)
                    cpp_files.append((full_path, relative_path))
        
        log_info(f"找到 {len(cpp_files)} 个C++文件")
        return cpp_files
        
    except Exception as e:
        log_error(f"查找C++文件失败: {str(e)}")
        raise

def clean_temp_files(directory: str, max_age_hours: int = 24):
    """清理临时文件"""
    try:
        import time
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getctime(file_path)
                    if file_age > max_age_seconds:
                        os.remove(file_path)
                        log_info(f"清理临时文件: {file_path}")
        
    except Exception as e:
        log_error(f"清理临时文件失败: {str(e)}")

def ensure_directory(path: str):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)

def get_file_info(file_path: str) -> dict:
    """获取文件详细信息"""
    try:
        stat = os.stat(file_path)
        return {
            "size": stat.st_size,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "extension": os.path.splitext(file_path)[1],
            "basename": os.path.basename(file_path)
        }
    except Exception as e:
        log_error(f"获取文件信息失败: {str(e)}")
        return {}
