"""
Tools: 인터페이스 신청 (Interface Request)

신청 종류: EAI, EIGW, MCG
신청 흐름: step1(기초정보) → regTemp(상세정보) → step3(최종 승인자)
           ※ 모두 임시저장 POST 요청

1. get_interface_request_codes              → GET  /api/bizcomm/cccd/selectbox?useYn=Y
2. create_interface_request_step1           → POST /api/ifreq/reqInfo/step1
3. search_chargr                            → GET  /api/bizcomm/chrgr
4. save_eai_interface_request_regtemp       → POST /api/eai/regTemp
"""
from datetime import date, timedelta
from collections import defaultdict
from typing import Literal
from mcp_server.app import mcp
from mcp_server.tools.auth import get_session


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼: EAI 코드값 → 코드명 매핑 (API 페이로드의 *Nm 필드 자동 파생)
# ─────────────────────────────────────────────────────────────────────────────
_EAI_CODE_NAMES: dict[str, dict[str, str]] = {
    "IF_TYP_CD":      {"1": "MQ", "2": "FILE"},
    "ROUND_TYP_CD":   {"1": "단방향", "2": "양방향"},
    "SYNC_TYP_CD":    {"1": "비동기 (Async)", "2": "동기 (Sync)"},
    "DRCTN_CD":       {"1": "송신  --> 수신", "2": "수신  --> 송신"},
    "RCV_OP_CD":      {"1": "실시간", "2": "배치", "3": "실시간 / 배치"},
    "FILE_IF_TYP_CD": {"1": "file_put (송신에서 보내주기)", "2": "file_get (수신에서 가져가기)"},
    "SVR_TYP_CD":     {"DEV": "개발기", "PRD": "운영기", "STG": "스테이징"},
}

def _code_name(cd_type: str, cd_val: str) -> str:
    """코드값에 해당하는 코드명을 반환. 없으면 빈 문자열."""
    return _EAI_CODE_NAMES.get(cd_type, {}).get(cd_val, "")


# ─────────────────────────────────────────────────────────────────────────────
# 1. 코드값 전체 조회
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_interface_request_codes() -> dict:
    """
    인터페이스 신청서 작성에 필요한 모든 선택 가능한 코드값(selectbox 옵션)을 한 번에 조회합니다.

    신청서 작성 전 반드시 이 툴을 먼저 호출하여 유효한 코드 ID와 코드명을 확인하세요.
    응답의 각 항목에서 'code' 값이 API에 실제로 전달되는 파라미터 값이고,
    'name' 값이 화면에 표시되는 이름입니다.

    코드 분류(opClCd):
        - COMM : 공통 코드 (SVR_TYP_CD 서버유형, PROC_ST 처리상태 등)
        - EAI  : EAI 전용 코드 (IF_TYP_CD 연동방식, ROUND_TYP_CD 단/양방향, SYNC_TYP_CD 동기여부 등)
        - EIGW : EIGW 전용 코드 (TRAN_TYP_CD 전송유형, SR_FLAG 송/수신 구분 등)
        - MCG  : MCG 전용 코드 (CHNL_TYP 채널유형, LNK_MTHD 연결방식 등)

    Returns:
        codes (dict): opClCd → cdId → list of {code, name} 구조
            예시:
            {
              "EAI": {
                "IF_TYP_CD": [{"code": "1", "name": "MQ"}, {"code": "2", "name": "FILE"}],
                "ROUND_TYP_CD": [{"code": "1", "name": "단방향"}, {"code": "2", "name": "양방향"}],
                ...
              },
              "COMM": { ... },
              "EIGW": { ... },
              "MCG": { ... }
            }
        total_count (int): 전체 코드 항목 수
    """
    session = await get_session()

    resp = await session.get("/api/bizcomm/cccd/selectbox", params={"useYn": "Y"})
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "코드값 조회 실패")}

    items: list = body.get("rstData", {}).get("ccCdLst", [])

    # opClCd → cdId → [{code, name}, ...]  형태로 그룹핑
    grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for item in items:
        op_cl = item.get("opClCd", "")
        cd_id = item.get("cdId", "")
        grouped[op_cl][cd_id].append({
            "code": item.get("cdDtlId"),
            "name": item.get("cdNm"),
        })

    # defaultdict → 일반 dict 변환
    result = {op: dict(cds) for op, cds in grouped.items()}

    return {
        "codes": result,
        "total_count": len(items),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. 인터페이스 신청 Step1 (기초정보 임시저장)
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def create_interface_request_step1(
    if_kind: Literal["EAI", "EIGW", "MCG"],
    req_title: str,
    req_purp: str,
    dvlp_aply_req_dt: str,
    oper_aply_req_dt: str,
    open_req_dt: str,
    req_rmk: str = "",
) -> dict:
    """
    인터페이스 신청서의 Step1 기초정보를 임시저장합니다.

    반드시 신청 흐름의 첫 번째 단계로 호출해야 합니다.
    성공하면 이후 regTemp/step3 단계에서 사용할 req_num(요청서 고유번호)을 반환합니다.

    날짜 형식: YYYY-MM-DD (예: 2026-03-25)
    날짜 제약: dvlp_aply_req_dt(개발 반영 예정일)는 오늘로부터 반드시 7일 이후여야 합니다.

    Args:
        if_kind:           신청 종류. "EAI" | "EIGW" | "MCG" 중 하나
        req_title:         요청 제목
        req_purp:          신청 목적
        dvlp_aply_req_dt:  개발 반영 예정일 (YYYY-MM-DD, 오늘+7일 이후)
        oper_aply_req_dt:  운영 반영 예정일 (YYYY-MM-DD)
        open_req_dt:       실 오픈일 (YYYY-MM-DD)
        req_rmk:           비고 (선택)

    Returns:
        req_num (str): 발급된 요청서 고유번호 (예: "260310-0004") — 이후 단계에서 필수
        req_title (str): 저장된 제목
        req_purp (str): 저장된 신청 목적
        dvlp_aply_req_dt (str): 개발 반영 예정일 (YYYYMMDD)
        oper_aply_req_dt (str): 운영 반영 예정일 (YYYYMMDD)
        open_req_dt (str): 실 오픈일 (YYYYMMDD)
        req_rmk (str): 비고
        if_kind (str): 신청 종류
        proc_st (str): 처리상태 (0=임시저장)
    """
    # ── 날짜 검증: dvlp_aply_req_dt는 오늘+7일 이후여야 함 ──────────────────
    today = date.today()
    min_dvlp_dt = today + timedelta(days=7)

    try:
        dvlp_dt_parsed = date.fromisoformat(dvlp_aply_req_dt)
    except ValueError:
        return {"error": f"dvlp_aply_req_dt 날짜 형식이 잘못되었습니다: '{dvlp_aply_req_dt}'. YYYY-MM-DD 형식으로 입력하세요."}

    if dvlp_dt_parsed < min_dvlp_dt:
        return {
            "error": (
                f"개발 반영 예정일(dvlp_aply_req_dt)은 오늘({today})로부터 7일 이후인 "
                f"{min_dvlp_dt} 이후여야 합니다. 입력값: {dvlp_aply_req_dt}"
            )
        }

    # ── API 호출 ─────────────────────────────────────────────────────────────
    session = await get_session()

    payload = {
        "reqNum":         "",
        "reqTitle":       req_title,
        "reqPurp":        req_purp,
        "reqrId":         "",
        "reqrM":          "",
        "procSt":         "0",
        "dvlpAplyReqDt":  dvlp_aply_req_dt,
        "operAplyReqDt":  oper_aply_req_dt,
        "openReqDt":      open_req_dt,
        "reqDtm":         "",
        "reqRmk":         req_rmk,
        "delYn":          "",
        "ifKind":         if_kind,
    }

    resp = await session.post("/api/ifreq/reqInfo/step1", json=payload)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "step1 임시저장 실패")}

    info: dict = body.get("rstData", {}).get("reqInfo", {})

    return {
        "req_num":          info.get("reqNum"),
        "req_title":        info.get("reqTitle"),
        "req_purp":         info.get("reqPurp"),
        "dvlp_aply_req_dt": info.get("dvlpAplyReqDt"),
        "oper_aply_req_dt": info.get("operAplyReqDt"),
        "open_req_dt":      info.get("openReqDt"),
        "req_rmk":          info.get("reqRmk"),
        "if_kind":          info.get("ifKind"),
        "proc_st":          info.get("procSt"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. 담당자 검색
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def search_chargr(
    han_nm: str,
    size: int = 5,
) -> dict:
    """
    이름으로 담당자를 검색합니다. 인터페이스 신청 시 운영담당자 / 업무담당 매니저 정보를 확인할 때 사용합니다.

    검색 결과가 2명 이상이면 동명이인이 있으므로 사용자에게 어떤 담당자인지 다시 확인을 받아야 합니다.
    담당자의 user_id, han_nm, org_nm 값을 save_eai_interface_request_regtemp 호출 시 사용합니다.

    Args:
        han_nm: 담당자 한글 이름 (부분 일치 검색, 예: "홍길동")
        size:   최대 반환 수 (기본 5)

    Returns:
        total_count (int): 검색된 담당자 수
        chargr_list (list): 담당자 목록
            - user_id (str): 사용자 ID (신청서 입력값으로 사용)
            - han_nm (str): 한글 이름
            - org_nm (str): 소속 조직명 (신청서 입력값으로 사용)
            - user_gb_nm (str): 소속 구분 (예: SKT, SK(주) C&C)
            - ofc_lvl_nm (str): 직급
        needs_confirmation (bool): True이면 동명이인이 있으므로 사용자 확인 필요
    """
    session = await get_session()

    resp = await session.get(
        "/api/bizcomm/chrgr",
        params={
            "userId": "", "hanNm": han_nm, "delYn": "N",
            "searchType": "", "pageNo": 1, "pageCount": 0, "size": size,
        },
    )
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "담당자 검색 실패")}

    items: list = body.get("rstData", {}).get("chrgrInfo", [])

    chargr_list = [
        {
            "user_id":    c.get("userId"),
            "han_nm":     c.get("hanNm"),
            "org_nm":     c.get("orgNm"),
            "user_gb_nm": c.get("userGbNm"),
            "ofc_lvl_nm": c.get("ofcLvlNm"),
        }
        for c in items
    ]

    return {
        "total_count":        len(chargr_list),
        "chargr_list":        chargr_list,
        "needs_confirmation": len(chargr_list) > 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. EAI 인터페이스 신청 regTemp (상세정보 임시저장)
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def save_eai_interface_request_regtemp(
    req_num: str,
    svr_list: list[dict],
    if_list: list[dict],
) -> dict:
    """
    EAI 인터페이스 신청서의 송/수신 서버 정보와 인터페이스 상세정보를 임시저장합니다.
    반드시 create_interface_request_step1 호출 후 획득한 req_num을 사용해야 합니다.

    ──────────────────────────────────────────────────────────
    [svr_list] 서버 목록 (송신/수신 각각 1개 이상)
    ──────────────────────────────────────────────────────────
    각 항목 구조:
        snd_rcv_cl  (str, 필수): 송수신 구분 - "S"(송신) 또는 "R"(수신)
        svr_typ_cd  (str, 필수): 서버 유형 코드 - "DEV"(개발기) | "STG"(스테이징) | "PRD"(운영기)
        sys_nm      (str, 필수): 시스템명
        host_nm     (str, 필수): Hostname
        v_ip        (str, 필수): VIP / 대표 IP
        nat_ip      (str, 선택): NAT IP
        etc_ip      (str, 선택): 추가 IP
        os_nm       (str, 권장): OS 이름
        company     (str, 권장): 담당 회사명

    ──────────────────────────────────────────────────────────
    [if_list] 인터페이스 목록 (1개 이상)
    ──────────────────────────────────────────────────────────
    공통 필수 필드:
        eai_if_nm_kor   (str): 인터페이스명 (한글)
        eai_if_nm_eng   (str): 인터페이스명 (영문)
        if_desc         (str): 연동 목적
        drctn_cd        (str): 연동 방향 - "1"(송신→수신) | "2"(수신→송신)
        if_typ_cd       (str): 연동 방식 - "1"(MQ) | "2"(FILE)
        rcv_op_cd       (str): 수신전문처리주기 - "1"(실시간) | "2"(배치) | "3"(실시간/배치)
        svc_impt        (str): 장애 영향도
        snd_mid         (str): 송신 MID
        rcv_mid         (str): 수신 MID
        snd_chrgr_id1      (str): 송신 운영담당자 userId (search_chargr로 조회)
        snd_chrgr_nm1      (str): 송신 운영담당자 한글명
        snd_chrgr_org_nm1  (str): 송신 운영담당자 소속
        snd_chrgr_mngr_id      (str): 송신 업무담당 매니저 userId
        snd_chrgr_mngr_nm      (str): 송신 업무담당 매니저 한글명
        snd_chrgr_mngr_org_nm  (str): 송신 업무담당 매니저 소속
        rcv_chrgr_id1      (str): 수신 운영담당자 userId
        rcv_chrgr_nm1      (str): 수신 운영담당자 한글명
        rcv_chrgr_org_nm1  (str): 수신 운영담당자 소속
        rcv_chrgr_mngr_id      (str): 수신 업무담당 매니저 userId
        rcv_chrgr_mngr_nm      (str): 수신 업무담당 매니저 한글명
        rcv_chrgr_mngr_org_nm  (str): 수신 업무담당 매니저 소속

    공통 선택 필드:
        rcv_tr          (str): 수신TR명 (SWING 시스템일 경우에만 입력)
        eai_rmk         (str): 기타 요청사항
        snd_chrgr_id2   (str): 송신 운영담당자2 userId (없으면 생략)
        snd_chrgr_nm2   (str): 송신 운영담당자2 한글명
        rcv_chrgr_id2   (str): 수신 운영담당자2 userId
        rcv_chrgr_nm2   (str): 수신 운영담당자2 한글명

    MQ(if_typ_cd="1") 추가 필수 필드:
        round_typ_cd    (str): 단/양방향 - "1"(단방향) | "2"(양방향)
        sync_typ_cd     (str): 요청처리방식 - "1"(비동기) | "2"(동기)  ← 양방향일 때만 필수

    FILE(if_typ_cd="2") 추가 필수 필드:
        file_if_typ_cd  (str): 파일연동방식 - "1"(file_put 송신에서보내주기) | "2"(file_get 수신에서가져가기)
        snd_dir         (str): 송신 디렉토리 경로
        rcv_dir         (str): 수신 디렉토리 경로

    FILE 선택 필드:
        rcv_sh_nm       (str): 수신 실행 Shell 이름
        file_op_code    (str): OP code

    Args:
        req_num:  step1에서 발급된 요청서 고유번호 (예: "260310-0004")
        svr_list: 서버 목록 (dict 리스트, 위 구조 참고)
        if_list:  인터페이스 목록 (dict 리스트, 위 구조 참고)

    Returns:
        success (bool): 저장 성공 여부
        message (str): 처리 결과 메시지
        validation_errors (list): 입력 검증 오류 목록 (있을 경우)
    """
    # ── 입력 검증 ────────────────────────────────────────────────────────────
    errors: list[str] = []

    # svr_list 검증
    for idx, svr in enumerate(svr_list):
        prefix = f"svr_list[{idx}]"
        if svr.get("snd_rcv_cl") not in ("S", "R"):
            errors.append(f"{prefix}.snd_rcv_cl: 'S'(송신) 또는 'R'(수신) 이어야 합니다.")
        if svr.get("svr_typ_cd") not in ("DEV", "STG", "PRD"):
            errors.append(f"{prefix}.svr_typ_cd: 'DEV' | 'STG' | 'PRD' 중 하나여야 합니다.")
        for field in ("sys_nm", "host_nm", "v_ip"):
            if not svr.get(field):
                errors.append(f"{prefix}.{field}: 필수 입력값입니다.")

    # if_list 검증
    COMMON_REQUIRED = (
        "eai_if_nm_kor", "eai_if_nm_eng", "if_desc", "drctn_cd", "if_typ_cd",
        "rcv_op_cd", "svc_impt",
        "snd_mid", "rcv_mid",
        "snd_chrgr_id1", "snd_chrgr_nm1", "snd_chrgr_org_nm1",
        "snd_chrgr_mngr_id", "snd_chrgr_mngr_nm", "snd_chrgr_mngr_org_nm",
        "rcv_chrgr_id1", "rcv_chrgr_nm1", "rcv_chrgr_org_nm1",
        "rcv_chrgr_mngr_id", "rcv_chrgr_mngr_nm", "rcv_chrgr_mngr_org_nm",
    )
    for idx, ifc in enumerate(if_list):
        prefix = f"if_list[{idx}]"
        for field in COMMON_REQUIRED:
            if not ifc.get(field):
                errors.append(f"{prefix}.{field}: 필수 입력값입니다.")

        if_typ = ifc.get("if_typ_cd", "")
        if if_typ == "1":   # MQ
            if not ifc.get("round_typ_cd"):
                errors.append(f"{prefix}.round_typ_cd: MQ 연동 시 필수입니다.")
            elif ifc.get("round_typ_cd") == "2" and not ifc.get("sync_typ_cd"):
                errors.append(f"{prefix}.sync_typ_cd: 양방향(round_typ_cd='2') 시 필수입니다.")
        elif if_typ == "2":  # FILE
            for field in ("file_if_typ_cd", "snd_dir", "rcv_dir"):
                if not ifc.get(field):
                    errors.append(f"{prefix}.{field}: FILE 연동 시 필수입니다.")
        elif if_typ:
            errors.append(f"{prefix}.if_typ_cd: '1'(MQ) 또는 '2'(FILE) 이어야 합니다.")

    if errors:
        return {"success": False, "message": "입력 검증 실패", "validation_errors": errors}

    # ── 페이로드 구성 ─────────────────────────────────────────────────────────
    def _build_svr(s: dict) -> dict:
        return {
            "reqNum":   req_num,
            "sndRcvCl": s["snd_rcv_cl"],
            "svrTypCd": s["svr_typ_cd"],
            "sysNm":    s["sys_nm"],
            "hostNm":   s["host_nm"],
            "vIp":      s["v_ip"],
            "natIp":    s.get("nat_ip", ""),
            "etcIp":    s.get("etc_ip", ""),
            "osNm":     s.get("os_nm", ""),
            "company":  s.get("company", ""),
            "procSt":   "1",
        }

    def _build_if(i: dict) -> dict:
        if_typ  = i["if_typ_cd"]
        rnd_typ = i.get("round_typ_cd", "")
        # syncTypCd는 양방향(round_typ_cd=2)일 때만 의미 있음
        syn_typ = i.get("sync_typ_cd", "") if rnd_typ == "2" else ""
        return {
            "reqNum":             req_num,
            "eaiIfId":            "",
            "procSt":             "1",
            # 기본 정보
            "eaiIfNmKor":         i["eai_if_nm_kor"],
            "eaiIfNmEng":         i["eai_if_nm_eng"],
            "ifDesc":             i["if_desc"],
            "drctnCd":            i["drctn_cd"],
            "drctnNm":            _code_name("DRCTN_CD", i["drctn_cd"]),
            "ifTypCd":            if_typ,
            "ifTypNm":            _code_name("IF_TYP_CD", if_typ),
            "rcvOpCd":            i["rcv_op_cd"],
            "svcImpt":            i["svc_impt"],
            "rcvTr":              i.get("rcv_tr", ""),
            "eaiRmk":             i.get("eai_rmk", ""),
            # MID
            "sndMid":             i["snd_mid"],
            "rcvMid":             i["rcv_mid"],
            # MQ 관련 (FILE이면 빈값)
            "roundTypCd":         rnd_typ,
            "roundTypNm":         _code_name("ROUND_TYP_CD", rnd_typ),
            "syncTypCd":          syn_typ,
            "syncTypNm":          _code_name("SYNC_TYP_CD", syn_typ),
            # FILE 관련 (MQ이면 빈값)
            "fileIfTypCd":        i.get("file_if_typ_cd", ""),
            "fileIfTypNm":        _code_name("FILE_IF_TYP_CD", i.get("file_if_typ_cd", "")),
            "sndDir":             i.get("snd_dir", ""),
            "rcvDir":             i.get("rcv_dir", ""),
            "rcvShNm":            i.get("rcv_sh_nm", ""),
            "fileOpCode":         i.get("file_op_code", ""),
            # 송신 담당자
            "sndChrgrId1":        i["snd_chrgr_id1"],
            "sndChrgrNm1":        i["snd_chrgr_nm1"],
            "sndChrgrOrgNm1":     i["snd_chrgr_org_nm1"],
            "sndChrgrId2":        i.get("snd_chrgr_id2", ""),
            "sndChrgrNm2":        i.get("snd_chrgr_nm2") or None,
            "sndChrgrOrgNm2":     i.get("snd_chrgr_org_nm2") or None,
            "sndChrgrMngrId":     i["snd_chrgr_mngr_id"],
            "sndChrgrMngrNm":     i["snd_chrgr_mngr_nm"],
            "sndChrgrMngrOrgNm":  i["snd_chrgr_mngr_org_nm"],
            # 수신 담당자
            "rcvChrgrId1":        i["rcv_chrgr_id1"],
            "rcvChrgrNm1":        i["rcv_chrgr_nm1"],
            "rcvChrgrOrgNm1":     i["rcv_chrgr_org_nm1"],
            "rcvChrgrId2":        i.get("rcv_chrgr_id2", ""),
            "rcvChrgrNm2":        i.get("rcv_chrgr_nm2") or None,
            "rcvChrgrOrgNm2":     i.get("rcv_chrgr_org_nm2") or None,
            "rcvChrgrMngrId":     i["rcv_chrgr_mngr_id"],
            "rcvChrgrMngrNm":     i["rcv_chrgr_mngr_nm"],
            "rcvChrgrMngrOrgNm":  i["rcv_chrgr_mngr_org_nm"],
        }

    payload = {
        "reqNum":  req_num,
        "svrList": [_build_svr(s) for s in svr_list],
        "ifList":  [_build_if(i) for i in if_list],
    }

    # ── API 호출 ──────────────────────────────────────────────────────────────
    session = await get_session()
    resp = await session.post("/api/eai/regTemp", json=payload)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {
            "success": False,
            "message": body.get("rstMsg", "regTemp 저장 실패"),
            "validation_errors": [],
        }

    return {
        "success": True,
        "message": body.get("rstMsg", "정상처리 되었습니다."),
        "validation_errors": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. 인터페이스 신청 Step3 (최종 승인자 설정)
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def save_interface_request_step3(
    req_num: str,
    aprv_id: str,
) -> dict:
    """
    인터페이스 신청서의 Step3 최종 승인자를 설정하고 임시저장합니다.
    신청 흐름의 마지막 단계입니다 (step1 → regTemp → step3).

    승인자 userId는 search_chargr 툴로 조회할 수 있습니다.
    search_chargr 결과의 needs_confirmation이 True이면 사용자에게 어떤 담당자인지 확인 후 userId를 선택하세요.

    Args:
        req_num:  step1에서 발급된 요청서 고유번호 (예: "260310-0001")
        aprv_id:  최종 승인자 userId (search_chargr로 조회한 user_id 값)

    Returns:
        success (bool): 저장 성공 여부
        message (str):  처리 결과 메시지
    """
    session = await get_session()

    payload = {
        "reqNum": req_num,
        "aprvId": aprv_id,
    }

    resp = await session.post("/api/ifreq/reqInfo/step3", json=payload)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"success": False, "message": body.get("rstMsg", "step3 저장 실패")}

    return {"success": True, "message": body.get("rstMsg", "정상처리 되었습니다.")}


# ─────────────────────────────────────────────────────────────────────────────
# 6. 신청서 기초정보 조회 (Step1 상세)
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_interface_request_step1(req_num: str) -> dict:
    """
    신청서 고유번호(req_num)로 기초정보(제목, 신청목적, 날짜, 처리상태 등)를 조회합니다.

    Args:
        req_num: 요청서 고유번호 (예: "260310-0001")

    Returns:
        req_num (str): 요청서 번호
        req_title (str): 제목
        req_purp (str): 신청 목적
        req_rmk (str): 비고
        if_kind (str): 신청 종류 (EAI/EIGW/MCG)
        req_typ (str): 신청 유형 (NEW 등)
        proc_st (str): 처리 상태 코드
        proc_nm (str): 처리 상태명 (예: 임시저장)
        dvlp_aply_req_dt (str): 개발 반영 예정일
        oper_aply_req_dt (str): 운영 반영 예정일
        open_req_dt (str): 실 오픈일
        req_dtm (str): 신청 일시
        reqr_nm (str): 신청자 이름
        reqr_id (str): 신청자 ID
        aprv_id (str): 최종 승인자 ID
        aprv_nm (str): 최종 승인자 이름
        aprv_yn (str): 승인 여부 (Y/N)
    """
    session = await get_session()
    resp = await session.get("/api/ifreq/detail/step1", params={"reqNum": req_num})
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "step1 조회 실패")}

    m: dict = body.get("rstData", {}).get("ifReqMst", {})

    return {
        "req_num":          m.get("reqNum"),
        "req_title":        m.get("reqTitle"),
        "req_purp":         m.get("reqPurp"),
        "req_rmk":          m.get("reqRmk"),
        "if_kind":          m.get("ifKind"),
        "req_typ":          m.get("reqTyp"),
        "proc_st":          m.get("procSt"),
        "proc_nm":          m.get("procNm"),
        "dvlp_aply_req_dt": m.get("dvlpAplyReqDtF"),
        "oper_aply_req_dt": m.get("operAplyReqDtF"),
        "open_req_dt":      m.get("openReqDtF"),
        "req_dtm":          m.get("reqDtm"),
        "reqr_nm":          m.get("reqrNm"),
        "reqr_id":          m.get("reqrId"),
        "aprv_id":          m.get("aprvId"),
        "aprv_nm":          m.get("aprvNm"),
        "aprv_yn":          m.get("aprvYn"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. 신청서 서버 목록 조회 (EAI)
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_eai_interface_request_svr_list(req_num: str) -> dict:
    """
    EAI 인터페이스 신청서의 송/수신 서버 목록을 조회합니다.

    Args:
        req_num: 요청서 고유번호 (예: "260310-0001")

    Returns:
        total_count (int): 전체 서버 수
        sender_list (list): 송신 서버 목록 (snd_rcv_cl="S")
        receiver_list (list): 수신 서버 목록 (snd_rcv_cl="R")
            각 항목:
            - sys_nm (str): 시스템명
            - host_nm (str): Hostname
            - v_ip (str): VIP / 대표 IP
            - nat_ip (str): NAT IP
            - etc_ip (str): 추가 IP
            - os_nm (str): OS
            - company (str): 담당 회사
            - svr_typ_cd (str): 서버 유형 코드 (DEV/STG/PRD)
            - snd_rcv_cl (str): 송수신 구분 (S/R)
    """
    session = await get_session()
    resp = await session.get(
        "/api/eai/regSvrList",
        params={"reqNum": req_num, "procSt": "1"},
    )
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "서버 목록 조회 실패")}

    items: list = body.get("rstData", {}).get("searchList", [])

    def _parse_svr(s: dict) -> dict:
        return {
            "sys_nm":     s.get("sysNm"),
            "host_nm":    s.get("hostNm"),
            "v_ip":       s.get("vIp"),
            "nat_ip":     s.get("natIp"),
            "etc_ip":     s.get("etcIp"),
            "os_nm":      s.get("osNm"),
            "company":    s.get("company"),
            "svr_typ_cd": s.get("svrTypCd"),
            "snd_rcv_cl": s.get("sndRcvCl"),
        }

    sender_list   = [_parse_svr(s) for s in items if s.get("sndRcvCl") == "S"]
    receiver_list = [_parse_svr(s) for s in items if s.get("sndRcvCl") == "R"]

    return {
        "total_count":   len(items),
        "sender_list":   sender_list,
        "receiver_list": receiver_list,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. 신청서 인터페이스 목록 조회 (EAI)
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_eai_interface_request_if_list(req_num: str) -> dict:
    """
    EAI 인터페이스 신청서에 등록된 인터페이스 목록을 조회합니다.
    MQ/FILE 유형에 따라 유효한 필드가 다릅니다.

    Args:
        req_num: 요청서 고유번호 (예: "260310-0001")

    Returns:
        total_count (int): 전체 인터페이스 수
        mq_list (list): MQ 인터페이스 목록 (if_typ_cd="1")
        file_list (list): FILE 인터페이스 목록 (if_typ_cd="2")
            각 항목 공통 필드:
            - eai_if_nm_kor (str): 인터페이스명 (한글)
            - eai_if_nm_eng (str): 인터페이스명 (영문)
            - if_desc (str): 연동목적
            - if_typ_nm (str): 연동방식 (MQ/FILE)
            - drctn_nm (str): 연동방향
            - rcv_op_cd (str): 수신전문처리주기 코드
            - svc_impt (str): 장애 영향도
            - snd_mid (str): 송신 MID
            - rcv_mid (str): 수신 MID
            - rcv_tr (str): 수신TR (SWING만)
            - eai_rmk (str): 기타 요청사항
            - snd_chrgr_nm1 / snd_chrgr_org_nm1: 송신 운영담당자
            - snd_chrgr_mngr_nm / snd_chrgr_mngr_org_nm: 송신 업무담당 매니저
            - rcv_chrgr_nm1 / rcv_chrgr_org_nm1: 수신 운영담당자
            - rcv_chrgr_mngr_nm / rcv_chrgr_mngr_org_nm: 수신 업무담당 매니저
            MQ 전용: round_typ_nm, sync_typ_nm
            FILE 전용: file_if_typ_cd, snd_dir, rcv_dir, rcv_sh_nm, file_op_code
    """
    session = await get_session()
    resp = await session.get(
        "/api/eai/regIfList",
        params={"reqNum": req_num, "procSt": "1"},
    )
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "인터페이스 목록 조회 실패")}

    items: list = body.get("rstData", {}).get("searchList", [])

    def _parse_if(i: dict) -> dict:
        return {
            "eai_if_nm_kor":       i.get("eaiIfNmKor"),
            "eai_if_nm_eng":       i.get("eaiIfNmEng"),
            "if_desc":             i.get("ifDesc"),
            "if_typ_cd":           i.get("ifTypCd"),
            "if_typ_nm":           i.get("ifTypNm"),
            "drctn_nm":            i.get("drctnNm"),
            "rcv_op_cd":           i.get("rcvOpCd"),
            "svc_impt":            i.get("svcImpt"),
            "snd_mid":             i.get("sndMid"),
            "rcv_mid":             i.get("rcvMid"),
            "rcv_tr":              i.get("rcvTr"),
            "eai_rmk":             i.get("eaiRmk"),
            # MQ 전용
            "round_typ_nm":        i.get("roundTypNm"),
            "sync_typ_nm":         i.get("syncTypNm"),
            # FILE 전용
            "file_if_typ_cd":      i.get("fileIfTypCd"),
            "snd_dir":             i.get("sndDir"),
            "rcv_dir":             i.get("rcvDir"),
            "rcv_sh_nm":           i.get("rcvShNm"),
            "file_op_code":        i.get("fileOpCode"),
            # 담당자
            "snd_chrgr_nm1":         i.get("sndChrgrNm1"),
            "snd_chrgr_org_nm1":     i.get("sndChrgrOrgNm1"),
            "snd_chrgr_mngr_nm":     i.get("sndChrgrMngrNm"),
            "snd_chrgr_mngr_org_nm": i.get("sndChrgrMngrOrgNm"),
            "rcv_chrgr_nm1":         i.get("rcvChrgrNm1"),
            "rcv_chrgr_org_nm1":     i.get("rcvChrgrOrgNm1"),
            "rcv_chrgr_mngr_nm":     i.get("rcvChrgrMngrNm"),
            "rcv_chrgr_mngr_org_nm": i.get("rcvChrgrMngrOrgNm"),
        }

    mq_list   = [_parse_if(i) for i in items if i.get("ifTypCd") == "1"]
    file_list = [_parse_if(i) for i in items if i.get("ifTypCd") == "2"]

    return {
        "total_count": len(items),
        "mq_list":     mq_list,
        "file_list":   file_list,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 9. 신청서 최종 승인자 조회 (Step3 상세)
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_interface_request_step3(req_num: str) -> dict:
    """
    신청서의 최종 승인자 정보를 조회합니다.

    Args:
        req_num: 요청서 고유번호 (예: "260310-0001")

    Returns:
        aprv_id (str): 승인자 userId
        aprv_nm (str): 승인자 이름
        org_nm (str): 소속 조직
        ofc_lvl_nm (str): 직급
        email_addr (str): 이메일
        mbl_phon_num (str): 휴대폰 번호
    """
    session = await get_session()
    resp = await session.get("/api/ifreq/detail/step3", params={"reqNum": req_num})
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "step3 조회 실패")}

    a: dict = body.get("rstData", {}).get("aprvInfo", {})

    return {
        "aprv_id":      a.get("aprvId"),
        "aprv_nm":      a.get("aprvNm"),
        "org_nm":       a.get("orgNm"),
        "ofc_lvl_nm":  a.get("ofcLvlNm"),
        "email_addr":   a.get("emailAddr"),
        "mbl_phon_num": a.get("mblPhonNum"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 10. EIGW 외부 담당자 검색 (대외기관)
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def search_eigw_out_chargr(
    han_nm: str = "",
    inst_cd: str = "",
    inst_nm: str = "",
    size: int = 5,
) -> dict:
    """
    EIGW 인터페이스 신청 시 대외기관(외부) 담당자를 검색합니다. (EIGW 전용)
    결과 중 담당자의 user_id, inst_cd 등을 save_eigw_interface_request_regtemp에 사용합니다.

    Args:
        han_nm: 담당자 이름
        inst_cd: 대외기관 코드
        inst_nm: 대외기관 이름
        size: 최대 반환 수 (기본 5)

    Returns:
        total_count (int): 검색된 수
        out_chargr_list (list): 외부 담당자 목록
            - user_id (str): 사용자 ID (신청서 입력값으로 사용)
            - han_nm (str): 한글 이름
            - inst_cd (str): 소속 기관 코드 (신청서 입력값으로 사용)
            - inst_nm (str): 소속 기관 이름
            - ofc_lvl_cd (str): 직급 코드
            - email_addr (str): 이메일
            - mbl_phon_num (str): 휴대폰
        needs_confirmation (bool): True이면 여러 명이 조회되어 확인 필요
    """
    session = await get_session()

    resp = await session.get(
        "/api/eigw/chrgrInfo",
        params={
            "pageNo": 1, "pageCount": 0, "size": size,
            "hanNm": han_nm, "instCd": inst_cd, "instNm": inst_nm
        },
    )
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "외부 담당자 검색 실패")}

    items: list = body.get("rstData", {}).get("searchList", [])

    out_chargr_list = [
        {
            "user_id":      c.get("userId"),
            "han_nm":       c.get("hanNm"),
            "inst_cd":      c.get("instCd"),
            "inst_nm":      c.get("instNm"),
            "ofc_lvl_cd":   c.get("ofcLvlCd"),
            "email_addr":   c.get("emailAddr"),
            "mbl_phon_num": c.get("mblPhonNum"),
        }
        for c in items
    ]

    return {
        "total_count":        len(out_chargr_list),
        "out_chargr_list":    out_chargr_list,
        "needs_confirmation": len(out_chargr_list) > 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 11. EIGW 인터페이스 신청 regTemp (상세정보 임시저장)
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def save_eigw_interface_request_regtemp(
    req_num: str,
    online_list: list[dict],
    file_list: list[dict],
) -> dict:
    """
    EIGW 인터페이스 신청서의 온라인(ONLINE) 및 파일(FILE) 연동 상세정보를 임시저장합니다.
    (내부 동작으로 담당자 상세 정보는 userId와 chrgrTyp을 바탕으로 자동 조회되어 채워집니다.)

    ──────────────────────────────────────────────────────────
    [online_list] 온라인 연동 정보 (선택적 0개 이상)
    ──────────────────────────────────────────────────────────
        eigw_if_id      (str, 필수): 인터페이스 ID
        eigw_if_nm      (str, 필수): 인터페이스명
        inst_nm         (str, 필수): 대외기관명 (예: "AIA손해보험")
        inst_cd         (str, 필수): 대외기관코드 (예: "AIAA")
        eigw_rmk        (str, 선택): 기타 요청사항
        pgm_typ         (str, 필수): 프로그램 유형 - "CLIENT" | "SERVER"
        link_typ        (str, 필수): 연결 유형 - "DISCONN"(비연결형) | ...
        dev_real_ip     (str, 필수): 개발기 REAL IP
        dev_port        (str, 필수): 개발기 Port
        prod_real_ip    (str, 필수): 운영기 REAL IP
        prod_port       (str, 필수): 운영기 Port
        online_user_list(list, 필수): 담당자 목록 (최소 1명 이상)
            각 담당자 구조:
            - chrgr_typ (str, 필수): "in"(내부운영) 또는 "out"(대외기관)
            - user_id   (str, 필수): search_chargr 또는 search_eigw_out_chargr로 찾은 ID

    ──────────────────────────────────────────────────────────
    [file_list] 파일 연동 정보 (선택적 0개 이상)
    ──────────────────────────────────────────────────────────
        eigw_if_id      (str, 필수): 인터페이스 ID
        eigw_if_nm      (str, 필수): 인터페이스명
        inst_nm         (str, 필수): 대외기관명
        inst_cd         (str, 필수): 대외기관코드
        file_nm         (str, 필수): 파일명 (예: "SS01.{기관코드}.YYYYMMDD.dat")
        sr_flag         (str, 필수): 송수신 구분 - "S"(송신) | "R"(수신)
        eigw_rmk        (str, 선택): 기타 요청사항
        out_path        (str, 필수): 대외기관 파일경로
        id              (str, 필수): 계정 정보 ID
        pwd             (str, 필수): 계정 정보 PW
        dev_real_ip     (str, 필수): 개발기 REAL IP
        dev_port        (str, 필수): 개발기 Port
        prod_real_ip    (str, 필수): 운영기 REAL IP
        prod_port       (str, 필수): 운영기 Port
        file_user_list  (list, 필수): 담당자 목록 (최소 1명 이상)
            각 담당자 구조: (온라인과 동일)
            - chrgr_typ (str, 필수): "in"(내부운영) 또는 "out"(대외기관)
            - user_id   (str, 필수): 담당자 ID

    Args:
        req_num: step1 발급 요청서 번호
        online_list: EIGW 온라인 인터페이스 목록
        file_list: EIGW 파일 인터페이스 목록

    Returns:
        success (bool), message (str), validation_errors (list)
    """
    errors: list[str] = []
    if not online_list and not file_list:
        return {"success": False, "message": "online_list나 file_list 중 하나 이상은 필수입니다.", "validation_errors": []}

    # 기본 필드 검증 - online
    ONLINE_REQ = ("eigw_if_id", "eigw_if_nm", "inst_nm", "inst_cd", "pgm_typ", "link_typ",
                  "dev_real_ip", "dev_port", "prod_real_ip", "prod_port", "online_user_list")
    for idx, o in enumerate(online_list):
        for f in ONLINE_REQ:
            if not o.get(f):
                errors.append(f"online_list[{idx}].{f}: 필수 입력값입니다.")

    # 기본 필드 검증 - file
    FILE_REQ = ("eigw_if_id", "eigw_if_nm", "inst_nm", "inst_cd", "file_nm", "sr_flag",
                "out_path", "id", "pwd", "dev_real_ip", "dev_port", "prod_real_ip", "prod_port", "file_user_list")
    for idx, fld in enumerate(file_list):
        for f in FILE_REQ:
            if not fld.get(f):
                errors.append(f"file_list[{idx}].{f}: 필수 입력값입니다.")

    if errors:
        return {"success": False, "message": "입력 검증 실패", "validation_errors": errors}

    session = await get_session()

    # 내부 담당자 조회 캐시
    _in_cache = {}
    async def _get_in_user(uid: str):
        if uid in _in_cache: return _in_cache[uid]
        r = await session.get("/api/bizcomm/chrgr", params={"userId": uid, "size": 1})
        info = r.json().get("rstData", {}).get("chrgrInfo", [])
        if info:
            c = info[0]
            _in_cache[uid] = {
                "hanNm": c.get("hanNm", ""), "instNm": c.get("instNm", ""), "instCd": c.get("instCd", ""),
                "ofcLvlCd": c.get("ofcLvlCd", ""), "mblPhonNum": c.get("mblPhonNum", ""), "emailAddr": c.get("emailAddr", "")
            }
        else:
            _in_cache[uid] = {}
        return _in_cache[uid]

    # 외부 담당자 조회 캐시
    _out_cache = {}
    async def _get_out_user(uid: str, inst_cd: str, inst_nm: str):
        if uid in _out_cache: return _out_cache[uid]
        r = await session.get("/api/eigw/chrgrInfo", params={"size": 100, "instCd": inst_cd})
        clist = r.json().get("rstData", {}).get("searchList", [])
        match = next((c for c in clist if c.get("userId") == uid), None)
        if match:
            _out_cache[uid] = match
        else:
            # Fallback
            _out_cache[uid] = {
                "hanNm": uid, "instNm": inst_nm, "instCd": inst_cd, "ofcLvlCd": "", "mblPhonNum": "", "emailAddr": ""
            }
        return _out_cache[uid]

    async def _build_user(u: dict, inst_cd: str, inst_nm: str) -> dict:
        CTYP = u["chrgr_typ"]
        UID = u["user_id"]
        res = {"chrgrTyp": CTYP, "userId": UID}
        if CTYP == "in":
            d = await _get_in_user(UID)
            res.update({
                "instNm": d.get("instNm", "SK C&C"), "instCd": d.get("instCd", "SKCC"),
                "hanNm": d.get("hanNm", UID), "ofcLvlCd": d.get("ofcLvlCd", "9"),
                "mblPhonNum": d.get("mblPhonNum", "010-0000-0000"), "emailAddr": d.get("emailAddr", "")
            })
        else:
            d = await _get_out_user(UID, inst_cd, inst_nm)
            res.update({
                "instNm": d.get("instNm", inst_nm), "instCd": d.get("instCd", inst_cd),
                "hanNm": d.get("hanNm", UID), "ofcLvlCd": d.get("ofcLvlCd", ""),
                "mblPhonNum": d.get("mblPhonNum", ""), "emailAddr": d.get("emailAddr", "")
            })
        return res

    payload_online = []
    for o in online_list:
        ulist = []
        for u in o.get("online_user_list", []):
            ulist.append(await _build_user(u, o["inst_cd"], o["inst_nm"]))
        payload_online.append({
            "reqNum": req_num,
            "eigwIfId": o["eigw_if_id"],
            "eigwIfNm": o["eigw_if_nm"],
            "instNm": o["inst_nm"],
            "instCd": o["inst_cd"],
            "eigwType": "online",
            "procSt": "1",
            "eigwRmk": o.get("eigw_rmk", ""),
            "pgmTyp": o["pgm_typ"],
            "linkTyp": o["link_typ"],
            "devRealIp": o["dev_real_ip"],
            "devPort": o["dev_port"],
            "prodRealIp": o["prod_real_ip"],
            "prodPort": o["prod_port"],
            "onlineUserList": ulist
        })

    payload_file = []
    for f in file_list:
        ulist = []
        for u in f.get("file_user_list", []):
            ulist.append(await _build_user(u, f["inst_cd"], f["inst_nm"]))
        payload_file.append({
            "reqNum": req_num,
            "eigwIfId": f["eigw_if_id"],
            "eigwIfNm": f["eigw_if_nm"],
            "instNm": f["inst_nm"],
            "instCd": f["inst_cd"],
            "fileNm": f["file_nm"],
            "eigwType": "file",
            "procSt": "1",
            "srFlag": f["sr_flag"],
            "eigwRmk": f.get("eigw_rmk", ""),
            "outPath": f["out_path"],
            "id": f["id"],
            "pwd": f["pwd"],
            "devRealIp": f["dev_real_ip"],
            "devPort": f["dev_port"],
            "prodRealIp": f["prod_real_ip"],
            "prodPort": f["prod_port"],
            "fileUserList": ulist
        })

    payload = {
        "reqNum": req_num,
        "onlineList": payload_online,
        "fileList": payload_file,
    }

    resp = await session.post("/api/eigw/ifReqInfo", json=payload)
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"success": False, "message": body.get("rstMsg", "EIGW regTemp 저장 실패"), "validation_errors": []}

    return {"success": True, "message": body.get("rstMsg", "정상처리 되었습니다."), "validation_errors": []}


# ─────────────────────────────────────────────────────────────────────────────
# 12. EIGW 인터페이스 목록 조회
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_eigw_interface_request_if_list(req_num: str) -> dict:
    """
    EIGW 인터페이스 신청서에 등록된 온라인(ONLINE) 및 파일(FILE) 인터페이스 목록을 상세 조회합니다.

    Args:
        req_num: 요청서 고유번호 (예: "260310-0008")

    Returns:
        online_list (list): 온라인 인터페이스 목록
            - inst_nm/inst_cd: 대외기관 정보
            - pgm_typ: 프로그램 유형
            - link_typ_nm: 연결 유형
            - dev_real_ip/dev_port: 개발망 IP/Port
            - prod_real_ip/prod_port: 운영망 IP/Port
            - online_user_list: 등록된 담당자 목록
        file_list (list): 파일 인터페이스 목록
            - inst_nm/inst_cd: 대외기관 정보
            - file_nm: 파일명
            - sr_flag: 송수신 구분
            - out_path: 대외기관 파일경로
            - dev_real_ip/dev_port: 개발망 IP/Port
            - prod_real_ip/prod_port: 운영망 IP/Port
            - file_user_list: 등록된 담당자 목록
    """
    session = await get_session()
    resp = await session.get(
        "/api/eigw/ifReqList",
        params={"reqNum": req_num, "procSt": "1"},
    )
    resp.raise_for_status()
    body = resp.json()

    if body.get("rstCd") != "S":
        return {"error": body.get("rstMsg", "EIGW 인터페이스 목록 조회 실패")}

    data = body.get("rstData", {})
    o_list = data.get("onlineList", [])
    f_list = data.get("fileList", [])

    def _parse_online(o: dict) -> dict:
        return {
            "eigw_if_id": o.get("eigwIfId"),
            "eigw_if_nm": o.get("eigwIfNm"),
            "inst_nm":    o.get("instNm"),
            "inst_cd":    o.get("instCd"),
            "pgm_typ":    o.get("pgmTyp"),
            "pgm_typ_nm": o.get("pgmTypNm"),
            "link_typ":   o.get("linkTyp"),
            "link_typ_nm":o.get("linkTypNm"),
            "eigw_rmk":   o.get("eigwRmk"),
            "dev_real_ip":o.get("devRealIp"),
            "dev_port":   o.get("devPort"),
            "prod_real_ip":o.get("prodRealIp"),
            "prod_port":  o.get("prodPort"),
            "online_user_list": o.get("onlineUserList", [])
        }

    def _parse_file(f: dict) -> dict:
        return {
            "eigw_if_id": f.get("eigwIfId"),
            "eigw_if_nm": f.get("eigwIfNm"),
            "inst_nm":    f.get("instNm"),
            "inst_cd":    f.get("instCd"),
            "file_nm":    f.get("fileNm"),
            "sr_flag":    f.get("srFlag"),
            "out_path":   f.get("outPath"),
            "eigw_rmk":   f.get("eigwRmk"),
            "dev_real_ip":f.get("devRealIp"),
            "dev_port":   f.get("devPort"),
            "prod_real_ip":f.get("prodRealIp"),
            "prod_port":  f.get("prodPort"),
            "file_user_list": f.get("fileUserList", [])
        }

    return {
        "online_list": [_parse_online(o) for o in o_list],
        "file_list":   [_parse_file(f) for f in f_list],
    }
