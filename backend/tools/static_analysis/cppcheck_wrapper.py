"""Cppcheck工具封装
作用：封装Cppcheck静态分析工具，提供统一接口
依赖：asyncio、subprocess、utils.logger
调用关系：被DetectionAgent调用
"""
import asyncio
import os
import subprocess
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional
from utils.logger import log_info, log_error


class CppcheckWrapper:
    """Cppcheck静态分析工具封装"""
    
    def __init__(self, cppcheck_path: str = "cppcheck"):
        self.cppcheck_path = cppcheck_path
        # 🆕 增强的默认参数
        self.default_args = [
            "--enable=all",           # 启用所有检查
            "--inconclusive",         # 🆕 启用不确定的检查（重要！能检测更多空指针）
            "--library=qt",           # 🆕 启用Qt库支持（关键！理解Qt API）
            "--library=std",          # 🆕 启用C++标准库支持
            "--library=posix",        # 🆕 POSIX库支持
            "--xml",                  # 输出XML格式
            "--xml-version=2",        # XML版本2
            "--force",                # 强制检查所有配置
            "--inline-suppr",         # 允许行内抑制
            "--suppress=missingInclude",  # 🆕 抑制缺少头文件警告（减少噪音）
            "--suppress=unmatchedSuppression",  # 🆕 抑制不匹配的抑制警告
            "-j", str(os.cpu_count() or 4)  # 🆕 多线程加速
        ]
        
    async def analyze(self, project_path: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行Cppcheck分析
        输入：项目路径和配置
        输出：分析结果字典
        """
        try:
            # 检查Cppcheck是否可用
            if not await self._check_cppcheck_available():
                return {
                    'success': False,
                    'error': 'Cppcheck not found',
                    'issues': []
                }
            
            log_info(f"开始Cppcheck分析 (增强模式): {project_path}")
            
            # 构建命令参数
            cmd_args = [self.cppcheck_path] + self.default_args
            
            # 🆕 支持自定义配置覆盖
            if config:
                if config.get('enable_verbose'):
                    cmd_args.append('--verbose')
                if config.get('max_configs'):
                    cmd_args.extend(['--max-configs', str(config['max_configs'])])
                # 自定义抑制规则
                if config.get('suppress_ids'):
                    for suppress_id in config['suppress_ids']:
                        cmd_args.append(f'--suppress={suppress_id}')
            
            cmd_args.append(project_path)
            
            log_info(f"🔍 Cppcheck命令: {' '.join(cmd_args[:5])}... (共{len(cmd_args)}个参数)")
            
            # 执行Cppcheck
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # 🆕 增加超时控制
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=600  # 10分钟超时
                )
            except asyncio.TimeoutError:
                process.kill()
                log_error("Cppcheck分析超时 (10分钟)")
                return {
                    'success': False,
                    'error': 'Analysis timeout',
                    'issues': []
                }
            
            # Cppcheck输出结果在stderr中
            if stderr:
                issues = self._parse_cppcheck_xml(stderr.decode('utf-8', errors='ignore'))
                
                # 🆕 统计并分类问题
                null_pointer_issues = [i for i in issues if 'null' in i.get('category', '').lower() 
                                      or 'nullptr' in i.get('message', '').lower()]
                
                log_info(f"✅ Cppcheck分析完成，发现 {len(issues)} 个问题")
                if null_pointer_issues:
                    log_info(f"   其中空指针相关: {len(null_pointer_issues)} 个")
                
                return {
                    'success': True,
                    'tool': 'cppcheck',
                    'issues': issues,
                    'statistics': {  # 🆕 添加统计信息
                        'total': len(issues),
                        'null_pointer_related': len(null_pointer_issues),
                        'by_severity': self._count_by_severity(issues)
                    },
                    'raw_output': stderr.decode('utf-8', errors='ignore')
                }
            else:
                log_info("✅ Cppcheck分析完成，未发现问题")
                return {
                    'success': True,
                    'tool': 'cppcheck', 
                    'issues': [],
                    'message': 'No issues found'
                }
                
        except Exception as e:
            log_error(f"❌ Cppcheck分析异常: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'issues': []
            }
    
    async def _check_cppcheck_available(self) -> bool:
        """检查Cppcheck是否可用"""
        try:
            process = await asyncio.create_subprocess_exec(
                self.cppcheck_path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                version = stdout.decode('utf-8').strip()
                log_info(f"检测到 {version}")
                
                # 🆕 检查是否支持 Qt 库
                if '--library=qt' in self.default_args:
                    qt_check = await self._check_qt_library_support()
                    if not qt_check:
                        log_error("⚠️ Cppcheck可能不支持Qt库，建议升级到2.0+版本")
                
                return True
            return False
        except:
            return False
    
    async def _check_qt_library_support(self) -> bool:
        """🆕 检查Qt库支持"""
        try:
            process = await asyncio.create_subprocess_exec(
                self.cppcheck_path, "--library=qt", "--help",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            return process.returncode == 0
        except:
            return False
    
    def _parse_cppcheck_xml(self, xml_output: str) -> List[Dict[str, Any]]:
        """解析Cppcheck XML输出"""
        issues = []
        
        try:
            # 提取XML部分
            xml_start = xml_output.find('<?xml')
            if xml_start == -1:
                return self._parse_cppcheck_text(xml_output)
            
            xml_content = xml_output[xml_start:]
            root = ET.fromstring(xml_content)
            
            for error in root.findall('.//error'):
                error_id = error.get('id', '')
                severity = error.get('severity', 'info')
                message = error.get('msg', '')
                
                issue = {
                    'id': error_id,
                    'severity': self._map_severity(severity),
                    'message': message,
                    'category': error_id,
                    'tool': 'cppcheck',
                    'verbose': error.get('verbose', message),  # 🆕 详细信息
                }
                
                # 🆕 标记空指针相关问题
                if any(keyword in error_id.lower() for keyword in 
                       ['null', 'nullptr', 'dereference', 'uninit']):
                    issue['tags'] = ['null_pointer_risk']
                    issue['priority'] = 'high'  # 提高优先级
                
                # 获取位置信息
                location = error.find('location')
                if location is not None:
                    issue.update({
                        'file': location.get('file', ''),
                        'line': int(location.get('line', 0)),
                        'column': int(location.get('column', 0)) if location.get('column') else None,
                        'info': location.get('info', '')  # 🆕 额外信息
                    })
                
                issues.append(issue)
        
        except ET.ParseError as e:
            log_error(f"XML解析失败: {str(e)}")
            return self._parse_cppcheck_text(xml_output)
        except Exception as e:
            log_error(f"处理Cppcheck输出异常: {str(e)}")
        
        return issues
    
    def _parse_cppcheck_text(self, text_output: str) -> List[Dict[str, Any]]:
        """解析Cppcheck文本输出（备用方案）"""
        issues = []
        
        for line in text_output.splitlines():
            if ':' in line and any(severity in line for severity in 
                                  ['error', 'warning', 'style', 'performance']):
                try:
                    parts = line.split(':', 3)
                    if len(parts) >= 3:
                        issue = {
                            'file': parts[0].strip() if len(parts) > 0 else '',
                            'line': int(parts[1].strip()) if parts[1].strip().isdigit() else 0,
                            'severity': 'medium',
                            'message': parts[-1].strip() if len(parts) > 2 else line,
                            'category': 'cppcheck_text',
                            'tool': 'cppcheck'
                        }
                        issues.append(issue)
                except:
                    continue
        
        return issues
    
    def _map_severity(self, cppcheck_severity: str) -> str:
        """映射Cppcheck严重程度到统一标准"""
        severity_map = {
            'error': 'high',
            'warning': 'medium',
            'style': 'low',
            'performance': 'medium',
            'portability': 'low',
            'information': 'info',
            'debug': 'info'  # 🆕
        }
        return severity_map.get(cppcheck_severity, 'info')
    
    def _count_by_severity(self, issues: List[Dict]) -> Dict[str, int]:
        """🆕 统计各严重度数量"""
        counts = {'high': 0, 'medium': 0, 'low': 0, 'info': 0}
        for issue in issues:
            severity = issue.get('severity', 'info')
            counts[severity] = counts.get(severity, 0) + 1
        return counts
