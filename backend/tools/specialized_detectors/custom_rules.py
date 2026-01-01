"""
可扩展自定义规则引擎
作用：允许用户添加项目特定的检测规则
依赖：pattern_matcher、utils.logger
调用关系：被DetectionAgent调用
"""
import os
import re
import json
from typing import Dict, List, Any
from .pattern_matcher import PatternMatcher
from utils.logger import log_info, log_error, log_warning


class CustomRule:
    """单个自定义规则"""
    
    def __init__(
        self,
        rule_id: str,
        name: str,
        description: str,
        pattern: str,
        severity: str,
        message: str,
        suggestion: str,
        file_extensions: List[str] = None
    ):
        self.rule_id = rule_id
        self.name = name
        self.description = description
        self.pattern = re.compile(pattern)
        self.severity = severity
        self.message = message
        self.suggestion = suggestion
        self.file_extensions = file_extensions or ['.cpp', '.h', '.hpp', '.c']
    
    def check(self, code: str, file_path: str) -> List[Dict[str, Any]]:
        """检查代码是否匹配规则"""
        issues = []
        
        # 检查文件扩展名
        if not any(file_path.endswith(ext) for ext in self.file_extensions):
            return issues
        
        lines = code.split('\n')
        for line_num, line in enumerate(lines, 1):
            match = self.pattern.search(line)
            if match:
                issues.append({
                    'type': 'custom_rule',
                    'rule_id': self.rule_id,
                    'rule_name': self.name,
                    'severity': self.severity,
                    'file': os.path.basename(file_path),
                    'line': line_num,
                    'code': line.strip(),
                    'message': self.message,
                    'suggestion': self.suggestion,
                    'matched_text': match.group(0)
                })
        
        return issues


class CustomRulesEngine:
    """自定义规则引擎"""
    
    def __init__(self, rules_dir: str = None):
        """初始化规则引擎"""
        if rules_dir is None:
            backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            rules_dir = os.path.join(backend_dir, '..', 'configs', 'custom_rules')
        
        self.rules_dir = rules_dir
        self.rules: List[CustomRule] = []
        self.matcher = PatternMatcher()
        
        # 创建规则目录
        os.makedirs(self.rules_dir, exist_ok=True)
        
        # 加载内置规则
        self._load_builtin_rules()
        
        # 加载用户自定义规则
        self._load_user_rules()
    
    def _load_builtin_rules(self):
        """加载内置规则"""
        # 规则1: 禁止使用strcpy
        self.rules.append(CustomRule(
            rule_id='DANGEROUS_FUNC_001',
            name='禁止使用strcpy',
            description='strcpy不检查缓冲区大小，容易导致溢出',
            pattern=r'\bstrcpy\s*\(',
            severity='high',
            message='使用了不安全的strcpy函数',
            suggestion='使用strncpy或std::string替代'
        ))
        
        # 规则2: 禁止使用gets
        self.rules.append(CustomRule(
            rule_id='DANGEROUS_FUNC_002',
            name='禁止使用gets',
            description='gets函数无法限制输入长度',
            pattern=r'\bgets\s*\(',
            severity='critical',
            message='使用了极其危险的gets函数',
            suggestion='使用fgets或std::getline替代'
        ))
        
        # 规则3: 检测hardcoded密码
        self.rules.append(CustomRule(
            rule_id='SECURITY_001',
            name='硬编码密码',
            description='代码中不应包含硬编码的密码',
            pattern=r'(password|passwd|pwd)\s*=\s*["\'][\w]+["\']',
            severity='critical',
            message='检测到硬编码的密码',
            suggestion='使用配置文件或环境变量存储敏感信息'
        ))
        
        # 规则4: 检测魔法数字
        self.rules.append(CustomRule(
            rule_id='CODE_QUALITY_001',
            name='魔法数字',
            description='直接使用数字字面量降低代码可读性',
            pattern=r'[^\w](\d{3,})[^\w]',
            severity='low',
            message='使用了魔法数字',
            suggestion='定义有意义的常量替代魔法数字'
        ))
        
        # 规则5: TODO/FIXME标记
        self.rules.append(CustomRule(
            rule_id='CODE_QUALITY_002',
            name='未完成的代码',
            description='TODO/FIXME标记表示代码未完成',
            pattern=r'//\s*(TODO|FIXME|HACK|XXX):',
            severity='low',
            message='代码包含TODO/FIXME标记',
            suggestion='完成标记的工作或删除注释'
        ))
        
        log_info(f"加载了 {len(self.rules)} 条内置规则")
    
    def _load_user_rules(self):
        """从JSON文件加载用户自定义规则"""
        rules_file = os.path.join(self.rules_dir, 'user_rules.json')
        
        if not os.path.exists(rules_file):
            self._create_example_rules_file(rules_file)
            return
        
        try:
            with open(rules_file, 'r', encoding='utf-8') as f:
                user_rules_data = json.load(f)
            
            for rule_data in user_rules_data.get('rules', []):
                try:
                    rule = CustomRule(
                        rule_id=rule_data['rule_id'],
                        name=rule_data['name'],
                        description=rule_data.get('description', ''),
                        pattern=rule_data['pattern'],
                        severity=rule_data.get('severity', 'medium'),
                        message=rule_data['message'],
                        suggestion=rule_data.get('suggestion', ''),
                        file_extensions=rule_data.get('file_extensions', ['.cpp', '.h'])
                    )
                    self.rules.append(rule)
                    log_info(f"加载用户规则: {rule.name}")
                except Exception as e:
                    log_error(f"加载规则失败: {str(e)}")
            
            log_info(f"总共加载了 {len(self.rules)} 条规则")
            
        except Exception as e:
            log_error(f"加载用户规则文件失败: {str(e)}")
    
    def _create_example_rules_file(self, file_path: str):
        """创建示例规则文件"""
        example_rules = {
            "rules": [
                {
                    "rule_id": "USER_001",
                    "name": "检测printf调试语句",
                    "description": "生产代码中不应包含printf调试语句",
                    "pattern": "printf\\s*\\(",
                    "severity": "low",
                    "message": "检测到printf调试语句",
                    "suggestion": "使用日志系统替代printf",
                    "file_extensions": [".cpp", ".c"]
                }
            ],
            "description": "自定义规则配置文件"
        }
        
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(example_rules, f, indent=2, ensure_ascii=False)
            log_info(f"创建示例规则文件: {file_path}")
        except Exception as e:
            log_error(f"创建示例规则文件失败: {str(e)}")
    
    async def detect(self, project_path: str, enabled_rules: List[str] = None) -> Dict[str, Any]:
        """执行自定义规则检测"""
        try:
            log_info("开始自定义规则检测")
            
            active_rules = self.rules
            if enabled_rules:
                active_rules = [r for r in self.rules if r.rule_id in enabled_rules]
            
            log_info(f"激活 {len(active_rules)} 条规则")
            
            issues = []
            files_analyzed = []
            
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['build', 'cmake-build-debug']]
                
                for file in files:
                    if any(file.endswith(ext) for ext in ['.cpp', '.c', '.h', '.hpp']):
                        file_path = os.path.join(root, file)
                        
                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                code = f.read()
                            
                            for rule in active_rules:
                                rule_issues = rule.check(code, file_path)
                                issues.extend(rule_issues)
                            
                            if issues:
                                files_analyzed.append(os.path.basename(file_path))
                        
                        except Exception as e:
                            log_warning(f"读取文件失败 {file_path}: {str(e)}")
                            continue
            
            log_info(f"自定义规则检测完成，发现{len(issues)}个问题")
            
            return {
                'success': True,
                'tool': 'custom_rules',
                'rules_applied': len(active_rules),
                'issues': issues,
                'files_analyzed': list(set(files_analyzed)),
                'summary': {
                    'total_issues': len(issues),
                    'critical': len([i for i in issues if i['severity'] == 'critical']),
                    'high': len([i for i in issues if i['severity'] == 'high']),
                    'medium': len([i for i in issues if i['severity'] == 'medium']),
                    'low': len([i for i in issues if i['severity'] == 'low'])
                }
            }
            
        except Exception as e:
            log_error(f"自定义规则检测异常: {str(e)}")
            return {'success': False, 'error': str(e), 'issues': []}
