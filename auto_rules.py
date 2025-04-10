from mcp.server.fastmcp import FastMCP, Context
import json
import os
import difflib
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Tuple
import logging
from datetime import datetime
import re
import uuid

# 로깅 설정
LOG_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = LOG_DIR / "autorules.log"

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AutoRules")

# 파일 핸들러 추가
file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

logger.info(f"=== AutoRules 서버 시작 - 로그 파일: {LOG_FILE} ===")
logger.info(f"현재 작업 디렉토리: {os.getcwd()}")
logger.info(f"스크립트 위치: {os.path.abspath(__file__)}")

# 환경 변수 디버깅 로그
logger.info("====== 환경 변수 확인 ======")
logger.info(f"AUTO_RULES_ROOT: {os.environ.get('AUTO_RULES_ROOT', '설정되지 않음')}")
logger.info("===========================")

# MCP 서버 생성
mcp = FastMCP(
    "AutoRules",
    description="LLM 코드 생성을 위한 자동 규칙 시스템",
)

# 설정 및 상수
CURSOR_RULES_DIR = ".cursor/rules"  # Cursor 규칙 디렉토리
CURSOR_RULES_FILE = "auto_rules.mdc"  # Cursor 규칙 파일명
AUTO_RULES_ROOT_ENV = "AUTO_RULES_ROOT"  # 환경 변수명

# 환경 변수 확인
auto_rules_root = os.environ.get(AUTO_RULES_ROOT_ENV)

# 애플리케이션 기본 경로
if not auto_rules_root:
    logger.warning(f"환경 변수 {AUTO_RULES_ROOT_ENV}가 설정되지 않았습니다. 현재 디렉토리를 사용합니다.")
    auto_rules_root = os.getcwd()
    os.environ[AUTO_RULES_ROOT_ENV] = auto_rules_root
    logger.info(f"{AUTO_RULES_ROOT_ENV} 환경 변수를 {auto_rules_root}로 설정했습니다.")

RULES_DIR = Path(auto_rules_root) / ".autorules"

# Rules 저장 경로
CURSOR_RULES_PATH = Path(auto_rules_root) / CURSOR_RULES_DIR / CURSOR_RULES_FILE

# 규칙을 MDC 형식으로 변환하는 함수
def convert_rules_to_mdc(rules: List[Dict[str, Any]]) -> str:
    """규칙 리스트를 MDC 포맷으로 변환"""
    mdc_content = f"# 자동 규칙 모음\n\n"
    
    for rule in rules:
        rule_name = rule.get("name", "")
        rule_description = rule.get("description", "")
        rule_original_code = rule.get("original_code", "")
        rule_modified_code = rule.get("modified_code", "")
        
        # 규칙 내용 추가
        mdc_content += f"## {rule_name}\n\n"
        mdc_content += f"{rule_description}\n\n"
        
        # 원본 코드와 수정된 코드 추가
        mdc_content += "### 원본 코드\n\n"
        mdc_content += f"```\n{rule_original_code}\n```\n\n"
        mdc_content += "### 수정된 코드\n\n"
        mdc_content += f"```\n{rule_modified_code}\n```\n\n"
    
    return mdc_content

# MDC 형식을 JSON 규칙으로 변환하는 함수
def convert_mdc_to_rules(mdc_content: str) -> List[Dict[str, Any]]:
    """MDC 포맷에서 규칙 리스트로 변환"""
    rules = []
    
    if not mdc_content or mdc_content.strip() == "":
        return rules
    
    # 규칙 섹션 분리 (## 로 시작하는 부분)
    rule_sections = re.split(r'(?=^## )', mdc_content, flags=re.MULTILINE)
    
    # 첫 번째 섹션은 일반적으로 문서 제목이므로 건너뜀
    for section in rule_sections[1:]:
        if not section.strip():
            continue
        
        lines = section.strip().split('\n')
        if not lines:
            continue
        
        # 규칙 이름 추출
        rule_name = lines[0].replace('## ', '').strip()
        if not rule_name:
            continue
        
        # 초기 규칙 데이터 생성
        rule_data = {
            "id": f"{rule_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "name": rule_name,
            "description": "",
            "original_code": "",
            "modified_code": "",
            "feedback": "MDC에서 추출",
            "tags": [],
            "created_at": datetime.now().isoformat()
        }
        
        # 설명 부분 추출 (## 이름과 ### 원본 코드 사이)
        description_lines = []
        i = 1
        while i < len(lines) and not lines[i].startswith('### 원본 코드'):
            description_lines.append(lines[i])
            i += 1
        rule_data["description"] = '\n'.join(description_lines).strip()
        
        # 원본 코드 추출
        if i < len(lines) and lines[i].startswith('### 원본 코드'):
            i += 1  # ### 원본 코드 라인 건너뜀
            code_lines = []
            # ``` 찾기
            while i < len(lines) and not lines[i].strip().startswith('```'):
                i += 1
            i += 1  # ``` 라인 건너뜀
            
            # 원본 코드 수집
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            rule_data["original_code"] = '\n'.join(code_lines)
        
        # 수정된 코드 추출
        i += 1  # ``` 라인 건너뜀
        while i < len(lines) and not lines[i].startswith('### 수정된 코드'):
            i += 1
        
        if i < len(lines) and lines[i].startswith('### 수정된 코드'):
            i += 1  # ### 수정된 코드 라인 건너뜀
            code_lines = []
            # ``` 찾기
            while i < len(lines) and not lines[i].strip().startswith('```'):
                i += 1
            i += 1  # ``` 라인 건너뜀
            
            # 수정된 코드 수집
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            rule_data["modified_code"] = '\n'.join(code_lines)
        
        # 유효한 규칙이면 추가
        if rule_data["name"] and (rule_data["original_code"] or rule_data["modified_code"]):
            rules.append(rule_data)
    
    return rules

# 규칙을 MDC 파일로 저장하는 함수
def save_rules_to_mdc(rules: List[Dict[str, Any]]) -> bool:
    """규칙들을 MDC 파일에 저장하기"""
    try:
        # 환경 변수에서 루트 경로 가져오기
        root_path = os.environ.get(AUTO_RULES_ROOT_ENV)
        if not root_path:
            logger.error(f"{AUTO_RULES_ROOT_ENV} 환경 변수가 설정되지 않았습니다.")
            return False
        
        # 커서 규칙 디렉토리 경로 생성
        cursor_rules_dir = os.path.join(root_path, CURSOR_RULES_DIR)
        
        # 디렉토리가 없으면 생성
        os.makedirs(cursor_rules_dir, exist_ok=True)
        
        # MDC 파일 경로
        cursor_rules_path = os.path.join(cursor_rules_dir, CURSOR_RULES_FILE)
        
        # 규칙을 MDC 형식으로 변환
        mdc_content = convert_rules_to_mdc(rules)
        
        # MDC 파일에 저장
        with open(cursor_rules_path, 'w', encoding='utf-8') as f:
            f.write(mdc_content)
        
        logger.info(f"{len(rules)}개 규칙이 성공적으로 MDC 파일에 저장되었습니다: {cursor_rules_path}")
        return True
    except Exception as e:
        logger.error(f"MDC 파일 저장 중 오류: {e}")
        return False

def load_all_rules() -> List[Dict[str, Any]]:
    """모든 규칙 불러오기"""
    # 환경 변수 확인
    root_path = os.environ.get(AUTO_RULES_ROOT_ENV)
    if not root_path:
        logger.warning(f"{AUTO_RULES_ROOT_ENV} 환경 변수가 설정되지 않았습니다.")
        return []
    
    # Cursor 규칙 파일 경로
    cursor_rules_dir = os.path.join(root_path, CURSOR_RULES_DIR)
    cursor_rules_path = os.path.join(cursor_rules_dir, CURSOR_RULES_FILE)
    
    # MDC 파일 존재 확인
    if not os.path.exists(cursor_rules_path):
        logger.info(f"MDC 파일이 존재하지 않습니다: {cursor_rules_path}")
        return []
    
    try:
        # MDC 파일에서 규칙 불러오기
        with open(cursor_rules_path, 'r', encoding='utf-8') as f:
            mdc_content = f.read()
        
        # MDC 콘텐츠에서 규칙 추출
        rules = convert_mdc_to_rules(mdc_content)
        logger.info(f"{len(rules)}개 규칙이 MDC 파일에서 로드되었습니다.")
        return rules
    except Exception as e:
        logger.error(f"MDC 파일에서 규칙 로드 중 오류: {e}")
        return []

def load_rule(rule_name: str) -> Optional[Dict[str, Any]]:
    """이름으로 규칙 불러오기"""
    rules = load_all_rules()
    
    for rule in rules:
        if rule.get("name") == rule_name:
            return rule
    
    return None

def add_rule(rule: Dict[str, Any]) -> Tuple[bool, str]:
    """새 규칙 추가하기"""
    try:
        # 환경 변수에서 루트 경로 가져오기
        root_path = os.environ.get(AUTO_RULES_ROOT_ENV)
        if not root_path:
            return False, f"{AUTO_RULES_ROOT_ENV} 환경 변수가 설정되지 않았습니다."
        
        # 규칙 이름 확인
        rule_name = rule.get("name")
        if not rule_name:
            return False, "규칙 이름이 필요합니다."
        
        # 현재 규칙 불러오기
        current_rules = load_all_rules()
        
        # 이미 존재하는 규칙인지 확인
        for existing_rule in current_rules:
            if existing_rule.get("name") == rule_name:
                return False, f"'{rule_name}' 규칙이 이미 존재합니다."
        
        # 규칙 ID 생성 및 생성 시간 추가
        rule["id"] = str(uuid.uuid4())
        rule["created_at"] = datetime.now().isoformat()
        
        # 규칙 추가
        current_rules.append(rule)
        
        # MDC 파일에 저장
        if save_rules_to_mdc(current_rules):
            return True, f"규칙 '{rule_name}'이(가) 추가되었습니다."
        else:
            return False, "MDC 파일 저장 중 오류가 발생했습니다."
    except Exception as e:
        return False, f"규칙 추가 중 오류 발생: {e}"

def update_rule(rule: Dict[str, Any]) -> Tuple[bool, str]:
    """기존 규칙 업데이트"""
    try:
        # 환경 변수에서 루트 경로 가져오기
        root_path = os.environ.get(AUTO_RULES_ROOT_ENV)
        if not root_path:
            return False, f"{AUTO_RULES_ROOT_ENV} 환경 변수가 설정되지 않았습니다."
        
        # 규칙 이름 또는 ID 확인
        rule_name = rule.get("name")
        rule_id = rule.get("id")
        
        if not rule_name and not rule_id:
            return False, "규칙 업데이트를 위해 이름 또는 ID가 필요합니다."
        
        # 현재 규칙 불러오기
        current_rules = load_all_rules()
        updated = False
        
        # 규칙 찾아서 업데이트
        for i, existing_rule in enumerate(current_rules):
            if (rule_id and existing_rule.get("id") == rule_id) or \
               (rule_name and existing_rule.get("name") == rule_name):
                # 원래 ID와 생성 시간 유지
                original_id = existing_rule.get("id")
                original_created_at = existing_rule.get("created_at")
                
                # ID와 생성 시간이 없는 경우 새로 생성
                if not original_id:
                    original_id = str(uuid.uuid4())
                if not original_created_at:
                    original_created_at = datetime.now().isoformat()
                
                # 업데이트 시간 추가
                rule["id"] = original_id
                rule["created_at"] = original_created_at
                rule["updated_at"] = datetime.now().isoformat()
                
                # 규칙 업데이트
                current_rules[i] = rule
                updated = True
                break
        
        if not updated:
            return False, f"규칙 '{rule_name or rule_id}'을(를) 찾을 수 없습니다."
        
        # MDC 파일에 저장
        if save_rules_to_mdc(current_rules):
            return True, f"규칙 '{rule_name or rule_id}'이(가) 업데이트되었습니다."
        else:
            return False, "MDC 파일 저장 중 오류가 발생했습니다."
    except Exception as e:
        return False, f"규칙 업데이트 중 오류 발생: {e}"

def delete_rule(rule_name: str) -> Tuple[bool, str]:
    """규칙 삭제하기"""
    try:
        # 환경 변수에서 루트 경로 가져오기
        root_path = os.environ.get(AUTO_RULES_ROOT_ENV)
        if not root_path:
            return False, f"{AUTO_RULES_ROOT_ENV} 환경 변수가 설정되지 않았습니다."
        
        # 현재 규칙 불러오기
        current_rules = load_all_rules()
        original_count = len(current_rules)
        
        # 해당 이름의 규칙 필터링
        filtered_rules = [rule for rule in current_rules if rule.get("name") != rule_name]
        
        # 삭제된 규칙이 있는지 확인
        if len(filtered_rules) == original_count:
            return False, f"규칙 '{rule_name}'을(를) 찾을 수 없습니다."
        
        # MDC 파일에 저장
        if save_rules_to_mdc(filtered_rules):
            return True, f"규칙 '{rule_name}'이(가) 삭제되었습니다."
        else:
            return False, "MDC 파일 저장 중 오류가 발생했습니다."
    except Exception as e:
        return False, f"규칙 삭제 중 오류 발생: {e}"

# 태그로 규칙 불러오기
def load_rules_by_tags(tags: List[str]) -> List[Dict[str, Any]]:
    """태그로 규칙 필터링"""
    all_rules = load_all_rules()
    if not tags:
        return all_rules
    
    filtered_rules = []
    for rule in all_rules:
        rule_tags = rule.get("tags", [])
        if any(tag in rule_tags for tag in tags):
            filtered_rules.append(rule)
    
    return filtered_rules

# MDC 문서에서 규칙 추출
def extract_rules_from_mdc(mdc_content: str) -> List[Dict[str, Any]]:
    """MDC 문서 콘텐츠에서 규칙 추출"""
    return convert_mdc_to_rules(mdc_content)

# MCP 도구: 새 규칙 추가
@mcp.tool()
def mcp_auto_rules_add_rule(
    ctx: Context,
    name: str,
    description: str,
    original_code: str,
    modified_code: str,
    feedback: str,
    tags: Optional[List[str]] = None,
) -> str:
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
    # tags가 None이면 빈 리스트로 설정
    tags_list = [] if tags is None else tags
    
    # 규칙 데이터 생성
    rule_data = {
        "name": name,
        "description": description,
        "original_code": original_code,
        "modified_code": modified_code,
        "feedback": feedback,
        "tags": tags_list
    }
    
    # 규칙 추가 함수 호출
    success, message = add_rule(rule_data)
    
    if success:
        # 규칙이 추가된 경우 성공 메시지 반환
        current_rules = load_all_rules()
        return f"{message} 저장 위치: {CURSOR_RULES_DIR}/{CURSOR_RULES_FILE} (총 {len(current_rules)}개 규칙)"
    else:
        # 오류 발생 시 오류 메시지 반환
        logger.error(message)
        return f"규칙 추가 실패: {message}"

# MCP 도구: 코드 수정을 새 규칙으로 추가
@mcp.tool()
def mcp_auto_rules_add_code_edit_to_rules(
    ctx: Context,
    name: str,
    description: str,
    original_code: str,
    modified_code: str,
    feedback: str = "코드 수정",
    tags: Optional[List[str]] = None,
) -> str:
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
    return mcp_auto_rules_add_rule(
        ctx, name, description, original_code, modified_code, feedback, tags
    )

# MCP 도구: Cursor Rules 문서에서 규칙 추출
@mcp.tool()
def mcp_auto_rules_extract_cursor_rules(
    ctx: Context,
    rules_content: str,
) -> str:
    """
    Cursor Rules 문서 내용에서 규칙 추출
    
    Parameters:
    - rules_content: Cursor Rules 문서 내용
    """
    try:
        # 규칙 추출
        rules = extract_rules_from_mdc(rules_content)
        
        if not rules:
            return "추출된 규칙이 없습니다."
        
        # 현재 규칙 로드
        current_rules = load_all_rules()
        
        # 새 규칙 수와 충돌 수 계산을 위한 변수
        new_rules_count = 0
        conflicts_count = 0
        
        # 현재 규칙 이름 목록
        current_rule_names = [rule.get("name") for rule in current_rules if rule.get("name")]
        
        # 새 규칙 추가
        for rule in rules:
            rule_name = rule.get("name")
            
            if not rule_name:
                continue
            
            if rule_name in current_rule_names:
                conflicts_count += 1
                continue
            
            # 규칙 추가
            success, _ = add_rule(rule)
            if success:
                new_rules_count += 1
        
        return f"{len(rules)}개 규칙이 추출되었습니다. {new_rules_count}개 새 규칙이 추가되었습니다. {conflicts_count}개 규칙은 이미 존재합니다."
    except Exception as e:
        logger.error(f"규칙 추출 중 오류: {e}")
        return f"규칙 추출 중 오류 발생: {e}"

# MCP 도구: 규칙 삭제
@mcp.tool()
def mcp_auto_rules_delete_rule(
    ctx: Context,
    rule_name: str,
) -> str:
    """
    규칙 삭제
    
    Parameters:
    - rule_name: 삭제할 규칙 이름
    """
    success, message = delete_rule(rule_name)
    
    if success:
        current_rules = load_all_rules()
        return f"{message} 총 {len(current_rules)}개 규칙이 남아있습니다."
    else:
        return f"규칙 삭제 실패: {message}"

def main():
    """MCP 서버 실행 함수"""
    try:
        logger.info("AutoRules 서버 시작 중...")
        logger.info(f"시작 시간: {datetime.now()}")
        
        # 환경 변수 AUTO_RULES_ROOT 다시 확인
        if not auto_rules_root:
            error_msg = "환경 변수 AUTO_RULES_ROOT가 설정되지 않았습니다. MCP 서버를 종료합니다."
            logger.error(error_msg)
            print(error_msg)
            import sys
            sys.exit(1)
        
        # Cursor Rules 디렉토리 확인 및 생성
        cursor_rules_dir = Path(auto_rules_root) / CURSOR_RULES_DIR
        if not cursor_rules_dir.exists():
            try:
                cursor_rules_dir.mkdir(exist_ok=True, parents=True)
                logger.info(f"Cursor Rules directory created at: {cursor_rules_dir}")
            except Exception as e:
                error_msg = f"Cursor Rules 디렉토리 생성 실패: {e}, MCP 서버를 종료합니다."
                logger.error(error_msg)
                print(error_msg)
                import sys
                sys.exit(1)
        
        # 규칙 로드
        rules = load_all_rules()
        logger.info(f"{len(rules)}개의 규칙 로드됨")
        
        # MDC 파일 생성 또는 업데이트
        mdc_file_path = cursor_rules_dir / CURSOR_RULES_FILE
        if not mdc_file_path.exists() or rules:
            logger.info(f"Creating/Updating MDC file: {mdc_file_path}")
            save_rules_to_mdc(rules)
        
        # Cursor Rules 문서에서 자동 규칙 로드 (필요한 경우)
        try:
            cursor_rules_path = Path(".cursor/rules/autorules.mdc")
            if cursor_rules_path.exists():
                logger.info(f"Found Cursor Rules at {cursor_rules_path}")
                with open(cursor_rules_path, "r", encoding="utf-8") as f:
                    rules_content = f.read()
                    logger.info("Extracting rules from Cursor Rules document")
                    ctx = Context()  # 임시 Context 객체 생성
                    result = extract_cursor_rules(ctx, rules_content)
                    logger.info(f"Extraction result: {result}")
        except Exception as e:
            logger.error(f"Error loading Cursor Rules: {e}")
        
        # MCP 서버 실행
        logger.info("Starting MCP server...")
        logger.info(f"Using AUTO_RULES_ROOT: {auto_rules_root}")
        logger.info(f"Cursor Rules directory: {cursor_rules_dir}")
        logger.info(f"Cursor Rules file: {CURSOR_RULES_PATH}")
        mcp.run()
    except Exception as e:
        error_msg = f"Error starting AutoRules server: {e}, MCP 서버를 종료합니다."
        logger.error(error_msg)
        print(error_msg)
        import sys
        sys.exit(1)

if __name__ == "__main__":
    main()
