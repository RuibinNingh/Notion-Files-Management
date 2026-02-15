"""
Python 日志模块
与 C# 日志系统保持一致，保存到相同目录
"""
import logging
import os
from datetime import datetime
from pathlib import Path


class PythonLogger:
    """Python 日志管理器"""
    
    _initialized = False
    _logger = None
    _log_file_path = None
    
    @classmethod
    def init(cls, log_dir: str):
        """
        初始化日志系统
        
        Args:
            log_dir: 日志目录路径（与 C# 日志目录相同）
        """
        if cls._initialized:
            return
        
        try:
            # 确保日志目录存在
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            
            # 生成日志文件名：yyyyMMddHHmmss-Py.logs
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            log_filename = f"{timestamp}-Py.logs"
            cls._log_file_path = log_path / log_filename
            
            # 配置 logging
            cls._logger = logging.getLogger("NotionFilesManagement")
            cls._logger.setLevel(logging.DEBUG)
            
            # 避免重复添加 handler
            if cls._logger.handlers:
                cls._logger.handlers.clear()
            
            # 文件 handler
            file_handler = logging.FileHandler(
                cls._log_file_path,
                mode='a',
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            
            # 控制台 handler（可选，用于调试）
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # 格式化
            formatter = logging.Formatter(
                '[%(asctime)s][T%(thread)d][%(levelname)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            cls._logger.addHandler(file_handler)
            cls._logger.addHandler(console_handler)
            
            cls._initialized = True
            cls._logger.info(f"Python logging enabled: {cls._log_file_path}")
            
        except Exception as e:
            # 如果初始化失败，至少尝试输出到控制台
            print(f"[PythonLogger] Failed to initialize logging: {e}")
            cls._logger = logging.getLogger("NotionFilesManagement")
            cls._logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            cls._logger.addHandler(handler)
            cls._initialized = True
    
    @classmethod
    def get_logger(cls):
        """获取 logger 实例"""
        if not cls._initialized:
            # 如果未初始化，创建一个基本的 logger
            cls._logger = logging.getLogger("NotionFilesManagement")
            cls._logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            cls._logger.addHandler(handler)
            cls._initialized = True
        return cls._logger
    
    @classmethod
    def debug(cls, message: str):
        """Debug 级别日志"""
        cls.get_logger().debug(message)
    
    @classmethod
    def info(cls, message: str):
        """Info 级别日志"""
        cls.get_logger().info(message)
    
    @classmethod
    def warning(cls, message: str):
        """Warning 级别日志"""
        cls.get_logger().warning(message)
    
    @classmethod
    def error(cls, message: str, exc_info=None):
        """Error 级别日志"""
        cls.get_logger().error(message, exc_info=exc_info)
    
    @classmethod
    def get_log_file_path(cls):
        """获取日志文件路径"""
        return cls._log_file_path


# 便捷函数
def get_logger():
    """获取 logger 实例的便捷函数"""
    return PythonLogger.get_logger()


def debug(message: str):
    """Debug 级别日志的便捷函数"""
    PythonLogger.debug(message)


def info(message: str):
    """Info 级别日志的便捷函数"""
    PythonLogger.info(message)


def warning(message: str):
    """Warning 级别日志的便捷函数"""
    PythonLogger.warning(message)


def error(message: str, exc_info=None):
    """Error 级别日志的便捷函数"""
    PythonLogger.error(message, exc_info=exc_info)
