# -*- coding: utf-8 -*-
"""
AI后处理器 - 使用LLM智能去重和分析检测结果
"""
import json
from typing import Dict, List, Any
from pathlib import Path
from tools.llm_client import LLMClient
from tools.code_extractor import CodeExtractor
from utils.logger import log_info, log_error, log_warning
class AIPostProcessor:
    """AI驱动的检测结果后处理器"""
    
    def __init__(self, llm_client: LLMClient = None):
        self.llm_client = llm_client or LLMClient()
        self.code_extractor = CodeExtractor()
        
    async def process_detection_results(
        self,
        raw_results: Dict[str, Any],
        project_path: str
    ) -> Dict[str, Any]:
        log_info("🤖 开始AI后处理...")
        
        try:
            source_code_map = self._extract_source_code(
                raw_results['issues'],
                project_path
            )
            
            prompt = self._build_analysis_prompt(
                raw_results,
                source_code_map
            )
            
            log_info("📡 调用智谱API进行智能分析...")
            ai_response = await self.llm_client.analyze_with_context(
                prompt=prompt,
                temperature=0.3,
                max_tokens=8000
            )
            
            processed_results = self._parse_ai_response(
                ai_response,
                raw_results
            )
            
            final_results = self._merge_results(
                raw_results,
                processed_results
            )
            
            log_info(f"✅ AI处理完成: {len(raw_results['issues'])} → {len(final_results['issues'])} 问题")
            return final_results
            
        except Exception as e:
            log_error(f"AI后处理失败: {e}")
            log_warning("⚠️ 降级使用原始检测结果")
            return raw_results
    
    def _extract_source_code(
        self,
        issues: List[Dict],
        project_path: str
    ) -> Dict[str, str]:
        source_map = {}
        project_root = Path(project_path)
        
        files_to_extract = set()
        for issue in issues:
            for frame in issue.get('stack_trace', []):
                file_path = frame.get('file', '')
                if str(project_root) in file_path:
                    files_to_extract.add(file_path)
            
            if issue.get('file'):
                issue_file = issue['file']
                for f in project_root.rglob('*.cpp'):
                    if f.name == Path(issue_file).name:
                        files_to_extract.add(str(f))
        
        for file_path in files_to_extract:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    source_map[file_path] = f.read()
            except Exception as e:
                log_warning(f"无法读取 {file_path}: {e}")
        
        log_info(f"📄 提取了 {len(source_map)} 个源文件")
        return source_map
    
    def _build_analysis_prompt(
        self,
        raw_results: Dict,
        source_code_map: Dict[str, str]
    ) -> str:
        simplified_issues = []
        for i, issue in enumerate(raw_results['issues']):
            simplified_issues.append({
                'original_index': i,
                'type': issue['type'],
                'severity': issue['severity'],
                'message': issue['message'],
                'tool': issue['tool'],
                'file': issue.get('file'),
                'line': issue.get('line'),
                'category': issue.get('category'),
                'stack_trace': issue.get('stack_trace', [])[:3]
            })
        
        prompt = f"""# 任务:智能分析C++代码漏洞检测结果

## 检测工具报告(原始)
共检测到 {len(simplified_issues)} 个问题:

```json
{json.dumps(simplified_issues, indent=2, ensure_ascii=False)}
```

## 相关源代码
"""
        # ⚠️ 这里是重点：for循环体必须缩进！
        for file_path, code in list(source_code_map.items())[:10]:
            file_name = Path(file_path).name
            lines = code.split('\n')
            numbered_code = '\n'.join(
                f"{i+1:4d} | {line}"
                for i, line in enumerate(lines[:100])
            )

            prompt += f"""
    文件: {file_name}
```cpp
    {numbered_code}
```

"""
    
        prompt += """
你的任务
请你作为一个专业的静态分析专家,完成以下工作:

1. 智能去重
识别完全重复的问题(同一漏洞被多个工具/多次执行检测到)

识别同根问题(同一个bug的不同表现,如heap-overflow导致的SEGV)

保留每组重复中最详细的那个

2. 问题分类
将问题分组为:

真实漏洞: 确实存在的安全问题

误报: 工具误判

重复: 与其他问题重复

3. 根因分析
对每个真实漏洞,找出:

漏洞的根本原因(哪行代码、什么逻辑错误)

CVE类型(如果能识别,如CWE-122)

影响范围

4. 修复建议
为每个真实漏洞提供:

具体的修复代码(diff格式)

安全编码建议

输出格式(必须严格JSON)

{{
  "deduplication": {{
    "original_count": 46,
    "unique_count": 5,
    "duplicate_groups": [
      {{
        "representative_index": 0,
        "duplicates": [1, 2, 3],
        "reason": "同一个堆溢出被ASan、Valgrind多次检测到"
      }}
    ]
  }},
  "classification": {{
    "real_vulnerabilities": [
      {{
        "issue_index": 0,
        "type": "heap-buffer-overflow",
        "severity": "critical",
        "file": "vuln_001.cpp",
        "line": 25,
        "root_cause": "realloc失败后仍然memcpy",
        "cve_type": "CWE-122",
        "impact": "可造成远程代码执行"
      }}
    ],
    "false_positives": [],
    "duplicates": []
  }},
  "repair_suggestions": [
    {{
      "issue_index": 0,
      "title": "修复堆溢出漏洞",
      "description": "检查realloc返回值",
      "code_diff": "--- a/vuln_001.cpp\\n+++ b/vuln_001.cpp\\n@@ -17,6 +17,9 @@\\n     size_t newCapacity = pool->capacity * 2;\\n     char *newBuffer = (char*)realloc(pool->buffer, newCapacity);\\n-    if (!newBuffer) return -1;\\n+    if (!newBuffer) {{\\n+        return -1;\\n+    }}\\n     pool->buffer = newBuffer;",
      "security_advice": "始终检查内存分配是否成功,失败时不要继续使用原指针"
    }}
  ]
}}
重要:

只输出JSON,不要任何额外文字

所有字符串用UTF-8编码

issue_index指向原始issues数组的索引(original_index)

duplicate_groups中的representative_index是保留的代表issue索引
        """

        return prompt
    

    def _parse_ai_response(
        self,
        ai_response: str,
        raw_results: Dict
    ) -> Dict[str, Any]:
        try:
            json_str = ai_response.strip()
            if '```json' in json_str:
                json_str = json_str.split('```json')[1].split('```')[0]
            elif '```' in json_str:
                json_str = json_str.split('```')[1].split('```')[0]

            parsed = json.loads(json_str)
            return parsed
            
        except json.JSONDecodeError as e:
            log_error(f"AI返回的JSON格式错误: {e}")
            log_error(f"原始响应: {ai_response[:500]}")
            return {
                "deduplication": {
                    "original_count": len(raw_results['issues']),
                    "unique_count": len(raw_results['issues']),
                    "duplicate_groups": []
                },
                "classification": {"real_vulnerabilities": []},
                "repair_suggestions": []
            }

    def _merge_results(
        self,
        raw_results: Dict,
        processed: Dict
    ) -> Dict[str, Any]:
        final = raw_results.copy()

        if processed.get('deduplication'):
            dedup = processed['deduplication']
            
            keep_indices = set()
            
            for group in dedup.get('duplicate_groups', []):
                rep_idx = group.get('representative_index')
                if rep_idx is not None:
                    keep_indices.add(rep_idx)
            
            if not keep_indices:
                log_warning("AI未返回有效去重结果,保留所有问题")
                keep_indices = set(range(len(raw_results['issues'])))
            
            original_count = len(raw_results['issues'])
            final['issues'] = [
                issue for i, issue in enumerate(raw_results['issues'])
                if i in keep_indices
            ]
            
            log_info(f"🗑️ 去重: {original_count} → {len(final['issues'])} 问题")
            
            for issue in final['issues']:
                issue['ai_analyzed'] = True
        
        final['ai_classification'] = processed.get('classification', {})
        
        final['repair_suggestions'] = processed.get('repair_suggestions', [])
        
        final['summary']['total_issues'] = len(final['issues'])
        final['summary']['repairs_generated'] = len(final['repair_suggestions'])
        final['summary']['ai_processed'] = True
        
        if processed.get('deduplication'):
            final['summary']['deduplication'] = {
                'original_count': processed['deduplication'].get('original_count', 0),
                'unique_count': len(final['issues']),
                'reduction_rate': f"{(1 - len(final['issues']) / max(processed['deduplication'].get('original_count', 1), 1)) * 100:.1f}%"
            }
        
        return final
_ai_processor_instance = None

def get_ai_postprocessor() -> AIPostProcessor:
        global _ai_processor_instance
        if _ai_processor_instance is None:
            _ai_processor_instance = AIPostProcessor()
        return _ai_processor_instance
