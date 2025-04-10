from mcp.server.fastmcp import FastMCP, Context, Image
import json
import os
import asyncio
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional
from pathlib import Path

# 로깅 설정
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AutoRulesServer")

# 규칙이 저장될 디렉토리
RULES_DIR = Path("rules")

@dataclass
class Rule:
    name: str
    description: str
    original_code: str
    modified_code: str
    feedback: str
    tags: List[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "original_code": self.original_code,
            "modified_code": self.modified_code,
            "feedback": self.feedback,
            "tags": self.tags or []
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Rule':
        return cls(
            name=data["name"],
            description=data["description"],
            original_code=data["original_code"],
            modified_code=data["modified_code"],
            feedback=data["feedback"],
            tags=data.get("tags", [])
        )

class RuleManager:
    def __init__(self):
        self.rules: Dict[str, Rule] = {}
        self._load_rules()
    
    def _load_rules(self) -> None:
        """디스크에서 규칙 로딩"""
        RULES_DIR.mkdir(exist_ok=True)
        
        for rule_file in RULES_DIR.glob("*.json"):
            try:
                with open(rule_file, "r", encoding="utf-8") as f:
                    rule_data = json.load(f)
                    rule = Rule.from_dict(rule_data)
                    self.rules[rule.name] = rule
                    logger.info(f"규칙 로드됨: {rule.name}")
            except Exception as e:
                logger.error(f"규칙 로드 실패: {rule_file.name}: {str(e)}")
    
    def save_rule(self, rule: Rule) -> None:
        """규칙을 디스크에 저장"""
        self.rules[rule.name] = rule
        
        try:
            RULES_DIR.mkdir(exist_ok=True)
            rule_path = RULES_DIR / f"{rule.name}.json"
            
            with open(rule_path, "w", encoding="utf-8") as f:
                json.dump(rule.to_dict(), f, ensure_ascii=False, indent=2)
                
            logger.info(f"규칙 저장됨: {rule.name}")
        except Exception as e:
            logger.error(f"규칙 저장 실패: {rule.name}: {str(e)}")
    
    def get_rule(self, name: str) -> Optional[Rule]:
        """이름으로 규칙 조회"""
        return self.rules.get(name)
    
    def delete_rule(self, name: str) -> bool:
        """규칙 삭제"""
        if name in self.rules:
            try:
                rule_path = RULES_DIR / f"{name}.json"
                if rule_path.exists():
                    rule_path.unlink()
                del self.rules[name]
                logger.info(f"규칙 삭제됨: {name}")
                return True
            except Exception as e:
                logger.error(f"규칙 삭제 실패: {name}: {str(e)}")
                return False
        return False
    
    def list_rules(self) -> List[Dict[str, Any]]:
        """모든 규칙 목록 조회"""
        return [rule.to_dict() for rule in self.rules.values()]
    
    def search_rules(self, query: str = "", tags: List[str] = None) -> List[Dict[str, Any]]:
        """쿼리와 태그로 규칙 검색"""
        results = []
        query = query.lower()
        
        for rule in self.rules.values():
            # 쿼리 검색
            matches_query = (not query) or any(
                query in field.lower() 
                for field in [rule.name, rule.description, rule.original_code, 
                              rule.modified_code, rule.feedback]
            )
            
            # 태그 검색
            matches_tags = (not tags) or (rule.tags and all(tag in rule.tags for tag in tags))
            
            if matches_query and matches_tags:
                results.append(rule.to_dict())
                
        return results

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """서버 시작/종료 라이프사이클 관리"""
    try:
        logger.info("AutoRules 서버 시작 중...")
        rule_manager = RuleManager()
        logger.info(f"{len(rule_manager.rules)} 개의 규칙 로드됨")
        
        yield {"rule_manager": rule_manager}
    finally:
        logger.info("AutoRules 서버 종료 중...")

# MCP 서버 생성
mcp = FastMCP(
    "AutoRules",
    description="LLM 코드 피드백을 통한 자동 규칙 생성 서버",
    lifespan=server_lifespan
)

# 리소스 엔드포인트

@mcp.resource("rules://all")
def get_all_rules() -> str:
    """모든 규칙 조회"""
    rule_manager = mcp.lifespan_context["rule_manager"]
    rules = rule_manager.list_rules()
    return json.dumps(rules, ensure_ascii=False, indent=2)

@mcp.resource("rules://{rule_name}")
def get_rule_by_name(rule_name: str) -> str:
    """특정 이름의 규칙 조회"""
    rule_manager = mcp.lifespan_context["rule_manager"]
    rule = rule_manager.get_rule(rule_name)
    
    if not rule:
        return json.dumps({"error": f"규칙을 찾을 수 없음: {rule_name}"})
    
    return json.dumps(rule.to_dict(), ensure_ascii=False, indent=2)

@mcp.resource("rules://search/{query}")
def search_rules(query: str) -> str:
    """규칙 검색"""
    rule_manager = mcp.lifespan_context["rule_manager"]
    rules = rule_manager.search_rules(query)
    return json.dumps(rules, ensure_ascii=False, indent=2)

# 도구 엔드포인트

@mcp.tool()
def add_rule(ctx: Context, name: str, description: str, original_code: str, 
             modified_code: str, feedback: str, tags: List[str] = None) -> str:
    """
    새 규칙 추가
    
    Parameters:
    - name: 규칙 이름
    - description: 규칙 설명
    - original_code: 원본 코드
    - modified_code: 수정된 코드
    - feedback: 사용자 피드백
    - tags: 규칙 태그 (선택사항)
    """
    rule_manager = ctx.request_context.lifespan_context["rule_manager"]
    
    # 중복 검사
    if rule_manager.get_rule(name):
        return f"에러: 이미 같은 이름의 규칙이 있습니다: {name}"
    
    # 새 규칙 생성
    rule = Rule(
        name=name,
        description=description,
        original_code=original_code,
        modified_code=modified_code,
        feedback=feedback,
        tags=tags or []
    )
    
    # 규칙 저장
    rule_manager.save_rule(rule)
    
    return f"규칙 추가 성공: {name}"

@mcp.tool()
def update_rule(ctx: Context, name: str, description: str = None, original_code: str = None,
                modified_code: str = None, feedback: str = None, tags: List[str] = None) -> str:
    """
    기존 규칙 업데이트
    
    Parameters:
    - name: 규칙 이름
    - description: 규칙 설명 (선택사항)
    - original_code: 원본 코드 (선택사항)
    - modified_code: 수정된 코드 (선택사항)
    - feedback: 사용자 피드백 (선택사항)
    - tags: 규칙 태그 (선택사항)
    """
    rule_manager = ctx.request_context.lifespan_context["rule_manager"]
    
    # 규칙 존재 확인
    existing_rule = rule_manager.get_rule(name)
    if not existing_rule:
        return f"에러: 규칙을 찾을 수 없음: {name}"
    
    # 제공된 값만 업데이트
    if description is not None:
        existing_rule.description = description
    if original_code is not None:
        existing_rule.original_code = original_code
    if modified_code is not None:
        existing_rule.modified_code = modified_code
    if feedback is not None:
        existing_rule.feedback = feedback
    if tags is not None:
        existing_rule.tags = tags
    
    # 규칙 저장
    rule_manager.save_rule(existing_rule)
    
    return f"규칙 업데이트 성공: {name}"

@mcp.tool()
def delete_rule(ctx: Context, name: str) -> str:
    """
    규칙 삭제
    
    Parameters:
    - name: 삭제할 규칙 이름
    """
    rule_manager = ctx.request_context.lifespan_context["rule_manager"]
    
    if rule_manager.delete_rule(name):
        return f"규칙 삭제 성공: {name}"
    else:
        return f"에러: 규칙 삭제 실패 또는 존재하지 않음: {name}"

@mcp.tool()
def apply_rules_to_code(ctx: Context, code: str, tags: List[str] = None) -> str:
    """
    기존 규칙을 적용하여 코드 수정
    
    Parameters:
    - code: 수정할 코드
    - tags: 적용할 규칙의 태그 (선택사항)
    """
    rule_manager = ctx.request_context.lifespan_context["rule_manager"]
    
    # 태그가 있으면 해당 태그의 규칙만 필터링
    if tags:
        rules = [rule for rule in rule_manager.rules.values() 
                if rule.tags and all(tag in rule.tags for tag in tags)]
    else:
        rules = list(rule_manager.rules.values())
    
    modified_code = code
    applied_rules = []
    
    # 규칙 적용
    for rule in rules:
        if rule.original_code in modified_code:
            modified_code = modified_code.replace(rule.original_code, rule.modified_code)
            applied_rules.append(rule.name)
    
    result = {
        "modified_code": modified_code,
        "applied_rules": applied_rules,
        "total_rules_applied": len(applied_rules)
    }
    
    return json.dumps(result, ensure_ascii=False, indent=2)

@mcp.tool()
def add_code_edit_to_rules(ctx: Context, name: str, description: str, 
                          original_code: str, modified_code: str, 
                          feedback: str = "코드 수정", tags: List[str] = None) -> str:
    """
    코드 수정을 새 규칙으로 추가
    
    Parameters:
    - name: 규칙 이름
    - description: 규칙 설명
    - original_code: 원본 코드
    - modified_code: 수정된 코드
    - feedback: 수정에 대한 피드백 (기본: "코드 수정")
    - tags: 규칙 태그 (선택사항)
    """
    rule_manager = ctx.request_context.lifespan_context["rule_manager"]
    
    # 새 규칙 생성
    rule = Rule(
        name=name,
        description=description,
        original_code=original_code,
        modified_code=modified_code,
        feedback=feedback,
        tags=tags or ["코드 수정"]
    )
    
    # 규칙 저장
    rule_manager.save_rule(rule)
    
    return f"코드 수정 규칙 추가 성공: {name}"

@mcp.tool()
def extract_cursor_rules(ctx: Context, rules_content: str) -> str:
    """
    Cursor Rules 문서 내용에서 규칙 추출
    
    Parameters:
    - rules_content: Cursor Rules 문서 내용
    """
    # 간단한 구현: 문서에서 규칙 이름과 설명 추출
    lines = rules_content.strip().split('\n')
    extracted_rules = []
    
    current_rule = None
    rule_content = []
    
    for line in lines:
        if line.startswith('# ') or line.startswith('## '):
            # 새 규칙 시작, 이전 규칙 저장
            if current_rule and rule_content:
                extracted_rules.append({
                    "name": current_rule,
                    "content": '\n'.join(rule_content)
                })
                rule_content = []
            
            current_rule = line.lstrip('#').strip()
        elif current_rule:
            rule_content.append(line)
    
    # 마지막 규칙 저장
    if current_rule and rule_content:
        extracted_rules.append({
            "name": current_rule,
            "content": '\n'.join(rule_content)
        })
    
    return json.dumps(extracted_rules, ensure_ascii=False, indent=2)

@mcp.prompt()
def rule_creation_strategy() -> str:
    """RLHF를 통한 코드 규칙 생성 전략 정의"""
    return """코드 규칙 생성을 위한 RLHF(Reinforcement Learning from Human Feedback) 전략:

1. 코드 생성 및 피드백 수집:
   - LLM이 사용자 요청에 따라 코드를 생성합니다.
   - 사용자가 코드에 대한 피드백을 제공하거나 직접 수정합니다.
   - 이 피드백과 수정사항을 규칙으로 저장합니다.

2. 패턴 인식:
   - 비슷한 패턴의 피드백이 반복될 경우 그것을 규칙으로 일반화합니다.
   - 태그를 사용하여 규칙을 카테고리별로 분류합니다.

3. 규칙 적용:
   - 이후 코드 생성 시 저장된 규칙을 참조하여 사용자 선호도를 반영합니다.
   - 코드 생성 전 관련 규칙을 조회하고 적용합니다.

4. 규칙 최적화:
   - 적용된 규칙의 효과를 평가하고 필요한 경우 수정합니다.
   - 더 이상 유용하지 않은 규칙은 삭제하거나 업데이트합니다.

규칙 생성 시 고려사항:
- 규칙은 구체적이고 명확해야 합니다.
- 코드 스타일, 네이밍 컨벤션, 아키텍처 패턴 등 다양한 측면을 포함할 수 있습니다.
- 규칙 간 충돌이 없도록 주의해야 합니다.
- 규칙은 항상 현재 프로젝트의 컨텍스트에 맞게 적용해야 합니다.
"""

def main():
    """MCP 서버 실행"""
    mcp.run()

if __name__ == "__main__":
    main()
