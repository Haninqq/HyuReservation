"""사범대 스터디룸 예약: 학부/대학원별 허용 학과 목록."""

DEPTS_UNDERGRAD = [
    "교육학과",
    "교육공학과",
    "국어교육과",
    "영어교육과",
    "수학교육과",
    "응용미술교육과",
]

DEPTS_GRADUATE = [
    "교육공학과",
    "러닝사이언스학과",
    "응용미술학과",
    "한국어교육학과",
    "박물관교육학과",
    "다문화교육학과",
    "평생학습학과",
]


def allowed_depts(is_graduate: bool) -> list[str]:
    return DEPTS_GRADUATE if is_graduate else DEPTS_UNDERGRAD


def is_valid_dept(dept: str, is_graduate: bool) -> bool:
    d = (dept or "").strip()
    return bool(d) and d in allowed_depts(is_graduate)
