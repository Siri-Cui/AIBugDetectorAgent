"""规则引擎
作用：定义和管理静态分析规则
依赖：configs.static_rules.yaml、utils.logger
调用关系：被静态分析工具调用
"""
import os
import yaml
from typing import Dict, List, Any, Optional

from utils.logger import log_info, log_error
from config import settings  # ✅ 修复导入

class RuleEngine:
    """规则引擎 - 管理静态分析规则"""
    
    def __init__(self):
        self.rules = {}
        self.rule_file = os.path.join("configs", "static_rules.yaml")
        self.load_rules()
    
    def load_rules(self) -> None:
        """加载规则配置"""
        try:
            if os.path.exists(self.rule_file):
                with open(self.rule_file, 'r', encoding='utf-8') as f:
                    self.rules = yaml.safe_load(f) or {}
                log_info(f"加载规则配置: {len(self.rules)} 条规则")
            else:
                self.rules = self._get_default_rules()
                log_info("使用默认规则配置")
                
        except Exception as e:
            log_error(f"加载规则配置失败: {str(e)}")
            self.rules = self._get_default_rules()


    
    def get_cppcheck_rules(self) -> List[str]:
        """获取Cppcheck规则"""
        return self.rules.get('cppcheck', {}).get('enabled_checks', [
            'all'
        ])
    
    def get_severity_mapping(self) -> Dict[str, str]:
        """获取严重程度映射"""
        return self.rules.get('severity_mapping', {
            'error': 'high',
            'warning': 'medium',
            'style': 'low',
            'performance': 'medium',
            'information': 'info'
        })
    
    def should_ignore_issue(self, issue: Dict[str, Any]) -> bool:
        """判断是否应该忽略某个问题"""
        ignore_rules = self.rules.get('ignore_rules', [])
        
        for rule in ignore_rules:
            if self._match_rule(issue, rule):
                return True
        
        return False
    
    def _match_rule(self, issue: Dict[str, Any], rule: Dict[str, Any]) -> bool:
        """匹配规则"""
        for key, value in rule.items():
            if key in issue and issue[key] == value:
                return True
        return False
    
    def _get_default_rules(self) -> Dict[str, Any]:
        """获取默认规则配置"""
        return {
            'cppcheck': {
                'enabled_checks': ['all'],
                'disabled_checks': ['missingIncludeSystem', 'unusedFunction']
            },
            'severity_mapping': {
                'error': 'high',
                'warning': 'medium',
                'style': 'low',
                'performance': 'medium',
                'information': 'info'
            },
            'ignore_rules': [
                {'category': 'missingIncludeSystem'},
                {'category': 'unusedFunction'}
            ]
        }